from __future__ import annotations

import sys
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.comfy_service import ComfyCancelled, ComfyService
from backend.app.h3_motion_transfer_workflow import (
    MOTION_TRANSFER_DEFAULT_PROMPT,
    MOTION_TRANSFER_OUTPUT_NODE,
    build_h3_motion_transfer_workflow,
    resolve_motion_transfer_dimensions,
    snap_h3_length,
    snap_h3_size,
)
from backend.app.models import JobMode, JobStatus, UserRole
from backend.app.config import Settings
from backend.app.auth import AuthStore, csrf_token
from backend.app.storage import JobStore
from backend.app.video_analysis import VideoAnalysisError, VideoProbe
from backend.app.motion_transfer_media import validate_motion_video
from backend.app.workflow_registry import (
    MOTION_TRANSFER_OPTION_SCHEMA,
    is_local_comfy_job,
    is_motion_transfer_workflow,
    normalize_options,
    workflow_for,
)


class MotionTransferRegistryTests(unittest.TestCase):
    def test_registry_entry_is_catalog_visible_with_paired_references(self) -> None:
        definition = workflow_for(JobMode.MINIMAX_H3_MOTION_TRANSFER)
        self.assertEqual(definition.id, JobMode.MINIMAX_H3_MOTION_TRANSFER.value)
        self.assertFalse(definition.hidden_from_catalog)
        self.assertEqual(definition.catalog_group, "official_h3")
        self.assertEqual(definition.media_type, "video")
        self.assertEqual((definition.min_references, definition.max_references), (2, 2))
        self.assertEqual(definition.reference_labels, ("角色形象图", "动作参考视频"))
        self.assertTrue(definition.accepts_video_reference)
        self.assertFalse(definition.accepts_audio_reference)
        self.assertEqual(definition.reference_kind(2), "video")
        self.assertEqual(definition.default_prompt, MOTION_TRANSFER_DEFAULT_PROMPT)

    def test_option_schema_layers_follow_product_standard(self) -> None:
        properties = MOTION_TRANSFER_OPTION_SCHEMA["properties"]
        primary = [k for k, v in properties.items() if v["ui_group"] == "primary"]
        advanced = [k for k, v in properties.items() if v["ui_group"] == "advanced"]
        internal = [k for k, v in properties.items() if v["ui_group"] == "internal"]
        self.assertEqual(sorted(primary), ["aspect_ratio", "control_strength", "duration"])
        self.assertEqual(sorted(advanced), ["render_quality", "seed"])
        self.assertLessEqual(len(primary), 4)
        self.assertLessEqual(len(advanced), 4)
        self.assertIn("width", internal)
        self.assertIn("length", internal)
        self.assertIn("steps", internal)

    def test_normalize_options_returns_schema_defaults(self) -> None:
        normalized = normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, {})
        self.assertEqual(normalized["control_strength"], 1.0)
        self.assertEqual(normalized["aspect_ratio"], "16:9")
        self.assertEqual(normalized["duration"], "5s")
        self.assertEqual(normalized["steps"], 20)
        self.assertEqual(normalized["fps"], 24)
        self.assertEqual((normalized["width"], normalized["height"], normalized["length"]), (864, 480, 124))
        # 未在 schema 中声明的提交键不应透传进生效参数。
        self.assertNotIn("prompt", normalized)

    def test_fixed_seed_and_quality_survive_repeated_normalization(self) -> None:
        normalized = normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, {
            "aspect_ratio": "9:16", "duration": "15s", "render_quality": "preview", "seed": 123,
        })
        self.assertEqual((normalized["width"], normalized["height"], normalized["length"]), (480, 864, 362))
        self.assertEqual(normalized["steps"], 8)
        self.assertEqual(normalized["seed"], 123)
        self.assertEqual(normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, normalized), normalized)
        for seed in [-1, True, "12", 2147483648]:
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, {"seed": seed})

    def test_motion_transfer_occupies_serial_video_worker(self) -> None:
        self.assertTrue(is_motion_transfer_workflow(JobMode.MINIMAX_H3_MOTION_TRANSFER))
        self.assertTrue(is_local_comfy_job(JobMode.MINIMAX_H3_MOTION_TRANSFER))


class MotionTransferDimensionTests(unittest.TestCase):
    def test_dimensions_follow_official_presets(self) -> None:
        self.assertEqual(resolve_motion_transfer_dimensions("16:9", "5s"), (864, 480, 124))
        self.assertEqual(resolve_motion_transfer_dimensions("9:16", "10s"), (480, 864, 243))
        self.assertEqual(resolve_motion_transfer_dimensions("1:1", "15s"), (640, 640, 362))

    def test_snappers_keep_h3_grid_constraints(self) -> None:
        self.assertEqual(snap_h3_length(120), 124)
        self.assertEqual(snap_h3_length(362), 362)
        self.assertEqual(snap_h3_length(1), 29)
        self.assertEqual(snap_h3_size(0), 32)
        self.assertEqual(snap_h3_size(850), 832)


class MotionTransferGraphTests(unittest.TestCase):
    def test_graph_maps_identity_motion_and_control_wiring(self) -> None:
        graph = build_h3_motion_transfer_workflow(
            "character.png", "dance.mp4", "跳舞", width=864, height=480, length=124, seed=42,
        )
        self.assertEqual(graph["1"]["class_type"], "LoadImage")
        self.assertEqual(graph["1"]["inputs"]["image"], "character.png")
        self.assertEqual(graph["2"]["class_type"], "LoadVideo")
        self.assertEqual(graph["2"]["inputs"]["file"], "dance.mp4")
        # 身份锁定:角色图进 ref_images autogrow 槽位 0。
        self.assertEqual(graph["12"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(graph["12"]["inputs"]["ref_images"], {"0": ["1", 0]})
        self.assertEqual(graph["12"]["inputs"]["length"], 124)
        # 动作锁定:骨架序列进 Fun ControlNet 的 control_video。
        self.assertEqual(graph["16"]["class_type"], "MiniMaxH3FunControlNetApply")
        self.assertEqual(graph["16"]["inputs"]["control_video"], ["8", 0])
        self.assertEqual(graph["16"]["inputs"]["strength"], 1.0)
        self.assertEqual(graph["16"]["inputs"]["model"], ["10", 0])
        # 采样链路与成片节点。
        self.assertEqual(graph["21"]["class_type"], "SamplerCustomAdvanced")
        self.assertEqual(graph["21"]["inputs"]["latent_image"], ["12", 1])
        self.assertEqual(graph[MOTION_TRANSFER_OUTPUT_NODE]["class_type"], "SaveVideo")
        self.assertEqual(graph[MOTION_TRANSFER_OUTPUT_NODE]["inputs"]["video"], ["24", 0])

    def test_graph_clamps_strength_steps_and_snaps_geometry(self) -> None:
        graph = build_h3_motion_transfer_workflow(
            "character.png", "dance.mp4", "  ", width=850, height=500, length=120,
            control_strength=5.0, steps=999, seed=7,
        )
        self.assertEqual(graph["16"]["inputs"]["strength"], 1.0)
        self.assertEqual(graph["17"]["inputs"]["noise_seed"], 7)
        self.assertEqual(graph["19"]["inputs"]["steps"], 40)
        self.assertEqual(graph["12"]["inputs"]["width"], 832)
        self.assertEqual(graph["12"]["inputs"]["height"], 480)
        self.assertEqual(graph["12"]["inputs"]["length"], 124)
        # 空提示词回落到产品默认提示词。
        self.assertEqual(graph["12"]["inputs"]["prompt"], MOTION_TRANSFER_DEFAULT_PROMPT)


class MotionTransferServiceWiringTests(unittest.TestCase):
    def test_service_has_dispatch_and_recovery_branches(self) -> None:
        self.assertTrue(hasattr(ComfyService, "_run_motion_transfer"))
        source = Path(ComfyService.__module__.replace(".", "/") + ".py")
        # completed_outputs 恢复分支必须覆盖动作迁移模式。
        text = source.read_text(encoding="utf-8")
        self.assertIn("MINIMAX_H3_MOTION_TRANSFER", text)

    def test_recovery_reads_the_existing_motion_output_without_resubmitting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ComfyService(Settings(workspace_dir=Path(directory)))
            service.download = Mock()
            service.output_payload = Mock(return_value={"kind": "video", "path": "result.mp4"})
            record = {"outputs": {MOTION_TRANSFER_OUTPUT_NODE: {"images": [{
                "filename": "result.mp4", "subfolder": "video", "type": "output",
            }]}}}
            result = service.completed_outputs(JobMode.MINIMAX_H3_MOTION_TRANSFER, record)
            self.assertEqual(result[0]["kind"], "video")
            self.assertEqual(service.download.call_args.args[0]["filename"], "result.mp4")
            self.assertEqual(service.download.call_args.args[1], "h3_motion_transfer")

    def test_cancelled_motion_does_not_upload_or_submit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ComfyService(Settings(workspace_dir=Path(directory)))
            service.upload_image = Mock()
            service.run_workflow = Mock()
            with self.assertRaises(ComfyCancelled):
                service.run(JobMode.MINIMAX_H3_MOTION_TRANSFER, ["character.png", "dance.mp4"], "动作", "", None,
                            {}, Mock(), Mock(), Mock(), is_cancelled=lambda: True)
            service.upload_image.assert_not_called()
            service.run_workflow.assert_not_called()

    def test_service_submits_one_identity_and_one_prepared_motion_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ComfyService(Settings(workspace_dir=Path(directory)))
            service.upload_image = Mock(return_value="character.png")
            service.upload_video = Mock(return_value="motion.mp4")
            service.run_workflow = Mock(return_value={"outputs": {"28": {"images": [{
                "filename": "result.mp4", "subfolder": "video", "type": "output",
            }]}}})
            service.download = Mock()
            service.output_payload = Mock(return_value={"kind": "video", "path": "result.mp4", "label": "动作迁移"})
            options = normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, {"seed": 42, "render_quality": "preview"})
            with patch("backend.app.comfy_service.prepare_motion_video", side_effect=lambda src, dest, **kw: dest) as prepare:
                result = service.run(
                    JobMode.MINIMAX_H3_MOTION_TRANSFER, ["character-local.png", "motion-local.mp4"], "跳舞", "", None,
                    options, Mock(), Mock(), Mock(), is_cancelled=lambda: False,
                )
            self.assertEqual(result[0]["kind"], "video")
            service.upload_image.assert_called_once_with("character-local.png", "motion_transfer_character")
            self.assertEqual(service.upload_video.call_count, 1)
            self.assertEqual(prepare.call_args.kwargs, {"fps": 24, "length": 124})
            graph = service.run_workflow.call_args.args[0]
            self.assertEqual(graph["17"]["inputs"]["noise_seed"], 42)
            self.assertEqual(graph["19"]["inputs"]["steps"], 8)
            self.assertEqual(graph["12"]["inputs"]["prompt"], "跳舞")
            self.assertFalse(list(service.settings.staging_dir.iterdir()))


class MotionTransferApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from backend.app import main

        self.main = main
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.settings = Settings(workspace_dir=self.root, data_dir_override=str(self.root / "data"))
        self.store = JobStore(self.root / "test.db")
        self.auth = AuthStore(self.root / "test.db")
        self.worker = SimpleNamespace(enqueue=AsyncMock())
        self.stack.enter_context(patch.object(main, "settings", self.settings))
        for name, value in {"store": self.store, "auth_store": self.auth, "worker": self.worker}.items():
            self.stack.enter_context(patch.object(main.app.state, name, value, create=True))
        self.probe = self.stack.enter_context(patch(
            "backend.app.motion_transfer_media.probe_video", return_value=VideoProbe(640, 360, 30, 16.0),
        ))
        self.user = self.auth.create_user("motion-test", "动作验收", "test-password-123", UserRole.EMPLOYEE, must_change_password=False)
        token, _ = self.auth.create_session(self.user["id"])
        self.client = TestClient(main.app)  # No lifespan: never connect to the production database or start workers.
        self.addCleanup(self.client.close)
        self.client.cookies.set("zly_ai_video_studio_session", token)
        self.headers = {"X-CSRF-Token": csrf_token(token)}
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
        self.png = buffer.getvalue()
        self.video = b"\x00\x00\x00\x18ftypisom" + b"test-motion" * 4

    def files(self, video_type: str = "video/mp4") -> list:
        return [("references", ("character.png", self.png, "image/png")),
                ("references", ("dance.mp4", self.video, video_type))]

    def create(self, *, options: dict | None = None, files: list | None = None, prompt: str = ""):
        data = {"mode": JobMode.MINIMAX_H3_MOTION_TRANSFER.value, "prompt": prompt}
        if options is not None:
            data["options"] = json.dumps(options)
        return self.client.post("/api/jobs", data=data, files=self.files() if files is None else files, headers=self.headers)

    def test_modes_api_exposes_motion_transfer_with_layered_options(self) -> None:
        with patch.object(self.main, "listed_workflows", return_value=[workflow_for(JobMode.MINIMAX_H3_MOTION_TRANSFER)]):
            payload = self.client.get("/api/modes").json()
        modes = {item["id"]: item for item in payload["modes"]}
        self.assertIn(JobMode.MINIMAX_H3_MOTION_TRANSFER.value, modes)
        mode = modes[JobMode.MINIMAX_H3_MOTION_TRANSFER.value]
        self.assertEqual(mode["min_references"], 2)
        self.assertEqual(mode["max_references"], 2)
        self.assertEqual(mode["reference_labels"], ["角色形象图", "动作参考视频"])
        self.assertTrue(mode["accepts_video_reference"])
        references = next(item for item in mode["parameters"] if item["name"] == "references")
        self.assertEqual(references["content_type"], "image/*,video/*")
        prompt = next(item for item in mode["parameters"] if item["name"] == "prompt")
        self.assertFalse(prompt["required"])
        options_param = next(item for item in mode["parameters"] if item["name"] == "options")
        properties = options_param["schema"]["properties"]
        visible_groups = {"primary": [], "advanced": [], "internal": []}
        for name, definition in properties.items():
            visible_groups[definition["ui_group"]].append(name)
        self.assertEqual(sorted(visible_groups["primary"]), ["aspect_ratio", "control_strength", "duration"])
        self.assertEqual(sorted(visible_groups["advanced"]), ["render_quality", "seed"])

    def test_image_and_video_submission_uses_default_and_preserves_effective_options(self) -> None:
        response = self.create(options={"seed": 42, "duration": "15s", "aspect_ratio": "9:16"})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job["prompt"], MOTION_TRANSFER_DEFAULT_PROMPT)
        self.assertEqual(job["options"]["seed"], 42)
        self.assertEqual((job["options"]["width"], job["options"]["height"], job["options"]["length"]), (480, 864, 362))
        self.assertEqual([item["kind"] for item in job["references"]], ["image", "video"])
        self.assertEqual(job["rounds"][0]["options"], job["options"])
        runtime = {item["name"]: item for item in job["request_parameters"]}
        self.assertEqual(runtime["options.steps"]["visibility"], "internal")
        self.worker.enqueue.assert_awaited_once_with(job["id"])
        for reference in [job["references"][1], job["rounds"][0]["references"][1]]:
            preview = self.client.get(reference["url"])
            self.assertEqual(preview.headers["content-type"], "video/mp4")
            self.assertEqual(preview.content, self.video)

    def test_binary_video_content_type_is_validated_by_probe(self) -> None:
        self.assertEqual(self.create(files=self.files("application/octet-stream")).status_code, 202)
        self.probe.assert_called_once()

    def test_wrong_roles_and_missing_video_are_rejected_without_queueing(self) -> None:
        cases = [
            (self.files()[::-1], "第 1 项"),
            ([self.files()[0], self.files()[0]], "第 2 项"),
            ([self.files()[0]], "动作参考视频"),
        ]
        for files, text in cases:
            with self.subTest(text=text):
                response = self.create(files=files)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(text, response.json()["detail"])
        self.worker.enqueue.assert_not_awaited()
        self.assertFalse(list(self.settings.uploads_dir.rglob("*.png")))

    def test_unreadable_or_too_short_motion_rejects_and_cleans_partial_uploads(self) -> None:
        for probe in [VideoProbe(640, 360, 24, 2.0), VideoAnalysisError("no video stream")]:
            with self.subTest(probe=probe):
                self.probe.side_effect = probe if isinstance(probe, Exception) else None
                self.probe.return_value = probe
                response = self.create()
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("动作参考视频", response.json()["detail"])
                self.assertFalse(list(self.settings.uploads_dir.rglob("*.png")))
                self.assertFalse(list(self.settings.uploads_dir.rglob("*.mp4")))
        self.worker.enqueue.assert_not_awaited()

    def test_oversized_second_file_leaves_no_partial_references(self) -> None:
        with patch.object(self.main, "MAX_UPLOAD_BYTES", len(self.png) + 5):
            files = self.files()
            files[1] = ("references", ("dance.mp4", b"x" * 200, "video/mp4"))
            response = self.create(files=files)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(list(self.settings.uploads_dir.rglob("*.png")))
        self.assertFalse(list(self.settings.uploads_dir.rglob("*.mp4")))

    def test_normal_image_workflow_still_rejects_videos_and_requires_prompt(self) -> None:
        for prompt, files, detail in [("", [self.files()[0]], "提示词"), ("画面", self.files(), "图片")]:
            response = self.client.post("/api/jobs", headers=self.headers, data={
                "mode": JobMode.MINIMAX_H3_I2V.value, "prompt": prompt,
            }, files=files)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn(detail, response.json()["detail"])

    def test_round_upload_and_reuse_keep_video_and_random_seed_semantics(self) -> None:
        job = self.create(options={"seed": 0}).json()
        self.store.update(job["id"], status=JobStatus.SUCCEEDED, stage="完成")
        response = self.client.post(f"/api/jobs/{job['id']}/rounds", headers=self.headers, data={"prompt": ""})
        self.assertEqual(response.status_code, 202, response.text)
        second = response.json()
        self.assertEqual(second["reference_count"], 2)
        self.assertNotEqual(second["options"]["seed"], job["options"]["seed"])
        self.store.update(job["id"], status=JobStatus.SUCCEEDED, stage="完成")
        response = self.client.post(f"/api/jobs/{job['id']}/rounds", headers=self.headers,
                                    data={"prompt": "动作", "options": '{"seed":123}'}, files=self.files())
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["options"]["seed"], 123)


class MotionVideoValidationTests(unittest.TestCase):
    def test_duration_and_corrupt_inputs_return_actionable_errors(self) -> None:
        with patch("backend.app.motion_transfer_media.probe_video", return_value=VideoProbe(640, 360, 24, 4.98)):
            validate_motion_video(Path("video.mp4"), "5s")
            with self.assertRaisesRegex(ValueError, "更短"):
                validate_motion_video(Path("video.mp4"), "10s")
        with patch("backend.app.motion_transfer_media.probe_video", side_effect=VideoAnalysisError("invalid")):
            with self.assertRaisesRegex(ValueError, "无法读取"):
                validate_motion_video(Path("video.mp4"), "5s")


if __name__ == "__main__":
    unittest.main()
