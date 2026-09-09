from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI

from backend.app.xiaji_api import register_xiaji_routes
from backend.app.xiaji_asset_api import register_xiaji_asset_routes
from backend.app.xiaji_asset_prompts import character_look_prompt, character_portrait_prompt, image_options_for_look, image_options_for_prop_view, prop_view_prompt, scene_master_prompt, scene_view_prompt
from backend.app.xiaji_asset_store import XiajiAssetStore
from backend.app.xiaji_episode_api import register_xiaji_episode_routes
from backend.app.xiaji_episode_prompts import normalize_script_beats
from backend.app.xiaji_literal_script import generate_script_beats, parse_scene_heading_line
from backend.app.xiaji_episode_store import XiajiEpisodeStore, allocate_chapter_text, split_original_lines
from backend.app.xiaji_parser import episode_count_for_text, extract_docx_text, parse_chapters
from backend.app.xiaji_project_store import XiajiProjectStore

from backend.app.xiaji_store import XiajiIngestStore
from backend.app.xiaji_analyze import (
    CHARACTER_PROMPT,
    build_ingest_messages,
    define_voice_profile,
    normalize_analysis,
    parse_llm_json,
)

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _xiaji_workspace(raw: str, owner: str = "user-1"):
    path = Path(raw) / "xiaji.db"
    projects = XiajiProjectStore(path)
    ingest = XiajiIngestStore(path)
    assets = XiajiAssetStore(path)
    episodes = XiajiEpisodeStore(path)
    project = projects.create_project(owner, "测试项目")
    return projects, ingest, assets, episodes, project


def _minimal_docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>")
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


class XiajiParserTests(unittest.TestCase):
    def test_chinese_chapter_headings(self) -> None:
        chapters = parse_chapters("前言一段\n第一章 出发\n正文甲\n第二章 抵达\n正文乙")
        self.assertEqual([item["title"] for item in chapters], ["开篇", "第一章 出发", "第二章 抵达"])
        self.assertEqual(chapters[1]["content"], "正文甲")

    def test_markdown_headings_and_fallback(self) -> None:
        chapters = parse_chapters("# 序章\n开场\n## 尾声\n结束")
        self.assertEqual(len(chapters), 2)
        fallback = parse_chapters("没有标题的一整段故事")
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["title"], "没有标题的一整段故事")

    def test_explicit_segments_keep_time_titles_and_boundaries(self) -> None:
        text = (
            "第一段｜0–10秒：废墟中的幸存者\n"
            "男主穿过废墟。\n"
            "第二段｜10–20秒：地下室的危险\n"
            "怪物突然冲出。\n"
            "第三段｜20–30秒：最后的选择\n"
            "男主把水递给女孩。"
        )
        chapters = parse_chapters(text)
        self.assertEqual([item["title"] for item in chapters], [
            "第一段｜0–10秒：废墟中的幸存者",
            "第二段｜10–20秒：地下室的危险",
            "第三段｜20–30秒：最后的选择",
        ])
        self.assertEqual([item["content"] for item in chapters], [
            "男主穿过废墟。",
            "怪物突然冲出。",
            "男主把水递给女孩。",
        ])
        self.assertEqual(episode_count_for_text(text), 3)

    def test_explicit_segment_variants_are_supported(self) -> None:
        chapters = parse_chapters("Part 1: Opening\nA\nSegment 2 - Chase\nB\n段落3｜Ending\nC")
        self.assertEqual([item["title"] for item in chapters], ["Part 1: Opening", "Segment 2 - Chase", "段落3｜Ending"])

    def test_episode_headings_are_one_shot_per_line_segments(self) -> None:
        text = (
            "第 1 集\n"
            "1-1 场景：苏鸾寝殿深夜内\n"
            "人物：苏糖、锦绣\n"
            "△【闪回】漆黑寝殿。\n"
            "苏糖：我不能死！\n"
            "第 2 集\n"
            "2-1 场景：大学宿舍 日 内\n"
            "△苏糖把书砸在地上。\n"
        )
        chapters = parse_chapters(text)
        self.assertEqual([item["title"] for item in chapters], ["第 1 集", "第 2 集"])
        self.assertEqual(chapters[0]["content"].split("\n")[0], "1-1 场景：苏鸾寝殿深夜内")
        self.assertIn("苏糖：我不能死！", chapters[0]["content"])
        self.assertEqual(episode_count_for_text(text), 2)
        self.assertEqual(
            allocate_chapter_text(chapters, 2)[0].split("\n")[-1],
            "苏糖：我不能死！",
        )
        prose = parse_chapters("第一集已经结束。\n她走进雨夜巷口。")
        self.assertEqual(len(prose), 1)

    def test_docx_paragraphs(self) -> None:
        text = extract_docx_text(_minimal_docx(["第一章 雨夜", "角色走进巷口。"]))
        self.assertIn("第一章 雨夜", text)
        self.assertIn("角色走进巷口。", text)


class XiajiStoreTests(unittest.TestCase):
    def test_create_and_replace_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, store, _assets, _episodes, project = _xiaji_workspace(raw)
            created = store.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="story.txt",
                title="测试文稿",
                source_format="txt",
                original_text="第一章 甲\n内容一\n第二章 乙\n内容二",
            )
            self.assertEqual(created["status"], "ready")
            self.assertEqual(created["chapter_count"], 2)
            self.assertEqual(created["project_id"], project["id"])
            self.assertEqual(len(store.list_documents("user-1", project["id"])), 1)
            with self.assertRaises(KeyError):
                store.get_document(created["id"], "other-user")

            updated = store.replace_chapters(
                created["id"],
                "user-1",
                [
                    {"title": "合并章", "content": "内容一\n内容二"},
                ],
            )
            self.assertEqual(updated["chapter_count"], 1)
            self.assertEqual(updated["chapters"][0]["title"], "合并章")
            store.delete_document(created["id"], "user-1")
            self.assertEqual(store.list_documents("user-1", project["id"]), [])

    def test_pasted_plain_text_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, store, _assets, _episodes, project = _xiaji_workspace(raw)
            created = store.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="paste.txt",
                title="粘贴文稿",
                source_format="txt",
                original_text="第一章 雨夜\n角色走进巷口。",
            )
            self.assertEqual(created["filename"], "paste.txt")
            self.assertEqual(created["chapters"][0]["title"], "第一章 雨夜")

    def test_explicit_segments_drive_episode_estimate_and_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, store, _assets, _episodes, project = _xiaji_workspace(raw)
            text = "第一段｜0–10秒：A\n甲\n第二段｜10–20秒：B\n乙\n第三段｜20–30秒：C\n丙"
            created = store.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="segments.txt",
                title="分段短剧",
                source_format="txt",
                original_text=text,
            )
            self.assertEqual(created["chapter_count"], 3)
            self.assertEqual(created["estimated_episodes"], 3)
            self.assertEqual(
                allocate_chapter_text(created["chapters"], 3),
                ["甲", "乙", "丙"],
            )


class XiajiPastePayloadTests(unittest.TestCase):
    def test_browser_json_body_is_accepted(self) -> None:
        from backend.app.xiaji_api import XiajiPasteRequest

        payload = XiajiPasteRequest.model_validate(
            {
                "text": "骊珠洞天泥瓶巷的孤儿，五岁那年本命瓷被父亲打碎。",
                "title": "",
                "spine_template": "drama",
                "visual_style": "chinese_period_drama",
                "narration_style": "first_person",
                "ethnicity": "Chinese",
            }
        )
        self.assertIn("骊珠洞天", payload.text)


class XiajiAnalysisTests(unittest.TestCase):
    def test_parse_fenced_json_and_normalize(self) -> None:
        raw = """```json
        {
          "summary": "雨夜巷口的对峙。",
          "characters": [
            {"name": "谢铮", "aliases": ["小谢铮"], "role": "主角", "is_main": true, "gender": "男",
             "age_group": "youth", "body_type": "清瘦", "description": "冷静", "face_prompt": "男性，青年，黑发"},
            {"name": "阿宁", "aliases": [], "role": "闺蜜", "is_main": true, "gender": "女",
             "age_group": "youth", "body_type": "", "description": "", "face_prompt": ""}
          ],
          "scenes": [{"name": "雨夜巷口", "scene_type": "exterior", "description": "窄巷积水"}],
          "props": [{"name": "短刀", "aliases": [], "prop_type": "weapon", "visual_prompt": "锈蚀短刀", "owner": "谢铮"}],
          "episodes": [{"number": 1, "title": "巷口", "content_summary": "对峙", "main_conflict": "身份", "cliffhanger": "有人跟踪", "key_events": ["拔刀"]}]
        }
        ```"""
        parsed = parse_llm_json(raw)
        result = normalize_analysis(parsed, target_episodes=1)
        self.assertEqual(result["summary"], "雨夜巷口的对峙。")
        self.assertEqual(result["characters"][0]["name"], "谢铮")
        self.assertTrue(result["characters"][0]["is_main"])
        self.assertFalse(result["characters"][1]["is_main"])
        self.assertEqual(result["scenes"][0]["name"], "雨夜巷口")
        self.assertEqual(result["episodes"][0]["title"], "巷口")

    def test_invalid_json_keeps_raw(self) -> None:
        from backend.app.llm_client import LlmError

        raw = "<<<think>>> this is not json {"
        with self.assertRaises(LlmError) as ctx:
            parse_llm_json(raw)
        self.assertIn("不是合法 JSON", str(ctx.exception))
        self.assertEqual(ctx.exception.raw, raw)

    def test_ingest_character_prompt_requires_description(self) -> None:
        self.assertIn("description: 必填", CHARACTER_PROMPT)
        self.assertIn("性格", CHARACTER_PROMPT)
        self.assertIn("禁止空字符串", CHARACTER_PROMPT)
        self.assertIn("不要写死造型/身份戏服", CHARACTER_PROMPT)
        self.assertNotIn("不要提取身份/服装信息", CHARACTER_PROMPT)
        messages = build_ingest_messages(
            "陈平安护送少女李宝瓶南下求学。",
            spine_template="drama",
            visual_style="anime",
            narration_style="first_person",
            ethnicity="Chinese",
            target_episodes=1,
        )
        system = messages[0]["content"]
        self.assertIn("description: 必填", system)
        self.assertIn("不要写死造型/身份戏服", system)
        self.assertNotIn("不要提取身份/服装信息", system)

    def test_explicit_segment_prompt_and_normalization(self) -> None:
        text = "第一段｜0–10秒：A\n甲\n第二段｜10–20秒：B\n乙\n第三段｜20–30秒：C\n丙"
        messages = build_ingest_messages(
            text,
            spine_template="drama",
            visual_style="",
            narration_style="first_person",
            ethnicity="Chinese",
            target_episodes=3,
        )
        self.assertIn("必须严格按这些分段逐项输出", messages[0]["content"])
        self.assertIn("第一段｜0–10秒：A", messages[0]["content"])
        result = normalize_analysis(
            {"summary": "", "episodes": [{"number": 1, "title": "A"}]},
            target_episodes=3,
            segment_titles=["第一段｜0–10秒：A", "第二段｜10–20秒：B", "第三段｜20–30秒：C"],
        )
        self.assertEqual(len(result["episodes"]), 3)
        self.assertEqual([item["number"] for item in result["episodes"]], [1, 2, 3])
        self.assertEqual(result["episodes"][2]["title"], "第三段｜20–30秒：C")

    def test_drama_ingest_keeps_one_shot_per_line(self) -> None:
        drama = build_ingest_messages(
            "第 1 集\n△苏糖坐起。\n苏糖：几更了？",
            spine_template="drama",
            visual_style="",
            narration_style="first_person",
            ethnicity="Chinese",
            target_episodes=1,
        )
        self.assertIn("一行一个镜头", drama[0]["content"])
        self.assertIn("第 1 集", drama[0]["content"])
        narrated = build_ingest_messages(
            "第一章\n她走进雨夜巷口。",
            spine_template="narrated",
            visual_style="",
            narration_style="third_person",
            ethnicity="Chinese",
            target_episodes=1,
        )
        self.assertNotIn("一行一个镜头", narrated[0]["content"])

    def test_save_analysis_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, store, _assets, _episodes, project = _xiaji_workspace(raw)
            created = store.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="paste.txt",
                title="粘贴文稿",
                source_format="txt",
                original_text="第一章 雨夜\n角色走进巷口。",
            )
            saved = store.save_analysis(
                created["id"],
                "user-1",
                {
                    "summary": "雨夜",
                    "characters": [{"name": "谢铮", "role": "主角", "is_main": True}],
                    "scenes": [],
                    "props": [],
                    "episodes": [],
                },
                logs=["解析原文", "调用大模型"],
                model="test-model",
                status="indexed",
            )
            self.assertEqual(saved["status"], "indexed")
            self.assertEqual(saved["analysis"]["summary"], "雨夜")
            self.assertEqual(saved["analysis"]["model"], "test-model")
            self.assertEqual(saved["analysis"]["logs"][1], "调用大模型")


class XiajiProjectIsolationTests(unittest.TestCase):
    def test_create_project_inherits_user_art_style(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            projects, *_rest = _xiaji_workspace(raw)
            projects.set_user_art_style_id("user-1", "as_1007")
            created = projects.create_project("user-1", "新剧")
            self.assertEqual(created["settings"]["art_style_id"], "as_1007")

    def test_documents_and_assets_are_scoped_to_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, _episodes, first = _xiaji_workspace(raw)
            second = projects.create_project("user-1", "第二部")
            ingest.create_from_text(
                "user-1",
                project_id=first["id"],
                filename="a.txt",
                title="甲",
                source_format="txt",
                original_text="第一章 甲\n正文",
            )
            ingest.create_from_text(
                "user-1",
                project_id=second["id"],
                filename="b.txt",
                title="乙",
                source_format="txt",
                original_text="第一章 乙\n正文",
            )
            self.assertEqual([item["title"] for item in ingest.list_documents("user-1", first["id"])], ["甲"])
            self.assertEqual([item["title"] for item in ingest.list_documents("user-1", second["id"])], ["乙"])
            analysis = {
                "ingest_settings": {"visual_style": "anime"},
                "characters": [{"name": "谢铮", "role": "主角", "is_main": True}],
                "scenes": [],
                "props": [],
            }
            assets.sync_from_analysis("user-1", analysis, project_id=first["id"])
            assets.sync_from_analysis("user-1", analysis, project_id=second["id"])
            self.assertEqual(len(assets.list_assets("user-1", first["id"], "character")), 1)
            self.assertEqual(len(assets.list_assets("user-1", second["id"], "character")), 1)
            projects.delete_project(first["id"], "user-1")
            self.assertEqual(ingest.list_documents("user-1", first["id"]), [])
            self.assertEqual(assets.list_assets("user-1", first["id"]), [])
            self.assertEqual(len(ingest.list_documents("user-1", second["id"])), 1)

    def test_clear_project_content_keeps_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, first = _xiaji_workspace(raw)
            second = projects.create_project("user-1", "第二部")
            ingest.create_from_text(
                "user-1",
                project_id=first["id"],
                filename="a.txt",
                title="甲",
                source_format="txt",
                original_text="第一章 甲\n正文",
            )
            assets.sync_from_analysis(
                "user-1",
                {"characters": [{"name": "谢铮", "role": "主角", "is_main": True}], "scenes": [], "props": []},
                project_id=first["id"],
            )
            ingest.create_from_text(
                "user-1",
                project_id=second["id"],
                filename="b.txt",
                title="乙",
                source_format="txt",
                original_text="第一章 乙\n正文",
            )
            episodes.upsert_episode(
                "user-1",
                project_id=first["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀。"],
                overwrite_script=True,
            )
            projects.clear_project_content(first["id"], "user-1")
            kept = projects.get_project(first["id"], "user-1")
            self.assertEqual(kept["name"], "测试项目")
            self.assertEqual(ingest.list_documents("user-1", first["id"]), [])
            self.assertEqual(assets.list_assets("user-1", first["id"]), [])
            self.assertEqual(episodes.list_episodes("user-1", first["id"]), [])
            self.assertEqual([item["title"] for item in ingest.list_documents("user-1", second["id"])], ["乙"])

    def test_paste_replace_clears_previous_ingest(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, project = _xiaji_workspace(raw)
            old = ingest.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="old.txt",
                title="旧稿",
                source_format="txt",
                original_text="第一章 旧\n旧正文",
            )
            assets.sync_from_analysis(
                "user-1",
                {"characters": [{"name": "旧人", "role": "路人", "is_main": False}], "scenes": [], "props": []},
                project_id=project["id"],
            )

            class Llm:
                def analyze_xiaji_ingest(self, text, **kwargs):
                    return {
                        "summary": "新稿",
                        "characters": [{"name": "谢铮", "is_main": True, "aliases": []}],
                        "scenes": [],
                        "props": [],
                        "episodes": [],
                        "model": "t",
                    }

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_store = ingest
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_store = episodes
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            client = TestClient(app)
            pasted = client.post(
                "/api/xiaji/documents/paste",
                params={"project_id": project["id"]},
                json={"text": "第一章 新\n谢铮拔刀。", "replace": True},
            )
            self.assertEqual(pasted.status_code, 201, pasted.text)
            docs = ingest.list_documents("user-1", project["id"])
            self.assertEqual(len(docs), 1)
            self.assertNotEqual(docs[0]["id"], old["id"])
            names = [item["name"] for item in assets.list_assets("user-1", project["id"], "character")]
            self.assertNotIn("旧人", names)
            self.assertIn("谢铮", names)


class XiajiRouteAuthTests(unittest.TestCase):
    def test_paste_does_not_require_query_user(self) -> None:
        app = FastAPI()
        register_xiaji_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
        parameters = app.openapi()["paths"]["/api/xiaji/documents/paste"]["post"].get("parameters") or []
        names = [item.get("name") for item in parameters]
        self.assertNotIn("user", names)
        self.assertIn("project_id", names)

    def test_assets_list_does_not_require_query_user(self) -> None:
        app = FastAPI()
        register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
        parameters = app.openapi()["paths"]["/api/xiaji/assets"]["get"].get("parameters") or []
        names = [item.get("name") for item in parameters]
        self.assertNotIn("user", names)
        self.assertIn("project_id", names)
        self.assertIn("/api/xiaji/assets/sync", app.openapi()["paths"])


class XiajiAssetStoreTests(unittest.TestCase):
    def test_sync_creates_character_scene_prop_and_narrator(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, _ingest, store, _episodes, project = _xiaji_workspace(raw)
            result = store.sync_from_analysis(
                "user-1",
                {
                    "ingest_settings": {"art_style_id": "as_1001"},
                    "characters": [
                        {
                            "name": "谢铮",
                            "role": "主角",
                            "is_main": True,
                            "gender": "男",
                            "age_group": "youth",
                            "description": "泥瓶巷孤儿",
                            "face_prompt": "男性，青年，短发",
                            "aliases": ["小谢铮"],
                        }
                    ],
                    "scenes": [{"name": "泥瓶巷", "scene_type": "exterior", "description": "窑火巷口"}],
                    "props": [{"name": "本命瓷", "prop_type": "artifact", "visual_prompt": "碎瓷片"}],
                },
                project_id=project["id"],
            )
            kinds = {item["kind"]: item for item in result["assets"]}
            self.assertGreaterEqual(result["created"], 3)
            self.assertEqual(result["transferred"]["characters"], 1)
            self.assertEqual(result["transferred"]["scenes"], 1)
            self.assertEqual(result["transferred"]["props"], 1)
            self.assertEqual(kinds["character"]["name"], "谢铮")
            self.assertTrue(kinds["character"]["definition"]["looks"])
            self.assertEqual(kinds["character"]["definition"]["ethnicity"], "Chinese")
            self.assertEqual(kinds["scene"]["name"], "泥瓶巷")
            self.assertEqual(kinds["prop"]["name"], "本命瓷")
            self.assertEqual(kinds["voice"]["name"], "解说")
            again = store.sync_from_analysis("user-1", {
                "ingest_settings": {"art_style_id": "as_1001", "ethnicity": "Chinese"},
                "characters": [{"name": "谢铮", "description": "泥瓶巷孤儿", "aliases": ["瓷孩儿"]}],
                "scenes": [{"name": "泥瓶巷", "description": "窑火巷口"}],
                "props": [{"name": "本命瓷", "visual_prompt": "碎瓷片"}],
            }, project_id=project["id"])
            self.assertEqual(again["created"], 0)
            character = store.list_assets("user-1", project["id"], "character")[0]
            self.assertIn("瓷孩儿", character["definition"]["aliases"])
            self.assertEqual(character["definition"]["ethnicity"], "Chinese")
            prompt = character_portrait_prompt(character)
            self.assertIn("谢铮", prompt)
            self.assertIn("Chinese", prompt)
            self.assertIn("epic cinematic scene", prompt)
            self.assertIn("plain mid-gray background", prompt)
            style_locked = character_portrait_prompt(character, has_style_reference=True)
            self.assertIn("first attached image is REFERENCE 1", style_locked)
            self.assertIn("color palette", style_locked)
            self.assertNotIn("plain mid-gray background", style_locked)
            look = character["definition"]["looks"][0]
            sheet = character_look_prompt(character, {**look, "appearance_details": "青衫佩剑"})
            self.assertIn("IDENTITY ANCHOR", sheet)
            self.assertIn("4-panel character reference sheet", sheet)
            self.assertIn("青衫佩剑", sheet)
            self.assertIn("谢铮", sheet)
            self.assertNotIn("Default ethnicity for people in this image", sheet)
            self.assertEqual(image_options_for_look()["aspect_ratio"], "16:9")
            self.assertEqual(image_options_for_look()["resolution"], "1K")
            contract_only = character_portrait_prompt(
                {
                    "name": "苏糖",
                    "kind": "character",
                    "definition": {"face_prompt": "少女", "visual_style": "chinese_period_drama"},
                }
            )
            self.assertIn("CINEMATIC FILMIC REALISM", contract_only)
            self.assertIn("NOT anime", contract_only)
            mixed_style = character_portrait_prompt(
                {
                    "name": "苏糖",
                    "kind": "character",
                    "definition": {
                        "face_prompt": "少女",
                        "visual_style": "chinese_period_drama",
                        "art_style_id": "as_1001",
                    },
                }
            )
            self.assertIn("CINEMATIC FILMIC REALISM", mixed_style)
            self.assertIn("epic cinematic scene", mixed_style)
            anime_sheet = character_look_prompt(
                character,
                {**look, "appearance_details": "校服"},
                style="anime",
            )
            self.assertIn("animated character reference sheet", anime_sheet)
            self.assertIn("窑火", scene_master_prompt(kinds["scene"]))
            reverse = scene_view_prompt(kinds["scene"], "reverse")
            pano = scene_view_prompt(kinds["scene"], "panorama")
            pano_with_refs = scene_view_prompt(
                kinds["scene"], "panorama", has_master_reference=True, has_reverse_reference=True
            )
            self.assertIn("FRONT-FACING", scene_master_prompt(kinds["scene"]))
            occupied = {
                "name": "破屋内",
                "kind": "scene",
                "definition": {
                    "scene_type": "interior",
                    "description": "一间破旧的屋内，陈平安跪在床前，父亲已逝，母亲咳血。",
                    "art_style_id": "as_1001",
                },
            }
            occupied_prompt = scene_master_prompt(occupied)
            self.assertIn("EMPTY LOCATION CONTRACT", occupied_prompt)
            self.assertIn("Do NOT draw any person", occupied_prompt)
            self.assertIn("ignore people and story action", occupied_prompt)
            self.assertIn("陈平安跪在床前", occupied_prompt)
            self.assertIn("yaw-rotate 180", reverse)
            self.assertIn("背面", reverse)
            self.assertNotEqual(scene_master_prompt(kinds["scene"]), reverse)
            self.assertIn("equirectangular", pano)
            self.assertIn("2:1", pano)
            self.assertIn("PRIMARY VISUAL BIBLE", pano_with_refs)
            self.assertIn("BACK-HALF VISUAL BIBLE", pano_with_refs)
            self.assertIn("Reference image 2", pano_with_refs)
            master_prop = prop_view_prompt(kinds["prop"], "master")
            turnaround = prop_view_prompt(kinds["prop"], "turnaround")
            detail = prop_view_prompt(kinds["prop"], "detail")
            self.assertIn("本命瓷", master_prop)
            self.assertIn("FRONT product photograph", master_prop)
            self.assertNotIn("LAYOUT (1x3", master_prop)
            self.assertNotIn("3-PANEL product reference sheet", master_prop)
            self.assertIn("3-PANEL product reference sheet", turnaround)
            self.assertIn("LAYOUT (1x3, 16:9 overall)", turnaround)
            self.assertIn("SIDE PROFILE", turnaround)
            self.assertIn("BACK VIEW", turnaround)
            self.assertIn("extreme close-up", detail)
            self.assertNotEqual(master_prop, turnaround)
            self.assertNotEqual(turnaround, detail)
            for view in ("master", "turnaround", "detail"):
                self.assertEqual(image_options_for_prop_view(view)["aspect_ratio"], "16:9")
                self.assertEqual(image_options_for_prop_view(view)["resolution"], "1K")

    def test_sync_fills_empty_art_style_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _projects, _ingest, store, _episodes, project = _xiaji_workspace(raw)
            store.create_asset(
                "user-1",
                project_id=project["id"],
                kind="character",
                name="空白角色",
                definition={"face_prompt": "青年"},
            )
            store.sync_from_analysis(
                "user-1",
                {
                    "ingest_settings": {"art_style_id": "as_1007"},
                    "characters": [
                        {"name": "空白角色", "description": "无风格"},
                        {"name": "谢铮", "role": "主角", "description": "泥瓶巷孤儿"},
                    ],
                    "scenes": [{"name": "泥瓶巷", "description": "窑火巷口"}],
                    "props": [],
                },
                project_id=project["id"],
            )
            blank = next(item for item in store.list_assets("user-1", project["id"], "character") if item["name"] == "空白角色")
            created = next(item for item in store.list_assets("user-1", project["id"], "character") if item["name"] == "谢铮")
            scene = store.list_assets("user-1", project["id"], "scene")[0]
            self.assertEqual(blank["definition"]["art_style_id"], "as_1007")
            self.assertEqual(created["definition"]["art_style_id"], "as_1007")
            self.assertEqual(scene["definition"]["art_style_id"], "as_1007")
            store.sync_from_analysis(
                "user-1",
                {
                    "ingest_settings": {"art_style_id": "as_1001"},
                    "characters": [{"name": "空白角色"}, {"name": "谢铮"}],
                    "scenes": [{"name": "泥瓶巷"}],
                    "props": [],
                },
                project_id=project["id"],
            )
            blank = next(item for item in store.list_assets("user-1", project["id"], "character") if item["name"] == "空白角色")
            self.assertEqual(blank["definition"]["art_style_id"], "as_1007")

    def test_voice_json_fields(self) -> None:
        parsed = parse_llm_json(
            '{"language":"中文普通话","timbre":"沉稳男中音","pitch":"偏低","speaking_style":"慢",'
            '"sample_line":"此生与修行无缘。","tts_voice":"onyx","prompt":"压低气息"}'
        )
        self.assertEqual(parsed["tts_voice"], "onyx")

        class FakeClient:
            def chat_completion(self, *_args, **_kwargs):
                return (
                    '{"language":"中文","timbre":"清亮","pitch":"适中","speaking_style":"干脆",'
                    '"sample_line":"练拳百万次。","tts_voice":"nova","prompt":"干净利落"}'
                )

        profile = define_voice_profile(FakeClient(), "test-model", {"name": "宁姚", "gender": "女"})
        self.assertEqual(profile["tts_voice"], "nova")
        self.assertEqual(profile["sample_line"], "练拳百万次。")


class XiajiGenerateImageRouteTests(unittest.TestCase):
    def test_generate_image_returns_202_with_job_id(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def __init__(self) -> None:
                    self.generation_ids: list[str] = []
                    self.enqueued: list[str] = []

                def enqueue_generation(self, item_id: str) -> None:
                    self.generation_ids.append(item_id)

                async def enqueue(self, job_id: str) -> None:
                    self.enqueued.append(job_id)

            worker = Worker()
            app.state.grs_provider = Grs()
            app.state.worker = worker
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-test-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{
                    "generation_items": [{
                        "id": "gen-1",
                        "executor": "grs",
                        "status": JobStatus.QUEUED.value,
                    }],
                }],
            }
            with patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued:
                client = TestClient(app)
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"style": "anime", "ethnicity": "Chinese"},
                )
            self.assertEqual(response.status_code, 202)
            body = response.json()
            self.assertEqual(body["ok"], True)
            self.assertEqual(body["job_id"], "job-test-1")
            self.assertEqual(body["status"], "generating")
            self.assertEqual(body["asset"]["status"], "generating")
            self.assertEqual(body["asset"]["image_job_id"], "job-test-1")
            self.assertFalse(body["asset"].get("image_url"))
            self.assertEqual(worker.generation_ids, ["gen-1"])
            self.assertEqual(worker.enqueued, [])
            queued.assert_called_once()

    def test_generate_image_uses_project_visual_style_when_asset_empty(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测", {"art_style_id": "as_1007"})
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            self.assertFalse(created["definition"].get("art_style_id"))
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.xiaji_project_store = projects
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-style-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            style_file = Path(raw) / "as_1007.jpg"
            style_file.write_bytes(TINY_PNG)
            with (
                patch("backend.app.xiaji_asset_api.ensure_art_style_preview", return_value=style_file),
                patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued,
            ):
                client = TestClient(app)
                response = client.post(f"/api/xiaji/assets/{created['id']}/generate-image", json={})
            self.assertEqual(response.status_code, 202)
            prompt = queued.call_args.kwargs.get("prompt") or queued.call_args[1].get("prompt")
            self.assertIn("hyperreal manga fusion", prompt)
            self.assertIn("first attached image is REFERENCE 1", prompt)
            self.assertIn("color palette", prompt)
            refs = queued.call_args.kwargs.get("references") or queued.call_args[1].get("references") or []
            self.assertEqual(refs, [str(style_file)])
            refreshed = assets.get_asset(created["id"], "u1")
            self.assertEqual(refreshed["definition"]["art_style_id"], "as_1007")

    def test_create_asset_inherits_project_visual_style(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测", {"art_style_id": "as_1007"})
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.xiaji_project_store = projects
            app.state.store = object()
            app.state.resource_storage = None
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                "/api/xiaji/assets",
                params={"project_id": project["id"]},
                json={"kind": "character", "name": "宁姚", "definition": {}},
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["definition"]["art_style_id"], "as_1007")

    def test_generate_image_persists_requested_art_style(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测", {"art_style_id": "as_1001"})
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年", "art_style_id": "as_1001"},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.xiaji_project_store = projects
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-style-2",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            style_file = Path(raw) / "as_1007.jpg"
            style_file.write_bytes(TINY_PNG)
            with (
                patch("backend.app.xiaji_asset_api.ensure_art_style_preview", return_value=style_file),
                patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued,
            ):
                client = TestClient(app)
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"art_style_id": "as_1007"},
                )
            self.assertEqual(response.status_code, 202)
            prompt = queued.call_args.kwargs.get("prompt") or queued.call_args[1].get("prompt")
            self.assertIn("hyperreal manga fusion", prompt)
            self.assertEqual(response.json()["asset"]["definition"]["art_style_id"], "as_1007")

    def test_look_generate_keeps_portrait_job_and_media_slots(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            portrait_file = Path(raw) / "portrait.png"
            portrait_file.write_bytes(TINY_PNG)
            looks = list(created["definition"]["looks"])
            looks[0]["appearance_details"] = "青衫佩剑"
            assets.update_asset(
                created["id"],
                "u1",
                definition={"looks": looks},
                image_url=str(portrait_file),
                status="ready",
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            jobs = [
                {
                    "id": "job-portrait-1",
                    "mode": "grs-gpt-image-2",
                    "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
                },
                {
                    "id": "job-look-1",
                    "mode": "grs-gpt-image-2",
                    "rounds": [{"generation_items": [{"id": "gen-2", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
                },
            ]
            with patch("backend.app.xiaji_asset_api.create_queued_job", side_effect=jobs) as queued:
                client = TestClient(app)
                portrait = client.post(f"/api/xiaji/assets/{created['id']}/generate-image", json={})
                look = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"look_id": look_id},
                )
            self.assertEqual(portrait.status_code, 202)
            self.assertEqual(look.status_code, 202)
            body = look.json()["asset"]
            self.assertEqual(body["image_job_id"], "job-portrait-1")
            self.assertEqual(body["status"], "generating")
            looks = body["definition"]["looks"]
            self.assertEqual(looks[0]["job_id"], "job-look-1")
            kinds = {(item["media_kind"], item["slot"]): item["job_id"] for item in body["media"]}
            self.assertEqual(kinds[("portrait", "portrait")], "job-portrait-1")
            self.assertEqual(kinds[("look", look_id)], "job-look-1")
            look_call = queued.call_args_list[1]
            prompt = look_call.kwargs.get("prompt") or look_call[1].get("prompt")
            options = look_call.kwargs.get("options") or {}
            refs = look_call.kwargs.get("references") or []
            self.assertEqual(refs, [str(portrait_file)])
            self.assertEqual(options.get("aspect_ratio"), "16:9")
            self.assertEqual(options.get("resolution"), "1K")
            self.assertIn("IDENTITY ANCHOR", prompt)
            self.assertIn("青衫佩剑", prompt)

    def test_look_generate_requires_portrait(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年", "looks": [{"id": "look-1", "name": "基础", "appearance_details": "青衫"}]},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            app.state.grs_provider = Grs()
            app.state.worker = object()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/assets/{created['id']}/generate-image",
                json={"look_id": created["definition"]["looks"][0]["id"]},
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("肖像", response.json()["detail"])

    def test_look_generate_requires_appearance(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            portrait_file = Path(raw) / "portrait.png"
            portrait_file.write_bytes(TINY_PNG)
            assets.update_asset(created["id"], "u1", image_url=str(portrait_file), status="ready")
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            app.state.grs_provider = Grs()
            app.state.worker = object()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/assets/{created['id']}/generate-image",
                json={"look_id": created["definition"]["looks"][0]["id"]},
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("外观描述", response.json()["detail"])

    def test_hydrate_writes_portrait_and_look_from_separate_jobs(self) -> None:
        from backend.app.models import JobStatus
        from backend.app.xiaji_asset_api import _hydrate_asset

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            assets.add_media(created["id"], "u1", media_kind="portrait", slot="portrait", job_id="job-portrait-1")
            assets.add_media(created["id"], "u1", media_kind="look", slot=look_id, job_id="job-look-1")
            looks = list(created["definition"]["looks"])
            looks[0]["job_id"] = "job-look-1"
            assets.update_asset(
                created["id"],
                "u1",
                definition={"looks": looks},
                status="generating",
                image_job_id="job-portrait-1",
            )

            class Jobs:
                def get(self, job_id):
                    mapping = {
                        "job-portrait-1": {
                            "id": "job-portrait-1",
                            "status": JobStatus.SUCCEEDED.value,
                            "outputs": [{"kind": "image", "cloud_url": "https://cdn.example/portrait.png"}],
                        },
                        "job-look-1": {
                            "id": "job-look-1",
                            "status": JobStatus.SUCCEEDED.value,
                            "outputs": [{"kind": "image", "cloud_url": "https://cdn.example/look.png"}],
                        },
                    }
                    return mapping[job_id]

            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = Jobs()
            app.state.resource_storage = None
            hydrated = _hydrate_asset(app, assets.get_asset(created["id"], "u1"), "u1")
            self.assertEqual(hydrated["image_url"], "https://cdn.example/portrait.png")
            self.assertEqual(hydrated["definition"]["looks"][0]["image_url"], "https://cdn.example/look.png")
            self.assertNotEqual(hydrated["image_url"], hydrated["definition"]["looks"][0]["image_url"])
            media_urls = {item["job_id"]: item["url"] for item in hydrated["media"]}
            self.assertEqual(media_urls["job-portrait-1"], "https://cdn.example/portrait.png")
            self.assertEqual(media_urls["job-look-1"], "https://cdn.example/look.png")

    def test_upload_look_does_not_replace_portrait(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            assets.update_asset(created["id"], "u1", image_url="https://cdn.example/portrait.png", status="ready")

            class Stored:
                key = "look-key"

            class Storage:
                def store_bytes(self, *_args, **_kwargs):
                    return Stored()

            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = Storage()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/assets/{created['id']}/upload-image",
                files={"file": ("look.png", b"fake-bytes", "image/png")},
                data={"look_id": look_id},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["image_url"], "https://cdn.example/portrait.png")
            self.assertTrue(body["definition"]["looks"][0]["image_url"])
            self.assertNotEqual(body["definition"]["looks"][0]["image_url"], body["image_url"])

    def test_latest_media_url_overrides_wrong_look_field(self) -> None:
        from backend.app.xiaji_asset_api import _hydrate_asset, _with_media_urls

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            looks = list(created["definition"]["looks"])
            looks[0]["image_url"] = "https://cdn.example/portrait.png"
            assets.update_asset(
                created["id"],
                "u1",
                definition={"looks": looks},
                image_url="https://cdn.example/portrait.png",
                image_job_id="job-portrait-1",
                status="ready",
            )
            assets.add_media(
                created["id"], "u1", media_kind="portrait", slot="portrait",
                job_id="job-portrait-1", url="https://cdn.example/portrait.png",
            )
            assets.add_media(
                created["id"], "u1", media_kind="look", slot=look_id,
                job_id="job-look-1", url="https://cdn.example/look.png",
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            public = _with_media_urls(_hydrate_asset(app, assets.get_asset(created["id"], "u1"), "u1"))
            self.assertEqual(public["image_url"], "https://cdn.example/portrait.png")
            self.assertEqual(public["definition"]["looks"][0]["image_url"], "https://cdn.example/look.png")

    def test_hydrate_rewrites_portrait_when_image_job_id_is_look(self) -> None:
        from backend.app.xiaji_asset_api import _character_slot_sources, _hydrate_asset

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="林平之",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            looks = list(created["definition"]["looks"])
            looks[0]["job_id"] = "job-look-1"
            looks[0]["image_url"] = "https://cdn.example/look.png"
            assets.update_asset(
                created["id"],
                "u1",
                definition={"looks": looks},
                image_url="https://cdn.example/look.png",
                image_job_id="job-look-1",
                status="ready",
            )
            assets.add_media(
                created["id"], "u1", media_kind="portrait", slot="portrait",
                job_id="job-portrait-1", url="https://cdn.example/portrait.png",
            )
            assets.add_media(
                created["id"], "u1", media_kind="look", slot=look_id,
                job_id="job-look-1", url="https://cdn.example/look.png",
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            hydrated = _hydrate_asset(app, assets.get_asset(created["id"], "u1"), "u1")
            self.assertEqual(hydrated["image_url"], "https://cdn.example/portrait.png")
            self.assertEqual(hydrated["image_job_id"], "job-portrait-1")
            portrait_job, portrait_url, _key = _character_slot_sources(hydrated, "portrait")
            look_job, look_url, _look_key = _character_slot_sources(hydrated, "look", look_id=look_id)
            self.assertEqual(portrait_job, "job-portrait-1")
            self.assertEqual(portrait_url, "https://cdn.example/portrait.png")
            self.assertEqual(look_job, "job-look-1")
            self.assertEqual(look_url, "https://cdn.example/look.png")

    def test_render_character_refs_are_face_then_costume(self) -> None:
        from unittest.mock import patch

        from backend.app.xiaji_episode_api import _append_character_refs

        look_id = "look-1"
        asset = {
            "id": "ast-lin",
            "image_job_id": "job-look-1",
            "image_url": "https://cdn.example/look.png",
            "definition": {"looks": [{"id": look_id, "job_id": "job-look-1", "image_url": "https://cdn.example/look.png"}]},
            "media": [
                {"media_kind": "portrait", "slot": "portrait", "job_id": "job-portrait-1", "url": "https://cdn.example/portrait.png"},
                {"media_kind": "look", "slot": look_id, "job_id": "job-look-1", "url": "https://cdn.example/look.png"},
            ],
        }
        captured: list[dict] = []

        def capture(_app, paths, seen, **kwargs):
            captured.append(kwargs)
            paths.append(kwargs["stem"])
            seen.add(kwargs["stem"])

        with patch("backend.app.xiaji_episode_api._append_ref_file", side_effect=capture):
            _append_character_refs(object(), [], set(), {"character_ids": ["ast-lin"]}, {"ast-lin": asset})
        self.assertEqual([item["stem"] for item in captured], ["ast-lin-portrait", f"ast-lin-look-{look_id}"])
        self.assertEqual(captured[0]["job_id"], "job-portrait-1")
        self.assertEqual(captured[1]["job_id"], "job-look-1")

    def test_list_project_jobs_returns_slot_records(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="character",
                name="谢铮",
                definition={"face_prompt": "青年"},
            )
            look_id = created["definition"]["looks"][0]["id"]
            assets.add_media(created["id"], "u1", media_kind="portrait", slot="portrait", job_id="job-portrait-1")
            assets.add_media(created["id"], "u1", media_kind="look", slot=look_id, job_id="job-look-1")
            assets.update_asset(created["id"], "u1", image_job_id="job-portrait-1")

            class Jobs:
                def get(self, job_id, **_kwargs):
                    return {
                        "id": job_id,
                        "title": f"导台2 {job_id}",
                        "status": JobStatus.SUCCEEDED.value,
                        "mode": "grs-gpt-image-2",
                        "prompt": f"prompt-{job_id}",
                        "progress": 100,
                        "created_at": "2026-09-03T00:00:00",
                        "updated_at": "2026-09-03T00:01:00",
                        "reference_count": 1 if job_id == "job-portrait-1" else 0,
                        "options": {"aspect_ratio": "4:3", "count": 1},
                        "outputs": [{"kind": "image", "cloud_url": f"https://cdn.example/{job_id}.png"}],
                    }

            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.xiaji_project_store = projects
            app.state.store = Jobs()
            app.state.resource_storage = None
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.get("/api/xiaji/jobs", params={"project_id": project["id"]})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            slots = {item["slot"]: item for item in body}
            self.assertIn("portrait", slots)
            self.assertIn("look", slots)
            self.assertEqual(slots["portrait"]["preview_url"], "https://cdn.example/job-portrait-1.png")
            self.assertEqual(slots["look"]["preview_url"], "https://cdn.example/job-look-1.png")
            self.assertNotEqual(slots["portrait"]["preview_url"], slots["look"]["preview_url"])
            self.assertEqual(slots["portrait"]["reference_count"], 1)
            self.assertEqual(slots["portrait"]["references"][0]["url"], "/api/jobs/job-portrait-1/references/1")
            names = {item["name"] for item in slots["portrait"]["parameters"]}
            self.assertIn("options.aspect_ratio", names)
            self.assertIn("prompt", names)

    def test_job_input_snapshot_counts_round_references(self) -> None:
        from backend.app.xiaji_asset_api import _job_input_snapshot

        snapshot = _job_input_snapshot(
            {
                "id": "yZsvmOlGDr7n",
                "mode": "grs-gpt-image-2",
                "title": "导台2 场景背面 · 落魄山",
                "prompt": "REFERENCE 1",
                "options": {"aspect_ratio": "16:9"},
                "rounds": [{"id": "r1", "reference_count": 1}],
            }
        )
        self.assertEqual(snapshot["reference_count"], 1)
        self.assertEqual(snapshot["references"][0]["url"], "/api/jobs/yZsvmOlGDr7n/references/1")
        self.assertIn("正面源图", snapshot["references"][0]["label"])

    def test_scene_reverse_requires_master_image(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="scene",
                name="泥瓶巷",
                definition={"description": "正面：巷口石板。背面：窑火门洞。", "scene_type": "exterior"},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/assets/{created['id']}/generate-image",
                json={"scene_view": "reverse"},
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("正面源图", response.json()["detail"])

    def test_scene_panorama_requires_master_image(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="scene",
                name="泥瓶巷",
                definition={"description": "巷口", "scene_type": "exterior"},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/assets/{created['id']}/generate-image",
                json={"scene_view": "panorama"},
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("正面源图", response.json()["detail"])

    def test_scene_reverse_uses_distinct_prompt_and_keeps_master_job(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="scene",
                name="泥瓶巷",
                definition={"description": "正面：巷口石板。背面：窑火门洞。", "scene_type": "exterior"},
            )
            front = Path(raw) / "front.png"
            front.write_bytes(TINY_PNG)
            assets.update_asset(created["id"], "u1", image_url=str(front), status="ready")
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-reverse-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            with patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued:
                client = TestClient(app)
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"scene_view": "reverse"},
                )
            self.assertEqual(response.status_code, 202)
            body = response.json()
            self.assertNotEqual(body["asset"].get("image_job_id"), "job-reverse-1")
            self.assertEqual((body["asset"].get("definition") or {}).get("scene_jobs", {}).get("reverse"), "job-reverse-1")
            prompt = queued.call_args.kwargs.get("prompt") or queued.call_args[1].get("prompt")
            refs = queued.call_args.kwargs.get("references") or []
            self.assertIn("yaw-rotate 180", prompt)
            self.assertIn("REFERENCE 1", prompt)
            self.assertEqual(refs, [str(front)])

    def test_scene_panorama_attaches_master_then_reverse(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            front = Path(raw) / "front.png"
            reverse = Path(raw) / "reverse.png"
            front.write_bytes(TINY_PNG)
            reverse.write_bytes(TINY_PNG)
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="scene",
                name="泥瓶巷",
                definition={
                    "description": "正面：巷口石板。背面：窑火门洞。",
                    "scene_type": "exterior",
                    "back_image_url": str(reverse),
                },
            )
            assets.update_asset(created["id"], "u1", image_url=str(front), status="ready")
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-pano-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            with patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued:
                client = TestClient(app)
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"scene_view": "panorama"},
                )
            self.assertEqual(response.status_code, 202)
            prompt = queued.call_args.kwargs.get("prompt") or queued.call_args[1].get("prompt")
            refs = queued.call_args.kwargs.get("references") or []
            self.assertEqual(refs, [str(front), str(reverse)])
            self.assertIn("PRIMARY VISUAL BIBLE", prompt)
            self.assertIn("BACK-HALF VISUAL BIBLE", prompt)
            self.assertIn("equirectangular", prompt)

    def test_prop_turnaround_uses_distinct_prompt_and_keeps_master_job(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="prop",
                name="本命瓷",
                definition={"visual_prompt": "碎瓷片镶金边", "description": "宁姚本命瓷"},
            )
            master = Path(raw) / "prop-master.png"
            master.write_bytes(TINY_PNG)
            assets.update_asset(created["id"], "u1", image_url=str(master), status="ready")
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            job = {
                "id": "job-turn-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            with patch("backend.app.xiaji_asset_api.create_queued_job", return_value=job) as queued:
                client = TestClient(app)
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"prop_view": "turnaround"},
                )
            self.assertEqual(response.status_code, 202)
            body = response.json()
            self.assertNotEqual(body["asset"].get("image_job_id"), "job-turn-1")
            self.assertEqual((body["asset"].get("definition") or {}).get("prop_jobs", {}).get("turnaround"), "job-turn-1")
            prompt = queued.call_args.kwargs.get("prompt") or queued.call_args[1].get("prompt")
            self.assertIn("本命瓷", prompt)
            self.assertIn("3-PANEL product reference sheet", prompt)
            self.assertIn("LAYOUT (1x3, 16:9 overall)", prompt)
            options = queued.call_args.kwargs.get("options") or {}
            self.assertEqual(options.get("aspect_ratio"), "16:9")
            self.assertEqual(options.get("resolution"), "1K")
            refs = queued.call_args.kwargs.get("references") or []
            self.assertEqual(refs, [str(master)])
            self.assertIn("REFERENCE 1", prompt)

    def test_prop_turnaround_requires_master_image(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="prop",
                name="本命瓷",
                definition={"visual_prompt": "碎瓷片"},
            )
            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.store = object()
            app.state.resource_storage = None

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def enqueue_generation(self, item_id: str) -> None:
                    return None

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            for view in ("turnaround", "detail"):
                response = client.post(
                    f"/api/xiaji/assets/{created['id']}/generate-image",
                    json={"prop_view": view},
                )
                self.assertEqual(response.status_code, 422, view)
                self.assertIn("主视图", response.json()["detail"])

    def test_failed_reverse_job_is_not_left_generating(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            assets = XiajiAssetStore(Path(raw) / "xiaji.db")
            projects = XiajiProjectStore(Path(raw) / "xiaji.db")
            project = projects.create_project("u1", "测")
            created = assets.create_asset(
                "u1",
                project_id=project["id"],
                kind="scene",
                name="落魄山",
                definition={"description": "正面山门。背面荒坡。", "scene_type": "exterior", "scene_jobs": {"reverse": "job-reverse-fail"}},
            )
            assets.update_asset(
                created["id"],
                "u1",
                status="ready",
                image_job_id="job-master-1",
                image_url="https://cdn.example/front.png",
            )
            assets.add_media(created["id"], "u1", media_kind="reverse", slot="reverse", job_id="job-reverse-fail")

            class Jobs:
                def get(self, job_id):
                    if job_id == "job-reverse-fail":
                        return {
                            "id": job_id,
                            "status": JobStatus.FAILED.value,
                            "error": "内容未通过审核：请上传 REFERENCE 1",
                        }
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_asset_store = assets
            app.state.xiaji_project_store = projects
            app.state.store = Jobs()
            app.state.resource_storage = None
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.get(f"/api/xiaji/assets?project_id={project['id']}&kind=scene")
            self.assertEqual(response.status_code, 200)
            scene = response.json()[0]
            self.assertNotEqual((scene.get("definition") or {}).get("scene_jobs", {}).get("reverse"), "job-reverse-fail")
            reverse_media = next(item for item in scene["media"] if item["media_kind"] == "reverse")
            self.assertEqual(reverse_media.get("job_status"), JobStatus.FAILED.value)
            self.assertIn("REFERENCE 1", reverse_media.get("job_error") or "")


class DummyJobs:
    def get(self, job_id):
        raise KeyError(job_id)


class XiajiEpisodeTests(unittest.TestCase):
    def test_split_and_allocate_text(self) -> None:
        lines = split_original_lines("  甲\n\n乙  \n")
        self.assertEqual(lines, ["甲", "乙"])
        chunks = allocate_chapter_text(
            [{"content": "aaaaaaaaaa"}, {"content": "bbbbbbbbbb"}],
            2,
        )
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0])
        self.assertTrue(chunks[1])

    def test_normalize_script_beats_drops_unknown_speaker(self) -> None:
        beats = normalize_script_beats(
            {
                "beats": [
                    {"kind": "scene_heading", "int_ext": "外", "location": "巷口", "time_of_day": "夜"},
                    {"kind": "dialogue", "speaker": "路人", "text": "让开", "action": "有人拦路"},
                    {"kind": "action", "action": "谢铮拔刀"},
                ]
            },
            name_to_asset={("character", "谢铮"): "a1", ("scene", "巷口"): "s1"},
            allowed_speakers={"谢铮"},
        )
        self.assertEqual(beats[0]["kind"], "scene_heading")
        self.assertIn("巷口", beats[0]["heading"])
        self.assertEqual(beats[1]["kind"], "action")
        self.assertEqual(beats[2]["character_ids"], [])

    def test_from_analysis_and_delete_cascade(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, project = _xiaji_workspace(raw)
            created = ingest.create_from_text(
                "user-1",
                project_id=project["id"],
                filename="story.txt",
                title="测试",
                source_format="txt",
                original_text="第一章\n谢铮走进雨夜巷口，抽出瓷刀。",
            )
            ingest.save_analysis(
                created["id"],
                "user-1",
                {
                    "summary": "对峙",
                    "characters": [{"name": "谢铮", "is_main": True, "aliases": ["瓷孩儿"]}],
                    "scenes": [{"name": "雨夜巷口"}],
                    "props": [{"name": "瓷刀"}],
                    "episodes": [{"number": 1, "title": "巷口", "content_summary": "对峙", "main_conflict": "身份", "cliffhanger": "跟踪", "key_events": ["拔刀"]}],
                },
                logs=["ok"],
                model="test",
                status="indexed",
            )
            assets.sync_from_analysis(
                "user-1",
                ingest.get_document(created["id"], "user-1")["analysis"],
                project_id=project["id"],
                document_id=created["id"],
            )
            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_store = ingest
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_store = episodes
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            client = TestClient(app)
            response = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project['id']}", json={})
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(len(body), 1)
            self.assertEqual(body[0]["title"], "巷口")
            self.assertGreaterEqual(body[0]["line_count"], 1)
            self.assertGreaterEqual(body[0]["character_count"], 1)
            episode_id = body[0]["id"]
            other = FastAPI()
            other.state.xiaji_project_store = projects
            other.state.xiaji_store = ingest
            other.state.xiaji_asset_store = assets
            other.state.xiaji_episode_store = episodes
            other.state.store = DummyJobs()
            other.state.resource_storage = None
            register_xiaji_episode_routes(other, current_user=lambda: {"id": "user-2"}, mutating_user=lambda: {"id": "user-2"})
            forbidden = TestClient(other).get(f"/api/xiaji/episodes/{episode_id}")
            self.assertEqual(forbidden.status_code, 404)
            projects.delete_project(project["id"], "user-1")
            self.assertEqual(episodes.list_episodes("user-1", project["id"]), [])

    def test_generate_script_and_sketch_idempotent(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus

        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = ingest.create_from_text(
                "u1",
                project_id=project["id"],
                filename="story.txt",
                title="测试",
                source_format="txt",
                original_text="谢铮拔刀。",
            )
            ingest.save_analysis(
                created["id"],
                "u1",
                {
                    "episodes": [{"number": 1, "title": "巷口", "content_summary": "拔刀", "key_events": []}],
                    "characters": [{"name": "谢铮"}],
                    "scenes": [],
                    "props": [],
                },
                logs=[],
                model="m",
                status="indexed",
            )
            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_store = ingest
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_store = episodes
            app.state.store = DummyJobs()
            app.state.resource_storage = None

            class Llm:
                def generate_xiaji_script(self, payload):
                    return [{
                        "kind": "action",
                        "heading": "",
                        "speaker": "",
                        "dialogue": "",
                        "action": "谢铮拔刀",
                        "character_ids": [],
                        "scene_id": None,
                        "prop_ids": [],
                    }]

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                def __init__(self) -> None:
                    self.generation_ids: list[str] = []

                def enqueue_generation(self, item_id: str) -> None:
                    self.generation_ids.append(item_id)

                async def enqueue(self, job_id: str) -> None:
                    return None

            app.state.llm_provider = Llm()
            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project['id']}", json={}).json()
            episode_id = created_eps[0]["id"]
            script = client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
            self.assertEqual(script.status_code, 202, script.text)
            body = script.json()
            self.assertEqual(body["ok"], True)
            self.assertEqual(body["status"], "scripting")
            loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
            self.assertEqual(loaded["status"], "script_ready")
            self.assertEqual(loaded["beats"][0]["action"], "谢铮拔刀")
            beat_id = loaded["beats"][0]["id"]
            scene_id = next((item["asset_id"] for item in loaded["links"] if item["kind"] == "scene"), None)
            patched = client.patch(
                f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}",
                json={"action": "谢铮拔刀对峙", "scene_id": scene_id, "character_ids": [item["asset_id"] for item in loaded["links"] if item["kind"] == "character"]},
            )
            self.assertEqual(patched.status_code, 200, patched.text)
            self.assertEqual(patched.json()["beats"][0]["action"], "谢铮拔刀对峙")
            self.assertEqual(patched.json()["beats"][0]["scene_id"], scene_id)
            job = {
                "id": "job-sketch-1",
                "mode": "grs-gpt-image-2",
                "rounds": [{"generation_items": [{"id": "gen-1", "executor": "grs", "status": JobStatus.QUEUED.value}]}],
            }
            with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=job) as queued:
                first = client.post(
                    f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-sketch",
                    json={"scene_view": "front"},
                )
                second = client.post(f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-sketch", json={})
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()["job_id"], "job-sketch-1")
            self.assertFalse(first.json().get("reused"))
            self.assertEqual(second.status_code, 202)
            self.assertTrue(second.json().get("reused"))
            self.assertEqual(queued.call_count, 1)
            prompt = queued.call_args.kwargs["prompt"]
            self.assertNotIn("photoreal", prompt.lower())
            self.assertIn("storyboard", prompt.lower())
            self.assertEqual(queued.call_args.kwargs.get("references") or [], [])

            blocked_render = client.post(
                f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-render",
                json={},
            )
            self.assertEqual(blocked_render.status_code, 422, blocked_render.text)

            png = Path(raw) / "sketch.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            episodes.update_beat(beat_id, "u1", sketch_url="https://cdn.example/sketch.png", sketch_job_id="job-sketch-1", status="succeeded")
            render_job = {"id": "job-render-1", "mode": "grs-gpt-image-2"}
            with patch("backend.app.xiaji_episode_api._reference_paths", return_value=[str(png)]) as refs:
                with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=render_job) as queued_render:
                    rendered = client.post(
                        f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-render",
                        json={"scene_view": "front"},
                    )
            self.assertEqual(rendered.status_code, 202, rendered.text)
            self.assertEqual(rendered.json()["job_id"], "job-render-1")
            self.assertIn("SKETCH", queued_render.call_args.kwargs["prompt"])
            self.assertEqual(refs.call_args.kwargs.get("stage"), "render")
            self.assertEqual(queued_render.call_args.kwargs["references"][0], str(png))

            episodes.update_beat(beat_id, "u1", render_url="https://cdn.example/render.png", render_job_id="job-render-1")
            render_job_2 = {"id": "job-render-2", "mode": "grs-gpt-image-2"}
            with patch("backend.app.xiaji_episode_api._reference_paths", return_value=[str(png)]):
                with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=render_job_2) as queued_rerender:
                    rerendered = client.post(
                        f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-render",
                        json={"force": True, "scene_view": "front"},
                    )
            self.assertEqual(rerendered.status_code, 202, rerendered.text)
            self.assertEqual(rerendered.json()["job_id"], "job-render-2")
            self.assertFalse(rerendered.json().get("reused"))
            self.assertEqual(queued_rerender.call_count, 1)

            blocked_video = client.post(
                f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-video",
                json={},
            )
            self.assertEqual(blocked_video.status_code, 422, blocked_video.text)
            self.assertIn("渲染图", blocked_video.json()["detail"])

            episodes.update_beat(beat_id, "u1", render_url="https://cdn.example/render.png", render_job_id="job-render-1")
            video_job = {"id": "job-video-1", "mode": "minimax-h3-i2v"}
            with patch("backend.app.xiaji_episode_api._append_ref_file", side_effect=lambda app, paths, seen, **kwargs: paths.append(str(png))):
                with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=video_job) as queued_video:
                    video = client.post(
                        f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-video",
                        json={"family": "official_h3", "duration": 5},
                    )
            self.assertEqual(video.status_code, 202, video.text)
            self.assertEqual(video.json()["job_id"], "job-video-1")
            self.assertEqual(queued_video.call_args.kwargs["mode"], "minimax-h3-i2v")
            self.assertIn("first-frame", queued_video.call_args.kwargs["prompt"])
            self.assertEqual(queued_video.call_args.kwargs["options"]["duration"], 5.0)

            r2v_job = {"id": "job-video-r2v", "mode": "minimax-h3-lightx2v-r2v"}
            with patch("backend.app.xiaji_episode_api._append_ref_file", side_effect=lambda app, paths, seen, **kwargs: paths.append(str(png))):
                with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=r2v_job) as queued_r2v:
                    r2v = client.post(
                        f"/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-video",
                        json={
                            "force": True,
                            "family": "minimax-h3-lightx2v-r2v",
                            "duration": 5,
                            "quality": "0.2",
                            "speed": "balanced",
                            "aspect_ratio": "16:9",
                        },
                    )
            self.assertEqual(r2v.status_code, 202, r2v.text)
            self.assertEqual(queued_r2v.call_args.kwargs["mode"], "minimax-h3-lightx2v-r2v")
            self.assertIn("<Picture 1>", queued_r2v.call_args.kwargs["prompt"])
            self.assertEqual(queued_r2v.call_args.kwargs["options"]["duration"], 5.0)
            self.assertEqual(queued_r2v.call_args.kwargs["options"]["quality"], "0.2")
            self.assertEqual(queued_r2v.call_args.kwargs["options"]["speed"], "balanced")
            self.assertGreaterEqual(len(queued_r2v.call_args.kwargs["references"]), 1)

    def test_failed_render_job_clears_generating_status(self) -> None:
        from backend.app.models import JobStatus
        from backend.app.xiaji_episode_api import _hydrate_episode

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, _assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                sketch_url="https://cdn.example/sketch.png",
                sketch_job_id="job-sketch-ok",
                status="succeeded",
                render_job_id="ty2QwKPPsLQ",
                render_status="generating",
            )

            class Jobs:
                def get(self, job_id):
                    if job_id != "ty2QwKPPsLQ":
                        raise KeyError(job_id)
                    return {
                        "id": job_id,
                        "status": JobStatus.FAILED.value,
                        "error": "GRS 内容审核未通过",
                        "outputs": [],
                    }

            app = FastAPI()
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = _assets
            app.state.store = Jobs()
            app.state.resource_storage = None
            hydrated = _hydrate_episode(app, episodes.get_episode(created["id"], "u1"), "u1")
            beat = hydrated["beats"][0]
            self.assertEqual(beat["render_status"], "failed")
            self.assertEqual(beat["render_error"], "GRS 内容审核未通过")
            self.assertFalse(beat.get("render_url"))
            stored = episodes.get_episode(created["id"], "u1")["beats"][0]
            self.assertEqual(stored["render_status"], "failed")
            self.assertNotIn(stored["render_status"], {"queued", "generating"})

    def test_failed_video_job_clears_generating_status(self) -> None:
        from backend.app.models import JobStatus
        from backend.app.xiaji_episode_api import _hydrate_episode

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, _assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                sketch_url="https://cdn.example/sketch.png",
                status="succeeded",
                render_url="https://cdn.example/render.png",
                render_status="succeeded",
                video_job_id="T5qSf6xMCZce",
                video_status="generating",
            )

            class Jobs:
                def get(self, job_id):
                    if job_id != "T5qSf6xMCZce":
                        raise KeyError(job_id)
                    return {
                        "id": job_id,
                        "status": JobStatus.FAILED.value,
                        "error": "ComfyUI 已报告任务失败",
                        "outputs": [],
                    }

            app = FastAPI()
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = _assets
            app.state.store = Jobs()
            app.state.resource_storage = None
            hydrated = _hydrate_episode(app, episodes.get_episode(created["id"], "u1"), "u1")
            beat = hydrated["beats"][0]
            self.assertEqual(beat["video_status"], "failed")
            self.assertEqual(beat["video_error"], "ComfyUI 已报告任务失败")
            stored = episodes.get_episode(created["id"], "u1")["beats"][0]
            self.assertEqual(stored["video_status"], "failed")
            self.assertNotIn(stored["video_status"], {"queued", "generating"})

    def test_missing_video_job_clears_generating_status(self) -> None:
        from backend.app.xiaji_episode_api import _hydrate_episode

        with tempfile.TemporaryDirectory() as raw:
            _projects, _ingest, _assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                render_url="https://cdn.example/render.png",
                render_status="succeeded",
                video_job_id="T5qSf6xMCZce",
                video_status="generating",
            )

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = _assets
            app.state.store = Jobs()
            app.state.resource_storage = None
            hydrated = _hydrate_episode(app, episodes.get_episode(created["id"], "u1"), "u1", jobs_cache={})
            beat = hydrated["beats"][0]
            self.assertEqual(beat["video_status"], "failed")
            stored = episodes.get_episode(created["id"], "u1")["beats"][0]
            self.assertEqual(stored["video_status"], "failed")

    def test_video_prompt_accepts_post_not_get(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                render_url="https://cdn.example/render.png",
                render_status="succeeded",
            )

            class Llm:
                def availability(self):
                    return False, "大模型未配置"

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.store = Jobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            prefix = f"/api/xiaji/episodes/{created['id']}/beats/{beat_id}"
            for path in (f"{prefix}/video-prompt", f"{prefix}/generate-video-prompt"):
                get_resp = client.get(path)
                self.assertEqual(get_resp.status_code, 405, get_resp.text)
                post_resp = client.post(path, json={})
                self.assertNotEqual(post_resp.status_code, 405, post_resp.text)
                self.assertEqual(post_resp.status_code, 503, post_resp.text)

    def test_video_prompt_uses_selected_duration(self) -> None:
        from fastapi.testclient import TestClient
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            llm_jobs = XiajiLlmJobStore(Path(raw) / "xiaji.db")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "天空裂缝"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                render_url="https://cdn.example/render.png",
                render_status="succeeded",
            )
            captured: list[dict] = []

            class Llm:
                def availability(self):
                    return True, None

                def generate_xiaji_beat_video_prompt(self, payload):
                    captured.append(payload)
                    duration = payload.get("duration")
                    return {
                        "prompt_zh": f"持续 {duration:g} 秒",
                        "prompt_en": f"<Picture 1> holds for {duration:g} seconds",
                    }

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = Jobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            path = f"/api/xiaji/episodes/{created['id']}/beats/{beat_id}/video-prompt"
            response = client.post(path, json={"duration": 10, "family": "minimax-h3-lightx2v-r2v"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(captured[0]["duration"], 10)
            self.assertEqual(response.json()["episode"]["beats"][0]["video_duration"], "10")
            job = next(item for item in llm_jobs.list_project_jobs("u1", project["id"]) if item["kind"] == "video_prompt")
            self.assertEqual(job["options"]["duration"], 10)
            self.assertIn("指定时长：10 秒", job["prompt"])
            self.assertEqual(response.json()["episode"]["beats"][0].get("video_prompt_job_id"), job["id"])

    def test_later_beat_video_prompt_does_not_require_previous_video(self) -> None:
        from fastapi.testclient import TestClient
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            llm_jobs = XiajiLlmJobStore(Path(raw) / "xiaji.db")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["第一镜", "第二镜"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [
                    {"kind": "action", "action": "第一镜动作"},
                    {"kind": "action", "action": "第二镜动作"},
                ],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            first_id = episode["beats"][0]["id"]
            second_id = episode["beats"][1]["id"]
            episodes.update_beat(first_id, "u1", render_url="https://cdn.example/one.png", render_status="succeeded")
            episodes.update_beat(second_id, "u1", render_url="https://cdn.example/two.png", render_status="succeeded")

            class Llm:
                def availability(self):
                    return True, None

                def generate_xiaji_beat_video_prompt(self, payload):
                    return {"prompt_zh": "第二镜中文", "prompt_en": "<Picture 1> beat two"}

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = Jobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            response = client.post(
                f"/api/xiaji/episodes/{created['id']}/beats/{second_id}/generate-video-prompt",
                json={"duration": 5, "family": "minimax-h3-lightx2v-r2v"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["prompt_zh"], "第二镜中文")

    def test_hydrate_applies_latest_video_prompt_job(self) -> None:
        from backend.app.xiaji_episode_api import _hydrate_episode
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore, finish_xiaji_llm_job, start_xiaji_llm_job

        with tempfile.TemporaryDirectory() as raw:
            _projects, _ingest, _assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            llm_jobs = XiajiLlmJobStore(Path(raw) / "xiaji.db")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "天空裂缝"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            beat_id = episode["beats"][0]["id"]
            episodes.update_beat(
                beat_id,
                "u1",
                video_prompt_zh="自然视觉风格，无漫画字效。锁定英雄脸部。",
                video_prompt="Natural style. Lock the hero face.",
            )

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            app = FastAPI()
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = _assets
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = Jobs()
            app.state.resource_storage = None
            app.state.llm_provider = type("Llm", (), {})()
            job_id = start_xiaji_llm_job(
                app,
                owner_user_id="u1",
                project_id=project["id"],
                kind="video_prompt",
                target="镜头1",
                title="镜头视频提示词",
                messages=[{"role": "user", "content": "时长 10"}],
                parameters={"beat_id": beat_id, "episode_id": created["id"]},
                temperature=0.5,
                max_tokens=256,
            )
            finish_xiaji_llm_job(
                app,
                job_id,
                status="succeeded",
                response={
                    "prompt_zh": "Use <Picture 1> as 本镜精绘首帧。Use <Picture 2> as 齐静春 头像素材。",
                    "prompt_en": "Use <Picture 1> as first frame. Use <Picture 2> as 齐静春 portrait.",
                },
            )
            hydrated = _hydrate_episode(app, episodes.get_episode(created["id"], "u1"), "u1")
            beat = hydrated["beats"][0]
            self.assertIn("齐静春", beat["video_prompt_zh"])
            self.assertNotIn("英雄", beat["video_prompt_zh"])
            self.assertEqual(beat["video_prompt_job_id"], job_id)
            stored = episodes.get_episode(created["id"], "u1")["beats"][0]
            self.assertIn("齐静春", stored["video_prompt_zh"])

    def test_second_beat_video_requires_previous_clip_and_in_frame(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀", "对峙"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [
                    {"kind": "action", "action": "谢铮拔刀"},
                    {"kind": "action", "action": "对峙"},
                ],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            first_id = episode["beats"][0]["id"]
            second_id = episode["beats"][1]["id"]
            episodes.update_beat(
                first_id,
                "u1",
                render_url="https://cdn.example/r1.png",
                render_job_id="job-r1",
                render_status="succeeded",
            )
            episodes.update_beat(
                second_id,
                "u1",
                render_url="https://cdn.example/r2.png",
                render_job_id="job-r2",
                render_status="succeeded",
            )

            class Jobs:
                def get(self, job_id):
                    raise KeyError(job_id)

            class Stored:
                key = "in-frame-key"

            class Storage:
                def store_bytes(self, *_args, **_kwargs):
                    return Stored()

            class Worker:
                async def enqueue(self, job_id: str) -> None:
                    return None

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.store = Jobs()
            app.state.resource_storage = Storage()
            app.state.worker = Worker()
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            prefix = f"/api/xiaji/episodes/{created['id']}/beats/{second_id}"
            missing_prev = client.post(f"{prefix}/generate-video", json={"force": True})
            self.assertEqual(missing_prev.status_code, 422, missing_prev.text)
            self.assertIn("上一镜视频", missing_prev.json()["detail"])

            episodes.update_beat(
                first_id,
                "u1",
                video_url="https://cdn.example/v1.mp4",
                video_job_id="job-v1",
                video_status="succeeded",
            )
            missing_frame = client.post(f"{prefix}/generate-video", json={"force": True})
            self.assertEqual(missing_frame.status_code, 422, missing_frame.text)
            self.assertIn("衔接帧", missing_frame.json()["detail"])

            with patch("backend.app.xiaji_episode_api.resource_object_url", return_value="https://cdn.example/in.png"):
                uploaded = client.post(
                    f"{prefix}/upload-in-frame",
                    files={"file": ("in.png", TINY_PNG, "image/png")},
                    data={"manual": "1", "source_job_id": "job-v1", "sec": "4.9"},
                )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            second = uploaded.json()["beats"][1]
            self.assertEqual(second["video_in_frame_url"], "https://cdn.example/in.png")
            self.assertEqual(second["video_in_frame_manual"], "1")
            self.assertEqual(second["video_in_source_job_id"], "job-v1")

            png = Path(raw) / "frame.png"
            png.write_bytes(TINY_PNG)
            video_job = {"id": "job-video-2", "mode": "minimax-h3-lightx2v-r2v"}
            with patch(
                "backend.app.xiaji_episode_api._append_ref_file",
                side_effect=lambda app, paths, seen, **kwargs: paths.append(str(png)),
            ):
                with patch("backend.app.xiaji_episode_api.create_queued_job", return_value=video_job) as queued:
                    generated = client.post(
                        f"{prefix}/generate-video",
                        json={"force": True, "family": "minimax-h3-lightx2v-r2v", "duration": 5},
                    )
            self.assertEqual(generated.status_code, 202, generated.text)
            prompt = queued.call_args.kwargs["prompt"]
            self.assertIn("0-1.5s", prompt)
            self.assertIn("<Picture 1>", prompt)
            self.assertIn("<Picture 2>", prompt)

    def test_auto_run_conflict_and_sketch_gate(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus
        from backend.app.xiaji_auto_pipeline import XiajiAutoPipeline
        from backend.app.xiaji_episode_run_store import XiajiEpisodeRunStore
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            db_path = Path(raw) / "xiaji.db"
            runs = XiajiEpisodeRunStore(db_path)
            llm_jobs = XiajiLlmJobStore(db_path)
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}, {"kind": "action", "action": "对峙"}],
                status="script_ready",
            )

            class MemoryJobs:
                def __init__(self) -> None:
                    self.jobs: dict[str, dict] = {}

                def get(self, job_id):
                    return self.jobs[job_id]

            class Llm:
                def availability(self):
                    return True, None

                def generate_xiaji_beat_video_prompt(self, payload):
                    return {"prompt_zh": "中文稿", "prompt_en": "English prompt"}

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                async def enqueue(self, job_id: str) -> None:
                    return None

                def enqueue_generation(self, item_id: str) -> None:
                    return None

            class Stored:
                key = "in-frame-key"

            class Storage:
                def store_bytes(self, *_args, **_kwargs):
                    return Stored()

            jobs = MemoryJobs()
            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_run_store = runs
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = jobs
            app.state.resource_storage = Storage()
            app.state.llm_provider = Llm()
            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            pipeline = XiajiAutoPipeline(app, poll_interval=0.01, wait_timeout=0.05)
            app.state.xiaji_auto_pipeline = pipeline
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            seeded = runs.create(
                owner_user_id="u1",
                project_id=project["id"],
                episode_id=created["id"],
                video_params={"duration": 8},
            )
            runs.update(seeded["id"], status="running")
            blocked = client.post(
                f"/api/xiaji/episodes/{created['id']}/auto-run",
                json={"duration": 5},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            runs.update(seeded["id"], status="failed", error="stop", update_error=True)

            png = Path(raw) / "plate.png"
            png.write_bytes(TINY_PNG)
            queued_calls: list[dict] = []

            def fake_create(*_args, **kwargs):
                queued_calls.append(kwargs)
                job = {
                    "id": f"job-{len(queued_calls)}",
                    "status": JobStatus.QUEUED.value,
                    "mode": kwargs.get("mode"),
                    "options": kwargs.get("options"),
                    "title": kwargs.get("title"),
                    "outputs": [],
                }
                jobs.jobs[job["id"]] = job
                return job

            with patch.object(pipeline, "start"):
                started = client.post(
                    f"/api/xiaji/episodes/{created['id']}/auto-run",
                    json={"duration": 8, "family": "minimax-h3-lightx2v-r2v"},
                )
            self.assertEqual(started.status_code, 202, started.text)
            run_id = started.json()["run"]["id"]
            with patch("backend.app.xiaji_episode_api.create_queued_job", side_effect=fake_create):
                with patch("backend.app.xiaji_episode_api._reference_paths", return_value=[str(png)]):
                    import asyncio

                    asyncio.run(pipeline._run(run_id))
            self.assertEqual(len(queued_calls), 1)
            self.assertIn("草图", queued_calls[0]["title"])
            failed = client.get(f"/api/xiaji/episodes/{created['id']}/auto-run").json()["run"]
            self.assertEqual(failed["status"], "failed")
            self.assertIn("草图", failed["error"])

    def test_auto_run_locks_video_params_and_skips_ready_sketch(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from backend.app.models import JobStatus
        from backend.app.xiaji_auto_pipeline import XiajiAutoPipeline
        from backend.app.xiaji_episode_run_store import XiajiEpisodeRunStore
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, _ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
            db_path = Path(raw) / "xiaji.db"
            runs = XiajiEpisodeRunStore(db_path)
            llm_jobs = XiajiLlmJobStore(db_path)
            created = episodes.upsert_episode(
                "u1",
                project_id=project["id"],
                number=1,
                title="巷口",
                source_document_id=None,
                content_summary="",
                main_conflict="",
                cliffhanger="",
                key_events=[],
                original_lines=["谢铮拔刀"],
                overwrite_script=True,
            )
            episodes.replace_beats(
                created["id"],
                "u1",
                [{"kind": "action", "action": "谢铮拔刀"}, {"kind": "action", "action": "对峙"}],
                status="script_ready",
            )
            episode = episodes.get_episode(created["id"], "u1")
            first_id = episode["beats"][0]["id"]
            episodes.update_beat(first_id, "u1", sketch_url="https://cdn.example/s1.png", sketch_job_id="job-s0", status="succeeded")

            class MemoryJobs:
                def __init__(self) -> None:
                    self.jobs: dict[str, dict] = {}

                def get(self, job_id):
                    return self.jobs[job_id]

            class Llm:
                def availability(self):
                    return True, None

                def generate_xiaji_beat_video_prompt(self, payload):
                    return {"prompt_zh": f"时长{payload.get('duration')}", "prompt_en": f"hold {payload.get('duration')}s"}

            class Workflow:
                id = "grs-gpt-image-2"

            class Grs:
                def enabled_image_workflows(self):
                    return [Workflow()]

                def availability(self, _mode):
                    return True, None

            class Worker:
                async def enqueue(self, job_id: str) -> None:
                    return None

                def enqueue_generation(self, item_id: str) -> None:
                    return None

            class Stored:
                key = "in-frame-key"

            class Storage:
                def store_bytes(self, *_args, **_kwargs):
                    return Stored()

            png = Path(raw) / "plate.png"
            png.write_bytes(TINY_PNG)
            clip = Path(raw) / "clip.mp4"
            clip.write_bytes(b"fake-mp4")
            jobs = MemoryJobs()
            created_jobs: list[dict] = []

            def fake_create(*_args, **kwargs):
                created_jobs.append(kwargs)
                kind = "video" if "视频" in str(kwargs.get("title") or "") else "image"
                local = str(clip if kind == "video" else png)
                job = {
                    "id": f"job-{len(created_jobs)}",
                    "status": JobStatus.SUCCEEDED.value,
                    "mode": kwargs.get("mode"),
                    "options": kwargs.get("options"),
                    "title": kwargs.get("title"),
                    "outputs": [{"kind": kind, "cloud_url": f"https://cdn.example/{kind}-{len(created_jobs)}.{'mp4' if kind == 'video' else 'png'}", "path": local}],
                }
                jobs.jobs[job["id"]] = job
                return job

            def fake_extract(_src, dest: Path) -> None:
                dest.write_bytes(TINY_PNG)

            png = Path(raw) / "plate.png"
            png.write_bytes(TINY_PNG)
            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_run_store = runs
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = jobs
            app.state.resource_storage = Storage()
            app.state.llm_provider = Llm()
            app.state.grs_provider = Grs()
            app.state.worker = Worker()
            pipeline = XiajiAutoPipeline(app, poll_interval=0.01, wait_timeout=2, extract_frame=fake_extract)
            app.state.xiaji_auto_pipeline = pipeline
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
            client = TestClient(app)
            with patch.object(pipeline, "start"):
                started = client.post(
                    f"/api/xiaji/episodes/{created['id']}/auto-run",
                    json={
                        "duration": 8,
                        "family": "minimax-h3-lightx2v-r2v",
                        "quality": "0.2",
                        "aspect_ratio": "16:9",
                        "speed": "balanced",
                    },
                )
            self.assertEqual(started.status_code, 202, started.text)
            run_id = started.json()["run"]["id"]
            with patch("backend.app.xiaji_episode_api.create_queued_job", side_effect=fake_create):
                with patch("backend.app.xiaji_episode_api._reference_paths", return_value=[str(png)]):
                    with patch("backend.app.xiaji_episode_api._materialize_picture_slots", return_value=[str(png)]):
                        with patch("backend.app.xiaji_episode_api.resource_object_url", return_value="https://cdn.example/in.png"):
                            import asyncio

                            asyncio.run(pipeline._run(run_id))
            titles = [str(item.get("title") or "") for item in created_jobs]
            self.assertIn("渲染", created_jobs[0]["title"])
            self.assertTrue(any("草图" in title for title in titles[1:]))
            video_jobs = [item for item in created_jobs if "视频" in str(item.get("title") or "")]
            self.assertEqual(len(video_jobs), 2)
            for item in video_jobs:
                self.assertEqual((item.get("options") or {}).get("duration"), 8)
            done = client.get(f"/api/xiaji/episodes/{created['id']}/auto-run").json()["run"]
            self.assertEqual(done["status"], "succeeded")
            loaded = client.get(f"/api/xiaji/episodes/{created['id']}").json()
            self.assertTrue(loaded["beats"][0]["video_url"])
            self.assertTrue(loaded["beats"][1]["video_url"])
            self.assertTrue(loaded["beats"][1]["video_in_frame_url"])
            listed = client.get("/api/xiaji/jobs", params={"project_id": project["id"]})
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertTrue(any(item.get("slot") == "auto_run" for item in listed.json()))


class XiajiLiteralScriptTests(unittest.TestCase):
    def test_parse_bracket_and_simple_headings(self) -> None:
        bracket = parse_scene_heading_line("【外】巷口 夜")
        self.assertEqual(bracket["location"], "巷口")
        self.assertEqual(bracket["int_ext"], "外")
        simple = parse_scene_heading_line("雨夜巷口 日 内")
        self.assertEqual(simple["location"], "雨夜巷口")
        self.assertEqual(simple["int_ext"], "内")
        self.assertIsNone(parse_scene_heading_line("谢铮走进雨夜巷口，抽出瓷刀。"))

    def test_literal_one_line_one_beat_skips_heading_llm(self) -> None:
        calls: list[str] = []

        class Client:
            def chat_completion(self, messages, **_kwargs):
                user = messages[-1]["content"]
                calls.append(user)
                if "当前行：谢铮：让开" in user:
                    return '{"audio_type":"dialogue","speaker":"谢铮","visual_description":"{{谢铮}} 开口说话","scene_name":"","character_names":["谢铮"],"prop_names":["瓷刀"]}'
                return '{"audio_type":"silence","speaker":"","visual_description":"{{谢铮}} 拔出 [[瓷刀]]","scene_name":"巷口","character_names":["谢铮"],"prop_names":["瓷刀"]}'

        beats = generate_script_beats(
            Client(),
            "m",
            original_lines=["【外】巷口 夜", "人物：谢铮", "谢铮拔刀。", "谢铮：让开"],
            characters=["谢铮"],
            scenes=["巷口"],
            props=["瓷刀"],
            visual_style="guoman_fantasy",
            title="巷口",
            summary="对峙",
            name_to_asset={
                ("character", "谢铮"): "a1",
                ("scene", "巷口"): "s1",
                ("prop", "瓷刀"): "p1",
            },
        )
        self.assertEqual(len(beats), 3)
        self.assertEqual(beats[0]["kind"], "scene_heading")
        self.assertEqual(beats[0]["scene_id"], "s1")
        self.assertEqual(beats[1]["kind"], "action")
        self.assertIn("谢铮", beats[1]["action"])
        self.assertEqual(beats[1]["character_ids"], ["a1"])
        self.assertEqual(beats[1]["prop_ids"], ["p1"])
        self.assertEqual(beats[1]["scene_id"], "s1")
        self.assertEqual(beats[2]["kind"], "dialogue")
        self.assertEqual(beats[2]["speaker"], "谢铮")
        self.assertEqual(beats[2]["dialogue"], "让开")
        self.assertEqual(len(calls), 2)

    def test_literal_timeout_falls_back_without_failing_episode(self) -> None:
        from backend.app.llm_client import LlmError

        class Client:
            def chat_completion(self, messages, **_kwargs):
                raise LlmError("请求大模型服务超时（等待 90 秒仍无响应）。")

        beats = generate_script_beats(
            Client(),
            "m",
            original_lines=["谢铮：让开", "雨还在下。"],
            characters=["谢铮"],
            scenes=[],
            props=[],
            visual_style="",
            title="巷口",
            summary="",
            name_to_asset={("character", "谢铮"): "a1"},
        )
        self.assertEqual(len(beats), 2)
        self.assertEqual(beats[0]["kind"], "dialogue")
        self.assertEqual(beats[0]["dialogue"], "让开")
        self.assertEqual(beats[1]["kind"], "action")
        self.assertIn("雨还在下", beats[1]["action"])

    def test_unknown_dialogue_speaker_becomes_action(self) -> None:
        class Client:
            def chat_completion(self, messages, **_kwargs):
                return '{"audio_type":"dialogue","speaker":"路人","visual_description":"有人拦路喊话","scene_name":"","character_names":[],"prop_names":[]}'

        beats = generate_script_beats(
            Client(),
            "m",
            original_lines=["路人：让开"],
            characters=["谢铮"],
            scenes=[],
            props=[],
            visual_style="",
            title="巷口",
            summary="",
            name_to_asset={("character", "谢铮"): "a1"},
        )
        self.assertEqual(beats[0]["kind"], "action")
        self.assertEqual(beats[0]["speaker"], "")
        self.assertIn("有人拦路", beats[0]["action"])


class XiajiBeatPromptTests(unittest.TestCase):
    def test_sketch_is_storyboard_not_photoreal(self) -> None:
        from backend.app.xiaji_episode_prompts import beat_render_prompt, beat_sketch_prompt, beat_video_prompt, character_marker_color

        assets = [
            {"id": "c1", "name": "谢铮", "kind": "character", "definition": {"face_prompt": "sharp jaw"}},
            {"id": "s1", "name": "巷口", "kind": "scene", "definition": {"description": "雨夜石板路"}},
        ]
        beat = {
            "kind": "action",
            "heading": "",
            "action": "谢铮拔刀",
            "dialogue": "",
            "speaker": "",
            "character_ids": ["c1"],
            "scene_id": "s1",
            "prop_ids": [],
        }
        sketch = beat_sketch_prompt(beat, assets=assets, visual_style="chinese_period_drama", ethnicity="Chinese")
        self.assertNotIn("photoreal", sketch.lower())
        self.assertIn("storyboard", sketch.lower())
        hex_color, _name = character_marker_color("c1")
        self.assertIn(hex_color, sketch)
        self.assertNotIn("sharp jaw", sketch)
        render = beat_render_prompt(beat, assets=assets, visual_style="chinese_period_drama", ethnicity="Chinese")
        self.assertIn("Keep exact composition", render)
        self.assertIn("FACE then COSTUME", render)
        self.assertIn("sharp jaw", render)
        self.assertIn("photorealistic", render)
        video = beat_video_prompt(beat)
        self.assertIn("first-frame", video)
        self.assertIn("谢铮拔刀", video)
        r2v = beat_video_prompt(beat, route="r2v", picture_count=3)
        self.assertIn("<Picture 1>", r2v)
        self.assertIn("<Picture 3>", r2v)
        self.assertIn("谢铮拔刀", r2v)
        pictured = beat_video_prompt(
            beat,
            route="r2v",
            pictures=[
                {"tag": "<Picture 1>", "label_en": "first-frame render"},
                {"tag": "<Picture 2>", "label_en": "FACE lock"},
            ],
        )
        self.assertIn("<Picture 2> = FACE lock", pictured)

    def test_sketch_and_render_keep_anime_style_without_art_style(self) -> None:
        from backend.app.xiaji_episode_prompts import beat_render_prompt, beat_sketch_prompt, build_video_motion_messages

        assets = [
            {"id": "c1", "name": "谢铮", "kind": "character", "definition": {"face_prompt": "sharp jaw"}},
        ]
        beat = {
            "kind": "action",
            "action": "谢铮拔刀",
            "character_ids": ["c1"],
            "scene_id": "",
            "prop_ids": [],
        }
        sketch = beat_sketch_prompt(beat, assets=assets, visual_style="anime", ethnicity="Chinese")
        self.assertIn("ANIME", sketch)
        self.assertIn("cel animation", sketch.lower())
        render = beat_render_prompt(beat, assets=assets, visual_style="anime", ethnicity="Chinese")
        self.assertIn("ANIME", render)
        self.assertIn("cel-shading", render.lower())
        self.assertIn("NOT real people", render)
        self.assertNotIn("photorealistic, 8k", render)
        user = build_video_motion_messages(
            beat=beat,
            pictures=[{"tag": "<Picture 1>", "label_en": "first", "role": "first_frame", "name": "r"}],
            duration=5,
            visual_style="anime",
            route="r2v",
        )[1]["content"]
        self.assertIn("动漫风格", user)
        self.assertIn("cel animation", user.lower())
        self.assertIn("允许漫画字效", user)

    def test_render_uses_protagonist_art_style_and_not_live_person(self) -> None:
        from backend.app.xiaji_episode_prompts import beat_render_prompt

        assets = [
            {
                "id": "c-side",
                "name": "李宝瓶",
                "kind": "character",
                "definition": {"is_main": False, "art_style_id": "as_1001", "face_prompt": "女青年"},
            },
            {
                "id": "c-main",
                "name": "陈平安",
                "kind": "character",
                "definition": {
                    "is_main": True,
                    "art_style_id": "as_1008",
                    "face_prompt": "男性，youth，黑色短发",
                },
            },
        ]
        beat = {
            "kind": "action",
            "action": "陈平安 和 李宝瓶 在搏杀黑白双蟒",
            "character_ids": ["c-main", "c-side"],
            "scene_id": "",
            "prop_ids": [],
        }
        render = beat_render_prompt(beat, assets=assets, visual_style="", ethnicity="Chinese")
        self.assertIn("NOT real people", render)
        self.assertIn("陈平安", render)
        self.assertIn("warm 3D character animation", render)
        self.assertIn("温暖角色动画", render)
        self.assertNotIn("photorealistic, 8k", render)
        self.assertNotIn("epic cinematic scene", render)

    def test_video_motion_messages_use_requested_duration(self) -> None:
        from backend.app.xiaji_episode_prompts import build_video_motion_messages

        messages = build_video_motion_messages(
            beat={"action": "裂缝蔓延"},
            pictures=[{"tag": "<Picture 1>", "label_zh": "首帧", "label_en": "first", "role": "first_frame", "name": "r"}],
            duration=10,
            visual_style="",
            route="r2v",
        )
        user = messages[1]["content"]
        self.assertIn("指定时长：10 秒", user)
        self.assertNotIn("指定时长：5 秒", user)

    def test_video_motion_messages_name_each_picture_material(self) -> None:
        from backend.app.xiaji_episode_prompts import build_video_motion_messages, format_video_picture_catalog

        pictures = [
            {
                "tag": "<Picture 1>",
                "role": "first_frame",
                "material": "shot_render",
                "name": "本镜精绘首帧",
                "label_zh": "本镜精绘首帧",
                "label_en": "approved first-frame render",
                "detail_zh": "动作=天空裂缝出现",
            },
            {
                "tag": "<Picture 2>",
                "role": "portrait",
                "material": "character_portrait",
                "name": "齐静春",
                "label_zh": "齐静春 头像素材",
                "label_en": "character portrait still of 齐静春",
                "detail_zh": "外貌=白衣女修",
                "detail_en": "APPEARANCE=white-robed woman",
            },
            {
                "tag": "<Picture 3>",
                "role": "look",
                "material": "character_costume",
                "name": "齐静春·基础造型",
                "label_zh": "齐静春 造型素材「基础造型」",
                "label_en": "costume still of 齐静春 named 基础造型",
                "detail_zh": "服装=素白长裙",
            },
            {
                "tag": "<Picture 6>",
                "role": "scene",
                "material": "scene_plate",
                "name": "骊珠洞天",
                "label_zh": "场景「骊珠洞天」正面",
                "label_en": "front environment plate of 骊珠洞天",
                "detail_zh": "环境=洞府山门",
            },
        ]
        catalog = format_video_picture_catalog(pictures)
        self.assertIn("齐静春", catalog)
        self.assertIn("基础造型", catalog)
        self.assertIn("骊珠洞天", catalog)
        self.assertIn("character_portrait", catalog)
        messages = build_video_motion_messages(
            beat={"heading": "洞天", "action": "天空裂缝出现，地面震动", "dialogue": "", "speaker": ""},
            pictures=pictures,
            duration=10,
            visual_style="as_1001",
            route="r2v",
        )
        user = messages[1]["content"]
        self.assertIn("齐静春", user)
        self.assertIn("骊珠洞天", user)
        self.assertIn("天空裂缝出现", user)
        self.assertIn("【必须演出】", user)
        self.assertIn("MUST PLAY THIS ACTION", user)
        self.assertIn("史诗叙事电影", user)
        self.assertIn("禁止改成 hero", user)
        self.assertNotIn("rooftop", user.lower())
        self.assertIn("No <Audio n>", user)

    def test_video_motion_pair_requires_picture_tags(self) -> None:
        from backend.app.xiaji_episode_prompts import _normalize_video_motion_pair

        pictures = [{"tag": "<Picture 1>"}, {"tag": "<Picture 2>"}]
        pair = _normalize_video_motion_pair(
            {
                "prompt_zh": "用 <Picture 1> 作首帧，<Picture 2> 锁脸。",
                "prompt_en": "Use <Picture 1> as first frame and <Picture 2> to lock the face.",
            },
            pictures,
        )
        self.assertIn("<Picture 2>", pair["prompt_en"])
        filled_missing = _normalize_video_motion_pair(
            {"prompt_zh": "中文用 <Picture 1>。", "prompt_en": "Use <Picture 1> only."},
            pictures,
        )
        self.assertIn("<Picture 2>", filled_missing["prompt_en"])
        self.assertIn("<Picture 2>", filled_missing["prompt_zh"])

    def test_video_picture_slots_follow_r2v_order(self) -> None:
        from backend.app.xiaji_episode_api import _video_picture_slots

        look_id = "look-1"
        beat = {
            "id": "beat-1",
            "render_job_id": "job-render",
            "render_url": "https://cdn.example/render.png",
            "character_ids": ["c1"],
            "scene_id": "s1",
        }
        by_id = {
            "c1": {
                "id": "c1",
                "name": "谢铮",
                "definition": {
                    "gender": "男",
                    "face_prompt": "sharp jaw",
                    "looks": [{"id": look_id, "name": "夜行", "appearance_details": "黑衣佩刀", "job_id": "job-look", "image_url": "https://cdn.example/look.png"}],
                },
                "media": [
                    {"media_kind": "portrait", "slot": "portrait", "job_id": "job-face", "url": "https://cdn.example/face.png"},
                    {"media_kind": "look", "slot": look_id, "job_id": "job-look", "url": "https://cdn.example/look.png"},
                ],
            },
            "s1": {
                "id": "s1",
                "name": "巷口",
                "image_job_id": "job-scene",
                "image_url": "https://cdn.example/scene.png",
                "definition": {"description": "雨夜石板路", "scene_type": "exterior"},
            },
        }
        slots = _video_picture_slots(beat, by_id, scene_view="front", route="r2v")
        self.assertEqual([item["role"] for item in slots], ["first_frame", "portrait", "look", "scene"])
        self.assertEqual(slots[0]["tag"], "<Picture 1>")
        self.assertEqual(slots[1]["tag"], "<Picture 2>")
        self.assertIn("头像", slots[1]["label_zh"])
        self.assertIn("谢铮", slots[1]["label_en"])
        self.assertIn("谢铮", slots[1]["detail_zh"])
        self.assertIn("sharp jaw", slots[1]["detail_zh"])
        self.assertIn("夜行", slots[2]["detail_zh"])
        self.assertIn("黑衣佩刀", slots[2]["detail_zh"])
        self.assertIn("巷口", slots[3]["detail_zh"])
        self.assertIn("雨夜石板路", slots[3]["detail_zh"])
        self.assertEqual(slots[1]["material"], "character_portrait")
        self.assertEqual(slots[2]["material"], "character_costume")

    def test_video_picture_slots_put_bridge_before_render(self) -> None:
        from backend.app.xiaji_episode_api import _video_picture_slots, previous_video_beat

        episode = {
            "beats": [
                {"id": "a", "sequence": 1, "kind": "scene_heading", "heading": "", "action": ""},
                {"id": "b", "sequence": 2, "kind": "action", "action": "拔刀", "video_url": "https://cdn.example/v.mp4"},
                {"id": "c", "sequence": 3, "kind": "action", "action": "对峙"},
            ]
        }
        previous = previous_video_beat(episode, episode["beats"][2])
        self.assertEqual(previous["id"], "b")
        beat = {
            "id": "c",
            "render_job_id": "job-render",
            "render_url": "https://cdn.example/render.png",
            "video_in_frame_url": "https://cdn.example/in.png",
            "character_ids": [],
            "scene_id": None,
        }
        slots = _video_picture_slots(beat, {}, scene_view="front", route="r2v")
        self.assertEqual([item["role"] for item in slots], ["bridge_in", "shot_render"])
        self.assertEqual(slots[0]["url"], "https://cdn.example/in.png")
        self.assertEqual(slots[1]["url"], "https://cdn.example/render.png")
        i2v = _video_picture_slots(beat, {}, route="i2v")
        self.assertEqual([item["role"] for item in i2v], ["bridge_in"])

    def test_bridge_prompt_requires_timing(self) -> None:
        from backend.app.xiaji_episode_prompts import (
            _normalize_video_motion_pair,
            beat_video_prompt,
            build_video_motion_messages,
        )
        from backend.app.llm_client import LlmError

        pictures = [
            {"tag": "<Picture 1>", "role": "bridge_in", "name": "上一镜衔接帧", "label_en": "previous last frame"},
            {"tag": "<Picture 2>", "role": "shot_render", "name": "本镜精绘", "label_en": "current render"},
        ]
        templated = beat_video_prompt({"action": "对峙"}, route="r2v", pictures=pictures)
        self.assertTrue(templated.startswith("MUST PLAY THIS ACTION"))
        self.assertIn("对峙", templated)
        self.assertIn("0-1.5s", templated)
        self.assertIn("<Picture 2>", templated)
        messages = build_video_motion_messages(
            beat={"action": "对峙", "heading": "", "dialogue": "", "speaker": ""},
            pictures=pictures,
            duration=5,
            visual_style="",
            route="r2v",
        )
        self.assertIn("0-1.5s", messages[1]["content"])
        self.assertIn("CUT 1", messages[1]["content"])
        self.assertIn("220", messages[1]["content"])
        self.assertIn("CUT 1", messages[0]["content"])
        self.assertIn("不少于 220", messages[0]["content"])
        pair = _normalize_video_motion_pair(
            {
                "prompt_zh": "0-1.5s 用 <Picture 1> 过渡到 <Picture 2>，之后对峙。",
                "prompt_en": "From 0-1.5s transform <Picture 1> into <Picture 2>, then hold the standoff.",
            },
            pictures,
        )
        self.assertIn("0-1.5s", pair["prompt_en"])
        with self.assertRaises(LlmError):
            _normalize_video_motion_pair(
                {
                    "prompt_zh": "用 <Picture 1> 和 <Picture 2> 开拍。",
                    "prompt_en": "Use <Picture 1> and <Picture 2> as the first frame.",
                },
                pictures,
            )
        filled = _normalize_video_motion_pair(
            {
                "prompt_zh": "CUT 1：从精绘构图开始，陈平安跪在床前。",
                "prompt_en": "CUT 1: hold the first-frame blocking as Chen kneels.",
            },
            [
                {"tag": "<Picture 1>", "role": "first_frame", "name": "本镜精绘首帧", "label_zh": "本镜精绘首帧", "label_en": "approved first-frame render"},
                {"tag": "<Picture 2>", "role": "portrait", "name": "陈平安", "label_zh": "陈平安头像", "label_en": "portrait of 陈平安"},
                {"tag": "<Picture 3>", "role": "look", "name": "陈平安·基础造型", "label_zh": "基础造型", "label_en": "costume of 陈平安 named 基础造型"},
                {"tag": "<Picture 4>", "role": "scene", "name": "破屋内", "label_zh": "破屋内正面", "label_en": "front plate of 破屋内"},
            ],
        )
        self.assertIn("<Picture 2>", filled["prompt_en"])
        self.assertIn("<Picture 3>", filled["prompt_zh"])
        self.assertIn("破屋内", filled["prompt_en"])
        self.assertIn("陈平安", filled["prompt_zh"])

    def test_video_motion_leads_with_beat_action(self) -> None:
        from backend.app.xiaji_episode_prompts import _normalize_video_motion_pair

        pictures = [
            {"tag": "<Picture 1>", "role": "first_frame", "name": "本镜精绘首帧", "label_zh": "本镜精绘首帧", "label_en": "approved first-frame render"},
            {"tag": "<Picture 2>", "role": "portrait", "name": "顾粲", "label_zh": "顾粲头像", "label_en": "portrait of 顾粲"},
        ]
        pair = _normalize_video_motion_pair(
            {
                "prompt_zh": "用 <Picture 1> 作首帧。不得改变首帧站位。CUT 1 保持构图。",
                "prompt_en": "Use <Picture 1> as first frame. Lock composition and blocking. HOLD still.",
            },
            pictures,
            action="母亲咳血",
            dialogue="",
        )
        self.assertTrue(pair["prompt_zh"].startswith("【必须演出】母亲咳血"))
        self.assertTrue(pair["prompt_en"].upper().startswith("MUST PLAY THIS ACTION"))
        self.assertIn("母亲咳血", pair["prompt_en"])
        self.assertLess(pair["prompt_zh"].find("母亲咳血"), pair["prompt_zh"].find("<Picture 1>"))
        self.assertIn("<Picture 2>", pair["prompt_en"])


class XiajiLlmJobTests(unittest.TestCase):
    def test_ingest_and_script_jobs_appear_in_project_list(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, project = _xiaji_workspace(raw)
            llm_jobs = XiajiLlmJobStore(Path(raw) / "xiaji.db")

            class Llm:
                def analyze_xiaji_ingest(self, text, **kwargs):
                    return {
                        "summary": "雨夜对峙",
                        "characters": [{"name": "谢铮", "is_main": True, "aliases": []}],
                        "scenes": [{"name": "巷口"}],
                        "props": [{"name": "瓷刀"}],
                        "episodes": [{"number": 1, "title": "巷口", "content_summary": "对峙", "main_conflict": "身份", "cliffhanger": "跟踪", "key_events": ["拔刀"]}],
                        "model": "test-model",
                    }

                def generate_xiaji_script(self, payload):
                    self.last_payload = payload
                    return [{
                        "kind": "action",
                        "heading": "",
                        "speaker": "",
                        "dialogue": "",
                        "action": "谢铮拔刀",
                        "character_ids": [],
                        "scene_id": None,
                        "prop_ids": [],
                    }]

                def define_xiaji_voice(self, payload):
                    return {
                        "language": "中文普通话",
                        "timbre": "沉稳男中音",
                        "pitch": "适中",
                        "speaking_style": "克制",
                        "sample_line": "我是谢铮。",
                        "tts_voice": "onyx",
                        "prompt": "沉稳克制",
                    }

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_store = ingest
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            register_xiaji_episode_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            client = TestClient(app)
            pasted = client.post(
                "/api/xiaji/documents/paste",
                params={"project_id": project["id"]},
                json={
                    "text": "第一章 雨夜\n谢铮走进雨夜巷口，抽出瓷刀。",
                    "spine_template": "drama",
                    "visual_style": "chinese_period_drama",
                    "ethnicity": "Chinese",
                },
            )
            self.assertEqual(pasted.status_code, 201, pasted.text)
            created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project['id']}", json={}).json()
            episode_id = created_eps[0]["id"]
            script = client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
            self.assertEqual(script.status_code, 202, script.text)
            character = next(item for item in client.get("/api/xiaji/assets", params={"project_id": project["id"]}).json() if item["kind"] == "character")
            voice = client.post(f"/api/xiaji/assets/{character['id']}/define-voice")
            self.assertEqual(voice.status_code, 200, voice.text)
            listed = client.get("/api/xiaji/jobs", params={"project_id": project["id"]})
            self.assertEqual(listed.status_code, 200, listed.text)
            body = listed.json()
            by_slot = {item["slot"]: item for item in body}
            self.assertIn("ingest", by_slot)
            self.assertIn("script", by_slot)
            self.assertIn("voice", by_slot)
            ingest_job = by_slot["ingest"]
            self.assertEqual(ingest_job["status"], "succeeded")
            names = {item["name"] for item in ingest_job["parameters"]}
            self.assertIn("system_prompt", names)
            self.assertIn("messages", names)
            self.assertIn("original_text", names)
            self.assertIn("visual_style", names)
            self.assertIn("temperature", names)
            self.assertIn("response", names)
            self.assertIn("你负责小说/剧本导入", ingest_job["system_prompt"])
            self.assertIn("谢铮走进雨夜巷口", ingest_job["prompt"])
            self.assertEqual(ingest_job["options"]["visual_style"], "chinese_period_drama")
            script_job = by_slot["script"]
            script_names = {item["name"] for item in script_job["parameters"]}
            self.assertIn("original_lines", script_names)
            self.assertIn("逐行分镜标注师", script_job["system_prompt"])
            self.assertIn("谢铮拔刀", str(script_job["llm_output"]))
            voice_job = by_slot["voice"]
            self.assertIn("沉稳男中音", str(voice_job["llm_output"]))
            self.assertIn("你是影视配音导演", voice_job["system_prompt"])

    def test_failed_ingest_job_keeps_model_raw(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.llm_client import LlmError
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        with tempfile.TemporaryDirectory() as raw:
            projects, ingest, assets, episodes, project = _xiaji_workspace(raw)
            llm_jobs = XiajiLlmJobStore(Path(raw) / "xiaji.db")

            class Llm:
                def analyze_xiaji_ingest(self, text, **kwargs):
                    raise LlmError("大模型返回的分析结果不是合法 JSON", raw="<<<think>>> not json")

            app = FastAPI()
            app.state.xiaji_project_store = projects
            app.state.xiaji_store = ingest
            app.state.xiaji_asset_store = assets
            app.state.xiaji_episode_store = episodes
            app.state.xiaji_llm_job_store = llm_jobs
            app.state.store = DummyJobs()
            app.state.resource_storage = None
            app.state.llm_provider = Llm()
            register_xiaji_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            register_xiaji_asset_routes(app, current_user=lambda: {"id": "user-1"}, mutating_user=lambda: {"id": "user-1"})
            client = TestClient(app)
            pasted = client.post(
                "/api/xiaji/documents/paste",
                params={"project_id": project["id"]},
                json={"text": "第一章 雨夜\n谢铮走进巷口。", "spine_template": "drama"},
            )
            self.assertEqual(pasted.status_code, 201, pasted.text)
            listed = client.get("/api/xiaji/jobs", params={"project_id": project["id"]})
            self.assertEqual(listed.status_code, 200, listed.text)
            ingest_job = next(item for item in listed.json() if item.get("slot") == "ingest")
            self.assertEqual(ingest_job["status"], "failed")
            self.assertEqual(ingest_job["error"], "大模型返回的分析结果不是合法 JSON")
            self.assertIn("<<<think>>> not json", str(ingest_job["llm_output"]))


class XiajiComposeTests(unittest.TestCase):
    def test_srt_timeline(self) -> None:
        from backend.app.xiaji_compose import ComposeClip, build_srt_content, format_srt_time

        self.assertEqual(format_srt_time(0), "00:00:00,000")
        self.assertEqual(format_srt_time(5), "00:00:05,000")
        clips = [
            ComposeClip("a", 1, "一", "别动。", 5.0, Path("."), None, 0.0),
            ComposeClip("b", 2, "二", "走。", 3.0, Path("."), None, 5.0),
        ]
        text = build_srt_content(clips)
        self.assertIn("00:00:00,000 --> 00:00:05,000", text)
        self.assertIn("别动。", text)
        self.assertIn("00:00:05,000 --> 00:00:08,000", text)

    def _compose_app(self, raw: str, *, spine: str = "drama"):
        import subprocess

        from fastapi.testclient import TestClient

        from backend.app.resource_storage import StoredResource

        projects, ingest, assets, episodes, project = _xiaji_workspace(raw, owner="u1")
        if spine != "drama":
            projects.update_project(project["id"], "u1", settings={"spine_template": spine})
            project = projects.get_project(project["id"], "u1")
        created = ingest.create_from_text(
            "u1",
            project_id=project["id"],
            filename="story.txt",
            title="测试",
            source_format="txt",
            original_text="谢铮拔刀。",
        )
        ingest.save_analysis(
            created["id"],
            "u1",
            {
                "episodes": [{"number": 1, "title": "巷口", "content_summary": "拔刀", "key_events": []}],
                "characters": [{"name": "谢铮"}],
                "scenes": [],
                "props": [],
            },
            logs=[],
            model="m",
            status="indexed",
        )
        app = FastAPI()
        app.state.xiaji_project_store = projects
        app.state.xiaji_store = ingest
        app.state.xiaji_asset_store = assets
        app.state.xiaji_episode_store = episodes
        app.state.store = DummyJobs()
        staging = Path(raw) / "compose-storage"
        staging.mkdir()

        class FakeStorage:
            provider_id = "test"
            persistent_outputs = True

            def store_bytes(self, prefix, filename, content):
                key = f"{prefix}_{filename}"
                path = staging / key
                path.write_bytes(content)
                return StoredResource(key=key, local_path=path)

            def object_url(self, key):
                return f"https://cdn.test/{key}"

            def resolve(self, key):
                path = staging / key
                return path if path.is_file() else None

            def download_url(self, key, expires_in_seconds=300):
                return self.object_url(key)

        class Llm:
            def generate_xiaji_script(self, payload):
                return [{
                    "kind": "action",
                    "heading": "",
                    "speaker": "",
                    "dialogue": "别动。",
                    "action": "谢铮拔刀",
                    "character_ids": [],
                    "scene_id": None,
                    "prop_ids": [],
                }]

        class FakeFfmpeg:
            def __init__(self) -> None:
                self.commands: list[list[str]] = []

            def require(self):
                return "ffmpeg", "ffprobe"

            def run(self, args):
                self.commands.append(list(args))
                dest = Path(args[-1])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"fake-mp4-bytes")
                return subprocess.CompletedProcess(["ffmpeg", *args], 0, "", "")

            def probe_duration(self, path):
                return 5.0

            def probe_has_audio(self, path):
                return True

        app.state.resource_storage = FakeStorage()
        app.state.llm_provider = Llm()
        app.state.ffmpeg_runner = FakeFfmpeg()
        from backend.app.xiaji_llm_jobs import XiajiLlmJobStore

        app.state.xiaji_llm_job_store = XiajiLlmJobStore(Path(raw) / "xiaji.db")
        register_xiaji_episode_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
        register_xiaji_asset_routes(app, current_user=lambda: {"id": "u1"}, mutating_user=lambda: {"id": "u1"})
        return app, project["id"]

    def test_drama_missing_video_returns_422(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            app, project_id = self._compose_app(raw)
            with TestClient(app) as client:
                created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project_id}", json={}).json()
                episode_id = created_eps[0]["id"]
                script = client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
                self.assertEqual(script.status_code, 202, script.text)
                response = client.post(f"/api/xiaji/episodes/{episode_id}/compose", json={})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("视频", response.json()["detail"])

    def test_narrated_missing_audio_returns_422(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            app, project_id = self._compose_app(raw, spine="narrated")
            with TestClient(app) as client:
                created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project_id}", json={}).json()
                episode_id = created_eps[0]["id"]
                client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
                loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                beat_id = loaded["beats"][0]["id"]
                clip = Path(raw) / "shot.mp4"
                clip.write_bytes(b"video")
                app.state.xiaji_episode_store.update_beat(
                    beat_id, "u1", video_url=str(clip), video_duration="5", video_status="succeeded",
                )
                response = client.post(f"/api/xiaji/episodes/{episode_id}/compose", json={})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("配音", response.json()["detail"])

    def test_drama_compose_writes_url_and_srt(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            app, project_id = self._compose_app(raw)
            with TestClient(app) as client:
                created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project_id}", json={}).json()
                episode_id = created_eps[0]["id"]
                client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
                loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                beat_id = loaded["beats"][0]["id"]
                clip = Path(raw) / "shot.mp4"
                clip.write_bytes(b"video")
                app.state.xiaji_episode_store.update_beat(
                    beat_id, "u1", video_url=str(clip), video_duration="5", video_status="succeeded", dialogue="别动。",
                )
                response = client.post(
                    f"/api/xiaji/episodes/{episode_id}/compose",
                    json={"resolution": "1920x1080", "add_subtitles": True},
                )
                self.assertEqual(response.status_code, 202, response.text)
                self.assertTrue(response.json().get("job_id"))
                fetched = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                self.assertEqual(fetched["compose_status"], "succeeded")
                self.assertTrue(fetched["compose_url"])
                self.assertEqual(fetched["compose_resolution"], "1920x1080")
                self.assertTrue(fetched["compose_add_subtitles"])
                listed = client.get("/api/xiaji/jobs", params={"project_id": project_id})
                self.assertEqual(listed.status_code, 200, listed.text)
                compose_jobs = [item for item in listed.json() if item.get("slot") == "compose"]
                self.assertEqual(len(compose_jobs), 1, listed.text)
                self.assertEqual(compose_jobs[0]["status"], "succeeded")
                self.assertEqual(compose_jobs[0]["preview_url"], fetched["compose_url"])
                self.assertEqual(compose_jobs[0]["slot_label"], "合成成片")
                srt = client.get(f"/api/xiaji/episodes/{episode_id}/export/srt")
                self.assertEqual(srt.status_code, 200, srt.text)
                self.assertIn("别动。", srt.text)
                video = client.get(f"/api/xiaji/episodes/{episode_id}/export/video")
                self.assertEqual(video.status_code, 200, video.text)
                self.assertEqual(video.content, b"fake-mp4-bytes")

    def test_scene_heading_without_video_does_not_block_compose(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            app, project_id = self._compose_app(raw)
            with TestClient(app) as client:
                created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project_id}", json={}).json()
                episode_id = created_eps[0]["id"]
                client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
                loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                app.state.xiaji_episode_store.replace_beats(
                    episode_id,
                    "u1",
                    [
                        {"kind": "scene_heading", "heading": "外 巷口 夜", "action": "", "dialogue": ""},
                        {
                            "kind": "action",
                            "action": "谢铮拔刀",
                            "dialogue": "别动。",
                            "heading": "",
                        },
                    ],
                    status="script_ready",
                )
                loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                action = next(item for item in loaded["beats"] if item["kind"] == "action")
                clip = Path(raw) / "shot.mp4"
                clip.write_bytes(b"video")
                app.state.xiaji_episode_store.update_beat(
                    action["id"], "u1", video_url=str(clip), video_duration="5", video_status="succeeded",
                )
                fetched = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                self.assertTrue(fetched["compose_ready"], fetched.get("compose_blockers"))
                self.assertFalse(any(item["beat_id"] != action["id"] for item in fetched["compose_blockers"]))
                response = client.post(f"/api/xiaji/episodes/{episode_id}/compose", json={})
                self.assertEqual(response.status_code, 202, response.text)

    def test_compose_ready_with_partial_shot_videos(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as raw:
            app, project_id = self._compose_app(raw)
            with TestClient(app) as client:
                created_eps = client.post(f"/api/xiaji/episodes/from-analysis?project_id={project_id}", json={}).json()
                episode_id = created_eps[0]["id"]
                client.post(f"/api/xiaji/episodes/{episode_id}/generate-script")
                app.state.xiaji_episode_store.replace_beats(
                    episode_id,
                    "u1",
                    [
                        {"kind": "action", "action": "第一刀", "dialogue": "", "heading": ""},
                        {"kind": "action", "action": "第二刀", "dialogue": "", "heading": ""},
                    ],
                    status="script_ready",
                )
                loaded = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                first = loaded["beats"][0]
                clip = Path(raw) / "shot.mp4"
                clip.write_bytes(b"video")
                app.state.xiaji_episode_store.update_beat(
                    first["id"], "u1", video_url=str(clip), video_duration="5", video_status="succeeded",
                )
                fetched = client.get(f"/api/xiaji/episodes/{episode_id}").json()
                self.assertTrue(fetched["compose_ready"], fetched.get("compose_blockers"))
                self.assertTrue(fetched["compose_blockers"])
                response = client.post(f"/api/xiaji/episodes/{episode_id}/compose", json={})
                self.assertEqual(response.status_code, 202, response.text)


if __name__ == "__main__":
    unittest.main()
