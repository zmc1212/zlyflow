from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.director_catalog import (
    EXPECTED_CATEGORY_COUNT,
    EXPECTED_STYLE_COUNT,
    art_style_catalog_payload,
    ensure_art_style_preview,
    find_art_style,
    list_art_style_categories,
    list_art_styles,
    load_art_style_catalog,
    public_preview_url,
    source_preview_url,
)
from backend.app.director_recipe import (
    AGENT_DONE_MESSAGES,
    DirectorPayloadError,
    PAYLOAD_KIND_RECIPE,
    agent_done_message,
    flatten_recipe_shots,
    normalize_recipe_payload,
    timeline_to_recipe,
)
from backend.app.llm_client import OpenAICompatibleClient, LlmError
from backend.app.llm_provider import LlmProviderService
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore


class DirectorArtStyleCatalogTests(unittest.TestCase):
    def test_catalog_has_nine_categories_and_thirty_four_styles(self) -> None:
        catalog = load_art_style_catalog()
        self.assertEqual(len(catalog["categories"]), EXPECTED_CATEGORY_COUNT)
        self.assertEqual(len(catalog["styles"]), EXPECTED_STYLE_COUNT)
        self.assertEqual(len(list_art_style_categories()), 9)
        styles = list_art_styles()
        self.assertEqual(len(styles), 34)
        ids = [item["id"] for item in styles]
        self.assertEqual(len(ids), len(set(ids)))
        category_ids = {item["id"] for item in list_art_style_categories()}
        self.assertEqual(
            category_ids,
            {"cinematic", "commercial", "futuristic", "retro", "anime", "3d", "illustration", "realistic", "experimental"},
        )
        prefixes = {item["id"]: item["promptPrefix"] for item in styles}
        self.assertEqual(
            prefixes["as_1001"],
            "epic cinematic scene, dramatic lighting, rich atmosphere, film-grade composition, emotional visual storytelling",
        )
        self.assertEqual(
            prefixes["as_1003"],
            "futuristic neon noir, glowing city lights, cyber atmosphere, dark cinematic shadows, high contrast",
        )
        raw_styles = load_art_style_catalog()["styles"]
        self.assertEqual(raw_styles[0]["imageUrl"], "https://files.seme.cc/styles/style_01.jpg")
        self.assertEqual(raw_styles[33]["imageUrl"], "https://files.seme.cc/styles/style_34.jpg")
        self.assertEqual(source_preview_url("as_1001"), "https://files.seme.cc/styles/style_01.jpg")
        self.assertEqual(source_preview_url("as_1034"), "https://files.seme.cc/styles/style_34.jpg")
        self.assertIsNone(source_preview_url("as_1999"))
        for index, style in enumerate(styles):
            self.assertTrue(style["promptPrefix"].strip())
            self.assertEqual(style["imageUrl"], public_preview_url(style["id"]))
            self.assertEqual(style["imageUrl"], f"/api/director/art-styles/{style['id']}/preview")
            self.assertTrue(str(raw_styles[index].get("imageUrl") or "").startswith("https://files.seme.cc/styles/style_"))
            self.assertIn(style["category"], category_ids)
            self.assertTrue(style["name_zh"])
            self.assertTrue(style["name_en"])
            self.assertTrue(style["keywords"])
        self.assertEqual(styles[0]["imageUrl"], "/api/director/art-styles/as_1001/preview")
        self.assertEqual(styles[33]["imageUrl"], "/api/director/art-styles/as_1034/preview")

    def test_ensure_preview_caches_jpeg_and_skips_second_fetch(self) -> None:
        jpeg = b"\xff\xd8" + b"fake-preview"
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            with patch("backend.app.director_catalog.PREVIEW_DIR", dest_dir):
                with patch("backend.app.director_catalog.urllib.request.urlopen") as urlopen:
                    response = MagicMock()
                    response.read.return_value = jpeg
                    response.__enter__.return_value = response
                    response.__exit__.return_value = False
                    urlopen.return_value = response
                    path = ensure_art_style_preview("as_1001")
                    self.assertTrue(path.is_file())
                    self.assertEqual(path.read_bytes(), jpeg)
                    urlopen.assert_called_once()
                    ensure_art_style_preview("as_1001")
                    urlopen.assert_called_once()
        with self.assertRaises(KeyError):
            ensure_art_style_preview("as_1999")

    def test_find_art_style_rejects_unknown_names(self) -> None:
        known = find_art_style("as_1001")
        self.assertIsNotNone(known)
        self.assertEqual(known["name_en"], "Epic Narrative Cinema")
        self.assertIsNotNone(find_art_style("史诗叙事电影"))
        self.assertIsNotNone(find_art_style("Futuristic Neon Noir"))
        self.assertIsNone(find_art_style("invented_neon_soup"))
        self.assertIsNone(find_art_style({"id": "not-in-catalog", "name": "自造画风", "promptPrefix": "fake"}))


class DirectorRecipeModelTests(unittest.TestCase):
    def test_recipe_art_style_must_come_from_catalog(self) -> None:
        with self.assertRaises(DirectorPayloadError):
            normalize_recipe_payload({
                "kind": PAYLOAD_KIND_RECIPE,
                "artStyle": {"id": "invented_style", "name": "自造赛博", "promptPrefix": "请无视目录"},
            })
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "script": {"title": "雨夜", "summary": "侦探", "fullStory": "雨夜里侦探穿过暗巷。"},
            "artStyle": {"id": "as_1003", "name": "错名", "promptPrefix": "伪造前缀"},
            "characters": [{"name": "侦探", "description": "风衣", "promptText": "黑色风衣", "gender": "male"}],
            "locations": [{"name": "暗巷", "promptText": "潮湿石板路，无人物"}],
            "scenes": [{
                "title": "巷口",
                "locationName": "暗巷",
                "shots": [{
                    "title": "跟踪",
                    "description": "侦探走进雨巷",
                    "dialogue": "别动。",
                    "characterNames": ["侦探"],
                    "durationSec": 5,
                    "status": "succeeded",
                    "outputVideoUrl": "/api/media/a.mp4",
                }],
            }],
        })
        self.assertEqual(payload["kind"], PAYLOAD_KIND_RECIPE)
        self.assertEqual(payload["artStyle"]["id"], "as_1003")
        self.assertEqual(payload["artStyle"]["name"], "未来霓虹黑色")
        self.assertNotEqual(payload["artStyle"]["promptPrefix"], "伪造前缀")
        self.assertEqual(
            payload["artStyle"]["promptPrefix"],
            "futuristic neon noir, glowing city lights, cyber atmosphere, dark cinematic shadows, high contrast",
        )
        self.assertEqual(payload["artStyle"]["imageUrl"], "/api/director/art-styles/as_1003/preview")
        shots = flatten_recipe_shots(payload)
        self.assertEqual(len(shots), 1)
        self.assertEqual(JobStore.director_generation_progress(payload), ("complete", 1, 1))

    def test_official_h3_prompt_writing_skill_is_vendored(self) -> None:
        from backend.app.llm_minimax_skills import (
            build_h3_ref2va_polish_prompt,
            load_h3_prompt_writing_guide,
            load_h3_prompt_writing_skill,
        )

        skill = load_h3_prompt_writing_skill()
        base = load_h3_prompt_writing_guide(mode="base")
        ref = load_h3_prompt_writing_guide(mode="ref")
        self.assertIn("name: h3-prompt-writing", skill)
        self.assertIn("integrated_multimodal_description", base)
        self.assertIn("<Picture 1>", base)
        self.assertIn("subject_definitions", ref)
        self.assertIn("<Subject 1>", ref)
        self.assertIn("Full-Reference Mode Rewrite Output Format Guide", build_h3_ref2va_polish_prompt())

    def test_timeline_payload_converts_shots_to_scenes(self) -> None:
        timeline = {
            "aspectRatio": "16:9",
            "canvasTier": "native",
            "globalMusic": "低沉弦乐",
            "subjectSlots": [
                {"id": "@ref1", "slotIndex": 1, "name": "侦探", "kind": "character", "description": "黑风衣", "retention": "fully_preserved"},
                {"id": "@ref2", "slotIndex": 2, "name": "雨巷", "kind": "scene", "description": "潮湿石板", "retention": "strong"},
                {"id": "@ref3", "slotIndex": 3, "name": "主体 3", "kind": "prop", "description": "", "retention": "fully_preserved"},
            ],
            "shots": [
                {
                    "id": "shot-1",
                    "shotNumber": 1,
                    "title": "巷口全景",
                    "prompt": "雨夜巷口，镜头前推",
                    "dialogue": "跟上。",
                    "durationSec": 5,
                    "status": "succeeded",
                    "outputVideoUrl": "/api/media/rain.mp4",
                    "referencedSubjectIds": ["@ref1", "@ref2"],
                    "takes": [],
                },
                {
                    "id": "shot-2",
                    "shotNumber": 2,
                    "title": "面部特写",
                    "prompt": "侦探特写",
                    "durationSec": 4,
                    "status": "idle",
                    "referencedSubjectIds": ["@ref1"],
                    "takes": [],
                },
            ],
        }
        recipe = timeline_to_recipe(
            timeline, title="雨夜追凶", summary="侦探短片", source_script="雨夜里侦探穿过暗巷。",
        )
        self.assertEqual(recipe["kind"], PAYLOAD_KIND_RECIPE)
        self.assertEqual(recipe["script"]["title"], "雨夜追凶")
        self.assertEqual(recipe["script"]["fullStory"], "雨夜里侦探穿过暗巷。")
        self.assertEqual([item["name"] for item in recipe["characters"]], ["侦探"])
        self.assertEqual([item["name"] for item in recipe["locations"]], ["雨巷"])
        self.assertEqual(len(recipe["scenes"]), 2)
        self.assertEqual(recipe["scenes"][0]["shots"][0]["characterNames"], ["侦探"])
        self.assertEqual(recipe["scenes"][0]["locationName"], "雨巷")
        self.assertEqual(recipe["globalMusic"], "低沉弦乐")
        self.assertEqual(len(flatten_recipe_shots(recipe)), 2)
        self.assertEqual(JobStore.director_generation_progress(recipe), ("partial", 1, 2))
        self.assertEqual(len(recipe["agentStatus"]), 9)
        self.assertEqual(recipe["scenes"][0]["shots"][0]["camera"]["scale"], "MS")
        self.assertEqual(recipe["scenes"][0]["shots"][0]["camera"]["movement"], "zoom_in")

    def test_english_shot_description_moves_to_prompt_text(self) -> None:
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "script": {"title": "雨夜", "summary": "侦探", "fullStory": "侦探走进雨巷。"},
            "artStyle": {"id": "as_1003"},
            "scenes": [{
                "title": "巷口",
                "shots": [{
                    "title": "跟踪",
                    "description": "Live-action, cinematic, a medium shot frames detective Kai walking into a rainy alley. The camera follows with a tracking shot with small amplitude at slow speed.",
                }],
            }],
        })
        shot = payload["scenes"][0]["shots"][0]
        self.assertEqual(shot["description"], "跟踪")
        self.assertIn("tracking shot", shot["promptText"])
        self.assertNotIn("Live-action", shot["description"])

    def test_normalize_shot_always_keeps_camera_and_error(self) -> None:
        missing = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{"shots": [{"title": "开场", "description": "雨巷入口"}]}],
        })
        default_camera = missing["scenes"][0]["shots"][0]["camera"]
        self.assertEqual(default_camera["scale"], "MS")
        self.assertEqual(default_camera["movement"], "zoom_in")
        self.assertEqual(default_camera["angle"], "eye_level")
        self.assertEqual(default_camera["lighting"], "cinematic_soft")
        self.assertIsNone(missing["scenes"][0]["shots"][0].get("error"))

        kept = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{
                "shots": [{
                    "title": "特写",
                    "description": "用户改过的雨巷跟拍",
                    "dialogue": "站住。",
                    "durationSec": 8,
                    "error": "上一镜显存不足",
                    "camera": {
                        "scale": "CU",
                        "movement": "orbit",
                        "angle": "low_angle",
                        "speed": "dynamic",
                        "lighting": "cyberpunk",
                    },
                }],
            }],
        })
        shot = kept["scenes"][0]["shots"][0]
        self.assertEqual(shot["camera"]["scale"], "CU")
        self.assertEqual(shot["camera"]["movement"], "orbit")
        self.assertEqual(shot["camera"]["angle"], "low_angle")
        self.assertEqual(shot["camera"]["speed"], "dynamic")
        self.assertEqual(shot["camera"]["lighting"], "cyberpunk")
        self.assertEqual(shot["error"], "上一镜显存不足")
        self.assertEqual(shot["dialogue"], "站住。")
        self.assertEqual(shot["durationSec"], 8)
        self.assertFalse(shot["usePreviousEndFrame"])
        self.assertIsNone(shot["firstFrameUrl"])
        self.assertIsNone(shot["stillUrl"])
        self.assertIsNone(shot["approvedTakeId"])

    def test_normalize_keeps_agent_stage_and_pipeline_run(self) -> None:
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "agentStatus": [
                {"id": "script", "status": "completed", "message": "剧本已写好"},
                {"id": "storyboard", "status": "running", "message": "正在读剧本"},
            ],
            "pipelineRun": {"agents": ["script", "storyboard"], "active": True},
        })
        by_id = {item["id"]: item for item in payload["agentStatus"]}
        self.assertEqual(by_id["script"]["message"], "剧本已写好")
        self.assertEqual(by_id["storyboard"]["message"], "正在读剧本")
        self.assertEqual(payload["pipelineRun"]["agents"], ["script", "storyboard"])
        self.assertTrue(payload["pipelineRun"]["active"])
        empty = normalize_recipe_payload({"kind": PAYLOAD_KIND_RECIPE})
        self.assertEqual(empty["pipelineRun"], {"agents": [], "active": False})
        self.assertIsNone(empty["agentStatus"][3]["message"])

    def test_agent_done_messages_do_not_claim_media_ready(self) -> None:
        self.assertEqual(AGENT_DONE_MESSAGES["voice"], "配音方案已写好，音频待生成")
        self.assertEqual(AGENT_DONE_MESSAGES["music"], "配乐方案已写好，音频待上传")
        self.assertEqual(AGENT_DONE_MESSAGES["media"], "出片参数已编译，视频待生成")
        self.assertIn("定妆图待生成", AGENT_DONE_MESSAGES["characters"])
        self.assertIn("定妆图待生成", AGENT_DONE_MESSAGES["locations"])
        self.assertEqual(AGENT_DONE_MESSAGES["storyboard"], "分镜方案已写好")
        self.assertEqual(agent_done_message("voice"), AGENT_DONE_MESSAGES["voice"])
        self.assertEqual(agent_done_message("storyboard"), "分镜方案已写好")
        self.assertEqual(
            agent_done_message("storyboard", {
                "kind": PAYLOAD_KIND_RECIPE,
                "scenes": [{"shots": [{"title": "A"}, {"title": "B"}]}],
            }),
            "已写出 2 个镜头",
        )

    def test_normalize_repairs_mojibake_title_and_strips_dialogue_tag(self) -> None:
        garbled_title = "巷口".encode("utf-8").decode("latin-1")
        garbled_line = "你过来。".encode("utf-8").decode("latin-1")
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{
                "shots": [{
                    "title": garbled_title,
                    "description": garbled_title,
                    "promptText": "Close-up on the monitor.",
                    "dialogue": f"<d>[Chinese] {garbled_line}</d>",
                }],
            }],
        })
        shot = payload["scenes"][0]["shots"][0]
        self.assertEqual(shot["title"], "巷口")
        self.assertEqual(shot["description"], "巷口")
        self.assertEqual(shot["dialogue"], "你过来。")

    def test_interrupt_stale_pipeline_marks_running_storyboard_failed(self) -> None:
        from backend.app.director_recipe import STALE_PIPELINE_INTERRUPT, interrupt_stale_pipeline

        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "agentStatus": [
                {"id": "script", "status": "completed"},
                {"id": "storyboard", "status": "running", "message": "正在读剧本"},
            ],
            "pipelineRun": {"agents": ["storyboard"], "active": True},
        })
        updated = interrupt_stale_pipeline(payload)
        self.assertIsNotNone(updated)
        storyboard = next(item for item in updated["agentStatus"] if item["id"] == "storyboard")
        self.assertEqual(storyboard["status"], "failed")
        self.assertEqual(storyboard["error"], STALE_PIPELINE_INTERRUPT)
        self.assertIsNone(storyboard["message"])
        self.assertFalse(updated["pipelineRun"]["active"])
        self.assertIsNone(interrupt_stale_pipeline(updated))

    def test_normalize_shot_keeps_continuity_and_still_fields(self) -> None:
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{
                "shots": [{
                    "id": "shot-a",
                    "title": "开场",
                    "firstFrameUrl": "/api/jobs/aaa/outputs/0/download",
                    "endFrameUrl": "/api/director/recipes/p1/frames/shot-a/end",
                    "endFramePath": "/tmp/end.png",
                    "stillUrl": "/api/jobs/still/outputs/0/download",
                    "stillJobId": "still-1",
                    "usePreviousEndFrame": True,
                    "approvedTakeId": "take-9",
                    "activeTakeIndex": 2,
                }],
            }],
        })
        shot = payload["scenes"][0]["shots"][0]
        self.assertEqual(shot["firstFrameUrl"], "/api/jobs/aaa/outputs/0/download")
        self.assertEqual(shot["endFrameUrl"], "/api/director/recipes/p1/frames/shot-a/end")
        self.assertEqual(shot["endFramePath"], "/tmp/end.png")
        self.assertEqual(shot["stillUrl"], "/api/jobs/still/outputs/0/download")
        self.assertEqual(shot["stillJobId"], "still-1")
        self.assertTrue(shot["usePreviousEndFrame"])
        self.assertEqual(shot["approvedTakeId"], "take-9")
        self.assertEqual(shot["activeTakeIndex"], 2)
        dropped = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{"shots": [{"title": "开场", "firstFrameUrl": "data:image/png;base64,abc"}]}],
        })
        self.assertIsNone(dropped["scenes"][0]["shots"][0]["firstFrameUrl"])

    def test_normalize_character_and_location_keep_library_asset_id(self) -> None:
        payload = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "characters": [{
                "name": "艾达",
                "type": "character",
                "libraryAssetId": "lib-char1",
                "imageUrl": "/api/director/library-assets/lib-char1/image",
            }, {
                "name": "怀表",
                "type": "object",
                "libraryAssetId": "lib-prop1",
            }],
            "locations": [{
                "name": "雨巷",
                "libraryAssetId": "lib-scene1",
            }],
        })
        self.assertEqual(payload["characters"][0]["libraryAssetId"], "lib-char1")
        self.assertEqual(payload["characters"][1]["type"], "object")
        self.assertEqual(payload["characters"][1]["libraryAssetId"], "lib-prop1")
        self.assertEqual(payload["locations"][0]["libraryAssetId"], "lib-scene1")

    def test_insert_library_assets_maps_prop_to_object_and_scene_to_location(self) -> None:
        from backend.app.director_library import insert_library_assets_into_recipe
        from backend.app.director_recipe import empty_recipe_payload

        recipe = insert_library_assets_into_recipe(empty_recipe_payload(), [
            {
                "id": "lib-ada",
                "kind": "character",
                "name": "艾达",
                "description": "女侦探",
                "prompt_text": "a woman detective",
                "gender": "female",
                "image_url": "https://media.example.com/ada.png",
                "image_job_id": "job-ada",
                "owner_user_id": "u1",
            },
            {
                "id": "lib-watch",
                "kind": "prop",
                "name": "怀表",
                "description": "金色怀表",
                "prompt_text": "golden pocket watch",
                "owner_user_id": "u1",
            },
            {
                "id": "lib-alley",
                "kind": "scene",
                "name": "雨巷",
                "description": "夜晚巷口",
                "prompt_text": "rainy alley",
                "owner_user_id": "u1",
            },
        ])
        self.assertEqual(len(recipe["characters"]), 2)
        self.assertEqual(recipe["characters"][0]["name"], "艾达")
        self.assertEqual(recipe["characters"][0]["type"], "character")
        self.assertEqual(recipe["characters"][0]["libraryAssetId"], "lib-ada")
        self.assertEqual(recipe["characters"][0]["imageJobId"], "job-ada")
        self.assertEqual(recipe["characters"][1]["name"], "怀表")
        self.assertEqual(recipe["characters"][1]["type"], "object")
        self.assertEqual(recipe["characters"][1]["libraryAssetId"], "lib-watch")
        self.assertEqual(recipe["locations"][0]["name"], "雨巷")
        self.assertEqual(recipe["locations"][0]["libraryAssetId"], "lib-alley")

    def test_timeline_to_recipe_keeps_existing_camera(self) -> None:
        recipe = timeline_to_recipe({
            "shots": [{
                "id": "shot-cam",
                "title": "环绕",
                "prompt": "The camera orbits the detective.",
                "dialogue": "跟上。",
                "durationSec": 6,
                "camera": {
                    "scale": "WS",
                    "movement": "orbit",
                    "angle": "high_angle",
                    "speed": "smooth",
                    "lighting": "golden_hour",
                    "sfx": "",
                },
                "takes": [],
            }],
        }, title="旧工程")
        shot = recipe["scenes"][0]["shots"][0]
        self.assertEqual(shot["camera"]["scale"], "WS")
        self.assertEqual(shot["camera"]["movement"], "orbit")
        self.assertEqual(shot["camera"]["angle"], "high_angle")
        self.assertEqual(shot["camera"]["lighting"], "golden_hour")
        self.assertEqual(shot["dialogue"], "跟上。")
        self.assertEqual(shot["durationSec"], 6)

    def test_timeline_to_recipe_keeps_first_end_frames(self) -> None:
        recipe = timeline_to_recipe({
            "shots": [
                {
                    "id": "shot-1",
                    "title": "巷口",
                    "prompt": "rain alley",
                    "firstFrameUrl": "/api/jobs/first/outputs/0/download",
                    "endFrameUrl": "/api/jobs/end/outputs/0/download",
                    "usePreviousEndFrame": False,
                    "takes": [],
                },
                {
                    "id": "shot-2",
                    "title": "特写",
                    "prompt": "close-up",
                    "usePreviousEndFrame": True,
                    "takes": [],
                },
            ],
        }, title="旧工程")
        first, second = recipe["scenes"][0]["shots"][0], recipe["scenes"][1]["shots"][0]
        self.assertEqual(first["firstFrameUrl"], "/api/jobs/first/outputs/0/download")
        self.assertEqual(first["endFrameUrl"], "/api/jobs/end/outputs/0/download")
        self.assertTrue(second["usePreviousEndFrame"])


class DirectorScriptSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.provider = LlmProviderService(self.job_store, self.credential_key)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_split_script_json_parsing(self) -> None:
        client = OpenAICompatibleClient(base_url="https://api.example.com", api_key="sk-test")
        sample_json = """```json
{
  "project_title": "雨夜追凶",
  "summary": "未来侦探在暴雨街头追踪神秘仿生人",
  "shots": [
    {
      "shot_number": 1,
      "title": "雨夜街景全景",
      "prompt": "赛博朋克城市全景，倾盆大雨，霓虹招牌反光，镜头缓慢前推",
      "scale": "WS",
      "movement": "zoom_in",
      "angle": "high_angle",
      "speed": "smooth",
      "lighting": "cyberpunk",
      "sfx": "倾盆暴雨声与城市远处低沉的警报"
    },
    {
      "shot_number": 2,
      "title": "侦探特写",
      "prompt": "侦探面部特写，雨水顺着帽檐滴落，眼神锐利凝视前方",
      "scale": "CU",
      "movement": "static",
      "angle": "eye_level",
      "speed": "slow",
      "lighting": "dramatic_low_key",
      "sfx": "沉重的呼吸声与雨水滴答声"
    }
  ]
}
```"""
        with patch.object(client, "chat_completion", return_value=sample_json):
            result = client.split_script("未来都市雨夜追捕", shot_count=2, model="test-model")
            self.assertEqual(result["project_title"], "雨夜追凶")
            self.assertEqual(len(result["shots"]), 2)
            self.assertEqual(result["shots"][0]["scale"], "WS")
            self.assertEqual(result["shots"][1]["movement"], "static")

    def test_split_script_fallback(self) -> None:
        client = OpenAICompatibleClient(base_url="https://api.example.com", api_key="sk-test")
        with patch.object(client, "chat_completion", return_value="非 JSON 文本响应"):
            result = client.split_script("一段简短的剧情文本", shot_count=3, model="test-model")
            self.assertIn("project_title", result)
            self.assertIn("shots", result)
            self.assertGreaterEqual(len(result["shots"]), 2)

    def test_split_script_chinese_and_alias_normalization(self) -> None:
        client = OpenAICompatibleClient(base_url="https://api.example.com", api_key="sk-test")
        chinese_raw_json = """{
  "project_title": "武侠竹林对决",
  "summary": "剑客在竹林间的对决",
  "shots": [
    {
      "shot_number": 1,
      "title": "竹海起势",
      "prompt": "清晨竹海云雾缭绕",
      "scale": "全景",
      "movement": "前推",
      "angle": "平视",
      "speed": "平稳",
      "lighting": "电影柔光",
      "sfx": "风吹竹叶声"
    },
    {
      "shot_number": "2",
      "title": "",
      "prompt": "",
      "scale": "特写",
      "movement": "跟拍",
      "angle": "低机位",
      "speed": "快动态",
      "lighting": "赛博",
      "sfx": null
    }
  ]
}"""
        with patch.object(client, "chat_completion", return_value=chinese_raw_json):
            result = client.split_script("武侠竹海故事", shot_count=2, model="test-model")
            self.assertEqual(result["shots"][0]["scale"], "WS")
            self.assertEqual(result["shots"][0]["movement"], "zoom_in")
            self.assertEqual(result["shots"][0]["angle"], "eye_level")
            self.assertEqual(result["shots"][0]["lighting"], "cinematic_soft")
            self.assertEqual(result["shots"][1]["scale"], "CU")
            self.assertEqual(result["shots"][1]["movement"], "tracking")
            self.assertEqual(result["shots"][1]["angle"], "low_angle")
            self.assertEqual(result["shots"][1]["speed"], "dynamic")
            self.assertEqual(result["shots"][1]["lighting"], "cyberpunk")
            self.assertEqual(result["shots"][1]["sfx"], "")
            self.assertTrue(bool(result["shots"][1]["prompt"]))



class DirectorApiEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_api.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)

        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider

        self.user = self.auth_store.create_user("director_user", "Director", "password123456", UserRole.EMPLOYEE, must_change_password=False)
        self.token, self.csrf_token = self.auth_store.create_session(self.user["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_split_script_endpoint_unavailable_when_disabled(self) -> None:
        response = self.client.post(
            "/api/llm/split-script",
            headers={"X-CSRF-Token": csrf_token(self.token)},
            json={"script": "未来科技短片剧本", "shot_count": 3},
        )
        self.assertEqual(response.status_code, 503)

    def test_split_script_endpoint_success(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com",
            "model": "deepseek-v3",
            "api_key": "sk-dummy",
        })
        mock_response = {
            "project_title": "测试导演项目",
            "summary": "测试剧情梗概",
            "shots": [
                {
                    "shot_number": 1,
                    "title": "起势全景",
                    "prompt": "壮丽的日落山谷，镜头向前推近",
                    "scale": "WS",
                    "movement": "zoom_in",
                    "angle": "eye_level",
                    "speed": "smooth",
                    "lighting": "golden_hour",
                    "sfx": "微风声",
                }
            ],
        }
        with patch.object(self.llm_provider, "split_script", return_value=mock_response):
            response = self.client.post(
                "/api/llm/split-script",
                headers={"X-CSRF-Token": csrf_token(self.token)},
                json={"script": "日落山谷的探险故事", "shot_count": 2},
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["project_title"], "测试导演项目")
            self.assertEqual(len(data["shots"]), 1)


class DirectorCompilerTests(unittest.TestCase):
    def _shot(self, number: int, duration: float = 5, *, prompt: str = "主角走过雨夜街道", first: bool = False, last: bool = False, ref: str | None = None) -> dict:
        shot = {
            "shotNumber": number,
            "title": f"分镜 {number}",
            "durationSec": duration,
            "prompt": prompt if not ref else f"{prompt} {ref}",
            "dialogue": "",
            "soundscape": "",
            "camera": {
                "scale": "MS",
                "movement": "zoom_in",
                "angle": "eye_level",
                "speed": "smooth",
                "lighting": "cinematic_soft",
                "sfx": "",
            },
            "referencedSubjectIds": [ref] if ref else [],
            "usePreviousEndFrame": number > 1,
        }
        if first:
            shot["hasFirstFrame"] = True
            shot["firstFrameUrl"] = f"data:image/png;base64,first{number}"
        if last:
            shot["hasLastFrame"] = True
            shot["endFrameUrl"] = f"data:image/png;base64,last{number}"
        return shot

    def _project(self, shots: list[dict], *, subjects: int = 0, refs_on: bool = True, override: str | None = None, family: str | None = None) -> dict:
        slots = []
        for index in range(9):
            slot = {
                "id": f"@ref{index + 1}",
                "slotIndex": index + 1,
                "name": f"主体 {index + 1}",
                "kind": "character" if index == 0 else "scene" if index == 1 else "prop",
                "retention": "fully_preserved",
                "description": f"特征{index + 1}" if index < subjects else "",
            }
            if index < subjects:
                slot["hasImage"] = True
                slot["previewUrl"] = f"data:image/png;base64,sub{index + 1}"
            slots.append(slot)
        data = {
            "title": "测试工程",
            "aspectRatio": "16:9",
            "canvasTier": "native",
            "fps": 24,
            "refsMode": "refs_on" if refs_on else "refs_off",
            "globalSoundscape": "电影级空间环绕声",
            "globalMusic": "",
            "subjectSlots": slots,
            "shots": shots,
            "manualPromptOverrideEnabled": bool(override),
            "manualPromptOverrideText": override or "",
        }
        if family:
            data["videoWorkflowFamily"] = family
        return data

    def test_duration_snap_and_frame_alignment(self) -> None:
        from backend.app.director_compiler import h3_aligned_frames, snap_h3_duration_sec

        self.assertEqual(snap_h3_duration_sec(1), 2)
        self.assertEqual(snap_h3_duration_sec(2), 2)
        self.assertEqual(snap_h3_duration_sec(3), 3)
        self.assertEqual(snap_h3_duration_sec(4.4), 4)
        self.assertEqual(snap_h3_duration_sec(7.6), 8)
        self.assertEqual(snap_h3_duration_sec(16), 15)
        self.assertEqual(snap_h3_duration_sec(20), 15)
        self.assertEqual(h3_aligned_frames(2), 56)
        self.assertEqual(h3_aligned_frames(5), 124)
        self.assertEqual(h3_aligned_frames(15), 362)

    def test_picture_numbering_locks_first_frame_then_subjects(self) -> None:
        from backend.app.director_compiler import build_reference_plan, compile_shot_prompt, resolve_shot_submission

        project = self._project([self._shot(1, first=True, ref="@ref1")], subjects=2)
        plan = build_reference_plan(project, project["shots"][0])
        self.assertEqual(plan["workflowId"], "minimax-h3-r2v")
        self.assertEqual([item["role"] for item in plan["items"]], ["first_frame", "subject", "subject"])
        self.assertEqual([item["pictureIndex"] for item in plan["items"]], [1, 2, 3])
        self.assertEqual(plan["items"][1]["slotId"], "@ref1")
        prompt = compile_shot_prompt(project, project["shots"][0], plan)
        self.assertIn("<Picture 1>", prompt)
        self.assertIn("<Picture 2>", prompt)
        self.assertIn("shown in <Picture 2>", prompt)
        self.assertIn("shown in <Picture 3>", prompt)
        self.assertIn("<Subject 1> is the character", prompt)
        self.assertIn("subject_definitions:", prompt)
        self.assertIn("detailed_description:", prompt)
        self.assertIn("overall_soundscape:", prompt)
        self.assertIn("non_diegetic_music:", prompt)
        self.assertNotIn("@ref1", prompt)
        self.assertIn("the camera pushes in with small amplitude at slow speed", prompt.lower())
        submission = resolve_shot_submission(project, project["shots"][0])
        self.assertEqual(submission["quality"], "1.0")
        self.assertEqual(submission["speed"], "balanced")
        self.assertEqual(submission["renderPass"], "final")
        self.assertEqual(submission["aspectRatio"], "16:9")
        self.assertEqual(submission["durationSec"], 5)

    def test_i2v_and_t2v_routing(self) -> None:
        from backend.app.director_compiler import build_reference_plan, compile_shot_prompt

        i2v_project = self._project([self._shot(1, first=True, last=True)], subjects=0, refs_on=False)
        i2v_plan = build_reference_plan(i2v_project, i2v_project["shots"][0])
        self.assertEqual(i2v_plan["workflowId"], "minimax-h3-i2v")
        self.assertEqual([item["role"] for item in i2v_plan["items"]], ["first_frame", "last_frame"])
        i2v_prompt = compile_shot_prompt(i2v_project, i2v_project["shots"][0], i2v_plan)
        self.assertIn("How the reference pictures align with the target video", i2v_prompt)
        self.assertIn("<Picture 1>", i2v_prompt)
        self.assertIn("integrated_multimodal_description:", i2v_prompt)
        self.assertIn("[Shot 1]", i2v_prompt)

        t2v_project = self._project([self._shot(1)], subjects=0, refs_on=False)
        t2v_plan = build_reference_plan(t2v_project, t2v_project["shots"][0])
        self.assertEqual(t2v_plan["workflowId"], "minimax-h3-t2v")
        self.assertEqual(t2v_plan["items"], [])
        t2v_prompt = compile_shot_prompt(t2v_project, t2v_project["shots"][0], t2v_plan)
        self.assertNotIn("<Picture", t2v_prompt)
        self.assertIn("integrated_multimodal_description:", t2v_prompt)
        self.assertIn("overall_soundscape:", t2v_prompt)
        self.assertIn("non_diegetic_music:", t2v_prompt)
        self.assertIn("The camera pushes in with small amplitude at slow speed", t2v_prompt)

    def test_workflow_family_routes_lightx2v_and_dual_accel(self) -> None:
        from backend.app.director_compiler import build_reference_plan

        r2v_project = self._project(
            [self._shot(1, first=True, ref="@ref1")],
            subjects=1,
            family="lightx2v",
        )
        r2v_plan = build_reference_plan(r2v_project, r2v_project["shots"][0])
        self.assertEqual(r2v_plan["route"], "r2v")
        self.assertEqual(r2v_plan["workflowId"], "minimax-h3-lightx2v-r2v")

        t2v_project = self._project([self._shot(1)], subjects=0, refs_on=False, family="dual_accel")
        t2v_plan = build_reference_plan(t2v_project, t2v_project["shots"][0])
        self.assertEqual(t2v_plan["route"], "t2v")
        self.assertEqual(t2v_plan["workflowId"], "minimax-h3-dual-accel-t2v")

    def test_clip_allowed_only_when_snapped_total_within_15s(self) -> None:
        from backend.app.director_compiler import compile_clip_prompt, resolve_clip_submission, resolve_shot_submission

        clip_project = self._project([
            self._shot(1, 5, first=True, ref="@ref1"),
            self._shot(2, 5, ref="@ref1"),
            self._shot(3, 5, ref="@ref1"),
        ], subjects=1)
        compiled = compile_clip_prompt(clip_project)
        self.assertTrue(compiled["allowed"])
        self.assertEqual(compiled["durationSec"], 15)
        self.assertIn("[Shot 1]", compiled["prompt"])
        self.assertIn("[Shot 3]", compiled["prompt"])
        self.assertIn("[Shot 2] At 00:05.000", compiled["prompt"])
        self.assertIn("overall_soundscape:", compiled["prompt"])
        self.assertIn("<Picture 2>", compiled["prompt"])
        self.assertIn("detailed_description:", compiled["prompt"])

        too_long = self._project([self._shot(1, 5), self._shot(2, 5), self._shot(3, 5), self._shot(4, 5)])
        rejected = compile_clip_prompt(too_long)
        self.assertFalse(rejected["allowed"])
        self.assertIn("20s", rejected["errors"][0])

        kept_short = self._project([self._shot(1, 3), self._shot(2, 3), self._shot(3, 3)])
        compiled_short = compile_clip_prompt(kept_short)
        self.assertTrue(compiled_short["allowed"])
        self.assertEqual(compiled_short["durationSec"], 9)

        two_second = self._project([self._shot(1, 2, first=True)])
        compiled_two = compile_clip_prompt(two_second)
        self.assertTrue(compiled_two["allowed"])
        self.assertEqual(compiled_two["durationSec"], 2)

        override_project = self._project([self._shot(1)], override="ONLY THIS SHOT PROMPT")
        shot_submit = resolve_shot_submission(override_project, override_project["shots"][0])
        self.assertEqual(shot_submit["prompt"], "ONLY THIS SHOT PROMPT")
        self.assertTrue(shot_submit["isOverride"])
        self.assertFalse(shot_submit["isClip"])
        clip_submit = resolve_clip_submission(override_project)
        self.assertEqual(clip_submit["prompt"], "ONLY THIS SHOT PROMPT")
        self.assertTrue(clip_submit["isClip"])

    def test_more_than_nine_images_errors(self) -> None:
        from backend.app.director_compiler import build_reference_plan

        project = self._project([self._shot(1, first=True)], subjects=9)
        plan = build_reference_plan(project, project["shots"][0])
        self.assertTrue(plan["errors"])
        self.assertEqual(len(plan["items"]), 10)

    def test_canvas_quality_maps_to_registry(self) -> None:
        from backend.app.director_compiler import director_job_options, registry_quality_for_canvas, resolve_shot_submission

        self.assertEqual(registry_quality_for_canvas("fast"), "0.4")
        self.assertEqual(registry_quality_for_canvas("native"), "1.0")
        self.assertEqual(registry_quality_for_canvas("past_native"), "2.0")
        self.assertEqual(director_job_options("preview", "native"), {"quality": "0.4", "speed": "fast", "weight_profile": "full", "renderPass": "preview"})
        self.assertEqual(director_job_options("final", "native"), {"quality": "1.0", "speed": "balanced", "weight_profile": "full", "renderPass": "final"})
        project = self._project([self._shot(1)])
        project["canvasTier"] = "past_native"
        submission = resolve_shot_submission(project, project["shots"][0])
        self.assertEqual(submission["quality"], "2.0")
        preview = resolve_shot_submission(project, project["shots"][0], "preview")
        self.assertEqual(preview["quality"], "0.4")
        self.assertEqual(preview["speed"], "fast")
        project["previewQuality"] = "1.0"
        project["previewSpeed"] = "balanced"
        project["finalQuality"] = "0.4"
        project["finalSpeed"] = "quality"
        custom_preview = resolve_shot_submission(project, project["shots"][0], "preview")
        self.assertEqual(custom_preview["quality"], "1.0")
        self.assertEqual(custom_preview["speed"], "balanced")
        custom_final = resolve_shot_submission(project, project["shots"][0], "final")
        self.assertEqual(custom_final["quality"], "0.4")
        self.assertEqual(custom_final["speed"], "quality")
        project["weightProfile"] = "pruned"
        pruned = resolve_shot_submission(project, project["shots"][0], "final")
        self.assertEqual(pruned["weight_profile"], "pruned")
        self.assertEqual(pruned["speed"], "quality")

    def test_recipe_shot_keeps_camera_and_edited_description(self) -> None:
        from backend.app.director_compiler import recipe_shot_as_timeline_shot, resolve_recipe_shot_submission

        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "artStyle": {"id": "as_1001"},
            "scenes": [{
                "shots": [{
                    "title": "跟拍",
                    "description": "用户改过的雨巷跟拍",
                    "dialogue": "站住。",
                    "durationSec": 7,
                    "camera": {
                        "scale": "CU",
                        "movement": "orbit",
                        "angle": "low_angle",
                        "speed": "smooth",
                        "lighting": "cyberpunk",
                    },
                }],
            }],
        })
        shot = recipe["scenes"][0]["shots"][0]
        timeline_shot = recipe_shot_as_timeline_shot(recipe, shot)
        self.assertEqual(timeline_shot["camera"]["scale"], "CU")
        self.assertEqual(timeline_shot["camera"]["movement"], "orbit")
        self.assertEqual(timeline_shot["dialogue"], "站住。")
        self.assertEqual(timeline_shot["durationSec"], 7)
        self.assertIn("用户改过的雨巷跟拍", timeline_shot["prompt"])
        preview = resolve_recipe_shot_submission(recipe, shot, "preview")
        self.assertEqual(preview["renderPass"], "preview")
        self.assertEqual(preview["quality"], "0.4")
        self.assertEqual(preview["speed"], "fast")
        self.assertIn("用户改过的雨巷跟拍", preview["prompt"])
        self.assertIn("arc shot", preview["prompt"].lower())
        self.assertIn("站住。", preview["prompt"])

    def test_recipe_bilingual_asset_names_keep_character_and_single_location_plates(self) -> None:
        from backend.app.director_compiler import recipe_assets_as_slots, resolve_recipe_shot_submission

        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "characters": [
                {"name": "李明", "promptText": "male programmer with glasses", "imageUrl": "/api/jobs/li/outputs/0/download"},
                {"name": "艾达", "promptText": "sentient AI on a screen", "imageUrl": "/api/jobs/ada/outputs/0/download"},
            ],
            "locations": [
                {"name": "公司办公室", "promptText": "office at night", "imageUrl": "/api/jobs/office/outputs/0/download"},
                {"name": "公司会议室", "promptText": "conference room", "imageUrl": "/api/jobs/room/outputs/0/download"},
            ],
            "scenes": [{"shots": [
                {
                    "title": "对话",
                    "promptText": "Li Ming talks with Ada in the office.",
                    "characterNames": ["Li Ming", "Ada"],
                    "locationName": "Tech company office",
                },
                {
                    "title": "重逢",
                    "promptText": "Li Ming finds Ada in the conference room.",
                    "characterNames": ["Li Ming", "Ada"],
                    "locationName": "Company conference room",
                },
            ]}],
        })

        first, second = recipe["scenes"][0]["shots"]
        first_slots = recipe_assets_as_slots(recipe, first)
        second_slots = recipe_assets_as_slots(recipe, second)
        self.assertEqual([(item["kind"], item["name"]) for item in first_slots], [
            ("character", "李明"), ("character", "艾达"), ("scene", "公司办公室"),
        ])
        self.assertEqual([(item["kind"], item["name"]) for item in second_slots], [
            ("character", "李明"), ("character", "艾达"), ("scene", "公司会议室"),
        ])
        submission = resolve_recipe_shot_submission(recipe, first)
        self.assertEqual(submission["plan"]["route"], "r2v")
        self.assertIn("<Subject 1> is the character", submission["prompt"])
        self.assertIn("<Subject 2> is the character", submission["prompt"])
        self.assertIn("<Subject 3> is the scene", submission["prompt"])

    def test_ref2va_llm_rewrite_is_validated_without_replacing_subject_names(self) -> None:
        from backend.app.director_compiler import build_reference_plan, validate_ref2va_prompt

        project = self._project([self._shot(1, ref="@ref1")], subjects=2)
        plan = build_reference_plan(project, project["shots"][0])
        unbound = (
            "subject_definitions:\n<Subject 1> is a character shown in <Picture 1>.\n"
            "<Subject 2> is a character shown in <Picture 2>.\n\n"
            "summary:\n[reference generation] <Subject 1> meets <Subject 2>.\n\n"
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - retained.\n"
            "<Subject 2> (appears in [Shot 1]): fully_preserved - retained.\n\n"
            "detailed_description:\n[Shot 1] Li Ming looks at Ada.\n\n"
            "overall_soundscape:\nQuiet room tone.\n\n"
            "non_diegetic_music:\nN/A"
        )
        errors = validate_ref2va_prompt(unbound, plan)
        self.assertTrue(any("detailed_description" in error for error in errors))

        polished = unbound.replace(
            "[Shot 1] Li Ming looks at Ada.",
            "[Shot 1] <Subject 1>, Li Ming, looks at <Subject 2>, Ada, on the monitor.",
        )
        self.assertEqual(validate_ref2va_prompt(polished, plan), [])

    def test_h3_prompt_mode_follows_actual_reference_relationship(self) -> None:
        from backend.app.director_compiler import h3_prompt_mode, validate_h3_polished_prompt

        self.assertEqual(h3_prompt_mode({"items": [], "route": "t2v"}), "T2VA")
        self.assertEqual(h3_prompt_mode({"items": [{"role": "first_frame"}], "route": "i2v"}), "I2VA")
        self.assertEqual(h3_prompt_mode({"items": [{"role": "first_frame"}, {"role": "last_frame"}], "route": "i2v"}), "FL2VA")
        self.assertEqual(h3_prompt_mode({"items": [{"role": "last_frame"}], "route": "i2v"}), "L2VA")
        self.assertEqual(h3_prompt_mode({"items": [{"role": "subject", "slotIndex": 1}], "route": "r2v"}), "REF2VA")

        t2va = "integrated_multimodal_description: [Shot 1] A courier walks.\n\noverall_soundscape: Footsteps.\n\nnon_diegetic_music: N/A"
        self.assertEqual(validate_h3_polished_prompt(t2va, {"items": [], "route": "t2v"}), [])
        i2va = (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            + t2va
        )
        self.assertEqual(validate_h3_polished_prompt(i2va, {"items": [{"role": "first_frame"}], "route": "i2v"}), [])

    def test_recipe_standalone_shot_strips_accumulated_shot_tag_and_timecode(self) -> None:
        from backend.app.director_compiler import recipe_shot_as_timeline_shot, resolve_recipe_shot_submission

        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "scenes": [{"shots": [{
                "title": "心灵交流",
                "promptText": "[Shot 3] At 00:11.000, the camera cuts to a medium shot of Li Ming talking with Ada. The camera slowly arcs around him.",
                "durationSec": 7,
            }]}],
        })
        shot = recipe["scenes"][0]["shots"][0]
        timeline_shot = recipe_shot_as_timeline_shot(recipe, shot)
        self.assertNotIn("[Shot 3]", timeline_shot["prompt"])
        self.assertNotIn("00:11.000", timeline_shot["prompt"])
        self.assertTrue(timeline_shot["prompt"].startswith("a medium shot"))
        submission = resolve_recipe_shot_submission(recipe, shot)
        self.assertIn("[Shot 1]", submission["prompt"])
        self.assertNotIn("[Shot 3]", submission["prompt"])
        self.assertNotIn("00:11.000", submission["prompt"])
        self.assertIn("a medium shot of Li Ming", submission["prompt"])

    def test_recipe_previous_end_frame_compiles_as_i2v(self) -> None:
        from backend.app.director_compiler import apply_recipe_continuity, recipe_shot_as_timeline_shot, resolve_recipe_shot_submission

        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "artStyle": {"id": "as_1001"},
            "scenes": [
                {
                    "shots": [{
                        "id": "shot-1",
                        "title": "开场",
                        "description": "走进雨巷",
                        "endFrameUrl": "/api/jobs/end1/outputs/0/download",
                        "endFramePath": "/tmp/end1.png",
                    }],
                },
                {
                    "shots": [{
                        "id": "shot-2",
                        "title": "承接",
                        "description": "侦探转身",
                        "usePreviousEndFrame": True,
                    }],
                },
            ],
        })
        second = recipe["scenes"][1]["shots"][0]
        resolved = apply_recipe_continuity(recipe, second)
        self.assertEqual(resolved["firstFrameUrl"], "/api/jobs/end1/outputs/0/download")
        self.assertEqual(resolved["firstFramePath"], "/tmp/end1.png")
        timeline_shot = recipe_shot_as_timeline_shot(recipe, resolved)
        self.assertEqual(timeline_shot["firstFrameUrl"], "/api/jobs/end1/outputs/0/download")
        self.assertTrue(timeline_shot["hasFirstFrame"])
        submission = resolve_recipe_shot_submission(recipe, second)
        self.assertEqual(submission["plan"]["route"], "i2v")
        self.assertTrue(str(submission["workflowId"]).endswith("-i2v"))
        self.assertEqual(submission["plan"]["items"][0]["role"], "first_frame")

    def test_recipe_previous_still_compiles_as_i2v(self) -> None:
        from backend.app.director_compiler import apply_recipe_continuity, resolve_recipe_shot_submission

        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "artStyle": {"id": "as_1001"},
            "scenes": [
                {
                    "shots": [{
                        "id": "shot-1",
                        "title": "开场",
                        "description": "走进雨巷",
                        "stillUrl": "/api/jobs/still1/outputs/0/download",
                        "stillJobId": "still1",
                    }],
                },
                {
                    "shots": [{
                        "id": "shot-2",
                        "title": "承接",
                        "description": "侦探转身",
                        "usePreviousEndFrame": True,
                    }],
                },
            ],
        })
        second = recipe["scenes"][1]["shots"][0]
        resolved = apply_recipe_continuity(recipe, second)
        self.assertEqual(resolved["firstFrameUrl"], "/api/jobs/still1/outputs/0/download")
        self.assertEqual(resolved["firstFrameJobId"], "still1")
        submission = resolve_recipe_shot_submission(recipe, second)
        self.assertEqual(submission["plan"]["route"], "i2v")
        self.assertTrue(str(submission["workflowId"]).endswith("-i2v"))


class DirectorAnalyzeEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_analyze.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        self.user = self.auth_store.create_user("vision_user", "Vision", "password123456", UserRole.EMPLOYEE, must_change_password=False)
        self.token, self.csrf_token = self.auth_store.create_session(self.user["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_status_reports_vision_from_model_name(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-ai/DeepSeek-V4-Flash-0731",
            "api_key": "sk-dummy",
        })
        response = self.client.get("/api/llm/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["supports_vision"])

        self.llm_provider.update({"model": "qwen2.5-vl-72b-instruct"})
        response = self.client.get("/api/llm/status")
        self.assertTrue(response.json()["supports_vision"])

    def test_analyze_subject_requires_vision_model(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        response = self.client.post(
            "/api/llm/analyze-subject",
            headers={"X-CSRF-Token": csrf_token(self.token)},
            data={"kind": "character", "name": "主角"},
            files={"image": ("ref.png", b"fake-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("视觉", response.json()["detail"])

    def test_analyze_subject_sends_image(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "qwen-vl-max",
            "api_key": "sk-dummy",
        })
        with patch.object(self.llm_provider, "analyze_subject", return_value="黑色短发，深色风衣，冷白皮"):
            response = self.client.post(
                "/api/llm/analyze-subject",
                headers={"X-CSRF-Token": csrf_token(self.token)},
                data={"kind": "character", "name": "侦探"},
                files={"image": ("ref.png", b"fake-bytes", "image/png")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "黑色短发，深色风衣，冷白皮")


class DirectorProjectApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_director_projects.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        self.user = self.auth_store.create_user(
            "director_lib", "导演库", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.other = self.auth_store.create_user(
            "director_other", "另一员工", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, self.csrf = self.auth_store.create_session(self.user["id"])
        self.other_token, self.other_csrf = self.auth_store.create_session(self.other["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(token or self.token)}

    def _empty_payload(self, *, shots: list[dict] | None = None) -> dict:
        return {
            "aspectRatio": "16:9",
            "canvasTier": "native",
            "width": 1344,
            "height": 768,
            "fps": 24,
            "refsMode": "refs_on",
            "globalSoundscape": "电影级空间环境声",
            "globalMusic": "",
            "subjectSlots": [{"id": "@ref1", "slotIndex": 1, "name": "主体 1", "kind": "character", "retention": "fully_preserved", "description": "", "previewUrl": "data:image/png;base64,abc"}],
            "shots": shots if shots is not None else [{
                "id": "shot-1",
                "shotNumber": 1,
                "title": "分镜 1",
                "startSec": 0,
                "durationSec": 5,
                "prompt": "",
                "status": "idle",
                "takes": [],
                "firstFrameUrl": "data:image/png;base64,frame",
            }],
            "manualPromptOverrideEnabled": False,
            "manualPromptOverrideText": "",
        }

    def test_crud_list_and_copy(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "雨夜追凶",
                "summary": "侦探短片",
                "source_script": "雨夜里侦探穿过暗巷。",
                "style_vibe": "赛博朋克",
                "requested_shot_count": 4,
                "payload": self._empty_payload(),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["title"], "雨夜追凶")
        self.assertEqual(body["source_script"], "雨夜里侦探穿过暗巷。")
        self.assertTrue(body["has_source_script"])
        self.assertEqual(body["generation_status"], "pending")
        self.assertIsNone(body["payload"]["shots"][0].get("firstFrameUrl"))
        self.assertIsNone(body["payload"]["subjectSlots"][0].get("previewUrl"))
        self.assertNotIn("owner_user_id", body)

        listed = self.client.get("/api/director/projects")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertNotIn("source_script", listed.json()[0])
        self.assertNotIn("payload", listed.json()[0])
        self.assertTrue(listed.json()[0]["has_source_script"])

        project_id = body["id"]
        updated = self.client.put(
            f"/api/director/projects/{project_id}",
            headers=self._headers(),
            json={"title": "雨夜追凶·终", "payload": self._empty_payload(shots=[
                {**self._empty_payload()["shots"][0], "status": "succeeded", "outputVideoUrl": "/api/media/a.mp4"},
            ])},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "雨夜追凶·终")
        self.assertEqual(updated.json()["source_script"], "雨夜里侦探穿过暗巷。")
        self.assertEqual(updated.json()["generation_status"], "complete")

        copied = self.client.post(f"/api/director/projects/{project_id}/copy", headers=self._headers())
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.json()["title"], "雨夜追凶·终 副本")
        self.assertEqual(copied.json()["source_script"], "雨夜里侦探穿过暗巷。")
        self.assertNotEqual(copied.json()["id"], project_id)

        deleted = self.client.delete(f"/api/director/projects/{project_id}", headers=self._headers())
        self.assertEqual(deleted.status_code, 204)
        missing = self.client.get(f"/api/director/projects/{project_id}")
        self.assertEqual(missing.status_code, 404)

    def test_employee_cannot_access_another_users_project(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "员工甲的工程", "source_script": "仅甲可见", "payload": self._empty_payload()},
        )
        project_id = created.json()["id"]
        other_client = TestClient(app)
        other_client.cookies.set("zly_ai_video_studio_session", self.other_token)
        listed = other_client.get("/api/director/projects")
        self.assertEqual(listed.json(), [])
        self.assertEqual(other_client.get(f"/api/director/projects/{project_id}").status_code, 404)
        self.assertEqual(
            other_client.put(
                f"/api/director/projects/{project_id}",
                headers=self._headers(self.other_token),
                json={"title": "抢改"},
            ).status_code,
            404,
        )
        self.assertEqual(
            other_client.delete(
                f"/api/director/projects/{project_id}",
                headers=self._headers(self.other_token),
            ).status_code,
            404,
        )
        still = self.client.get(f"/api/director/projects/{project_id}")
        self.assertEqual(still.status_code, 200)
        self.assertEqual(still.json()["title"], "员工甲的工程")

    def test_content_revision_conflict_returns_latest_snapshot(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "并发工程", "payload": self._empty_payload()},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()
        self.assertEqual(project["revision"], 1)
        self.assertEqual(project["content_revision"], 1)

        first = self.client.put(
            f"/api/director/projects/{project['id']}",
            headers=self._headers(),
            json={"title": "窗口 A", "expected_content_revision": 1},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["content_revision"], 2)

        conflict = self.client.put(
            f"/api/director/projects/{project['id']}",
            headers=self._headers(),
            json={"title": "窗口 B", "expected_content_revision": 1},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        detail = conflict.json()["detail"]
        self.assertEqual(detail["code"], "DIRECTOR_CONTENT_CONFLICT")
        self.assertEqual(detail["current_revision"], 2)
        self.assertEqual(detail["current_project"]["title"], "窗口 A")

        forced = self.client.put(
            f"/api/director/projects/{project['id']}",
            headers=self._headers(),
            json={"title": "窗口 B", "expected_content_revision": 1, "force": True},
        )
        self.assertEqual(forced.status_code, 200, forced.text)
        self.assertEqual(forced.json()["title"], "窗口 B")
        self.assertEqual(forced.json()["content_revision"], 3)

    def test_migrate_localstorage_payload_is_idempotent_and_strips_data_urls(self) -> None:
        local_id = "proj-local-rain-01"
        first = self.client.post(
            "/api/director/projects/migrate",
            headers=self._headers(),
            json={
                "projects": [{
                    "id": local_id,
                    "title": "浏览器旧工程",
                    "summary": "迁库",
                    "source_script": "原文必须留下来",
                    "style_vibe": "电影级大片",
                    "requested_shot_count": 3,
                    "payload": self._empty_payload(),
                    "created_at": "2026-08-20T00:00:00+00:00",
                    "updated_at": "2026-08-21T00:00:00+00:00",
                }],
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["imported"], 1)
        self.assertEqual(first.json()["skipped"], 0)
        fetched = self.client.get(f"/api/director/projects/{local_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["source_script"], "原文必须留下来")
        self.assertEqual(fetched.json()["created_at"], "2026-08-20T00:00:00+00:00")
        self.assertIsNone(fetched.json()["payload"]["shots"][0].get("firstFrameUrl"))

        second = self.client.post(
            "/api/director/projects/migrate",
            headers=self._headers(),
            json={"projects": [{"id": local_id, "title": "浏览器旧工程", "source_script": "不应覆盖", "payload": {}}]},
        )
        self.assertEqual(second.json()["imported"], 0)
        self.assertEqual(second.json()["skipped"], 1)
        again = self.client.get(f"/api/director/projects/{local_id}")
        self.assertEqual(again.json()["source_script"], "原文必须留下来")

    def test_split_result_put_keeps_source_script(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "待拆分",
                "source_script": "探险飞船降落在冰封异星。",
                "style_vibe": "科幻史诗",
                "requested_shot_count": 2,
                "payload": self._empty_payload(shots=[]),
            },
        )
        project_id = created.json()["id"]
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com",
            "model": "deepseek-v3",
            "api_key": "sk-dummy",
        })
        mock_response = {
            "project_title": "深空遗迹",
            "summary": "飞船降落",
            "shots": [{
                "shot_number": 1, "title": "降落", "prompt": "冰封异星降落",
                "scale": "WS", "movement": "zoom_in", "angle": "eye_level",
                "speed": "smooth", "lighting": "cinematic_soft", "sfx": "",
            }],
        }
        with patch.object(self.llm_provider, "split_script", return_value=mock_response):
            split = self.client.post(
                "/api/llm/split-script",
                headers=self._headers(),
                json={"script": "探险飞船降落在冰封异星。", "shot_count": 2, "style_vibe": "科幻史诗"},
            )
        self.assertEqual(split.status_code, 200)
        shots = [{
            "id": "shot-split-1",
            "shotNumber": 1,
            "title": split.json()["shots"][0]["title"],
            "startSec": 0,
            "durationSec": 5,
            "prompt": split.json()["shots"][0]["prompt"],
            "status": "idle",
            "takes": [],
        }]
        saved = self.client.put(
            f"/api/director/projects/{project_id}",
            headers=self._headers(),
            json={
                "title": split.json()["project_title"],
                "summary": split.json()["summary"],
                "source_script": "探险飞船降落在冰封异星。",
                "payload": {**self._empty_payload(shots=shots), "shots": shots},
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["title"], "深空遗迹")
        self.assertEqual(saved.json()["source_script"], "探险飞船降落在冰封异星。")
        self.assertEqual(saved.json()["shot_count"], 1)
        persisted = self.client.get(f"/api/director/projects/{project_id}")
        self.assertEqual(persisted.json()["source_script"], "探险飞船降落在冰封异星。")
        self.assertEqual(persisted.json()["payload"]["shots"][0]["title"], "降落")

    def test_put_can_write_and_clear_source_script(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "空白工程", "payload": self._empty_payload()},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]
        self.assertEqual(created.json()["source_script"], "")
        self.assertFalse(created.json()["has_source_script"])

        filled = self.client.put(
            f"/api/director/projects/{project_id}",
            headers=self._headers(),
            json={"source_script": "手写原文，不依赖拆分弹窗。"},
        )
        self.assertEqual(filled.status_code, 200, filled.text)
        self.assertEqual(filled.json()["source_script"], "手写原文，不依赖拆分弹窗。")
        self.assertTrue(filled.json()["has_source_script"])

        cleared = self.client.put(
            f"/api/director/projects/{project_id}",
            headers=self._headers(),
            json={"source_script": ""},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["source_script"], "")
        self.assertFalse(cleared.json()["has_source_script"])
        persisted = self.client.get(f"/api/director/projects/{project_id}")
        self.assertEqual(persisted.json()["source_script"], "")


    def test_art_styles_endpoint_returns_catalog(self) -> None:
        anonymous = TestClient(app)
        self.assertEqual(anonymous.get("/api/director/art-styles").status_code, 401)
        response = self.client.get("/api/director/art-styles")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 34)
        self.assertEqual(len(body["categories"]), 9)
        self.assertEqual(len(body["styles"]), 34)
        first = body["styles"][0]
        self.assertTrue(first["promptPrefix"])
        self.assertEqual(first["id"], "as_1001")
        self.assertEqual(first["imageUrl"], "/api/director/art-styles/as_1001/preview")
        self.assertEqual(
            first["promptPrefix"],
            "epic cinematic scene, dramatic lighting, rich atmosphere, film-grade composition, emotional visual storytelling",
        )
        self.assertTrue(all(item["imageUrl"] == f"/api/director/art-styles/{item['id']}/preview" for item in body["styles"]))
        payload = art_style_catalog_payload()
        self.assertEqual(payload["count"], 34)

    def test_art_style_preview_requires_login_and_serves_cached_jpeg(self) -> None:
        anonymous = TestClient(app)
        self.assertEqual(anonymous.get("/api/director/art-styles/as_1001/preview").status_code, 401)
        missing = self.client.get("/api/director/art-styles/as_1999/preview")
        self.assertEqual(missing.status_code, 404)
        jpeg = b"\xff\xd8\xff\xdb" + b"0" * 48
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.app.director_catalog.PREVIEW_DIR", Path(tmp)):
                with patch("backend.app.director_catalog.urllib.request.urlopen") as urlopen:
                    response = MagicMock()
                    response.read.return_value = jpeg
                    response.__enter__.return_value = response
                    response.__exit__.return_value = False
                    urlopen.return_value = response
                    ok = self.client.get("/api/director/art-styles/as_1001/preview")
                    failed = MagicMock()
                    failed.read.return_value = b"not-a-jpeg"
                    failed.__enter__.return_value = failed
                    failed.__exit__.return_value = False
                    urlopen.return_value = failed
                    bad = self.client.get("/api/director/art-styles/as_1002/preview")
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.headers["content-type"].split(";")[0], "image/jpeg")
        self.assertEqual(ok.content, jpeg)
        self.assertEqual(bad.status_code, 502)

    def test_recipe_payload_roundtrip_and_invalid_art_style(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "Recipe 工程",
                "summary": "侦探",
                "source_script": "雨夜里侦探穿过暗巷。",
                "payload": {
                    "kind": "director_recipe",
                    "script": {"title": "雨夜追凶", "summary": "侦探短片", "fullStory": "雨夜里侦探穿过暗巷。"},
                    "artStyle": {"id": "as_1005", "name": "乱写", "promptPrefix": "伪造"},
                    "characters": [{"name": "侦探", "promptText": "黑风衣", "gender": "male"}],
                    "locations": [{"name": "暗巷", "promptText": "空巷，无人物"}],
                    "scenes": [{
                        "title": "巷口",
                        "shots": [{
                            "title": "跟踪",
                            "description": "走进雨巷",
                            "dialogue": "别动。",
                            "characterNames": ["侦探"],
                            "durationSec": 5,
                            "status": "idle",
                        }],
                    }],
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["kind"], "director_recipe")
        self.assertEqual(body["payload"]["kind"], "director_recipe")
        self.assertEqual(body["payload"]["artStyle"]["id"], "as_1005")
        self.assertEqual(body["payload"]["artStyle"]["name"], "单色张力")
        self.assertEqual(body["payload"]["artStyle"]["imageUrl"], "/api/director/art-styles/as_1005/preview")
        self.assertEqual(
            body["payload"]["artStyle"]["promptPrefix"],
            "monochrome cinematic style, black and white, sharp contrast, dramatic shadows, tense atmosphere",
        )
        self.assertEqual(body["shot_count"], 1)
        listed = self.client.get("/api/director/projects")
        self.assertEqual(listed.json()[0]["kind"], "director_recipe")

        rejected = self.client.put(
            f"/api/director/projects/{body['id']}",
            headers=self._headers(),
            json={"payload": {"kind": "director_recipe", "artStyle": {"id": "not-a-real-style"}}},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("目录", rejected.json()["detail"])

    def test_get_recipe_persists_qiniu_image_url(self) -> None:
        from backend.app.models import JobMode, JobStatus

        job = self.job_store.create(
            "assetjob1", JobMode.GRS_GPT_IMAGE_2, "prompt", "", None, [],
            owner_user_id=self.user["id"],
        )
        item = job["rounds"][0]["generation_items"][0]
        self.job_store.update_generation(item["id"], status=JobStatus.SUCCEEDED, outputs=[{
            "kind": "image",
            "path": "studio/image/ada.png",
            "label": "生成图片",
            "delivery_status": "cloud",
            "cloud_url": "https://media.example.com/studio/image/ada.png",
        }])
        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "artStyle": {"id": "as_1001"},
            "characters": [{"name": "艾达", "promptText": "look", "imageJobId": "assetjob1"}],
        })
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "定妆云地址", "payload": recipe},
        )
        self.assertEqual(created.status_code, 201, created.text)
        fetched = self.client.get(f"/api/director/projects/{created.json()['id']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(
            fetched.json()["payload"]["characters"][0]["imageUrl"],
            "https://media.example.com/studio/image/ada.png",
        )
        persisted = self.job_store.get_director_project(created.json()["id"])
        self.assertEqual(
            persisted["payload"]["characters"][0]["imageUrl"],
            "https://media.example.com/studio/image/ada.png",
        )

    def test_convert_timeline_to_recipe(self) -> None:
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "旧时间轴",
                "summary": "可转换",
                "source_script": "探险飞船降落在冰封异星。",
                "payload": self._empty_payload(shots=[{
                    "id": "shot-1",
                    "shotNumber": 1,
                    "title": "降落",
                    "prompt": "冰封异星降落",
                    "startSec": 0,
                    "durationSec": 5,
                    "status": "idle",
                    "takes": [],
                }]),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["kind"], "timeline")
        project_id = created.json()["id"]
        converted = self.client.post(
            f"/api/director/projects/{project_id}/convert-to-recipe",
            headers=self._headers(),
        )
        self.assertEqual(converted.status_code, 200, converted.text)
        payload = converted.json()["payload"]
        self.assertEqual(converted.json()["kind"], "director_recipe")
        self.assertEqual(payload["kind"], "director_recipe")
        self.assertEqual(payload["script"]["fullStory"], "探险飞船降落在冰封异星。")
        self.assertEqual(len(payload["scenes"]), 1)
        self.assertEqual(payload["scenes"][0]["shots"][0]["title"], "降落")
        again = self.client.post(
            f"/api/director/projects/{project_id}/convert-to-recipe",
            headers=self._headers(),
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["payload"]["kind"], "director_recipe")


class DirectorJobCreateStatusTests(unittest.TestCase):
    def test_create_job_returns_current_status_after_enqueue(self) -> None:
        from backend.app import main as main_module
        from backend.app.config import Settings
        from backend.app.models import JobStatus

        class WorkerStub:
            def __init__(self, store, comfy, *_args) -> None:
                self.store = store

            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            async def enqueue(self, job_id: str) -> None:
                self.store.update(job_id, status=JobStatus.RUNNING, stage="MiniMax H3 正在生成视频", progress=0)

        with tempfile.TemporaryDirectory() as directory:
            original_settings = main_module.settings
            original_worker = main_module.JobWorker
            root = Path(directory)
            main_module.settings = Settings(workspace_dir=root, data_dir_override=str(root / "data"))
            main_module.JobWorker = WorkerStub
            try:
                with TestClient(main_module.app) as client:
                    user = main_module.app.state.auth_store.create_user(
                        "director-status", "导演状态", "secure-pass-123", UserRole.SUPER_ADMIN, must_change_password=False,
                    )
                    token, _ = main_module.app.state.auth_store.create_session(user["id"])
                    response = client.post(
                        "/api/jobs",
                        headers={"X-CSRF-Token": csrf_token(token)},
                        cookies={"zly_ai_video_studio_session": token},
                        data={"mode": "minimax-h3-t2v", "prompt": "电影级城市远景", "options": "{}"},
                    )
                    self.assertEqual(response.status_code, 202)
                    payload = response.json()
                    self.assertEqual(payload["status"], "running")
                    self.assertEqual(payload["stage"], "MiniMax H3 正在生成视频")
            finally:
                main_module.settings = original_settings
                main_module.JobWorker = original_worker


class DirectorAgentPipelineTests(unittest.TestCase):
    def test_art_style_agent_rejects_invented_catalog_id(self) -> None:
        from backend.app.director_agents import run_agent

        def chat(_messages: list[dict]) -> str:
            return '{"id": "invented_neon_soup", "name": "自造霓虹汤"}'

        recipe = run_agent(
            "art_style",
            {"kind": "director_recipe", "script": {"title": "雨夜", "summary": "侦探", "fullStory": "赛博雨巷"}},
            goal="neon cyber noir detective in the rain",
            chat_fn=chat,
        )
        self.assertEqual(recipe["artStyle"]["id"], "as_1003")
        self.assertNotEqual(recipe["artStyle"]["id"], "invented_neon_soup")
        self.assertIn("neon", recipe["artStyle"]["promptPrefix"])
        self.assertEqual(recipe["agentStatus"][2]["status"], "completed")

    def test_pipeline_json_and_media_compile(self) -> None:
        from backend.app.director_agents import run_recipe_pipeline

        def chat(messages: list[dict]) -> str:
            system = messages[0]["content"]
            if "AGENT_ID: script" in system:
                return '{"title": "雨夜追凶", "summary": "侦探短片", "fullStory": "侦探阿凯走入雨巷。"}'
            if "AGENT_ID: art_style" in system:
                return '{"id": "as_1005"}'
            if "AGENT_ID: storyboard" in system:
                return json.dumps({
                    "scenes": [{
                        "title": "巷口",
                        "locationName": "暗巷",
                        "shots": [{
                            "title": "跟踪",
                            "description": "侦探走进雨巷",
                            "promptText": "Live-action, cinematic, a medium shot frames detective Kai walking into a rainy alley. The camera follows with a tracking shot with small amplitude at slow speed.",
                            "dialogue": "别动。",
                            "characterNames": ["阿凯"],
                            "locationName": "暗巷",
                            "durationSec": 5,
                            "camera": {"scale": "MS", "movement": "tracking", "angle": "eye_level", "speed": "smooth", "lighting": "cinematic_soft"},
                        }],
                    }],
                }, ensure_ascii=False)
            if "AGENT_ID: characters" in system:
                return '{"characters":[{"name":"阿凯","description":"黑风衣侦探","promptText":"male detective in black coat","gender":"male","type":"character"}]}'
            if "AGENT_ID: locations" in system:
                return '{"locations":[{"name":"暗巷","description":"雨夜空巷","promptText":"empty rainy alley, no people"}]}'
            if "AGENT_ID: voice" in system:
                return '{"characters":[{"name":"阿凯","voiceId":"onyx"}],"shots":[{"shotNumber":1,"dialogue":"别动。","speakerName":"阿凯"}]}'
            if "AGENT_ID: music" in system:
                return '{"globalMusic":"low tense noir score","globalSoundscape":"rain and distant traffic","bgmVolume":0.22,"bgmFadeInSec":1.5,"bgmFadeOutSec":2.5}'
            return "{}"

        recipe = run_recipe_pipeline({}, goal="雨夜里侦探穿过暗巷。", chat_fn=chat, skip_research=True)
        self.assertEqual(recipe["script"]["title"], "雨夜追凶")
        self.assertEqual(recipe["artStyle"]["id"], "as_1005")
        self.assertEqual(recipe["characters"][0]["name"], "阿凯")
        self.assertEqual(recipe["locations"][0]["name"], "暗巷")
        self.assertEqual(recipe["scenes"][0]["shots"][0]["dialogue"], "别动。")
        self.assertEqual(recipe["scenes"][0]["shots"][0]["speakerName"], "阿凯")
        self.assertEqual(recipe["characters"][0]["voiceId"], "onyx")
        self.assertEqual(recipe["audio"]["bgmVolume"], 0.22)
        self.assertEqual(recipe["audio"]["bgmFadeInSec"], 1.5)
        self.assertEqual(recipe["scenes"][0]["shots"][0]["description"], "侦探走进雨巷")
        self.assertIn("tracking shot", recipe["scenes"][0]["shots"][0]["promptText"])
        self.assertTrue(recipe["scenes"][0]["shots"][0]["compiledPrompt"])
        self.assertIn("monochrome", recipe["scenes"][0]["shots"][0]["compiledPrompt"])
        compiled = recipe["scenes"][0]["shots"][0]["compiledPrompt"]
        self.assertIn("integrated_multimodal_description:", compiled)
        self.assertIn("overall_soundscape:", compiled)
        self.assertIn("non_diegetic_music:", compiled)
        self.assertIn("<d>[Chinese] 别动。</d>", compiled)
        self.assertIn("tracking shot", compiled)
        self.assertNotIn("侦探走进雨巷", compiled)
        statuses = {item["id"]: item["status"] for item in recipe["agentStatus"]}
        self.assertEqual(statuses["research"], "completed")
        self.assertEqual(statuses["media"], "completed")
        self.assertTrue(all(status == "completed" for status in statuses.values()))
        messages = {item["id"]: item["message"] for item in recipe["agentStatus"]}
        self.assertEqual(messages["voice"], "配音方案已写好，音频待生成")
        self.assertEqual(messages["music"], "配乐方案已写好，音频待上传")
        self.assertEqual(messages["media"], "出片参数已编译，视频待生成")
        self.assertEqual(messages["characters"], "人物方案已抽出，定妆图待生成")
        self.assertEqual(messages["locations"], "场景方案已抽出，定妆图待生成")

    def test_storyboard_agent_follows_h3_official_skill(self) -> None:
        from backend.app.director_agents import run_agent
        from backend.app.llm_minimax_skills import build_h3_storyboard_agent_prompt

        captured: list[str] = []

        def chat(messages: list[dict]) -> str:
            captured.append(messages[0]["content"])
            return json.dumps({
                "scenes": [{
                    "title": "巷口",
                    "locationName": "暗巷",
                    "shots": [{
                        "title": "跟踪",
                        "description": "侦探走进雨巷，镜头平稳跟拍。",
                        "promptText": "Live-action, cinematic, a medium shot frames detective Kai in a black coat walking into the rainy alley. The camera follows with a tracking shot with small amplitude at slow speed.",
                        "dialogue": "别动。",
                        "characterNames": ["阿凯"],
                        "locationName": "暗巷",
                        "durationSec": 5,
                        "camera": {"scale": "MS", "movement": "tracking", "angle": "eye_level", "speed": "smooth", "lighting": "cinematic_soft"},
                        "soundscape": "雨打石板和远处车声。",
                    }],
                }],
            }, ensure_ascii=False)

        skill = build_h3_storyboard_agent_prompt()
        self.assertIn("h3-prompt-writing", skill)
        self.assertIn("Video Prompt Writing Guide", skill)
        self.assertIn("The camera pushes in with small amplitude at slow speed toward the folded letter", skill)
        self.assertIn("<d>[Chinese]", skill)
        self.assertIn("promptText", skill)
        self.assertIn("Never translate or transliterate names", skill)
        self.assertIn("local timeline starts at 00:00", skill)
        self.assertIn("8–24", skill)
        self.assertIn("主镜头", skill)
        self.assertIn("ONLY one JSON object", skill)

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "雨夜", "summary": "侦探", "fullStory": "侦探走进雨巷。"}},
            goal="雨夜里侦探穿过暗巷。",
            chat_fn=chat,
        )
        self.assertTrue(captured)
        self.assertIn("h3-prompt-writing", captured[0])
        self.assertIn("侦探走进雨巷", recipe["scenes"][0]["shots"][0]["description"])
        self.assertNotIn("Live-action", recipe["scenes"][0]["shots"][0]["description"])
        self.assertIn("tracking shot", recipe["scenes"][0]["shots"][0]["promptText"])
        self.assertEqual(recipe["scenes"][0]["shots"][0]["soundscape"], "雨打石板和远处车声。")

    def test_storyboard_keeps_chinese_card_when_model_writes_english(self) -> None:
        from backend.app.director_agents import run_agent

        def chat(messages: list[dict]) -> str:
            return json.dumps({
                "scenes": [{
                    "title": "巷口",
                    "locationName": "暗巷",
                    "shots": [{
                        "title": "跟踪",
                        "description": "Live-action, cinematic, a medium shot frames detective Kai walking into a rainy alley.",
                        "dialogue": "别动。",
                        "characterNames": ["阿凯"],
                        "locationName": "暗巷",
                        "durationSec": 5,
                    }],
                }],
            })

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "雨夜", "summary": "侦探", "fullStory": "侦探走进雨巷。"}},
            goal="雨夜里侦探穿过暗巷。",
            chat_fn=chat,
        )
        shot = recipe["scenes"][0]["shots"][0]
        self.assertNotIn("Live-action", shot["description"])
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in shot["description"]))
        self.assertIn("medium shot", shot["promptText"])

    def test_storyboard_keeps_every_shot_from_script_and_rejects_dummy(self) -> None:
        from backend.app.director_agents import parse_json_object, run_agent, _apply_storyboard

        def chat(_messages: list[dict]) -> str:
            return json.dumps({
                "scenes": [
                    {
                        "title": f"场 {index}",
                        "locationName": "公司",
                        "shots": [{
                            "title": f"镜头 {index}",
                            "description": f"程序员在第 {index} 场推开玻璃门。",
                            "promptText": f"A medium shot of a programmer in scene {index} pushing a glass door.",
                            "dialogue": "",
                            "characterNames": ["林舟"],
                            "locationName": "公司",
                            "durationSec": 5,
                        }],
                    }
                    for index in range(1, 13)
                ],
            }, ensure_ascii=False)

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "summary": "加班", "fullStory": "林舟连夜改代码，天亮去公司开会。"}},
            goal="生成一份都市类型程序员职业的 AI 短剧剧本",
            chat_fn=chat,
        )
        shots = [shot for scene in recipe["scenes"] for shot in scene["shots"]]
        self.assertEqual(len(shots), 12)
        self.assertEqual(shots[0]["title"], "镜头 1")
        self.assertEqual(shots[-1]["title"], "镜头 12")
        self.assertTrue(all(shot["title"] != "主镜头" for shot in shots))

        empty = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟连夜改代码。"}},
            goal="生成一份都市类型程序员职业的 AI 短剧剧本",
            chat_fn=lambda _messages: "{}",
        )
        self.assertEqual(empty["scenes"], [])
        self.assertEqual(empty["agentStatus"][3]["status"], "failed")
        self.assertIn("镜头", empty["agentStatus"][3]["error"] or "")

        truncated = parse_json_object(
            '{"scenes":[{"title":"开场","shots":['
            '{"title":"进门","description":"推门进屋","promptText":"He pushes the door"},'
            '{"title":"坐下","description":"坐到工位","promptText":"He sits at the desk"},'
            '{"title":"开会","description":"会议室对视","promptText":"They face each other"'
        )
        self.assertIsNotNone(truncated)
        self.assertEqual(len(truncated["scenes"][0]["shots"]), 3)

        recipe = {"kind": "director_recipe", "script": {}, "scenes": []}
        _apply_storyboard(recipe, truncated, "goal")
        self.assertEqual(len(recipe["scenes"][0]["shots"]), 3)

    def test_storyboard_retries_when_model_returns_one_dummy_shot(self) -> None:
        from backend.app.director_agents import run_agent

        calls: list[str] = []

        def chat(messages: list[dict]) -> str:
            calls.append(messages[0]["content"])
            if len(calls) == 1:
                return json.dumps({
                    "scenes": [{
                        "title": "开场",
                        "shots": [{"title": "主镜头", "description": "生成一份都市类型程序员职业的 AI 短剧剧本"}],
                    }],
                }, ensure_ascii=False)
            return json.dumps({
                "scenes": [{
                    "title": "公司",
                    "locationName": "写字楼",
                    "shots": [
                        {
                            "title": "进门",
                            "description": "林舟推开玻璃门。",
                            "promptText": "A programmer pushes open a glass office door.",
                            "characterNames": ["林舟"],
                            "durationSec": 5,
                        },
                        {
                            "title": "工位",
                            "description": "他坐到显示器前打开终端。",
                            "promptText": "He sits at dual monitors and opens a terminal.",
                            "characterNames": ["林舟"],
                            "durationSec": 6,
                        },
                    ],
                }],
            }, ensure_ascii=False)

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟清晨赶到公司改代码。"}},
            goal="生成一份都市类型程序员职业的 AI 短剧剧本",
            chat_fn=chat,
        )
        self.assertGreaterEqual(len(calls), 2)
        shots = [shot for scene in recipe["scenes"] for shot in scene["shots"]]
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0]["title"], "进门")
        self.assertEqual(recipe["agentStatus"][3]["status"], "completed")

    def test_storyboard_accepts_shot_array_and_nested_payload(self) -> None:
        from backend.app.director_agents import parse_json_object, run_agent

        shots_payload = [
            {"title": "进门", "description": "林舟推开玻璃门。", "promptText": "He pushes the glass door."},
            {"title": "工位", "description": "他坐下打开电脑。", "promptText": "He sits and opens a laptop."},
            {"title": "开会", "description": "会议室里对视。", "promptText": "They face each other across the table."},
        ]

        def chat_array(_messages: list[dict]) -> str:
            return json.dumps(shots_payload, ensure_ascii=False)

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟赶到公司开会。"}},
            goal="都市程序员短剧",
            chat_fn=chat_array,
        )
        shots = [shot for scene in recipe["scenes"] for shot in scene["shots"]]
        self.assertEqual([shot["title"] for shot in shots], ["进门", "工位", "开会"])
        self.assertEqual(recipe["agentStatus"][3]["status"], "completed")

        parsed = parse_json_object(json.dumps({"data": {"shots": shots_payload}}, ensure_ascii=False))
        self.assertIsNotNone(parsed)
        wrapped = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟赶到公司开会。"}},
            goal="都市程序员短剧",
            chat_fn=lambda _messages: json.dumps({"result": {"scenes": [{"title": "公司", "shots": shots_payload}]}}, ensure_ascii=False),
        )
        self.assertEqual(len([shot for scene in wrapped["scenes"] for shot in scene["shots"]]), 3)

    def test_storyboard_parses_prose_shot_blocks(self) -> None:
        from backend.app.director_agents import run_agent

        def chat(_messages: list[dict]) -> str:
            return (
                "[Shot 1] Live-action, a programmer pushes open a glass office door.\n"
                "[Shot 2] He sits at dual monitors and types quickly.\n"
                "[Shot 3] Colleagues gather around the meeting table."
            )

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟赶到公司开会。"}},
            goal="都市程序员短剧",
            chat_fn=chat,
        )
        shots = [shot for scene in recipe["scenes"] for shot in scene["shots"]]
        self.assertEqual(len(shots), 3)
        self.assertEqual(recipe["agentStatus"][3]["status"], "completed")
        self.assertTrue(all(shot["title"] != "主镜头" for shot in shots))

    def test_chat_text_does_not_retry_timeout(self) -> None:
        from backend.app.director_agents import _chat_text
        from backend.app.llm_client import LlmTemporaryError

        calls = {"n": 0}

        def chat(_messages: list[dict]) -> str:
            calls["n"] += 1
            raise LlmTemporaryError("请求大模型服务超时（等待 300 秒仍无响应）。模型可能仍在生成或首次装入显存，请稍后重试。")

        with self.assertRaises(LlmTemporaryError):
            _chat_text(chat, [{"role": "user", "content": "x"}])
        self.assertEqual(calls["n"], 1)

    def test_chat_text_retries_connection_error(self) -> None:
        from backend.app.director_agents import _chat_text
        from backend.app.llm_client import LlmTemporaryError

        calls = {"n": 0}

        def chat(_messages: list[dict]) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise LlmTemporaryError("无法连接大模型服务 http://127.0.0.1:11434/v1")
            return "ok"

        self.assertEqual(_chat_text(chat, [{"role": "user", "content": "x"}]), "ok")
        self.assertEqual(calls["n"], 2)

    def test_pipeline_continues_to_storyboard_when_local_script_step_fails(self) -> None:
        from backend.app.director_agents import run_recipe_pipeline

        def chat(messages: list[dict]) -> str:
            system = messages[0]["content"]
            if "AGENT_ID: script" in system:
                raise ValueError("本地解析失败")
            return json.dumps({
                "shots": [
                    {"title": "进门", "description": "推开门", "promptText": "He opens the door."},
                    {"title": "工位", "description": "坐下", "promptText": "He sits down."},
                ],
            }, ensure_ascii=False)

        recipe = run_recipe_pipeline(
            {},
            goal="都市程序员短剧",
            chat_fn=chat,
            skip_research=True,
            agents=["script", "storyboard"],
        )
        statuses = {item["id"]: item["status"] for item in recipe["agentStatus"]}
        self.assertEqual(statuses["script"], "failed")
        self.assertEqual(statuses["storyboard"], "completed")
        shots = [shot for scene in recipe["scenes"] for shot in scene["shots"]]
        self.assertEqual(len(shots), 2)

    def test_pipeline_persists_failed_state_then_rethrows_llm_error(self) -> None:
        from backend.app.director_agents import run_recipe_pipeline
        from backend.app.llm_client import LlmError

        snapshots: list[dict] = []

        with self.assertRaises(LlmError):
            run_recipe_pipeline(
                {},
                goal="都市程序员短剧",
                chat_fn=lambda _messages: (_ for _ in ()).throw(LlmError("上游对话失败")),
                skip_research=True,
                agents=["script", "storyboard"],
                on_progress=lambda recipe: snapshots.append(deepcopy(recipe)),
            )

        self.assertTrue(snapshots)
        latest = snapshots[-1]
        script = next(item for item in latest["agentStatus"] if item["id"] == "script")
        self.assertEqual(script["status"], "failed")
        self.assertEqual(script["error"], "上游对话失败")
        self.assertFalse(latest["pipelineRun"]["active"])

    def test_pipeline_raises_billing_error_with_upstream_log(self) -> None:
        from backend.app.director_agents import run_recipe_pipeline
        from backend.app.llm_client import LlmBillingError

        snapshots: list[dict] = []

        def chat(_messages: list[dict]) -> str:
            raise LlmBillingError(
                "大模型上游余额不足或欠费（HTTP 403），请到供应商控制台充值后再试。"
                "上游返回：account balance is insufficient"
            )

        def on_progress(recipe: dict) -> None:
            snapshots.append(recipe)

        with self.assertRaises(LlmBillingError) as ctx:
            run_recipe_pipeline(
                {},
                goal="都市程序员短剧",
                chat_fn=chat,
                skip_research=True,
                agents=["script", "storyboard"],
                on_progress=on_progress,
            )
        self.assertIn("余额不足", str(ctx.exception))
        self.assertIn("account balance is insufficient", str(ctx.exception))
        script = next(item for item in snapshots[-1]["agentStatus"] if item["id"] == "script")
        self.assertEqual(script["status"], "failed")
        self.assertIn("余额不足", script["error"] or "")

    def test_pipeline_emits_running_status_before_llm(self) -> None:
        from backend.app.director_agents import run_recipe_pipeline

        snapshots: list[str] = []

        def chat(messages: list[dict]) -> str:
            system = messages[0]["content"]
            if "AGENT_ID: script" in system:
                self.assertIn("running", snapshots)
                return '{"title": "雨夜", "summary": "侦探", "fullStory": "侦探走进雨巷。"}'
            return "{}"

        def on_progress(recipe: dict) -> None:
            status = next(item["status"] for item in recipe["agentStatus"] if item["id"] == "script")
            snapshots.append(status)

        recipe = run_recipe_pipeline(
            {},
            goal="雨夜里侦探穿过暗巷。",
            chat_fn=chat,
            skip_research=True,
            agents=["research", "script"],
            on_progress=on_progress,
        )
        self.assertEqual(recipe["agentStatus"][1]["status"], "completed")
        self.assertGreaterEqual(snapshots.count("running"), 1)
        self.assertEqual(snapshots[-1], "completed")

    def test_pipeline_subset_tracks_active_run_and_stage_messages(self) -> None:
        from copy import deepcopy
        from backend.app.director_agents import run_recipe_pipeline

        snapshots: list[dict] = []

        def chat(messages: list[dict]) -> str:
            system = messages[0]["content"]
            if "AGENT_ID: script" in system:
                return '{"title": "都市", "summary": "程序员", "fullStory": "李明走进公司。他坐下写代码。"}'
            return json.dumps({
                "shots": [
                    {"title": "进门", "description": "推开门", "promptText": "He opens the door."},
                    {"title": "工位", "description": "坐下", "promptText": "He sits down."},
                ],
            }, ensure_ascii=False)

        def on_progress(recipe: dict) -> None:
            snapshots.append(deepcopy(recipe))

        recipe = run_recipe_pipeline(
            {},
            goal="都市程序员短剧",
            chat_fn=chat,
            skip_research=True,
            agents=["script", "storyboard"],
            on_progress=on_progress,
        )
        self.assertEqual(recipe["pipelineRun"]["agents"], ["script", "storyboard"])
        self.assertFalse(recipe["pipelineRun"]["active"])
        self.assertEqual(recipe["agentStatus"][3]["message"], "已写出 2 个镜头")
        active = [item for item in snapshots if (item.get("pipelineRun") or {}).get("active")]
        self.assertTrue(active)
        self.assertEqual(active[0]["pipelineRun"]["agents"], ["script", "storyboard"])
        storyboard_messages = [
            next(item["message"] for item in snap["agentStatus"] if item["id"] == "storyboard")
            for snap in snapshots
            if next(item["status"] for item in snap["agentStatus"] if item["id"] == "storyboard") == "running"
        ]
        self.assertIn("正在读剧本", storyboard_messages)
        self.assertIn("正在整理镜头", storyboard_messages)

    def test_storyboard_reports_streamed_character_count(self) -> None:
        from backend.app.director_agents import DirectorChatFn, run_agent

        class FakeClient:
            def chat_completion(self, _messages, **kwargs):
                body = json.dumps({
                    "shots": [
                        {"title": "进门", "description": "推开门", "promptText": "He opens the door."},
                        {"title": "工位", "description": "坐下", "promptText": "He sits down."},
                    ],
                }, ensure_ascii=False)
                on_chunk = kwargs.get("on_chunk")
                if on_chunk:
                    on_chunk(body[:8])
                    on_chunk(body)
                return body

        snapshots: list[str] = []

        def on_progress(recipe: dict) -> None:
            status = next(item for item in recipe["agentStatus"] if item["id"] == "storyboard")
            if status.get("message"):
                snapshots.append(status["message"])

        recipe = run_agent(
            "storyboard",
            {"kind": "director_recipe", "script": {"title": "都市程序员", "fullStory": "林舟赶到公司开会。"}},
            goal="都市程序员短剧",
            chat_fn=DirectorChatFn(FakeClient(), "demo-model"),
            on_progress=on_progress,
        )
        self.assertTrue(any(item.startswith("正在写分镜（已收到 ") for item in snapshots))
        self.assertEqual(len([shot for scene in recipe["scenes"] for shot in scene["shots"]]), 2)

    def test_recipe_r2v_packs_at_most_nine_references(self) -> None:
        from backend.app.director_compiler import recipe_assets_as_slots, resolve_recipe_shot_submission

        characters = [
            {"name": f"角色{index}", "promptText": "look", "imageUrl": f"/api/jobs/img{index}/outputs/0/download"}
            for index in range(1, 12)
        ]
        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "artStyle": {"id": "as_1001"},
            "characters": characters,
            "locations": [{"name": "大厅", "promptText": "empty hall", "imageUrl": "/api/jobs/loc/outputs/0/download"}],
            "scenes": [{
                "shots": [{
                    "title": "群像",
                    "description": "众人入场",
                    "characterNames": [f"角色{index}" for index in range(1, 12)],
                    "locationName": "大厅",
                    "durationSec": 5,
                }],
            }],
        })
        shot = recipe["scenes"][0]["shots"][0]
        slots = recipe_assets_as_slots(recipe, shot)
        self.assertEqual(len(slots), 9)
        submission = resolve_recipe_shot_submission(recipe, shot)
        self.assertEqual(submission["workflowId"], "minimax-h3-r2v")
        self.assertEqual(len(submission["plan"]["items"]), 9)
        self.assertIn("<Picture 1>", submission["prompt"])
        self.assertIn("<Picture 9>", submission["prompt"])
        self.assertNotIn("<Picture 10>", submission["prompt"])
        self.assertIn("epic cinematic", submission["prompt"])


class DirectorDualEngineApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_director_dual.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        self.enqueued: list[str] = []

        class WorkerStub:
            def __init__(self, outer) -> None:
                self.outer = outer

            async def enqueue(self, job_id: str) -> None:
                self.outer.enqueued.append(job_id)

        app.state.worker = WorkerStub(self)
        self._original_grs_provider = getattr(app.state, "grs_provider", None)
        self.user = self.auth_store.create_user(
            "director_dual", "双引擎", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, self.csrf = self.auth_store.create_session(self.user["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
        if hasattr(self, "_original_grs_provider"):
            app.state.grs_provider = self._original_grs_provider
        self.temp_dir.cleanup()

    def _headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(self.token)}

    def test_recipes_run_and_render_shots_enqueue_t2v(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        from backend.app.director_recipe import empty_recipe_payload

        def fake_run(recipe, *, goal, art_style_id=None, agents=None, skip_research=None, on_progress=None):
            payload = normalize_recipe_payload(recipe or empty_recipe_payload())
            payload["script"] = {"title": "雨夜", "summary": "侦探", "fullStory": goal}
            payload["artStyle"] = {
                "id": "as_1001",
                "name": "史诗叙事电影",
                "name_en": "Epic Narrative Cinema",
                "promptPrefix": "epic cinematic scene, dramatic lighting, rich atmosphere, film-grade composition, emotional visual storytelling",
            }
            payload["scenes"] = [{
                "title": "巷口",
                "locationName": "暗巷",
                "shots": [{
                    "title": "跟踪",
                    "description": "走进雨巷",
                    "dialogue": "别动。",
                    "characterNames": [],
                    "durationSec": 5,
                    "status": "idle",
                }],
            }]
            if on_progress:
                on_progress(payload)
            return payload

        with patch.object(self.llm_provider, "run_director_recipe", side_effect=fake_run):
            response = self.client.post(
                "/api/director/recipes/run",
                headers=self._headers(),
                json={"goal": "雨夜里侦探穿过暗巷。", "skip_research": True},
            )
        self.assertEqual(response.status_code, 200, response.text)
        project = response.json()
        self.assertEqual(project["kind"], "director_recipe")
        self.assertEqual(project["payload"]["script"]["title"], "雨夜")
        shot_id = project["payload"]["scenes"][0]["shots"][0]["id"]
        missing = self.client.post(
            f"/api/director/recipes/{project['id']}/render-shots",
            headers=self._headers(),
            json={"shot_ids": ["missing-shot"], "render_pass": "final"},
        )
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertIn("没有找到", missing.json()["detail"])

        def polish_after_queue(draft, mode):
            current = self.job_store.get_director_project(project["id"])
            queued = current["payload"]["scenes"][0]["shots"][0]
            self.assertEqual(queued.get("status"), "queued")
            self.assertFalse(queued.get("jobId"))
            return draft

        with patch.object(self.llm_provider, "polish_director_h3_prompt", side_effect=polish_after_queue) as polish:
            rendered = self.client.post(
                f"/api/director/recipes/{project['id']}/render-shots",
                headers=self._headers(),
                json={"shot_ids": [shot_id], "render_pass": "final"},
            )
        polish.assert_called_once_with(ANY, "T2VA")
        self.assertEqual(rendered.status_code, 200, rendered.text)
        body = rendered.json()
        job_id = body["payload"]["scenes"][0]["shots"][0]["jobId"]
        self.assertTrue(job_id)
        self.assertIn(job_id, self.enqueued)
        job = self.job_store.get(job_id)
        self.assertEqual(job["mode"], "minimax-h3-t2v")
        self.assertIn("epic cinematic", job["prompt"])

        with patch.object(self.llm_provider, "polish_director_h3_prompt", side_effect=lambda draft, mode: draft):
            previewed = self.client.post(
                f"/api/director/recipes/{project['id']}/render-shots",
                headers=self._headers(),
                json={"shot_ids": [shot_id], "render_pass": "preview"},
            )
        self.assertEqual(previewed.status_code, 200, previewed.text)
        preview_shot = previewed.json()["payload"]["scenes"][0]["shots"][0]
        preview_job = self.job_store.get(preview_shot["jobId"])
        self.assertEqual(preview_job["options"]["quality"], "0.4")
        self.assertEqual(preview_job["options"]["speed"], "fast")
        self.assertEqual(preview_shot["takes"][-1]["renderPass"], "preview")

    def test_recipes_run_accepts_script_and_storyboard_subset(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        from backend.app.director_recipe import empty_recipe_payload

        captured: dict[str, object] = {}

        def fake_run(recipe, *, goal, art_style_id=None, agents=None, skip_research=None, on_progress=None):
            captured["agents"] = agents
            payload = normalize_recipe_payload(recipe or empty_recipe_payload())
            payload["script"] = {"title": "都市程序员", "summary": "加班", "fullStory": "林舟连夜改代码。"}
            payload["scenes"] = [{
                "title": "公司",
                "shots": [
                    {"title": "进门", "description": "推开玻璃门", "durationSec": 5, "status": "idle"},
                    {"title": "工位", "description": "打开终端", "durationSec": 6, "status": "idle"},
                ],
            }]
            if on_progress:
                on_progress(payload)
            return payload

        with patch.object(self.llm_provider, "run_director_recipe", side_effect=fake_run):
            response = self.client.post(
                "/api/director/recipes/run",
                headers=self._headers(),
                json={
                    "goal": "生成一份都市类型程序员职业的 AI 短剧剧本",
                    "skip_research": True,
                    "agents": ["script", "storyboard"],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(captured["agents"], ["script", "storyboard"])
        shots = response.json()["payload"]["scenes"][0]["shots"]
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0]["title"], "进门")

        from backend.app.llm_client import LlmBillingError

        def fake_billing(*_args, **_kwargs):
            raise LlmBillingError(
                "大模型上游余额不足或欠费（HTTP 403），请到供应商控制台充值后再试。"
                "上游返回：account balance is insufficient"
            )

        with patch.object(self.llm_provider, "run_director_recipe", side_effect=fake_billing):
            billed = self.client.post(
                "/api/director/recipes/run",
                headers=self._headers(),
                json={"goal": "测试余额", "skip_research": True, "agents": ["storyboard"]},
            )
        self.assertEqual(billed.status_code, 502, billed.text)
        self.assertIn("余额不足", billed.json()["detail"])
        self.assertIn("account balance is insufficient", billed.json()["detail"])

        bad = self.client.post(
            "/api/director/recipes/run",
            headers=self._headers(),
            json={"goal": "测试", "agents": ["not-an-agent"]},
        )
        self.assertEqual(bad.status_code, 422)

    def test_durable_operation_create_read_cancel_and_exclusive_guard(self) -> None:
        from backend.app.director_recipe import empty_recipe_payload

        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "持久化操作", "payload": empty_recipe_payload(title="持久化操作")},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]
        started: list[str] = []

        class OperationStarterStub:
            @staticmethod
            def start(operation_id: str) -> None:
                started.append(operation_id)

        original = getattr(app.state, "director_operations", None)
        app.state.director_operations = OperationStarterStub()
        try:
            response = self.client.post(
                f"/api/director/recipes/{project_id}/operations",
                headers=self._headers(),
                json={"kind": "shot_render_prepare", "shot_ids": ["shot-1"], "render_pass": "preview"},
            )
            self.assertEqual(response.status_code, 202, response.text)
            operation = response.json()
            self.assertEqual(operation["status"], "queued")
            self.assertEqual(started, [operation["id"]])
            self.assertNotIn("owner_user_id", operation)

            duplicate = self.client.post(
                f"/api/director/recipes/{project_id}/operations",
                headers=self._headers(),
                json={"kind": "shot_render_prepare"},
            )
            self.assertEqual(duplicate.status_code, 409, duplicate.text)

            fetched = self.client.get(f"/api/director/operations/{operation['id']}")
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertEqual(fetched.json()["request"]["shot_ids"], ["shot-1"])

            cancelled = self.client.post(
                f"/api/director/operations/{operation['id']}/cancel",
                headers=self._headers(),
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertTrue(cancelled.json()["cancel_requested"])
        finally:
            if original is None:
                delattr(app.state, "director_operations")
            else:
                app.state.director_operations = original

    def test_render_shots_with_first_frame_enqueues_i2v(self) -> None:
        from backend.app.director_recipe import empty_recipe_payload

        frame = Path(self.temp_dir.name) / "first.png"
        frame.write_bytes(b"\x89PNG\r\n\x1a\n" + b"frame")
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "首帧工程",
                "payload": {
                    **empty_recipe_payload(title="首帧工程"),
                    "artStyle": {"id": "as_1001"},
                    "scenes": [{"shots": [{
                        "id": "shot-i2v",
                        "title": "开场",
                        "description": "走进雨巷",
                        "durationSec": 5,
                        "firstFramePath": str(frame),
                        "firstFrameUrl": "/api/director/recipes/x/frames/shot-i2v/first",
                    }]}],
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]
        rendered = self.client.post(
            f"/api/director/recipes/{project_id}/render-shots",
            headers=self._headers(),
            json={"shot_ids": ["shot-i2v"], "render_pass": "preview"},
        )
        self.assertEqual(rendered.status_code, 200, rendered.text)
        shot = rendered.json()["payload"]["scenes"][0]["shots"][0]
        job = self.job_store.get(shot["jobId"], include_references=True)
        self.assertEqual(job["mode"], "minimax-h3-i2v")
        self.assertEqual(job["options"]["quality"], "0.4")
        self.assertEqual(job.get("reference_count"), 1)

    def test_generate_stills_enqueues_image_job(self) -> None:
        from backend.app.director_recipe import empty_recipe_payload
        from backend.app.models import JobMode

        class FakeGrs:
            def availability(self, mode=None):
                return True, None

            def enabled_image_workflows(self):
                return [{"id": JobMode.GRS_GPT_IMAGE_2.value}]

        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={
                "title": "静帧工程",
                "payload": {
                    **empty_recipe_payload(title="静帧工程"),
                    "artStyle": {"id": "as_1001"},
                    "scenes": [{"shots": [{
                        "id": "shot-still",
                        "title": "开场",
                        "description": "走进雨巷",
                        "promptText": "detective walks into a rainy alley",
                    }]}],
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]
        app.state.grs_provider = FakeGrs()
        stills = self.client.post(
            f"/api/director/recipes/{project_id}/generate-stills",
            headers=self._headers(),
            json={"shot_ids": ["shot-still"], "force": True},
        )
        self.assertEqual(stills.status_code, 200, stills.text)
        shot = stills.json()["payload"]["scenes"][0]["shots"][0]
        self.assertTrue(shot["stillJobId"])
        self.assertIn(shot["stillJobId"], self.enqueued)
        job = self.job_store.get(shot["stillJobId"])
        self.assertEqual(job["mode"], JobMode.GRS_GPT_IMAGE_2.value)
        self.assertIn("still frame", job["prompt"])
        self.assertIn("detective walks", job["prompt"])

    def test_batches_enqueue_two_t2v_jobs(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        with patch.object(self.llm_provider, "fission_batch_scripts", return_value=[
            {"title": "版本甲", "script": "清晨城市晨跑"},
            {"title": "版本乙", "script": "夜晚霓虹骑行"},
        ]):
            response = self.client.post(
                "/api/director/batches",
                headers=self._headers(),
                json={"theme": "运动活力", "count": 2, "aspect_ratio": "9:16", "duration_sec": 8, "art_style_id": "as_1001"},
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["kind"], "batch_run")
        self.assertEqual(len(body["payload"]["items"]), 2)
        self.assertEqual(len(self.enqueued), 2)
        for item in body["payload"]["items"]:
            self.assertTrue(item["jobId"])
            job = self.job_store.get(item["jobId"])
            self.assertEqual(job["mode"], "minimax-h3-t2v")
            self.assertEqual(job["options"]["duration"], 8)
            self.assertEqual(job["options"]["aspect_ratio"], "9:16")
        self.assertEqual(body["payload"]["videoWorkflowFamily"], "official_h3")

    def test_batches_enqueue_selected_workflow_family(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        with patch.object(self.llm_provider, "fission_batch_scripts", return_value=[
            {"title": "版本甲", "script": "清晨城市晨跑"},
        ]):
            response = self.client.post(
                "/api/director/batches",
                headers=self._headers(),
                json={
                    "theme": "运动活力",
                    "count": 1,
                    "aspect_ratio": "9:16",
                    "duration_sec": 8,
                    "video_workflow_family": "lightx2v",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["payload"]["videoWorkflowFamily"], "lightx2v")
        job = self.job_store.get(body["payload"]["items"][0]["jobId"])
        self.assertEqual(job["mode"], "minimax-h3-lightx2v-t2v")

    def test_batch_render_retries_only_requested_item(self) -> None:
        self.llm_provider.update({
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-dummy",
        })
        with patch.object(self.llm_provider, "fission_batch_scripts", return_value=[
            {"title": "版本甲", "script": "清晨城市晨跑"},
            {"title": "版本乙", "script": "夜晚霓虹骑行"},
        ]):
            created = self.client.post(
                "/api/director/batches",
                headers=self._headers(),
                json={"theme": "运动活力", "count": 2, "aspect_ratio": "9:16", "duration_sec": 8},
            )
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()
        first = project["payload"]["items"][0]
        first_job = first["jobId"]
        retry = self.client.post(
            f"/api/director/batches/{project['id']}/render",
            headers=self._headers(),
            json={"item_ids": [first["id"]]},
        )
        self.assertEqual(retry.status_code, 200, retry.text)
        retried = retry.json()["payload"]["items"]
        self.assertEqual(len(self.enqueued), 3)
        self.assertNotEqual(retried[0]["jobId"], first_job)
        self.assertEqual(retried[1]["jobId"], project["payload"]["items"][1]["jobId"])
        self.assertEqual(retried[0]["status"], "queued")
        self.assertIsNone(retried[0].get("error"))


class DirectorAssetCloudTests(unittest.TestCase):
    def test_job_asset_image_url_prefers_cloud_url(self) -> None:
        from backend.app.director_jobs import job_asset_image_url, job_public_output_url

        job = {
            "id": "j1",
            "outputs": [{
                "kind": "image",
                "path": "studio/a.png",
                "delivery_status": "cloud",
                "cloud_url": "https://media.example.com/studio/a.png",
            }],
        }
        self.assertEqual(job_asset_image_url(job), "https://media.example.com/studio/a.png")
        self.assertEqual(job_public_output_url(job, kind="image"), "/api/jobs/j1/outputs/0/download")

        class Storage:
            def object_url(self, key: str) -> str:
                return f"https://media.example.com/{key}"

        derived = {
            "id": "j2",
            "outputs": [{"kind": "image", "path": "studio/b.png", "delivery_status": "cloud"}],
        }
        self.assertEqual(
            job_asset_image_url(derived, resource_storage=Storage()),
            "https://media.example.com/studio/b.png",
        )

    def test_bind_writes_qiniu_url_onto_matching_recipe_assets(self) -> None:
        from backend.app.director_jobs import bind_director_asset_image

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            recipe = normalize_recipe_payload({
                "kind": PAYLOAD_KIND_RECIPE,
                "artStyle": {"id": "as_1001"},
                "characters": [{"name": "艾达", "promptText": "look", "imageJobId": "job-ada"}],
                "locations": [{"name": "会议室", "promptText": "office", "imageJobId": "job-room"}],
            })
            project = store.create_director_project("user-1", "定妆", payload=recipe)
            bound = bind_director_asset_image(
                store,
                owner_user_id="user-1",
                job_id="job-ada",
                image_url="https://media.example.com/studio/image/ada.png",
            )
            self.assertEqual(bound, 1)
            saved = store.get_director_project(project["id"])
            chars = {item["name"]: item["imageUrl"] for item in saved["payload"]["characters"]}
            locs = {item["name"]: item["imageUrl"] for item in saved["payload"]["locations"]}
            self.assertEqual(chars["艾达"], "https://media.example.com/studio/image/ada.png")
            self.assertIsNone(locs["会议室"])

    def test_bind_writes_still_url_onto_matching_recipe_shot(self) -> None:
        from backend.app.director_jobs import bind_director_asset_image

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            recipe = normalize_recipe_payload({
                "kind": PAYLOAD_KIND_RECIPE,
                "artStyle": {"id": "as_1001"},
                "scenes": [{"shots": [{
                    "id": "shot-still",
                    "title": "静帧",
                    "stillJobId": "job-still",
                }]}],
            })
            project = store.create_director_project("user-1", "静帧", payload=recipe)
            bound = bind_director_asset_image(
                store,
                owner_user_id="user-1",
                job_id="job-still",
                image_url="https://media.example.com/studio/image/still.png",
            )
            self.assertEqual(bound, 1)
            saved = store.get_director_project(project["id"])
            shot = saved["payload"]["scenes"][0]["shots"][0]
            self.assertEqual(shot["stillUrl"], "https://media.example.com/studio/image/still.png")
            self.assertEqual(shot["stillStatus"], "succeeded")

    def test_materialize_downloads_cloud_object_when_local_file_missing(self) -> None:
        from backend.app import director_jobs as director_jobs_module
        from backend.app.director_jobs import materialize_job_output_file

        class Storage:
            def download_url(self, key: str, expires_in_seconds: int = 300) -> str:
                return "https://signed.example.com/studio/a.png?e=1"

        job = {
            "id": "cloud-plate",
            "outputs": [{"kind": "image", "path": "studio/a.png", "delivery_status": "cloud"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_settings = type("Settings", (), {"staging_dir": root, "results_dir": root / "results"})()
            with patch.object(director_jobs_module, "settings", fake_settings):
                with patch("backend.app.director_jobs.urllib.request.urlopen") as urlopen:
                    response = MagicMock()
                    response.read.return_value = b"png-bytes"
                    response.__enter__.return_value = response
                    response.__exit__.return_value = False
                    urlopen.return_value = response
                    path = materialize_job_output_file(job, resource_storage=Storage(), kind="image")
            self.assertIsNotNone(path)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"png-bytes")


class DirectorLibraryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_director_library.db"
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        self.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = self.llm_provider
        self.user = self.auth_store.create_user(
            "lib_owner", "资产员工", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.other = self.auth_store.create_user(
            "lib_other", "另一员工", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, self.csrf = self.auth_store.create_session(self.user["id"])
        self.other_token, self.other_csrf = self.auth_store.create_session(self.other["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(token or self.token)}

    def _recipe_payload(self) -> dict:
        from backend.app.director_recipe import empty_recipe_payload

        recipe = empty_recipe_payload(title="雨夜")
        recipe["characters"] = [{
            "name": "艾达",
            "description": "女侦探",
            "promptText": "a woman detective",
            "type": "character",
            "imageUrl": "https://media.example.com/ada.png",
            "imageJobId": "job-ada",
        }, {
            "name": "怀表",
            "description": "金色怀表",
            "promptText": "golden pocket watch",
            "type": "object",
        }]
        recipe["locations"] = [{
            "name": "雨巷",
            "description": "夜晚巷口",
            "promptText": "rainy alley at night",
        }]
        return recipe

    def test_crud_is_owner_scoped_and_inserts_into_recipe(self) -> None:
        created = self.client.post(
            "/api/director/library-assets",
            headers=self._headers(),
            json={"kind": "character", "name": "艾达", "description": "女侦探", "promptText": "detective"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        asset = created.json()
        self.assertEqual(asset["kind"], "character")
        self.assertEqual(asset["name"], "艾达")
        self.assertTrue(asset["id"].startswith("lib-"))

        listed = self.client.get("/api/director/library-assets")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        other_client = TestClient(app)
        other_client.cookies.set("zly_ai_video_studio_session", self.other_token)
        other_list = other_client.get("/api/director/library-assets")
        self.assertEqual(other_list.status_code, 200)
        self.assertEqual(other_list.json(), [])
        other_get = other_client.get(f"/api/director/library-assets/{asset['id']}/image")
        self.assertEqual(other_get.status_code, 404)
        other_delete = other_client.delete(
            f"/api/director/library-assets/{asset['id']}",
            headers=self._headers(self.other_token),
        )
        self.assertEqual(other_delete.status_code, 404)

        project = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "雨夜", "payload": self._recipe_payload()},
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["id"]

        saved = self.client.post(
            "/api/director/library-assets/from-recipe",
            headers=self._headers(),
            json={"project_id": project_id},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["imported"], 3)
        kinds = {item["kind"] for item in body["assets"]}
        self.assertEqual(kinds, {"character", "scene", "prop"})
        prop = next(item for item in body["assets"] if item["kind"] == "prop")
        self.assertEqual(prop["name"], "怀表")
        scene = next(item for item in body["assets"] if item["kind"] == "scene")
        self.assertEqual(scene["name"], "雨巷")

        empty = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "新工程", "payload": {"kind": "director_recipe"}},
        )
        self.assertEqual(empty.status_code, 201, empty.text)
        inserted = self.client.post(
            f"/api/director/recipes/{empty.json()['id']}/insert-library-assets",
            headers=self._headers(),
            json={"asset_ids": [item["id"] for item in body["assets"]]},
        )
        self.assertEqual(inserted.status_code, 200, inserted.text)
        payload = inserted.json()["payload"]
        self.assertEqual(len(payload["characters"]), 2)
        self.assertEqual(len(payload["locations"]), 1)
        names = {item["name"] for item in payload["characters"]}
        self.assertEqual(names, {"艾达", "怀表"})
        watch = next(item for item in payload["characters"] if item["name"] == "怀表")
        self.assertEqual(watch["type"], "object")
        self.assertEqual(watch["libraryAssetId"], prop["id"])
        self.assertEqual(payload["locations"][0]["libraryAssetId"], scene["id"])

        deleted = self.client.delete(
            f"/api/director/library-assets/{asset['id']}",
            headers=self._headers(),
        )
        self.assertEqual(deleted.status_code, 204)
        after = self.client.get("/api/director/library-assets")
        self.assertEqual(len(after.json()), 3)

    def test_upload_image_and_plate_path_uses_library_file(self) -> None:
        from backend.app.director_jobs import _plate_file_for_slot
        from backend.app import director_library as library_module

        uploads = Path(self.temp_dir.name) / "uploads"
        uploads.mkdir()
        created = self.client.post(
            "/api/director/library-assets",
            headers=self._headers(),
            json={"kind": "scene", "name": "雨巷", "promptText": "rainy alley"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        asset_id = created.json()["id"]
        with patch.object(library_module, "settings") as fake_settings:
            fake_settings.uploads_dir = uploads
            uploaded = self.client.post(
                f"/api/director/library-assets/{asset_id}/image",
                headers=self._headers(),
                files={"file": ("alley.png", b"\x89PNG\r\n\x1a\n" + b"alley", "image/png")},
            )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["imageUrl"], f"/api/director/library-assets/{asset_id}/image")
        row = self.job_store.get_director_library_asset(asset_id)
        self.assertTrue(Path(row["image_path"]).is_file())
        slot = {"libraryAssetId": asset_id, "imageJobId": None}
        path = _plate_file_for_slot(self.job_store, slot)
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())

    def test_does_not_create_series_or_episode_tree(self) -> None:
        created = self.client.post(
            "/api/director/library-assets",
            headers=self._headers(),
            json={"kind": "character", "name": "艾达"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        asset = created.json()
        self.assertNotIn("seriesId", asset)
        self.assertNotIn("episodeId", asset)
        self.assertNotIn("seasonId", asset)


class DirectorAvExportTests(unittest.TestCase):
    def setUp(self) -> None:
        import subprocess

        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_director_av.db"
        self.audio_dir = Path(self.temp_dir.name) / "audio"
        self.mux_dir = Path(self.temp_dir.name) / "mux"
        self.audio_dir.mkdir()
        self.mux_dir.mkdir()
        self.credential_key = Fernet.generate_key().decode("ascii")
        self.auth_store = AuthStore(self.db_path)
        self.job_store = JobStore(self.db_path)
        from backend.app.tts_provider import TtsProviderService
        self.tts_provider = TtsProviderService(self.job_store, self.credential_key)
        app.state.auth_store = self.auth_store
        app.state.store = self.job_store
        app.state.llm_provider = LlmProviderService(self.job_store, self.credential_key)
        app.state.tts_provider = self.tts_provider
        self.user = self.auth_store.create_user(
            "director_av", "成片", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, self.csrf = self.auth_store.create_session(self.user["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)
        self._patches = [
            patch("backend.app.director_export.recipe_audio_dir", lambda *_a, **_k: self.audio_dir),
            patch("backend.app.director_export.recipe_mux_dir", lambda *_a, **_k: self.mux_dir),
        ]
        for item in self._patches:
            item.start()

        class FakeFfmpeg:
            def __init__(self, duration: float) -> None:
                self.duration = duration
                self.commands: list[list[str]] = []

            def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
                self.commands.append(list(args))
                dest = Path(args[-1])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"fake-mp4-bytes")
                return subprocess.CompletedProcess(["ffmpeg", *args], 0, "", "")

            def probe_duration(self, path: Path) -> float:
                return self.duration

        self.FakeFfmpeg = FakeFfmpeg
        self._subprocess = subprocess

    def tearDown(self) -> None:
        for item in reversed(self._patches):
            item.stop()
        app.state.ffmpeg_runner = None
        self.temp_dir.cleanup()

    def _headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(self.token)}

    def _create_recipe_project(self, shots: list[dict]) -> str:
        recipe = normalize_recipe_payload({
            "kind": PAYLOAD_KIND_RECIPE,
            "script": {"title": "雨夜成片", "summary": "侦探", "fullStory": "雨巷"},
            "artStyle": {"id": "as_1001"},
            "characters": [{"name": "阿凯", "gender": "male", "promptText": "detective"}],
            "scenes": [{"title": "巷口", "shots": shots}],
        })
        created = self.client.post(
            "/api/director/projects",
            headers=self._headers(),
            json={"title": "雨夜成片", "payload": recipe},
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["id"]

    def _succeed_video_job(self, job_id: str, path: Path) -> None:
        from backend.app.models import JobMode, JobStatus
        job = self.job_store.create(
            job_id, JobMode.MINIMAX_H3_T2V, "prompt", "", None, [],
            owner_user_id=self.user["id"],
        )
        item = job["rounds"][0]["generation_items"][0]
        self.job_store.update_generation(item["id"], status=JobStatus.SUCCEEDED, outputs=[{
            "kind": "video",
            "path": str(path),
            "label": "分镜视频",
            "delivery_status": "pending",
        }])

    def test_tts_writes_succeeded_status(self) -> None:
        project_id = self._create_recipe_project([{
            "title": "跟踪",
            "description": "走进雨巷",
            "dialogue": "别动。",
            "durationSec": 5,
            "status": "idle",
        }])
        fetched = self.client.get(f"/api/director/projects/{project_id}")
        shot_id = fetched.json()["payload"]["scenes"][0]["shots"][0]["id"]

        class FakeTts:
            def synthesize(self, text: str, *, voice: str | None = None) -> bytes:
                return f"audio:{voice}:{text}".encode("utf-8")

        app.state.tts_provider = FakeTts()
        response = self.client.post(
            f"/api/director/recipes/{project_id}/tts",
            headers=self._headers(),
            json={"shot_ids": [shot_id]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        shot = response.json()["payload"]["scenes"][0]["shots"][0]
        self.assertEqual(shot["ttsStatus"], "succeeded")
        self.assertTrue(shot["ttsUrl"])
        audio_files = list(self.audio_dir.glob("tts-*.mp3"))
        self.assertEqual(len(audio_files), 1)
        self.assertIn("别动".encode("utf-8"), audio_files[0].read_bytes())

    def test_mux_duration_skips_failed_shots(self) -> None:
        good_a = Path(self.temp_dir.name) / "a.mp4"
        good_b = Path(self.temp_dir.name) / "b.mp4"
        good_a.write_bytes(b"video-a")
        good_b.write_bytes(b"video-b")
        self._succeed_video_job("job-a", good_a)
        self._succeed_video_job("job-b", good_b)
        project_id = self._create_recipe_project([
            {
                "title": "第一镜",
                "dialogue": "走。",
                "durationSec": 5,
                "status": "succeeded",
                "jobId": "job-a",
                "outputVideoUrl": "/api/jobs/job-a/outputs/0/download",
                "approvedTakeId": "take-a",
                "takes": [{"id": "take-a", "jobId": "job-a", "status": "succeeded", "videoUrl": "/api/jobs/job-a/outputs/0/download", "outputPath": str(good_a)}],
            },
            {
                "title": "失败镜",
                "dialogue": "啊。",
                "durationSec": 8,
                "status": "failed",
                "jobId": "job-fail",
                "error": "OOM",
            },
            {
                "title": "第三镜",
                "dialogue": "停。",
                "durationSec": 5,
                "status": "succeeded",
                "jobId": "job-b",
                "outputVideoUrl": "/api/jobs/job-b/outputs/0/download",
                "approvedTakeId": "take-b",
                "takes": [{"id": "take-b", "jobId": "job-b", "status": "succeeded", "videoUrl": "/api/jobs/job-b/outputs/0/download", "outputPath": str(good_b)}],
            },
        ])
        app.state.ffmpeg_runner = self.FakeFfmpeg(duration=10.0)
        muxed = self.client.post(
            f"/api/director/recipes/{project_id}/mux",
            headers=self._headers(),
            json={"burn_subtitles": False},
        )
        self.assertEqual(muxed.status_code, 200, muxed.text)
        export = muxed.json()["payload"]["export"]
        self.assertEqual(export["muxStatus"], "succeeded")
        self.assertEqual(export["muxDurationSec"], 10.0)
        self.assertTrue((self.mux_dir / "film.mp4").is_file())

        xml = self.client.get(f"/api/director/recipes/{project_id}/export.fcpxml")
        self.assertEqual(xml.status_code, 200, xml.text)
        body = xml.text
        self.assertEqual(body.count("<asset-clip ref="), 2)
        self.assertNotIn("失败镜", body)
        self.assertIn("第一镜", body)
        self.assertIn("第三镜", body)

        edl = self.client.get(f"/api/director/recipes/{project_id}/export.edl")
        self.assertEqual(edl.status_code, 200, edl.text)
        self.assertIn("TITLE:", edl.text)
        self.assertIn("FROM CLIP NAME:", edl.text)

    def test_fcpxml_shot_count_matches_muxable_clips(self) -> None:
        from backend.app.director_export import MuxClip, build_fcpxml, timeline_duration_sec
        clip_a = Path(self.temp_dir.name) / "clip-a.mp4"
        clip_b = Path(self.temp_dir.name) / "clip-b.mp4"
        clip_a.write_bytes(b"a")
        clip_b.write_bytes(b"b")
        clips = [
            MuxClip("s1", 1, "开场", "你好", 5, clip_a, start_sec=0),
            MuxClip("s2", 2, "结尾", "再见", 7, clip_b, start_sec=5),
        ]
        xml = build_fcpxml({"fps": 24, "width": 1280, "height": 720}, clips, project_title="测试")
        self.assertEqual(xml.count("<asset-clip ref=\"r"), 2)
        self.assertEqual(timeline_duration_sec(clips), 12.0)


if __name__ == "__main__":
    unittest.main()
