from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock

from backend.app.llm_client import LlmError, OpenAICompatibleClient
from backend.app.tts_provider import (
    MIMO_BASE_URL,
    MIMO_DEFAULT_VOICE,
    MIMO_TTS_MODEL,
    TtsProviderService,
    detect_tts_provider,
    resolve_tts_voice,
    voice_for_gender,
    voices_for_provider,
)


class MimoProviderDetectionTests(unittest.TestCase):
    def test_detects_mimo_by_base_url_and_model(self) -> None:
        self.assertEqual(detect_tts_provider(base_url=MIMO_BASE_URL), "mimo")
        self.assertEqual(detect_tts_provider(model=MIMO_TTS_MODEL), "mimo")
        self.assertEqual(
            detect_tts_provider(base_url="https://api.xiaomimimo.com/v1", model=MIMO_TTS_MODEL),
            "mimo",
        )

    def test_keeps_other_providers(self) -> None:
        self.assertEqual(detect_tts_provider(base_url="http://127.0.0.1:7866/v1"), "indextts")
        self.assertEqual(detect_tts_provider(base_url="https://api.siliconflow.cn/v1"), "siliconflow")
        self.assertEqual(detect_tts_provider(base_url="https://api.openai.com/v1"), "openai")
        self.assertEqual(detect_tts_provider(base_url="https://example.com/v1"), "custom")

    def test_voice_catalog_has_chinese_and_english_voices(self) -> None:
        voices = voices_for_provider("mimo")
        ids = {item["id"] for item in voices}
        self.assertEqual(len(voices), 9)
        self.assertTrue({"冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"} <= ids)

    def test_gender_mapping_uses_chinese_voices(self) -> None:
        self.assertEqual(voice_for_gender("female", base_url=MIMO_BASE_URL), "冰糖")
        self.assertEqual(voice_for_gender("女", base_url=MIMO_BASE_URL), "冰糖")
        self.assertEqual(voice_for_gender("male", base_url=MIMO_BASE_URL), "苏打")
        self.assertEqual(voice_for_gender("", base_url=MIMO_BASE_URL), MIMO_DEFAULT_VOICE)

    def test_invalid_asset_voice_falls_back_to_gender(self) -> None:
        self.assertEqual(
            resolve_tts_voice("clone", base_url=MIMO_BASE_URL, model=MIMO_TTS_MODEL),
            MIMO_DEFAULT_VOICE,
        )
        self.assertEqual(
            resolve_tts_voice("clone", gender="female", base_url=MIMO_BASE_URL, model=MIMO_TTS_MODEL),
            "冰糖",
        )
        self.assertEqual(
            resolve_tts_voice("Chloe", base_url=MIMO_BASE_URL, model=MIMO_TTS_MODEL),
            "Chloe",
        )


class MimoSpeechTests(unittest.TestCase):
    def _client(self, payload: dict) -> tuple[OpenAICompatibleClient, MagicMock]:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        session = MagicMock()
        session.post.return_value = response
        return OpenAICompatibleClient(MIMO_BASE_URL, "sk-test", session=session), session

    def test_speech_via_chat_decodes_base64_audio(self) -> None:
        audio = b"ID3mimo-audio"
        payload = {
            "choices": [{"message": {"audio": {"data": base64.b64encode(audio).decode()}}}],
        }
        client, session = self._client(payload)
        result = client.speech_via_chat(text="你好", model=MIMO_TTS_MODEL, voice="冰糖")
        self.assertEqual(result, audio)
        _args, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["model"], MIMO_TTS_MODEL)
        self.assertEqual(kwargs["json"]["audio"], {"format": "mp3", "voice": "冰糖"})
        self.assertEqual(kwargs["json"]["messages"], [{"role": "assistant", "content": "你好"}])
        self.assertTrue(str(session.post.call_args[0][0]).endswith("/chat/completions"))

    def test_speech_via_chat_rejects_missing_audio(self) -> None:
        client, _session = self._client({"choices": [{"message": {}}]})
        with self.assertRaises(LlmError):
            client.speech_via_chat(text="你好", model=MIMO_TTS_MODEL, voice="冰糖")

    def test_service_synthesize_routes_mimo_to_chat(self) -> None:
        audio = b"ID3mimo-audio"
        payload = {"choices": [{"message": {"audio": {"data": base64.b64encode(audio).decode()}}}]}
        client, session = self._client(payload)

        class _MimoService(TtsProviderService):
            def __init__(self) -> None:
                pass

            def provider_name(self, config=None) -> str:
                return "mimo"

            def client(self):
                return client, MIMO_TTS_MODEL, MIMO_DEFAULT_VOICE

            def base_url(self, config=None) -> str:
                return MIMO_BASE_URL

            def model(self, config=None) -> str:
                return MIMO_TTS_MODEL

        service = _MimoService()
        result = service.synthesize("你好", voice="clone", gender="male")
        self.assertEqual(result, audio)
        _args, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["audio"]["voice"], "苏打")
        self.assertEqual(kwargs["json"]["messages"][-1]["content"], "你好")


if __name__ == "__main__":
    unittest.main()
