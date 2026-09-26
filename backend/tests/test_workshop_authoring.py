"""P1 作者路由与元数据 + P2 完整稿保真与原子采纳。"""
import json
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services import workshop_h3_skill as skill
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.media_studio.services.workshop_h3_skill import writing_author
from backend.tests.test_workshop_h3_skill import body, complete_draft


def _beats():
    return [{"id": "a", "scene": "书房", "speaker": "阿宁", "dialogue": "阿宁：回来。", "video_duration": 8},
            {"id": "b", "scene": "书房", "speaker": "阿南", "dialogue": "阿南：好的。", "video_duration": 8}]


def _group(timecode_mode="cumulative"):
    return {"id": "g1", "beat_ids": ["a", "b"],
            "common_prompt": "人物\n声音设定：\n阿宁 (S1)：自然人声。\n阿南 (S2)：低沉男声。",
            "reference_slots": [], "timecode_mode": timecode_mode}


def _plan(beats, group):
    return {"workflow_id": "minimax-h3-director-accel-t2v", "aspect_ratio": "16:9",
            "groups": [group], "schema_version": 7, "revision": 1,
            "shot_prompts": {}}


class WritingAuthorRouteTests(unittest.TestCase):
    """writing_author 配置解析：默认、profile_id、model 覆盖。"""

    @patch("backend.app.media_studio.services.workshop_h3_skill.llm_row")
    @patch("backend.app.media_studio.services.workshop_h3_skill.credential_manager")
    def test_default_author_uses_llm_row(self, cred, row_fn):
        row_fn.return_value = {"base_url": "https://api.example.com/v1", "model": "test-model",
                               "api_key_encrypted": "enc", "reasoning_effort": "medium"}
        cred.return_value.decrypt.return_value = "sk-test"
        author = writing_author()
        self.assertEqual(author["model"], "test-model")
        self.assertEqual(author["base_url"], "https://api.example.com/v1")
        self.assertEqual(author["reasoning_effort"], "medium")
        self.assertEqual(author["profile_id"], "custom")

    @patch("backend.app.media_studio.services.workshop_h3_skill.query_one")
    @patch("backend.app.media_studio.services.workshop_h3_skill.llm_row")
    @patch("backend.app.media_studio.services.workshop_h3_skill.credential_manager")
    def test_profile_id_overrides_base_row(self, cred, row_fn, query_fn):
        row_fn.return_value = {"base_url": "https://api.default.com/v1", "model": "default-model",
                               "api_key_encrypted": "enc"}
        cred.return_value.decrypt.return_value = "sk-test"
        query_fn.return_value = {"profile_id": "p1", "base_url": "https://api.profile.com/v1",
                                 "model": "profile-model", "reasoning_effort": "high", "api_key_encrypted": "profile-enc"}
        author = writing_author({"profile_id": "p1"})
        self.assertEqual(author["model"], "profile-model")
        self.assertEqual(author["base_url"], "https://api.profile.com/v1")
        self.assertEqual(author["reasoning_effort"], "high")

    @patch("backend.app.media_studio.services.workshop_h3_skill.llm_row")
    @patch("backend.app.media_studio.services.workshop_h3_skill.credential_manager")
    def test_model_override_wins(self, cred, row_fn):
        row_fn.return_value = {"base_url": "https://api.example.com/v1", "model": "base-model",
                               "api_key_encrypted": "enc"}
        cred.return_value.decrypt.return_value = "sk-test"
        author = writing_author({"model": "override-model"})
        self.assertEqual(author["model"], "override-model")

    @patch("backend.app.media_studio.services.workshop_h3_skill.llm_row")
    @patch("backend.app.media_studio.services.workshop_h3_skill.credential_manager")
    def test_incomplete_config_raises(self, cred, row_fn):
        row_fn.return_value = {"base_url": "", "model": "", "api_key_encrypted": None}
        cred.return_value.decrypt.return_value = None
        with self.assertRaisesRegex(ValueError, "配置不完整"):
            writing_author()

    @patch("backend.app.media_studio.services.workshop_h3_skill.query_one")
    @patch("backend.app.media_studio.services.workshop_h3_skill.llm_row")
    @patch("backend.app.media_studio.services.workshop_h3_skill.credential_manager")
    def test_missing_profile_raises(self, cred, row_fn, query_fn):
        row_fn.return_value = {"base_url": "https://api.example.com/v1", "model": "m",
                               "api_key_encrypted": "enc"}
        cred.return_value.decrypt.return_value = "sk-test"
        query_fn.return_value = None
        with self.assertRaisesRegex(ValueError, "供应商配置不存在"):
            writing_author({"profile_id": "nonexistent"})


class AuthorGroupMetaTests(unittest.TestCase):
    """author_group 元数据记录与不静默回退。"""

    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    @patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient")
    def test_meta_records_requested_and_actual_model(self, client_cls, author_fn):
        author_fn.return_value = {
            "profile_id": "p1", "base_url": "https://api.example.com/v1",
            "model": "test-model", "reasoning_effort": "low",
            "api_key": "sk-test", "supports_vision": False,
        }
        client = client_cls.return_value
        def fake_chat(messages, model, **kwargs):
            meta_out = kwargs.get("meta_out")
            if meta_out is not None:
                meta_out.update({"requested_model": model, "provider_request_id": "req-123",
                                 "response_model": "response-model",
                                 "usage": {"total_tokens": 100}, "elapsed_ms": 500, "ok": True})
            return "draft text"
        client.chat_completion = fake_chat
        text, meta = LlmService.author_group("system", "user", [], max_tokens=1000)
        self.assertEqual(meta["requested_model"], "test-model")
        self.assertEqual(meta["actual_model"], "response-model")
        self.assertEqual(meta["mode"], "text")
        self.assertFalse(meta["attach_images"])
        self.assertIsNone(meta["fallback_from"])
        self.assertEqual(meta["request_id"], "req-123")
        self.assertEqual(meta["usage"], {"total_tokens": 100})
        self.assertEqual(meta["elapsed_ms"], 500)

    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    def test_no_vision_no_vlm_fact_extraction_raises(self, author_fn):
        author_fn.return_value = {
            "profile_id": "p1", "base_url": "https://api.example.com/v1",
            "model": "text-only-model", "reasoning_effort": "low",
            "api_key": "sk-test", "supports_vision": False,
        }
        with self.assertRaisesRegex(ValueError, "不支持看图"):
            LlmService.author_group("system", "user", ["https://example.com/img.png"])

    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    @patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient")
    def test_vision_capable_author_attaches_images(self, client_cls, author_fn):
        author_fn.return_value = {
            "profile_id": "p1", "base_url": "https://api.example.com/v1",
            "model": "vision-model", "reasoning_effort": "low",
            "api_key": "sk-test", "supports_vision": True,
        }
        def fake_chat(messages, model, **kwargs):
            self.assertEqual(messages[0]["content"], "system")
            self.assertEqual(messages[1]["content"], [{"type": "text", "text": "user"}] + [
                {"type": "image_url", "image_url": {"url": url}}
                for url in ["https://example.com/first.png", "https://example.com/second.png", "https://example.com/first.png"]])
            meta_out = kwargs.get("meta_out")
            if meta_out is not None:
                meta_out.update({"requested_model": model, "provider_request_id": None,
                                 "usage": None, "elapsed_ms": 100, "ok": True})
            return "draft"
        client_cls.return_value.chat_completion = fake_chat
        text, meta = LlmService.author_group("system", "user", ["https://example.com/first.png", "https://example.com/second.png", "https://example.com/first.png"])
        self.assertEqual(meta["mode"], "vision")
        self.assertTrue(meta["attach_images"])
        self.assertIsNone(meta["actual_model"])

    @patch("backend.app.media_studio.services.workshop_h3_skill.vlm_fact_extraction_author")
    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    @patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient")
    def test_vlm_fact_extraction_mode(self, client_cls, author_fn, vlm_fn):
        author_fn.return_value = {
            "profile_id": "p1", "base_url": "https://api.example.com/v1",
            "model": "text-only-model", "reasoning_effort": "low",
            "api_key": "sk-test", "supports_vision": False,
        }
        vlm_fn.return_value = {
            "profile_id": "vlm", "base_url": "https://api.vlm.com/v1",
            "model": "vlm-model", "reasoning_effort": "none",
            "api_key": "sk-vlm", "supports_vision": True,
        }
        calls = []
        def fake_chat(messages, model, **kwargs):
            calls.append({"messages": messages, "model": model})
            meta_out = kwargs.get("meta_out")
            if meta_out is not None:
                meta_out.update({"requested_model": model, "provider_request_id": None,
                                 "usage": None, "elapsed_ms": 100, "ok": True})
            if len(calls) == 1:
                return "外观事实：人物穿蓝色外套"
            return "draft text"
        client_cls.return_value.chat_completion = fake_chat
        text, meta = LlmService.author_group("system", "user", ["https://example.com/img.png"],
                                             fact_extraction="vlm")
        self.assertEqual(meta["fact_extraction"], "vlm")
        self.assertEqual(meta["fact_extraction_model"], "vlm-model")
        self.assertEqual(text, "draft text")
        # 两次调用：先 VLM 提取外观事实（vlm-model），再作者写稿（text-only-model）。
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["model"], "vlm-model")
        self.assertEqual(calls[1]["model"], "text-only-model")
        self.assertEqual(calls[0]["messages"][1]["content"][1],
                         {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}})
        drafting_user = calls[1]["messages"][1]["content"]
        self.assertIn("外观事实：人物穿蓝色外套", drafting_user)
        self.assertIn("user", drafting_user)

    @patch("backend.app.media_studio.services.workshop_h3_skill.writing_author")
    @patch("backend.app.media_studio.services.llm_service.OpenAICompatibleClient")
    def test_llm_error_propagates_with_model_name(self, client_cls, author_fn):
        author_fn.return_value = {
            "profile_id": "p1", "base_url": "https://api.example.com/v1",
            "model": "test-model", "reasoning_effort": "low",
            "api_key": "sk-test", "supports_vision": False,
        }
        from backend.app.llm_client import LlmError
        def fake_chat(messages, model, **kwargs):
            kwargs["meta_out"].update(response_model="actual-model", provider_request_id="failed-request", elapsed_ms=52)
            raise LlmError("connection refused")
        client_cls.return_value.chat_completion = fake_chat
        with self.assertRaisesRegex(RuntimeError, "test-model.*connection refused") as raised:
            LlmService.author_group("system", "user", [])
        self.assertEqual(raised.exception.author_meta["request_id"], "failed-request")
        self.assertEqual(raised.exception.author_meta["actual_model"], "actual-model")
        self.assertNotIn("api_key", raised.exception.author_meta)


class SplitRoundTripTests(unittest.TestCase):
    """完整稿拆分-合并往返保真。"""

    def test_skill_style_header_round_trip(self):
        """技能风格 【Shot N｜...】 头部正确拆分并保留创作内容。"""
        beats = _beats()
        group = _group("cumulative")
        draft = (
            "subject_definitions（主体定义）:\n<Subject 1> 是 阿宁。\n声音设定：\n阿宁 (S1)：自然人声。\n"
            "detailed_description:\n"
            "【Shot 1｜0\u20138秒｜中景】\n"
            "【主体】阿宁坐在案前。\n"
            "【动作】(0\u20133秒) 阿宁 (S1) 看向门口，说：<d>[中文] 回来。</d>\n(3\u20138秒) 他闭口停住。\n"
            "【镜头】固定中景。\n【音效】呼吸声。\n【约束】一致。\n"
            "【Shot 2｜8\u201316秒｜近景】\n"
            "【主体】阿南站在门口。\n"
            "【动作】(8\u201311秒) 阿南 (S2) 点头，说：<d>[中文] 好的。</d>\n(11\u201316秒) 他转身离开。\n"
            "【镜头】固定近景。\n【音效】脚步声。\n【约束】一致。\n"
        )
        parsed = skill.split_complete_group_draft(draft, beats, group=group)
        self.assertEqual(len(parsed["shots"]), 2)
        self.assertIn("阿宁 (S1) 看向门口", parsed["shots"][0])
        self.assertIn("阿南 (S2) 点头", parsed["shots"][1])
        self.assertIn("<d>[中文] 回来。</d>", parsed["shots"][0])
        self.assertIn("<d>[中文] 好的。</d>", parsed["shots"][1])
        self.assertTrue(parsed["shots"][0].startswith("detailed_description:\n[Shot 1] 00:00.00\u201300:08.00"))
        self.assertTrue(parsed["shots"][1].startswith("detailed_description:\n[Shot 2] 00:08.00\u201300:16.00"))
        self.assertIn("subject_definitions", parsed["common_prompt"])
        self.assertIn("阿宁 (S1)", parsed["common_prompt"])
        for shot in parsed["shots"]:
            self.assertNotIn("subject_definitions", shot)
            self.assertNotIn("声音设定", shot)

    def test_v7_storage_header_round_trip(self):
        """v7 存储风格 [Shot N] mm:ss\u2013mm:ss 头部正确拆分。"""
        beats = _beats()
        group = _group("cumulative")
        draft = complete_draft([body(), body("阿南", 2, "好的。", offset=8)])
        parsed = skill.split_complete_group_draft(draft, beats, group=group)
        self.assertEqual(len(parsed["shots"]), 2)
        merged = parsed["common_prompt"] + "\n" + "\n".join(parsed["shots"])
        self.assertIn("阿宁", merged)
        self.assertIn("阿南", merged)
        self.assertIn("回来。", merged)
        self.assertIn("好的。", merged)

    def test_no_silent_rewrite_of_authored_content(self):
        """拆分器不改写动作、对白、音效或约束。"""
        beats = _beats()
        group = _group("cumulative")
        draft = complete_draft([body(), body("阿南", 2, "好的。", offset=8)])
        parsed = skill.split_complete_group_draft(draft, beats, group=group)
        self.assertIn("(1\u20136秒)", parsed["shots"][0])
        self.assertIn("(9\u201314秒)", parsed["shots"][1])
        self.assertIn("呼吸声与环境底噪", parsed["shots"][0])

    def test_duplicate_detailed_description_lines_stripped(self):
        """正文内多余的 detailed_description: 行被剥离，只保留一个容器头。"""
        beats = _beats()
        group = _group("cumulative")
        draft = (
            "subject_definitions（主体定义）:\n<Subject 1> 是 阿宁。\n声音设定：\n阿宁 (S1)：自然人声。\n"
            "detailed_description:\n"
            "detailed_description:\n[Shot 1] 00:00.00\u201300:08.00\n"
            "【主体】阿宁。\n【动作】(0\u20138秒) 坐住。\n【镜头】固定。\n【音效】安静。\n【约束】一致。\n"
            "[Shot 2] 00:08.00\u201300:16.00\n"
            "【主体】阿南。\n【动作】(8\u201316秒) 站住。\n【镜头】固定。\n【音效】安静。\n【约束】一致。\n"
        )
        parsed = skill.split_complete_group_draft(draft, beats, group=group)
        for shot in parsed["shots"]:
            self.assertEqual(shot.count("detailed_description"), 1)


class AtomicAdoptionTests(unittest.TestCase):
    """__common_prompt__ 原子采纳与并发冲突。"""

    def test_common_prompt_candidate_stored_separately(self):
        """__common_prompt__ 不直接进入 shot_prompts。"""
        beats = _beats()
        group = _group()
        plan = _plan(beats, group)
        raw = complete_draft([body(), body("阿南", 2, "好的。", offset=8)])
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {"ok": True})):
            result = prompts.generate_group(plan, group, beats)
        self.assertIn("__common_prompt__", result)
        self.assertNotIn("__common_prompt__", {k: v for k, v in result.items() if k != "__common_prompt__"})

    def test_common_prompt_not_updated_when_no_candidate(self):
        """无 __common_prompt__ 候选时不更新公共设定。"""
        beats = _beats()
        group = _group()
        plan = _plan(beats, group)
        raw = complete_draft([body(), body("阿南", 2, "好的。", offset=8)], common=group["common_prompt"])
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {"ok": True})):
            result = prompts.generate_group(plan, group, beats)
        self.assertNotIn("__common_prompt__", result)


class RepairBoundTests(unittest.TestCase):
    """返修上限 3 次。"""

    def test_max_three_attempts(self):
        beats = _beats()
        group = _group()
        plan = _plan(beats, group)
        raw = complete_draft([body()])
        with patch.object(prompts.LlmService, "author_group", side_effect=[(raw + f"\n第{i}版", {"ok": True}) for i in range(3)]) as chat:
            with self.assertRaises(ValueError):
                prompts.generate_group(plan, group, beats)
            self.assertEqual(chat.call_count, 3)

    def test_writing_history_recorded(self):
        beats = _beats()
        group = _group()
        plan = _plan(beats, group)
        raw = complete_draft([body(), body("阿南", 2, "好的。", offset=8)])
        with patch.object(prompts.LlmService, "author_group", return_value=(raw, {"ok": True})):
            prompts.generate_group(plan, group, beats)
        self.assertTrue(plan.get("writing_history"))
        self.assertEqual(plan["writing_history"][-1]["attempt"], 1)
        self.assertIn("author", plan["writing_history"][-1])
        self.assertIn("raw", plan["writing_history"][-1])


if __name__ == "__main__":
    unittest.main()
