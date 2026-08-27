from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.llm_client import OpenAICompatibleClient, LlmError
from backend.app.llm_provider import LlmProviderService
from backend.app.main import app
from backend.app.models import UserRole
from backend.app.storage import JobStore


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

    def _project(self, shots: list[dict], *, subjects: int = 0, refs_on: bool = True, override: str | None = None) -> dict:
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
        return {
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
        self.assertIn("(@ref1) is the character", prompt)
        body = prompt.split("\n\n")[-1]
        self.assertNotIn("@ref1", body)
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
        self.assertNotIn("<Picture", i2v_prompt)

        t2v_project = self._project([self._shot(1)], subjects=0, refs_on=False)
        t2v_plan = build_reference_plan(t2v_project, t2v_project["shots"][0])
        self.assertEqual(t2v_plan["workflowId"], "minimax-h3-t2v")
        self.assertEqual(t2v_plan["items"], [])
        t2v_prompt = compile_shot_prompt(t2v_project, t2v_project["shots"][0], t2v_plan)
        self.assertNotIn("<Picture", t2v_prompt)

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
        self.assertIn("[overall_soundscape]", compiled["prompt"])
        self.assertIn("<Picture 2>", compiled["prompt"])

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


if __name__ == "__main__":
    unittest.main()

