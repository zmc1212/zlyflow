"""Regression coverage for Hypit handoff, target selection and export freshness."""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.director_hypit import (
    HypitError, empty_hypit_payload, find_hypit_svrun, svrun_output_name,
    write_hypit_brief, write_hypit_compile_runtime,
)


class HypitHandoffRegressionTests(unittest.TestCase):
    def test_compile_runtime_uses_workbench_endpoint_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "hypit.runtime.json"
            source.write_text(json.dumps({
                "format": "hypit.runtime-local@1",
                "dataRoot": ".hypit/runtimes/local",
                "endpoints": {
                    "comfy.h3": {
                        "use": "@zly/provider-comfy-h3",
                        "config": {"comfyUrl": "http://192.168.10.54:8188", "megapixels": 0.98},
                    },
                },
            }), encoding="utf-8")
            workspace = Path(folder) / "project"
            with patch("backend.app.director_hypit.hypit_runtime_path", return_value=source):
                with patch("backend.app.director_hypit.hypit_poc_root", return_value=Path(folder)):
                    overlay = write_hypit_compile_runtime(workspace, megapixels=0.6, comfy_url="https://remote.example/comfy/")
            data = json.loads(overlay.read_text(encoding="utf-8"))
            self.assertEqual(data["endpoints"]["comfy.h3"]["config"]["megapixels"], 0.6)
            self.assertEqual(data["endpoints"]["comfy.h3"]["config"]["comfyUrl"], "https://remote.example/comfy")
            self.assertTrue(Path(data["dataRoot"]).is_absolute())
            original = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(original["endpoints"]["comfy.h3"]["config"]["megapixels"], 0.98)

    def test_run_selection_uses_final_video_not_alphabetically_first_material(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            (workspace / "runs").mkdir()
            material = workspace / "runs" / "a-roll.svrun"
            material.write_text('<svrun><target output="cast.video"/></svrun>', encoding="utf-8")
            final = workspace / "runs" / "clone.svrun"
            final.write_text("<svrun><!-- output=\"wrong.video\" --><target output='voice.audio'/><target output='final.video'/></svrun>", encoding="utf-8")
            self.assertEqual(find_hypit_svrun(workspace), final)
            self.assertEqual(svrun_output_name(final), "final.video")
            (workspace / "runs" / "old.svrun").write_text(final.read_text(), encoding="utf-8")
            with self.assertRaisesRegex(HypitError, "多个"):
                find_hypit_svrun(workspace)

    def test_run_rejects_missing_or_ambiguous_video_target(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.svrun"
            for xml in ['<svrun/>', '<svrun><target output="voice.audio"/></svrun>', '<svrun><target output="a.video"/><target output="b.video"/></svrun>']:
                path.write_text(xml, encoding="utf-8")
                with self.assertRaises(HypitError):
                    svrun_output_name(path)

    def test_brief_handoff_tracks_latest_request_without_overwriting_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            (workspace / "notes").mkdir()
            analysis = workspace / "notes" / "ANALYSIS.md"
            analysis.write_text("agent notes", encoding="utf-8")
            payload = empty_hypit_payload(title="产品")
            payload["brief"] = "换新台词"
            brief = write_hypit_brief(workspace, payload)
            self.assertIn("换新台词", brief.read_text(encoding="utf-8"))
            payload["brief"] = "保留原声"
            write_hypit_brief(workspace, payload)
            self.assertIn("保留原声", brief.read_text(encoding="utf-8"))
            self.assertNotIn("换新台词", brief.read_text(encoding="utf-8"))
            self.assertEqual(analysis.read_text(encoding="utf-8"), "agent notes")


class HypitCompileResultTests(unittest.TestCase):
    def test_compile_requires_new_export_and_workbench_runtime(self) -> None:
        from backend.app.director_operations import DirectorOperationService

        for build_log, exported, success in [
            ("finished without receipt", b"new video", False),
            ("Build bld_new", None, False),
            ("Build bld_new", b"", False),
            ("Build bld_new", b"new video", True),
        ]:
            with self.subTest(build_log=build_log, exported=exported), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                (workspace / "runs").mkdir()
                (workspace / "notes").mkdir()
                (workspace / "runs" / "clone.svrun").write_text('<svrun><target output="final.video"/></svrun>', encoding="utf-8")
                final = workspace / "notes" / "final.mp4"
                final.write_bytes(b"previous result")
                payload = empty_hypit_payload()
                payload["result"] = {"path": str(final), "url": "/previous", "buildId": "bld_old"}
                record = {"payload": payload, "content_revision": 1}
                store = MagicMock()
                store.get_director_project.side_effect = lambda _: deepcopy(record)
                store.get_comfy_settings.return_value = {"base_url": "https://remote.example/comfy"}

                def save(_project_id, *, payload, **_kwargs):
                    record["payload"] = deepcopy(payload)
                    record["content_revision"] += 1
                    return deepcopy(record)

                store.update_director_project.side_effect = save
                service = DirectorOperationService(store, llm_provider=None, worker=None, resource_storage=None)
                service._check_cancelled = MagicMock()
                service._emit = MagicMock()
                calls = []

                def run(command, args, **kwargs):
                    calls.append((command, args))
                    if command == "build":
                        return build_log
                    if command == "get" and exported is not None:
                        Path(args[args.index("--to") + 1]).write_bytes(exported)
                    return "ok"

                with patch("backend.app.director_hypit.hypit_workspace", return_value=workspace), \
                     patch("backend.app.director_hypit.reap_hypit_compile_orphans", return_value=[]), \
                     patch("backend.app.director_hypit.run_hypit", side_effect=run):
                    operation = {"id": "director-op-test", "project_id": "p", "owner_user_id": "u"}
                    if success:
                        service._hypit_compile_thread(operation)
                        self.assertEqual(final.read_bytes(), b"new video")
                        self.assertEqual(record["payload"]["result"]["buildId"], "bld_new")
                        self.assertIn("?build=bld_new", record["payload"]["result"]["url"])
                        build_args = next(args for cmd, args in calls if cmd == "build")
                        get_args = next(args for cmd, args in calls if cmd == "get")
                        self.assertNotIn("--runtime", get_args)  # CLI get uses the Build receipt.
                        overlay = json.loads(Path(build_args[build_args.index("--runtime") + 1]).read_text())
                        self.assertEqual(overlay["endpoints"]["comfy.h3"]["config"]["comfyUrl"], "https://remote.example/comfy")
                    else:
                        with self.assertRaises(HypitError):
                            service._hypit_compile_thread(operation)
                        self.assertEqual(final.read_bytes(), b"previous result")
                        self.assertEqual(record["payload"]["result"]["buildId"], "bld_old")
                        self.assertEqual(record["payload"]["compile"]["status"], "failed")
                    self.assertFalse(list((workspace / "notes").glob("*.pending.mp4")))



if __name__ == "__main__":
    unittest.main()

