from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from backend.app import llm_provider as provider_module
from backend.app.llm_capabilities import detect_capabilities
from backend.app.llm_client import (
    ChatResult,
    LlmCapabilityError,
    OpenAICompatibleClient,
    apply_explicit_cache,
    capability_rejection_field,
    normalize_tool_calls,
    normalize_usage,
)
from backend.app.llm_provider import LlmProviderService
from backend.app.storage import JobStore

DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK = "https://api.deepseek.com/v1"
MODELSCOPE = "https://api-inference.modelscope.cn/v1"
ZHIPU = "https://open.bigmodel.cn/api/paas/v4"
OLLAMA = "http://127.0.0.1:11434/v1"


class CapabilityDetectionTests(unittest.TestCase):
    def test_qwen37_uses_every_optional_capability(self):
        caps = detect_capabilities(DASHSCOPE, "qwen3.7-max")
        self.assertEqual(caps.provider, "dashscope")
        self.assertTrue(caps.native_tools)
        self.assertEqual(caps.structured_output, "json_schema")
        self.assertEqual(caps.prompt_cache, "explicit")
        self.assertTrue(caps.web_search)

    def test_qwen_cache_tiers(self):
        self.assertEqual(detect_capabilities(DASHSCOPE, "qwen-plus").prompt_cache, "explicit")
        self.assertEqual(detect_capabilities(DASHSCOPE, "qwen2.5-72b-instruct").prompt_cache, "implicit")
        self.assertEqual(detect_capabilities(DASHSCOPE, "qwen2.5-72b-instruct").structured_output, "json_object")
        self.assertTrue(detect_capabilities(DASHSCOPE, "qwen2.5-72b-instruct").web_search)
        self.assertFalse(detect_capabilities("https://api.openai.com/v1", "gpt-4o-mini").web_search)

    def test_bailian_text_models_are_not_limited_to_one_model(self):
        for model in ("qwen-long", "qwen3-max", "kimi-k2-0905-preview", "MiniMax-M2", "qwq-plus"):
            caps = detect_capabilities(DASHSCOPE, model)
            self.assertTrue(caps.native_tools, model)
            self.assertTrue(caps.web_search, model)
            self.assertIn(caps.structured_output, {"json_object", "json_schema"}, model)
            self.assertIn(caps.prompt_cache, {"implicit", "explicit"}, model)
        self.assertEqual(detect_capabilities(DASHSCOPE, "qwen3-max").structured_output, "json_schema")
        self.assertEqual(detect_capabilities(DASHSCOPE, "qwen3-max").prompt_cache, "explicit")

    def test_vision_models_opt_out_of_text_features(self):
        caps = detect_capabilities(DASHSCOPE, "qwen3-vl-plus")
        self.assertFalse(caps.native_tools)
        self.assertIsNone(caps.structured_output)
        self.assertIsNone(caps.prompt_cache)
        self.assertFalse(caps.web_search)

    def test_deepseek_official(self):
        caps = detect_capabilities(DEEPSEEK, "deepseek-chat")
        self.assertEqual(caps.provider, "deepseek")
        self.assertTrue(caps.native_tools)
        self.assertEqual(caps.structured_output, "json_object")
        self.assertEqual(caps.prompt_cache, "implicit")
        self.assertFalse(caps.web_search)

    def test_modelscope_keeps_native_tools_off(self):
        caps = detect_capabilities(MODELSCOPE, "deepseek-ai/DeepSeek-V4-Flash-0731")
        self.assertEqual(caps.provider, "modelscope")
        self.assertFalse(caps.native_tools)
        self.assertEqual(caps.structured_output, "json_object")

    def test_other_gateways(self):
        self.assertTrue(detect_capabilities(ZHIPU, "glm-4.6").native_tools)
        self.assertFalse(detect_capabilities(ZHIPU, "some-other-model").native_tools)
        self.assertEqual(detect_capabilities(OLLAMA, "qwen3:8b").structured_output, "json_schema")
        self.assertEqual(
            detect_capabilities("https://api.openai.com/v1", "gpt-4o-mini").structured_output,
            "json_schema",
        )


class ClientCapabilityTests(unittest.TestCase):
    def test_normalize_usage_reads_provider_shapes(self):
        usage = normalize_usage({
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 100},
        })
        self.assertEqual(usage["cached_tokens"], 100)
        self.assertEqual(usage["total_tokens"], 150)
        self.assertEqual(normalize_usage({"prompt_cache_hit_tokens": 40}), {})
        self.assertEqual(normalize_usage(None), {})

    def test_normalize_tool_calls_keeps_json_string_arguments(self):
        calls = normalize_tool_calls([{"id": "a", "function": {"name": "editor_read", "arguments": {"x": 1}}}])
        self.assertEqual(calls[0]["function"]["arguments"], '{"x": 1}')
        self.assertEqual(normalize_tool_calls([{"function": {"name": ""}}]), [])

    def test_explicit_cache_marks_tail_user_message(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ]
        cached = apply_explicit_cache(messages)
        self.assertEqual(cached[1]["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(messages[1]["content"], "hi")

    def test_explicit_cache_skips_tool_turns(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{}"},
        ]
        cached = apply_explicit_cache(messages)
        self.assertIsInstance(cached[1]["content"], list)
        self.assertEqual(cached[3]["content"], "{}")

    def test_capability_rejection_detection(self):
        self.assertEqual(
            capability_rejection_field(400, "unknown parameter: stream_options", {"stream_options"}), "stream_options",
        )
        self.assertEqual(
            capability_rejection_field(422, "Extra inputs are not permitted: enable_search", {"enable_search"}), "enable_search",
        )
        self.assertIsNone(capability_rejection_field(401, "stream_options unauthorized", {"stream_options"}))
        self.assertIsNone(capability_rejection_field(400, "model not found", {"tools"}))

    @patch("requests.Session.post")
    def test_payload_carries_optional_capabilities(self, mock_post: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        mock_post.return_value = response
        client = OpenAICompatibleClient(DASHSCOPE, "sk-test")
        result = client.chat_completion_result(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
            "qwen3.7-max",
            stream=False,
            response_format={"type": "json_object"},
            tools=[{"type": "function", "function": {"name": "editor_read", "parameters": {"type": "object"}}}],
            enable_search=True,
            cache_control=True,
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(payload["enable_search"])
        self.assertNotIn("stream_options", payload)
        self.assertEqual(payload["messages"][1]["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(result.usage["total_tokens"], 7)
        self.assertEqual(result.mode, "native")

    @patch("requests.Session.post")
    def test_legacy_payload_unchanged(self, mock_post: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_post.return_value = response
        client = OpenAICompatibleClient(MODELSCOPE, "ms")
        client.chat_completion([{"role": "user", "content": "hi"}], "deepseek-ai/DeepSeek-V4-Flash-0731")
        payload = mock_post.call_args.kwargs["json"]
        for key in ("tools", "response_format", "enable_search", "cache_control", "stream_options"):
            self.assertNotIn(key, payload)

    @patch("requests.Session.post")
    def test_stream_collects_tool_calls_and_usage(self, mock_post: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"create_draft","arguments":"{\\"artifact_type\\""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"script\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
            "data: [DONE]",
        ]
        mock_post.return_value = response
        client = OpenAICompatibleClient(DASHSCOPE, "sk-test")
        result = client.chat_completion_result(
            [{"role": "user", "content": "写剧本"}],
            "qwen3.7-max",
            stream=True,
            tools=[{"type": "function", "function": {"name": "create_draft", "parameters": {"type": "object"}}}],
            include_usage=True,
        )
        self.assertEqual(result.mode, "native")
        self.assertEqual(result.tool_calls[0]["id"], "call_1")
        self.assertEqual(result.tool_calls[0]["function"]["name"], "create_draft")
        self.assertEqual(result.tool_calls[0]["function"]["arguments"], '{"artifact_type":"script"}')
        self.assertEqual(result.usage["total_tokens"], 15)
        self.assertEqual(result.finish_reason, "tool_calls")


class ProviderCapabilityDegradationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = JobStore(Path(self.temp_dir.name) / "cap.db")
        self.provider = LlmProviderService(self.store, Fernet.generate_key().decode("ascii"))
        provider_module._CAPABILITY_DEGRADED.clear()
        self.addCleanup(provider_module._CAPABILITY_DEGRADED.clear)

    def test_explicit_cache_is_requested_for_qwen37(self):
        self.provider.update({
            "enabled": True,
            "base_url": DASHSCOPE,
            "api_key": "sk-test-12345678",
            "model": "qwen3.7-max",
            "assistant_models": ["qwen3.7-max"],
        })
        captured: list[dict] = []

        def fake_request(client, messages, model_id, on_chunk, options):
            captured.append(options)
            return ChatResult(content="ok", usage={"total_tokens": 9})

        with patch.object(LlmProviderService, "_assistant_request", side_effect=fake_request):
            result = self.provider.assistant_chat_with_meta(
                [{"role": "user", "content": "hi"}], "qwen3.7-max", tools=[{"type": "function", "function": {"name": "x"}}],
            )
        self.assertTrue(captured[0]["tools"])
        self.assertTrue(captured[0]["cache_control"])
        self.assertTrue(captured[0]["include_usage"])
        self.assertEqual(result.usage["total_tokens"], 9)

    def test_rejected_field_is_retried_and_remembered(self):
        self.provider.update({
            "enabled": True,
            "base_url": DASHSCOPE,
            "api_key": "sk-test-12345678",
            "model": "qwen3.7-max",
            "assistant_models": ["qwen3.7-max"],
        })
        calls: list[dict] = []

        def fake_request(client, messages, model_id, on_chunk, options):
            calls.append(dict(options))
            if len(calls) == 1:
                raise LlmCapabilityError("tools", "tools are not supported")
            return ChatResult(content="ok")

        with patch.object(LlmProviderService, "_assistant_request", side_effect=fake_request):
            result = self.provider.assistant_chat_with_meta(
                [{"role": "user", "content": "hi"}], "qwen3.7-max", tools=[{"type": "function", "function": {"name": "x"}}],
            )
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[1]["tools"])
        self.assertEqual(result.extra["degraded"], ["native_tools"])
        self.assertFalse(self.provider.assistant_capabilities("qwen3.7-max")["native_tools"])
        self.assertIn("native_tools", self.provider.assistant_capabilities("qwen3.7-max")["degraded"])

    def test_catalog_exposes_capabilities(self):
        self.provider.update({
            "enabled": True,
            "base_url": MODELSCOPE,
            "api_key": "ms-test-12345678",
            "model": "deepseek-ai/DeepSeek-V4-Flash-0731",
            "assistant_models": ["deepseek-ai/DeepSeek-V4-Flash-0731"],
        })
        models = self.provider.assistant_model_catalog()
        self.assertEqual(models[0]["id"], "deepseek-ai/DeepSeek-V4-Flash-0731")
        self.assertEqual(models[0]["capabilities"]["structured_output"], "json_object")
        self.assertFalse(models[0]["capabilities"]["web_search"])


if __name__ == "__main__":
    unittest.main()
