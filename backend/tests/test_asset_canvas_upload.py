from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import patch
from PIL import Image

from backend.app.media_studio.services.project_detail_service import ProjectDetailService
from backend.app.media_studio.services.job_payload import serialize_job_row


def row(kind="scene", extra=None, image_url="old"):
    return {"id": "asset", "project_id": "project", "kind": kind, "name": "测试资产", "image_url": image_url, "extra_json": json.dumps(extra or {}, ensure_ascii=False)}


def png(format="PNG"):
    output = BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format)
    return output.getvalue()


class AssetCanvasImageUploadTests(unittest.TestCase):
    def test_running_look_job_keeps_its_canvas_slot_in_the_slim_list(self):
        job = serialize_job_row({"id": "job", "job_type": "image_generation", "status": "running", "payload_json": json.dumps({"asset_id": "character", "target_type": "identity", "identity_id": "look-two", "draft": "large private draft"})}, slim=True)
        self.assertEqual("look-two", job["payload"]["identity_id"])
        self.assertEqual("character", job["payload"]["asset_id"])
        self.assertEqual("identity", job["payload"]["target_type"])
        self.assertNotIn("draft", job["payload"])

    @patch("backend.app.media_studio.services.project_detail_service.QiniuService.store_bytes")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_kind_and_identity_are_checked_before_storage(self, query, store):
        query.return_value = row("scene")
        with self.assertRaisesRegex(ValueError, "类型不匹配"):
            ProjectDetailService.upload_asset_image("project", "asset", target_type="identity", identity_id="look", filename="a.png", content=png())
        query.return_value = row("character", {"identities": [{"id": "first"}]})
        with self.assertRaisesRegex(ValueError, "找不到该造型"):
            ProjectDetailService.upload_asset_image("project", "asset", target_type="identity", identity_id="missing", filename="a.png", content=png())
        store.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.QiniuService.store_bytes")
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_invalid_or_disguised_images_never_reach_storage(self, query, store):
        query.return_value = row()
        for content in (b"not an image", png("BMP")):
            with self.subTest(content=content[:10]):
                with self.assertRaisesRegex(ValueError, "图片无法读取"):
                    ProjectDetailService.upload_asset_image("project", "asset", target_type="scene_master", filename="fake.png", content=content)
        store.assert_not_called()

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.QiniuService.store_bytes", return_value=("object-key", "https://cdn/new.png"))
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_secondary_scene_image_preserves_master_and_latest_layout(self, query, store, execute):
        latest = {"master_url": "https://cdn/master.png", "source_references": [{"id": "r", "url": "https://cdn/ref.png"}], "creation_canvas": {"version": 1, "positions": {"group": {"x": 100, "y": 200}}}}
        query.side_effect = [row(), row(extra=latest), row(extra=latest)]
        ProjectDetailService.upload_asset_image("project", "asset", target_type="scene_reverse", filename="a.png", content=png())
        args = execute.call_args.args[1]
        extra = json.loads(args[1])
        self.assertEqual("old", args[0])
        self.assertEqual("https://cdn/new.png", extra["reverse_url"])
        self.assertEqual(latest["creation_canvas"], extra["creation_canvas"])
        self.assertEqual("https://cdn/ref.png", extra["source_references"][0]["url"])
        self.assertEqual("r", extra["source_references"][0]["id"])
        self.assertEqual("https://cdn/master.png", extra["master_url"])
        self.assertEqual(("asset", "project"), args[-2:])

    @patch("backend.app.media_studio.services.project_detail_service.execute_sql")
    @patch("backend.app.media_studio.services.project_detail_service.QiniuService.store_bytes", return_value=("object-key", "https://cdn/new.png"))
    @patch("backend.app.media_studio.services.project_detail_service.query_one")
    def test_identity_upload_updates_only_the_requested_look(self, query, store, execute):
        extra = {"identities": [{"id": "first", "name": "初始造型", "image_url": "first.png"}, {"id": "second", "name": "工作装", "description": "新修改", "image_url": "second.png"}], "voice": {"preset_id": "voice"}}
        query.return_value = row("character", extra)
        ProjectDetailService.upload_asset_image("project", "asset", target_type="identity", identity_id="second", filename="a.png", content=png())
        args = execute.call_args.args[1]
        saved = json.loads(args[1])
        self.assertEqual("old", args[0])
        self.assertEqual("first.png", saved["identities"][0]["image_url"])
        self.assertEqual("https://cdn/new.png", saved["identities"][1]["image_url"])
        self.assertEqual("新修改", saved["identities"][1]["description"])
        self.assertEqual("voice", saved["voice"]["preset_id"])

    @patch("backend.app.media_studio.services.project_detail_service.QiniuService.store_bytes")
    @patch("backend.app.media_studio.services.project_detail_service.query_one", return_value=row())
    @patch("backend.app.media_studio.services.project_detail_service.MAX_SOURCE_REFERENCE_BYTES", 3)
    def test_size_limit_is_checked_before_decoding_or_storage(self, query, store):
        with self.assertRaisesRegex(ValueError, "10 MB"):
            ProjectDetailService.upload_asset_image("project", "asset", target_type="scene_master", filename="a.png", content=png())
        store.assert_not_called()

    def test_generation_retains_edits_saved_while_the_provider_was_running(self):
        prefix = "backend.app.media_studio.services.project_detail_service."
        original = row(extra={"environment_prompt": "旧提示词"})
        latest = row(extra={"environment_prompt": "新的提示词", "creation_canvas": {"version": 1, "positions": {"group": {"x": 400, "y": 300}}}})
        with patch(prefix + "query_one", side_effect=[original, {"provider_model": "test", "display_name": "Test", "profile": "gpt_image_2"}, latest, latest]), patch(prefix + "execute_sql") as execute, patch(prefix + "grs_row", return_value={"base_url": "https://provider.test", "api_key_encrypted": "fixture"}), patch(prefix + "credential_manager") as credentials, patch(prefix + "GrsClient") as client, patch(prefix + "QiniuService.store_bytes", return_value=("object", "https://cdn/new.png")):
            credentials.return_value.decrypt.return_value = "test-key"
            client.return_value.generate_sync.return_value = "https://provider.test/image.png"
            client.return_value.download_image.return_value = ("image.png", b"image")
            ProjectDetailService.generate_asset_image("project", "asset", {"target_type": "scene_master", "prompt": "旧提示词"})
            write = next(call for call in execute.call_args_list if "UPDATE ai_project_assets" in call.args[0])
            saved = json.loads(write.args[1][1])
            self.assertEqual("新的提示词", saved["environment_prompt"])
            self.assertEqual({"x": 400, "y": 300}, saved["creation_canvas"]["positions"]["group"])
            self.assertEqual("https://cdn/new.png", saved["master_url"])


class AssetGenerateModelAndAspectTests(unittest.TestCase):
    def _run_generate(self, payload, asset_row, model_row):
        prefix = "backend.app.media_studio.services.project_detail_service."
        with patch(prefix + "query_one", side_effect=[asset_row, model_row, asset_row, asset_row]) as query, patch(prefix + "execute_sql") as execute, patch(prefix + "grs_row", return_value={"base_url": "https://provider.test", "api_key_encrypted": "fixture"}), patch(prefix + "credential_manager") as credentials, patch(prefix + "GrsClient") as client, patch(prefix + "QiniuService.store_bytes", return_value=("object", "https://cdn/new.png")):
            credentials.return_value.decrypt.return_value = "test-key"
            client.return_value.generate_sync.return_value = "https://provider.test/image.png"
            client.return_value.download_image.return_value = ("image.png", b"image")
            ProjectDetailService.generate_asset_image("project", "asset", payload)
        return query, execute, client

    def _job_payload(self, execute):
        insert = next(call for call in execute.call_args_list if "INSERT INTO ai_project_jobs" in call.args[0])
        return json.loads(insert.args[1][3])

    def test_slot_model_is_resolved_by_workflow_id_from_the_catalog(self):
        model_row = {"provider_model": "gpt-image-2.6", "display_name": "GPT Image 2.6", "profile": "gpt_image_2_5"}
        query, execute, client = self._run_generate({"target_type": "scene_master", "prompt": "雨夜巷口", "model": "grs-gpt-image-2.6"}, row(), model_row)
        self.assertIn("grs-gpt-image-2.6", query.call_args_list[1].args[1])
        client.return_value.generate_sync.assert_called_once()
        self.assertEqual("gpt-image-2.6", client.return_value.generate_sync.call_args.kwargs["model"])
        payload = self._job_payload(execute)
        self.assertEqual("gpt-image-2.6", payload["model"])
        self.assertEqual("gpt-image-2.6", payload["request_body"]["model"])

    def test_identity_aspect_follows_the_canvas_request(self):
        asset = row("character", {"identities": [{"id": "look-1", "name": "日常", "description": "白色连衣裙"}]})
        model_row = {"provider_model": "gpt-image-2.5", "display_name": "GPT Image 2.5", "profile": "gpt_image_2_5"}
        _, execute, client = self._run_generate({"target_type": "identity", "identity_id": "look-1", "aspect_ratio": "9:16", "prompt": "白色连衣裙"}, asset, model_row)
        payload = self._job_payload(execute)
        self.assertEqual("9:16", payload["aspect_ratio"])
        self.assertEqual((1152, 2048), (payload["width"], payload["height"]))
        self.assertEqual("1152x2048", payload["request_body"]["aspectRatio"])
        self.assertIn("9:16", payload["clean_prompt"])

    def test_identity_aspect_falls_back_to_16_9_when_unsupported(self):
        asset = row("character", {"identities": [{"id": "look-1", "name": "日常", "description": "白色连衣裙"}]})
        model_row = {"provider_model": "gpt-image-2.5", "display_name": "GPT Image 2.5", "profile": "gpt_image_2_5"}
        _, execute, client = self._run_generate({"target_type": "identity", "identity_id": "look-1", "aspect_ratio": "1:8", "prompt": "白色连衣裙"}, asset, model_row)
        payload = self._job_payload(execute)
        self.assertEqual("16:9", payload["aspect_ratio"])
        self.assertEqual((2048, 1152), (payload["width"], payload["height"]))
        self.assertNotIn("1:8", payload["clean_prompt"])
