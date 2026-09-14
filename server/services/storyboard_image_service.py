from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import settings
from ..crypto import CredentialManager
from ..db import execute_sql, now_str, query_all, query_one
from .episode_image_prompts import asset_to_prompt_dict, beat_reference_urls, beat_render_prompt, beat_sketch_prompt
from .grs_client import GrsClient, GrsError
from .qiniu_service import QiniuService


_EXECUTOR = ThreadPoolExecutor(max_workers=20, thread_name_prefix="storyboard-image")
_DISPATCH_LOCK = threading.Lock()
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
ACTIVE_STATUSES = {"preparing", "running", "storing"}


class StoryboardImageService:
    @classmethod
    def enqueue(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any], stage: str) -> dict[str, Any]:
        if stage not in {"sketch", "render"}:
            raise ValueError("stage 必须是 sketch 或 render")

        from .project_detail_service import ProjectDetailService

        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        beats = detail.get("beats") or []
        target = next((beat for beat in beats if beat.get("id") == beat_id), None)
        if not target:
            raise ValueError("分镜不存在")
        if target.get("kind") == "scene_heading" and not (target.get("action") or target.get("heading")):
            raise ValueError("这一条没有可生成的画面")
        if stage == "render" and not str(target.get("sketch_url") or "").strip():
            raise ValueError("请先生成草图")

        target_type = f"beat_{stage}"
        for row in query_all(
            "SELECT id, status, payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'image_generation' "
            "AND status IN ('queued','preparing','running','storing') ORDER BY created_at DESC",
            (project_id,),
        ):
            existing_payload = cls._payload(row)
            if existing_payload.get("target_type") == target_type and existing_payload.get("episode_id") == episode_id \
                    and existing_payload.get("beat_id") == beat_id:
                return {"job_id": row["id"], "beat_id": beat_id, "status": row["status"], "duplicate": True}

        scene_view = str(payload.get("scene_view") or "front").strip()
        if scene_view not in {"front", "reverse"}:
            scene_view = "front"
        style = ProjectDetailService._project_visual_settings(project_id, payload)
        raw_assets = ProjectDetailService.list_assets(project_id)
        prompt_assets = [asset_to_prompt_dict(row) for row in raw_assets]
        if stage == "render":
            cls._validate_render_looks(target, raw_assets)
            clean_prompt = beat_render_prompt(target, assets=prompt_assets, **style)
        else:
            clean_prompt = beat_sketch_prompt(target, assets=prompt_assets, **style)

        reference_urls = beat_reference_urls(target, raw_assets, stage=stage, scene_view=scene_view)
        if stage == "render" and not reference_urls:
            raise ValueError("无法读取草图文件，请重新生成草图")

        grs_model, _ = ProjectDetailService._resolve_grs_model(str(payload.get("model") or ""))
        grs_row = query_one("SELECT * FROM ai_grs_provider_settings WHERE id = 1") or {}
        grs_base_url = grs_row.get("base_url") or "https://grsai.dakka.com.cn"
        encrypted_key = grs_row.get("api_key_encrypted")
        api_key = CredentialManager(settings.credential_key).decrypt(encrypted_key) if encrypted_key else None
        if not api_key:
            raise ValueError("GRS 供应商 API Key 未配置")

        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        image_size = "1K"
        aspect_ratio = "2:3"
        job_payload = {
            "model": grs_model,
            "api_endpoint": f"{grs_base_url}/v1/api/generate",
            "image_size": image_size,
            "target_type": target_type,
            "project_id": project_id,
            "episode_id": episode_id,
            "beat_id": beat_id,
            "beat_sequence": target.get("sequence"),
            "scene_view": scene_view,
            "prompt": clean_prompt,
            "clean_prompt": clean_prompt,
            "aspect_ratio": aspect_ratio,
            "width": 768,
            "height": 1152,
            **style,
            "reply_type": "async",
            "reference_urls": reference_urls,
            "request_body": {
                "model": grs_model, "prompt": clean_prompt, "images": reference_urls,
                "aspectRatio": aspect_ratio, "imageSize": image_size, "replyType": "async",
            },
        }
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,'image_generation',%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, f"生成{'镜头草图' if stage == 'sketch' else '镜头渲染'}: 第 {detail['number']} 集 - Beat {target.get('sequence')} ({grs_model})",
             json.dumps(job_payload, ensure_ascii=False), timestamp, timestamp),
        )
        job_field = "sketch_job_id" if stage == "sketch" else "render_job_id"
        state_updates = {job_field: jid}
        if stage == "render":
            state_updates["render_status"] = "queued"
        ProjectDetailService._update_episode_beat_atomic(project_id, episode_id, beat_id, state_updates, initial_beats=beats)
        cls.kick()
        return {"job_id": jid, "beat_id": beat_id, "status": "queued"}

    @classmethod
    def enqueue_batch(cls, project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        stage = str(payload.get("stage") or "")
        beat_ids = payload.get("beat_ids") or []
        if not isinstance(beat_ids, list) or not beat_ids:
            raise ValueError("beat_ids 不能为空")
        jobs, skipped = [], []
        for beat_id in dict.fromkeys(str(item) for item in beat_ids):
            try:
                jobs.append(cls.enqueue(project_id, episode_id, beat_id, payload, stage))
            except Exception as err:
                skipped.append({"beat_id": beat_id, "reason": str(err)})
        return {"status": "queued", "stage": stage, "jobs": jobs, "skipped": skipped}

    @classmethod
    def kick(cls) -> None:
        if not _DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            limit = cls._limit()
            active_rows = query_all(
                "SELECT id,payload_json FROM ai_project_jobs WHERE job_type='image_generation' "
                "AND status IN ('preparing','running','storing')"
            )
            database_active = sum(
                1 for row in active_rows
                if cls._payload(row).get("target_type") in {"beat_sketch", "beat_render"}
            )
            with _ACTIVE_LOCK:
                capacity = max(0, limit - max(len(_ACTIVE), database_active))
            if not capacity:
                return
            rows = query_all(
                "SELECT id,payload_json FROM ai_project_jobs WHERE job_type = 'image_generation' AND status = 'queued' "
                "ORDER BY created_at ASC LIMIT 100"
            )
            for row in rows:
                if capacity <= 0:
                    break
                if cls._payload(row).get("target_type") not in {"beat_sketch", "beat_render"}:
                    continue
                jid = row["id"]
                if execute_sql(
                    "UPDATE ai_project_jobs SET status='preparing',progress=10,updated_at=%s WHERE id=%s AND status='queued'",
                    (now_str(), jid),
                ) != 1:
                    continue
                with _ACTIVE_LOCK:
                    _ACTIVE.add(jid)
                _EXECUTOR.submit(cls._run, jid)
                capacity -= 1
        finally:
            _DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        for row in query_all(
            "SELECT id,status,payload_json FROM ai_project_jobs WHERE job_type='image_generation' "
            "AND status IN ('queued','preparing','running','storing')"
        ):
            payload = cls._payload(row)
            if payload.get("target_type") not in {"beat_sketch", "beat_render"}:
                continue
            if row["status"] == "queued" or payload.get("remote_task_id"):
                execute_sql("UPDATE ai_project_jobs SET status='queued',progress=0,updated_at=%s WHERE id=%s", (now_str(), row["id"]))
            else:
                execute_sql(
                    "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                    ("服务重启时任务尚未记录上游任务 ID，为避免重复扣费，请手动重试。", now_str(), row["id"]),
                )
        cls.kick()

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (job_id, project_id))
        payload = cls._payload(row or {})
        if not row or payload.get("target_type") not in {"beat_sketch", "beat_render"}:
            raise ValueError("分镜图片任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的任务可以重试")
        return cls.enqueue(project_id, payload["episode_id"], payload["beat_id"], payload, payload["target_type"].removeprefix("beat_"))

    @classmethod
    def _run(cls, job_id: str) -> None:
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s", (job_id,)) or {}
            payload = cls._payload(row)
            grs_row = query_one("SELECT * FROM ai_grs_provider_settings WHERE id=1") or {}
            encrypted_key = grs_row.get("api_key_encrypted")
            api_key = CredentialManager(settings.credential_key).decrypt(encrypted_key) if encrypted_key else None
            if not api_key:
                raise ValueError("GRS 供应商 API Key 未配置")
            client = GrsClient(grs_row.get("base_url") or "https://grsai.dakka.com.cn", api_key)
            remote_task_id = payload.get("remote_task_id")
            if not remote_task_id:
                reference_images = []
                for ref_url in payload.get("reference_urls") or []:
                    ref_name, ref_bytes = client.download_image(ref_url)
                    reference_images.append(GrsClient.data_uri_from_bytes(ref_bytes, ref_name))
                remote_task_id = client.submit(
                    model=payload["model"], prompt=payload["clean_prompt"], aspect_ratio=payload["aspect_ratio"],
                    images=reference_images, image_size=payload.get("image_size"),
                )
                payload["remote_task_id"] = remote_task_id
                cls._set_state(job_id, payload, "running", 40)
            else:
                cls._set_state(job_id, payload, "running", 40)
            grs_url = client.wait_for_result(str(remote_task_id))
            cls._set_state(job_id, payload, "storing", 85)
            filename, content = client.download_image(grs_url)
            object_key, image_url = QiniuService.store_bytes("image", filename, content)
            payload.update({"grs_url": grs_url, "api_url": image_url, "object_key": object_key})
            cls._complete(job_id, payload, image_url)
        except Exception as err:
            message = f"GRS 生图失败: {err}" if isinstance(err, GrsError) else str(err)
            execute_sql(
                "UPDATE ai_project_jobs SET status='failed',progress=0,error_message=%s,updated_at=%s WHERE id=%s",
                (message[:4000], now_str(), job_id),
            )
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(job_id)
            cls.kick()

    @classmethod
    def _complete(cls, job_id: str, payload: dict[str, Any], image_url: str) -> None:
        from .project_detail_service import ProjectDetailService

        stage = payload["target_type"].removeprefix("beat_")
        updates = ({"sketch_url": image_url, "sketch_prompt": payload["clean_prompt"], "status": "sketched"}
                   if stage == "sketch" else
                   {"render_url": image_url, "render_prompt": payload["clean_prompt"], "render_status": "succeeded"})
        try:
            ProjectDetailService._update_episode_beat_atomic(
                payload["project_id"], payload["episode_id"], payload["beat_id"], updates,
                completed_job={"id": job_id, "result_url": image_url, "payload": payload},
                expected_job_id=job_id, expected_job_field=f"{stage}_job_id",
            )
        except ValueError as err:
            if "任务结果已过期" not in str(err):
                raise
            execute_sql(
                "UPDATE ai_project_jobs SET status='completed',progress=100,result_url=%s,payload_json=%s,"
                "error_message=%s,completed_at=%s,updated_at=%s WHERE id=%s",
                (image_url, json.dumps(payload, ensure_ascii=False), "结果已保留，但未覆盖较新的 Beat 任务。",
                 now_str(), now_str(), job_id),
            )

    @staticmethod
    def _set_state(job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        execute_sql(
            "UPDATE ai_project_jobs SET status=%s,progress=%s,payload_json=%s,updated_at=%s WHERE id=%s",
            (status, progress, json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(row.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _limit() -> int:
        row = query_one("SELECT max_storyboard_concurrency FROM ai_grs_provider_settings WHERE id=1") or {}
        return max(1, min(20, int(row.get("max_storyboard_concurrency") or 5)))

    @staticmethod
    def _validate_render_looks(beat: dict[str, Any], assets: list[dict[str, Any]]) -> None:
        if not beat.get("character_ids"):
            return
        by_id = {str(asset.get("id") or ""): asset for asset in assets}
        selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
        legacy = str(beat.get("character_look_id") or "")
        invalid = []
        for character_id in map(str, beat.get("character_ids") or []):
            character = by_id.get(character_id) or {}
            identities = (character.get("extra") or {}).get("identities") or []
            selected = str(selected_ids.get(character_id) or legacy)
            look = next((item for item in identities if str((item or {}).get("id") or "") == selected), None)
            if not str((look or {}).get("image_url") or "").startswith(("http://", "https://")):
                invalid.append(str(character.get("name") or character_id))
        if invalid:
            raise ValueError("请为当前分镜的出场角色选择有效服饰造型：" + "、".join(invalid))
