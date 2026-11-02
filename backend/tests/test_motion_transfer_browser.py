"""Opt-in desktop/API/ComfyUI acceptance; ordinary test runs never submit GPU work.

ZLY_MOTION_BROWSER_E2E=1 checks the real 5173 UI against an isolated SQLite API.
ZLY_MOTION_RENDER_E2E=1 additionally executes exactly one real remote ComfyUI job.
Provide ZLY_MOTION_TEST_IMAGE and ZLY_MOTION_TEST_VIDEO as existing authorized assets.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch

import requests


@unittest.skipUnless(os.getenv("ZLY_MOTION_BROWSER_E2E") == "1", "opt-in desktop/remote acceptance")
class MotionTransferBrowserAcceptance(unittest.TestCase):
    def test_desktop_upload_login_submission_and_reedit(self) -> None:
        from fastapi.testclient import TestClient
        from playwright.sync_api import sync_playwright

        from backend.app import main
        from backend.app.auth import AuthStore
        from backend.app.comfy_service import ComfyService
        from backend.app.config import Settings
        from backend.app.models import JobStatus, UserRole
        from backend.app.resource_storage import BrowserLocalStagingStorage
        from backend.app.storage import JobStore
        from backend.app.worker import JobWorker
        from backend.app.workflow_registry import WORKFLOWS, workflow_for

        render = os.getenv("ZLY_MOTION_RENDER_E2E") == "1"
        image = Path(os.environ["ZLY_MOTION_TEST_IMAGE"]).resolve()
        video = Path(os.environ["ZLY_MOTION_TEST_VIDEO"]).resolve()
        self.assertTrue(image.is_file() and video.is_file())
        output = Path("test-results/motion-transfer").resolve()
        output.mkdir(parents=True, exist_ok=True)
        if render and ((output / "workbench-e2e.mp4").exists() or (output / "remote-submission.json").exists()):
            self.fail("A remote acceptance was already submitted; inspect its saved prompt ID instead of blindly submitting twice.")
        # Read the effective provider; never infer remote configuration from a historical URL.
        health = requests.get("http://127.0.0.1:7865/api/health", timeout=15).json()
        comfy_url = health["comfy"]["url"]
        if render:
            queue = requests.get(f"{comfy_url}/queue", timeout=10).json()
            self.assertFalse(queue.get("queue_running") or queue.get("queue_pending"), "Do not interfere with existing GPU work")

        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="motion-browser-", dir=output)))
            settings = Settings(workspace_dir=directory, data_dir_override=str(directory / "data"), comfy_url=comfy_url)
            store = JobStore(directory / "test.db")
            auth = AuthStore(directory / "test.db")
            auth.create_user("motion-browser", "动作迁移验收", "isolated-test-password-123", UserRole.EMPLOYEE, must_change_password=False)
            storage = BrowserLocalStagingStorage(settings.staging_dir)
            comfy = ComfyService(settings, storage, url_resolver=lambda: comfy_url)
            worker = JobWorker(store, comfy, resource_storage=storage)
            stack.enter_context(patch.object(main, "settings", settings))
            for name, value in {"store": store, "auth_store": auth, "worker": worker, "resource_storage": storage,
                                "grs_provider": SimpleNamespace(availability=lambda *_: (True, None))}.items():
                stack.enter_context(patch.object(main.app.state, name, value, create=True))
            definitions = [workflow_for("grs-gpt-image-2"), *WORKFLOWS]
            stack.enter_context(patch.object(main, "listed_workflows", return_value=definitions))
            client = TestClient(main.app)  # No application lifespan or production DB access.
            stack.callback(client.close)
            submissions: list[dict] = []
            prompt_ids: list[str] = []
            original_submission = store.set_comfy_execution

            def capture_submission(job_id, prompt_id, client_id, phase):
                prompt_ids.append(prompt_id)
                (output / "remote-submission.json").write_text(json.dumps({
                    "comfy_url": comfy_url, "prompt_id": prompt_id, "job_id": job_id,
                }, indent=2), encoding="utf-8")
                return original_submission(job_id, prompt_id, client_id, phase)

            stack.enter_context(patch.object(store, "set_comfy_execution", side_effect=capture_submission))

            def route_api(route):
                request = route.request
                url = urlsplit(request.url)
                path = url.path
                # Only presentation-only provider status is fixture data. Authentication,
                # multipart submission, job records, reference bytes and result downloads
                # all pass through the real application, with its original auth/CSRF checks.
                fixtures = {
                    "/api/health": health,
                    "/api/llm/status": {"available": False, "message": "验收不调用 LLM", "skills": []},
                    "/api/upscale/capabilities": {"engines": [], "default": "rtx"},
                    "/api/providers/grs/balance": {"credits": 0, "queried_at": None, "refresh_error": None},
                }
                if path in fixtures:
                    route.fulfill(json=fixtures[path])
                    return
                allowed = (path.startswith("/api/auth/") or path == "/api/modes"
                           or path.startswith("/api/modes/") or path.startswith("/api/jobs"))
                if not allowed:
                    route.fulfill(status=200, json={})
                    return
                headers = {key: value for key, value in request.headers.items()
                           if key.lower() not in {"host", "content-length", "accept-encoding", "connection", "cookie"}}
                response = client.request(request.method, path + (f"?{url.query}" if url.query else ""),
                                          headers=headers, content=request.post_data_buffer)
                if path == "/api/jobs" and request.method == "POST":
                    self.assertEqual(response.status_code, 202, response.text)
                    submissions.append(response.json())
                response_headers = {key: value for key, value in response.headers.items()
                                    if key.lower() not in {"content-length", "content-encoding", "transfer-encoding"}}
                route.fulfill(status=response.status_code, headers=response_headers, body=response.content)

            def submit_browser_form(payload):
                # CDP omits native multipart file bodies in request.post_data_buffer.
                # Carry the actual FormData entries/bytes over a test-only binding;
                # let HTTPX encode them for the real FastAPI multipart parser.
                files = [("references", (item["name"], base64.b64decode(item["data"]), item["type"]))
                         for item in payload["files"]]
                self.assertEqual(files[0][1][1], image.read_bytes())
                self.assertEqual(files[1][1][1], video.read_bytes())
                response = client.post("/api/jobs", data=dict(payload["fields"]), files=files, headers=payload["headers"])
                if response.status_code == 202:
                    submissions.append(response.json())
                return {"status": response.status_code, "body": response.json()}

            playwright = stack.enter_context(sync_playwright())
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            stack.callback(browser.close)
            context = browser.new_context(viewport={"width": 1536, "height": 864}, device_scale_factor=1)
            stack.callback(context.close)
            context.route("**/api/**", route_api)
            page = context.new_page()
            page.expose_function("motionAcceptanceSubmit", submit_browser_form)
            page.add_init_script("""
                const nativeFetch = window.fetch.bind(window);
                window.fetch = async (input, init) => {
                    if (input === '/api/jobs' && init?.method === 'POST' && init.body instanceof FormData) {
                        const fields = [], files = [];
                        for (const [name, value] of init.body.entries()) {
                            if (typeof value === 'string') fields.push([name, value]);
                            else {
                                const data = await new Promise((resolve, reject) => {
                                    const reader = new FileReader();
                                    reader.onload = () => resolve(String(reader.result).split(',')[1]);
                                    reader.onerror = reject;
                                    reader.readAsDataURL(value);
                                });
                                files.push({name: value.name, type: value.type, data});
                            }
                        }
                        const result = await window.motionAcceptanceSubmit({fields, files, headers: init.headers});
                        return new Response(JSON.stringify(result.body), {status: result.status, headers: {'Content-Type': 'application/json'}});
                    }
                    return nativeFetch(input, init);
                };
            """)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:5173/generate/video?workflow=minimax-h3-motion-transfer")
            page.get_by_label("上传动作参考视频", exact=True).wait_for()
            page.get_by_label("上传角色形象图", exact=True).set_input_files(str(image))
            page.get_by_label("上传动作参考视频", exact=True).set_input_files(str(video))
            page.get_by_role("button", name="预览动作参考视频", exact=True).wait_for()
            page.wait_for_function("document.querySelector('.studio-motion-reference video')?.readyState >= 1")
            self.assertEqual(page.get_by_role("textbox", name="创作提示词", exact=True).input_value(), "")
            page.get_by_role("button", name="更多设置", exact=True).click()
            page.get_by_role("combobox", name="生成质量", exact=True).click()
            page.get_by_text("快速预览", exact=True).click()
            page.get_by_role("spinbutton", name="随机种子", exact=True).fill("20261102")
            page.get_by_role("combobox", name="生成质量", exact=True).press("Escape")
            page.locator(".ant-select-dropdown:visible").wait_for(state="hidden")
            self.assertEqual(page.get_by_role("spinbutton", name="采样步数", exact=True).count(), 0)
            readable_number = """() => {
                const input = document.querySelector('input[aria-label="动作跟随强度"]');
                if (!input) return false;
                const foreground = getComputedStyle(input).color.match(/[\\d.]+/g)?.slice(0, 3).map(Number);
                const hex = getComputedStyle(document.documentElement).getPropertyValue('--studio-field').trim().replace('#', '');
                const background = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16));
                const luminance = channels => channels.map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
                    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
                if (!foreground) return false;
                const a = luminance(foreground), b = luminance(background);
                return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 4.5;
            }"""
            page.wait_for_function(readable_number)
            page.screenshot(path=str(output / "desktop-dark.png"), full_page=True)
            page.get_by_role("button", name="切换到浅色外观", exact=True).click()
            page.wait_for_function(readable_number)
            page.screenshot(path=str(output / "desktop-light.png"), full_page=True)
            page.get_by_role("button", name="切换到暗色外观", exact=True).click()
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 1536)

            # A guest's generation click must require real sign-in, preserve both
            # local media slots and never auto-submit after authenticating.
            page.get_by_role("button", name="开始生成", exact=True).click()
            page.get_by_placeholder("请输入你的账号", exact=True).fill("motion-browser")
            page.get_by_placeholder("请输入密码", exact=True).fill("isolated-test-password-123")
            page.get_by_role("button", name="登录并继续", exact=False).click()
            page.get_by_role("heading", name="登录，继续创作", exact=True).wait_for(state="hidden")
            self.assertFalse(submissions)
            self.assertTrue(page.get_by_role("button", name="预览动作参考视频", exact=True).is_visible())
            self.assertTrue(page.get_by_role("button", name="开始生成", exact=True).is_enabled())
            page.get_by_role("button", name="开始生成", exact=True).click()
            page.wait_for_url("**/generate/video/*")
            self.assertEqual(len(submissions), 1)
            job = submissions[0]
            self.assertEqual([ref["kind"] for ref in job["references"]], ["image", "video"])
            self.assertEqual(job["options"]["steps"], 8)
            self.assertEqual(job["options"]["seed"], 20261102)
            self.assertTrue(job["prompt"])
            evidence = {"comfy_url": comfy_url, "submission_status": 202, "reference_kinds": ["image", "video"],
                        "viewport": [1536, 864], "login_preserved_draft": True, "options": job["options"], "rendered": render}

            if render:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, worker.execute(job["id"]))
                    # Browser polling is the application's own job polling, not a
                    # second inference submission. It remains interactive during rendering.
                    page.wait_for_function("document.querySelector('.studio-video-player')?.readyState >= 2 || document.querySelector('.studio-round-error')", timeout=900_000)
                    future.result(timeout=30)
                finished = store.get(job["id"])
                self.assertEqual(finished["status"], JobStatus.SUCCEEDED.value, finished.get("error"))
                artifact = storage.resolve(finished["outputs"][0]["path"])
                self.assertIsNotNone(artifact)
                shutil.copy2(artifact, output / "workbench-e2e.mp4")
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                        "stream=codec_type,codec_name,width,height,nb_frames:format=duration", "-of", "json",
                                        str(output / "workbench-e2e.mp4")], capture_output=True, text=True, check=True)
                evidence["media"] = json.loads(probe.stdout)
                evidence["prompt_ids"] = prompt_ids
                self.assertEqual(len(prompt_ids), 1)
                self.assertTrue(any(stream["codec_type"] == "audio" for stream in evidence["media"]["streams"]))
                page.screenshot(path=str(output / "desktop-result.png"), full_page=True)
            else:
                store.update(job["id"], status=JobStatus.SUCCEEDED, stage="仅验证提交，未调用 GPU")

            page.get_by_role("button", name="重新编辑", exact=True).click()
            page.wait_for_url("**/generate/video")
            page.get_by_role("button", name="预览动作参考视频", exact=True).wait_for()
            page.get_by_role("button", name="预览角色形象图", exact=True).wait_for()
            evidence["reedit_restored_image_and_video"] = True
            page.get_by_role("combobox", name="选择生成类型", exact=True).click()
            page.locator(".ant-select-dropdown:visible").get_by_text("图片生成", exact=True).click()
            page.wait_for_url("**/generate/image")
            page.get_by_role("combobox", name="选择生成类型", exact=True).click()
            page.locator(".ant-select-dropdown:visible").get_by_text("视频生成", exact=True).click()
            page.wait_for_url("**/generate/video")
            page.get_by_role("button", name="预览动作参考视频", exact=True).wait_for()
            page.wait_for_function("document.querySelector('.studio-motion-reference video')?.readyState >= 1")
            evidence["media_switch_preserved_motion_draft"] = True
            page.get_by_role("link", name="工具", exact=True).click()
            page.wait_for_url("**/tools")
            tool = page.get_by_role("link", name="动作迁移：", exact=False)
            tool.wait_for()
            self.assertNotIn("即将上线", tool.inner_text())
            tool.click()
            # 动作迁移有专属工具页（与提示词反推同构），入口卡是语义化链接。
            page.wait_for_url("**/tools/motion-transfer")
            page.get_by_role("heading", name="动作迁移", exact=True).wait_for()
            page.get_by_label("上传动作参考视频", exact=True).wait_for()
            self.assertTrue(page.get_by_role("button", name="开始生成", exact=True).is_visible())
            evidence["tool_entry_opened"] = True
            evidence["page_errors"] = errors
            self.assertFalse(errors)
            (output / ("e2e-evidence.json" if render else "browser-evidence.json")).write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
            )


if __name__ == "__main__":
    unittest.main()
