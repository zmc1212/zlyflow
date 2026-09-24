"""Reviewed action/camera plans and leased Blender MCP preview jobs."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

from ...vision_runtime import chat_on_endpoint, resolve_analysis_endpoint, resolve_text_endpoint
from ..db import execute_sql, now_str, query_all, query_one
from ..provider_bridge import credential_manager, llm_row, vlm_row
from .action_previs_schema import ACTION_TYPES, FPS, MAX_SECONDS, MIN_SECONDS, validate_plan
from .job_payload import parse_job_payload, serialize_job_row
from .qiniu_service import QiniuService

JOB_TYPE = "action_previs"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="action-previs-plan")
_IMAGE_LIMIT = 4
_IMAGE_BYTES = 8 * 1024 * 1024
_VIDEO_BYTES = 100 * 1024 * 1024
_ARTIFACT_LIMITS = {"video": 60 * 1024 * 1024, "blend": 100 * 1024 * 1024,
                    "contact_sheet": 8 * 1024 * 1024, "report": 256 * 1024}
_LEASE_SECONDS = 120


def _lease_valid(payload: dict[str, Any], token: str) -> bool:
    lease = payload.get("lease") or {}
    return bool(token) and secrets.compare_digest(str(lease.get("token") or ""), token) and float(lease.get("expires_at") or 0) > time.time()


def _json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("模型须返回 JSON 对象")
    return value


def _duration_frames(value: Any) -> int:
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("镜头时长无效") from exc
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise ValueError(f"动作编排仅支持 {MIN_SECONDS}–{MAX_SECONDS} 秒镜头")
    return round(duration * FPS)


def _video_frames(content: bytes) -> list[str]:
    """Sample a short reference clip for VLM; ffmpeg/ffprobe are server dependencies."""
    with tempfile.TemporaryDirectory(prefix="action-previs-") as folder:
        source = Path(folder) / "reference.mp4"
        source.write_bytes(content)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        duration = float((json.loads(probe.stdout).get("format") or {}).get("duration") or 0)
        if not 0.5 <= duration <= MAX_SECONDS:
            raise ValueError("参考视频须为 0.5–15 秒")
        result: list[str] = []
        for index in range(6):
            second = min(duration - 0.05, duration * (index + 0.5) / 6)
            frame = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{second:.3f}", "-i", str(source),
                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                capture_output=True, timeout=30, check=True,
            ).stdout
            if frame:
                with Image.open(io.BytesIO(frame)) as image:
                    rgb = image.convert("RGB")
                    rgb.thumbnail((640, 640))
                    buf = io.BytesIO()
                    rgb.save(buf, format="JPEG", quality=80)
                result.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
        if not result:
            raise ValueError("参考视频无法提取画面")
        return result


class ActionPrevisService:
    @staticmethod
    def _row(project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s AND job_type=%s",
                        (job_id, project_id, JOB_TYPE))
        if not row:
            raise ValueError("动作编排任务不存在")
        return row

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return serialize_job_row(row, slim=False)

    @classmethod
    def _replace(cls, row: dict[str, Any], payload: dict[str, Any], *, status: str | None = None,
                 progress: int | None = None, error: str | None = None, result_url: str | None = None) -> bool:
        """Compare the complete previous payload to avoid concurrent review/worker clobbers."""
        raw = row.get("payload_json") or "{}"
        update = json.dumps(payload, ensure_ascii=False)
        next_status = status or row["status"]
        completed_at = now_str() if next_status in {"completed", "needs_revision", "failed", "cancelled"} else None
        return execute_sql(
            "UPDATE ai_project_jobs SET payload_json=%s,status=%s,progress=%s,error_message=%s,result_url=%s,completed_at=%s,updated_at=%s "
            "WHERE id=%s AND status=%s AND payload_json=%s",
            (update, next_status, row.get("progress") if progress is None else progress,
             error, result_url if result_url is not None else row.get("result_url"), completed_at, now_str(),
             row["id"], row["status"], raw),
        ) == 1

    @classmethod
    def create(cls, project_id: str, episode_id: str, beat_id: str, description: str,
               images: list[tuple[str, bytes, str]], video: tuple[str, bytes, str] | None) -> dict[str, Any]:
        from .project_service import ProjectService
        if not ProjectService.get_project(project_id):
            raise ValueError("项目不存在")
        ep = query_one("SELECT id,data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s",
                       (episode_id, project_id))
        if not ep:
            raise ValueError("分集不存在")
        beats = parse_job_payload(ep.get("data_json")).get("beats") or []
        beat = next((item for item in beats if str(item.get("id")) == beat_id), None)
        if not beat:
            raise ValueError("镜头不存在，请先保存镜头")
        request_text = str(description or "").strip()
        if not request_text or len(request_text) > 3000:
            raise ValueError("动作需求须为 1–3000 字")
        frame_count = _duration_frames(beat.get("video_duration") or 8)
        if len(images) > _IMAGE_LIMIT:
            raise ValueError("最多上传四张参考图片")
        if not QiniuService.get_config().available:
            raise ValueError("动作编排需要先配置七牛云素材存储")
        decrypt = credential_manager().decrypt
        if not resolve_text_endpoint(llm_row(), decrypt):
            raise ValueError("请先启用大语言模型")
        if (images or video) and not resolve_analysis_endpoint(llm_row(), vlm_row(), decrypt):
            raise ValueError("使用参考图片或视频前，请先启用可看图的视觉模型")
        video_frames: list[str] | None = None
        if video:
            _, content, mime = video
            if mime not in {"video/mp4", "video/quicktime", "video/webm"} or not 0 < len(content) <= _VIDEO_BYTES:
                raise ValueError("参考视频只接受 100MB 内的 MP4、MOV、WebM")
            video_frames = _video_frames(content)
        refs: list[dict[str, Any]] = []
        for index, (name, content, mime) in enumerate(images):
            if mime not in {"image/jpeg", "image/png", "image/webp"} or not 0 < len(content) <= _IMAGE_BYTES:
                raise ValueError("参考图片只接受 8MB 内的 JPEG、PNG、WebP")
            try:
                with Image.open(io.BytesIO(content)) as image:
                    if image.width * image.height > 32_000_000 or image.width < 16 or image.height < 16:
                        raise ValueError("参考图片尺寸无效")
                    image.verify()
            except (OSError, SyntaxError) as exc:
                raise ValueError("参考图片无法解码") from exc
            suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
            _, url = QiniuService.store_bytes("action-previs/input", f"{project_id}-{index}{suffix}", content)
            refs.append({"kind": "image", "url": url, "name": str(name)[:120]})
        if video:
            name, content, mime = video
            suffix = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}[mime]
            _, url = QiniuService.store_bytes("action-previs/input", f"{project_id}-reference{suffix}", content)
            frame_urls: list[str] = []
            for index, frame in enumerate(video_frames or []):
                _, frame_url = QiniuService.store_bytes(
                    "action-previs/input", f"{project_id}-reference-frame-{index}.jpg",
                    base64.b64decode(frame.partition(",")[2]),
                )
                frame_urls.append(frame_url)
            refs.append({"kind": "video", "url": url, "name": str(name)[:120], "frames": frame_urls})
        jid = f"job-{uuid.uuid4().hex[:12]}"
        payload = {"schema_version": 1, "target_type": JOB_TYPE, "episode_id": episode_id,
                   "beat_id": beat_id, "description": request_text, "frame_count": frame_count,
                   "beat_snapshot": {key: beat.get(key) for key in ("heading", "action", "camera", "character_ids", "video_duration")},
                   "references": refs, "plan_revision": 0, "approved_revision": None, "artifacts": {},
                   "stage": "analysis"}
        ts = now_str()
        execute_sql(
            "INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,result_url,payload_json,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'queued',0,NULL,%s,%s,%s)",
            (jid, project_id, JOB_TYPE, f"动作与镜头编排 · {str(beat.get('heading') or beat_id)[:70]}",
             json.dumps(payload, ensure_ascii=False), ts, ts),
        )
        cls.kick()
        return {"job_id": jid, "status": "queued"}

    @classmethod
    def kick(cls) -> None:
        for row in query_all("SELECT id,project_id FROM ai_project_jobs WHERE job_type=%s AND status='queued' ORDER BY created_at LIMIT 10", (JOB_TYPE,)):
            if execute_sql("UPDATE ai_project_jobs SET status='planning',progress=5,updated_at=%s WHERE id=%s AND status='queued'",
                           (now_str(), row["id"])) == 1:
                _EXECUTOR.submit(cls._plan, str(row["project_id"]), str(row["id"]))

    @classmethod
    def _plan(cls, project_id: str, job_id: str) -> None:
        try:
            row = cls._row(project_id, job_id)
            payload = parse_job_payload(row.get("payload_json"))
            refs = payload.get("references") or []
            images = [r["url"] for r in refs if r.get("kind") == "image"]
            for r in refs:
                if r.get("kind") == "video":
                    images.extend(r.get("frames") or [])
            decrypt = credential_manager().decrypt
            observations = "无视觉参考；仅根据文字和本镜头描述规划。"
            vision_model = ""
            if images:
                vision = resolve_analysis_endpoint(llm_row(), vlm_row(), decrypt)
                if not vision:
                    raise ValueError("视觉模型不可用，无法分析参考素材")
                observations = chat_on_endpoint(
                    vision, "你是动作和摄影参考分析员。只描述图中能观察到的姿态、人物位置、接触、景别和按图片顺序的变化；不可凭空声称已看到连续运动。",
                    "按顺序分析这些参考图。视频抽帧按时间顺序排列。输出简洁中文观察，不写制作指令。", images[:8], max_tokens=1500,
                )
                vision_model = vision.model
            text = resolve_text_endpoint(llm_row(), decrypt)
            if not text:
                raise ValueError("大语言模型不可用")
            prompt = (
                "按用户需求、镜头原设定与视觉观察，生成可执行的人形动作和电影镜头方案。"
                "只输出 JSON 对象，不要 Markdown 或代码。schema: "
                "{version:1,frame_count:int,actors:[{id:'A'|'B',label:string,start:[x,y,z],facing_deg:number}],"
                "beats:[{start:int,end:int,description:string,actions:[{actor:'A'|'B',type:string}],"
                "contact:null|{frame:int,actor:'A'|'B',target_actor:'A'|'B',bone:string,target_bone:string}}],"
                "shots:[{start:int,end:int,size:'wide'|'medium'|'close'|'detail',"
                "angle:'front'|'side'|'three_quarter'|'over_shoulder'|'low'|'high',"
                "move:'static'|'dolly_in'|'dolly_out'|'truck_left'|'truck_right'|'orbit_left'|'orbit_right'|'follow',"
                "subject:'A'|'B'|'both',lens_mm:number}]}。"
                "动作类型仅允许: " + ",".join(sorted(ACTION_TYPES)) + "。"
                "节拍和镜头分别从 0 连续覆盖所有帧，end 为开区间。双人交互必须同拍给双方动作，打击须有对手反应与接触点。"
                "动作包含重心、步法、预备、发力、接触、回收；相机不要一直正拍，切点贴合动作。"
                "必须把用户需求里的可见动作、目标物和镜头意图落到 beat description、actions 和 shots 中；例如‘走到桌前坐下’必须有 walk 后接 crouch（保持坐姿），description 中明确写出桌子/坐下，不能只输出 idle。"
                "每个关键动作至少占据一个完整节拍，并让前后节拍保持连续姿态；不要用一个静态 idle 节拍替代用户明确要求的走、蹲、坐、拿取或转身。"
            )
            user = json.dumps({"frame_count": payload["frame_count"], "fps": FPS,
                               "requirement": payload["description"], "shot": payload["beat_snapshot"],
                               "visual_observations": observations}, ensure_ascii=False)
            error = ""
            for attempt in range(2):
                raw = chat_on_endpoint(text, prompt, user + ("\n上次方案校验失败：" + error if error else ""),
                                       max_tokens=3500, temperature=0.2)
                try:
                    plan = validate_plan(_json_object(raw), expected_frames=int(payload["frame_count"]))
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    error = str(exc)
            else:
                raise ValueError("大语言模型两次返回的动作方案均无效：" + error)
            row = cls._row(project_id, job_id)
            if row["status"] != "planning":
                return
            payload = parse_job_payload(row.get("payload_json"))
            payload.update(plan=plan, plan_revision=1, observations=observations,
                           vision_model=vision_model, llm_model=text.model, stage="awaiting_review")
            if not cls._replace(row, payload, status="awaiting_review", progress=35):
                raise RuntimeError("方案状态已变化，请刷新")
        except Exception as exc:
            row = cls._row(project_id, job_id)
            if row["status"] == "planning":
                payload = parse_job_payload(row.get("payload_json"))
                payload["stage"] = "failed"
                cls._replace(row, payload, status="failed", progress=0, error=str(exc)[:2000])

    @classmethod
    def get(cls, project_id: str, job_id: str) -> dict[str, Any]:
        return cls.public(cls._row(project_id, job_id))

    @classmethod
    def latest(cls, project_id: str, episode_id: str, beat_id: str) -> dict[str, Any] | None:
        rows = query_all("SELECT * FROM ai_project_jobs WHERE project_id=%s AND job_type=%s ORDER BY created_at DESC LIMIT 100",
                         (project_id, JOB_TYPE))
        for row in rows:
            payload = parse_job_payload(row.get("payload_json"))
            if payload.get("episode_id") == episode_id and payload.get("beat_id") == beat_id:
                return cls.public(row)
        return None

    @classmethod
    def revise(cls, project_id: str, job_id: str, plan_raw: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        row = cls._row(project_id, job_id)
        if row["status"] != "awaiting_review":
            raise ValueError("只有待确认的方案可以修改")
        payload = parse_job_payload(row.get("payload_json"))
        if int(payload.get("plan_revision") or 0) != expected_revision:
            raise RuntimeError("REVISION_CONFLICT: 方案已更新，请刷新后再改")
        payload["plan"] = validate_plan(plan_raw, expected_frames=int(payload["frame_count"]))
        payload["plan_revision"] = expected_revision + 1
        if not cls._replace(row, payload):
            raise RuntimeError("REVISION_CONFLICT: 方案已更新，请刷新后再改")
        return cls.get(project_id, job_id)

    @classmethod
    def render(cls, project_id: str, job_id: str, expected_revision: int) -> dict[str, Any]:
        if not os.environ.get("ZLY_ACTION_PREVIS_WORKER_TOKEN", "").strip():
            raise ValueError(
                "远端 Blender 执行器尚未配置，不能提交渲染；请设置 "
                "ZLY_ACTION_PREVIS_WORKER_TOKEN，并让远端 worker 使用相同令牌"
            )
        row = cls._row(project_id, job_id)
        if row["status"] != "awaiting_review":
            raise ValueError("请先等待动作方案并完成审稿")
        payload = parse_job_payload(row.get("payload_json"))
        if int(payload.get("plan_revision") or 0) != expected_revision:
            raise RuntimeError("REVISION_CONFLICT: 方案已变化，请刷新")
        payload["approved_revision"] = expected_revision
        payload["stage"] = "queued_remote"
        payload["references"] = [{k: v for k, v in r.items() if k != "frames"} for r in payload.get("references") or []]
        if not cls._replace(row, payload, status="queued_remote", progress=40):
            raise RuntimeError("REVISION_CONFLICT: 方案已变化，请刷新")
        return cls.get(project_id, job_id)

    @classmethod
    def cancel(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = cls._row(project_id, job_id)
        if row["status"] in {"completed", "needs_revision", "failed", "cancelled"}:
            return cls.public(row)
        payload = parse_job_payload(row.get("payload_json"))
        payload["stage"] = "cancelled"
        if not cls._replace(row, payload, status="cancelled", error="用户已取消"):
            raise RuntimeError("任务状态已变化，请刷新")
        return cls.get(project_id, job_id)

    @classmethod
    def retry(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = cls._row(project_id, job_id)
        payload = parse_job_payload(row.get("payload_json"))
        if row["status"] not in {"failed", "needs_revision", "interrupted"} or not payload.get("approved_revision"):
            raise ValueError("只有已审稿的失败任务可以从当前方案重试")
        payload.update(stage="queued_remote", lease=None, artifacts={}, retry_count=int(payload.get("retry_count") or 0) + 1)
        if not cls._replace(row, payload, status="queued_remote", progress=40, error=None, result_url=""):
            raise RuntimeError("任务状态已变化，请刷新")
        return cls.get(project_id, job_id)

    @classmethod
    def claim(cls, worker_id: str) -> dict[str, Any] | None:
        if not worker_id or len(worker_id) > 100:
            raise ValueError("worker_id 无效")
        rows = query_all("SELECT * FROM ai_project_jobs WHERE job_type=%s AND status IN ('queued_remote','remote_running') ORDER BY created_at LIMIT 20", (JOB_TYPE,))
        for row in rows:
            payload = parse_job_payload(row.get("payload_json"))
            lease = payload.get("lease") or {}
            if row["status"] == "remote_running" and float(lease.get("expires_at") or 0) > time.time():
                continue
            token = secrets.token_urlsafe(32)
            payload["lease"] = {"worker_id": worker_id, "token": token, "expires_at": time.time() + _LEASE_SECONDS}
            payload["stage"] = "remote_running"
            if cls._replace(row, payload, status="remote_running", progress=45):
                return {"job_id": row["id"], "project_id": row["project_id"], "lease_token": token,
                        "plan": payload["plan"], "references": payload.get("references") or [],
                        "approved_revision": payload.get("approved_revision")}
        return None

    @classmethod
    def heartbeat(cls, project_id: str, job_id: str, token: str, progress: int, stage: str) -> dict[str, Any]:
        for _ in range(3):
            row = cls._row(project_id, job_id)
            if row["status"] == "cancelled":
                return {"cancelled": True}
            payload = parse_job_payload(row.get("payload_json"))
            if row["status"] != "remote_running" or not _lease_valid(payload, token):
                raise ValueError("执行租约无效")
            payload["lease"]["expires_at"] = time.time() + _LEASE_SECONDS
            payload["stage"] = str(stage or "rendering")[:80]
            if cls._replace(row, payload, progress=max(45, min(95, int(progress)))):
                return {"cancelled": False}
        raise RuntimeError("任务状态已变化，请重试心跳")

    @classmethod
    def artifact(cls, project_id: str, job_id: str, token: str, slot: str, content: bytes) -> dict[str, str]:
        if slot not in _ARTIFACT_LIMITS or not 0 < len(content) <= _ARTIFACT_LIMITS[slot]:
            raise ValueError("产物类型或大小无效")
        initial = cls._row(project_id, job_id)
        if initial["status"] != "remote_running" or not _lease_valid(parse_job_payload(initial.get("payload_json")), token):
            raise ValueError("执行租约无效")
        ext = {"video": ".mp4", "blend": ".blend", "contact_sheet": ".jpg", "report": ".json"}[slot]
        if slot == "report":
            report = json.loads(content)
            if not isinstance(report, dict) or not isinstance(report.get("issues"), list):
                raise ValueError("质量报告格式无效")
        _, url = QiniuService.store_bytes("action-previs/output", f"{job_id}-{slot}{ext}", content)
        for _ in range(3):
            row = cls._row(project_id, job_id)
            payload = parse_job_payload(row.get("payload_json"))
            if row["status"] != "remote_running" or not _lease_valid(payload, token):
                raise ValueError("执行租约无效")
            payload.setdefault("artifacts", {})[slot] = url
            if cls._replace(row, payload):
                return {"url": url}
        raise RuntimeError("产物上传时任务状态已变化")

    @classmethod
    def complete(cls, project_id: str, job_id: str, token: str, report: dict[str, Any]) -> dict[str, Any]:
        row = cls._row(project_id, job_id)
        payload = parse_job_payload(row.get("payload_json"))
        if row["status"] != "remote_running" or not _lease_valid(payload, token):
            raise ValueError("执行租约无效")
        artifacts = payload.get("artifacts") or {}
        if set(_ARTIFACT_LIMITS) - set(artifacts):
            raise ValueError("白膜产物不完整")
        issues = [str(x)[:300] for x in (report.get("issues") or []) if str(x).strip()][:20]
        if report.get("passed") is not True and not issues:
            issues.append("远端逐帧质量检查未通过")
        payload["worker_report"] = {"passed": report.get("passed") is True, "issues": issues[:20]}
        vision = resolve_analysis_endpoint(llm_row(), vlm_row(), credential_manager().decrypt)
        if vision:
            try:
                verdict = _json_object(chat_on_endpoint(
                    vision, "你是白膜动作预演审片员。仅根据画面判断人物是否明显出画、是否始终正拍、打斗是否只有孤立挥拳直踢。只输出 JSON: {pass:boolean,issues:string[]}。看不清时给出问题，不虚构。",
                    "这是按时间顺序拼接的白膜关键帧联系表。检查动作与镜头可读性。", [artifacts["contact_sheet"]], max_tokens=500,
                ))
                if verdict.get("pass") is not True:
                    issues.extend(str(x)[:300] for x in (verdict.get("issues") or [])[:5])
                payload["vision_review"] = {"model": vision.model, "result": verdict}
            except Exception as exc:
                issues.append("视觉复审未完成：" + str(exc)[:180])
        else:
            issues.append("视觉复审模型不可用")
        latest_row = cls._row(project_id, job_id)
        latest_payload = parse_job_payload(latest_row.get("payload_json"))
        if latest_row["status"] != "remote_running" or not _lease_valid(latest_payload, token):
            raise ValueError("执行租约无效")
        latest_payload["quality"] = {"passed": not issues, "issues": issues}
        latest_payload["worker_report"] = payload["worker_report"]
        if payload.get("vision_review"):
            latest_payload["vision_review"] = payload["vision_review"]
        latest_payload["stage"] = "completed" if not issues else "needs_revision"
        latest_payload["lease"] = None
        status = "completed" if not issues else "needs_revision"
        if not cls._replace(latest_row, latest_payload, status=status, progress=100,
                            error="；".join(issues)[:2000] if issues else None,
                            result_url=artifacts["video"]):
            raise RuntimeError("任务状态已变化")
        return cls.get(project_id, job_id)

    @classmethod
    def fail(cls, project_id: str, job_id: str, token: str, message: str) -> dict[str, Any]:
        row = cls._row(project_id, job_id)
        payload = parse_job_payload(row.get("payload_json"))
        if row["status"] != "remote_running" or not _lease_valid(payload, token):
            raise ValueError("执行租约无效")
        payload["lease"] = None
        payload["stage"] = "failed"
        if not cls._replace(row, payload, status="failed", error=str(message)[:2000]):
            raise RuntimeError("任务状态已变化")
        return cls.get(project_id, job_id)

    @classmethod
    def recover(cls) -> None:
        for row in query_all("SELECT * FROM ai_project_jobs WHERE job_type=%s AND status='planning'", (JOB_TYPE,)):
            payload = parse_job_payload(row.get("payload_json"))
            payload["stage"] = "interrupted"
            cls._replace(row, payload, status="failed", error="服务重启中断了方案分析，请重新提交。")
        cls.kick()
