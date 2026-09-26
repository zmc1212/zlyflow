from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.llm_provider import model_supports_vision
from backend.app.vision_capability import _CACHE, VisionProbeResult, probe_fields
from backend.app.skill_packs.handlers import parse_dual_author_output, extract_ref2va_prompt
from backend.app.vision_runtime import (
    VISION_FAILURE_BLOCK,
    VISION_FAILURE_WARN_AND_TEXT,
    VISION_STATUS_FAILED_TEXT_FALLBACK,
    VisionEndpoint,
    analysis_vision_public,
    authoring_vision_public,
    build_user_content,
    chat_on_endpoint,
    complete_authoring,
    llm_status_vision_fields,
    overlay_vlm_credentials,
    resolve_analysis_endpoint,
    resolve_authoring_endpoint,
)


class VisionResolverTests(unittest.TestCase):
    def setUp(self):
        _CACHE.clear()
        self.addCleanup(_CACHE.clear)
        for source, model, key in (("llm", "gpt-5.6-sol", "sk-llm"), ("vlm", "glm-4v-flash", "sk-vlm")):
            row = {"enabled": 1, "base_url": f"https://{source}.example/v1", "model": model, "api_key": key}
            probe_fields(row, VisionProbeResult("supported", "mock verified endpoint"))
        probe = patch("backend.app.vision_capability.probe_vision_capability", return_value=VisionProbeResult("unsupported", "mock unsupported"))
        probe.start()
        self.addCleanup(probe.stop)

    def test_llm_vision_wins_for_authoring(self) -> None:
        endpoint = resolve_authoring_endpoint(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
            {"enabled": 1, "base_url": "https://vlm.example/v1", "model": "glm-4v-flash", "api_key": "sk-vlm"},
        )
        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertEqual("llm", endpoint.source)
        self.assertEqual("gpt-5.6-sol", endpoint.model)
        self.assertTrue(endpoint.attach_images)

    def test_seven_b_does_not_attach_images(self) -> None:
        endpoint = resolve_authoring_endpoint(
            {
                "enabled": 1,
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "api_key": "sk-7b",
            },
            {"enabled": 0},
        )
        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertFalse(endpoint.attach_images)
        content = build_user_content("写这一镜", ["https://cdn.example/char.png"], attach_images=endpoint.attach_images)
        self.assertIsInstance(content, str)
        self.assertIn("https://cdn.example/char.png", content)
        self.assertNotIn("image_url", content)

    def test_authoring_falls_back_to_vlm_when_llm_cannot_see(self) -> None:
        endpoint = resolve_authoring_endpoint(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "Qwen/Qwen2.5-7B-Instruct", "api_key": "sk-7b"},
            {"enabled": 1, "base_url": "https://vlm.example/v1", "model": "glm-4v-flash", "api_key": "sk-vlm"},
        )
        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertEqual("vlm", endpoint.source)
        self.assertTrue(endpoint.attach_images)
        content = build_user_content("写这一镜", ["https://cdn.example/char.png"], attach_images=True)
        self.assertIsInstance(content, list)
        self.assertEqual("image_url", content[1]["type"])

    def test_analysis_prefers_vlm_over_llm_vision(self) -> None:
        endpoint = resolve_analysis_endpoint(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
            {"enabled": 1, "base_url": "https://vlm.example/v1", "model": "glm-4v-flash", "api_key": "sk-vlm"},
        )
        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertEqual("vlm", endpoint.source)

    def test_analysis_falls_back_to_llm_vision(self) -> None:
        endpoint = resolve_analysis_endpoint(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
            {"enabled": 0},
        )
        self.assertIsNotNone(endpoint)
        assert endpoint is not None
        self.assertEqual("llm", endpoint.source)
        self.assertTrue(endpoint.attach_images)

    def test_analysis_unavailable_for_seven_b(self) -> None:
        endpoint = resolve_analysis_endpoint(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "Qwen/Qwen2.5-7B-Instruct", "api_key": "sk-7b"},
            {"enabled": 0},
        )
        self.assertIsNone(endpoint)

    def test_vlm_can_reuse_llm_credentials(self) -> None:
        merged = overlay_vlm_credentials(
            {
                "enabled": 1,
                "use_llm_credentials": True,
                "base_url": "https://old-vlm.example/v1",
                "model": "glm-4.6v-flash",
            },
            {"base_url": "https://llm.example/v1", "api_key_encrypted": "enc-llm", "model": "deepseek-v4.1-flash"},
        )
        self.assertEqual("https://llm.example/v1", merged["base_url"])
        self.assertEqual("enc-llm", merged["api_key_encrypted"])
        self.assertEqual("deepseek-v4.1-flash", merged["model"])

    def test_status_fields_do_not_mix_vlm_only_with_authoring(self) -> None:
        authoring = authoring_vision_public(
            llm_available=True,
            llm_model="gpt-5.6-sol",
            llm_supports_vision=True,
            vlm_available=False,
            vlm_model=None,
        )
        analysis = analysis_vision_public(
            llm_available=True,
            llm_model="gpt-5.6-sol",
            llm_supports_vision=True,
            vlm_available=False,
            vlm_model=None,
        )
        self.assertTrue(authoring["attach_images"])
        self.assertEqual("llm", authoring["source"])
        self.assertTrue(analysis["available"])
        self.assertEqual("llm", analysis["source"])
        self.assertTrue(model_supports_vision("gpt-5.6-sol"))
        self.assertFalse(model_supports_vision("Qwen/Qwen2.5-7B-Instruct"))
        fields = llm_status_vision_fields(
            llm_available=True,
            llm_model="Qwen/Qwen2.5-7B-Instruct",
            vlm_available=False,
            vlm_model=None,
        )
        self.assertFalse(fields["supports_vision"])
        self.assertFalse(fields["authoring_vision"]["attach_images"])
        self.assertFalse(fields["analysis_vision"]["available"])

    @patch("backend.app.vision_runtime.chat_on_endpoint")
    def test_authoring_records_failed_text_fallback(self, mock_chat) -> None:
        mock_chat.side_effect = [RuntimeError("vision down"), "text draft"]
        text, meta = complete_authoring(
            {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
            {"enabled": 0},
            None,
            "system",
            "user",
            ["https://cdn.example/char.png"],
            on_failure=VISION_FAILURE_WARN_AND_TEXT,
        )
        self.assertEqual("text draft", text)
        self.assertEqual(VISION_STATUS_FAILED_TEXT_FALLBACK, meta.status)
        self.assertEqual(2, mock_chat.call_count)
        self.assertTrue(mock_chat.call_args_list[0].args[0].attach_images)
        self.assertFalse(mock_chat.call_args_list[1].args[0].attach_images)
        self.assertNotIn("image_url", str(build_user_content("x", ["https://x/a.png"], attach_images=False)))

    @patch("backend.app.vision_runtime.chat_on_endpoint")
    def test_authoring_block_strategy_raises_instead_of_fallback(self, mock_chat) -> None:
        mock_chat.side_effect = [RuntimeError("vision down"), "text draft"]
        with self.assertRaisesRegex(RuntimeError, "vision down"):
            complete_authoring(
                {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
                {"enabled": 0},
                None,
                "system",
                "user",
                ["https://cdn.example/char.png"],
                on_failure=VISION_FAILURE_BLOCK,
            )
        # The failing vision call must not be followed by a silent text retry.
        self.assertEqual(1, mock_chat.call_count)

    def test_authoring_rejects_unknown_failure_strategy(self) -> None:
        with self.assertRaisesRegex(ValueError, "带图失败策略"):
            complete_authoring(
                {"enabled": 1, "base_url": "https://llm.example/v1", "model": "gpt-5.6-sol", "api_key": "sk-llm"},
                {"enabled": 0},
                None,
                "system",
                "user",
                ["https://cdn.example/char.png"],
                on_failure="silent",
            )

    @patch("backend.app.vision_runtime.OpenAICompatibleClient")
    def test_chat_on_endpoint_disables_gpt5_reasoning(self, mock_client_cls) -> None:
        instance = mock_client_cls.return_value
        instance.chat_completion.return_value = "draft"
        endpoint = VisionEndpoint(
            source="llm",
            base_url="https://llm.example/v1",
            model="gpt-5.6-sol",
            api_key="sk-llm",
            attach_images=False,
        )
        text = chat_on_endpoint(endpoint, "sys", "user")
        self.assertEqual("draft", text)
        self.assertEqual("none", instance.chat_completion.call_args.kwargs["reasoning_effort"])
        self.assertEqual(16000, instance.chat_completion.call_args.kwargs["max_tokens"])


class DualAuthorParseTests(unittest.TestCase):
    def test_splits_zh_and_en_blocks(self) -> None:
        zh, en = parse_dual_author_output(
            "preface\n<<<ZH>>>\n镜头目的：对峙\n<<<EN>>>\nsubject_definitions:\nA locked face.\n"
        )
        self.assertIn("镜头目的", zh)
        self.assertTrue(en.lower().startswith("subject_definitions:"))
        self.assertEqual("subject_definitions:\nA locked face.", extract_ref2va_prompt(en))

    def test_plain_zh_without_markers_stays_zh(self) -> None:
        zh, en = parse_dual_author_output("镜头目的：对峙\n参考素材：")
        self.assertIn("镜头目的", zh)
        self.assertEqual("", en)

    def test_unmarked_combined_splits_at_english_headings(self) -> None:
        zh, en = parse_dual_author_output(
            "镜头目的：对峙\n参考素材：<Picture 1>\nsubject_definitions:\nA locked face.\n"
        )
        self.assertIn("镜头目的", zh)
        self.assertNotIn("subject_definitions", zh)
        self.assertTrue(en.lower().startswith("subject_definitions:"))

    def test_english_only_six_sections_are_not_chinese(self) -> None:
        zh, en = parse_dual_author_output("subject_definitions:\nA locked face.\nsummary:\n[Shot 1]\n")
        self.assertEqual("", zh)
        self.assertTrue(en.lower().startswith("subject_definitions:"))
