from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.app import vision_capability as caps
from backend.app.llm_client import LlmError
from backend.app.llm_provider import LlmProviderService
from backend.app.vlm_provider import VlmProviderService
from backend.app.storage import JobStore
from cryptography.fernet import Fernet
from backend.app.vision_runtime import (
    VISION_FAILURE_WARN_AND_TEXT, complete_authoring, endpoint_from_row,
    overlay_vlm_credentials, resolve_analysis_endpoint, resolve_authoring_endpoint,
)


def verified_row(model="deepseek-v4.1-flash", capability="supported", **overrides):
    row = {"enabled": True, "profile_id": "custom", "base_url": "https://llm.example/v1",
           "model": model, "api_key": "test-key", **overrides}
    return {**row, **caps.probe_fields(row, caps.VisionProbeResult(capability, "mock evidence"))}


class VisionCapabilityTests(unittest.TestCase):
    def setUp(self):
        caps._CACHE.clear()
        self.addCleanup(caps._CACHE.clear)

    def test_verified_unknown_name_is_supported(self):
        self.assertTrue(caps.row_supports_vision(verified_row()))

    def test_unsupported_name_guess_cannot_override_evidence(self):
        self.assertFalse(caps.row_supports_vision(verified_row("gpt-5.6-sol", "unsupported")))

    def test_legacy_guess_is_only_an_unverified_hint(self):
        row = {"model": "gpt-5.6-sol", **caps.vision_capability_fields_for_backfill("gpt-5.6-sol")}
        self.assertEqual("legacy_name_guess", row["vision_capability_source"])
        self.assertEqual("unknown", caps.row_vision_capability(row))
        row["vision_capability_checked_at"] = datetime.now(timezone.utc).isoformat()
        row["vision_capability_fingerprint"] = caps.row_fingerprint(row)
        self.assertFalse(caps.row_supports_vision(row))

    def test_connection_identity_changes_invalidate_evidence(self):
        row = verified_row()
        for field in ("model", "base_url", "api_key", "profile_id"):
            with self.subTest(field=field):
                self.assertEqual("unknown", caps.row_vision_capability({**row, field: "changed"}))

    def test_expired_evidence_is_unknown(self):
        row = verified_row()
        caps._CACHE.clear()
        row["vision_capability_checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.assertEqual("unknown", caps.row_vision_capability(row))

    def test_update_invalidates_saved_capability(self):
        row = verified_row()
        for key in ("model", "base_url", "api_key_encrypted", "profile_id", "use_llm_credentials"):
            updates = {key: "changed"}
            caps.invalidate_changed_capability(row, updates)
            self.assertEqual("unknown", updates["vision_capability"])
            self.assertIsNone(updates["vision_capability_fingerprint"])

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_semantic_probe_sends_distinct_images(self, client):
        client.return_value.chat_completion.side_effect = ["red", "blue"]
        result = caps.probe_vision_capability(base_url="https://example/v1", api_key="secret", model="alias")
        self.assertEqual("supported", result.capability)
        calls = client.return_value.chat_completion.call_args_list
        self.assertEqual(2, len(calls))
        self.assertNotEqual(calls[0].args[0][1]["content"][1], calls[1].args[0][1]["content"][1])
        self.assertLessEqual(calls[1].kwargs["timeout"], caps.VISION_PROBE_TIMEOUT)

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_model_ignoring_images_does_not_pass(self, client):
        client.return_value.chat_completion.return_value = "red"
        result = caps.probe_vision_capability(base_url="https://example/v1", api_key="secret", model="alias")
        self.assertEqual("unsupported", result.capability)

    @patch("backend.app.vision_capability.OpenAICompatibleClient")
    def test_probe_failure_redacts_credentials(self, client):
        client.return_value.chat_completion.side_effect = RuntimeError("Authorization: Bearer topsecret api_key=topsecret")
        result = caps.probe_vision_capability(base_url="https://example/v1", api_key="topsecret", model="alias")
        self.assertEqual("unsupported", result.capability)
        self.assertNotIn("topsecret", result.message)

    @patch("backend.app.vision_capability.probe_vision_capability")
    def test_unknown_probes_once_then_reuses_cache(self, probe):
        probe.return_value = caps.VisionProbeResult("supported", "ok")
        row = {"base_url": "https://example/v1", "model": "alias", "api_key": "secret"}
        self.assertTrue(caps.row_supports_vision(caps.ensure_vision_capability(row, "secret")))
        caps.ensure_vision_capability(row, "secret")
        probe.assert_called_once()

    @patch("backend.app.vision_capability.probe_vision_capability")
    def test_authoring_does_not_probe_unused_vlm(self, probe):
        endpoint = resolve_authoring_endpoint(verified_row(), {"enabled": True, "base_url": "https://other/v1", "model": "alias", "api_key": "key"}, probe_unknown=True)
        self.assertEqual("llm", endpoint.source)
        probe.assert_not_called()

    def test_analysis_prefers_verified_vlm(self):
        endpoint = resolve_analysis_endpoint(verified_row(), verified_row("vision", base_url="https://vlm/v1"))
        self.assertEqual("vlm", endpoint.source)

    def test_reused_connection_cannot_reuse_other_provider_evidence(self):
        vlm = verified_row("glm-4v-flash", use_llm_credentials=True)
        effective = overlay_vlm_credentials(vlm, {"base_url": "https://different/v1", "api_key": "different-key"})
        self.assertIsNone(endpoint_from_row("vlm", effective, None, require_vision=True))

    @patch("backend.app.vision_runtime.chat_on_endpoint")
    def test_default_block_does_not_retry_without_images(self, chat):
        chat.side_effect = LlmError("vision rejected")
        with self.assertRaisesRegex(LlmError, "vision rejected"):
            complete_authoring(verified_row(), {}, None, "sys", "user", ["https://image/a.png"])
        chat.assert_called_once()

    @patch("backend.app.vision_runtime.chat_on_endpoint")
    def test_block_without_supported_endpoint_never_calls_writer(self, chat):
        with self.assertRaisesRegex(LlmError, "没有已验证"):
            complete_authoring(verified_row(capability="unsupported"), {}, None, "sys", "user", ["https://image/a.png"])
        chat.assert_not_called()

    @patch("backend.app.vision_runtime.chat_on_endpoint")
    def test_explicit_fallback_records_actual_text_writer(self, chat):
        chat.side_effect = [LlmError("vision rejected"), "draft"]
        text, meta = complete_authoring(verified_row("writer", "unsupported"), verified_row("viewer"), None, "sys", "user", ["https://image/a.png"], on_failure=VISION_FAILURE_WARN_AND_TEXT)
        self.assertEqual("draft", text)
        data = meta.as_dict()
        self.assertEqual("writer", data["actual_model"])
        self.assertEqual("writer", data["requested_model"])
        self.assertEqual("viewer", data["fallback"])
        self.assertEqual("failed_text_fallback", data["status"])
        self.assertFalse(data["attach_images"])
        self.assertTrue(data["warning"])

    @patch("backend.app.vision_capability.probe_vision_capability")
    @patch("backend.app.vision_runtime.chat_on_endpoint", return_value="draft")
    def test_text_only_never_probes(self, chat, probe):
        complete_authoring(verified_row(capability="unsupported"), {}, None, "sys", "user", [])
        probe.assert_not_called()


class VisionCapabilityPersistenceTests(unittest.TestCase):
    def setUp(self):
        caps._CACHE.clear()
        self.addCleanup(caps._CACHE.clear)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "vision.db"
        self.store = JobStore(self.path)
        key = Fernet.generate_key().decode()
        self.llm = LlmProviderService(self.store, key)
        self.vlm = VlmProviderService(self.store, key)
        self.llm.update({"profile_id": "custom", "enabled": True, "base_url": "https://llm.example/v1",
                         "model": "deepseek-v4.1-flash", "api_key": "private-test-key"})
        for target, value in (("backend.app.llm_provider.OpenAICompatibleClient.test_connection", "connected"),
                              ("backend.app.llm_provider.probe_vision_capability", caps.VisionProbeResult("supported", "mock verified"))):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_saved_probe_survives_restart_and_profile_activation(self):
        result = self.llm.test()
        self.assertEqual("supported", result["vision_capability"])
        caps._CACHE.clear()
        restarted = JobStore(self.path)
        self.assertTrue(caps.row_supports_vision(restarted.get_llm_settings()))
        self.assertTrue(caps.row_supports_vision(restarted.get_llm_profile("custom")))
        self.assertNotIn("private-test-key", str(result))
        self.assertNotIn("vision_capability_fingerprint", result)

    def test_unsaved_model_probe_does_not_certify_saved_model(self):
        result = self.llm.test({"model": "unsaved-model"})
        self.assertEqual("supported", result["vision_capability"])
        self.assertIn("未保存", result["vision_capability_message"])
        self.assertEqual("unknown", caps.row_vision_capability(self.store.get_llm_settings()))

    def test_unsaved_key_probe_does_not_certify_saved_key(self):
        self.llm.test({"api_key": "other-private-key"})
        self.assertEqual("unknown", caps.row_vision_capability(self.store.get_llm_settings()))

    def test_probe_before_save_persists_exact_model_evidence_without_reprobe(self):
        result = self.llm.test({"model": "kimi-k3"})
        self.assertFalse(self.llm.public_config()["supports_vision"])
        with patch("backend.app.vision_capability.probe_vision_capability") as probe:
            saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                     "base_url": "https://llm.example/v1", "model": "kimi-k3"})
        probe.assert_not_called()
        self.assertTrue(saved["supports_vision"])
        self.assertEqual(result["vision_capability_checked_at"], saved["vision_capability_checked_at"])
        self.assertNotIn("未保存", saved["vision_capability_message"])
        caps._CACHE.clear()
        self.assertTrue(caps.row_supports_vision(JobStore(self.path).get_llm_settings()))

    def test_tested_key_evidence_survives_encryption_on_save(self):
        self.llm.test({"model": "kimi-k3", "api_key": "new-private-key"})
        saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                 "base_url": "https://llm.example/v1", "model": "kimi-k3",
                                 "api_key": "new-private-key"})
        caps._CACHE.clear()
        self.assertTrue(self.llm.public_config()["supports_vision"])
        self.assertNotIn("new-private-key", str(saved))

    def test_save_different_connection_cannot_adopt_probe(self):
        for change in ({"model": "other-model"}, {"base_url": "https://other.example/v1"},
                       {"api_key": "different-key"}, {"profile_id": "modelscope"}):
            with self.subTest(change=next(iter(change))):
                self.llm.test({"profile_id": "custom", "model": "kimi-k3", "api_key": "tested-key"})
                saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                         "base_url": "https://llm.example/v1", "model": "kimi-k3",
                                         "api_key": "tested-key", **change})
                self.assertFalse(saved["supports_vision"])

    def test_expired_preview_cannot_become_fresh_by_saving(self):
        self.llm.test({"model": "expired-model"})
        for fields in caps._CACHE.values():
            fields["vision_capability_checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                 "base_url": "https://llm.example/v1", "model": "expired-model"})
        self.assertFalse(saved["supports_vision"])

    def test_resaving_same_plaintext_key_preserves_saved_probe_after_cache_clear(self):
        result = self.llm.test()
        caps._CACHE.clear()
        saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                 "base_url": "https://llm.example/v1", "model": "deepseek-v4.1-flash",
                                 "api_key": "private-test-key"})
        caps._CACHE.clear()
        self.assertTrue(self.llm.public_config()["supports_vision"])
        self.assertEqual(result["vision_capability_checked_at"], saved["vision_capability_checked_at"])

    def test_negative_probe_is_preserved_without_claiming_vision(self):
        with patch("backend.app.llm_provider.probe_vision_capability", return_value=caps.VisionProbeResult("unsupported", "图片被明确拒绝")):
            self.llm.test({"model": "text-only"})
        saved = self.llm.update({"profile_id": "custom", "enabled": True,
                                 "base_url": "https://llm.example/v1", "model": "text-only"})
        self.assertEqual("unsupported", saved["vision_capability"])
        self.assertFalse(saved["supports_vision"])

    def test_independent_vlm_test_before_save_persists_probe(self):
        with patch("backend.app.vlm_provider.OpenAICompatibleClient.test_connection", return_value="connected"), \
             patch("backend.app.vlm_provider.probe_vision_capability", return_value=caps.VisionProbeResult("supported", "双色图通过")):
            result = self.vlm.test({"profile_id": "custom", "use_llm_credentials": False,
                                    "base_url": "https://vlm.example/v1", "model": "kimi-k3", "api_key": "vlm-test-key"})
        saved = self.vlm.update({"profile_id": "custom", "use_llm_credentials": False, "enabled": True,
                                 "base_url": "https://vlm.example/v1", "model": "kimi-k3", "api_key": "vlm-test-key"})
        caps._CACHE.clear()
        self.assertTrue(self.vlm.public_config()["supports_vision"])
        self.assertEqual(result["vision_capability_checked_at"], saved["vision_capability_checked_at"])

    def test_model_edit_invalidates_both_profile_and_active_row(self):
        self.llm.test()
        self.store.update_llm_profile("custom", {"model": "new-model"}, activate=True)
        for row in (self.store.get_llm_profile("custom"), self.store.get_llm_settings()):
            self.assertEqual("unknown", caps.row_vision_capability(row))
            self.assertIsNone(row["vision_capability_checked_at"])

    def test_concurrent_edit_wins_over_test_result(self):
        def changed(**kwargs):
            self.store.update_llm_profile("custom", {"model": "new-model"}, activate=True)
            return caps.VisionProbeResult("supported", "ok")
        with patch("backend.app.llm_provider.probe_vision_capability", side_effect=changed):
            self.llm.test()
        row = self.store.get_llm_settings()
        self.assertEqual("new-model", row["model"])
        self.assertEqual("unknown", caps.row_vision_capability(row))

    def test_reuse_rejects_unverified_llm_without_saving(self):
        before = self.store.get_vlm_settings()
        with patch("backend.app.vision_capability.probe_vision_capability", return_value=caps.VisionProbeResult("unsupported", "Model not exist")):
            with self.assertRaisesRegex(ValueError, "复用大模型连接尚未通过视觉验证"):
                self.vlm.update({"enabled": True, "profile_id": "custom", "use_llm_credentials": True,
                                 "base_url": "https://old.example/v1", "model": "glm-4v-flash"})
        self.assertEqual(before, self.store.get_vlm_settings())

    def test_reuse_probes_llm_model_not_stale_vlm_model(self):
        with patch("backend.app.vision_capability.probe_vision_capability", return_value=caps.VisionProbeResult("supported", "ok")) as probe:
            result = self.vlm.update({"enabled": True, "profile_id": "custom", "use_llm_credentials": True,
                                      "base_url": "https://old.example/v1", "model": "other-verified-model"})
        probe.assert_called_once()
        self.assertEqual("https://llm.example/v1", probe.call_args.kwargs["base_url"])
        self.assertEqual("deepseek-v4.1-flash", probe.call_args.kwargs["model"])
        self.assertTrue(result["supports_vision"])
        self.store.update_llm_settings({"base_url": "https://changed.example/v1"})
        self.assertFalse(self.vlm.public_config()["supports_vision"])

    def test_reuse_shares_verified_llm_without_reprobe_and_preserves_independent_connection(self):
        self.vlm.update({"enabled": True, "profile_id": "zhipu", "use_llm_credentials": False,
                         "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4v-flash",
                         "api_key": "independent-private-key"})
        independent = self.store.get_vlm_settings()
        llm = self.llm.test()
        caps._CACHE.clear()
        with patch("backend.app.vision_capability.probe_vision_capability") as probe:
            public = self.vlm.update({"enabled": True, "use_llm_credentials": True,
                                      "base_url": "https://stale.example/v1", "model": "old-model",
                                      "api_key": "stale-unsaved-key"})
        probe.assert_not_called()
        self.assertEqual("deepseek-v4.1-flash", public["model"])
        self.assertEqual("llm", public["connection_source"])
        self.assertEqual(independent["model"], public["independent_model"])
        self.assertEqual(independent["base_url"], public["independent_base_url"])
        self.assertTrue(public["supports_vision"])
        for name in ("vision_capability", "vision_capability_source", "vision_capability_checked_at",
                     "vision_capability_message", "last_test_at"):
            self.assertEqual(llm[name], public[name])
        raw = self.store.get_vlm_settings()
        for name in ("profile_id", "base_url", "model", "api_key_encrypted"):
            self.assertEqual(independent[name], raw[name])
        restored = self.vlm.update({"enabled": True, "use_llm_credentials": False,
                                    "profile_id": independent["profile_id"],
                                    "base_url": independent["base_url"], "model": independent["model"]})
        self.assertEqual("glm-4v-flash", restored["model"])
        self.assertEqual("vlm", restored["connection_source"])
        self.assertEqual("independent-private-key", self.vlm.api_key())

    def test_historical_reuse_flag_immediately_follows_llm(self):
        self.llm.test()
        self.store.update_vlm_settings({"enabled": True, "use_llm_credentials": True, "model": "glm-4v-flash"})
        caps._CACHE.clear()
        with patch("backend.app.vision_capability.probe_vision_capability") as probe:
            public = self.vlm.public_config()
        probe.assert_not_called()
        self.assertEqual("deepseek-v4.1-flash", public["model"])
        self.assertTrue(public["supports_vision"])

    def test_reuse_follows_llm_changes_and_invalidates_old_evidence(self):
        self.store.update_vlm_settings({"enabled": True, "use_llm_credentials": True})
        changes = ({"model": "new-writer"}, {"base_url": "https://new.example/v1"},
                   {"api_key_encrypted": self.llm.credentials.encrypt("new-private-key")})
        for change in changes:
            with self.subTest(field=next(iter(change))):
                self.llm.test()
                self.assertTrue(self.vlm.public_config()["supports_vision"])
                self.store.update_llm_profile("custom", change, activate=True)
                caps._CACHE.clear()
                public = self.vlm.public_config()
                self.assertFalse(public["supports_vision"])
                self.assertEqual("unknown", public["vision_capability"])
                self.assertEqual(self.store.get_llm_settings()["model"], public["model"])
                self.assertEqual(self.store.get_llm_settings()["base_url"], public["base_url"])

    def test_reuse_probe_updates_llm_evidence_not_independent_glm(self):
        self.store.update_vlm_settings({"enabled": True, "use_llm_credentials": True, "model": "glm-4v-flash"})
        with patch("backend.app.llm_provider.probe_vision_capability", return_value=caps.VisionProbeResult("supported", "new verification")) as probe:
            public = self.vlm.test({"use_llm_credentials": True, "model": "glm-4v-flash", "api_key": "ignore-this-key"})
        self.assertEqual("deepseek-v4.1-flash", probe.call_args.kwargs["model"])
        self.assertEqual("private-test-key", probe.call_args.kwargs["api_key"])
        caps._CACHE.clear()
        self.assertTrue(caps.row_supports_vision(self.store.get_llm_settings()))
        self.assertFalse(caps.row_supports_vision(self.store.get_vlm_settings()))
        self.assertEqual("new verification", public["vision_capability_message"])
        self.assertEqual("deepseek-v4.1-flash", public["model"])

    def test_reuse_save_persists_new_evidence_on_llm(self):
        with patch("backend.app.vision_capability.probe_vision_capability", return_value=caps.VisionProbeResult("supported", "verified during save")):
            self.vlm.update({"enabled": True, "use_llm_credentials": True})
        caps._CACHE.clear()
        self.assertTrue(caps.row_supports_vision(self.store.get_llm_settings()))
        self.assertTrue(self.vlm.public_config()["supports_vision"])

    def test_reuse_save_rejects_concurrent_llm_edit(self):
        def change_connection(**kwargs):
            self.store.update_llm_profile("custom", {"model": "changed-during-probe"}, activate=True)
            return caps.VisionProbeResult("supported", "old endpoint verified")
        before = self.store.get_vlm_settings()
        with patch("backend.app.vision_capability.probe_vision_capability", side_effect=change_connection):
            with self.assertRaisesRegex(ValueError, "验证期间变更"):
                self.vlm.update({"enabled": True, "use_llm_credentials": True})
        self.assertEqual(before, self.store.get_vlm_settings())
        self.assertFalse(caps.row_supports_vision(self.store.get_llm_settings()))

    def test_reuse_without_llm_model_never_uses_glm(self):
        self.store.update_llm_settings({"model": ""})
        with patch("backend.app.vision_capability.probe_vision_capability") as probe:
            with self.assertRaisesRegex(ValueError, "缺少大模型地址、模型或密钥"):
                self.vlm.update({"enabled": True, "use_llm_credentials": True, "model": "glm-4v-flash"})
        probe.assert_not_called()

    def test_legacy_migration_is_idempotent_and_never_authorizes(self):
        with self.store.connection() as db:
            db.execute("DELETE FROM schema_migrations WHERE name = ?", (self.store.VISION_CAPABILITY_MIGRATION,))
            db.execute("UPDATE llm_provider_settings SET model = ?, vision_capability = 'unknown', vision_capability_source = NULL", ("gpt-5.6-sol",))
        restarted = JobStore(self.path)
        row = restarted.get_llm_settings()
        self.assertEqual("legacy_name_guess", row["vision_capability_source"])
        self.assertFalse(caps.row_supports_vision(row))
        self.assertEqual(row, JobStore(self.path).get_llm_settings())
