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
from backend.app.xiaji_asset_prompts import character_portrait_prompt, prop_view_prompt, scene_master_prompt, scene_view_prompt
from backend.app.xiaji_asset_store import XiajiAssetStore
from backend.app.xiaji_episode_api import register_xiaji_episode_routes
from backend.app.xiaji_episode_prompts import normalize_script_beats
from backend.app.xiaji_episode_store import XiajiEpisodeStore, allocate_chapter_text, split_original_lines
from backend.app.xiaji_parser import extract_docx_text, parse_chapters
from backend.app.xiaji_project_store import XiajiProjectStore
from backend.app.xiaji_store import XiajiIngestStore
from backend.app.xiaji_analyze import define_voice_profile, normalize_analysis, parse_llm_json


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
                    "ingest_settings": {"visual_style": "chinese_period_drama"},
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
                "ingest_settings": {"visual_style": "chinese_period_drama", "ethnicity": "Chinese"},
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
            self.assertIn("写实古装剧", prompt)
            self.assertIn("窑火", scene_master_prompt(kinds["scene"]))
            reverse = scene_view_prompt(kinds["scene"], "reverse")
            pano = scene_view_prompt(kinds["scene"], "panorama")
            self.assertIn("FRONT-FACING", scene_master_prompt(kinds["scene"]))
            self.assertIn("yaw-rotate 180", reverse)
            self.assertIn("背面", reverse)
            self.assertNotEqual(scene_master_prompt(kinds["scene"]), reverse)
            self.assertIn("equirectangular", pano)
            self.assertIn("2:1", pano)
            master_prop = prop_view_prompt(kinds["prop"], "master")
            turnaround = prop_view_prompt(kinds["prop"], "turnaround")
            detail = prop_view_prompt(kinds["prop"], "detail")
            self.assertIn("本命瓷", master_prop)
            self.assertIn("hero product photograph", master_prop)
            self.assertNotIn("2x2", master_prop)
            self.assertIn("2x2 four-panel", turnaround)
            self.assertIn("BACK view", turnaround)
            self.assertIn("extreme close-up", detail)
            self.assertNotEqual(master_prop, turnaround)
            self.assertNotEqual(turnaround, detail)

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
            self.assertIn("yaw-rotate 180", prompt)
            self.assertIn("背面", prompt)

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
            self.assertIn("2x2 four-panel", prompt)
            self.assertIn("本命瓷", prompt)


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
        self.assertIn("sharp jaw", render)
        video = beat_video_prompt(beat)
        self.assertIn("first-frame", video)
        self.assertIn("谢铮拔刀", video)
        r2v = beat_video_prompt(beat, route="r2v", picture_count=3)
        self.assertIn("<Picture 1>", r2v)
        self.assertIn("<Picture 3>", r2v)
        self.assertIn("谢铮拔刀", r2v)


if __name__ == "__main__":
    unittest.main()
