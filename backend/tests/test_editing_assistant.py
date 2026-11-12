from __future__ import annotations

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.director_assistant.editing import (
    _needs_chinese_translation,
    arrange_videos,
    make_subtitle_translator,
    place_audio_subtitles,
    place_subtitles,
    rebuild_cut,
    subtitle_translation_targets,
    translate_subtitles,
)
from backend.app.director_assistant.repository import AssistantConflict, AssistantNotFound, dumps
from backend.app.director_assistant.service import AssistantService
from backend.app.media_studio.routers.smart_edit_router import register_smart_edit_routes
from backend.app.media_studio.services.smart_edit_document import empty_document, validate_document
from backend.app.media_studio.services.smart_edit_service import document_id
from backend.app.storage import JobStore


def video(key, beat=None, duration=2.09):
    return {"id": key, "kind": "video", "name": key, "url": f"https://media.example/{key}.mp4", "duration": duration, **({"beat_id": beat} if beat else {})}


def audio(key, beat, duration=6):
    return {"id": key, "kind": "audio", "name": key, "url": f"https://media.example/{key}.mp3", "duration": duration, "beat_id": beat}


def beats():
    return [
        {"id": "b1", "sequence": 1, "heading": "开场", "duration_sec": 4,
         "dubbing_lines": [{"text": "你终于来了。", "duration_sec": 1.2}, {"text": "我等你很久了。", "duration_sec": 1.4}]},
        {"id": "b2", "sequence": 2, "heading": "追逐", "action": "他冲进雨里追逐列车", "duration_sec": 6},
        {"id": "b3", "sequence": 3, "heading": "真相", "action": "冲突爆发，真相揭晓", "duration_sec": 5,
         "dubbing_lines": [{"text": "一切都结束了。", "duration_sec": 1.8}]},
        {"id": "b4", "sequence": 4, "heading": "过渡", "action": "他在走廊里缓慢地走过", "duration_sec": 10},
    ]


class ArrangeVideosTests(unittest.TestCase):
    def test_hook_cut_requires_an_explicit_user_strategy(self):
        with self.assertRaises(ValueError):
            AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [{"name": "propose_edit", "arguments": {"operation": "hook_cut"}}]}))
        audio = AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [{"name": "propose_edit", "arguments": {"operation": "audio_subtitle"}}]}))
        self.assertEqual(audio.tool_calls[0].arguments, {"operation": "audio_subtitle"})
        parsed = AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [{"name": "propose_edit", "arguments": {"operation": "hook_cut", "strategy": "conflict_3s"}}]}))
        self.assertEqual(parsed.tool_calls[0].arguments["strategy"], "conflict_3s")
        with self.assertRaises(ValueError):
            AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [{"name": "propose_edit", "arguments": {"operation": "quick_cut", "strategy": "trailer"}}]}))

    def test_model_tool_tags_use_the_same_validated_protocol(self):
        parsed = AssistantService._parse('<tool_call>editor_read</tool_call><tool_call>propose_edit<param_key>operation</param_key><param_value>video_arrange</param_value></tool_call>')
        self.assertEqual([c.name for c in parsed.tool_calls], ["editor_read", "propose_edit"])
        self.assertEqual(parsed.tool_calls[1].arguments, {"operation": "video_arrange"})
        for raw in ['<tool_call>shell</tool_call>', '<tool_call>propose_edit<param_key>project_id</param_key><param_value>other</param_value></tool_call>', '<tool_call>editor_read</tool_call>混入正文', '<!DOCTYPE x><tool_call>editor_read</tool_call>']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): AssistantService._parse(raw)

    def test_subtitle_translate_is_a_valid_propose_edit_operation(self):
        parsed = AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [
            {"name": "propose_edit", "arguments": {"operation": "subtitle_translate"}}]}))
        self.assertEqual(parsed.tool_calls[0].arguments, {"operation": "subtitle_translate"})
        with self.assertRaises(ValueError):
            AssistantService._parse(json.dumps({"text": "开始", "tool_calls": [
                {"name": "propose_edit", "arguments": {"operation": "subtitle_translate", "strategy": "trailer"}}]}))

    def test_adopted_order_imports_duplicates_and_existing_lanes(self):
        doc = empty_document()
        old, second, first, imported = video("old", "b1"), video("second", "b2"), video("first", "b1"), video("imported")
        doc["assets"] = [old, imported, second, first]
        doc["assets"].append({**video("sound"), "kind": "audio"})
        doc["clips"] = [{"id": "existing", "track": "video", "asset_id": "old", "start": 0, "duration": 1, "speed": 2},
                        {"id": "caption", "track": "text", "start": 0, "duration": 10, "text": "原字幕"},
                        {"id": "voice", "track": "audio", "asset_id": "sound", "start": 0, "duration": 1}]
        doc = validate_document(doc); before = copy.deepcopy(doc)
        plan = arrange_videos(doc, [first, second, {**imported, "id": "duplicate"}])
        self.assertEqual([i["asset_id"] for i in plan["items"]], ["second", "duplicate"])
        self.assertEqual(plan["append_at"], 1)
        self.assertEqual(plan["document"]["clips"][:3], doc["clips"])
        self.assertEqual(doc, before)
        self.assertEqual(plan["skipped_count"], 2)

    def test_free_sequence_uses_library_order_and_no_images_or_audio(self):
        doc = empty_document()
        doc["settings"]["fps"] = 30
        doc["assets"] = [video("10"), {**video("image"), "kind": "image"}, video("2", "b2"), {**video("audio"), "kind": "audio"}]
        plan = arrange_videos(doc, [], free=True)
        self.assertEqual([i["name"] for i in plan["items"]], ["10", "2"])
        self.assertAlmostEqual(plan["items"][0]["duration"], 62 / 30)
        for clip in plan["document"]["clips"]:
            self.assertEqual((clip["speed"], clip["in_point"], clip["muted"], clip["volume"]), (1, 0, False, 1))
        repeated = arrange_videos(plan["document"], [], free=True)
        self.assertEqual(repeated["count"], 0)

    def test_missing_video_and_empty_library_do_not_substitute_images(self):
        image = {**video("storyboard", "b1"), "kind": "image"}
        plan = arrange_videos(empty_document(), [image])
        self.assertEqual((plan["count"], plan["missing_video_count"]), (0, 1))
        self.assertEqual(plan["document"]["clips"], [])

    def test_limits_fail_the_entire_plan(self):
        for assets in ([video(str(i), duration=10) for i in range(201)], [video("long", duration=1801)], [video(str(i)) for i in range(301)]):
            doc = empty_document(); doc["assets"] = assets
            with self.subTest(count=len(assets)), self.assertRaises(ValueError):
                arrange_videos(doc, [], free=True)
            self.assertEqual(doc["clips"], [])

    def test_selected_asset_order_is_honoured_and_validated(self):
        doc = empty_document(); doc["assets"] = [video("a"), video("b")]
        plan = arrange_videos(doc, [], free=True, asset_ids=["b", "a"])
        self.assertEqual([i["asset_id"] for i in plan["items"]], ["b", "a"])
        self.assertEqual([c["asset_id"] for c in plan["document"]["clips"]], ["b", "a"])
        with self.assertRaises(ValueError): arrange_videos(doc, [], free=True, asset_ids=["missing"])


class SubtitleAndCutTests(unittest.TestCase):
    def sources(self):
        return [video("v1", "b1", 10), video("v2", "b2", 10), video("v3", "b3", 10), video("v4", "b4", 10),
                audio("a1", "b1"), audio("a3", "b3")]

    @staticmethod
    def transcript(asset_id="v1", beat="b1", *, spans=None, segments=None):
        return {asset_id: {"asset_id": asset_id, "name": asset_id, "beat_id": beat, "status": "succeeded",
                           "spans": spans if spans is not None else [
                               {"clip_id": "c1", "timeline_start": 0.0, "timeline_duration": 4.0,
                                "in_point": 1.0, "speed": 2.0}],
                           "segments": segments if segments is not None else [
                               {"id": "0", "start": 0.4, "end": 1.2, "text": "剪掉的开头"},
                               {"id": "1", "start": 2.0, "end": 3.0, "text": "你终于来了。"},
                               {"id": "2", "start": 4.0, "end": 5.0, "text": "一切都结束了。"},
                               {"id": "3", "start": 6.0, "end": 9.4,
                                "text": "我们先去爬山，然后到山顶看日落晚上再一起吃饭聊天把这一周的事情说完。"},
                               {"id": "4", "start": 9.5, "end": 10.0, "text": "超出镜头的尾巴"}]}}

    def audio_document(self, *, manual=True):
        doc = empty_document()
        doc["assets"] = [video("v1", "b1", 10)]
        doc["clips"] = [{"id": "c1", "track": "video", "asset_id": "v1", "start": 0, "duration": 4},
                        {"id": "old", "track": "text", "start": 3.5, "duration": 0.5, "text": "旧自动字幕",
                         "origin": "auto_subtitle"}]
        if manual:
            doc["clips"].append({"id": "manual", "track": "text", "start": 0.5, "duration": .5, "text": "手动标题"})
        return validate_document(doc)

    def test_audio_subtitles_map_source_times_and_skip_audible_conflicts(self):
        plan = place_audio_subtitles(self.audio_document(), self.transcript())
        self.assertEqual((plan["count"], plan["skipped_count"], plan["inaudible_count"], plan["replaced_count"]), (3, 1, 2, 1))
        captions = [clip for clip in plan["document"]["clips"] if clip.get("origin") == "auto_subtitle"]
        self.assertEqual([c["text"] for c in captions][0], "一切都结束了。")
        self.assertAlmostEqual(captions[0]["start"], 1.5); self.assertAlmostEqual(captions[0]["duration"], .5)
        self.assertEqual(captions[0]["font_size"], 56)
        for caption in captions:
            self.assertGreaterEqual(caption["start"], 0); self.assertLessEqual(caption["start"] + caption["duration"], 4 + 1e-6)
            self.assertLessEqual(len(caption["text"]), 30); self.assertLessEqual(caption["duration"], 5)
        self.assertTrue(all(not (caption["start"] < 1 - 1e-6 and caption["start"] + caption["duration"] > .5 + 1e-6)
                            for caption in captions))
        self.assertTrue(any(c["id"] == "manual" and c["text"] == "手动标题" for c in plan["document"]["clips"]))
        self.assertTrue(all(item["asset_id"] == "v1" and item["segment_id"] for item in plan["items"]))
        self.assertTrue(any("已按镜头边界收短" in item["reason"] for item in plan["items"]))
        repeated = place_audio_subtitles(plan["document"], self.transcript())
        self.assertEqual((repeated["count"], repeated["replaced_count"], repeated["skipped_count"]), (3, 3, 1))

    def test_audio_subtitles_follow_speed_and_repeat_the_asset_on_every_span(self):
        spans = [{"clip_id": "c1", "timeline_start": 0.0, "timeline_duration": 2.0, "in_point": 0.0, "speed": 2.0},
                 {"clip_id": "c2", "timeline_start": 4.0, "timeline_duration": 2.0, "in_point": 6.0, "speed": 1.0}]
        segments = [{"id": "0", "start": 1.0, "end": 1.8, "text": "第一次出现。"},
                    {"id": "1", "start": 6.5, "end": 7.5, "text": "第二次出现。"}]
        plan = place_audio_subtitles(self.audio_document(manual=False), self.transcript(spans=spans, segments=segments))
        self.assertEqual([round(c["start"], 3) for c in plan["document"]["clips"] if c.get("origin") == "auto_subtitle"],
                         [0.5, 4.5])
        self.assertEqual(plan["count"], 2)

    def test_audio_subtitles_never_substitute_script_dialogue(self):
        with self.assertRaises(ValueError) as first:
            place_audio_subtitles(self.audio_document(), {})
        self.assertIn("转写", str(first.exception))
        doc = self.audio_document()
        plan = place_audio_subtitles(doc, self.transcript(segments=[{"id": "0", "start": 20.0, "end": 22.0, "text": "镜头外的语音"}]))
        self.assertEqual(plan["count"], 0)
        self.assertEqual(plan["inaudible_count"], 1)
        self.assertEqual([c["id"] for c in plan["document"]["clips"] if c["track"] == "text"], ["manual"])

    def test_subtitles_follow_dialogue_timings_and_replace_only_auto_captions(self):
        doc = empty_document(); doc["settings"]["ratio"] = "9:16"
        doc["assets"] = [video("v1", "b1", 10), video("v2", "b2", 10)]
        doc["clips"] = [{"id": "c1", "track": "video", "asset_id": "v1", "start": 0, "duration": 5},
                        {"id": "c2", "track": "video", "asset_id": "v2", "start": 5, "duration": 5},
                        {"id": "manual", "track": "text", "start": 4, "duration": .5, "text": "手动标题"},
                        {"id": "old", "track": "text", "start": 0, "duration": 1, "text": "旧自动字幕", "origin": "auto_subtitle"}]
        plan = place_subtitles(doc, beats()[:2])
        self.assertEqual((plan["count"], plan["skipped_count"], plan["replaced_count"]), (2, 1, 1))
        captions = [c for c in plan["document"]["clips"] if c.get("origin") == "auto_subtitle"]
        self.assertEqual([c["text"] for c in captions], ["你终于来了。", "我等你很久了。"])
        self.assertEqual([c["beat_id"] for c in captions], ["b1", "b1"])
        self.assertAlmostEqual(captions[0]["start"], 0); self.assertAlmostEqual(captions[1]["start"], 28 / 24)
        self.assertAlmostEqual(captions[0]["duration"], 28 / 24); self.assertAlmostEqual(captions[1]["duration"], 33 / 24)
        self.assertAlmostEqual(plan["total_duration"], 61 / 24)
        for caption in captions:
            self.assertEqual((caption["font_size"], caption["y"], caption["color"]), (46, 36, "#ffffff"))
            self.assertLessEqual(caption["start"] + caption["duration"], 5 + 1e-6)
        self.assertTrue(any(c["id"] == "manual" and c["text"] == "手动标题" for c in plan["document"]["clips"]))
        again = place_subtitles(plan["document"], beats()[:2])
        self.assertEqual((again["count"], again["replaced_count"]), (2, 2))
        self.assertEqual(sum(1 for c in again["document"]["clips"] if c.get("origin") == "auto_subtitle"), 2)

    def test_dialogue_cut_keeps_dialogue_rebuilds_audio_and_preserves_manual_text(self):
        doc = empty_document()
        doc["clips"] = [{"id": "note", "track": "text", "start": 0, "duration": .5, "text": "手动字"}]
        plan = rebuild_cut(doc, self.sources(), beats(), "dialogue_cut")
        self.assertEqual([i["beat_id"] for i in plan["items"]], ["b1", "b3"])
        self.assertEqual((plan["dropped_count"], plan["trimmed_count"]), (2, 2))
        clips = plan["document"]["clips"]
        videos = [c for c in clips if c["track"] == "video"]
        sounds = [c for c in clips if c["track"] == "audio"]
        self.assertEqual([c["asset_id"] for c in videos], ["v1", "v3"])
        self.assertEqual([c["asset_id"] for c in sounds], ["a1", "a3"])
        self.assertAlmostEqual(videos[0]["start"], 0); self.assertAlmostEqual(videos[0]["duration"], 76 / 24)
        self.assertAlmostEqual(videos[1]["start"], 76 / 24); self.assertAlmostEqual(videos[1]["duration"], 57 / 24)
        for sound in sounds:
            owner = next(v for v in videos if v["start"] <= sound["start"] < v["start"] + v["duration"])
            self.assertLessEqual(sound["start"] + sound["duration"], owner["start"] + owner["duration"] + 1e-6)
        self.assertTrue(any(c["id"] == "note" and c["text"] == "手动字" for c in clips))
        self.assertAlmostEqual(plan["total_duration"], 133 / 24)

    def test_quick_cut_compresses_all_beats_and_highlight_keeps_top_scored(self):
        doc = empty_document()
        quick = rebuild_cut(doc, self.sources(), beats(), "quick_cut")
        self.assertEqual([i["beat_id"] for i in quick["items"]], ["b1", "b2", "b3", "b4"])
        self.assertEqual((quick["dropped_count"], quick["trimmed_count"]), (0, 4))
        highlight = rebuild_cut(doc, self.sources(), beats(), "highlight_cut")
        self.assertEqual([i["beat_id"] for i in highlight["items"]], ["b1", "b2", "b3"])
        self.assertEqual((highlight["count"], highlight["dropped_count"], highlight["trimmed_count"]), (3, 1, 1))

    def test_cut_operations_require_usable_shot_videos(self):
        with self.assertRaises(ValueError): rebuild_cut(empty_document(), [], beats(), "quick_cut")
        with self.assertRaises(ValueError): place_subtitles(empty_document(), beats())
        with self.assertRaises(ValueError): place_subtitles(empty_document(), [])

    def test_hook_strategies_open_on_evidence_and_drop_the_resolution(self):
        doc = empty_document()
        conflict = rebuild_cut(doc, self.sources(), beats(), "hook_cut", "conflict_3s")
        self.assertEqual(conflict["items"][0]["beat_id"], "b3")
        self.assertLess(conflict["count"], 4)
        self.assertTrue(all(item.get("reason") for item in conflict["items"]))
        self.assertTrue(conflict["items"][0]["reason"].startswith("冲突开场"))
        climax = rebuild_cut(doc, self.sources(), beats(), "hook_cut", "climax_only")
        self.assertEqual({item["beat_id"] for item in climax["items"]}, {"b2", "b3"})
        quote = rebuild_cut(doc, self.sources(), beats(), "hook_cut", "quote_open")
        self.assertEqual(quote["items"][0]["beat_id"], "b3")
        self.assertTrue(quote["items"][0]["reason"].startswith("金句开场"))
        ending = rebuild_cut(doc, self.sources(), beats(), "hook_cut", "ending_hook")
        self.assertEqual([item["beat_id"] for item in ending["items"]], ["b3"])
        trailer = rebuild_cut(doc, self.sources(), beats(), "hook_cut", "trailer")
        self.assertEqual(trailer["items"][0]["beat_id"], "b3")
        self.assertNotIn("b4", [item["beat_id"] for item in trailer["items"]])
        for strategy in ("conflict_3s", "climax_only", "quote_open", "ending_hook", "trailer"):
            with self.subTest(strategy=strategy):
                clips = rebuild_cut(doc, self.sources(), beats(), "hook_cut", strategy)["document"]["clips"]
                self.assertTrue(any(clip["track"] == "video" for clip in clips))
        with self.assertRaises(ValueError):
            rebuild_cut(doc, self.sources(), beats(), "hook_cut", "unknown")


class SubtitleTranslateTests(unittest.TestCase):
    def test_language_detection(self):
        self.assertTrue(_needs_chinese_translation("シャンクス、おれも船に乗せてくれ！"))
        self.assertTrue(_needs_chinese_translation("路飞：「行くぞ！」"))
        self.assertTrue(_needs_chinese_translation("Let's go, Luffy!"))
        self.assertTrue(_needs_chinese_translation("안녕하세요"))
        self.assertFalse(_needs_chinese_translation("香克斯，让我上船吧！"))
        self.assertFalse(_needs_chinese_translation("第一集 123！"))
        self.assertFalse(_needs_chinese_translation("？！"))

    def test_targets_collect_only_foreign_lines(self):
        doc = empty_document()
        doc["assets"] = [video("v1", duration=30)]
        doc["clips"] = [
            {"id": "ja", "track": "text", "start": 0, "duration": 1, "text": "行くぞ！"},
            {"id": "zh", "track": "text", "start": 1, "duration": 1, "text": "已经是中文"},
            {"id": "blank", "track": "text", "start": 2, "duration": 1, "text": " "},
            {"id": "v", "track": "video", "asset_id": "v1", "start": 0, "duration": 3},
        ]
        self.assertEqual(subtitle_translation_targets(doc), [{"clip_id": "ja", "text": "行くぞ！"}])

    def test_translate_subtitles_only_touches_text(self):
        doc = empty_document()
        doc["assets"] = [video("v1", duration=30)]
        doc["clips"] = [
            {"id": "ja", "track": "text", "start": 1.5, "duration": 2, "text": "シャンクス、おれも船に乗せてくれ！"},
            {"id": "zh", "track": "text", "start": 4, "duration": 1, "text": "已经是中文"},
            {"id": "v", "track": "video", "asset_id": "v1", "start": 0, "duration": 5},
        ]
        plan = translate_subtitles(doc, {"ja": "香克斯，让我上船吧！"})
        self.assertEqual((plan["count"], plan["skipped_count"]), (1, 1))
        self.assertEqual(plan["items"][0]["clip_id"], "ja")
        self.assertEqual(plan["items"][0]["name"], "香克斯，让我上船吧！")
        self.assertIn("原文：", plan["items"][0]["reason"])
        clips = {clip["id"]: clip for clip in plan["document"]["clips"]}
        self.assertEqual(clips["ja"]["text"], "香克斯，让我上船吧！")
        self.assertEqual((clips["ja"]["start"], clips["ja"]["duration"]), (1.5, 2))
        self.assertEqual(clips["zh"]["text"], "已经是中文")
        self.assertEqual(next(c for c in doc["clips"] if c["id"] == "ja")["text"], "シャンクス、おれも船に乗せてくれ！")
        with self.assertRaises(ValueError):
            translate_subtitles(doc, {})

    def test_translator_validates_and_batches_model_output(self):
        llm = Mock()
        llm.chat_json.return_value = {"lines": ["一", "二"]}
        translate = make_subtitle_translator(llm)
        self.assertEqual(translate(["a", "b"]), ["一", "二"])
        llm.chat_json.return_value = {"lines": ["一"]}
        with self.assertRaises(ValueError):
            translate(["a", "b"])
        llm.chat_json.side_effect = RuntimeError("provider down")
        with self.assertRaises(ValueError):
            translate(["a"])
        batch_llm = Mock()
        batch_llm.chat_json.side_effect = lambda system, payload, **kwargs: {
            "lines": ["译"] * len(json.loads(payload)["lines"])}
        self.assertEqual(make_subtitle_translator(batch_llm)([f"line{i}" for i in range(85)]), ["译"] * 85)
        self.assertEqual(batch_llm.chat_json.call_count, 3)
        with self.assertRaises(ValueError):
            make_subtitle_translator(object())(["a"])


class FakeTranscript:
    def __init__(self, evidence=None, status="succeeded"):
        self.evidence_value = evidence if evidence is not None else SubtitleAndCutTests.transcript()
        self.status = status
        self.meta = {"status": status, "model": "asr-test", "used_count": len(self.evidence_value),
                     "segment_count": sum(len(item.get("segments") or []) for item in self.evidence_value.values())}

    def evidence(self, owner, project, sequence):
        return ({} if self.status in {"missing", "stale", "failed", "empty"} else self.evidence_value), dict(self.meta)

    def summary(self, owner, project, sequence):
        return {"status": self.status, "model": "asr-test", "segment_count": self.meta["segment_count"],
                "transcribed_count": self.meta["used_count"], "stale": self.status == "stale"}


class EditingAssistantTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = JobStore(Path(temp.name) / "editing.db")
        self.llm = Mock(); self.llm.assistant_models.return_value = ["model"]
        self.service = AssistantService(self.store, self.llm, Path(temp.name) / "uploads")
        self.editing = self.service.editing
        with self.store.connection() as conn:
            conn.execute("CREATE TABLE ai_projects (id TEXT PRIMARY KEY,name TEXT,settings_json TEXT)")
            conn.execute("INSERT INTO ai_projects VALUES ('p','测试工程','{}')")
            conn.execute("CREATE TABLE ai_project_episodes (id TEXT PRIMARY KEY,project_id TEXT)")
            conn.execute("INSERT INTO ai_project_episodes VALUES ('ep','p')")
            conn.execute("CREATE TABLE ai_smart_edit_documents (id TEXT PRIMARY KEY,project_id TEXT,owner_user_id TEXT,sequence_id TEXT,revision INTEGER,document_json TEXT,created_at TEXT,updated_at TEXT)")
        self.doc = empty_document(); self.doc["assets"] = [video("v1"), video("v2")]
        self.seed(self.doc)
        source_patch = patch("backend.app.director_assistant.editing.smart_edit_service.project_sources", return_value=[])
        source_patch.start(); self.addCleanup(source_patch.stop)

    def seed(self, doc, revision=1):
        with self.store.connection() as conn:
            key = document_id("p", "alice", "main")
            conn.execute("DELETE FROM ai_smart_edit_documents WHERE id=?", (key,))
            conn.execute("INSERT INTO ai_smart_edit_documents VALUES (?,?,?,?,?,?,?,?)", (key, "p", "alice", "main", revision, dumps(validate_document(doc)), "now", "now"))

    def proposal(self):
        return self.editing.preview("alice", "p", "main", revision=1)

    def session(self, sequence="main"):
        with patch.object(self.service.actions, "context", return_value={}):
            return self.service.create_session("alice", {"project_id": "p", "context": {"kind": "smart_edit", "sequence_id": sequence}})

    def test_preview_does_not_mutate_and_confirm_saves_once(self):
        plan = self.proposal()
        self.assertNotIn("_document", plan)
        self.assertEqual(self.editing.read("alice", "p", "main")["clips"], [])
        result = self.editing.confirm("alice", "p", "main", plan["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["snapshot"]["revision"], 2)
        self.assertEqual(len(result["snapshot"]["document"]["clips"]), 2)
        self.assertEqual(self.editing.confirm("alice", "p", "main", plan["id"]), result)
        self.assertEqual(self.editing.read("alice", "p", "main")["revision"], 2)

    def test_conflict_preserves_updated_document(self):
        plan = self.proposal(); changed = copy.deepcopy(self.doc); changed["name"] = "另一个窗口修改"
        self.seed(changed, 2)
        with self.assertRaises(AssistantConflict): self.editing.confirm("alice", "p", "main", plan["id"])
        self.assertEqual(self.editing.get("alice", "p", "main", plan["id"])["status"], "pending")
        self.assertEqual(self.editing.read("alice", "p", "main")["clips"], [])

    def audio_timeline(self):
        doc = copy.deepcopy(self.doc)
        doc["assets"] = [video("v1", duration=10), video("v2", duration=10)]
        doc["clips"] = [{"id": "c1", "track": "video", "asset_id": "v1", "start": 0, "duration": 4},
                        {"id": "note", "track": "text", "start": 5, "duration": 1, "text": "手动注释"}]
        self.seed(doc, 1)
        return doc

    def test_audio_subtitle_preview_and_confirm_use_transcript_evidence(self):
        self.audio_timeline()
        self.editing.transcription = FakeTranscript()
        plan = self.editing.preview("alice", "p", "main", revision=1, operation="audio_subtitle")
        self.assertEqual((plan["operation"], plan["title"], plan["count"]), ("audio_subtitle", "音轨字幕", 4))
        self.assertEqual((plan["inaudible_count"], plan["replaced_count"]), (2, 0))
        self.assertEqual(plan["transcript"]["segment_count"], 5)
        self.assertEqual(len(self.editing.read("alice", "p", "main")["clips"]), 2)
        result = self.editing.confirm("alice", "p", "main", plan["id"])
        self.assertEqual(result["snapshot"]["revision"], 2)
        clips = result["snapshot"]["document"]["clips"]
        captions = [c for c in clips if c.get("origin") == "auto_subtitle"]
        self.assertEqual(len(captions), plan["count"])
        self.assertTrue(any(c["id"] == "note" and c["text"] == "手动注释" for c in clips))
        self.assertTrue(all(c["track"] == "text" and 0 <= c["start"] < 4 for c in captions))
        self.assertNotIn("手动注释", [c["text"] for c in captions])
        self.assertEqual(self.editing.confirm("alice", "p", "main", plan["id"]), result)
        self.assertEqual(len(self.editing.read("alice", "p", "main")["clips"]), 2 + len(captions))

    def test_audio_subtitle_requires_usable_transcript(self):
        self.audio_timeline()
        for status, phrase in (("missing", "请先转写音频"), ("stale", "已过期"), ("empty", "没有识别到语音"),
                               ("failed", "重新转写"), ("running", "正在进行")):
            self.editing.transcription = FakeTranscript({}, status=status)
            with self.subTest(status=status), self.assertRaises(ValueError) as error:
                self.editing.preview("alice", "p", "main", revision=1, operation="audio_subtitle")
            self.assertIn(phrase, str(error.exception))
        self.assertEqual(len(self.editing.read("alice", "p", "main")["clips"]), 2)
        self.assertEqual(self.service.repo.list("alice", "edit_proposal"), [])

    def subtitle_timeline(self, revision=1):
        doc = copy.deepcopy(self.doc)
        doc["clips"] = [
            {"id": "ja1", "track": "text", "start": 0, "duration": 2, "text": "シャンクス、おれも船に乗せてくれ！", "origin": "auto_subtitle"},
            {"id": "zh1", "track": "text", "start": 3, "duration": 1, "text": "已经是中文", "origin": "auto_subtitle"},
        ]
        self.seed(doc, revision)

    def test_subtitle_translate_flow_through_preview_and_confirm(self):
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        session = self.session()
        plan = self.editing.preview("alice", "p", "main", revision=1, session_id=session["id"], operation="subtitle_translate")
        self.assertEqual((plan["operation"], plan["title"], plan["count"], plan["skipped_count"], plan["status"]),
                         ("subtitle_translate", "字幕翻译", 1, 1, "pending"))
        self.assertEqual(plan["items"][0]["clip_id"], "ja1")
        self.assertEqual(plan["items"][0]["name"], "香克斯，让我上船吧！")
        self.assertIn("原文：", plan["items"][0]["reason"])
        texts = [c.get("text") for c in self.editing.read("alice", "p", "main")["clips"]]
        self.assertIn("シャンクス、おれも船に乗せてくれ！", texts)
        self.assertIn("已经是中文", texts)
        result = self.editing.confirm("alice", "p", "main", plan["id"])
        self.assertEqual(result["status"], "succeeded")
        clips = {c["id"]: c for c in result["snapshot"]["document"]["clips"]}
        self.assertEqual(clips["ja1"]["text"], "香克斯，让我上船吧！")
        self.assertEqual(clips["zh1"]["text"], "已经是中文")
        self.assertEqual((clips["ja1"]["start"], clips["ja1"]["duration"]), (0, 2))
        self.assertEqual(self.editing.confirm("alice", "p", "main", plan["id"]), result)
        self.assertEqual(self.llm.chat_json.call_count, 1)

    def test_subtitle_translate_without_foreign_lines_returns_empty_plan(self):
        doc = copy.deepcopy(self.doc)
        doc["clips"] = [{"id": "zh1", "track": "text", "start": 0, "duration": 1, "text": "已经是中文"}]
        self.seed(doc, 1)
        plan = self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_translate")
        self.assertEqual((plan["count"], plan["status"]), (0, "empty"))
        self.llm.chat_json.assert_not_called()

    def test_subtitle_translate_failures_surface_friendly_errors(self):
        self.subtitle_timeline()
        self.llm.chat_json.side_effect = RuntimeError("provider down")
        with self.assertRaises(ValueError) as error:
            self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_translate")
        self.assertIn("字幕翻译暂时失败", str(error.exception))
        self.llm.chat_json.side_effect = None
        self.llm.chat_json.return_value = {"lines": []}
        with self.assertRaises(ValueError) as error:
            self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_translate")
        self.assertIn("结果不完整", str(error.exception))
        self.assertEqual(self.service.repo.list("alice", "edit_proposal"), [])
        self.assertEqual(self.editing.read("alice", "p", "main")["revision"], 1)

    def test_reapply_restores_translations_without_new_model_calls(self):
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        session = self.session()
        plan = self.editing.preview("alice", "p", "main", revision=1, session_id=session["id"], operation="subtitle_translate")
        self.editing.confirm("alice", "p", "main", plan["id"])
        calls = self.llm.chat_json.call_count
        self.assertEqual(plan["translations"][0]["original"], "シャンクス、おれも船に乗せてくれ！")
        doc = copy.deepcopy(self.doc)
        doc["clips"] = [
            {"id": "ja9", "track": "text", "start": 0, "duration": 2, "text": "シャンクス、おれも船に乗せてくれ！", "origin": "auto_subtitle"},
            {"id": "zh9", "track": "text", "start": 3, "duration": 1, "text": "已经是中文", "origin": "auto_subtitle"},
        ]
        self.seed(doc, 2)
        again = self.editing.reapply("alice", "p", "main", plan["id"], revision=2, session_id=session["id"])
        self.assertEqual((again["operation"], again["status"], again["count"], again["reapplied_from"]),
                         ("subtitle_translate", "pending", 1, plan["id"]))
        self.assertEqual(again["items"][0]["name"], "香克斯，让我上船吧！")
        self.assertEqual(self.llm.chat_json.call_count, calls)
        result = self.editing.confirm("alice", "p", "main", again["id"])
        clips = {c["id"]: c for c in result["snapshot"]["document"]["clips"]}
        self.assertEqual(clips["ja9"]["text"], "香克斯，让我上船吧！")
        self.assertEqual(result["snapshot"]["revision"], 3)

    def test_reapply_rejects_pending_and_unmatched_and_other_operations(self):
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        plan = self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_translate")
        with self.assertRaises(ValueError):
            self.editing.reapply("alice", "p", "main", plan["id"], revision=1)
        self.editing.confirm("alice", "p", "main", plan["id"])
        doc = copy.deepcopy(self.doc)
        doc["clips"] = [{"id": "en", "track": "text", "start": 0, "duration": 1, "text": "Hello world"}]
        self.seed(doc, 2)
        empty = self.editing.reapply("alice", "p", "main", plan["id"], revision=2)
        self.assertEqual((empty["count"], empty["status"]), (0, "empty"))
        self.assertEqual(self.llm.chat_json.call_count, 1)
        other = self.editing.preview("alice", "p", "main", revision=2, operation="video_arrange")
        self.editing.confirm("alice", "p", "main", other["id"])
        with self.assertRaises(ValueError):
            self.editing.reapply("alice", "p", "main", other["id"], revision=3)
        with self.assertRaises(AssistantNotFound):
            self.editing.reapply("bob", "p", "main", plan["id"], revision=3)

    def test_reapply_falls_back_to_legacy_items(self):
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        plan = self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_translate")
        self.editing.confirm("alice", "p", "main", plan["id"])
        record = self.service.repo.get("alice", plan["id"])
        self.service.repo.update("alice", record, {"translations": None})
        self.subtitle_timeline(2)
        again = self.editing.reapply("alice", "p", "main", plan["id"], revision=2)
        self.assertEqual((again["count"], again["status"]), (1, "pending"))
        self.assertEqual(again["items"][0]["name"], "香克斯，让我上船吧！")

    def test_http_reapply_route(self):
        app = FastAPI(); app.state.director_assistant = self.service
        def current(): return {"id": "alice"}
        def mutation(): return {"id": "alice"}
        register_smart_edit_routes(app, current_user=current, mutating_user=mutation)
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        base = "/api/projects/p/smart-edit/main/actions"
        with TestClient(app) as client:
            plan = client.post(base + "/preview", json={"revision": 1, "operation": "subtitle_translate"}).json()
            client.post(base + "/" + plan["id"] + "/confirm")
            self.subtitle_timeline(2)
            reapplied = client.post(base + "/" + plan["id"] + "/reapply", json={"revision": 2}).json()
            self.assertEqual((reapplied["operation"], reapplied["count"], reapplied["reapplied_from"]),
                             ("subtitle_translate", 1, plan["id"]))
            self.assertEqual(client.post(base + "/" + plan["id"] + "/reapply", json={"revision": 1}).status_code, 409)

    def test_editor_read_analysis_reports_transcript_state(self):
        self.editing.transcription = FakeTranscript()
        analysis = self.editing.read("alice", "p", "main")["analysis"]
        self.assertEqual(analysis["transcript"]["status"], "succeeded")
        self.assertEqual(analysis["transcript"]["segment_count"], 5)
        self.editing.transcription = None
        self.assertNotIn("transcript", self.editing.read("alice", "p", "main")["analysis"])

    def test_ownership_target_and_session_scope(self):
        plan = self.proposal()
        for method in (self.editing.get, self.editing.confirm):
            with self.assertRaises(AssistantNotFound): method("bob", "p", "main", plan["id"])
            with self.assertRaises(AssistantNotFound): method("alice", "p", "ep", plan["id"])
        with self.assertRaises(AssistantNotFound): self.editing.preview("alice", "p", "wrong")
        session = self.session("ep")
        with self.assertRaises(AssistantConflict): self.editing.preview("alice", "p", "main", session_id=session["id"])
        with patch.object(self.service.actions, "context", return_value={}), self.assertRaises(ValueError):
            self.service.create_session("alice", {"context": {"kind": "smart_edit", "sequence_id": "main"}})

    def test_transaction_rolls_back_document_if_record_write_fails(self):
        plan = self.proposal()
        with patch.object(self.service.repo, "update", side_effect=RuntimeError("database write failed")):
            with self.assertRaises(RuntimeError): self.editing.confirm("alice", "p", "main", plan["id"])
        self.assertEqual(self.editing.read("alice", "p", "main")["revision"], 1)
        self.assertEqual(self.editing.get("alice", "p", "main", plan["id"])["status"], "pending")

    def test_parallel_confirm_is_idempotent(self):
        plan = self.proposal()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.editing.confirm("alice", "p", "main", plan["id"]), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.editing.read("alice", "p", "main")["revision"], 2)

    def test_language_tools_share_the_same_proposal_and_require_editor_read(self):
        session = self.session(); run = {"id": "run", "project_id": "p", "context": session["context"]}
        with self.assertRaises(ValueError): self.service._tool("alice", session, run, "propose_edit", {}, {})
        context = self.service._tool("alice", session, run, "editor_read", {}, {})
        self.assertEqual(len(context["videos"]), 2)
        with self.assertRaises(ValueError): self.service._tool("alice", session, run, "propose_edit", {"project_id": "other"}, {})
        plan = self.service._tool("alice", session, run, "propose_edit", {"operation": "video_arrange"}, {})
        self.assertEqual(plan["items"], self.proposal()["items"])
        self.assertEqual(self.service.detail("alice", session["id"])["edit_proposals"][0]["id"], plan["id"])
        with self.assertRaises(ValueError): self.service._tool("alice", session, {**run, "context": None}, "editor_read", {}, {})

    def test_shortcut_records_message_without_calling_llm(self):
        session = self.session()
        plan = self.editing.preview("alice", "p", "main", revision=1, session_id=session["id"])
        detail = self.service.detail("alice", session["id"])
        self.assertEqual(detail["messages"][0]["parts"], [{"type": "edit_action", "action_id": plan["id"]}])
        self.llm.assistant_chat.assert_not_called()

    def episode_context(self, sources):
        return (patch("backend.app.director_assistant.editing.smart_edit_service.project_sources", return_value=sources),
                patch("backend.app.director_assistant.editing.ProjectDetailService.get_episode_detail", return_value={"beats": beats()}))

    def test_episode_subtitles_and_cut_operations_flow_through_preview_and_confirm(self):
        sources = [video("v1", "b1", 10), video("v2", "b2", 10), video("v3", "b3", 10), video("v4", "b4", 10),
                   audio("a1", "b1"), audio("a3", "b3")]
        source_patch, detail_patch = self.episode_context(sources)
        with source_patch, detail_patch:
            arrange = self.editing.preview("alice", "p", "ep", revision=0)
        self.assertEqual(arrange["count"], 4)
        self.assertEqual(self.editing.confirm("alice", "p", "ep", arrange["id"])["snapshot"]["revision"], 1)
        source_patch, detail_patch = self.episode_context(sources)
        with source_patch, detail_patch:
            subtitles = self.editing.preview("alice", "p", "ep", revision=1, operation="subtitle_arrange")
        self.assertEqual((subtitles["title"], subtitles["count"]), ("自动字幕", 3))
        self.assertEqual(self.editing.confirm("alice", "p", "ep", subtitles["id"])["snapshot"]["revision"], 2)
        source_patch, detail_patch = self.episode_context(sources)
        with source_patch, detail_patch:
            quick = self.editing.preview("alice", "p", "ep", revision=2, operation="quick_cut")
        self.assertEqual((quick["title"], quick["count"], quick["total_duration"]), ("成片速剪", 4, (74 + 60 + 55 + 60) / 24))
        document = self.editing.confirm("alice", "p", "ep", quick["id"])["snapshot"]["document"]
        self.assertEqual([c["asset_id"] for c in document["clips"] if c["track"] == "video"], ["v1", "v2", "v3", "v4"])
        self.assertEqual([c["asset_id"] for c in document["clips"] if c["track"] == "audio"], ["a1", "a3"])
        self.assertEqual([c for c in document["clips"] if c["track"] == "text"], [])

    def test_unsupported_operation_and_asset_order_are_rejected(self):
        with self.assertRaises(ValueError): self.editing.preview("alice", "p", "main", revision=1, operation="unknown")
        with self.assertRaises(ValueError): self.editing.preview("alice", "p", "main", revision=1, operation="subtitle_arrange", asset_ids=["v1"])

    def test_reorder_updates_pending_plan_and_confirm_uses_new_order(self):
        plan = self.proposal()
        with self.assertRaises(ValueError): self.editing.reorder("alice", "p", "main", plan["id"], ["missing"])
        reordered = self.editing.reorder("alice", "p", "main", plan["id"], ["v2", "v1"])
        self.assertEqual([i["asset_id"] for i in reordered["items"]], ["v2", "v1"])
        self.assertEqual(self.editing.get("alice", "p", "main", plan["id"])["status"], "pending")
        result = self.editing.confirm("alice", "p", "main", plan["id"])
        videos = [c for c in result["snapshot"]["document"]["clips"] if c["track"] == "video"]
        self.assertEqual([c["asset_id"] for c in videos], ["v2", "v1"])
        with self.assertRaises(ValueError): self.editing.reorder("alice", "p", "main", plan["id"], ["v1"])

    def test_reorder_rejects_stale_timeline(self):
        plan = self.proposal()
        self.seed(copy.deepcopy(self.doc), 2)
        with self.assertRaises(AssistantConflict): self.editing.reorder("alice", "p", "main", plan["id"], ["v2", "v1"])

    def test_language_tool_forwards_strategy_operations(self):
        session = self.session("ep"); run = {"id": "run", "project_id": "p", "context": session["context"]}
        sources = [video("v1", "b1", 10), video("v2", "b2", 10), video("v3", "b3", 10), video("v4", "b4", 10)]
        source_patch, detail_patch = self.episode_context(sources)
        with source_patch, detail_patch:
            context = self.service._tool("alice", session, run, "editor_read", {}, {})
            plan = self.service._tool("alice", session, run, "propose_edit", {"operation": "highlight_cut"}, {})
        self.assertEqual(context["analysis"]["dialogue_beat_count"], 2)
        self.assertEqual(context["analysis"]["highlight_candidates"][0]["beat_id"], "b3")
        self.assertGreater(context["analysis"]["dialogue_seconds"], 0)
        self.assertEqual((plan["operation"], plan["title"], plan["count"]), ("highlight_cut", "高光合集", 3))
        with self.assertRaises(ValueError):
            self.service._tool("alice", session, run, "propose_edit", {"operation": "highlight_cut", "asset_ids": ["v1"]}, {})

    def test_language_tool_requires_hook_strategy_and_returns_reasons(self):
        session = self.session("ep"); run = {"id": "run", "project_id": "p", "context": session["context"]}
        sources = [video("v1", "b1", 10), video("v2", "b2", 10), video("v3", "b3", 10), video("v4", "b4", 10)]
        source_patch, detail_patch = self.episode_context(sources)
        with source_patch, detail_patch:
            self.service._tool("alice", session, run, "editor_read", {}, {})
            with self.assertRaises(ValueError):
                self.service._tool("alice", session, run, "propose_edit", {"operation": "hook_cut"}, {})
            plan = self.service._tool("alice", session, run, "propose_edit", {"operation": "hook_cut", "strategy": "conflict_3s"}, {})
        self.assertEqual((plan["operation"], plan["title"], plan["strategy_title"]), ("hook_cut", "引流剪辑", "3秒进冲突"))
        self.assertTrue(plan["principle"])
        self.assertTrue(plan["items"][0]["reason"].startswith("冲突开场"))
        self.assertEqual(plan["items"][0]["beat_id"], "b3")

    def test_http_reorder_route(self):
        app = FastAPI(); app.state.director_assistant = self.service
        def current(): return {"id": "alice"}
        def mutation(): return {"id": "alice"}
        register_smart_edit_routes(app, current_user=current, mutating_user=mutation)
        base = "/api/projects/p/smart-edit/main/actions"
        with TestClient(app) as client:
            plan = client.post(base + "/preview", json={"revision": 1, "asset_ids": ["v2", "v1"]}).json()
            self.assertEqual([i["asset_id"] for i in plan["items"]], ["v2", "v1"])
            response = client.post(base + "/" + plan["id"] + "/reorder", json={"asset_ids": ["v1", "v2"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([i["asset_id"] for i in response.json()["items"]], ["v1", "v2"])
            self.assertEqual(client.post(base + "/" + plan["id"] + "/reorder", json={"asset_ids": []}).status_code, 422)
            def denied(): raise HTTPException(403, "CSRF 校验失败")
            app.dependency_overrides[mutation] = denied
            self.assertEqual(client.post(base + "/" + plan["id"] + "/reorder", json={"asset_ids": ["v1"]}).status_code, 403)

    def test_http_subtitle_translate_route(self):
        app = FastAPI(); app.state.director_assistant = self.service
        def current(): return {"id": "alice"}
        def mutation(): return {"id": "alice"}
        register_smart_edit_routes(app, current_user=current, mutating_user=mutation)
        self.subtitle_timeline()
        self.llm.chat_json.return_value = {"lines": ["香克斯，让我上船吧！"]}
        base = "/api/projects/p/smart-edit/main/actions"
        with TestClient(app) as client:
            plan = client.post(base + "/preview", json={"revision": 1, "operation": "subtitle_translate"}).json()
            self.assertEqual((plan["operation"], plan["count"]), ("subtitle_translate", 1))
            confirmed = client.post(base + "/" + plan["id"] + "/confirm").json()
            self.assertEqual(confirmed["snapshot"]["document"]["clips"][0]["text"], "香克斯，让我上船吧！")

    def test_complete_language_turn_freezes_context_and_produces_authorization_part(self):
        session = self.session()
        self.llm.assistant_chat.return_value = dumps({"text": "请确认铺轨清单。", "tool_calls": [
            {"name": "editor_read", "arguments": {}}, {"name": "propose_edit", "arguments": {"operation": "video_arrange"}}]})
        with patch("backend.app.director_assistant.service._EXECUTOR.submit"):
            run = self.service.send("alice", session["id"], {"text": "按分镜帮我铺轨", "client_message_id": "editing-language-123"})
        self.service.run("alice", run["id"])
        detail = self.service.detail("alice", session["id"])
        self.assertIsNone(detail["run"])
        self.assertEqual(detail["messages"][-1]["status"], "ready")
        self.assertEqual(self.service.repo.get("alice", run["id"])["status"], "succeeded")
        self.assertEqual(detail["messages"][-1]["parts"][-1]["type"], "edit_action")
        self.assertEqual(detail["edit_proposals"][0]["status"], "pending")
        self.assertEqual(self.editing.read("alice", "p", "main")["clips"], [])
        self.assertEqual(self.service.repo.get("alice", run["id"])["context"], session["context"])

    def test_http_auth_csrf_and_conflict(self):
        app = FastAPI(); app.state.director_assistant = self.service
        def current(): return {"id": "alice"}
        def mutation(): return {"id": "alice"}
        register_smart_edit_routes(app, current_user=current, mutating_user=mutation)
        base = "/api/projects/p/smart-edit/main/actions"
        with TestClient(app) as client:
            plan = client.post(base + "/preview", json={"revision": 1}).json()
            self.assertEqual(client.get(base + "/" + plan["id"]).status_code, 200)
            self.assertEqual(client.post(base + "/preview", json={"revision": 0}).status_code, 409)
            self.assertEqual(client.post(base + "/" + plan["id"] + "/confirm").json()["snapshot"]["revision"], 2)
            def denied(): raise HTTPException(403, "CSRF 校验失败")
            app.dependency_overrides[mutation] = denied
            self.assertEqual(client.post(base + "/preview", json={"revision": 2}).status_code, 403)
            def logged_out(): raise HTTPException(401, "请先登录")
            app.dependency_overrides[current] = logged_out
            self.assertEqual(client.get(base + "/" + plan["id"]).status_code, 401)
