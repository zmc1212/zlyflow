from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from ..db import execute_sql, now_str, query_one
from .comfy_service import ComfyService
from .comfy_video_client import ComfyVideoClient
from .h3_prompt_builder import H3PromptBuilder
from .project_detail_service import ProjectDetailService
from .qiniu_service import QiniuService


_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="h3-video")
logger = logging.getLogger("server.video")


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
    def _parse_jjj_markdown(cls) -> dict[int, dict[int, str]]:
        candidates = [
            Path("doc/jjj.md"),
            Path(__file__).resolve().parents[2] / "doc" / "jjj.md",
        ]
        path = next((p for p in candidates if p.is_file()), None)
        if not path:
            return {}
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return {}

        ep_pattern = re.compile(r"^# 第(\d+)集[：:](.*?)(?=^# 第\d+集|^# |\Z)", re.MULTILINE | re.DOTALL)
        shot_pattern = re.compile(r"^### 镜头(\d+)[｜|](.*?)(?=^### 镜头|\Z)", re.MULTILINE | re.DOTALL)
        prompt_pattern = re.compile(r"- H3视频生成提示词[：:]\s*```(?:text)?\s*\n(.*?)\n```", re.DOTALL)

        result: dict[int, dict[int, str]] = {}
        for ep_match in ep_pattern.finditer(content):
            ep_num = int(ep_match.group(1))
            ep_body = ep_match.group(2)
            result[ep_num] = {}
            for shot_match in shot_pattern.finditer(ep_body):
                shot_num = int(shot_match.group(1))
                shot_body = shot_match.group(2)
                pm = prompt_pattern.search(shot_body)
                if pm:
                    result[ep_num][shot_num] = pm.group(1).strip()
        return result

    @classmethod
    def _load_jjj_prompts_for_shots(
        cls, episode_number: int, shots: list[dict[str, Any]]
    ) -> list[dict[str, str]] | None:
        parsed = cls._parse_jjj_markdown()
        ep_shots = parsed.get(episode_number)
        if not ep_shots:
            return None
        supplied: list[dict[str, str]] = []
        for shot in shots:
            seq = int(shot.get("sequence") or 0)
            prompt = ep_shots.get(seq)
            if not prompt:
                return None
            supplied.append({"beat_id": str(shot["beat_id"]), "prompt": prompt})
        return supplied

    @classmethod
    def create_job(
        cls,
        project_id: str,
        episode_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options = options or {}
        duration_per_beat = int(options.get("duration_per_beat") or cls.DEFAULTS["duration_per_beat"])
        if duration_per_beat < 1 or duration_per_beat > 30:
            raise ValueError("每镜头时长必须在 1 到 30 秒之间")

        # MiniMax H3 帧数对齐规则: frame_count = 17k + 5
        if options.get("frames_per_beat"):
            frames_per_beat = int(options["frames_per_beat"])
        else:
            n = max(5, round(duration_per_beat * 24))
            frames_per_beat = n + ((5 - n % 17) % 17)

        if frames_per_beat < 1:
            raise ValueError("每镜头帧数必须大于 0")

        # 镜头质量与分辨率/步数映射（与 ComfyUI minimax_h3_director_加速版.json 尺寸表与采样一致）
        quality_map = {
            "0.2": {"width": 608, "height": 352, "steps": 20},
            "0.4": {"width": 864, "height": 480, "steps": 20},
            "0.7": {"width": 1152, "height": 640, "steps": 20},
            "1.0": {"width": 1344, "height": 768, "steps": 25},
            "2.0": {"width": 1920, "height": 1088, "steps": 25},
        }
        quality_key = str(options.get("quality") or "0.4").strip()
        quality_config = quality_map.get(quality_key, quality_map["0.4"])
        width = int(options.get("width") or quality_config["width"])
        height = int(options.get("height") or quality_config["height"])
        steps = int(options.get("steps") or quality_config["steps"])

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
        shots = cls._prepare_shots(detail, assets, project_id=project_id)
        for shot in shots:
            shot["duration_seconds"] = duration_per_beat
            shot["frame_count"] = frames_per_beat

        supplied_prompts = options.get("prompts")
        prompt_source = str(options.get("prompt_source") or "").strip()

        # 1. 优先使用传入的 prompts 或分集各个 Beat 中已保存的 h3_prompt (素材组提示词)
        if supplied_prompts is None:
            beat_prompts = []
            for shot in shots:
                bid = str(shot["beat_id"])
                matching_beat = next((b for b in (detail.get("beats") or []) if str(b.get("id")) == bid), None)
                p = (matching_beat or {}).get("h3_prompt")
                if p and len(str(p).strip()) > 30:
                    beat_prompts.append({"beat_id": bid, "prompt": str(p).strip()})
            if len(beat_prompts) == len(shots):
                supplied_prompts = beat_prompts
                prompt_source = "workshop_material"

        # 2. 次选：如果分镜未存提示词，尝试加载 doc/jjj.md
        if supplied_prompts is None:
            ep_num = int(detail.get("number") or 1)
            jjj_supplied = cls._load_jjj_prompts_for_shots(ep_num, shots)
            if jjj_supplied:
                supplied_prompts = jjj_supplied
                prompt_source = "jjj_md"

        # 3. 兜底：若仍没有，调用配置的大模型现生成
        if supplied_prompts is None:
            llm = H3PromptBuilder.ensure_available()
            prompt_source = "configured_llm"
        else:
            prompt_source = prompt_source or "external"
            llm = {
                "model": "素材组直读 (免模型处理)"
                if prompt_source == "workshop_material"
                else (
                    "doc/jjj.md (直读 H3 提示词，免模型处理)"
                    if prompt_source == "jjj_md"
                    else str(options.get("prompt_model") or prompt_source)
                )
            }

        prompt_cache: dict[str, str] = {}
        if supplied_prompts is not None:
            if not isinstance(supplied_prompts, list):
                raise ValueError("预生成提示词必须是数组")
            supplied_by_id = {
                str(item.get("beat_id") or ""): str(item.get("prompt") or "").strip()
                for item in supplied_prompts if isinstance(item, dict)
            }
            expected_ids = [str(shot["beat_id"]) for shot in shots]
            if set(supplied_by_id) != set(expected_ids):
                raise ValueError("预生成提示词必须与当前分集的全部 Beat 一一对应")
            if prompt_source == "workshop_material":
                for bid in expected_ids:
                    p = supplied_by_id[bid]
                    if len(p) < 30:
                        raise ValueError(f"分镜 {bid} 的 H3 提示词过短，请先在素材组生成或填写完整提示词")
                prompt_cache = dict(zip(expected_ids, [supplied_by_id[bid] for bid in expected_ids]))
            else:
                speaker_map = H3PromptBuilder._speaker_map(shots)
                prompts = [supplied_by_id[beat_id] for beat_id in expected_ids]
                min_words = 150 if prompt_source == "jjj_md" else 280
                prompt_errors = H3PromptBuilder.validate_prompts(
                    shots, prompts, speaker_map, min_english_words=min_words
                )
                if prompt_errors:
                    raise ValueError("预生成提示词校验失败：\n- " + "\n- ".join(prompt_errors))
                prompt_cache = dict(zip(expected_ids, prompts))
        jid = f"job-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        payload = {
            **cls.DEFAULTS,
            "duration_per_beat": duration_per_beat,
            "frames_per_beat": frames_per_beat,
            "width": width,
            "height": height,
            "steps": steps,
            "quality": quality_key,
            "model": "MiniMax H3 Ref2VA",
            "api_endpoint": f"{comfy_config.base_url}/prompt",
            "target_type": "episode_video",
            "project_id": project_id,
            "episode_id": episode_id,
            "episode_number": detail.get("number"),
            "episode_title": detail.get("title") or "",
            "shot_count": len(shots),
            "total_frames": len(shots) * frames_per_beat,
            "total_duration_seconds": len(shots) * duration_per_beat,
            "llm_model": llm["model"],
            "prompt_source": prompt_source,
            "comfy_base_url": comfy_config.base_url,
            "task_type": task_type,
            "source_shots": shots,
            "shots": [],
        }
        if prompt_cache:
            payload["prompt_cache"] = prompt_cache
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
        logger.info("video job queued %s episode=%s shots=%s", jid, episode_id, len(shots))
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
        prompt_cache = {
            str(item.get("beat_id")): str(item.get("prompt") or "")
            for item in (payload.get("llm_attempts") or [])
            if item.get("status") == "passed" and item.get("prompt")
        }
        for key in (
            "shots", "llm_attempts", "prompt_generation_progress", "timeline", "workflow_request",
            "prompt_id", "client_id", "queue_number", "node_errors", "comfy_output",
            "director_report", "storage_warning", "failure_stage", "comfy_submission_count",
        ):
            payload.pop(key, None)
        payload["shots"] = []
        if prompt_cache:
            payload["prompt_cache"] = prompt_cache
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
    def _prepare_shots(cls, detail: dict[str, Any], assets: list[dict[str, Any]], project_id: str = "") -> list[dict[str, Any]]:
        beats = sorted(detail.get("beats") or [], key=lambda item: int(item.get("sequence") or 0))
        if not beats:
            raise ValueError("该分集没有 Beat，无法生成视频。")
        by_id = {str(asset.get("id")): asset for asset in assets if asset.get("id")}
        protagonist = cls._episode_protagonist(beats, assets)
        if not protagonist:
            raise ValueError("无法确定分集主角，请为 Beat 关联主角资产。")
        missing: list[str] = []
        missing_scene_assets: dict[str, dict[str, Any]] = {}
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
            scene_id = str(beat.get("scene_id") or "").strip()
            scene = by_id.get(scene_id)
            scene_extra = (scene or {}).get("extra") if isinstance((scene or {}).get("extra"), dict) else {}
            scene_url = str(scene_extra.get("master_url") or (scene or {}).get("image_url") or "").strip()
            if not scene:
                missing.append(f"Beat {sequence} 缺少 scene_id 对应的场景主视图")
            elif not scene_url.startswith(("http://", "https://")):
                missing.append(f"Beat {sequence} 缺少 scene_id 对应的场景主视图")
                missing_scene_assets[str(scene.get("id") or scene_id)] = scene
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
            # 3. 出场道具参考图 (Props)
            prop_references: list[dict[str, str]] = []
            for pid in (beat.get("prop_ids") or []):
                p_asset = by_id.get(str(pid))
                if p_asset and p_asset.get("kind") == "prop":
                    extra = p_asset.get("extra") if isinstance(p_asset.get("extra"), dict) else {}
                    p_url = str(p_asset.get("image_url") or extra.get("reference_url") or extra.get("master_url") or "").strip()
                    if p_url.startswith(("http://", "https://")):
                        prop_references.append({
                            "prop_id": str(pid),
                            "prop_name": str(p_asset.get("name") or "道具"),
                            "url": p_url,
                        })
            for pname in (beat.get("props") or []):
                if not any(item["prop_name"] == pname for item in prop_references):
                    p_asset = next((a for a in assets if a.get("kind") == "prop" and a.get("name") == pname), None)
                    if p_asset:
                        extra = p_asset.get("extra") if isinstance(p_asset.get("extra"), dict) else {}
                        p_url = str(p_asset.get("image_url") or extra.get("reference_url") or extra.get("master_url") or "").strip()
                        if p_url.startswith(("http://", "https://")):
                            prop_references.append({
                                "prop_id": str(p_asset.get("id") or ""),
                                "prop_name": pname,
                                "url": p_url,
                            })

            shots.append({
                "beat_id": str(beat.get("id") or f"beat-{sequence}"),
                "sequence": sequence,
                "heading": str(beat.get("heading") or ""),
                "action": action,
                "camera": str(beat.get("camera") or ""),
                "dialogue": str(beat.get("dialogue") or "").strip(),
                "dialogue_turns": beat.get("dialogue_turns") if isinstance(beat.get("dialogue_turns"), list) else [],
                "visible_text": str(beat.get("visible_text") or "").strip(),
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
                "prop_references": prop_references,
                "scene_picture_index": len(character_references) + 1,
                "reference_urls": (
                    [item["url"] for item in character_references]
                    + [scene_url]
                    + [item["url"] for item in prop_references]
                ),
            })
        if missing:
            queued = cls._enqueue_missing_scene_masters(project_id or str(detail.get("project_id") or ""), missing_scene_assets)
            if queued:
                names = "、".join(item["name"] for item in queued)
                missing.append(f"已自动提交场景主视图任务：{names}。请在「全部任务」查看进度，完成后再生成视频")
            raise ValueError("视频生成前置检查失败：\n" + "\n".join(f"- {item}" for item in missing))
        return shots

    @classmethod
    def _enqueue_missing_scene_masters(
        cls,
        project_id: str,
        scenes: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not project_id or not scenes:
            return []
        queued: list[dict[str, Any]] = []
        for asset_id, scene in scenes.items():
            extra = scene.get("extra") if isinstance(scene.get("extra"), dict) else {}
            prompt = str(
                extra.get("environment_prompt") or scene.get("visual_prompt") or scene.get("description") or scene.get("name") or ""
            ).strip()
            try:
                result = ProjectDetailService.generate_asset_image(
                    project_id,
                    asset_id,
                    {
                        "enqueue": True,
                        "target_type": "scene_master",
                        "prompt": prompt,
                        "model": "gpt-image-2",
                        "aspect_ratio": "16:9",
                    },
                    enqueue_only=True,
                )
            except Exception:
                continue
            queued.append({
                "asset_id": asset_id,
                "name": str(scene.get("name") or asset_id),
                "job_id": result.get("job_id"),
                "duplicate": bool(result.get("duplicate")),
            })
        return queued

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
        char_image = str(character.get("image_url") or "").strip()
        looks = []
        for item in (extra.get("identities") or []):
            if isinstance(item, dict):
                img = str(item.get("image_url") or "").strip() or char_image
                if img:
                    looks.append({**item, "image_url": img})
        if not looks and char_image:
            looks.append({
                "id": str(character.get("id") or ""),
                "name": str(character.get("name") or ""),
                "image_url": char_image,
                "appearance_details": str(character.get("description") or character.get("visual_prompt") or ""),
            })
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
        logger.info("video job start %s", job_id)
        try:
            row = query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
            payload = json.loads(row.get("payload_json") or "{}")
            cls._set_state(job_id, payload, "preparing", 10)
            comfy = ComfyVideoClient(payload["comfy_base_url"])
            task_type = comfy.preflight()
            source_shots = payload.get("source_shots") or []

            payload["llm_attempts"] = []
            prompt_cache = payload.get("prompt_cache") if isinstance(payload.get("prompt_cache"), dict) else {}
            speaker_map = H3PromptBuilder._speaker_map(source_shots)
            cached_prompts = {
                str(shot["beat_id"]): str(prompt_cache.get(str(shot["beat_id"])) or "")
                for shot in source_shots
            }
            if payload.get("prompt_source") == "workshop_material":
                cached_prompts = {
                    beat_id: prompt for beat_id, prompt in cached_prompts.items()
                    if prompt and len(prompt.strip()) >= 30
                }
            else:
                min_words = 150 if payload.get("prompt_source") == "jjj_md" else 280
                cached_prompts = {
                    beat_id: prompt for beat_id, prompt in cached_prompts.items()
                    if prompt and not H3PromptBuilder.validate_prompts(
                        [next(shot for shot in source_shots if str(shot["beat_id"]) == beat_id)],
                        [prompt],
                        speaker_map,
                        min_english_words=min_words,
                    )
                }
            payload["prompt_generation_progress"] = {
                "completed": len(cached_prompts), "total": len(source_shots)
            }
            cls._set_state(job_id, payload, "prompt_generation", 20)
            logger.info("video job %s stage=prompt_generation shots=%s", job_id, len(source_shots))

            def record_attempt(attempt: dict[str, Any]) -> None:
                payload["llm_attempts"].append(attempt)
                if attempt.get("status") == "passed":
                    payload["prompt_generation_progress"]["completed"] += 1
                total = max(1, int(payload["prompt_generation_progress"]["total"]))
                completed = int(payload["prompt_generation_progress"]["completed"])
                cls._set_state(job_id, payload, "prompt_generation", 20 + (completed * 9 // total))

            missing_shots = [
                shot for shot in source_shots if str(shot["beat_id"]) not in cached_prompts
            ]
            generated_prompts = H3PromptBuilder.build_prompts(
                missing_shots, on_attempt=record_attempt, speaker_map=speaker_map
            )
            generated_by_id = {
                str(shot["beat_id"]): prompt
                for shot, prompt in zip(missing_shots, generated_prompts)
            }
            prompts = [
                cached_prompts.get(str(shot["beat_id"]))
                or generated_by_id[str(shot["beat_id"])]
                for shot in source_shots
            ]
            payload.pop("prompt_cache", None)

            generated_shots = []
            for shot, prompt in zip(source_shots, prompts):
                generated_shots.append({**shot, "prompt": prompt})
            payload["shots"] = generated_shots
            cls._set_state(job_id, payload, "uploading", 30)
            logger.info("video job %s stage=uploading", job_id)

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

            width = int(payload.get("width") or cls.DEFAULTS["width"])
            height = int(payload.get("height") or cls.DEFAULTS["height"])
            steps = int(payload.get("steps") or cls.DEFAULTS["steps"])

            timeline = comfy.build_timeline(generated_shots, task_type, width=width, height=height)
            workflow = comfy.build_workflow(
                timeline,
                task_type,
                f"video/{payload['project_id']}/{payload['episode_id']}/{job_id}",
                width=width,
                height=height,
                steps=steps,
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
            logger.info("video job %s stage=comfy_running", job_id)
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
                WHERE id = %s AND status <> 'cancelled'
                """,
                (result_url, json.dumps(payload, ensure_ascii=False), timestamp, timestamp, job_id),
            )
            logger.info("video job completed %s", job_id)
        except Exception as err:
            logger.exception("video job failed %s: %s", job_id, err)
            timestamp = now_str()
            try:
                row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id = %s", (job_id,)) or {}
                failed_payload = json.loads(row.get("payload_json") or "{}")
                failed_payload["failure_stage"] = failed_payload.get("runtime_stage") or "unknown"
                execute_sql(
                    """
                    UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s,
                      payload_json = %s, updated_at = %s WHERE id = %s AND status <> 'cancelled'
                    """,
                    (str(err)[:4000], json.dumps(failed_payload, ensure_ascii=False), timestamp, job_id),
                )
            except Exception:
                execute_sql(
                    "UPDATE ai_project_jobs SET status = 'failed', progress = 0, error_message = %s, updated_at = %s WHERE id = %s AND status <> 'cancelled'",
                    (str(err)[:4000], timestamp, job_id),
                )

    @staticmethod
    def _set_state(job_id: str, payload: dict[str, Any], status: str, progress: int) -> None:
        payload["runtime_stage"] = status
        execute_sql(
            "UPDATE ai_project_jobs SET status = %s, progress = %s, payload_json = %s, updated_at = %s WHERE id = %s AND status <> 'cancelled'",
            (status, progress, json.dumps(payload, ensure_ascii=False), now_str(), job_id),
        )

    @staticmethod
    def _director_report(outputs: dict[str, Any]) -> str:
        node = outputs.get("8") or {}
        values = node.get("text") or node.get("string") or []
        if isinstance(values, list):
            return "\n".join(str(value) for value in values)
        return str(values or "")
