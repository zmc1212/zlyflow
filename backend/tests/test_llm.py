from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore
from backend.app.llm_client import OpenAICompatibleClient, LlmError
from backend.app.llm_provider import LlmProviderService
from backend.app.main import app, session_cookie_scheme
from backend.app.models import UserRole
from backend.app.storage import JobStore


class StripThinkingTests(unittest.TestCase):
    def _strip(self, text: str) -> str:
        from backend.app.llm_client import OpenAICompatibleClient
        return OpenAICompatibleClient._strip_thinking(text)

    def test_strips_think_tags(self) -> None:
        raw = "<think>我在分析用户意图...</think>\n\nA cinematic shot of a cat."
        self.assertEqual(self._strip(raw), "A cinematic shot of a cat.")

    def test_strips_think_tag_no_newline(self) -> None:
        raw = "<think>internal monologue</think>Final prompt here."
        self.assertEqual(self._strip(raw), "Final prompt here.")

    def test_strips_slash_think(self) -> None:
        raw = "some reasoning\n/think\nFinal optimized prompt."
        self.assertEqual(self._strip(raw), "Final optimized prompt.")

    def test_passthrough_clean_text(self) -> None:
        raw = "A beautiful sunset over the ocean."
        self.assertEqual(self._strip(raw), raw)

    def test_multiple_think_blocks(self) -> None:
        raw = "<think>step 1</think><think>step 2</think>The result."
        self.assertEqual(self._strip(raw), "The result.")


class LLMProviderTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.provider = LlmProviderService(self.job_store, self.credential_key)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_config(self) -> None:
        cfg = self.provider.public_config()
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["base_url"], "https://api-inference.modelscope.cn/v1")
        self.assertEqual(cfg["model"], "Qwen/Qwen2.5-72B-Instruct")
        self.assertFalse(cfg["has_api_key"])
        self.assertTrue(cfg["credential_ready"])

    def test_update_and_mask_api_key(self) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "https://api-inference.modelscope.cn/v1",
            "api_key": "ms-secret-token-12345678",
            "model": "Qwen/Qwen2.5-72B-Instruct",
        })
        cfg = self.provider.public_config()
        self.assertTrue(cfg["enabled"])
        self.assertTrue(cfg["has_api_key"])
        self.assertTrue(cfg["api_key_masked"].startswith("ms-"))
        self.assertTrue(cfg["api_key_masked"].endswith("78"))
        self.assertTrue(cfg["available"])
        self.assertEqual(self.provider.api_key(), "ms-secret-token-12345678")

    @patch("requests.Session.post")
    def test_optimize_prompt_video(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "电影级中景，一位穿着风衣的女子缓步走在雨夜街道，霓虹倒影在湿漉的地面，镜头平稳向前推进。"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "Qwen/Qwen2.5-72B-Instruct",
        })
        result = self.provider.optimize_prompt("女子在下雨天散步", media_type="video", skill_id="minimalist-product-ad", reference_count=1)
        self.assertIn("电影级中景", result)
        mock_post.assert_called_once()
        # 验证 system prompt 包含 MiniMax H3 技能指导与首帧对齐
        call_kwargs = mock_post.call_args[1]
        sent_messages = call_kwargs["json"]["messages"]
        system_content = next(m["content"] for m in sent_messages if m["role"] == "system")
        self.assertIn("integrated_multimodal_description", system_content)
        self.assertIn("极简电商产品广告", system_content)
        self.assertIn("For the target video, at 0.00 seconds into the target video, <Picture 1>", system_content)

    @patch("requests.Session.post")
    def test_optimize_prompt_dashscope_format(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "text": "integrated_multimodal_description: [Shot 1] 3D Animation...\n\noverall_soundscape: birds...\n\nnon_diegetic_music: piano"
            }
        }
        mock_post.return_value = mock_response

        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "qwen-max",
        })
        result = self.provider.optimize_prompt("小猫在草地上玩耍", media_type="video")
        self.assertIn("3D Animation", result)



class LLMAppEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)

        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider

        self.admin = self.auth_store.create_user("superadmin", "Super Admin", "password123456", UserRole.SUPER_ADMIN, must_change_password=False)
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee = self.auth_store.create_user("worker", "Worker", "password123456", UserRole.EMPLOYEE, must_change_password=False)
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_admin_config_permissions(self) -> None:
        # 未登录访问
        res = self.client.get("/api/admin/providers/llm")
        self.assertEqual(res.status_code, 401)

        # 员工访问禁止
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/admin/providers/llm")
        self.assertEqual(res.status_code, 403)

        # 超级管理员正常访问
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.get("/api/admin/providers/llm")
        self.assertEqual(res.status_code, 200)
        self.assertIn("base_url", res.json())

    def test_list_h3_skills_api(self) -> None:
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        res = self.client.get("/api/llm/skills")
        self.assertEqual(res.status_code, 200)
        skills = res.json()["skills"]
        self.assertTrue(len(skills) >= 9)
        skill_ids = [s["id"] for s in skills]
        self.assertIn("general", skill_ids)
        self.assertIn("minimalist-product-ad", skill_ids)
        self.assertIn("3d-animation-short", skill_ids)
        self.assertIn("papercraft-stop-motion", skill_ids)

    @patch("requests.Session.post")
    def test_optimize_prompt_api(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "integrated_multimodal_description: [Shot 1] Live-action, cinematic...\n\noverall_soundscape: Wind blowing...\n\nnon_diegetic_music: Soft acoustic guitar."
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # 启用并配置 LLM
        self.llm_provider.update({
            "enabled": True,
            "api_key": "test-modelscope-token",
            "model": "Qwen/Qwen2.5-72B-Instruct",
        })

        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        from backend.app.auth import csrf_token
        res = self.client.post(
            "/api/llm/optimize-prompt",
            json={
                "prompt": "航拍日落",
                "media_type": "video",
                "skill_id": "3d-animation-short",
                "reference_count": 2,
            },
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["original_prompt"], "航拍日落")
        self.assertEqual(data["skill_id"], "3d-animation-short")
        self.assertIn("integrated_multimodal_description", data["optimized_prompt"])


if __name__ == "__main__":
    unittest.main()

