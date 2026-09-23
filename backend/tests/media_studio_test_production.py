from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.app.media_studio.services import production_state as model
from backend.app.media_studio.services.production_service import ProductionConflict, ProductionService
from backend.app.media_studio.services import production_media as media


def detail_fixture():
    beats = [{"id": f"b{i}", "sequence": i, "action": f"action {i}", "video_duration": 1} for i in range(1, 4)]
    plan = {"id": "plan-1", "revision": 1, "source_fingerprint": "source", "status": "current",
            "parts": [{"id": "part-1", "segments": [
                {"id": f"s{i}", "title": f"画面 {i}", "source_beat_ids": [f"b{i}"], "duration_seconds": 1}
                for i in range(1, 4)]}]}
    return {"id": "ep", "project_id": "project", "script_text": "原剧本", "beats": beats,
            "prompt_authoring": {"director_plan": plan}, "data": {"beats": beats}}


def material(detail, mid="base", ids=None, verified=True, mode="director"):
    ids = ids or [u["id"] for u in model.plan_context(detail, mode)["units"]]
    return {"id": mid, "plan_key": model.plan_context(detail, mode)["key"], "url": mid,
            "unit_ids": ids, "verified": verified, "duration": len(ids),
            "ranges": {u: {"start": i, "end": i + 1} for i, u in enumerate(ids)} if verified else {}}


class ProductionModelTests(unittest.TestCase):
    def setUp(self):
        self.detail = detail_fixture()
        self.state = model.hydrate(self.detail)
        model.register_material(self.state, "director", material(self.detail))

    def test_director_complete_without_beat_video_or_dubbing(self):
        state = model.summary(self.detail, self.state, "director")
        self.assertTrue(state["ready"])
        self.assertTrue(all(not b.get("video_url") for b in self.detail["beats"]))

    def test_candidate_does_not_replace_adopted_then_middle_adoption_preserves_edges(self):
        replacement = material(self.detail, "new", ["s2"])
        model.register_material(self.state, "director", replacement)
        self.assertEqual(model.summary(self.detail, self.state)["adopted"]["s2"], "base")
        model.adopt(self.state, self.detail, "director", "new")
        clips = model.summary(self.detail, self.state)["timeline"]
        self.assertEqual([(c["url"], c["start"], c["end"]) for c in clips], [("base", 0, 1), ("new", 0, 1), ("base", 2, 3)])

    def test_unverified_full_film_cannot_be_partially_replaced(self):
        self.state = model.hydrate(self.detail)
        model.register_material(self.state, "director", material(self.detail, verified=False))
        model.register_material(self.state, "director", material(self.detail, "new", ["s2"]))
        with self.assertRaisesRegex(ValueError, "切点"):
            model.adopt(self.state, self.detail, "director", "new")
        self.assertEqual(model.summary(self.detail, self.state)["adopted"]["s2"], "base")

    def test_new_plan_retains_old_candidates_and_adoption_but_does_not_reuse(self):
        original = model.version(self.state, "director", model.plan_context(self.detail, "director")["key"])
        original["exports"].append({"url": "old-plan-film"})
        self.detail["prompt_authoring"]["director_plan"]["revision"] = 2
        view = model.summary(self.detail, self.state)
        self.assertFalse(view["ready"])
        self.assertEqual(view["adopted"], {})
        self.assertEqual(len(view["materials"]), 1)
        self.assertEqual(view["legacy_exports"][0]["url"], "old-plan-film")
        with self.assertRaisesRegex(ValueError, "不属于"):
            model.adopt(self.state, self.detail, "director", "base")

    def test_stale_plan_blocks_export_but_keeps_film(self):
        context = model.plan_context(self.detail, "director")
        v = model.version(self.state, "director", context["key"])
        v["exports"].append({"url": "old-film", "fingerprint": model.fingerprint(v)})
        self.detail["prompt_authoring"]["director_plan"]["status"] = "stale"
        view = model.summary(self.detail, self.state)
        self.assertFalse(view["ready"])
        self.assertTrue(view["needs_export"])
        self.assertEqual(view["current_export"]["url"], "old-film")

    def test_modes_have_separate_adoption_and_return_preserves_both(self):
        model.register_material(self.state, "shot", material(self.detail, "shot", mode="shot"))
        self.assertEqual(set(model.summary(self.detail, self.state, "shot")["adopted"].values()), {"shot"})
        self.assertEqual(set(model.summary(self.detail, self.state, "director")["adopted"].values()), {"base"})

    def test_legacy_projection_is_idempotent_and_keeps_unknown_film(self):
        self.detail["beats"][0]["video_url"] = "legacy-shot"
        self.detail["data"]["episode_video_url"] = "unknown-film"
        first = model.hydrate(self.detail)
        self.detail["data"]["production"] = first
        self.assertEqual(first, model.hydrate(self.detail))
        self.assertEqual(first["legacy_exports"][0]["url"], "unknown-film")
        self.assertEqual(len(first["modes"]["shot"]["materials"]), 1)

    def test_adoption_invalidates_only_affected_audio(self):
        v = model.version(self.state, "director", model.plan_context(self.detail, "director")["key"])
        v["audio"] = [{"id": "a", "unit_ids": ["s2"], "enabled": True}, {"id": "b", "unit_ids": ["s3"], "enabled": True}]
        model.register_material(self.state, "director", material(self.detail, "new", ["s2"]))
        model.adopt(self.state, self.detail, "director", "new")
        self.assertTrue(v["audio"][0]["needs_alignment"])
        self.assertFalse(v["audio"][1].get("needs_alignment", False))
        self.assertFalse(model.summary(self.detail, self.state)["ready"])

    def test_audio_overrun_and_unrelated_source_rejected(self):
        line = {"id": "l", "beat_id": "b2", "status": "ready", "audio_url": "voice", "duration_sec": 1.2, "text": "对白"}
        record = {"line_id": "l", "material_id": "base", "start": 1, "end": 2}
        with patch("backend.app.media_studio.services.dubbing_lines.expand_episode_lines", return_value=[line]):
            with self.assertRaisesRegex(ValueError, "超过"):
                model.validate_audio(self.state, self.detail, "director", [record])
            line["duration_sec"] = .4
            result = model.validate_audio(self.state, self.detail, "director", [record])
            self.assertEqual(result[0]["audio_url"], "voice")
            self.assertEqual(result[0]["unit_ids"], ["s2"])
            line["beat_id"] = "unrelated"
            with self.assertRaisesRegex(ValueError, "来源"):
                model.validate_audio(self.state, self.detail, "director", [record])

    def test_late_export_does_not_become_current(self):
        c = model.plan_context(self.detail, "director")
        v = model.version(self.state, "director", c["key"])
        old = model.fingerprint(v)
        model.register_material(self.state, "director", material(self.detail, "new", ["s2"]))
        model.adopt(self.state, self.detail, "director", "new")
        v["exports"].append({"fingerprint": old, "url": "late-film"})
        self.assertIsNone(model.summary(self.detail, self.state)["current_export"])

    def test_voice_settings_and_asset_sort_do_not_invalidate_visual_prompt(self):
        from backend.app.media_studio.services.prompt_expansion_service import PromptExpansionService
        source = {"episode": {"id": "ep", "script_text": "原文"}, "beats": self.detail["beats"], "data": {},
                  "assets": [{"id": "b", "extra": {"voice": {"preset_id": "old"}, "identities": []}}, {"id": "a", "extra": {}}]}
        request = {"target": {"kind": "director_episode"}}
        before = PromptExpansionService.source_fingerprint(source, request)
        source["assets"][0]["extra"]["voice"]["preset_id"] = "new"
        source["assets"].reverse()
        self.assertEqual(before, PromptExpansionService.source_fingerprint(source, request))
        source["assets"][0]["image_url"] = "new-look"
        self.assertNotEqual(before, PromptExpansionService.source_fingerprint(source, request))

    def test_attributed_legacy_director_imports_whole_without_fabricated_cuts(self):
        plan = self.detail["prompt_authoring"]["director_plan"]
        self.detail["legacy_director_output"] = {"url": "film", "job_id": "old-job", "payload": {
            "director_plan_id": plan["id"], "director_plan_revision": plan["revision"],
            "source_shots": [{"beat_id": f"s{i}"} for i in range(1, 4)]}}
        view = model.summary(self.detail)
        self.assertTrue(view["ready"])
        self.assertEqual(view["current_export"]["url"], "film")
        self.assertFalse(view["materials"][0]["verified"])
        self.assertEqual(len(view["timeline"]), 1)


class ProductionTransactionTests(unittest.TestCase):
    """Exercise actual service transactions against isolated SQLite, never project MySQL."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = sqlite3.connect(str(Path(self.tmp.name) / "production.sqlite"))
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE ai_project_episodes (id TEXT, project_id TEXT, script_text TEXT, data_json TEXT, updated_at TEXT)")
        self.db.execute("CREATE TABLE ai_project_assets (id TEXT,project_id TEXT,updated_at TEXT)")
        self.detail = detail_fixture()
        data = {**self.detail["data"], "prompt_authoring": self.detail["prompt_authoring"]}
        self.db.execute("INSERT INTO ai_project_episodes VALUES ('ep','project','原剧本',?,'')", (json.dumps(data),))
        self.db.commit()
        db = self.db
        class Cursor:
            def execute(self, sql, params=()):
                self.c = db.execute(sql.replace(" FOR UPDATE", "").replace("%s", "?"), params)
            def fetchone(self):
                row = self.c.fetchone()
                return dict(row) if row else None
            def fetchall(self):
                return [dict(r) for r in self.c.fetchall()]
        @contextmanager
        def transaction():
            with db:
                yield Cursor()
        self.transaction = transaction
        for target, replacement in [
            ("backend.app.media_studio.services.production_service.transaction_cursor", transaction),
            ("backend.app.media_studio.services.production_service.ProductionService.detail", lambda *args: self.detail),
            ("backend.app.media_studio.services.prompt_expansion_service.PromptExpansionService.hydrated_authoring_state", lambda p, r, d, b, a: d["prompt_authoring"]),
        ]:
            p = patch(target, replacement); p.start(); self.addCleanup(p.stop)

    def test_revision_conflict_rolls_back(self):
        first = ProductionService.update("project", "ep", {"expected_revision": 0, "mode": "director"}, "mode")
        self.assertEqual(first["revision"], 1)
        with self.assertRaises(ProductionConflict):
            ProductionService.update("project", "ep", {"expected_revision": 0, "mode": "shot"}, "mode")
        saved = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        self.assertEqual(saved["production"]["revision"], 1)
        self.assertEqual(saved["production"]["active_mode"], "director")

    def test_late_generation_is_retained_but_not_adopted_in_new_plan(self):
        context = ProductionService.generation_context(self.detail, "director")
        payload = {"project_id": "project", "episode_id": "ep", "production_context": context}
        data = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        data["prompt_authoring"]["director_plan"]["revision"] = 2
        self.db.execute("UPDATE ai_project_episodes SET data_json=?", (json.dumps(data),)); self.db.commit()
        ProductionService.record_output(payload, "job-old", [{"beat_id": "s1"}], "url", {"duration": 1, "verified": True, "ranges": {"s1": {"start": 0, "end": 1}}})
        saved = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])["production"]
        self.assertEqual(len(saved["modes"]["director"]["materials"]), 1)
        self.assertTrue(all(not v["adopted"] for v in saved["modes"]["director"]["versions"].values()))

    def test_generation_retry_is_idempotent_and_export_snapshot_is_frozen(self):
        context = ProductionService.generation_context(self.detail, "director")
        payload = {"project_id": "project", "episode_id": "ep", "production_context": context}
        units = [{"beat_id": f"s{i}"} for i in range(1, 4)]
        measure = {"duration": 3, "verified": True, "ranges": {f"s{i}": {"start": i - 1, "end": i} for i in range(1, 4)}}
        ProductionService.record_output(payload, "job", units, "video", measure)
        ProductionService.record_output(payload, "job", units, "video", measure)
        data = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        self.assertEqual(len(data["production"]["modes"]["director"]["materials"]), 1)
        snap = ProductionService.export_snapshot("project", "ep", {"expected_revision": 2, "production_mode": "director"})
        self.assertEqual(snap["timeline"][0]["url"], "video")
        ProductionService.record_output(payload, "new-job", [{"beat_id": "s2"}], "new-video", {"duration": 1, "verified": True, "ranges": {"s2": {"start": 0, "end": 1}}})
        state = ProductionService.update("project", "ep", {"mode": "director", "expected_revision": 4, "material_id": payload["production_material_ids"][-1]}, "adopt")
        self.assertTrue(any(c["url"] == "new-video" for c in state["timeline"]))
        self.assertEqual(snap["timeline"][0]["url"], "video")

    def test_missing_expected_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected_revision"):
            ProductionService.update("project", "ep", {"mode": "director"}, "mode")

    def test_retry_with_different_bytes_is_new_candidate_not_silent_replacement(self):
        context = ProductionService.generation_context(self.detail, "director")
        payload = {"project_id": "project", "episode_id": "ep", "production_context": context}
        measured = {"duration": 1, "verified": True, "ranges": {"s1": {"start": 0, "end": 1}}, "content_sha256": "first"}
        first = ProductionService.record_output(payload, "job", [{"beat_id": "s1"}], "original", measured)
        newer = ProductionService.record_output(payload, "job", [{"beat_id": "s1"}], "retry", {**measured, "content_sha256": "second"})
        state = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])["production"]
        self.assertNotEqual(first, newer)
        self.assertEqual(model.version(state, "director", context["plan_key"])["adopted"]["s1"], first)

    def test_dubbing_sync_does_not_overwrite_concurrent_adoption(self):
        from backend.app.media_studio.services.dubbing_service import DubbingService
        stale = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        ProductionService.update("project", "ep", {"expected_revision": 0, "mode": "director"}, "mode")
        with patch("backend.app.media_studio.services.dubbing_service.transaction_cursor", self.transaction):
            DubbingService._write_lines("project", "ep", [], data=stale)
        saved = json.loads(self.db.execute("SELECT data_json FROM ai_project_episodes").fetchone()[0])
        self.assertEqual(saved["production"]["revision"], 1)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class ProductionMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def clip(self, name, color, seconds=1):
        path = self.root / (name + ".mp4")
        media.run([media.binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=96x64:r=24:d={seconds}",
                   "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
        return path.read_bytes()

    def test_measured_frames_and_mismatch_are_not_guessed(self):
        content = self.clip("base", "red", 3)
        valid = media.measure(content, [{"beat_id": f"s{i}", "frame_count": 24} for i in range(3)])
        self.assertTrue(valid["verified"])
        self.assertEqual(valid["ranges"]["s2"], {"start": 2, "end": 3})
        invalid = media.measure(content, [{"beat_id": "s1", "frame_count": 10}, {"beat_id": "s2", "frame_count": 10}])
        self.assertFalse(invalid["verified"])
        self.assertEqual(invalid["ranges"], {})

    def test_middle_replacement_exports_exact_order_and_duration(self):
        from backend.app.media_studio.services.episode_video_service import concat_video_bytes
        parts = [self.clip("red", "red"), self.clip("green", "green"), self.clip("blue", "blue")]
        source = concat_video_bytes(parts)
        sources = {"base": source, "new": self.clip("yellow", "yellow")}
        snapshot = {"timeline": [{"material_id": "base", "url": "base", "start": 0, "end": 1},
                                 {"material_id": "new", "url": "new", "start": 0, "end": 1},
                                 {"material_id": "base", "url": "base", "start": 2, "end": 3}], "audio": []}
        output = self.root / "out.mp4"
        output.write_bytes(media.assemble(snapshot, sources.__getitem__, sources.__getitem__))
        self.assertAlmostEqual(media.probe_file(output)["duration"], 3, delta=.06)
        pixels = []
        for t in (.5, 1.5, 2.5):
            raw = media.run([media.binary("ffmpeg"), "-v", "error", "-ss", str(t), "-i", str(output), "-frames:v", "1", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
            pixels.append(tuple(raw[:3]))
        self.assertGreater(pixels[0][0], 180)
        self.assertGreater(pixels[1][0], 180); self.assertGreater(pixels[1][1], 180)
        self.assertGreater(pixels[2][2], 180)

    def test_missing_media_and_invalid_interval_fail(self):
        with self.assertRaises(KeyError):
            media.assemble({"timeline": [{"url": "missing"}], "audio": []}, {}.__getitem__, {}.__getitem__)
        content = self.clip("base", "red")
        with self.assertRaisesRegex(ValueError, "超出"):
            media.assemble({"timeline": [{"url": "base", "material_id": "m", "start": 0, "end": 4}], "audio": []}, lambda _: content, lambda _: b"")

    def test_many_short_clips_do_not_accumulate_aac_padding(self):
        content = self.clip("short", "red", .25)
        snapshot = {"timeline": [{"url": "short", "material_id": str(i), "start": 0, "end": .25} for i in range(12)], "audio": []}
        output = self.root / "many.mp4"
        output.write_bytes(media.assemble(snapshot, lambda _: content, lambda _: b""))
        info = media.probe_file(output)
        self.assertEqual(info["frames"], 72)
        meta = json.loads(media.run([media.binary("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(output)]))
        sound = next(s for s in meta["streams"] if s["codec_type"] == "audio")
        self.assertAlmostEqual(float(sound["duration"]), 3, delta=.025)

    def test_audio_replacement_is_local_and_real_overrun_fails(self):
        import array
        content = self.clip("base", "red")
        voice = self.root / "voice.wav"
        media.run([media.binary("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.1", str(voice)])
        snapshot = {"timeline": [{"material_id": "m", "url": "base", "start": 0, "end": 1}],
                    "audio": [{"material_id": "m", "audio_url": "voice", "enabled": True, "start": .2, "end": .6, "mix": "replace"}]}
        output = self.root / "mixed.mp4"
        output.write_bytes(media.assemble(snapshot, lambda _: content, lambda _: voice.read_bytes()))
        def rms(start):
            raw = media.run([media.binary("ffmpeg"), "-v", "error", "-ss", str(start), "-i", str(output), "-t", "0.06", "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"])
            samples = array.array("h", raw)
            return (sum(x * x for x in samples) / len(samples)) ** .5
        self.assertGreater(rms(.8), 500)
        self.assertLess(rms(.45), 100)
        snapshot["audio"][0]["end"] = .25
        with self.assertRaisesRegex(ValueError, "实际配音超出"):
            media.assemble(snapshot, lambda _: content, lambda _: voice.read_bytes())
