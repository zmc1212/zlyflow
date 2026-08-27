from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    DirectorPayloadError,
    PAYLOAD_KIND_RECIPE,
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
        from backend.app.llm_minimax_skills import load_h3_prompt_writing_guide, load_h3_prompt_writing_skill

        skill = load_h3_prompt_writing_skill()
        base = load_h3_prompt_writing_guide(mode="base")
        ref = load_h3_prompt_writing_guide(mode="ref")
        self.assertIn("name: h3-prompt-writing", skill)
        self.assertIn("integrated_multimodal_description", base)
        self.assertIn("<Picture 1>", base)
        self.assertIn("subject_definitions", ref)
        self.assertIn("<Subject 1>", ref)

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
        self.assertEqual(director_job_options("preview", "native"), {"quality": "0.4", "speed": "fast", "renderPass": "preview"})
        self.assertEqual(director_job_options("final", "native"), {"quality": "1.0", "speed": "balanced", "renderPass": "final"})
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
                return '{"shots":[{"shotNumber":1,"dialogue":"别动。"}]}'
            if "AGENT_ID: music" in system:
                return '{"globalMusic":"low tense noir score","globalSoundscape":"rain and distant traffic"}'
            return "{}"

        recipe = run_recipe_pipeline({}, goal="雨夜里侦探穿过暗巷。", chat_fn=chat, skip_research=True)
        self.assertEqual(recipe["script"]["title"], "雨夜追凶")
        self.assertEqual(recipe["artStyle"]["id"], "as_1005")
        self.assertEqual(recipe["characters"][0]["name"], "阿凯")
        self.assertEqual(recipe["locations"][0]["name"], "暗巷")
        self.assertEqual(recipe["scenes"][0]["shots"][0]["dialogue"], "别动。")
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
        self.user = self.auth_store.create_user(
            "director_dual", "双引擎", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.token, self.csrf = self.auth_store.create_session(self.user["id"])
        self.client = TestClient(app)
        self.client.cookies.set("zly_ai_video_studio_session", self.token)

    def tearDown(self) -> None:
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
        rendered = self.client.post(
            f"/api/director/recipes/{project['id']}/render-shots",
            headers=self._headers(),
            json={"shot_ids": [shot_id], "render_pass": "final"},
        )
        self.assertEqual(rendered.status_code, 200, rendered.text)
        body = rendered.json()
        job_id = body["payload"]["scenes"][0]["shots"][0]["jobId"]
        self.assertTrue(job_id)
        self.assertIn(job_id, self.enqueued)
        job = self.job_store.get(job_id)
        self.assertEqual(job["mode"], "minimax-h3-t2v")
        self.assertIn("epic cinematic", job["prompt"])

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


if __name__ == "__main__":
    unittest.main()

