from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from backend.app.comfy_service import ComfyService, ComfyCancelled, interpret_comfy_progress, COMFY_PREPARE_STAGE
from backend.app.config import Settings
from backend.app.models import JobMode
from backend.app.scail2_workflow import (
    SCAIL_DEFAULT_PROMPT, SCAIL_MODELS, DPO_LORA, LIGHT_LORA,
    build_scail2_workflow, prepare_scail_inputs, probe_scail_canvas, scail_missing_message, subject_points,
    scail_chunk_plan, resolve_scail_video_options,
    subject_prompt_points,
)
from backend.app.workflow_registry import SCAIL2_OPTION_SCHEMA, is_local_comfy_job, normalize_options, workflow_for
from backend.tests import test_h3_motion_transfer as fixtures

MODE = JobMode.SCAIL2_REPLACEMENT
POINTS = json.dumps([{"x": 0.3, "y": 0.4}, {"x": 0.8, "y": 0.5, "exclude": True}])


def options(**extra):
    return normalize_options(MODE, {"source_points": POINTS, "reference_points": POINTS, "seed": 42, **extra})


def graph(**extra):
    return build_scail2_workflow("character.png", "motion.mp4", "first.png", "",
                                 width=512, height=896, source_coords=('[{"x":156,"y":330}]', '[]'),
                                 reference_coords=('[{"x":150,"y":290}]', '[]'), seed=42, **extra)


class ScailContractTests(unittest.TestCase):
    def test_registry_defaults_layers_and_reproducible_snapshot(self):
        definition = workflow_for(MODE)
        self.assertEqual(definition.reference_kind(2), "video")
        self.assertEqual(definition.reference_labels, ("角色形象图", "动作参考视频"))
        self.assertTrue(definition.hidden_from_catalog)  # dedicated subject picker required
        self.assertTrue(is_local_comfy_job(MODE))
        for field in SCAIL2_OPTION_SCHEMA["properties"].values():
            self.assertIn(field["ui_group"], {"primary", "advanced", "internal"})
        self.assertEqual([k for k, v in SCAIL2_OPTION_SCHEMA["properties"].items() if v["ui_group"] == "primary"], ["duration", "subject_count", "preserve_audio"])
        normalized = options()
        self.assertEqual(normalized, normalize_options(MODE, normalized))
        self.assertEqual((normalized["fps"], normalized["length"], normalized["steps"]), (16, 81, 6))
        self.assertTrue(normalized["preserve_audio"])
        self.assertEqual(normalized["seed"], 42)
        for override in [{"steps": 20}, {"fps": 24}, {"duration": "10s"}, {"unknown": 1}]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                options(**override)

    def test_ambiguous_invalid_and_nonfinite_selections_are_rejected(self):
        for points in ['', '[]', '{}', '[{"x":true,"y":0.5}]', '[{"x":NaN,"y":0.5}]',
                       '[{"x":1.1,"y":0}]', '[{"x":0,"y":0,"exclude":true}]']:
            with self.subTest(points=points), self.assertRaises(ValueError):
                subject_points(points, "视频首帧")
        with self.assertRaisesRegex(ValueError, "点击"):
            normalize_options(MODE, {})

    def test_full_video_uses_chained_anchors_and_trims_only_duplicates_and_padding(self):
        self.assertEqual(scail_chunk_plan(242), [{"start": 0, "length": 81}, {"start": 76, "length": 81}, {"start": 152, "length": 81}, {"start": 228, "length": 17}])
        with patch("backend.app.motion_transfer_media.probe_video", return_value=fixtures.VideoProbe(540, 960, 30, 15.116009)):
            window = resolve_scail_video_options(Path("source.mp4"), "full")
        self.assertEqual((window["length"], window["conditioning_length"], window["chunk_count"]), (242, 245, 4))
        g = build_scail2_workflow("r.png", "v.mp4", "f.png", "", width=512, height=896,
                                 source_coords=("[]", "[]"), reference_coords=("[]", "[]"), seed=42, length=242,
                                 source_coords_by_subject=[("[]", "[]"), ("[]", "[]")], reference_coords_by_subject=[("[]", "[]"), ("[]", "[]")])
        self.assertEqual(g["18"]["inputs"], {"masks.mask0": ["6", 0], "masks.mask1": ["17", 0]})
        self.assertEqual(g["10"]["inputs"]["sort_by"], "none")
        self.assertEqual(g["8"]["inputs"]["max_objects"], 2)
        self.assertEqual(g["67"]["inputs"]["mask"], ["19", 0])
        self.assertEqual(g["140"]["inputs"]["previous_frames"], ["44", 0])
        self.assertEqual(g["240"]["inputs"]["video_frame_offset"], ["140", 3])
        self.assertEqual(g["340"]["inputs"]["length"], 17)
        self.assertEqual(g["350"]["inputs"]["batch_index"], 5)
        self.assertEqual(g["2000"]["inputs"]["length"], 242)
        self.assertEqual(g["45"]["inputs"]["audio"], ["2", 1])
        self.assertEqual(g["46"]["inputs"]["video"], ["45", 0])

    def test_subject_pairing_is_required_for_both_images(self):
        with self.assertRaises(ValueError):
            options(subject_count="2")
        both = json.dumps([{"x":0.3,"y":0.4,"subject":0},{"x":0.8,"y":0.5,"subject":1}])
        result=options(subject_count="2", source_points=both, reference_points=both)
        self.assertEqual([p["subject"] for p in json.loads(result["source_points"])], [0,1])
        for seconds in [0.5,30.1]:
            with patch("backend.app.motion_transfer_media.probe_video", return_value=fixtures.VideoProbe(540,960,30,seconds)), self.assertRaises(ValueError):
                resolve_scail_video_options(Path("source.mp4"), "full")

    def test_detail_points_for_one_person_do_not_flood_other_person_with_negatives(self):
        own = [{"x": .2, "y": .4, "exclude": False, "subject": 0},
               {"x": .1, "y": .2, "exclude": True, "subject": 0}]
        other = [{"x": .8, "y": y, "exclude": False, "subject": 1} for y in (.3, .5, .7)]
        first = subject_prompt_points(own + other[:1], 0)
        self.assertEqual(subject_prompt_points(own + other, 0), first)
        self.assertEqual(len(first), 3)
        self.assertEqual(first[:2], own)  # explicit exclusion is retained
        self.assertTrue(first[-1]["exclude"])
        self.assertTrue(all(not p["exclude"] for p in other))
        self.assertEqual(sum(not p["exclude"] for p in subject_prompt_points(own + other, 1)), 3)

    def test_turbo_sigma_schedule_matches_official_template_in_all_segments(self):
        g = graph(length=242)
        for offset in (0, 100, 200, 300):
            # Regression: the sampler shift must not override the turbo sigma
            # source; the official template keeps these model inputs separate.
            self.assertEqual(g[str(42 + offset)]["inputs"]["model"], ["32", 0])
            self.assertEqual(g[str(43 + offset)]["inputs"]["model"], ["33", 0])

    def test_original_rgb_and_tracked_identity_drive_replacement(self):
        g = graph()
        self.assertEqual(g["40"]["inputs"]["pose_video"], ["2", 0])
        self.assertEqual(g["40"]["inputs"]["pose_video_mask"], ["10", 0])
        self.assertTrue(g["40"]["inputs"]["replacement_mode"])
        self.assertEqual(g["8"]["inputs"]["initial_mask"], ["6", 0])
        self.assertEqual(g["8"]["inputs"]["max_objects"], 1)
        self.assertEqual(g["38"]["inputs"]["image"], ["3", 0])
        self.assertEqual(g["40"]["inputs"]["reference_image"], ["3", 0])
        self.assertEqual(g["23"]["inputs"]["mask"], ["21", 0])
        self.assertEqual(g["35"]["inputs"]["text"], SCAIL_DEFAULT_PROMPT)
        self.assertEqual(g["45"]["inputs"]["audio"], ["2", 1])
        self.assertNotIn("audio", graph(preserve_audio=False)["45"]["inputs"])
        info = {node["class_type"]: {"input": {"required": {}}} for node in g.values()}
        for kind, (field, name) in SCAIL_MODELS.items():
            info[kind]["input"]["required"][field] = [[name]]
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"] = [[DPO_LORA, LIGHT_LORA]]
        self.assertIsNone(scail_missing_message(info, g))
        info.pop("SAM3_VideoTrack")
        self.assertIn("SAM3_VideoTrack", scail_missing_message(info, g))

    def test_native_input_previews_do_not_feed_video_and_survive_all_continuations(self):
        g = graph(length=242)
        self.assertEqual(g["61"]["inputs"]["images"], ["3", 0])
        self.assertEqual(g["62"]["inputs"]["images"], ["23", 0])
        self.assertEqual(g["63"]["inputs"]["images"], ["10", 1])
        self.assertEqual(g["60"]["inputs"], {"image": ["10", 0], "batch_index": 0, "length": 1})
        for offset in (0, 100, 200, 300):
            self.assertEqual(g[str(40 + offset)]["inputs"]["reference_image"], ["3", 0])
            self.assertEqual(g[str(40 + offset)]["inputs"]["reference_image_mask"], ["10", 1])
        self.assertEqual(g["46"]["class_type"], "SaveVideo")
        self.assertEqual(g["45"]["inputs"]["images"], ["2000", 0])
        self.assertEqual(g["65"]["inputs"]["mask"], ["7", 0])
        self.assertNotIn("67", g)

    def test_diagnostic_images_are_preparation_and_native_sampler_reports_sampling(self):
        g = graph()
        tick = interpret_comfy_progress({"type": "executing", "data": {"prompt_id": "p", "node": "61"}}, "p", g, "动作迁移")
        self.assertEqual(tick.stage, COMFY_PREPARE_STAGE)
        self.assertEqual(tick.progress, 12)
        tick = interpret_comfy_progress({"type": "progress", "data": {"prompt_id": "p", "node": "43", "value": 3, "max": 6}}, "p", g, "动作迁移")
        self.assertEqual((tick.stage, tick.progress), ("动作迁移", 50))

    def test_service_prepares_inputs_and_recovers_without_resubmission(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ComfyService(Settings(workspace_dir=Path(directory)))
            service.upload_image = Mock(return_value="uploaded.png")
            service.upload_video = Mock(return_value="uploaded.mp4")
            service.object_info = Mock(return_value={})
            history = {"outputs": {"46": {"images": [{"filename": "result.mp4", "subfolder": "video", "type": "output"}]}}}
            service.run_workflow = Mock(return_value=history)
            service.download = Mock()
            service.output_payload = Mock(return_value={"kind": "video", "path": "result.mp4"})
            prepared = {"image": Path("character.png"), "video": Path("motion.mp4"), "first": Path("first.png"),
                        "width": 512, "height": 896, "source_coords": ("[]", "[]"), "reference_coords": ("[]", "[]")}
            with patch("backend.app.comfy_service.prepare_scail_inputs", return_value=prepared), patch("backend.app.comfy_service.scail_missing_message", return_value=None):
                result = service.run(MODE, ["character.png", "motion.mp4"], "跳舞", "", None, options(), Mock(), Mock(), Mock())
            self.assertEqual(result[0]["kind"], "video")
            self.assertEqual(service.upload_video.call_count, 1)
            self.assertEqual(service.upload_image.call_count, 2)
            self.assertEqual(service.run_workflow.call_args.args[0]["43"]["inputs"]["noise_seed"], 42)
            service.run_workflow.reset_mock()
            service.completed_outputs(MODE, history)
            service.run_workflow.assert_not_called()
            self.assertEqual(service.download.call_args.args[0]["filename"], "result.mp4")
            self.assertFalse(list(service.settings.staging_dir.iterdir()))
            with self.assertRaises(ComfyCancelled):
                service.run(MODE, ["character.png", "motion.mp4"], "", "", None, options(), Mock(), Mock(), Mock(), is_cancelled=lambda: True)


class ScailApiTests(unittest.TestCase):
    setUp = fixtures.MotionTransferApiTests.setUp
    files = fixtures.MotionTransferApiTests.files

    def create(self, extra=None):
        with patch.object(self.main, "probe_scail_canvas", return_value=(512, 896)):
            return self.client.post("/api/jobs", data={"mode": MODE.value, "prompt": "", "options": json.dumps({"source_points": POINTS, "reference_points": POINTS, "seed": 42, **(extra or {})})}, files=self.files(), headers=self.headers)

    def test_real_multipart_task_snapshot_and_visibility(self):
        response = self.create()
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job["mode"], MODE.value)
        self.assertEqual(job["prompt"], SCAIL_DEFAULT_PROMPT)
        self.assertEqual(job["rounds"][0]["options"], job["options"])
        self.assertEqual((job["options"]["width"], job["options"]["height"]), (512, 896))
        self.assertEqual(json.loads(job["options"]["source_points"])[0]["x"], 0.3)
        runtime = {p["name"]: p for p in job["request_parameters"]}
        self.assertEqual(runtime["options.source_points"]["visibility"], "internal")
        self.assertEqual(runtime["options.preserve_audio"]["visibility"], "primary")
        self.assertEqual([r["kind"] for r in job["references"]], ["image", "video"])
        self.worker.enqueue.assert_awaited_once_with(job["id"])

    def test_missing_subject_cannot_queue_or_leave_uploads(self):
        response = self.create({"source_points": ""})
        self.assertEqual(response.status_code, 422)
        self.worker.enqueue.assert_not_awaited()
        self.assertFalse(list(self.settings.uploads_dir.rglob("*.mp4")))

    def test_full_two_person_multipart_snapshot_is_ready_for_worker_without_external_processing(self):
        self.probe.return_value = fixtures.VideoProbe(540,960,30,15.116009)
        points=json.dumps([{"x":0.3,"y":0.4,"subject":0},{"x":0.8,"y":0.5,"subject":1}])
        response=self.create({"duration":"full","subject_count":"2","source_points":points,"reference_points":points})
        self.assertEqual(response.status_code,202,response.text)
        job=response.json()
        self.assertEqual((job["options"]["length"],job["options"]["conditioning_length"],job["options"]["chunk_count"]),(242,245,4))
        self.assertEqual(job["rounds"][0]["options"],job["options"])
        self.worker.enqueue.assert_awaited_once_with(job["id"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration")
class ScailMediaTests(unittest.TestCase):
    def test_frame_grid_letterbox_points_and_source_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            video = p / "source.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x112:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "5.2", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True, capture_output=True)
            image = p / "image.png"
            Image.new("RGB", (100, 100), "blue").save(image)
            result = prepare_scail_inputs(image, video, p / "prepared", options())
            self.assertEqual((result["width"], result["height"]), (512, 896))
            self.assertEqual(probe_scail_canvas(video), (512, 896))
            self.assertEqual(json.loads(result["source_coords"][0]), [{"x": 154, "y": 358}])
            self.assertEqual(json.loads(result["reference_coords"][0]), [{"x": 154, "y": 397}])
            data = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(result["video"])]))
            streams = {s["codec_type"]: s for s in data["streams"]}
            self.assertEqual(streams["video"]["nb_frames"], "81")
            self.assertEqual(streams["video"]["r_frame_rate"], "16/1")
            self.assertIn("audio", streams)
            with Image.open(result["image"]) as reference:
                self.assertEqual(reference.getpixel((0, 0)), (0, 0, 0))
                self.assertEqual(reference.getpixel((256, 448)), (0, 0, 255))


if __name__ == "__main__":
    unittest.main()
