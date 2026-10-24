from __future__ import annotations

import copy
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.local_media import LOCAL_MEDIA_PREFIX, path_for_url, url_for_path
from backend.app.media_studio.routers.smart_edit_router import register_smart_edit_routes
from backend.app.media_studio.services import smart_edit_service as service
from backend.app.media_studio.services.job_payload import serialize_job_row
from backend.app.media_studio.services.smart_edit_document import empty_document, validate_document, wrap_text
from backend.app.media_studio.services.smart_edit_render import export_jianying, export_otio, export_xml, probe, render_document


def fixture():
    doc = empty_document("测试剪辑")
    doc["assets"] = [{"id": "v1", "name": "镜头一", "kind": "video", "url": "https://media.example/source.mp4", "duration": 4}]
    doc["clips"] = [{"id": "c1", "asset_id": "v1", "track": "video", "start": 0, "duration": 2, "in_point": 1, "speed": 1}]
    return validate_document(doc)


class SmartEditDocumentTests(unittest.TestCase):
    def test_full_document_and_exchange_formats_keep_source_and_timeline_time(self):
        doc = fixture()
        doc["clips"][0].update(speed=2, duration=1)
        xml = ET.fromstring(export_xml(doc))
        clip = xml.find("sequence/media/video/track/clipitem")
        self.assertEqual((clip.findtext("start"), clip.findtext("end"), clip.findtext("in"), clip.findtext("out")), ("0", "24", "24", "72"))
        otio = export_otio(doc)
        item = otio["tracks"]["children"][0]["children"][0]
        self.assertEqual(item["source_range"]["duration"]["value"], 48)
        self.assertEqual(item["effects"][0]["time_scalar"], 2)

    def test_validation_rejects_invalid_ranges_nan_overlap_and_missing_assets(self):
        variants = []
        for key, value in (("duration", 9), ("start", -.1), ("speed", 0), ("volume", float("nan")), ("scale", float("inf")), ("effect", "custom-script"), ("start", .01)):
            doc = fixture(); doc["clips"][0][key] = value; variants.append(doc)
        doc = fixture(); doc["clips"].append({**doc["clips"][0], "id": "c2", "start": 1}); variants.append(doc)
        doc = fixture(); doc["assets"] = []; variants.append(doc)
        doc = fixture(); doc["assets"][0]["url"] = "file:///etc/passwd"; variants.append(doc)
        for doc in variants:
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                validate_document(doc)

    def test_validation_does_not_mutate_input_and_allows_independent_lanes(self):
        doc = fixture(); raw = copy.deepcopy(doc)
        validate_document(doc); self.assertEqual(doc, raw)
        doc["clips"].append({"id": "text", "track": "text", "start": 0, "duration": 1, "text": "你好 <测试> ' : %", "color": "#ffffff"})
        self.assertEqual(len(validate_document(doc)["clips"]), 2)

    def test_text_wrap_matches_browser_breaks_and_preserves_manual_lines(self):
        self.assertEqual(wrap_text("一二三四五六七八九十\n手动换行", 192), "一二三四五六七八\n九十\n手动换行")
        self.assertEqual(wrap_text("第一行\r\n\r\n第二行", 64), "第一行\n\n第二行")

    def test_bundle_has_lossless_json_and_relative_media_references(self):
        doc = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def resolve(asset, destination):
                destination = destination.with_suffix(".mp4"); destination.write_bytes(b"test"); return destination
            with patch.object(service, "download_asset", side_effect=resolve):
                output = service.write_bundle(doc, "xml", True, root)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(json.loads(archive.read("project.zly.json")), doc)
                self.assertIn("media/001.mp4", archive.namelist())
                self.assertIn("media/001.mp4", archive.read("timeline.xml").decode())

    def test_download_rejects_arbitrary_origins_before_any_network_access(self):
        with patch.object(service.QiniuService, "get_config", return_value=SimpleNamespace(domain="https://media.example")), patch.object(service.requests, "get") as request:
            for url in ("http://127.0.0.1/private", "https://evil.example/a.mp4", "https://media.example@evil.example/a.mp4"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    service.download_asset({"url": url, "kind": "video"}, Path("unused"))
            request.assert_not_called()

    def test_jianying_adapter_preserves_clip_time_speed_volume_and_canvas(self):
        doc = fixture()
        doc["clips"][0].update(start=2, duration=1, speed=2, muted=True, x=10, scale=1.2)
        meta, content = export_jianying(doc, {"v1": "media/001.mp4"})
        self.assertEqual(meta["draft_id"], content["id"])
        self.assertEqual(content["materials"]["videos"][0]["path"], "media/001.mp4")
        segment = content["tracks"][0]["segments"][0]
        self.assertEqual(segment["source_timerange"], {"start": 1_000_000, "duration": 2_000_000})
        self.assertEqual(segment["target_timerange"], {"start": 2_000_000, "duration": 1_000_000})
        self.assertEqual(segment["volume"], 0)
        self.assertEqual(segment["speed"], 2)
        self.assertEqual(segment["clip"]["scale"]["x"], 1.2)


class LocalMediaTests(unittest.TestCase):
    def test_signed_reference_roundtrip_rejects_tampering_and_foreign_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "镜头 01.mp4"
            source.write_bytes(b"local")
            with patch("backend.app.local_media._secret", return_value=b"test-secret"):
                url = url_for_path(source)
                self.assertTrue(url.startswith(LOCAL_MEDIA_PREFIX))
                self.assertEqual(path_for_url(url), source.resolve())
                forged = url[:-1] + ("0" if url[-1] != "0" else "1")
                with self.assertRaises(ValueError):
                    path_for_url(forged)
            with self.assertRaises(ValueError):
                path_for_url("/etc/passwd")

    def test_document_accepts_signed_shape_and_rejects_plain_local_paths(self):
        doc = fixture()
        doc["assets"][0]["url"] = f"{LOCAL_MEDIA_PREFIX}YWJj." + "a" * 32
        self.assertEqual(validate_document(doc)["assets"][0]["url"], doc["assets"][0]["url"])
        for url in ("/api/local-media/../secret", "/api/local-media/abc", "G:/video.mp4"):
            doc["assets"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_document(doc)

    def test_local_asset_resolution_never_copies_or_uses_network(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"local")
            with patch("backend.app.local_media._secret", return_value=b"test-secret"):
                url = url_for_path(source)
                with patch.object(service.requests, "get") as request:
                    resolved = service.download_asset({"url": url, "kind": "video"}, Path(directory) / "copy.media")
                request.assert_not_called()
            self.assertEqual(resolved, source.resolve())

    def test_import_local_requires_absolute_existing_paths_and_allows_admin_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "U02.mp4").write_bytes(b"not-a-real-video")
            with self.assertRaises(ValueError):
                service.import_local_media("U02.mp4", False, {"role": "super_admin"})
            with self.assertRaises(ValueError):
                service.import_local_media(str(folder / "missing.mp4"), False, {"role": "super_admin"})
            with patch("backend.app.local_media.import_roots", return_value=[]):
                with self.assertRaises(ValueError):
                    service.import_local_media(str(folder), False, {"role": "employee"})
            with patch.object(service, "probe", return_value={"duration": 3, "width": 1080, "height": 1920, "has_video": True, "has_audio": True}):
                with patch("backend.app.local_media._secret", return_value=b"test-secret"):
                    result = service.import_local_media(str(folder), False, {"role": "super_admin"})
            self.assertEqual([asset["name"] for asset in result["assets"]], ["U02.mp4"])
            self.assertEqual(result["assets"][0]["kind"], "video")
            self.assertIn("/api/local-media/", result["assets"][0]["url"])
            self.assertEqual(result["assets"][0]["local_path"], str(folder / "U02.mp4"))


class SmartEditPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE ai_smart_edit_documents (id TEXT PRIMARY KEY, project_id TEXT, owner_user_id TEXT, sequence_id TEXT, revision INTEGER, document_json TEXT, created_at TEXT, updated_at TEXT)")
        self.db.execute("CREATE TABLE ai_project_jobs (id TEXT PRIMARY KEY, project_id TEXT, job_type TEXT, title TEXT, status TEXT, progress INTEGER, payload_json TEXT, created_at TEXT, updated_at TEXT, result_url TEXT, completed_at TEXT, error_message TEXT)")
        self.addCleanup(self.db.close)
        self.addCleanup(patch.stopall)
        patch.object(service, "query_one", side_effect=self.query).start()
        patch.object(service, "execute_sql", side_effect=self.execute).start()
        patch.object(service.ProjectService, "get_project", return_value=SimpleNamespace(name="测试工程")).start()

    def query(self, sql, params=()):
        row = self.db.execute(sql.replace("%s", "?"), params).fetchone()
        return dict(row) if row else None

    def execute(self, sql, params=()):
        return self.db.execute(sql.replace("%s", "?"), params).rowcount

    def test_roundtrip_isolates_accounts_projects_and_episodes(self):
        self.assertEqual(service.read_document("p1", "alice", "ep1")["revision"], 0)
        service.save_document("p1", "alice", "ep1", 0, fixture())
        self.assertEqual(service.read_document("p1", "alice", "ep1")["document"], fixture())
        for args in (("p1", "bob", "ep1"), ("p2", "alice", "ep1"), ("p1", "alice", "ep2")):
            self.assertEqual(service.read_document(*args)["revision"], 0)

    def test_stale_writes_and_simultaneous_initial_saves_cannot_overwrite(self):
        service.save_document("p", "u", "ep", 0, fixture())
        with self.assertRaises(service.EditConflict):
            service.save_document("p", "u", "ep", 0, fixture())
        service.save_document("p", "u", "ep", 1, fixture())
        with self.assertRaises(service.EditConflict):
            service.save_document("p", "u", "ep", 1, fixture())
        self.assertEqual(service.read_document("p", "u", "ep")["revision"], 2)

    def test_export_keeps_private_snapshot_out_of_generic_job_payload(self):
        with patch.object(service.QiniuService, "get_config", return_value=SimpleNamespace(available=True)), patch.object(service.shutil, "which", return_value="ffmpeg"), patch.object(service._EXECUTOR, "submit"):
            self.addCleanup(service._ACTIVE.clear)
            job = service.create_export("p", "alice", fixture(), 720)
            row = self.query("SELECT * FROM ai_project_jobs WHERE id = %s", (job["id"],))
            payload = json.loads(row["payload_json"])
            self.assertNotIn("document", payload)
            self.assertNotIn("output_path", serialize_job_row(row, slim=True)["payload"])
            self.assertNotIn("output_path", serialize_job_row(row, slim=False)["payload"])
            self.assertEqual(service.read_document("p", "alice", payload["document_sequence"])["document"], fixture())
            with self.assertRaises(ValueError): service.get_export("p", "bob", job["id"])
            self.assertEqual(service.get_export("p", "alice", job["id"])["status"], "queued")
            service._ACTIVE.clear()
            self.assertEqual(service.get_export("p", "alice", job["id"])["status"], "failed")

    def test_export_needs_no_qiniu_and_serves_the_owner_a_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(service, "settings", SimpleNamespace(exports_dir=Path(directory))), \
                    patch.object(service.shutil, "which", return_value="ffmpeg"), patch.object(service._EXECUTOR, "submit"):
                self.addCleanup(service._ACTIVE.clear)
                job = service.create_export("p", "alice", fixture(), 720)
            self.execute("UPDATE ai_project_jobs SET status = 'completed', result_url = %s WHERE id = %s", ("/api/local", job["id"]))
            target = Path(directory) / "smart-edit" / f"{job['id']}.mp4"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"mp4")
            self.assertEqual(job["output_path"], str(target))
            self.assertEqual(service.export_file_path("p", "alice", job["id"]), target)
            with self.assertRaises(ValueError):
                service.export_file_path("p", "bob", job["id"])
            with self.assertRaises(ValueError):
                service.export_file_path("p", "alice", "../escape")

    def test_export_to_custom_directory_checks_absolute_paths_and_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "成片输出"
            admin = {"id": "alice", "role": "super_admin"}
            with patch.object(service.shutil, "which", return_value="ffmpeg"), patch.object(service._EXECUTOR, "submit"):
                self.addCleanup(service._ACTIVE.clear)
                job = service.create_export("p", "alice", fixture(), 1080, str(target_dir), admin)
            self.assertEqual(Path(job["output_path"]).parent, target_dir.resolve())
            self.assertTrue(job["output_path"].endswith(".mp4"))
            self.assertIn("测试剪辑", Path(job["output_path"]).name)
            self.assertEqual(service.get_export("p", "alice", job["id"])["output_path"], job["output_path"])
            with patch.object(service.shutil, "which", return_value="ffmpeg"), patch.object(service._EXECUTOR, "submit"):
                with self.assertRaises(ValueError):
                    service.create_export("p", "alice", fixture(), 720, "relative/output", admin)
                with patch("backend.app.local_media.import_roots", return_value=[]):
                    with self.assertRaises(ValueError):
                        service.create_export("p", "alice", fixture(), 720, str(root / "员工输出"), {"id": "eve", "role": "employee"})
                with patch("backend.app.local_media.import_roots", return_value=[root.resolve()]):
                    employee = service.create_export("p2", "eve", fixture(), 720, str(root / "员工输出"), {"id": "eve", "role": "employee"})
            self.assertEqual(Path(employee["output_path"]).parent, (root / "员工输出").resolve())
            job_file = Path(job["output_path"])
            job_file.parent.mkdir(parents=True, exist_ok=True)
            job_file.write_bytes(b"mp4")
            self.execute("UPDATE ai_project_jobs SET status = 'completed' WHERE id = %s", (job["id"],))
            self.assertEqual(service.export_file_path("p", "alice", job["id"]), job_file)

    def test_http_routes_apply_auth_csrf_dependency_and_conflict_status(self):
        app = FastAPI()
        def current(): return {"id": "alice"}
        def mutation(): return {"id": "alice"}
        register_smart_edit_routes(app, current_user=current, mutating_user=mutation)
        with TestClient(app) as client:
            path = "/api/projects/p/smart-edit/main"
            self.assertEqual(client.get(path).json()["revision"], 0)
            payload = {"revision": 0, "document": fixture()}
            self.assertEqual(client.put(path, json=payload).status_code, 200)
            self.assertEqual(client.put(path, json=payload).status_code, 409)
            self.assertEqual(client.get(path).json()["revision"], 1)
            self.assertEqual(client.post("/api/projects/p/smart-edit/exports/bundle", json={"document": fixture(), "format": "prproj"}).status_code, 400)
            response = client.post("/api/projects/p/smart-edit/exports/bundle", json={"document": fixture(), "format": "jianying"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "application/zip")
            with patch.object(service, "import_local_media", return_value={"path": "G:/media", "assets": [], "skipped": []}):
                response = client.post(path + "/import-local", json={"path": "G:/media", "recursive": True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["path"], "G:/media")
            self.assertEqual(client.get("/api/local-media/not-a-token").status_code, 404)
            with patch.object(service, "create_export", return_value={"id": "edit-" + "a" * 20, "status": "queued", "progress": 0, "output_path": "G:/out/clip.mp4"}) as create:
                response = client.post("/api/projects/p/smart-edit/exports/mp4", json={"document": fixture(), "quality": 720, "output_dir": "G:/out"})
            self.assertEqual(response.status_code, 202)
            create.assert_called_once_with("p", "alice", fixture(), 720, "G:/out", {"id": "alice"})
        from fastapi import HTTPException
        def denied(): raise HTTPException(401, "请先登录")
        app.dependency_overrides[current] = denied
        with TestClient(app) as client:
            self.assertEqual(client.get(path).status_code, 401)
        def invalid_csrf(): raise HTTPException(403, "CSRF 校验失败")
        app.dependency_overrides[mutation] = invalid_csrf
        with TestClient(app) as client:
            self.assertEqual(client.put(path, json=payload).status_code, 403)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class SmartEditRenderTests(unittest.TestCase):
    def test_real_export_trims_changes_speed_fills_gaps_renders_text_and_mixes_sound(self):
        with tempfile.TemporaryDirectory(prefix="zly-edit-test-") as directory:
            root = Path(directory)
            def ff(*args):
                subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, capture_output=True, timeout=60)
            source = root / "fixture.mp4"
            ff("-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source))
            image = root / "fixture.png"
            ff("-f", "lavfi", "-i", "color=c=blue:s=160x90", "-frames:v", "1", str(image))
            sound = root / "fixture.wav"
            ff("-f", "lavfi", "-i", "sine=frequency=880:duration=2", str(sound))
            doc = fixture()
            doc["assets"] += [{"id": "image", "name": "图", "kind": "image", "url": "https://media.example/a.png", "duration": 5}, {"id": "sound", "name": "配音", "kind": "audio", "url": "https://media.example/a.wav", "duration": 2}]
            doc["clips"][0].update(speed=2, duration=1, effect="mono", rotation=5, scale=.9, opacity=.8, fade_in=.1, fade_out=.1)
            doc["clips"] += [{"id": "c2", "asset_id": "image", "track": "video", "start": 1.5, "duration": 1}, {"id": "a1", "asset_id": "sound", "track": "audio", "start": 0, "duration": 2, "volume": .5}, {"id": "t1", "track": "text", "start": .5, "duration": 2, "text": "这是一段很长的中文字幕用于验证预览和实际导出使用相同的自动断行规则不会在成片中横向越界裁切。\n手动换行 : ' 100% <画面>", "font_size": 96, "fade_in": .2, "fade_out": .2}]
            sources = {"v1": source, "image": image, "sound": sound}
            stages = []
            output = render_document(doc, root, lambda a, _: sources[a["id"]], stages.append, quality=720)
            info = probe(output)
            self.assertEqual((info["width"], info["height"]), (1280, 720))
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"], 2.5, delta=.08)
            self.assertEqual(stages[-1], 95)
            # Decode the gap: it must remain black despite an audio-only lane.
            sample = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-ss", "1.25", "-i", str(output), "-frames:v", "1", "-vf", "crop=16:16:0:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=30).stdout
            self.assertLess(sum(sample) / len(sample), 8)


if __name__ == "__main__":
    unittest.main()
