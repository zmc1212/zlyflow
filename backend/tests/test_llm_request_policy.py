from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.llm_client import LlmError, LlmTemporaryError, OpenAICompatibleClient
from backend.app.llm_request_policy import chat_policy, probe_token_budget
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.vision_capability import probe_vision_capability

BAILIAN = "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def ok_response(content: str = "正常中文回复") -> MagicMock:
    response = MagicMock(status_code=200)
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {"choices": [{"message": {
        "content": content, "reasoning_content": "不应成为正文的推理",
    }}]}
    return response


class OfficialParameterPolicyTests(unittest.TestCase):
    @patch("requests.Session.post")
    def test_kimi_fixed_temperature_models_use_defaults_and_keep_creation_budget(self, post):
        def kimi_upstream(_url, **kwargs):
            payload = kwargs["json"]
            # 重现截图中的供应商校验，而非仅断言本地策略函数。
            if "temperature" in payload:
                bad = MagicMock(status_code=400)
                bad.json.return_value = {"error": {"message": "Parameter 'temperature'=0.7 is not supported for kimi-k3 model."}}
                return bad
            return ok_response()
        post.side_effect = kimi_upstream
        for model in ("kimi-k3", "KIMI/kimi-k3", "kimi-k2.7-code", "kimi-k2-thinking", "kimi-k2.6", "kimi-k2.5"):
            for stream in (False, True):
                with self.subTest(model=model, stream=stream):
                    meta = {}
                    result = OpenAICompatibleClient(BAILIAN, "secret").chat_completion(
                        [{"role": "user", "content": "正文要求"}], model,
                        temperature=0.7, max_tokens=12000, stream=stream,
                        reasoning_effort="none", meta_out=meta,
                    )
                    self.assertEqual(result, "正常中文回复")
                    payload = post.call_args.kwargs["json"]
                    self.assertEqual(payload["max_tokens"], 12000)
                    self.assertNotIn("reasoning_effort", payload)
                    self.assertIsNone(meta["temperature"])
                    self.assertEqual(meta["effective_parameters"], {k: v for k, v in payload.items() if k != "messages"})
                    self.assertNotIn("secret", str(meta))
                    self.assertNotIn("正文要求", str(meta))

    @patch.object(OpenAICompatibleClient, "list_models", return_value=["kimi-k3"])
    @patch("requests.Session.post")
    def test_kimi_connection_has_reasoning_budget(self, post, _models):
        post.return_value = ok_response()
        self.assertEqual(OpenAICompatibleClient(BAILIAN, "key").test_connection("kimi-k3"), "正常中文回复")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("temperature", payload)
        self.assertTrue(payload["enable_thinking"])
        self.assertEqual(payload["max_tokens"], 4096)
        post.assert_called_once()

    @patch("requests.Session.post")
    def test_provider_specific_thinking_field_not_sent_to_moonshot(self, post):
        post.return_value = ok_response()
        OpenAICompatibleClient("https://api.moonshot.ai/v1", "key").chat_completion(
            [{"role": "user", "content": "hi"}], "kimi-k3",
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("enable_thinking", payload)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("temperature", payload)

    @patch("requests.Session.post")
    def test_unknown_alias_uses_minimal_request_without_vendor_guessing(self, post):
        post.return_value = ok_response()
        messages = [{"role": "user", "content": "完整任务"}]
        OpenAICompatibleClient(BAILIAN, "key").chat_completion(
            messages, "custom-alias", temperature=0.4, max_tokens=6000,
        )
        self.assertEqual(post.call_args.kwargs["json"], {
            "model": "custom-alias", "messages": messages, "max_tokens": 6000,
        })

    @patch("requests.Session.post")
    def test_unrecognized_rules_fail_explicitly_without_error_guessing_or_retries(self, post):
        response = MagicMock(status_code=400)
        response.json.return_value = {"error": {"message": "The model needs a different protocol."}}
        post.return_value = response
        with self.assertRaises(LlmError):
            OpenAICompatibleClient(BAILIAN, "key").chat_completion(
                [{"role": "user", "content": "hi"}], "unknown-model",
            )
        post.assert_called_once()

    @patch("requests.Session.post")
    @patch.object(LlmService, "_runtime_config", return_value=(BAILIAN, "kimi-k3", "key"))
    def test_character_generation_uses_same_policy_and_preserves_json_requirement(self, _config, post):
        post.return_value = ok_response('{"description":"现代青年，白衬衫", "visual_prompt":"单人全身白底"}')
        result = LlmService.generate_character_content("现代青年")
        self.assertEqual(result["description"], "现代青年，白衬衫")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("temperature", payload)
        self.assertTrue(payload["enable_thinking"])
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    @patch("requests.Session.post")
    def test_kimi_vision_probe_preserves_distinct_images_and_verifies_colors(self, post):
        post.side_effect = [ok_response("red"), ok_response("blue")]
        result = probe_vision_capability(base_url=BAILIAN, api_key="key", model="kimi-k3")
        self.assertEqual(result.capability, "supported")
        payloads = [call.kwargs["json"] for call in post.call_args_list]
        self.assertNotEqual(payloads[0]["messages"][1]["content"][1], payloads[1]["messages"][1]["content"][1])
        for payload in payloads:
            self.assertEqual(payload["max_tokens"], 4096)
            self.assertNotIn("temperature", payload)

    def test_thinking_only_models_use_probe_budget_without_disable_field(self):
        for model in ("deepseek-r1", "MiniMax-M2.5", "qwq-plus", "qwen3-235b-a22b-thinking-2507", "qwen3.8-2.4t-a95b"):
            with self.subTest(model=model):
                policy = chat_policy(model, BAILIAN)
                self.assertTrue(policy.thinking_required)
                self.assertIsNone(policy.thinking_control)
                self.assertEqual(probe_token_budget(model, BAILIAN, 8), 4096)

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_thinking_probe_uses_longer_default_deadline(self, client):
        client.return_value.chat_completion.side_effect = ["red", "blue"]
        result = probe_vision_capability(base_url=BAILIAN, api_key="key", model="kimi-k3")
        self.assertEqual(result.capability, "supported")
        self.assertGreater(client.return_value.chat_completion.call_args_list[0].kwargs["timeout"], 80)

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_explicit_probe_timeout_is_preserved(self, client):
        client.return_value.chat_completion.side_effect = ["red", "blue"]
        probe_vision_capability(base_url=BAILIAN, api_key="key", model="kimi-k3", timeout=5)
        self.assertLessEqual(client.return_value.chat_completion.call_args_list[0].kwargs["timeout"], 5)

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_temporary_probe_failure_does_not_claim_no_vision(self, client):
        client.return_value.chat_completion.side_effect = LlmTemporaryError("响应超时")
        result = probe_vision_capability(base_url=BAILIAN, api_key="key", model="kimi-k3")
        self.assertEqual(result.capability, "unknown")
        self.assertIn("暂未完成", result.message)


if __name__ == "__main__":
    unittest.main()
