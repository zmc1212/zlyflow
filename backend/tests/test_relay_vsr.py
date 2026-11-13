from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.models import JobMode
from backend.app.relay_vsr_workflow import (
    RELAY_VSR_BUNDLE,
    RELAY_VSR_COMPONENTS_NODE,
    RELAY_VSR_CREATE_NODE,
    RELAY_VSR_MODEL_NODE,
    RELAY_VSR_OUTPUT_LABEL,
    RELAY_VSR_OUTPUT_NODE,
    RELAY_VSR_UPSCALE_NODE,
    RELAY_VSR_UPSCALE_NODE_TYPE,
    build_relay_vsr_workflow,
    relay_vsr_bundles,
    relay_vsr_memory_rejection,
    relay_vsr_missing_message,
)
from backend.app.seedvr2_upscale_workflow import UPSCALE_ENGINE_RELAYVSR, UPSCALE_ENGINES
from backend.app.workflow_registry import (
    is_relayvsr_upscale_workflow,
    is_upscale_workflow,
    workflow_for,
)
from backend.tests.app_state_guard import isolated_lifespan_state


class RelayVsrGraphTests(unittest.TestCase):
    def test_graph_keeps_source_audio_through_create_video(self) -> None:
        graph = build_relay_vsr_workflow("source.mp4")
        self.assertEqual(graph[RELAY_VSR_MODEL_NODE]["class_type"], "RelayVSRModelLoader")
        self.assertEqual(graph[RELAY_VSR_MODEL_NODE]["inputs"]["bundle"], RELAY_VSR_BUNDLE)
        self.assertIs(graph[RELAY_VSR_MODEL_NODE]["inputs"]["offload"], True)
        self.assertEqual(graph[RELAY_VSR_UPSCALE_NODE]["class_type"], RELAY_VSR_UPSCALE_NODE_TYPE)
        self.assertEqual(graph[RELAY_VSR_UPSCALE_NODE]["inputs"]["images"], [RELAY_VSR_COMPONENTS_NODE, 0])
        self.assertEqual(graph[RELAY_VSR_UPSCALE_NODE]["inputs"]["sr_ratio"], 2)
        # 音轨必须由 GetVideoComponents 交回 CreateVideo，不能走只出画面的流式节点。
        self.assertEqual(graph[RELAY_VSR_CREATE_NODE]["inputs"]["audio"], [RELAY_VSR_COMPONENTS_NODE, 1])
        self.assertEqual(graph[RELAY_VSR_CREATE_NODE]["inputs"]["images"], [RELAY_VSR_UPSCALE_NODE, 0])
        self.assertEqual(graph[RELAY_VSR_OUTPUT_NODE]["class_type"], "SaveVideo")
        self.assertEqual(graph[RELAY_VSR_OUTPUT_NODE]["inputs"]["video"], [RELAY_VSR_CREATE_NODE, 0])

    def test_graph_requires_an_uploaded_video(self) -> None:
        with self.assertRaises(ValueError):
            build_relay_vsr_workflow("  ")

    def test_output_node_is_not_reused_by_other_upscalers(self) -> None:
        self.assertNotIn(RELAY_VSR_OUTPUT_NODE, {"14", "20", "21", "22", "23", "24"})
        self.assertEqual(RELAY_VSR_OUTPUT_LABEL, "2x 细节超分")


class RelayVsrCapabilityTests(unittest.TestCase):
    def ready_info(self) -> dict:
        return {
            "RelayVSRModelLoader": {"input": {"required": {"bundle": ["COMBO", {"options": [RELAY_VSR_BUNDLE]}]}}},
            "RelayVSRUpscale": {"input": {}},
        }

    def test_bundles_support_legacy_and_new_object_info_shapes(self) -> None:
        self.assertEqual(relay_vsr_bundles(self.ready_info()), [RELAY_VSR_BUNDLE])
        legacy = {"RelayVSRModelLoader": {"input": {"required": {"bundle": [[RELAY_VSR_BUNDLE, "RelayVSR_X4"]]}}}}
        self.assertEqual(relay_vsr_bundles(legacy), [RELAY_VSR_BUNDLE, "RelayVSR_X4"])

    def test_missing_message_covers_nodes_and_weights(self) -> None:
        self.assertIsNone(relay_vsr_missing_message(self.ready_info()))
        nodes = relay_vsr_missing_message({}, comfy_url="http://192.168.10.54:8188")
        self.assertIn("RelayVSR", nodes or "")
        self.assertIn("Python 3.11", nodes or "")
        no_weights = relay_vsr_missing_message(
            {
                "RelayVSRModelLoader": {"input": {"required": {"bundle": ["COMBO", {"options": ["RelayVSR_X4"]}]}}},
                "RelayVSRUpscale": {"input": {}},
            }
        )
        self.assertIn(RELAY_VSR_BUNDLE, no_weights or "")
        self.assertIn("models/relayvsr", no_weights or "")

    def test_memory_guard_allows_480p_and_rejects_1080p_long_clip(self) -> None:
        vram = 16 * 1024 ** 3
        self.assertIsNone(relay_vsr_memory_rejection(864, 486, 121, vram_total=vram))
        reason = relay_vsr_memory_rejection(1920, 1080, 224, vram_total=vram, device_name="RTX 4080")
        self.assertIn("RelayVSR", reason or "")
        self.assertIn("RTX 4080", reason or "")
        self.assertIn("SeedVR2", reason or "")
        # 读不到显存时不能编造限额。
        self.assertIsNone(relay_vsr_memory_rejection(1920, 1080, 224, vram_total=None))


class RelayVsrRegistryTests(unittest.TestCase):
    def test_workflow_is_hidden_and_counts_as_upscale(self) -> None:
        definition = workflow_for(JobMode.RELAYVSR_UPSCALE)
        self.assertTrue(definition.hidden_from_catalog)
        self.assertEqual(definition.media_type, "video")
        self.assertEqual((definition.min_references, definition.max_references), (1, 1))
        self.assertTrue(is_relayvsr_upscale_workflow(JobMode.RELAYVSR_UPSCALE))
        self.assertTrue(is_upscale_workflow(JobMode.RELAYVSR_UPSCALE))
        self.assertFalse(is_relayvsr_upscale_workflow(JobMode.NVIDIA_RTX_VSR))
        self.assertIn(UPSCALE_ENGINE_RELAYVSR, UPSCALE_ENGINES)


class RelayVsrUploadApiTests(unittest.TestCase):
    """「AI 工具 → 视频超分」上传原片的入口：必须有 1 条视频，并按原片补齐宽高/帧数。"""

    def test_uploaded_source_creates_relayvsr_job_and_probes_shape(self) -> None:
        import tempfile

        from fastapi.testclient import TestClient

        from backend.app import main as main_module
        from backend.app.auth import csrf_token
        from backend.app.config import Settings
        from backend.app.models import UserRole

        queued: list[str] = []

        class WorkerStub:
            def __init__(self, *_args) -> None:
                self.comfy = None

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def enqueue(self, job_id: str) -> None:
                queued.append(job_id)

        class FakeProbe:
            width = 864
            height = 480
            fps = 24.0
            duration = 5.0

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            original_probe = main_module.probe_source_video
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            main_module.probe_source_video = lambda _path: FakeProbe()
            try:
                with isolated_lifespan_state(main_module.app), TestClient(main_module.app) as client:
                    user = main_module.app.state.auth_store.create_user(
                        "relay-upload", "超分上传测试", "secure-pass-123", UserRole.SUPER_ADMIN,
                        must_change_password=False,
                    )
                    token, _ = main_module.app.state.auth_store.create_session(user["id"])
                    headers = {"X-CSRF-Token": csrf_token(token)}
                    cookies = {"zly_ai_video_studio_session": token}

                    missing = client.post(
                        "/api/jobs",
                        headers=headers,
                        cookies=cookies,
                        data={"mode": JobMode.RELAYVSR_UPSCALE.value, "prompt": "细节超分", "options": "{}"},
                    )
                    self.assertEqual(missing.status_code, 422)

                    created = client.post(
                        "/api/jobs",
                        headers=headers,
                        cookies=cookies,
                        data={"mode": JobMode.RELAYVSR_UPSCALE.value, "prompt": "细节超分", "options": "{}"},
                        files={"references": ("shot.mp4", b"fake-video-bytes", "video/mp4")},
                    )
                    self.assertEqual(created.status_code, 202, created.text)
                    payload = created.json()
                    self.assertEqual(payload["mode"], JobMode.RELAYVSR_UPSCALE.value)
                    self.assertEqual(payload["options"]["width"], 864)
                    self.assertEqual(payload["options"]["height"], 480)
                    self.assertEqual(payload["options"]["frames"], 120)
                    self.assertIn(payload["id"], queued)
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker
                main_module.probe_source_video = original_probe


if __name__ == "__main__":
    unittest.main()
