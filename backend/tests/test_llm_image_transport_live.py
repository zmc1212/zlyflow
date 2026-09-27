"""Opt-in, billed live check using an existing workshop job's exact references.

Set ZLY_LLM_IMAGE_LIVE_JOB_ID explicitly. Default test discovery never contacts
the provider. This reads the task/configuration; it cannot adopt or edit a draft.
"""
import json
import os
import unittest


@unittest.skipUnless(os.getenv("ZLY_LLM_IMAGE_LIVE_JOB_ID"), "live provider check is opt-in")
class LiveImageTransportTests(unittest.TestCase):
    def test_saved_group_references_reach_the_selected_aliyun_model(self):
        from pymysql.cursors import DictCursor
        from backend.app.config import settings
        from backend.app.db import mysql_settings_from_env_or_docs, _pymysql_connect
        from backend.app.grs_provider import CredentialManager
        from backend.app.llm_client import OpenAICompatibleClient
        from backend.app.llm_image_transport import uses_inline_images, MAX_ENCODED_BYTES

        cfg = mysql_settings_from_env_or_docs()
        connection = _pymysql_connect(cfg, database=cfg["database"], autocommit=False, cursorclass=DictCursor)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload_json FROM ai_project_jobs WHERE id=%s AND job_type='workshop_prompt'",
                               (os.environ["ZLY_LLM_IMAGE_LIVE_JOB_ID"],))
                job = cursor.fetchone()
                self.assertIsNotNone(job)
                payload = json.loads(job["payload_json"])
                author = payload.get("writing_author") or payload.get("request", {}).get("writing_author") or {}
                if author.get("profile_id"):
                    cursor.execute("SELECT * FROM llm_provider_profiles WHERE profile_id=%s", (author["profile_id"],))
                else:
                    cursor.execute("SELECT * FROM llm_provider_settings WHERE id=1")
                row = cursor.fetchone()
                self.assertIsNotNone(row)
        finally:
            connection.rollback()
            connection.close()
        if author.get("base_url"):
            self.assertEqual(author["base_url"].rstrip("/"), row["base_url"].rstrip("/"))
        self.assertTrue(uses_inline_images(row["base_url"]))
        selected = set(payload["request"].get("beat_ids") or [])
        group = next(g for g in payload["base_plan"]["groups"] if not selected or selected.intersection(g["beat_ids"]))
        urls = [slot["image_url"] for slot in group["reference_slots"]]
        self.assertTrue(urls)
        model = author.get("model") or row["model"]
        key = CredentialManager(settings.credential_key).decrypt(row["api_key_encrypted"])
        meta = {}
        reply = OpenAICompatibleClient(row["base_url"], key).chat_completion(
            [{"role": "user", "content": [
                {"type": "text", "text": f"请按顺序分别描述这 {len(urls)} 张参考图的主要主体和衣着或物品特征，每张一句。不猜姓名，不写剧本。"},
                *[{"type": "image_url", "image_url": {"url": url}} for url in urls],
            ]}], model, max_tokens=512, temperature=0, timeout=90, stream=True, meta_out=meta)
        self.assertTrue(reply.strip())
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["requested_model"], model)
        self.assertEqual(meta["inlined_image_count"], len(urls))
        self.assertLessEqual(meta["image_payload_bytes"], MAX_ENCODED_BYTES)
        print("LIVE_IMAGE_RESULT " + json.dumps({
            "job_id": os.environ["ZLY_LLM_IMAGE_LIVE_JOB_ID"],
            "meta": {k: v for k, v in meta.items() if k != "base_url"},
            "reply": reply,
        }, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
