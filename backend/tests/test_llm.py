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
    LLM_TEST_MAX_TOKENS,
    LLM_TEST_TIMEOUT_SECONDS,
    LLM_TEST_USER_PROMPT,
    OpenAICompatibleClient,
    LlmBillingError,
    LlmError,
    LlmStreamStalled,
    LlmTemporaryError,
    looks_like_short_input_probe,
    looks_like_gateway_timeout,
    parse_model_catalog,
    parse_siliconflow_plaza_free_ids,
    raise_llm_http_error,
    summarize_llm_test_reply,
)
from backend.app.llm_provider import LlmProviderService
from backend.app.vlm_provider import VlmProviderService
from backend.app.main import app, session_cookie_scheme
from backend.app.models import UserRole
from backend.app.storage import JobStore
from backend.tests.app_state_guard import restore_app_state, snapshot_app_state


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
        self.assertNotIn("enable_thinking", payload)

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
        self.assertNotIn("enable_thinking", payload)

    @patch("requests.Session.post")
    def test_original_hybrid_qwen3_keeps_thinking_switch(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://api.siliconflow.cn/v1", "sk-test")
        for model in ("Qwen/Qwen3-8B", "Qwen/Qwen3-30B-A3B", "Pro/Qwen/Qwen3-235B-A22B", "qwen3-8b:latest"):
            with self.subTest(model=model):
                client.chat_completion([{"role": "user", "content": "你好"}], model)
                self.assertFalse(mock_post.call_args.kwargs["json"]["enable_thinking"])

    @patch("requests.Session.post")
    def test_fixed_mode_and_vision_models_omit_thinking_switch(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://api.siliconflow.cn/v1", "sk-test")
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "描述画面"},
            {"type": "image_url", "image_url": {"url": "https://example.com/ref.png"}},
        ]}]
        for model in (
            "Qwen/Qwen3-VL-30B-A3B-Thinking", "Qwen/Qwen3-VL-30B-A3B-Instruct",
            "Qwen/Qwen3-30B-A3B-Thinking-2507", "Qwen/Qwen3-30B-A3B-Instruct-2507",
            "Qwen/Qwen2.5-VL-72B-Instruct", "glm-4.1v-thinking-flash", "zai-org/GLM-4.5V",
        ):
            with self.subTest(model=model):
                self.assertEqual("收到", client.chat_completion(messages, model))
                payload = mock_post.call_args.kwargs["json"]
                self.assertNotIn("enable_thinking", payload)
                self.assertNotIn("thinking", payload)
                self.assertEqual(messages, payload["messages"])

    @patch("requests.Session.post")
    def test_gpt5_sol_uses_max_completion_tokens_without_temperature(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://cn3.heilovehei.com/v1", "sk-test")
        client.chat_completion(
            [{"role": "user", "content": "expand this shot"}],
            "gpt-5.6-sol",
            temperature=0.7,
            max_tokens=1536,
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], 1536)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("enable_thinking", payload)
        self.assertNotIn("thinking", payload)

    @patch("requests.Session.post")
    def test_gpt5_reasoning_effort_is_forwarded(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response()
        client = OpenAICompatibleClient("https://cn3.heilovehei.com/v1", "sk-test")
        client.chat_completion(
            [{"role": "user", "content": "expand this shot"}],
            "gpt-5.6-sol",
            max_tokens=64,
            reasoning_effort="none",
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["max_completion_tokens"], 64)


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
    def test_stream_connection_error_wrapping_timeout_is_temporary(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.side_effect = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool: Read timed out. (read timeout=300)",
        )
        mock_post.return_value = mock_response

        with self.assertRaises(LlmTemporaryError) as ctx:
            self._client().chat_completion(
                [{"role": "user", "content": "hi"}],
                "Qwen/Qwen2.5-7B-Instruct",
                timeout=300.0,
                stream=True,
            )

        self.assertIn("等待 300 秒仍无响应", str(ctx.exception))
        self.assertNotIn("HTTPSConnectionPool", str(ctx.exception))

    @patch("requests.Session.post")
    def test_stream_stops_on_finish_reason_without_done(self, mock_post: MagicMock) -> None:
        def lines():
            yield 'data: {"choices":[{"delta":{"content":"完成"},"finish_reason":"stop"}]}'
            raise AssertionError("finish_reason 之后不应继续等待流结束")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.return_value = lines()
        mock_post.return_value = mock_response
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "Qwen/Qwen2.5-7B-Instruct",
            stream=True,
        )
        self.assertEqual(text, "完成")

    @patch("requests.Session.post")
    def test_stream_idle_watchdog_aborts_silent_connection(self, mock_post: MagicMock) -> None:
        import threading

        closed = threading.Event()

        class SilentStream:
            status_code = 200
            headers = {"Content-Type": "text/event-stream"}
            encoding = "utf-8"

            def iter_lines(self, decode_unicode: bool = False):
                yield 'data: {"choices":[{"delta":{"content":"前半"}}]}'
                closed.wait(5)

            def close(self) -> None:
                closed.set()

        mock_post.return_value = SilentStream()
        with self.assertRaises(LlmStreamStalled) as ctx:
            self._client().chat_completion(
                [{"role": "user", "content": "hi"}],
                "Qwen/Qwen2.5-7B-Instruct",
                stream=True,
                stream_idle_timeout=0.2,
            )
        self.assertIn("没有返回新内容", str(ctx.exception))
        self.assertTrue(closed.is_set())

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
    def test_stream_emits_reasoning_and_strips_think_tags(self, mock_post: MagicMock) -> None:
        from backend.app.llm_client import ThinkStreamSplitter

        splitter = ThinkStreamSplitter()
        self.assertEqual(splitter.feed("<thi"), [])
        self.assertEqual(splitter.feed("nk>先想一步"), [("reasoning", "先想一步")])
        self.assertEqual(splitter.feed("</th"), [])
        self.assertEqual(splitter.feed("ink>正文"), [("content", "正文")])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_lines.return_value = [
            "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"看镜头\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\"<think>内部\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\"</think>subject_definitions:\"}}]}",
            "data: [DONE]",
        ]
        mock_post.return_value = mock_response
        deltas: list[tuple[str, str]] = []
        text = self._client().chat_completion(
            [{"role": "user", "content": "hi"}],
            "gpt-5.6-sol",
            stream=True,
            on_delta=lambda kind, piece: deltas.append((kind, piece)),
        )
        self.assertEqual(text, "subject_definitions:")
        self.assertEqual(deltas[0], ("reasoning", "看镜头"))
        self.assertIn(("reasoning", "内部"), deltas)
        self.assertIn(("content", "subject_definitions:"), deltas)

    def test_stream_delta_parts_reads_reasoning_content(self) -> None:
        reasoning, content = OpenAICompatibleClient._stream_delta_parts({
            "choices": [{"delta": {"reasoning_content": "想", "content": "写"}}],
        })
        self.assertEqual(reasoning, "想")
        self.assertEqual(content, "写")

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


class H3PromptExtractionTests(unittest.TestCase):
    def test_extracts_last_fenced_prompt_from_reasoning(self) -> None:
        from backend.app.llm_minimax_skills import extract_h3_prompt_from_model_output

        raw = (
            "The user wants me to rewrite their idea into an H3 prompt.\n\n"
            "```\nintegrated_multimodal_description: draft one\n\noverall_soundscape: rain\n```\n\n"
            "Let me refine the timing.\n\n"
            "```\nFor the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] final action.\n\n"
            "overall_soundscape: final rain.\n\n"
            "non_diegetic_music: piano.\n```\n\nThis looks good."
        )
        result = extract_h3_prompt_from_model_output(raw)
        self.assertTrue(result.startswith("For the target video"))
        self.assertIn("final action", result)
        self.assertNotIn("The user wants", result)
        self.assertNotIn("This looks good", result)

    def test_keeps_clean_h3_prompt(self) -> None:
        from backend.app.llm_minimax_skills import extract_h3_prompt_from_model_output

        raw = (
            "integrated_multimodal_description: [Shot 1] A cat jumps.\n\n"
            "overall_soundscape: Soft wind.\n\n"
            "non_diegetic_music: Piano."
        )
        self.assertEqual(extract_h3_prompt_from_model_output(raw), raw)

    def test_trims_commentary_after_unwrapped_prompt(self) -> None:
        from backend.app.llm_minimax_skills import extract_h3_prompt_from_model_output

        raw = (
            "I need to plan the shots first.\n\n"
            "integrated_multimodal_description: [Shot 1] Final action.\n\n"
            "overall_soundscape: Rain.\n\n"
            "non_diegetic_music: Piano.\n\n"
            "This looks good. Let me check the timing."
        )
        result = extract_h3_prompt_from_model_output(raw)
        self.assertTrue(result.startswith("integrated_multimodal_description"))
        self.assertNotIn("This looks good", result)
        self.assertNotIn("I need to", result)

    def test_rejects_reasoning_without_final_prompt(self) -> None:
        from backend.app.llm_minimax_skills import extract_h3_prompt_from_model_output

        raw = (
            "The user wants me to rewrite this. "
            "Maybe integrated_multimodal_description: something? Wait, the timing is wrong."
        )
        self.assertEqual(extract_h3_prompt_from_model_output(raw), "")


class H3TranslationCoverageTests(unittest.TestCase):
    ENGLISH = (
        "integrated_multimodal_description: [Shot 1] Rainy street.\n\n"
        "overall_soundscape: Rain and traffic.\n\n"
        "non_diegetic_music: Low strings."
    )

    def test_complete_translation_has_no_missing_fields(self) -> None:
        from backend.app.llm_minimax_skills import missing_h3_translation_fields

        chinese = (
            "integrated_multimodal_description（整合多模态描述）：\n[Shot 1] 雨夜街道。\n\n"
            "overall_soundscape（整体声场）：雨声与车流。\n\n"
            "non_diegetic_music（画外音乐）：低音弦乐。"
        )
        self.assertEqual(missing_h3_translation_fields(self.ENGLISH, chinese), [])

    def test_partial_translation_reports_missing_fields(self) -> None:
        from backend.app.llm_minimax_skills import missing_h3_translation_fields

        chinese = "integrated_multimodal_description（整合多模态描述）：\n[Shot 1] 雨夜街道。"
        self.assertEqual(
            missing_h3_translation_fields(self.ENGLISH, chinese),
            ["overall_soundscape", "non_diegetic_music"],
        )

    def test_translation_keeps_english_field_names(self) -> None:
        from backend.app.llm_minimax_skills import missing_h3_translation_fields

        chinese = (
            "integrated_multimodal_description: 雨夜街道。\n"
            "overall_soundscape: 雨声。\n"
            "non_diegetic_music: 弦乐。"
        )
        self.assertEqual(missing_h3_translation_fields(self.ENGLISH, chinese), [])

    def test_clean_translation_strips_blockquote_markers(self) -> None:
        from backend.app.llm_minimax_skills import clean_h3_translation_output

        raw = "> integrated_multimodal_description（整合多模态描述）：\n> [Shot 1] 雨夜街道。"
        self.assertEqual(
            clean_h3_translation_output(raw),
            "integrated_multimodal_description（整合多模态描述）：\n[Shot 1] 雨夜街道。",
        )


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

    def test_assistant_chat_falls_back_to_non_streaming_after_stall(self) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "http://localhost:1234/v1",
            "model": "model-a",
            "assistant_models": ["model-a"],
        })
        client = MagicMock()
        client.chat_completion.side_effect = [LlmStreamStalled("流式中断"), "完整回复"]
        with patch.object(self.provider, "_chat_client", return_value=(client, "model-a")):
            result = self.provider.assistant_chat([{"role": "user", "content": "hi"}], "model-a")
        self.assertEqual(result, "完整回复")
        self.assertEqual(client.chat_completion.call_count, 2)
        self.assertTrue(client.chat_completion.call_args_list[0].kwargs["stream"])
        self.assertFalse(client.chat_completion.call_args_list[1].kwargs["stream"])
        self.assertEqual(client.chat_completion.call_args_list[0].kwargs["stream_idle_timeout"], 90)

    @patch("requests.Session.post")
    def test_translate_h3_prompt_to_chinese_strips_code_fence(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "```\n整合多模态描述：雨夜街头。\n```"}}]
        }
        mock_post.return_value = mock_response
        client = OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")
        result = client.translate_h3_prompt_to_chinese(
            "integrated_multimodal_description: Rainy street.",
            model="Qwen/Qwen2.5-72B-Instruct",
        )
        self.assertEqual(result, "整合多模态描述：雨夜街头。")
        messages = mock_post.call_args.kwargs["json"]["messages"]
        self.assertIn("中文翻译", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "integrated_multimodal_description: Rainy street.")

    def test_translate_h3_prompt_to_chinese_skips_empty(self) -> None:
        client = OpenAICompatibleClient("https://api-inference.modelscope.cn/v1", "ms-token")
        self.assertEqual(client.translate_h3_prompt_to_chinese("   ", model="Qwen/Qwen2.5-72B-Instruct"), "")

    @patch(
        "backend.app.llm_provider.OpenAICompatibleClient.translate_h3_prompt_to_chinese",
        side_effect=[
            "integrated_multimodal_description（整合多模态描述）：雨夜街道。",
            "integrated_multimodal_description（整合多模态描述）：雨夜街道。\n\n"
            "overall_soundscape（整体声场）：雨声。\n\n"
            "non_diegetic_music（画外音乐）：弦乐。",
        ],
    )
    def test_translate_display_retries_when_sections_missing(self, mock_translate: MagicMock) -> None:
        english = (
            "integrated_multimodal_description: Rainy street.\n\n"
            "overall_soundscape: Rain.\n\n"
            "non_diegetic_music: Strings."
        )
        result = self.provider._translate_prompt_for_display(
            english, {"base_url": "https://api-inference.modelscope.cn/v1", "model": "test-model"}, "key",
        )
        self.assertIn("non_diegetic_music", result)
        self.assertEqual(mock_translate.call_count, 2)
        self.assertEqual(
            mock_translate.call_args_list[1].kwargs["field_reminder"],
            ["overall_soundscape", "non_diegetic_music"],
        )

    @patch(
        "backend.app.llm_provider.OpenAICompatibleClient.translate_h3_prompt_to_chinese",
        return_value="integrated_multimodal_description（整合多模态描述）：雨夜街道。",
    )
    def test_translate_display_returns_empty_when_retry_still_incomplete(self, mock_translate: MagicMock) -> None:
        english = (
            "integrated_multimodal_description: Rainy street.\n\n"
            "overall_soundscape: Rain.\n\n"
            "non_diegetic_music: Strings."
        )
        result = self.provider._translate_prompt_for_display(
            english, {"base_url": "https://api-inference.modelscope.cn/v1", "model": "test-model"}, "key",
        )
        self.assertEqual(result, "")
        self.assertEqual(mock_translate.call_count, 2)

    @patch(
        "backend.app.llm_provider.OpenAICompatibleClient.translate_h3_prompt_to_chinese",
        return_value=(
            "integrated_multimodal_description（整合多模态描述）：雨夜街道。\n\n"
            "overall_soundscape（整体声场）：雨声。\n\n"
            "non_diegetic_music（画外音乐）：弦乐。"
        ),
    )
    def test_translate_display_skips_retry_when_complete(self, mock_translate: MagicMock) -> None:
        english = (
            "integrated_multimodal_description: Rainy street.\n\n"
            "overall_soundscape: Rain.\n\n"
            "non_diegetic_music: Strings."
        )
        result = self.provider._translate_prompt_for_display(
            english, {"base_url": "https://api-inference.modelscope.cn/v1", "model": "test-model"}, "key",
        )
        self.assertIn("non_diegetic_music", result)
        self.assertEqual(mock_translate.call_count, 1)

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="女子在雨夜街道漫步")
    @patch("requests.Session.post")
    def test_optimize_prompt_video(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                            "integrated_multimodal_description: [Shot 1] Cinematic medium shot, a woman in a trench coat walks along a rainy night street, "
                            "neon reflections on the wet pavement, the camera pushes in steadily.\n\n"
                            "overall_soundscape: Rain and distant traffic.\n\n"
                            "non_diegetic_music: Low strings."
                        )
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
        self.assertIn("Cinematic medium shot", result["optimized_prompt"])
        self.assertEqual(result["optimized_prompt_zh"], "女子在雨夜街道漫步")
        mock_post.assert_called_once()
        mock_translate.assert_called_once()
        # 验证 system prompt 包含 MiniMax H3 技能指导与首帧对齐
        call_kwargs = mock_post.call_args[1]
        sent_messages = call_kwargs["json"]["messages"]
        system_content = next(m["content"] for m in sent_messages if m["role"] == "system")
        self.assertIn("integrated_multimodal_description", system_content)
        self.assertIn("极简电商产品广告", system_content)
        self.assertIn("For the target video, at 0.00 seconds into the target video, <Picture 1>", system_content)

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="雨夜街道，镜头推进")
    @patch("requests.Session.post")
    def test_optimize_prompt_extracts_answer_from_reasoning(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": (
                "The user wants me to rewrite their idea into an H3 prompt.\n\n"
                "```\nintegrated_multimodal_description: draft\n\noverall_soundscape: rain\n```\n\n"
                "Let me refine it.\n\n"
                "```\nintegrated_multimodal_description: [Shot 1] Final rainy street.\n\n"
                "overall_soundscape: Final rain.\n\n"
                "non_diegetic_music: Piano.\n```\n\nThis looks good."
            )}}]
        }
        mock_post.return_value = mock_response
        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "XingChenAGI/Xing4.0-29B",
        })

        result = self.provider.optimize_prompt("女子在雨夜散步", media_type="video")

        self.assertTrue(result["optimized_prompt"].startswith("integrated_multimodal_description: [Shot 1] Final rainy street."))
        self.assertNotIn("The user wants", result["optimized_prompt"])
        self.assertNotIn("This looks good", result["optimized_prompt"])
        mock_translate.assert_called_once()
        self.assertEqual(mock_translate.call_args.args[0], result["optimized_prompt"])

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="")
    @patch("requests.Session.post")
    def test_optimize_prompt_rejects_reasoning_without_answer(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "The user wants me to rewrite this. Maybe integrated_multimodal_description: something? Wait, the timing is wrong."}}]
        }
        mock_post.return_value = mock_response
        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "XingChenAGI/Xing4.0-29B",
        })

        with self.assertRaises(LlmError):
            self.provider.optimize_prompt("女子在雨夜散步", media_type="video")
        mock_translate.assert_not_called()

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="小猫在草地上玩耍")
    @patch("requests.Session.post")
    def test_optimize_prompt_dashscope_format(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
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
        self.assertIn("3D Animation", result["optimized_prompt"])
        self.assertEqual(result["optimized_prompt_zh"], "小猫在草地上玩耍")

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="")
    @patch("requests.Session.post")
    def test_optimize_prompt_collection_single_reference_uses_ref2va(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": (
                "subject_definitions:\n<Subject 1> is the woman in a red coat.\n\n"
                "summary:\nA woman walks through a rainy street.\n\n"
                "retention_analysis:\nKeep the coat color and street layout.\n\n"
                "detailed_description:\n[Shot 1] The woman walks toward the camera.\n\n"
                "overall_soundscape:\nRain falls on the pavement.\n\n"
                "non_diegetic_music:\nSoft piano."
            )}}],
        }
        mock_post.return_value = mock_response
        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "Qwen/Qwen2.5-72B-Instruct",
        })

        self.provider.optimize_prompt(
            "女主站在雨夜街头",
            media_type="video",
            reference_count=1,
            workflow_id="minimax-h3-r2v",
            duration_seconds=8,
        )

        system_content = next(
            item["content"] for item in mock_post.call_args[1]["json"]["messages"] if item["role"] == "system"
        )
        self.assertIn("【当前任务模式：Ref2VA (多参考图生成，共 1 张参考图)", system_content)
        self.assertIn("subject_definitions:", system_content)
        self.assertIn("目标视频时长为 8.00 秒", system_content)
        self.assertNotIn("【当前任务模式：I2VA", system_content)

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="")
    @patch("requests.Session.post")
    def test_optimize_prompt_keyframes_two_references_uses_fl2va(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": (
                "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                "Picture 2 (from Shot 1) aligns with the 10.00-second mark of the target video.\n\n"
                "integrated_multimodal_description: [Shot 1] She walks from the door to the window.\n\n"
                "overall_soundscape: Footsteps and rain.\n\n"
                "non_diegetic_music: Warm strings."
            )}}],
        }
        mock_post.return_value = mock_response
        self.provider.update({
            "enabled": True,
            "api_key": "dummy-token",
            "model": "Qwen/Qwen2.5-72B-Instruct",
        })

        self.provider.optimize_prompt(
            "她从门口走到窗前",
            media_type="video",
            reference_count=2,
            workflow_id="minimax-h3-i2v",
            duration_seconds=10,
        )

        system_content = next(
            item["content"] for item in mock_post.call_args[1]["json"]["messages"] if item["role"] == "system"
        )
        self.assertIn("【当前任务模式：FL2VA (首尾帧生成", system_content)
        self.assertIn(
            "Picture 2 (from Shot 1) aligns with the 10.00-second mark of the target video.",
            system_content,
        )
        self.assertNotIn("【当前任务模式：Ref2VA", system_content)



class LLMAppEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        self.vlm_provider = VlmProviderService(self.job_store, self.credential_key)

        self._app_state = snapshot_app_state(app)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        app.state.vlm_provider = self.vlm_provider

        self.admin = self.auth_store.create_user("superadmin", "Super Admin", "password123456", UserRole.SUPER_ADMIN, must_change_password=False)
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee = self.auth_store.create_user("worker", "Worker", "password123456", UserRole.EMPLOYEE, must_change_password=False)
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])

        self.client = TestClient(app)

    def tearDown(self) -> None:
        restore_app_state(app, self._app_state)
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

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="航拍日落，电影感光影")
    @patch("requests.Session.post")
    def test_optimize_prompt_api(self, mock_post: MagicMock, mock_translate: MagicMock) -> None:
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
        self.assertEqual(data["optimized_prompt_zh"], "航拍日落，电影感光影")
        sent_messages = mock_post.call_args[1]["json"]["messages"]
        system_content = next(item["content"] for item in sent_messages if item["role"] == "system")
        self.assertIn("【当前任务模式：Ref2VA", system_content)
        self.assertIn("subject_definitions:", system_content)
        self.assertIn("retention_analysis:", system_content)
        self.assertIn("non_diegetic_music:", system_content)
        self.assertIn("必须严格输出 MiniMax H3 官方六段式", system_content)

    @patch.object(LlmProviderService, "_translate_prompt_for_display", return_value="雨夜城市，霓虹倒影")
    @patch("backend.app.vision_runtime.complete_authoring")
    def test_optimize_prompt_sends_images_when_provided(self, mock_complete: MagicMock, mock_translate: MagicMock) -> None:
        mock_complete.return_value = (
            "integrated_multimodal_description: [Shot 1] A rainy city at night with neon reflections, <Picture 1> is the main character.\n\n"
            "overall_soundscape: Rain and traffic.\n\n"
            "non_diegetic_music: Soft synth.",
            MagicMock(),
        )
        self.llm_provider.update({
            "enabled": True,
            "api_key": "test-modelscope-token",
            "model": "gpt-5.6-sol",
        })
        self.client.cookies.set("zly_ai_video_studio_session", self.employee_token)
        from backend.app.auth import csrf_token
        res = self.client.post(
            "/api/llm/optimize-prompt",
            json={
                "prompt": "雨夜城市",
                "media_type": "video",
                "reference_count": 1,
                "image_urls": ["https://cdn.example/ref.png"],
            },
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("<Picture 1>", res.json()["optimized_prompt"])
        self.assertEqual(res.json()["optimized_prompt_zh"], "雨夜城市，霓虹倒影")
        mock_complete.assert_called_once()
        self.assertEqual(["https://cdn.example/ref.png"], mock_complete.call_args.args[5])


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
        self.assertEqual(mock_chat.call_args.kwargs["max_tokens"], LLM_TEST_MAX_TOKENS)
        messages = mock_chat.call_args.args[0]
        contents = " ".join(str(item.get("content", "")) for item in messages)
        self.assertEqual(messages, [{"role": "user", "content": LLM_TEST_USER_PROMPT}])
        self.assertIn("你是什么模型", contents)
        self.assertGreater(len(LLM_TEST_USER_PROMPT), 20)
        self.assertNotIn("请仅回复两个字", contents)
        self.assertNotIn("分镜说明", contents)
        self.assertNotIn("reasoning_effort", mock_chat.call_args.kwargs)

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["gpt-5.6-sol"])
    @patch.object(OpenAICompatibleClient, "chat_completion", return_value="我是 gpt-5.6-sol，可以正常中文对话。")
    def test_connection_disables_gpt5_reasoning(self, mock_chat: MagicMock, _mock_list: MagicMock) -> None:
        client = OpenAICompatibleClient("https://cn3.heilovehei.com/v1", "sk-test")
        self.assertEqual(
            client.test_connection("gpt-5.6-sol", timeout=90.0),
            "我是 gpt-5.6-sol，可以正常中文对话。",
        )
        self.assertEqual(mock_chat.call_args.kwargs["reasoning_effort"], "none")
        self.assertEqual(mock_chat.call_args.kwargs["max_tokens"], LLM_TEST_MAX_TOKENS)

    def test_short_input_probe_error_is_rewritten(self) -> None:
        upstream = "Upstream rejected illegal short-input distillation or heartbeat probing."
        self.assertTrue(looks_like_short_input_probe(upstream))
        with self.assertRaises(LlmError) as ctx:
            raise_llm_http_error(action="对话推理", status=400, upstream=upstream)
        text = str(ctx.exception)
        self.assertIn("过短的探测请求", text)
        self.assertIn("目录接口可用", text)
        self.assertIn(upstream, text)

    def test_html_gateway_timeout_is_rewritten(self) -> None:
        upstream = (
            "<html><head><title>504 Gateway Time-out</title></head>"
            "<body><center><h1>504 Gateway Time-out</h1></center>"
            "<hr><center>nginx/1.18.0 (Ubuntu)</center></body></html>"
        )
        self.assertTrue(looks_like_gateway_timeout(upstream, 504))
        with self.assertRaises(LlmTemporaryError) as ctx:
            raise_llm_http_error(action="对话推理", status=504, upstream=upstream)
        text = str(ctx.exception)
        self.assertIn("网关超时", text)
        self.assertIn("60 秒", text)
        self.assertNotIn("<html", text)

    def test_success_reply_is_summarized_for_settings_panel(self) -> None:
        long_reply = "9:16 竖屏，都市情感短剧，" + ("夜戏细节 " * 40)
        summary = summarize_llm_test_reply(long_reply)
        self.assertTrue(summary.startswith("连接成功，模型已正常完成一次创作推理："))
        self.assertLessEqual(len(summary), 120)
        self.assertTrue(summary.endswith("…"))

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
        text = str(ctx.exception)
        self.assertIn("首次加载", text)
        self.assertIn("目录接口可用", text)

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="收到")
    def test_provider_uses_longer_timeout_for_local_ollama(self, mock_test: MagicMock) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b-instruct",
        })
        result = self.provider.test()
        self.assertEqual(mock_test.call_args.kwargs["timeout"], LLM_TEST_TIMEOUT_SECONDS)
        self.assertEqual(result["last_test_status"], "成功")

    @patch.object(OpenAICompatibleClient, "test_connection", return_value="ok")
    def test_provider_uses_same_timeout_for_cloud_reasoning_models(self, mock_test: MagicMock) -> None:
        self.provider.update({
            "enabled": True,
            "base_url": "https://api-inference.modelscope.cn/v1",
            "api_key": "ms-secret-token-12345678",
            "model": "gpt-5.6-sol",
        })
        self.provider.test()
        self.assertEqual(mock_test.call_args.kwargs["timeout"], LLM_TEST_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
