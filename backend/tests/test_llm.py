from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore
import requests

from backend.app.llm_client import (
    LLM_CONNECT_TIMEOUT_SECONDS,
    LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
    OpenAICompatibleClient,
    LlmBillingError,
    LlmError,
    LlmTemporaryError,
    parse_model_catalog,
    parse_siliconflow_plaza_free_ids,
)
from backend.app.llm_provider import LlmProviderService
from backend.app.main import app, session_cookie_scheme
from backend.app.models import UserRole
from backend.app.storage import JobStore


class ChatCompletionThinkingTests(unittest.TestCase):
    def _ok_response(self) -> MagicMock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "收到"}}]
        }
        return mock_response

    @patch("requests.Session.post")
    def test_deepseek_v4_disables_thinking_in_payload(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")
        client.chat_completion(
            [{"role": "user", "content": "hi"}],
            "deepseek-ai/DeepSeek-V4-Flash-0731",
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertFalse(payload["enable_thinking"])

    @patch("requests.Session.post")
    def test_qwen_does_not_send_deepseek_thinking_block(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")
        client.chat_completion(
            [{"role": "user", "content": "hi"}],
            "Qwen/Qwen2.5-7B-Instruct",
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertNotIn("thinking", payload)
        self.assertFalse(payload["enable_thinking"])


class ChatCompletionTimeoutAndStreamTests(unittest.TestCase):
    def _client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")

    def _ok_response(self) -> MagicMock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "收到"}}]
        }
        return mock_response

    @patch("requests.Session.post")
    def test_uses_connect_and_read_timeout(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        self._client().chat_completion([{"role": "user", "content": "hi"}], "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(
            mock_post.call_args.kwargs["timeout"],
            (LLM_CONNECT_TIMEOUT_SECONDS, 60.0),
        )
        self.assertFalse(mock_post.call_args.kwargs["json"].get("stream"))

    @patch("requests.Session.post")
    def test_read_timeout_omits_urllib3_dump(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")
        with self.assertRaises(LlmTemporaryError) as ctx:
            self._client().chat_completion(
                [{"role": "user", "content": "hi"}],
                "Qwen/Qwen2.5-7B-Instruct",
                timeout=300.0,
            )
        text = str(ctx.exception)
        self.assertIn("等待 300 秒仍无响应", text)
        self.assertNotIn("Read timed out", text)
        self.assertNotIn("HTTPSConnectionPool", text)

    @patch("requests.Session.post")
    def test_stream_accumulates_sse_deltas(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.return_value = [
            "data: {\"choices\":[{\"delta\":{\"content\":\"{\\\"title\\\"\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\":\\\"巷口\\\"}\"}}]}",
            "data: [DONE]",
        ]
        mock_post.return_value = mock_response
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "deepseek-ai/DeepSeek-V4-Flash-0731",
            timeout=300.0,
            stream=True,
        )
        self.assertEqual(text, '{"title":"巷口"}')
        payload = mock_post.call_args.kwargs["json"]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(mock_post.call_args.kwargs["timeout"], (LLM_CONNECT_TIMEOUT_SECONDS, 300.0))
        self.assertTrue(mock_post.call_args.kwargs["stream"])

    @patch("requests.Session.post")
    def test_stream_ignores_reasoning_deltas(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.return_value = [
            "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"思考中\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\"完成\"}}]}",
            "data: [DONE]",
        ]
        mock_post.return_value = mock_response
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "Qwen/Qwen2.5-7B-Instruct",
            stream=True,
        )
        self.assertEqual(text, "完成")

    @patch("requests.Session.post")
    def test_stream_reports_on_chunk(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.return_value = [
            "data: {\"choices\":[{\"delta\":{\"content\":\"镜\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\"头\"}}]}",
            "data: [DONE]",
        ]
        mock_post.return_value = mock_response
        chunks: list[str] = []
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "Qwen/Qwen2.5-7B-Instruct",
            stream=True,
            on_chunk=chunks.append,
        )
        self.assertEqual(text, "镜头")
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[-1], "镜头")

    @patch("requests.Session.post")
    def test_stream_decodes_utf8_chinese_from_bytes(self, mock_post: MagicMock) -> None:
        payload = json.dumps(
            {"choices": [{"delta": {"content": '{"title":"巷口"}'}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.encoding = "ISO-8859-1"
        mock_response.iter_lines.return_value = [b"data: " + payload, b"data: [DONE]"]
        mock_post.return_value = mock_response
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "Qwen/Qwen2.5-7B-Instruct",
            stream=True,
        )
        self.assertEqual(text, '{"title":"巷口"}')

    def test_repairs_utf8_mojibake(self) -> None:
        from backend.app.llm_client import repair_utf8_mojibake

        garbled = "巷口".encode("utf-8").decode("latin-1")
        self.assertNotEqual(garbled, "巷口")
        self.assertEqual(repair_utf8_mojibake(garbled), "巷口")
        self.assertEqual(repair_utf8_mojibake("Ada sent a message"), "Ada sent a message")

    def test_director_chat_fn_streams_with_long_idle_timeout(self) -> None:
        from backend.app.director_agents import default_chat_fn

        client = MagicMock()
        client.chat_completion.return_value = "ok"
        default_chat_fn(client, "deepseek-ai/DeepSeek-V4-Flash-0731")([{"role": "user", "content": "x"}])
        kwargs = client.chat_completion.call_args.kwargs
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout"], LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["max_tokens"], 8192)
        self.assertIn("on_chunk", kwargs)


class LlmBillingErrorTests(unittest.TestCase):
    def _client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")

    def _response(self, status: int, payload: dict) -> MagicMock:
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload, ensure_ascii=False)
        return mock_response

    @patch("requests.Session.post")
    def test_http_403_balance_returns_upstream_log(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._response(403, {"message": "account balance is insufficient"})
        with self.assertRaises(LlmBillingError) as ctx:
            self._client().chat_completion([{"role": "user", "content": "hi"}], "Qwen/Qwen2.5-7B-Instruct")
        text = str(ctx.exception)
        self.assertIn("余额不足", text)
        self.assertIn("HTTP 403", text)
        self.assertIn("account balance is insufficient", text)

    @patch("requests.Session.post")
    def test_http_429_quota_is_billing_not_temporary(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._response(429, {
            "error": {"message": "You have exceeded your current quota", "type": "insufficient_quota"},
        })
        with self.assertRaises(LlmBillingError) as ctx:
            self._client().chat_completion([{"role": "user", "content": "hi"}], "Qwen/Qwen2.5-7B-Instruct")
        self.assertNotIsInstance(ctx.exception, LlmTemporaryError)
        self.assertIn("exceeded your current quota", str(ctx.exception))

    @patch("requests.Session.post")
    def test_http_200_embedded_balance_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._response(200, {"code": 403, "message": "余额不足"})
        with self.assertRaises(LlmBillingError) as ctx:
            self._client().chat_completion([{"role": "user", "content": "hi"}], "Qwen/Qwen2.5-7B-Instruct")
        self.assertIn("余额不足", str(ctx.exception))
        self.assertIn("上游返回", str(ctx.exception))


class ModelCatalogTests(unittest.TestCase):
    def test_parse_siliconflow_free_only(self) -> None:
        payload = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen2.5-7B-Instruct (Free)"},
                {"id": "Qwen/Qwen3-8B", "tags": ["chat", "Free"]},
                {"id": "THUDM/glm-4-9b-chat", "price": "Free"},
                {"id": "Pro/Qwen/Qwen2.5-7B-Instruct", "name": "Qwen2.5-7B-Instruct"},
                {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3"},
                {"id": "Qwen/Qwen2.5-72B-Instruct", "description": "supports Classifier-Free Guidance"},
            ]
        }
        models = parse_model_catalog(payload, provider="siliconflow", free_only=True)
        ids = [item["id"] for item in models]
        self.assertEqual(ids, ["Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen3-8B", "THUDM/glm-4-9b-chat"])
        self.assertTrue(all(item["free"] for item in models))

    def test_openai_compatible_payload_without_free_label_is_empty(self) -> None:
        payload = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "object": "model", "owned_by": "Qwen"},
                {"id": "deepseek-ai/DeepSeek-V3", "object": "model", "owned_by": "deepseek-ai"},
                {"id": "Pro/Qwen/Qwen2.5-7B-Instruct", "object": "model", "owned_by": "Qwen"},
            ]
        }
        models = parse_model_catalog(payload, provider="siliconflow", free_only=True)
        self.assertEqual(models, [])

    def test_parse_siliconflow_plaza_price_zero(self) -> None:
        html = r"""
        self.__next_f.push([1,"x:{\"models\":[{\"modelName\":\"Qwen/Qwen2.5-7B-Instruct\",\"status\":\"enable\",\"pricing\":[{\"price\":\"0\",\"specification\":\"prompt\"},{\"price\":\"0\",\"specification\":\"completion\"}]},{\"modelName\":\"deepseek-ai/DeepSeek-V3\",\"status\":\"enable\",\"pricing\":[{\"price\":\"2\",\"specification\":\"prompt\"},{\"price\":\"8\",\"specification\":\"completion\"}]},{\"modelName\":\"Pro/Qwen/Qwen2.5-7B-Instruct\",\"status\":\"enable\",\"pricing\":[{\"price\":\"4\",\"specification\":\"prompt\"}]},{\"modelName\":\"Qwen/Qwen2-1.5B-Instruct\",\"status\":\"disable\",\"pricing\":[{\"price\":\"0\",\"specification\":\"prompt\"}]}]}"])
        <div class="w-full truncate break-all align-top text-base">internlm/internlm2_5-7b-chat</div>
        <span>Free</span>
        """
        ids = parse_siliconflow_plaza_free_ids(html)
        self.assertIn("Qwen/Qwen2.5-7B-Instruct", ids)
        self.assertIn("internlm/internlm2_5-7b-chat", ids)
        self.assertNotIn("deepseek-ai/DeepSeek-V3", ids)
        self.assertNotIn("Pro/Qwen/Qwen2.5-7B-Instruct", ids)
        self.assertNotIn("Qwen/Qwen2-1.5B-Instruct", ids)
        duplicate_paid = r'''
        {"modelName":"Qwen/Qwen2.5-14B-Instruct","pricing":[{"price":"0"},{"price":"0"}]}
        {"modelName":"Qwen/Qwen2.5-14B-Instruct","pricing":[{"price":"0.7"},{"price":"0.7"}]}
        '''
        self.assertNotIn("Qwen/Qwen2.5-14B-Instruct", parse_siliconflow_plaza_free_ids(duplicate_paid))

    def test_parse_local_models_all_free(self) -> None:
        payload = {"data": [{"id": "qwen2.5:7b-instruct"}, {"id": "qwen2.5:14b"}]}
        models = parse_model_catalog(payload, provider="ollama", free_only=True)
        self.assertEqual([item["id"] for item in models], ["qwen2.5:14b", "qwen2.5:7b-instruct"])
        self.assertTrue(all(item["free"] for item in models))

    @patch("requests.Session.get")
    def test_list_model_catalog_requests_all_siliconflow_models(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen2.5-7B-Instruct Free"},
                {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3"},
            ]
        }
        mock_get.return_value = mock_response
        client = OpenAICompatibleClient("https://api.siliconflow.cn/v1", "sk-test")
        result = client.list_model_catalog(free_only=True)
        self.assertEqual([item["id"] for item in result["models"]], ["Qwen/Qwen2.5-7B-Instruct"])
        self.assertTrue(result["free_only"])
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.kwargs.get("params"), {"sub_type": "chat"})

    @patch("requests.Session.get")
    def test_list_model_catalog_uses_plaza_when_api_has_no_free_label(self, mock_get: MagicMock) -> None:
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "object": "model", "owned_by": "Qwen"},
                {"id": "deepseek-ai/DeepSeek-V3", "object": "model", "owned_by": "deepseek-ai"},
                {"id": "Pro/Qwen/Qwen2.5-7B-Instruct", "object": "model", "owned_by": "Qwen"},
            ]
        }
        api_response.text = ""
        plaza_response = MagicMock()
        plaza_response.status_code = 200
        plaza_response.text = r"""
        {"modelName":"Qwen/Qwen2.5-7B-Instruct","status":"enable","pricing":[{"price":"0","specification":"prompt"},{"price":"0","specification":"completion"}]}
        {"modelName":"deepseek-ai/DeepSeek-V3","status":"enable","pricing":[{"price":"2","specification":"prompt"}]}
        """
        plaza_response.json.return_value = {}
        mock_get.side_effect = [api_response, plaza_response]
        client = OpenAICompatibleClient("https://api.siliconflow.cn/v1", "sk-test")
        result = client.list_model_catalog(free_only=True)
        self.assertEqual([item["id"] for item in result["models"]], ["Qwen/Qwen2.5-7B-Instruct"])
        self.assertTrue(result["models"][0]["free"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[0].kwargs.get("params"), {"sub_type": "chat"})
        plaza_headers = mock_get.call_args_list[1].kwargs.get("headers") or {}
        self.assertNotIn("Authorization", plaza_headers)
        self.assertIn("cloud.siliconflow.cn/open/models", mock_get.call_args_list[1].args[0])

    def test_llm_catalog_excludes_ocr_embedding_and_speech(self) -> None:
        from backend.app.llm_client import is_llm_chat_model, filter_llm_catalog_models

        self.assertTrue(is_llm_chat_model("Qwen/Qwen2.5-7B-Instruct"))
        self.assertTrue(is_llm_chat_model("Qwen/Qwen3-8B"))
        self.assertFalse(is_llm_chat_model("deepseek-ai/DeepSeek-OCR"))
        self.assertFalse(is_llm_chat_model("BAAI/bge-m3"))
        self.assertFalse(is_llm_chat_model("Qwen/Qwen3-ASR-1.7B"))
        models = filter_llm_catalog_models(
            [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "free": True},
                {"id": "deepseek-ai/DeepSeek-OCR", "free": True},
                {"id": "BAAI/bge-m3", "free": True},
            ],
            provider="siliconflow",
        )
        self.assertEqual([item["id"] for item in models], ["Qwen/Qwen2.5-7B-Instruct"])


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

    @patch("requests.Session.get")
    def test_admin_lists_siliconflow_free_models(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen2.5-7B-Instruct (Free)"},
                {"id": "Pro/Qwen/Qwen2.5-7B-Instruct", "name": "Qwen2.5-7B-Instruct"},
                {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3"},
            ]
        }
        mock_get.return_value = mock_response
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-siliconflow-test-key",
            "model": "Qwen/Qwen2.5-7B-Instruct",
        })
        from backend.app.auth import csrf_token
        self.client.cookies.set("zly_ai_video_studio_session", self.admin_token)
        res = self.client.post(
            "/api/admin/providers/llm/models",
            json={"base_url": "https://api.siliconflow.cn/v1", "free_only": True},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        ids = [item["id"] for item in res.json()["models"]]
        self.assertEqual(ids, ["Qwen/Qwen2.5-7B-Instruct"])

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


class LLMConnectionTestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.job_store = JobStore(self.db_path)
        self.provider = LlmProviderService(self.job_store, self.credential_key)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["qwen2.5:7b-instruct"])
    def test_connection_reports_missing_local_model(self, _mock_list: MagicMock) -> None:
        client = OpenAICompatibleClient("http://127.0.0.1:11434/v1", "ollama")
        with self.assertRaises(LlmError) as ctx:
            client.test_connection("qwen2.5:7b")
        self.assertIn("qwen2.5:7b-instruct", str(ctx.exception))
        self.assertIn("未找到模型", str(ctx.exception))

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["qwen2.5:7b-instruct"])
    @patch.object(OpenAICompatibleClient, "chat_completion", return_value="收到")
    def test_connection_uses_caller_timeout(self, mock_chat: MagicMock, _mock_list: MagicMock) -> None:
        client = OpenAICompatibleClient("http://127.0.0.1:11434/v1", "ollama")
        self.assertEqual(client.test_connection("qwen2.5:7b-instruct", timeout=90.0), "收到")
        self.assertEqual(mock_chat.call_args.kwargs["timeout"], 90.0)

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["qwen2.5:7b-instruct"])
    @patch.object(
        OpenAICompatibleClient,
        "chat_completion",
        side_effect=LlmTemporaryError("请求大模型服务超时（等待 90 秒仍无响应）：Read timed out"),
    )
    def test_connection_rewrites_local_timeout(self, _mock_chat: MagicMock, _mock_list: MagicMock) -> None:
        client = OpenAICompatibleClient("http://127.0.0.1:11434/v1", "ollama")
        with self.assertRaises(LlmTemporaryError) as ctx:
            client.test_connection("qwen2.5:7b-instruct", timeout=90.0)
        self.assertIn("首次加载", str(ctx.exception))

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="收到")
    def test_provider_uses_longer_timeout_for_local_ollama(self, mock_test: MagicMock) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b-instruct",
        })
        result = self.provider.test()
        self.assertEqual(mock_test.call_args.kwargs["timeout"], 90.0)
        self.assertEqual(result["last_test_status"], "成功")

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="ok")
    def test_provider_keeps_short_timeout_for_cloud(self, mock_test: MagicMock) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "https://api-inference.modelscope.cn/v1",
            "api_key": "ms-secret-token-12345678",
            "model": "deepseek-ai/DeepSeek-V4-Flash-0731",
        })
        self.provider.test()
        self.assertEqual(mock_test.call_args.kwargs["timeout"], 15.0)


if __name__ == "__main__":
    unittest.main()

