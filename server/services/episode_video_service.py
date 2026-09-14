from __future__ import annotations

import hashlib
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from ..db import execute_sql, now_str, query_one
from .comfy_service import ComfyService
from .comfy_video_client import ComfyVideoClient
from .h3_prompt_builder import H3PromptBuilder
from .project_detail_service import ProjectDetailService
from .qiniu_service import QiniuService


_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="h3-video")


class EpisodeVideoService:
    DEFAULTS = {
        "workflow": "minimax_h3_director_ref2va",
        "duration_per_beat": 8,
        "fps": 24,
        "frames_per_beat": 192,
        "width": 864,
        "height": 480,
        "audio_mode": "generate",
        "seed": 888,
        "steps": 20,
        "sampler": "res_multistep",
        "scheduler": "simple",
    }

    @classmethod
    def create_job(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        llm = H3PromptBuilder.ensure_available()
        comfy_config = ComfyService.get_config()
        comfy = ComfyVideoClient(comfy_config.base_url)
        task_type = comfy.preflight()

        existing = query_one(
            """
            SELECT id FROM ai_project_jobs
            WHERE project_id = %s AND job_type = 'video_generation'
              AND status IN ('queued', 'preparing', 'prompt_generation', 'uploading', 'comfy_queued', 'running')
              AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.episode_id')) = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id, episode_id),
        )
        if existing:
            raise ValueError(f"该分集已有进行中的视频任务：{existing['id']}")

        detail = ProjectDetailService.get_episode_detail(project_id, episode_id)
        assets = ProjectDetailService.list_assets(project_id)
        shots = cls._prepare_shots(detail, assets)
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        payload = {
            **cls.DEFAULTS,
            "model": "MiniMax H3 Ref2VA",
            "api_endpoint": f"{comfy_config.base_url}/prompt",
            "target_type": "episode_video",
            "project_id": project_id,
            "episode_id": episode_id,
            "episode_number": detail.get("number"),
            "episode_title": detail.get("title") or "",
            "shot_count": len(shots),
            "total_frames": len(shots) * 192,
            "total_duration_seconds": len(shots) * 8,
            "llm_model": llm["model"],
            "comfy_base_url": comfy_config.base_url,
            "task_type": task_type,
            "source_shots": shots,
            "shots": [],
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'video_generation', %s, 'queued', 0, NULL, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                f"一键生成视频：第 {detail.get('number')} 集 {detail.get('title') or ''}",
                json.dumps(payload, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        _EXECUTOR.submit(cls._run_job, jid)
        return {"job_id": jid, "status": "queued"}

    @classmethod
    def retry_job(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT * FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if not row or row.get("job_type") != "video_generation":
            raise ValueError("视频任务不存在")
        if row.get("status") not in {"failed", "completed", "succeeded"}:
            raise ValueError("只有失败或已完成的视频任务可以重试")
        payload = json.loads(row.get("payload_json") or "{}")
        for key in (
            "shots", "llm_attempts", "prompt_generation_progress", "timeline", "workflow_request",
            "prompt_id", "client_id", "queue_number", "node_errors", "comfy_output",
            "director_report", "storage_warning", "failure_stage", "comfy_submission_count",
        ):
            payload.pop(key, None)
        payload["shots"] = []
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs SET status = 'queued', progress = 0, result_url = NULL,
              error_message = NULL, completed_at = NULL, payload_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (json.dumps(payload, ensure_ascii=False), timestamp, job_id, project_id),
        )
        _EXECUTOR.submit(cls._run_job, job_id)
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}

    @classmethod
    def recover_orphaned_jobs(cls) -> None:
        timestamp = now_str()
        execute_sql(
            """
            UPDATE ai_project_jobs
            SET status = 'failed', progress = 0,
                error_message = '服务进程重启，后台视频任务已中断，请点击重试。', updated_at = %s
            WHERE job_type = 'video_generation'
              AND status IN ('queued', 'preparing', 'prompt_generation', 'uploading', 'comfy_queued', 'running')
            """,
            (timestamp,),
        )

    @classmethod
    def _prepare_shots(cls, detail: dict[str, Any], assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        beats = sorted(detail.get("beats") or [], key=lambda item: int(item.get("sequence") or 0))
        if not beats:
            raise ValueError("该分集没有 Beat，无法生成视频。")
        by_id = {str(asset.get("id")): asset for asset in assets if asset.get("id")}
        protagonist = cls._episode_protagonist(beats, assets)
        if not protagonist:
            raise ValueError("无法确定分集主角，请为 Beat 关联主角资产。")
        missing: list[str] = []
        shots: list[dict[str, Any]] = []
        for beat in beats:
            sequence = int(beat.get("sequence") or len(shots) + 1)
            action = str(beat.get("video_prompt_zh") or beat.get("action") or "").strip()
            if not action:
                missing.append(f"Beat {sequence} 缺少动作或视频提示词")
            if not str(beat.get("camera") or "").strip():
                missing.append(f"Beat {sequence} 缺少运镜描述")
            if str(beat.get("dialogue") or "").strip() and not str(beat.get("speaker") or "").strip():
                missing.append(f"Beat {sequence} 有对白但缺少说话人")
            scene = by_id.get(str(beat.get("scene_id") or ""))
            scene_extra = (scene or {}).get("extra") if isinstance((scene or {}).get("extra"), dict) else {}
            scene_url = str(scene_extra.get("master_url") or (scene or {}).get("image_url") or "").strip()
            if not scene or not scene_url.startswith(("http://", "https://")):
                missing.append(f"Beat {sequence} 缺少 scene_id 对应的场景主视图")
            beat_characters = [
                by_id[str(asset_id)] for asset_id in (beat.get("character_ids") or [])
                if str(asset_id) in by_id and by_id[str(asset_id)].get("kind") == "character"
            ]
            if not beat_characters:
                beat_characters = [protagonist]
            character_references: list[dict[str, str]] = []
            for character in beat_characters:
                look = cls._select_character_look(character, beat)
                selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
                selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
                if not look:
                    if selected_look_id:
                        missing.append(f"Beat {sequence} 为「{character.get('name')}」选择的造型无效，请重新选择")
                    else:
                        missing.append(f"Beat {sequence} 缺少符合时代/年龄/服装的「{character.get('name')}」造型图")
                    continue
                character_url = str(look.get("image_url") or "").strip()
                if not character_url.startswith(("http://", "https://")):
                    missing.append(f"Beat {sequence} 的「{character.get('name')}」造型没有有效图片")
                    continue
                character_references.append({
                    "character_id": str(character.get("id") or ""),
                    "character_name": str(character.get("name") or ""),
                    "look_id": str(look.get("id") or ""),
                    "description": str(look.get("appearance_details") or look.get("description") or ""),
                    "url": character_url,
                })
            shots.append({
                "beat_id": str(beat.get("id") or f"beat-{sequence}"),
                "sequence": sequence,
                "heading": str(beat.get("heading") or ""),
                "action": action,
                "camera": str(beat.get("camera") or ""),
                "dialogue": str(beat.get("dialogue") or "").strip(),
                "narration": str(beat.get("narration") or beat.get("voiceover") or "").strip(),
                "speaker": str(beat.get("speaker") or "").strip(),
                "characters": [item["character_name"] for item in character_references],
                "props": beat.get("props") or [],
                "scene": str(beat.get("scene") or (scene or {}).get("name") or ""),
                "scene_id": str(beat.get("scene_id") or ""),
                "scene_description": str((scene or {}).get("description") or (scene or {}).get("visual_prompt") or ""),
                "character_id": str(protagonist.get("id") or ""),
                "character_name": str(protagonist.get("name") or ""),
                "character_look_id": next(
                    (item["look_id"] for item in character_references if item["character_id"] == str(protagonist.get("id") or "")),
                    "",
                ),
                "character_description": next(
                    (item["description"] for item in character_references if item["character_id"] == str(protagonist.get("id") or "")),
                    "",
                ),
                "character_references": character_references,
                "scene_picture_index": len(character_references) + 1,
                "reference_urls": [item["url"] for item in character_references] + [scene_url],
            })
        if missing:
            raise ValueError("视频生成前置检查失败：\n" + "\n".join(f"- {item}" for item in missing))
        return shots

    @staticmethod
    def _episode_protagonist(beats: list[dict[str, Any]], assets: list[dict[str, Any]]) -> dict[str, Any] | None:
        characters = [asset for asset in assets if asset.get("kind") == "character"]
        by_id = {str(asset.get("id")): asset for asset in characters}
        for beat in beats:
            for asset_id in beat.get("character_ids") or []:
                if str(asset_id) in by_id:
                    return by_id[str(asset_id)]
        searchable = " ".join(
            str(beat.get(key) or "") for beat in beats
            for key in ("heading", "speaker", "action", "dialogue")
        )
        return next((asset for asset in characters if str(asset.get("name") or "") in searchable), None)

    @staticmethod
    def _select_character_look(character: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any] | None:
        extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
        looks = [item for item in (extra.get("identities") or []) if isinstance(item, dict) and item.get("image_url")]
        selected_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
        selected_look_id = str(selected_ids.get(str(character.get("id") or "")) or "").strip()
        if selected_look_id:
            return next((item for item in looks if str(item.get("id") or "") == selected_look_id), None)
        legacy_look_id = str(beat.get("character_look_id") or "").strip()
        if legacy_look_id:
            legacy = next((item for item in looks if str(item.get("id") or "") == legacy_look_id), None)
            if legacy:
                return legacy
        context = " ".join(str(beat.get(key) or "") for key in (
            "heading", "action", "visual_prompt", "video_prompt_zh", "scene", "speaker"
        ))
        modern = bool(re.search(r"现代|大学|图书馆|电脑|西装|衬衫|研究生|26岁", context))
        ancient = bool(re.search(r"古代|茅屋|长衫|粗布|发髻|陶碗|木床|土墙|米缸|17岁", context))
        def description(item: dict[str, Any]) -> str:
            return " ".join(str(item.get(key) or "") for key in ("name", "description", "appearance_details"))
        if modern:
            return next((item for item in looks if re.search(r"现代|西装|衬衫|研究生|26岁", description(item))), None)
        if ancient:
            return next((item for item in looks if re.search(r"古代|长衫|粗布|发髻|17岁", description(item))), None)
        return looks[0] if len(looks) == 1 else None

    @classmethod
    def _run_job(cls, job_id: str) -> None:
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
            payload = json.loads(row.get("payload_json") or "{}")
            cls._set_state(job_id, payload, "preparing", 10)
            comfy = ComfyVideoClient(payload["comfy_base_url"])
            task_type = comfy.preflight()
            source_shots = payload.get("source_shots") or []

            payload["llm_attempts"] = []
            payload["prompt_generation_progress"] = {"completed": 0, "total": len(source_shots)}
            cls._set_state(job_id, payload, "prompt_generation", 20)

            def record_attempt(attempt: dict[str, Any]) -> None:
                payload["llm_attempts"].append(attempt)
                if attempt.get("status") == "passed":
                    payload["prompt_generation_progress"]["completed"] += 1
                total = max(1, int(payload["prompt_generation_progress"]["total"]))
                completed = int(payload["prompt_generation_progress"]["completed"])
                cls._set_state(job_id, payload, "prompt_generation", 20 + (completed * 9 // total))

            prompts = H3PromptBuilder.build_prompts(source_shots, on_attempt=record_attempt)

            generated_shots = []
            for shot, prompt in zip(source_shots, prompts):
                generated_shots.append({**shot, "prompt": prompt})
            payload["shots"] = generated_shots
            cls._set_state(job_id, payload, "uploading", 30)

            uploaded_cache: dict[str, dict[str, str]] = {}
            subfolder = f"zly-ai-media/{payload['project_id']}/{payload['episode_id']}/{job_id}"
            for shot in generated_shots:
                uploaded_refs = []
                for ref_index, url in enumerate(shot["reference_urls"], start=1):
                    if url not in uploaded_cache:
                        suffix = PurePosixPath(urlparse(url).path).suffix or ".png"
                        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
                        uploaded_cache[url] = comfy.upload_image(
                            url,
                            subfolder=subfolder,
                            preferred_name=f"beat-{shot['sequence']}-picture-{ref_index}-{digest}{suffix}",
                        )
                    uploaded_refs.append(uploaded_cache[url])
                shot["uploaded_refs"] = uploaded_refs

            timeline = comfy.build_timeline(generated_shots, task_type)
            workflow = comfy.build_workflow(
                timeline, task_type, f"video/{payload['project_id']}/{payload['episode_id']}/{job_id}"
            )
            payload["timeline"] = timeline
            payload["workflow_request"] = workflow
            submitted = comfy.submit(workflow)
            payload.update({
                "client_id": submitted["client_id"],
                "prompt_id": submitted["prompt_id"],
                "queue_number": submitted.get("number"),
                "node_errors": submitted.get("node_errors") or {},
                "comfy_submission_count": 1,
            })
            cls._set_state(job_id, payload, "comfy_queued", 40)
            cls._set_state(job_id, payload, "running", 50)
            history, output = comfy.wait_for_result(
                submitted["prompt_id"],
                progress=lambda value: cls._set_state(job_id, payload, "running", value),
            )
            payload["comfy_output"] = output
            payload["director_report"] = cls._director_report(history.get("outputs") or {})
            result_url = comfy.view_url(output)
            try:
                if QiniuService.get_config().available:
                    content = comfy.download_output(output)
                    _, result_url = QiniuService.store_bytes("video", output["filename"], content)
            except Exception as upload_error:
                payload["storage_warning"] = str(upload_error)
            timestamp = now_str()
            execute_sql(
                """
                UPDATE ai_project_jobs SET status = 'completed', progress = 100, result_url = %s,
                  payload_json = %s, error_message = NULL, completed_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
            )
        except Exception as err:
            timestamp = now_str()
            try:
                row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
                failed_payload = json.loads(row.get("payload_json") or "{}")
                failed_payload["failure_stage"] = failed_payload.get("runtime_stage") or "unknown"
                execute_sql(
                    """
                    UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                      payload_json = %s, updated_at = %s WHERE id = %s
                    """,
                    (str(err)[:4000], json.dumps(failed_payload, ensure_ascii=False), timestamp, job_id),
                )
            except Exception:
                execute_sql(
                    "UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s, updated_at = %s WHERE id = %s",
                    (str(err)[:4000], timestamp, job_id),
                )

    @staticmethod
    def _set_state(job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        payload["runtime_stage"] = status
        execute_sql(
            "UPDATE ai_project_jobs SET status = %s, progress = %s, payload_json = %s, updated_at = %s WHERE id = %s",
            (status, progress, json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @staticmethod
    def _director_report(outputs: dict[str, Any]) -> str:
        node = outputs.get("8") or {}
        values = node.get("text") or node.get("string") or []
        if isinstance(values, list):
            return "\n".join(str(value) for value in values)
        return str(values or "")
