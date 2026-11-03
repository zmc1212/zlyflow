import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from backend.app.media_studio.services.episode_video_service import EpisodeVideoService, split_timeline_bytes, timeline_output_durations
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
from backend.app.media_studio.services.job_payload import slim_job_payload
from backend.app.media_studio.services.project_detail_service import BeatInputChangedError, ProjectDetailService
from backend.app.media_studio.services.video_preparation import (
    author_video_prompt, cache_video_prompt, prepare_video_keyframes, snapshot_prompt_inputs, video_prompt_signature,
)
from backend.tests.media_studio_test_h3_video import rich_prompt

VIDEO = "backend.app.media_studio.services.episode_video_service"
PREP = "backend.app.media_studio.services.video_preparation"


def shot(beat_id="b1", prompt=""):
    return {
        "beat_id": beat_id, "sequence": 1, "action": "沈砚在走廊停下", "camera": "固定中景",
        "speaker": "沈砚", "dialogue": "你好。", "h3_prompt": prompt,
        "reference_urls": ["https://example.test/character.png", "https://example.test/scene.png"],
        "character_references": [{"character_id": "c", "character_name": "沈砚", "look_id": "selected-look", "url": "https://example.test/character.png"}],
        "scene": "走廊", "scene_id": "s", "duration_sec": 8, "duration_seconds": 8, "frame_count": 192,
        "aspect_ratio": "9:16", "prompt_cache_base": {"action": "原文"},
    }


def payload(shots):
    return {"project_id": "p", "episode_id": "e", "aspect_ratio": "9:16", "source_shots": shots}


class VideoPreparationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_real_media_split_keeps_exact_frame_counts_and_color_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="zly-frame-boundary-test-") as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=red:size=32x32:rate=24:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=32000:duration=1",
                "-vf", "drawbox=color=green:t=fill:enable='gte(n,5)*lt(n,12)',drawbox=color=blue:t=fill:enable='gte(n,12)'",
                "-c:v", "libx264", "-c:a", "aac", str(source),
            ], capture_output=True, check=True, timeout=30)
            clips = split_timeline_bytes(source.read_bytes(), [5 / 24, 7 / 24, 12 / 24], frame_rate=24)
            for index, (clip, count) in enumerate(zip(clips, [5, 7, 12])):
                path = root / f"clip-{index}.mp4"
                path.write_bytes(clip)
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,nb_frames", "-of", "json", str(path)], capture_output=True, check=True, timeout=20)
                streams = json.loads(probe.stdout)["streams"]
                self.assertEqual(count, int(next(stream["nb_frames"] for stream in streams if stream["codec_type"] == "video")))
                self.assertTrue(any(stream["codec_type"] == "audio" for stream in streams))
                frame = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True, timeout=20).stdout
                pixel = frame[(16 * 32 + 16) * 3:(16 * 32 + 16) * 3 + 3]
                self.assertEqual(index, max(range(3), key=lambda channel: pixel[channel]))

    @patch.object(EpisodeVideoService, "_publish_timeline_result", return_value="https://example.test/movie.mp4")
    @patch(VIDEO + ".plan_timeline_chunks")
    def test_cached_render_retry_keeps_frame_contract_and_never_submits_again(self, plan, publish):
        shots = [shot(), shot("b2")]
        timeline = {"frameRate": 24, "segments": [{"id": "b1", "frameCount": 328}, {"id": "b2", "frameCount": 277}]}
        output = {"filename": "cached.mp4"}
        task = {**payload(shots), "render_scope": "selection", "shot_clip_urls": {"b1": "https://example.test/b1.mp4", "b2": "https://example.test/b2.mp4"},
                 "render_plan": {"chunks": [{"shot_ids": ["b1", "b2"], "status": "succeeded", "timeline": timeline, "output": output}]}}
        plan.return_value = [shots]
        definition = SimpleNamespace(supports_timeline=True, supports_multi_segment=True, max_segments=6, max_total_frames=1152, supports_segment_continuity=False, supports_audio_batch=True)
        comfy = Mock()
        result = EpisodeVideoService._run_timeline_job("job", task, comfy, "r2v", shots, definition, "workflow")
        self.assertEqual("https://example.test/movie.mp4", result)
        self.assertEqual(["https://example.test/b1.mp4", "https://example.test/b2.mp4"], [shot_["video_url"] for shot_ in shots])
        self.assertEqual(timeline, task["render_plan"]["chunks"][0]["timeline"])
        self.assertAlmostEqual(605 / 24, sum(timeline_output_durations(task, shots)))
        comfy.build_render_request.assert_not_called()
        comfy.submit_and_wait.assert_not_called()
        publish.assert_called_once_with("job", task, comfy, [output])

    def test_selection_splits_at_submitted_frame_boundaries_instead_of_requested_seconds(self):
        shots = [shot(), {**shot("b2"), "duration_sec": 11}, {**shot("b3"), "duration_sec": 11}]
        shots[0]["duration_sec"] = 13
        task = {**payload(shots), "render_scope": "selection", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "timeline": {"frameRate": 24, "segments": [{"id": "b1", "frameCount": 328}, {"id": "b2", "length": 277}]}},
            {"shot_ids": ["b3"], "timeline": {"frameRate": 24, "segments": [{"id": "b3", "frameCount": 277}]}},
        ]}}
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": []}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video", return_value={}), \
             patch(VIDEO + ".requests.get", return_value=SimpleNamespace(content=b"movie", raise_for_status=lambda: None)), \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a", b"b", b"c"]) as split, \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("a", "url-a"), ("b", "url-b"), ("c", "url-c")]):
            EpisodeVideoService._write_selected_beat_videos(task, shots, "https://example.test/merged.mp4")
        split.assert_called_once_with(b"movie", [328 / 24, 277 / 24, 277 / 24], frame_rate=24)
        self.assertAlmostEqual(605 / 24, shots[2]["outputStart"])
        self.assertAlmostEqual(882 / 24, task["render_plan"]["total_duration"])
        self.assertAlmostEqual(605 / 24, task["render_plan"]["chunks"][1]["output_start"])
        self.assertEqual([13, 11, 11], [s["duration_sec"] for s in shots])
        self.assertEqual([13, 11, 11], timeline_output_durations({}, shots))

    def test_job_list_exposes_group_progress_without_workflow_or_prompt_drafts(self):
        chunks = [{"status": "succeeded", "output": {"filename": "large-output"}}, {"status": "submitted", "timeline": "large-draft"}, {"status": "queued"}]
        source = {"render_plan": {"chunks": chunks}, "author_zh_draft": "private-draft"}
        slim = slim_job_payload(source)
        self.assertEqual({"total": 3, "completed": 1, "current": 2}, slim["render_progress"])
        self.assertNotIn("render_plan", slim)
        self.assertNotIn("author_zh_draft", slim)
        chunks[1]["status"] = chunks[2]["status"] = "succeeded"
        self.assertEqual({"total": 3, "completed": 3, "current": 3}, slim_job_payload(source)["render_progress"])
        self.assertNotIn("render_progress", slim_job_payload({}))
        self.assertNotIn("render_progress", slim_job_payload({"render_plan": {"chunks": None}}))

    def test_job_list_exposes_the_render_stage_of_every_beat(self):
        chunks = [
            {"shot_ids": ["b1"], "status": "succeeded"},
            {"shot_ids": ["b2"], "status": "submitted"},
            {"shot_ids": ["b3"], "status": "awaiting_refine"},
            {"shot_ids": ["b4"], "status": "queued"},
        ]
        slim = slim_job_payload({"render_scope": "selection", "beat_ids": ["b1", "b2", "b3", "b4"], "render_plan": {"chunks": chunks}})
        self.assertEqual({"b1": "succeeded", "b2": "running", "b3": "awaiting_refine", "b4": "queued"}, slim["shot_status"])
        self.assertEqual(["b1", "b2", "b3", "b4"], slim["beat_ids"])
        self.assertNotIn("shot_status", slim_job_payload({"render_scope": "selection"}))

    def test_each_finished_segment_publishes_its_shots_before_the_batch_ends(self):
        shots = [shot(), shot("b2"), shot("b3")]
        task = {**payload(shots), "render_scope": "selection", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
            {"shot_ids": ["b3"], "status": "queued"},
        ]}}
        comfy = Mock()
        comfy.download_output.return_value = b"segment"
        beats = [{"id": "b1", "action": "原文"}, {"id": "b2", "action": "原文"}, {"id": "b3", "action": "原文"}]
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": beats}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video",
                          return_value={"video_takes": [], "video_take_id": "take"}) as persist, \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"clip-1", b"clip-2"]) as split, \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("k1", "url-1"), ("k2", "url-2")]):
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
        split.assert_called_once_with(b"segment", [8.0, 8.0])
        self.assertEqual(2, persist.call_count)
        self.assertEqual(["url-1", "url-2"], [shots[0]["video_url"], shots[1]["video_url"]])
        self.assertFalse(shots[2].get("video_url"))
        self.assertEqual({"b1": "url-1", "b2": "url-2"}, task["shot_clip_urls"])
        self.assertTrue(task["render_plan"]["chunks"][0]["shots_published"])
        self.assertNotIn("shots_published", task["render_plan"]["chunks"][1])
        comfy.download_output.assert_called_once_with({"filename": "segment-1.mp4"})

    def test_early_shot_publish_never_overturns_a_succeeded_segment(self):
        shots = [shot(), shot("b2"), shot("b3")]
        task = {**payload(shots), "render_scope": "selection", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
            {"shot_ids": ["b3"], "status": "queued"},
        ]}}
        comfy = Mock()
        comfy.download_output.return_value = b"segment"
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": []}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video", side_effect=RuntimeError("七牛云写入失败")), \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a", b"b"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("k1", "url-1"), ("k2", "url-2")]):
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
        self.assertIn("七牛云写入失败", task["beat_update_warning"])
        self.assertNotIn("shot_clip_urls", task)
        self.assertNotIn("shots_published", task["render_plan"]["chunks"][0])

    def test_retry_of_a_legacy_batch_lands_shots_while_its_segments_are_reused(self):
        shots = [shot(), shot("b2"), shot("b3"), shot("b4")]
        task = {**payload(shots), "render_scope": "selection", "shot_clip_urls": {"b3": "url-3", "b4": "url-4"}, "render_plan": {"chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
            {"shot_ids": ["b3", "b4"], "status": "succeeded", "shots_published": True, "output": {"filename": "segment-2.mp4"}},
        ]}}
        landed: list[list[str]] = []

        def finalize(job_id, payload_, comfy, chunk_outputs):
            landed.append([str(item.get("video_url") or "") for item in shots])
            return "https://example.test/movie.mp4"

        comfy = Mock()
        comfy.download_output.return_value = b"segment-1"
        definition = SimpleNamespace(supports_timeline=True, supports_multi_segment=True, max_segments=6, max_total_frames=1152, supports_segment_continuity=False, supports_audio_batch=True)
        with patch(VIDEO + ".plan_timeline_chunks", return_value=[shots[:2], shots[2:]]), \
             patch.object(EpisodeVideoService, "_publish_timeline_result", side_effect=finalize) as publish, \
             patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": [{"id": item["beat_id"]} for item in shots]}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video", return_value={}), \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a", b"b"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("k1", "url-1"), ("k2", "url-2")]) as store:
            self.assertEqual("https://example.test/movie.mp4", EpisodeVideoService._run_timeline_job("job", task, comfy, "r2v", shots, definition, "workflow"))
        comfy.build_render_request.assert_not_called()
        comfy.submit_and_wait.assert_not_called()
        comfy.download_output.assert_called_once_with({"filename": "segment-1.mp4"})
        self.assertEqual(2, store.call_count)
        self.assertEqual({"b3": "url-3", "b4": "url-4", "b1": "url-1", "b2": "url-2"}, task["shot_clip_urls"])
        self.assertTrue(all(chunk["shots_published"] for chunk in task["render_plan"]["chunks"]))
        self.assertEqual([["url-1", "url-2", "url-3", "url-4"]], landed)
        publish.assert_called_once()

    def test_cached_segment_that_already_landed_is_not_uploaded_again(self):
        shots = [shot(), shot("b2"), shot("b3")]
        task = {**payload(shots), "render_scope": "selection", "shot_clip_urls": {"b1": "url-1", "b2": "url-2"}, "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "shots_published": True, "output": {"filename": "segment-1.mp4"}},
            {"shot_ids": ["b3"], "status": "succeeded", "output": {"filename": "segment-2.mp4"}},
        ]}}
        comfy = Mock()
        comfy.download_output.return_value = b"segment"
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": []}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video", return_value={}) as persist, \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", return_value=("k3", "url-3")) as store:
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
            comfy.download_output.assert_not_called()
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 1, shots, {})
        store.assert_called_once_with("video", ANY, b"a")
        self.assertEqual(1, persist.call_count)
        self.assertEqual("url-3", shots[2]["video_url"])
        self.assertTrue(task["render_plan"]["chunks"][1]["shots_published"])

    def test_single_segment_batch_defers_to_finalize_instead_of_uploading_twice(self):
        shots = [shot(), shot("b2")]
        task = {**payload(shots), "render_scope": "selection", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
        ]}}
        comfy = Mock()
        EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
        comfy.download_output.assert_not_called()
        self.assertNotIn("shot_clip_urls", task)

    def test_episode_scope_batch_lands_shots_while_later_segments_still_render(self):
        shots = [shot(), shot("b2"), shot("b3")]
        task = {**payload(shots), "render_scope": "episode", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
            {"shot_ids": ["b3"], "status": "submitted", "output": {"filename": "segment-2.mp4"}},
        ]}}
        comfy = Mock()
        comfy.download_output.return_value = b"segment"
        beats = [{"id": "b1"}, {"id": "b2"}, {"id": "b3"}]
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": beats}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video",
                          return_value={"video_takes": [], "video_take_id": "take"}) as persist, \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"clip-1", b"clip-2"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("k1", "url-1"), ("k2", "url-2")]):
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
        self.assertEqual(["url-1", "url-2"], [shots[0]["video_url"], shots[1]["video_url"]])
        self.assertFalse(shots[2].get("video_url"))
        self.assertEqual({"b1": "url-1", "b2": "url-2"}, task["shot_clip_urls"])
        self.assertTrue(task["render_plan"]["chunks"][0]["shots_published"])
        self.assertEqual("episode", persist.call_args.kwargs["scope"])

    def test_single_segment_episode_batch_publishes_because_finalize_only_makes_the_film(self):
        shots = [shot(), shot("b2")]
        task = {**payload(shots), "render_scope": "episode", "render_plan": {"mode": "timeline", "chunks": [
            {"shot_ids": ["b1", "b2"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
        ]}}
        comfy = Mock()
        comfy.download_output.return_value = b"segment"
        with patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": []}), \
             patch.object(EpisodeVideoService, "_persist_shot_original_video", return_value={}), \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a", b"b"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", side_effect=[("k1", "url-1"), ("k2", "url-2")]) as store:
            EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
        self.assertEqual(2, store.call_count)
        self.assertEqual({"b1": "url-1", "b2": "url-2"}, task["shot_clip_urls"])

    def test_whole_film_scopes_never_publish_shots_early(self):
        for scope in ("compose", "upscale"):
            with self.subTest(scope=scope):
                shots = [shot(), shot("b2")]
                task = {**payload(shots), "render_scope": scope, "render_plan": {"mode": "timeline", "chunks": [
                    {"shot_ids": ["b1"], "status": "succeeded", "output": {"filename": "segment-1.mp4"}},
                    {"shot_ids": ["b2"], "status": "queued"},
                ]}}
                comfy = Mock()
                EpisodeVideoService._publish_chunk_shots("job", task, comfy, 0, shots, {})
                comfy.download_output.assert_not_called()
                self.assertNotIn("shots_published", task["render_plan"]["chunks"][0])

    def test_episode_publish_lands_as_a_shot_take_so_history_still_lists_it(self):
        adopted = EpisodeVideoService._archive_and_adopt_beat_video(
            {"id": "b1", "video_url": "older.mp4"}, url="segment-shot.mp4", job_id="job", scope="episode",
        )
        self.assertEqual("segment-shot.mp4", adopted["video_url"])
        self.assertEqual(["older.mp4", "segment-shot.mp4"], [item["url"] for item in adopted["video_takes"]])
        self.assertEqual({"shot"}, {item["scope"] for item in adopted["video_takes"]})
        self.assertEqual(2, len(EpisodeVideoService._normalize_video_takes(adopted["video_takes"])))

    def test_final_merge_reuses_segment_urls_and_only_stores_the_missing_shot(self):
        shots = [shot(), shot("b2"), shot("b3")]
        shots[0]["video_url"] = "url-1"
        shots[1]["video_url"] = "url-2"
        task = {**payload(shots), "render_scope": "selection"}
        persisted = []

        def persist(_project, _episode, beat_id, url, **_kwargs):
            persisted.append((beat_id, url))
            return {"video_takes": [], "video_take_id": f"take-{beat_id}"}

        with patch.object(EpisodeVideoService, "_persist_shot_original_video", side_effect=persist), \
             patch.object(ProjectDetailService, "get_episode_detail", return_value={"beats": []}), \
             patch(VIDEO + ".requests.get", return_value=SimpleNamespace(content=b"movie", raise_for_status=lambda: None)), \
             patch(VIDEO + ".split_timeline_bytes", return_value=[b"a", b"b", b"c"]), \
             patch(VIDEO + ".QiniuService.get_config", return_value=SimpleNamespace(available=True)), \
             patch(VIDEO + ".QiniuService.store_bytes", return_value=("k3", "url-3")) as store:
            EpisodeVideoService._write_selected_beat_videos(task, shots, "https://example.test/merged.mp4", job_id="job")
        self.assertEqual(1, store.call_count)
        self.assertEqual([("b3", "url-3")], persisted)
        self.assertEqual(["url-1", "url-2", "url-3"], task["shot_video_urls"])

    def test_multi_segment_progress_advances_instead_of_restarting_every_segment(self):
        first = EpisodeVideoService._overall_render_progress(20, completed_units=0, total_units=4)
        middle = EpisodeVideoService._overall_render_progress(60, completed_units=1, total_units=4)
        tail = EpisodeVideoService._overall_render_progress(0, completed_units=3, total_units=4)
        done = EpisodeVideoService._overall_render_progress(100, completed_units=3, total_units=4)
        self.assertEqual([42, 62, 81, 95], [first, middle, tail, done])
        self.assertEqual(95, EpisodeVideoService._overall_render_progress(0, completed_units=8, total_units=8))
        self.assertEqual(67, EpisodeVideoService._overall_render_progress(50, completed_units=0, total_units=1))

    def test_missing_prompt_can_enqueue_without_calling_llm_in_request(self):
        captured = {}
        def insert(sql, params):
            captured.update(json.loads(params[3]))
        with patch.object(EpisodeVideoService, "apply_confirmed_video_resolution", side_effect=lambda p, opts: opts), \
             patch.object(EpisodeVideoService, "_assert_can_enqueue"), \
             patch.object(EpisodeVideoService, "_prepare_shots", return_value=[shot()]), \
             patch.object(ProjectDetailService, "get_episode_detail", return_value={"number": 1}), \
             patch.object(ProjectDetailService, "list_assets", return_value=[]), \
             patch.object(H3PromptBuilder, "ensure_available", return_value={"model": "test"}), \
             patch(VIDEO + ".ComfyService.get_config", return_value=SimpleNamespace(base_url="http://configured-remote")), \
             patch(VIDEO + ".ComfyVideoClient.preflight", return_value="minimax"), \
             patch(VIDEO + ".execute_sql", side_effect=insert), patch.object(EpisodeVideoService, "_submit_job"), \
             patch(PREP + ".LlmService.generate_h3_prompt") as llm:
            result = EpisodeVideoService.create_job("p", "e", beat_id="b1")
        self.assertEqual("queued", result["status"])
        self.assertEqual("h3", captured["prompt_mode"])
        self.assertFalse(captured["prepare_keyframes"])
        self.assertEqual("", captured["source_shots"][0]["h3_prompt"])
        llm.assert_not_called()

    @patch.object(EpisodeVideoService, "_set_state")
    @patch(PREP + ".cache_video_prompt", return_value=True)
    @patch(PREP + ".author_video_prompt")
    def test_retry_reuses_completed_prompts_after_later_prompt_failure(self, author, cache, state):
        first, second = shot(), shot("b2")
        ready = {**first, "h3_prompt": rich_prompt(), "h3_prompt_source": "generated"}
        author.side_effect = [(ready, {"h3_prompt": rich_prompt()}), RuntimeError("provider offline")]
        task = payload([first, second])
        with self.assertRaisesRegex(RuntimeError, "provider offline"):
            EpisodeVideoService._prepare_job_prompts("job", task)
        self.assertTrue(task["source_shots"][0]["h3_prompt"])
        self.assertEqual(1, task["prompt_generation_progress"]["completed"])
        author.reset_mock()
        author.side_effect = [({**second, "h3_prompt": rich_prompt()}, {"h3_prompt": rich_prompt()})]
        prompts = EpisodeVideoService._prepare_job_prompts("job", task)
        self.assertEqual(2, len(prompts))
        author.assert_called_once()
        self.assertEqual("b2", author.call_args.args[0]["beat_id"])

    @patch.object(EpisodeVideoService, "_set_state")
    @patch(PREP + ".author_video_prompt")
    @patch(PREP + ".prepare_video_keyframes")
    def test_saved_manual_prompt_and_default_asset_flow_do_not_generate_keyframes(self, plan, author, state):
        saved = {**shot(prompt="user-authored prompt"), "h3_prompt_source": "manual"}
        self.assertTrue(EpisodeVideoService._prepare_job_prompts("job", payload([saved])))
        plan.assert_not_called()
        author.assert_not_called()

    def test_asset_image_and_aspect_changes_invalidate_generated_cache(self):
        saved = shot(prompt=rich_prompt())
        saved["h3_prompt_input_signature"] = video_prompt_signature(saved)
        self.assertIsNotNone(EpisodeVideoService._workshop_prompt_for_shot(saved))
        changed = {**saved, "reference_urls": ["https://example.test/new-look.png"]}
        self.assertIsNone(EpisodeVideoService._workshop_prompt_for_shot(changed))
        self.assertIsNone(EpisodeVideoService._workshop_prompt_for_shot({**saved, "aspect_ratio": "16:9"}))
        self.assertIsNotNone(EpisodeVideoService._workshop_prompt_for_shot({**changed, "h3_prompt_source": "manual"}))

    @patch("backend.app.skill_packs.resolve_skill_pack_id", return_value="")
    def test_optional_plan_uses_panel_crops_in_the_actual_video_reference_order(self, pack):
        beat = {"id": "b", "sequence": 1, "action": "沈砚停下", "camera": "中景", "character_ids": ["c"], "scene_id": "s", "video_duration": "6",
                "triptych_url": "https://example.test/full-sheet.png", "triptych_panels": {"start": "https://example.test/start.png", "mid": "https://example.test/mid.png", "end": "https://example.test/end.png"}}
        assets = [
            {"id": "c", "name": "沈砚", "kind": "character", "extra": {"identities": [{"id": "look", "image_url": "https://example.test/look.png"}]}},
            {"id": "s", "name": "走廊", "kind": "scene", "extra": {"master_url": "https://example.test/scene.png"}},
        ]
        prepared = EpisodeVideoService._prepare_shots({"project_id": "p", "beats": [beat]}, assets)[0]
        self.assertEqual(5, len(prepared["reference_urls"]))
        self.assertNotIn(beat["triptych_url"], prepared["reference_urls"])
        self.assertEqual(prepared["reference_urls"], [item["url"] for item in prepared["ref_images"]])

    @patch(PREP + ".LlmService.generate_h3_prompt", return_value=rich_prompt())
    def test_auto_author_reads_real_images_in_video_upload_order(self, llm):
        source = shot()
        prepared, updates = author_video_prompt(source, payload([source]), Mock())
        info = llm.call_args.args[0]
        self.assertEqual(source["reference_urls"], [ref["url"] for ref in info["ref_images"]])
        self.assertEqual([1, 2], [ref["index"] for ref in info["ref_images"]])
        self.assertEqual("9:16", info["aspect_ratio"])
        self.assertEqual(video_prompt_signature(source), updates["h3_prompt_input_signature"])
        self.assertTrue(prepared["h3_prompt"])

    @patch(PREP + ".LlmService.generate_h3_prompt")
    def test_skill_pack_rebinding_retains_selected_look_scene_and_picture_labels(self, llm):
        from backend.app.skill_packs import HALF_NARRATED_PACK_ID, get_pack
        from backend.app.skill_packs.handlers import bind_r2v_slot_images, build_timestamped_zh_author_user, collect_zh_author_image_urls

        source = {**shot(), "skill_pack_id": HALF_NARRATED_PACK_ID}
        assets = [
            {"id": "c", "name": "沈砚", "kind": "character", "extra": {"identities": [
                {"id": "old-look", "image_url": "https://example.test/old.png"},
                {"id": "selected-look", "image_url": source["reference_urls"][0]},
            ]}},
            {"id": "s", "name": "走廊", "kind": "scene", "extra": {"master_url": source["reference_urls"][1]}},
        ]
        def generate(info):
            recipe = get_pack(HALF_NARRATED_PACK_ID)
            slots = bind_r2v_slot_images(recipe, info, assets)
            self.assertEqual(source["reference_urls"], [slot["url"] for slot in slots])
            self.assertEqual(source["reference_urls"], collect_zh_author_image_urls(recipe, info, assets))
            user = build_timestamped_zh_author_user(recipe, info, assets, beat_info=info)
            self.assertIn("<Picture 1>", user)
            self.assertIn("<Picture 2>", user)
            return rich_prompt()
        llm.side_effect = generate
        prepared, updates = author_video_prompt(source, payload([source]), Mock())
        self.assertTrue(prepared["h3_prompt"])

    @patch.object(EpisodeVideoService, "_set_state")
    @patch(PREP + ".author_video_prompt")
    def test_failed_author_keeps_drafts_for_diagnosis_without_submitting_video(self, author, state):
        from backend.app.media_studio.services.llm_service import DualShotAuthorError
        author.side_effect = DualShotAuthorError("missing picture", errors=["missing <Picture 1>"], zh_prompt="中文草稿", en_prompt="英文草稿")
        task = payload([shot()])
        with self.assertRaisesRegex(DualShotAuthorError, "missing picture"):
            EpisodeVideoService._prepare_job_prompts("job", task)
        self.assertEqual("中文草稿", task["author_zh_draft"])
        self.assertEqual("英文草稿", task["author_en_draft"])
        self.assertFalse(task["source_shots"][0]["h3_prompt"])

    @patch("backend.app.media_studio.services.project_detail_service.transaction_cursor")
    def test_late_prompt_cannot_overwrite_new_prose_or_manual_prompt(self, transaction):
        cursor = transaction.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"data_json": json.dumps({"beats": [{"id": "b1", "action": "新正文", "h3_prompt": "手写稿"}]})}
        with self.assertRaises(BeatInputChangedError):
            ProjectDetailService._update_episode_beat_atomic("p", "e", "b1", {"h3_prompt": "旧生成稿"}, expected_fields={"action": "原文"})
        self.assertEqual(1, cursor.execute.call_count)
        self.assertFalse(cache_video_prompt(shot(), payload([]), {"h3_prompt": "旧生成稿"}))

    @patch(PREP + ".time.sleep")
    @patch("backend.app.media_studio.services.storyboard_image_service.StoryboardImageService.enqueue", return_value={"job_id": "frames"})
    @patch.object(ProjectDetailService, "get_job", side_effect=[{"status": "running"}, {"status": "completed"}])
    @patch.object(ProjectDetailService, "get_episode_detail")
    def test_optional_keyframes_wait_for_one_job_then_continue(self, detail, get, enqueue, sleep):
        beat = {"id": "b1", "action": "原文"}
        detail.side_effect = [{"beats": [beat]}, {"beats": [{**beat, "triptych_url": "https://example.test/frames.png"}]}]
        source = {**shot(), "prompt_cache_base": snapshot_prompt_inputs(beat)}
        task = payload([source])
        result = prepare_video_keyframes(source, task, Mock())
        self.assertTrue(result["triptych_url"])
        enqueue.assert_called_once()
        self.assertEqual("frames", task["keyframe_jobs"]["b1"])
        self.assertEqual(2, get.call_count)

    @patch(PREP + ".author_video_prompt", side_effect=RuntimeError("prompt provider unavailable"))
    @patch(VIDEO + ".occupy_gpu")
    @patch(VIDEO + ".ComfyVideoClient")
    @patch(VIDEO + ".execute_sql")
    @patch(VIDEO + ".query_one")
    def test_prompt_failure_never_acquires_gpu_or_submits_video(self, query, execute, comfy, gpu, author):
        task = {**payload([shot()]), "comfy_base_url": "http://configured-remote", "render_scope": "shot"}
        query.side_effect = lambda *args: {"payload_json": json.dumps(task)}
        def checkpoint(_job, value, stage, progress):
            task.update(copy.deepcopy(value)); task["runtime_stage"] = stage
        with patch.object(EpisodeVideoService, "_set_state", side_effect=checkpoint):
            EpisodeVideoService._run_job("job")
        gpu.assert_not_called()
        comfy.return_value.upload_image.assert_not_called()
        self.assertEqual("prompt_generation", task["runtime_stage"])
        self.assertIn("prompt provider unavailable", str(execute.call_args))


if __name__ == "__main__":
    unittest.main()
