from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from backend.app.grs_provider import CredentialManager
from backend.app.llm_provider import LlmProviderService
from backend.app.storage import JobStore


QINIU_URL = "https://api.qnaigc.com/v1"
INTERNAI_URL = "https://discovery-api.intern-ai.org.cn/v1"
LOCAL_URL = "http://127.0.0.1:11434/v1"


class LlmEndpointCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "endpoint-credentials.db")
        self.credential_key = Fernet.generate_key().decode()
        self.service = LlmProviderService(self.store, self.credential_key)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save_config(self, *, base_url: str, model: str, api_key: str | None) -> dict:
        return self.service.update({
            "enabled": True,
            "base_url": base_url,
            "model": model,
            "assistant_models": None,
            "api_key": api_key,
        })

    def test_save_with_key_upserts_endpoint_vault_record(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-rotated")
        records = self.store.list_llm_endpoint_credentials()
        self.assertEqual([row["base_url"] for row in records], [QINIU_URL])
        self.assertEqual(self.service.credentials.decrypt(records[0]["api_key_encrypted"]), "sk-qiniu-rotated")
        self.assertEqual(records[0]["model"], "qiniu/conatus-free")

    def test_same_endpoint_save_without_key_backfills_vault_from_existing(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        # 模拟档案表缺失的历史数据：清空档案但保留主配置凭据。
        with self.store.connection() as connection:
            connection.execute("DELETE FROM llm_endpoint_credentials")
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key=None)
        records = self.store.list_llm_endpoint_credentials()
        self.assertEqual(len(records), 1)
        self.assertEqual(self.service.credentials.decrypt(records[0]["api_key_encrypted"]), "sk-qiniu-secret")

    def test_switch_endpoint_adopts_saved_vault_key_without_resubmitting(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        self.save_config(base_url=INTERNAI_URL, model="intern-s2", api_key="sk-internai-secret")
        # 端砚 → 七牛：不提交 Key，应自动带出七牛档案。
        result = self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key=None)
        self.assertEqual(result["base_url"], QINIU_URL)
        self.assertTrue(result["has_api_key"])
        self.assertEqual(result["api_key_masked"], self.service._mask_key("sk-qiniu-secret"))
        self.assertEqual(self.service.api_key(), "sk-qiniu-secret")
        # 七牛 → 端砚同样自动切回。
        back = self.save_config(base_url=INTERNAI_URL, model="intern-s2", api_key=None)
        self.assertEqual(self.service.api_key(), "sk-internai-secret")
        self.assertEqual(back["model"], "intern-s2")

    def test_switch_endpoint_without_vault_record_still_requires_key(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        with self.assertRaises(ValueError) as caught:
            self.save_config(base_url=INTERNAI_URL, model="intern-s2", api_key=None)
        self.assertIn("还没有保存过凭据", str(caught.exception))
        # 原配置不被破坏。
        self.assertEqual(self.service.api_key(), "sk-qiniu-secret")
        self.assertEqual(self.store.get_llm_settings()["base_url"], QINIU_URL)

    def test_switch_to_local_endpoint_without_record_clears_key(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        result = self.save_config(base_url=LOCAL_URL, model="qwen2.5:7b", api_key=None)
        self.assertIsNone(self.store.get_llm_settings()["api_key_encrypted"])
        self.assertEqual(result["base_url"], LOCAL_URL)

    def test_public_config_lists_masked_credentials_for_all_saved_endpoints(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        self.save_config(base_url=INTERNAI_URL, model="intern-s2", api_key="sk-internai-secret")
        saved = self.service.public_config()["saved_provider_credentials"]
        by_url = {row["base_url"]: row for row in saved}
        self.assertEqual(set(by_url), {QINIU_URL, INTERNAI_URL})
        self.assertEqual(by_url[INTERNAI_URL]["api_key_masked"], self.service._mask_key("sk-internai-secret"))
        self.assertEqual(by_url[QINIU_URL]["model"], "qiniu/conatus-free")
        # 原始 Key 不出现在任何响应字段里。
        import json

        self.assertNotIn("sk-qiniu-secret", json.dumps(self.service.public_config()))

    def test_uses_vault_key_for_non_active_endpoint_on_test_and_catalog(self) -> None:
        self.save_config(base_url=QINIU_URL, model="qiniu/conatus-free", api_key="sk-qiniu-secret")
        self.save_config(base_url=INTERNAI_URL, model="intern-s2", api_key="sk-internai-secret")
        with patch("backend.app.llm_provider.OpenAICompatibleClient") as client_cls:
            client = client_cls.return_value
            client.test_connection.return_value = "回复正常"
            self.service.test({"base_url": QINIU_URL, "model": "qiniu/conatus-free", "api_key": None})
            self.assertEqual(client_cls.call_args.kwargs["api_key"], "sk-qiniu-secret")
            self.service.list_catalog({"base_url": QINIU_URL, "api_key": None})
            self.assertEqual(client_cls.call_args.kwargs["api_key"], "sk-qiniu-secret")
        # 显式提交的 Key 优先于档案。
        with patch("backend.app.llm_provider.OpenAICompatibleClient") as client_cls:
            client_cls.return_value.test_connection.return_value = "回复正常"
            self.service.test({"base_url": QINIU_URL, "model": "qiniu/conatus-free", "api_key": "sk-fresh"})
            self.assertEqual(client_cls.call_args.kwargs["api_key"], "sk-fresh")

    def test_vault_records_survive_independent_of_active_config(self) -> None:
        first = self.store.upsert_llm_endpoint_credential(QINIU_URL, "cipher-a", "model-a")
        self.assertEqual(first["model"], "model-a")
        second = self.store.upsert_llm_endpoint_credential(QINIU_URL + "/", "cipher-b", "model-b")
        # 归一化后指向同一条记录（尾部斜杠折叠）。
        self.assertEqual(second["api_key_encrypted"], "cipher-b")
        self.assertEqual(len(self.store.list_llm_endpoint_credentials()), 1)
        self.assertIsNotNone(self.store.get_llm_endpoint_credential(" https://api.qnaigc.com/v1 "))


if __name__ == "__main__":
    unittest.main()
