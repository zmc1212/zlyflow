from __future__ import annotations

import tempfile
import unittest
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import local_video_studio as legacy

from backend.app.auth import AuthStore, csrf_token, validate_password, verify_password
from backend.app.config import Settings
from backend.app.models import JobMode, JobStatus
from backend.app.main import BROWSER_LOCAL_COMFY_VIEW_URL, DesktopDeliveryTickets, app, browser_direct_view_url, clear_login_failures_for_username, current_user, login_failures, public_job
from backend.app.comfy_service import ComfyQueuePrompt, ComfyService, ComfyUnavailable, resolve_reference_prompt
from backend.app.minimax_h3_workflow import build_minimax_h3_workflow
from backend.app.minimax_h3_t8_workflow import build_minimax_h3_t8_workflow
from backend.app.storage import JobStore
from backend.app.resource_storage import BrowserLocalStagingStorage, BrowserStreamStorage, create_resource_storage
from backend.app.models import UserRole
from backend.app.worker import JobWorker
from backend.app.workflow_registry import (
    h3_dimensions, normalize_options, validate_option_relationships, validate_references,
)
from backend.app.workflow_registry import WORKFLOWS, workflow_for


class WorkflowTests(unittest.TestCase):
    def test_reference_tokens_are_resolved_before_generation(self) -> None:
        prompt = resolve_reference_prompt("让 @图2 站在 @图1 中，采用 @图3 色调", 3)
        self.assertNotIn("@图", prompt)
        self.assertIn("主体参考图", prompt)
        self.assertIn("参考图约束", prompt)
        with self.assertRaises(legacy.ComfyError):
            resolve_reference_prompt("使用 @图2", 1)

    def test_image_workflow_replaces_prompt_size_and_seed(self) -> None:
        workflow = legacy.build_text_to_image_workflow("测试提示词", "不要水印", "横版 1280 x 720")
        self.assertEqual(workflow[legacy.T2I_PROMPT_NODE]["inputs"]["text"], "测试提示词")
        self.assertEqual(workflow[legacy.T2I_NEGATIVE_PROMPT_NODE]["inputs"]["text"], "不要水印")
        self.assertEqual(workflow[legacy.T2I_LATENT_NODE]["inputs"]["width"], 1280)
        self.assertEqual(workflow[legacy.T2I_LATENT_NODE]["inputs"]["height"], 720)
        self.assertIsInstance(workflow[legacy.T2I_SEED_NODE]["inputs"]["seed"], int)

    def test_video_workflows_preserve_output_nodes(self) -> None:
        flux = legacy.build_flux_workflow(("a.png", "b.png", "c.png"), "首帧")
        ltx = legacy.build_ltx_workflow("frame.png", "运镜")
        vace = legacy.build_vace_multi_reference_workflow(("a.png", "b.png", "c.png"), "视频")
        self.assertEqual(flux[legacy.FLUX_OUTPUT_NODE]["class_type"], "SaveImage")
        self.assertEqual(ltx[legacy.LTX_IMAGE_NODE]["inputs"]["image"], "frame.png")
        self.assertIn(legacy.VACE_OUTPUT_NODE, vace)

    def test_vace_workflow_uses_the_multi_reference_node_contract(self) -> None:
        workflow = legacy.build_vace_multi_reference_workflow(("scene.png", "subject.png", "style.png"), "video")
        vace_node = workflow["12"]
        self.assertEqual(vace_node["class_type"], "WanVaceMultiReference")
        self.assertEqual(vace_node["inputs"]["reference_images"], ["11", 0])
        self.assertNotIn("reference_image", vace_node["inputs"])
        self.assertEqual(workflow["2"]["inputs"]["shift"], 16.0)
        self.assertEqual(workflow["13"]["inputs"]["steps"], 50)
        self.assertEqual(workflow["13"]["inputs"]["cfg"], 5.0)

    def test_legacy_workflows_are_not_registered_or_accepted(self) -> None:
        registered = {workflow.id for workflow in WORKFLOWS}
        self.assertNotIn(JobMode.IMAGE, registered)
        self.assertNotIn(JobMode.LTX_VIDEO, registered)
        self.assertNotIn(JobMode.VACE_VIDEO, registered)
        with self.assertRaisesRegex(ValueError, "已从当前工作台移除"):
            validate_references(JobMode.IMAGE, [])

    def test_minimax_h3_reference_workflow_grows_with_uploaded_images(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "16:9", "quality": "1K", "duration": 5})
        workflow = build_minimax_h3_workflow(
            JobMode.MINIMAX_H3_R2V,
            "Use <Picture 1> and <Picture 2>.",
            ["character.png", "scene.png"],
            options,
            42,
        )
        self.assertEqual(h3_dimensions(options), (608, 352))
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(workflow["5"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
        self.assertEqual(workflow["5"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
        self.assertEqual(workflow["14"]["class_type"], "SaveVideo")

    def test_minimax_h3_accepts_arbitrary_positive_aspect_ratios(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "2:3", "quality": "1K", "duration": 5})
        self.assertEqual(options["aspect_ratio"], "2:3")
        self.assertEqual(h3_dimensions(options), (384, 576))
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "2:0"})
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_R2V, {"unrecognized": True})

    def test_minimax_h3_quality_presets_map_to_internal_megapixels_and_accept_legacy_mp(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T2V, {"quality": "4K"})
        self.assertEqual(options["quality"], "4K")
        self.assertEqual(options["megapixels"], 0.5)
        legacy = normalize_options(JobMode.MINIMAX_H3_T2V, {"megapixels": 0.3})
        self.assertEqual(legacy["quality"], "2K")
        self.assertEqual(legacy["megapixels"], 0.3)

    def test_minimax_h3_image_to_video_uses_first_and_last_frame(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_I2V, {})
        workflow = build_minimax_h3_workflow(JobMode.MINIMAX_H3_I2V, "Camera slowly pulls back.", ["start.png", "end.png"], options, 42)
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(workflow["5"]["inputs"]["first_frame"], ["20", 0])
        self.assertEqual(workflow["5"]["inputs"]["last_frame"], ["21", 0])
        with self.assertRaises(ValueError):
            validate_references(JobMode.MINIMAX_H3_R2V, [])

    def test_t8_all_reference_builds_multirate_graph_and_grows_references(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {})
        workflow = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
            "Use <Picture 1> and <Picture 2>.",
            ["character.png", "scene.png"],
            options,
        )
        self.assertEqual(workflow["8"]["class_type"], "MiniMaxH3MultiRateSamplerEXPT8")
        self.assertEqual(workflow["8"]["inputs"]["video_steps"], 8)
        self.assertEqual(workflow["8"]["inputs"]["audio_steps"], 10)
        self.assertEqual(workflow["3"]["inputs"]["task_type"], "Ref2VA")
        self.assertEqual(workflow["3"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
        self.assertEqual(workflow["3"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
        self.assertEqual(workflow["14"]["class_type"], "VHS_VideoCombine")
        self.assertTrue(workflow["14"]["inputs"]["save_output"])

    def test_t8_dual_clock_builds_source_sampler_contract(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {})
        workflow = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "Rain on a roof.", [], options,
        )
        self.assertEqual(workflow["8"]["class_type"], "MiniMaxH3DualClockSamplerT8")
        self.assertEqual(workflow["8"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["3"]["inputs"]["task_type"], "T2VA")
        self.assertEqual(workflow["16"]["class_type"], "LoraLoaderBypassModelOnly")

    def test_t8_options_validate_ranges_and_cross_field_rules(self) -> None:
        mode = JobMode.MINIMAX_H3_T8_ALL_REFERENCE
        normalized = normalize_options(mode, {"quality": "2K", "video_steps": 6, "audio_steps": 8})
        self.assertEqual(normalized["quality"], "2K")
        self.assertEqual(normalized["megapixels"], 1.0)
        self.assertEqual(normalized["video_steps"], 6)
        self.assertIsInstance(normalized["seed"], int)
        self.assertNotEqual(normalized["seed"], 123456789)
        self.assertNotEqual(normalized["seed"], normalize_options(mode, {"quality": "2K"})["seed"])
        with self.assertRaises(ValueError):
            normalize_options(mode, {"audio_steps": 3, "video_steps": 4})
        with self.assertRaises(ValueError):
            normalize_options(mode, {"save_output": False})
        with self.assertRaises(ValueError):
            validate_option_relationships(mode, normalize_options(mode, {"task_type": "Ref2VA"}), 0)


class ApiDocumentationTests(unittest.TestCase):
    def test_openapi_schema_contains_all_public_api_operations(self) -> None:
        schema = app.openapi()
        self.assertEqual(schema["info"]["title"], "ZLY AI 视频创作平台 API")
        self.assertIn("局域网 IPv4", schema["info"]["description"])
        self.assertIn("/api/jobs", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/references/{reference_index}", schema["paths"])
        self.assertIn("/api/auth/login", schema["paths"])
        self.assertIn("/api/admin/users", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/outputs/{output_index}/delivered", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/outputs/{output_index}/desktop-ticket", schema["paths"])
        self.assertIn("/api/modes/{mode_id}", schema["paths"])
        self.assertIn("/api/providers/grs/balance", schema["paths"])
        balance_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/providers/grs/balance")
        self.assertIn(current_user, [dependency.call for dependency in balance_route.dependant.dependencies])
        self.assertIn("multipart/form-data", schema["paths"]["/api/jobs"]["post"]["requestBody"]["content"])
        self.assertIn("/api/openapi.json", app.openapi_url)
        self.assertIn("APIKeyCookie", schema["components"]["securitySchemes"])

    def test_mode_parameter_schema_is_derived_from_the_registry(self) -> None:
        image_options = {item["name"]: item for item in workflow_for(JobMode.GRS_GPT_IMAGE_2).payload()["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(image_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(image_options["aspect_ratio"]["ui_companion"], "resolution")
        self.assertEqual(image_options["aspect_ratio"]["ui_options"][0], {"value": "auto", "label": "自动"})
        self.assertEqual(image_options["resolution"]["enum"], ["1K"])
        vip_image_options = {item["name"]: item for item in workflow_for(JobMode.GRS_GPT_IMAGE_2_VIP).payload()["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(vip_image_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(vip_image_options["aspect_ratio"]["ui_companion"], "resolution")
        self.assertIn({"value": "1:3", "label": "1:3"}, vip_image_options["aspect_ratio"]["ui_options"])
        self.assertEqual(vip_image_options["resolution"]["enum"], ["1K", "2K", "4K", "CUSTOM"])
        h3 = workflow_for(JobMode.MINIMAX_H3_R2V).payload()
        parameters = {item["name"]: item for item in h3["parameters"]}
        self.assertEqual(parameters["mode"]["values"], ["minimax-h3-r2v"])
        self.assertEqual(parameters["references"]["max_items"], 9)
        self.assertEqual(parameters["options"]["schema"]["properties"]["duration"]["maximum"], 15)
        self.assertNotIn("enum", parameters["options"]["schema"]["properties"]["aspect_ratio"])
        self.assertIn("pattern", parameters["options"]["schema"]["properties"]["aspect_ratio"])
        self.assertEqual(parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_companion"], "quality")
        self.assertEqual(parameters["options"]["schema"]["properties"]["duration"]["ui_control"], "duration-slider")
        self.assertEqual(
            parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_options"][0],
            {"value": "16:9", "label": "16:9 横屏"},
        )
        t8 = workflow_for(JobMode.MINIMAX_H3_T8_ALL_REFERENCE).payload()
        t8_options = {item["name"]: item for item in t8["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(t8_options["video_steps"]["default"], 8)
        self.assertEqual(t8_options["audio_steps"]["default"], 10)
        self.assertEqual(t8_options["reserved_vram"]["unit"], "GB")
        self.assertIn("output_format", t8_options)
        self.assertTrue(all(option["ui_group"] in {"primary", "advanced", "internal"} for option in t8_options.values()))
        self.assertEqual(t8_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(t8_options["duration"]["ui_control"], "duration-slider")
        self.assertEqual(
            {name for name, option in t8_options.items() if option["ui_group"] == "primary"},
            {"aspect_ratio", "duration"},
        )
        self.assertEqual(
            {name for name, option in t8_options.items() if option["ui_group"] == "advanced"},
            {"quality"},
        )
        self.assertEqual(t8_options["megapixels"]["ui_group"], "internal")
        self.assertEqual(t8_options["seed"]["ui_group"], "internal")
        self.assertEqual(t8_options["task_type"]["ui_group"], "internal")
        self.assertEqual(t8_options["video_steps"]["ui_group"], "internal")
        self.assertTrue(all(workflow.id.value.startswith(("minimax-h3-", "grs-gpt-image-")) for workflow in WORKFLOWS))


class StoreTests(unittest.TestCase):
    def test_settings_default_comfy_root_uses_the_workspace_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_dir = Path(directory) / "workbench"
            settings = Settings(workspace_dir=workspace_dir)

            self.assertEqual(
                settings.comfy_output_dir,
                workspace_dir.parent / "整合包及模型" / "comfyui-integrate-v1.3" / "comfyui-integrate" / "Comfyui" / "output",
            )

    def test_settings_migrates_the_legacy_database_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            legacy_path = data_dir / "".join(("toon", "flow.db"))
            legacy_path.write_bytes(b"sqlite-data")
            (data_dir / f"{legacy_path.name}-wal").write_bytes(b"wal-data")

            database_path = Settings(data_dir_override=str(data_dir)).database_path

            self.assertEqual(database_path.name, "zly-ai-video-studio.db")
            self.assertEqual(database_path.read_bytes(), b"sqlite-data")
            self.assertEqual((data_dir / "zly-ai-video-studio.db-wal").read_bytes(), b"wal-data")
            self.assertFalse(legacy_path.exists())

    def test_public_job_uses_reference_urls_instead_of_local_paths(self) -> None:
        job = public_job({
            "id": "job-1",
            "mode": JobMode.MINIMAX_H3_R2V,
            "prompt": "Use the first reference.",
            "negative_prompt": "",
            "image_size": None,
            "reference_count": 2,
            "options": {"aspect_ratio": "2:3", "quality": "1K", "megapixels": 0.2, "duration": 5},
            "submitted_options": {"aspect_ratio": "2:3", "quality": "1K", "duration": 5},
            "options_submitted": True,
            "outputs": [],
        })
        self.assertEqual(
            job["references"],
            [
                {"index": 1, "url": "/api/jobs/job-1/references/1"},
                {"index": 2, "url": "/api/jobs/job-1/references/2"},
            ],
        )
        self.assertEqual(
            job["request_parameters"],
            [
                {"name": "mode", "label": "工作流", "value": "minimax-h3-r2v", "visibility": "primary"},
                {"name": "prompt", "label": "创作提示词", "value": "Use the first reference.", "visibility": "primary"},
                {"name": "references", "label": "参考图", "value": 2, "visibility": "primary"},
                {"name": "options.aspect_ratio", "label": "画面比例", "value": "2:3", "visibility": "primary"},
                {"name": "options.quality", "label": "分辨率", "value": "1K", "visibility": "advanced"},
                {"name": "options.megapixels", "label": "内部像素面积", "value": 0.2, "visibility": "internal", "unit": "MP"},
                {"name": "options.duration", "label": "时长", "value": 5, "visibility": "primary", "unit": "秒"},
            ],
        )
        self.assertNotIn("submitted_options", job)

    def test_existing_database_adds_progress_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """CREATE TABLE jobs (
                        id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                        prompt TEXT NOT NULL, negative_prompt TEXT NOT NULL DEFAULT '', image_size TEXT,
                        options_json TEXT NOT NULL DEFAULT '{}', references_json TEXT NOT NULL,
                        outputs_json TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    )"""
                )
                connection.commit()
            finally:
                connection.close()
            JobStore(database_path)
            connection = sqlite3.connect(database_path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            finally:
                connection.close()
            self.assertIn("progress", columns)
            self.assertIn("submitted_options_json", columns)
            self.assertIn("options_submitted", columns)
            self.assertIn("comfy_prompt_id", columns)
            self.assertIn("comfy_client_id", columns)
            self.assertIn("comfy_phase", columns)

    def test_initialize_preserves_active_jobs_for_worker_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            store.update("job-1", status=JobStatus.RUNNING, stage="正在生成", progress=40)
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            reloaded = JobStore(Path(directory) / "test.db")
            job = reloaded.get("job-1")
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_job_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            created = store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            self.assertEqual(created["status"], JobStatus.QUEUED)
            self.assertEqual(created["progress"], 0)
            completed = store.update(
                "job-1", status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                outputs=[{"kind": "image", "path": "result.png", "label": "生成图片"}],
            )
            self.assertEqual(completed["outputs"][0]["path"], "result.png")
            self.assertEqual(store.list()[0]["status"], JobStatus.SUCCEEDED)
            self.assertEqual(store.list()[0]["progress"], 100)
            worker_job = store.get("job-1", include_references=True)
            self.assertEqual(worker_job["references"], [])
            self.assertNotIn("references", store.get("job-1"))

    def test_jobs_are_filtered_by_owner_and_delivery_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-a", JobMode.MINIMAX_H3_T2V, "A", "", None, [], owner_user_id="user-a")
            store.create("job-b", JobMode.MINIMAX_H3_T2V, "B", "", None, [], owner_user_id="user-b")
            store.update(
                "job-a", status=JobStatus.SUCCEEDED,
                outputs=[{"kind": "image", "path": "a.png", "label": "生成图片"}],
            )
            self.assertEqual([job["id"] for job in store.list_for_user("user-a")], ["job-a"])
            delivered = store.mark_output_delivered("job-a", 0, "2026-08-11T00:00:00+00:00")
            self.assertEqual(delivered["outputs"][0]["delivery_status"], "local")


class AuthenticationTests(unittest.TestCase):
    def test_password_minimum_length_is_six_characters(self) -> None:
        validate_password("secret")
        with self.assertRaisesRegex(ValueError, "至少需要 6 个字符"):
            validate_password("short")

    def test_password_reset_clears_login_failures_for_username_across_ips(self) -> None:
        login_failures.clear()
        self.addCleanup(login_failures.clear)
        login_failures.update({
            "10.0.0.10:staff": [1.0, 2.0],
            "10.0.0.11:staff": [3.0],
            "10.0.0.10:other": [4.0],
        })

        cleared = clear_login_failures_for_username(" Staff ")

        self.assertEqual(cleared, 2)
        self.assertEqual(login_failures, {"10.0.0.10:other": [4.0]})

    def test_user_password_session_and_revocation_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = AuthStore(Path(directory) / "auth.db")
            self.assertTrue(auth.setup_required())
            user = auth.create_user(
                "Admin", "管理员", "secure-pass-123", UserRole.SUPER_ADMIN,
                must_change_password=False,
            )
            self.assertFalse(auth.setup_required())
            self.assertEqual(auth.authenticate("admin", "secure-pass-123")["id"], user["id"])
            self.assertIsNone(auth.authenticate("admin", "wrong-password"))
            token, _ = auth.create_session(user["id"])
            self.assertEqual(auth.user_for_session(token)["id"], user["id"])
            self.assertEqual(len(csrf_token(token)), 64)
            auth.revoke_session(token)
            self.assertIsNone(auth.user_for_session(token))

    def test_password_reset_revokes_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = AuthStore(Path(directory) / "auth.db")
            user = auth.create_user("staff", "员工", "initial-pass-123", UserRole.EMPLOYEE)
            token, _ = auth.create_session(user["id"])
            updated = auth.set_password(user["id"], "changed-pass-123", must_change_password=False)
            self.assertFalse(updated["must_change_password"])
            self.assertIsNone(auth.user_for_session(token))
            self.assertIsNotNone(auth.authenticate("staff", "changed-pass-123"))
            connection = auth.connection()
            try:
                encoded = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
            finally:
                connection.close()
            self.assertTrue(verify_password("changed-pass-123", encoded))


class ResourceStorageTests(unittest.TestCase):
    def test_desktop_delivery_ticket_is_bound_to_one_user_and_output(self) -> None:
        tickets = DesktopDeliveryTickets()
        token = tickets.issue("employee-a", "job-a", 1)
        ticket = tickets.resolve(token, "job-a", 1)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.user_id, "employee-a")
        self.assertIsNone(tickets.resolve(token, "job-a", 0))
        self.assertIsNone(tickets.resolve(token, "job-b", 1))

    def test_browser_local_staging_is_removed_after_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BrowserLocalStagingStorage(Path(directory) / "staging")
            resource = storage.store_bytes("video", "source.mp4", b"video-bytes")
            self.assertEqual(storage.resolve(resource.key).read_bytes(), b"video-bytes")
            self.assertTrue(storage.delete(resource.key))
            self.assertIsNone(storage.resolve(resource.key))

    def test_browser_stream_keeps_completed_output_off_the_server_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BrowserStreamStorage(Path(directory) / "staging")
            service = ComfyService(Settings(workspace_dir=Path(directory)), storage)
            resource = service.download({"filename": "result.mp4", "subfolder": "h3", "type": "output"}, "video")

            self.assertIsNone(resource.local_path)
            self.assertIsNone(storage.resolve(resource.key))
            self.assertTrue(service.can_stream_output(resource.source_info))
            self.assertTrue(service.finalize_output_source(resource.source_info))
            self.assertTrue(storage.delete(resource.key))

    def test_browser_stream_rejects_an_unsafe_comfy_output_reference(self) -> None:
        service = ComfyService(Settings(), BrowserStreamStorage(Path(tempfile.gettempdir()) / "stream-test"))
        with self.assertRaisesRegex(legacy.ComfyError, "输出缺少 filename"):
            service.download({"filename": "../outside.mp4", "type": "output"}, "video")

    def test_provider_factory_fails_closed_for_unknown_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = create_resource_storage("browser-local", Path(directory) / "staging")
            self.assertEqual(storage.provider_id, "browser-local")
            self.assertEqual(
                create_resource_storage("browser-stream", Path(directory) / "staging").provider_id,
                "browser-stream",
            )
            with self.assertRaisesRegex(ValueError, "未知资源存储 provider"):
                create_resource_storage("qiniu-not-installed", Path(directory) / "staging")

    def test_comfy_output_cleanup_is_confined_to_fixed_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "comfy"
            output_dir = root / "output" / "video"
            output_dir.mkdir(parents=True)
            generated = output_dir / "result.mp4"
            generated.write_bytes(b"video")
            outside = root / "outside.mp4"
            outside.write_bytes(b"keep")
            test_settings = Settings(
                workspace_dir=Path(directory),
                comfy_root_override=str(root),
            )
            service = ComfyService(test_settings, BrowserLocalStagingStorage(Path(directory) / "staging"))
            self.assertTrue(service.delete_output_source({
                "filename": "result.mp4", "subfolder": "video", "type": "output",
            }))
            self.assertFalse(generated.exists())
            self.assertFalse(service.delete_output_source({
                "filename": "outside.mp4", "subfolder": "..", "type": "output",
            }))
            self.assertTrue(outside.exists())

    def test_public_job_never_exposes_comfy_output_locator(self) -> None:
        job = public_job({
            "id": "job-source", "mode": JobMode.MINIMAX_H3_T2V, "status": "succeeded",
            "prompt": "prompt", "negative_prompt": "", "image_size": None,
            "reference_count": 0, "options": {}, "submitted_options": {}, "options_submitted": False,
            "outputs": [{
                "kind": "image", "path": "result.png", "label": "生成图片",
                "_comfy_source": {"filename": "secret.png", "subfolder": "", "type": "output"},
            }],
        })
        self.assertNotIn("_comfy_source", job["outputs"][0])

    def test_browser_direct_view_url_uses_only_the_fixed_local_comfyui_origin(self) -> None:
        url = browser_direct_view_url({
            "filename": "result.mp4", "subfolder": "h3/output", "type": "output",
        })
        self.assertEqual(url, f"{BROWSER_LOCAL_COMFY_VIEW_URL}?filename=result.mp4&subfolder=h3%2Foutput&type=output")


class WorkerTests(unittest.TestCase):
    def test_comfy_progress_state_is_converted_to_percent(self) -> None:
        message = {
            "type": "progress_state",
            "data": {"prompt_id": "prompt-1", "nodes": {"10": {"state": "running", "value": 4, "max": 20}}},
        }
        self.assertEqual(ComfyService.progress_percent(message, "prompt-1"), 20)
        self.assertIsNone(ComfyService.progress_percent(message, "another-prompt"))

    def test_worker_keeps_reference_paths_internal(self) -> None:
        class FakeComfy:
            received_references: list[str] | None = None

            def run(self, mode, references, prompt, negative_prompt, image_size, options, update_stage, on_submitted, save_partial_outputs):
                self.received_references = references
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_R2V, "prompt", "", None, ["scene.png", "subject.png", "style.png"])
            comfy = FakeComfy()
            asyncio.run(JobWorker(store, comfy).execute("job-1"))
            self.assertEqual(comfy.received_references, ["scene.png", "subject.png", "style.png"])

    def test_worker_releases_queue_when_comfy_connection_is_interrupted(self) -> None:
        class InterruptedComfy:
            def run(self, *args, **kwargs):
                raise ComfyUnavailable("ComfyUI or FRP connection interrupted")

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            asyncio.run(JobWorker(store, InterruptedComfy()).execute("job-1"))
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.INTERRUPTED)
            self.assertIsNone(job["comfy_prompt_id"])
            self.assertIn("ComfyUI", job["stage"])

    def test_interrupted_job_can_be_requeued_after_comfy_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            self.assertIsNone(store.retry_terminal("job-1"))
            store.set_comfy_execution("job-1", "stale-prompt", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED)
            store.clear_comfy_execution("job-1")
            retried = store.retry_terminal("job-1")
            self.assertIsNotNone(retried)
            self.assertEqual(retried["status"], JobStatus.QUEUED)
            self.assertIsNone(retried["comfy_prompt_id"])
            self.assertIsNone(store.retry_terminal("job-1"))

    def test_failed_job_can_be_requeued_only_after_execution_id_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "active-prompt", "client-1", "generation")
            store.update("job-1", status=JobStatus.FAILED)
            self.assertIsNone(store.retry_terminal("job-1"))
            store.clear_comfy_execution("job-1")
            retried = store.retry_terminal("job-1")
            self.assertEqual(retried["status"], JobStatus.QUEUED)

    def test_worker_reconnects_interrupted_legacy_h3_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            store.update("job-1", status=JobStatus.INTERRUPTED, stage="应用已重启")
            created_at = datetime.fromisoformat(store.get("job-1")["created_at"])
            worker = JobWorker(store, object())
            worker.reconnect_legacy_jobs([ComfyQueuePrompt("prompt-1", "client-1", "提示词", created_at)])
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_legacy_reconnection_pairs_duplicate_prompts_by_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            for job_id in ("older", "newer"):
                store.create(job_id, JobMode.MINIMAX_H3_T2V, "同一提示词", "", None, [])
                store.update(job_id, status=JobStatus.INTERRUPTED, stage="应用已重启")
            connection = store.connection()
            try:
                connection.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-08-07T02:15:46+00:00", "older"))
                connection.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-08-07T02:16:45+00:00", "newer"))
                connection.commit()
            finally:
                connection.close()
            worker = JobWorker(store, object())
            worker.reconnect_legacy_jobs([
                ComfyQueuePrompt("current", "client-current", "同一提示词", datetime.fromisoformat("2026-08-07T02:16:45.100+00:00")),
                ComfyQueuePrompt("finished", "client-finished", "同一提示词", datetime.fromisoformat("2026-08-07T02:15:46.100+00:00")),
            ])
            self.assertEqual(store.get("older")["comfy_prompt_id"], "finished")
            self.assertEqual(store.get("newer")["comfy_prompt_id"], "current")


if __name__ == "__main__":
    unittest.main()
