from __future__ import annotations

import unittest
from unittest.mock import patch

from server.services.project_detail_service import (
    ProjectDetailService,
    has_primary_asset_image,
    index_episode_required_assets,
    is_protagonist_asset,
    primary_image_enqueue_payload,
)


def _asset(asset_id: str, kind: str, name: str, **extra) -> dict:
    return {"id": asset_id, "kind": kind, "name": name, "role": extra.pop("role", ""), "image_url": extra.pop("image_url", ""), "extra": extra}


class EpisodeRequiredAssetIndexTests(unittest.TestCase):
    def test_indexes_protagonist_scene_and_prop_and_skips_supporting_cast(self):
        assets = [
            _asset("c-lead", "character", "牛大", role_position="主角"),
            _asset("c-side", "character", "掌柜", role_position="配角"),
            _asset("s-shop", "scene", "东市铺面"),
            _asset("p-fan", "prop", "风扇"),
        ]
        beats = [{
            "character_ids": ["c-lead", "c-side"],
            "characters": ["牛大", "掌柜"],
            "speaker": "掌柜",
            "scene_id": "s-shop",
            "scene": "东市铺面",
            "prop_ids": ["p-fan"],
            "props": ["风扇"],
        }]
        indexed = index_episode_required_assets(beats, assets)
        self.assertEqual(["c-lead"], [item["id"] for item in indexed["characters"]])
        self.assertEqual(["s-shop"], [item["id"] for item in indexed["scenes"]])
        self.assertEqual(["p-fan"], [item["id"] for item in indexed["props"]])

    def test_resolves_assets_by_name_when_ids_are_missing(self):
        assets = [
            _asset("c-lead", "character", "淼淼", role="女主"),
            _asset("s-tea", "scene", "茶摊"),
            _asset("p-bowl", "prop", "陶碗"),
        ]
        beats = [{
            "characters": ["淼淼"],
            "scene": "茶摊",
            "props": ["陶碗"],
        }]
        indexed = index_episode_required_assets(beats, assets)
        self.assertEqual(["c-lead"], [item["id"] for item in indexed["characters"]])
        self.assertEqual(["s-tea"], [item["id"] for item in indexed["scenes"]])
        self.assertEqual(["p-bowl"], [item["id"] for item in indexed["props"]])

    def test_primary_image_and_payload(self):
        lead = _asset("c-lead", "character", "牛大", role_position="主角", avatar_url="http://img/a.png")
        scene = _asset("s-shop", "scene", "铺面")
        self.assertTrue(is_protagonist_asset(lead))
        self.assertTrue(has_primary_asset_image(lead))
        self.assertFalse(has_primary_asset_image(scene))
        self.assertEqual("scene_master", primary_image_enqueue_payload(scene)["target_type"])
        self.assertEqual("avatar", primary_image_enqueue_payload(lead)["target_type"])


class EpisodeRequiredAssetEnqueueTests(unittest.TestCase):
    @patch.object(ProjectDetailService, "generate_asset_image")
    @patch.object(ProjectDetailService, "list_assets")
    @patch.object(ProjectDetailService, "get_episode_detail")
    @patch("server.services.storyboard_image_service.StoryboardImageService.kick")
    @patch("server.services.storyboard_image_service.StoryboardImageService._limit", return_value=5)
    def test_enqueues_only_missing_primary_images(self, _limit, kick, get_detail, list_assets, generate):
        get_detail.return_value = {
            "beats": [{
                "character_ids": ["c-lead", "c-side"],
                "scene_id": "s-shop",
                "prop_ids": ["p-fan", "p-done"],
            }],
        }
        list_assets.return_value = [
            _asset("c-lead", "character", "牛大", role_position="主角"),
            _asset("c-side", "character", "掌柜", role_position="配角"),
            _asset("s-shop", "scene", "铺面"),
            _asset("p-fan", "prop", "风扇"),
            _asset("p-done", "prop", "算盘", reference_url="http://img/p.png"),
        ]
        generate.side_effect = lambda project_id, asset_id, payload, enqueue_only=False: {
            "job_id": f"job-{asset_id}",
            "asset_id": asset_id,
            "duplicate": False,
        }
        result = ProjectDetailService.enqueue_episode_required_assets("proj-1", "ep-1", {"model": "gpt-image-2"})
        submitted = {call.args[1] for call in generate.call_args_list}
        self.assertEqual({"c-lead", "s-shop", "p-fan"}, submitted)
        self.assertEqual(3, result["queued"])
        self.assertTrue(any(item["reason"] == "已有主图" for item in result["skipped"]))
        kick.assert_called()


if __name__ == "__main__":
    unittest.main()
