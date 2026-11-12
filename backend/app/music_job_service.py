"""
「音乐」模块任务服务：远端 YuE2 Studio 生成歌曲的后台执行器。

流程：enqueue 落库(queued) → 线程池逐个执行 → YuE2Client 提交 /v1/music/jobs →
轮询至终态 → 下载音频/封面 → 上传七牛 → result_url 写回 music_jobs。
远端引擎单机单实例，本地 max_workers=1 串行，避免排队任务挤爆显存。
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .grs_provider import CredentialManager
from .llm_client import LlmError
from .music_yue2_client import COMPLETED_STATUSES, FAILED_STATUSES, YuE2Client, YuE2Error, YUE2_POLL_INTERVAL, YUE2_POLL_MAX_WAIT
from .resource_storage import resource_object_url
from .storage import JobStore, now

MUSIC_ACTIVE_STATUSES = ("queued", "running")
DEFAULT_DURATION = 210
MIN_DURATION = 10
MAX_DURATION = 600
ALLOWED_FORMATS = ("flac", "mp3", "wav")
ALLOWED_COT = ("full", "melody", "off")
MAX_STYLE_LENGTH = 2000
MAX_LYRICS_LENGTH = 8000
MAX_VIBE_LENGTH = 1000

_RECOVER_MESSAGE = "服务重启时音乐任务已中断，请重新生成。"

MUSIC_VIBE_SYSTEM_PROMPT = """你是「ZLY AI 视频工作台」的音乐创作顾问，负责把用户的自然语言描述扩写成 AI 作曲引擎（YuE2）可直接使用的结构化参数。

只输出一个 JSON 对象，不要任何解释或 Markdown 代码块，字段如下：
{
  "title": "简短歌曲标题，中文，不超过 20 字，概括主题与情绪",
  "style": "一句英文标签串，逗号分隔，12-50 词，固定顺序：演唱语言 → 曲风/子曲风 → 主唱（性别/音色/唱法，纯音乐写 instrumental）→ 关键乐器与质感 → 情绪与旋律特征 → 结尾 N BPM。禁止指令句，禁止中文。",
  "lyrics": "完整歌词。分节标签 [Intro]、[Verse 1]、[Verse 2]、[Pre-Chorus]、[Chorus]、[Bridge]、[Outro] 各占一行，节与节之间空一行，每行一句歌词。用户未指定演唱语言时默认写中文歌词，分节标签本身保留英文。纯音乐时 lyrics 输出空字符串。"
}

扩写规则：
- 忠实呈现用户描述的主题、情绪、场景与演唱语言；用户没提的曲风、乐器、节奏由你补全成协调的整体。
- 歌词必须与用户描述的故事或情绪强相关，具体、有画面感，避免空喊口号；副歌要有记忆点并呼应主题。
- 时长参考：约 60 秒写 1-2 节主歌加 1 段副歌；约 210 秒写完整的 主歌-预副歌-副歌-桥段-尾奏 结构。
- BPM 与曲风匹配：民谣 70-100、流行 90-120、摇滚 110-150、电子 100-128、嘻哈 80-100、古风 60-90。"""


class MusicServiceError(RuntimeError):
    pass


class MusicJobService:
    _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-gen")
    _DISPATCH_LOCK = threading.Lock()
    _ACTIVE: set[str] = set()
    _ACTIVE_LOCK = threading.Lock()

    _store: JobStore | None = None
    _credentials: CredentialManager | None = None
    _resource_storage: Any | None = None

    @classmethod
    def configure(cls, store: JobStore, credential_key: str | None, resource_storage: Any | None) -> None:
        cls._store = store
        cls._credentials = CredentialManager(credential_key)
        cls._resource_storage = resource_storage

    # ------------------------------------------------------------------ #
    # 供应商配置
    # ------------------------------------------------------------------ #
    @classmethod
    def provider_settings(cls) -> dict[str, Any]:
        if cls._store is None:
            raise MusicServiceError("音乐服务尚未初始化")
        return cls._store.get_music_settings()

    @classmethod
    def client(cls) -> YuE2Client:
        settings = cls.provider_settings()
        base_url = str(settings.get("base_url") or "").strip()
        access_key = cls._credentials.decrypt(settings.get("access_key_encrypted")) if cls._credentials else None
        if not base_url:
            raise MusicServiceError("尚未配置音乐生成服务地址，请先在管理设置 → AI 供应商中配置 YuE2 Studio")
        if not access_key:
            raise MusicServiceError("尚未配置音乐生成服务访问密钥，请先在管理设置 → AI 供应商中配置 YuE2 Studio")
        return YuE2Client(base_url, access_key)

    @classmethod
    def public_config(cls) -> dict[str, Any]:
        """管理设置回显：不回传明文密钥，只给是否已配置。"""
        settings = cls.provider_settings()
        access_key = cls._credentials.decrypt(settings.get("access_key_encrypted")) if cls._credentials else None
        credential_ready = bool(cls._credentials and cls._credentials.ready)
        base_url = str(settings.get("base_url") or "").strip()
        return {
            "base_url": base_url,
            "has_access_key": bool(access_key),
            "credential_ready": credential_ready,
            "configured": bool(base_url and access_key),
            "last_test_status": settings.get("last_test_status"),
            "last_test_message": settings.get("last_test_message"),
            "last_test_at": settings.get("last_test_at"),
        }

    @classmethod
    def update_provider(cls, base_url: str | None, access_key: str | None) -> dict[str, Any]:
        if cls._store is None:
            raise MusicServiceError("音乐服务尚未初始化")
        updates: dict[str, Any] = {}
        if base_url is not None:
            updates["base_url"] = str(base_url).strip()
        if access_key:
            if not cls._credentials or not cls._credentials.ready:
                raise MusicServiceError("凭证主密钥不可用，无法保存访问密钥")
            updates["access_key_encrypted"] = cls._credentials.encrypt(str(access_key).strip())
        if updates:
            cls._store.update_music_settings(**updates)
        return cls.public_config()

    @classmethod
    def test(cls, base_url: str | None = None, access_key: str | None = None) -> dict[str, Any]:
        """测试远端连通性；显式参数优先，否则用已保存配置。结果写回 last_test_*。"""
        settings = cls.provider_settings()
        effective_base = str(base_url or settings.get("base_url") or "").strip()
        effective_key = str(access_key).strip() if access_key else None
        if not effective_key and cls._credentials:
            effective_key = cls._credentials.decrypt(settings.get("access_key_encrypted"))
        status, message = "ok", None
        try:
            if not effective_base:
                raise MusicServiceError("服务地址未配置")
            YuE2Client(effective_base, effective_key or "").ping()
        except (YuE2Error, MusicServiceError) as exc:
            status, message = "failed", str(exc)
        if cls._store is not None:
            cls._store.update_music_settings(
                last_test_status=status, last_test_message=message, last_test_at=now(),
            )
        result = cls.public_config()
        result["available"] = status == "ok"
        result["unavailable_reason"] = message
        return result

    @classmethod
    def remote_config(cls) -> dict[str, Any]:
        """给创建表单的远端能力快照：引擎默认值 + 已安装 LoRA。失败不阻塞表单。"""
        payload: dict[str, Any] = {"adapters": [], "defaults": None, "error": None}
        try:
            client = cls.client()
        except MusicServiceError as exc:
            payload["error"] = str(exc)
            return payload
        try:
            payload["adapters"] = client.list_adapters()
        except YuE2Error as exc:
            payload["error"] = str(exc)
        return payload

    # ------------------------------------------------------------------ #
    # 提交任务
    # ------------------------------------------------------------------ #
    @classmethod
    def enqueue(
        cls,
        owner_user_id: str,
        *,
        title: str,
        style: str,
        lyrics: str,
        duration_seconds: int = DEFAULT_DURATION,
        output_format: str = "flac",
        steps: int | None = None,
        seed: int | None = None,
        lm_seed: int | None = None,
        cot: str = "full",
        adapters: list[dict[str, Any]] | None = None,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        if cls._store is None:
            raise MusicServiceError("音乐服务尚未初始化")
        style = str(style or "").strip()
        lyrics = str(lyrics or "").strip()
        title = str(title or "").strip()
        if not style:
            raise ValueError("风格描述不能为空")
        if len(style) > MAX_STYLE_LENGTH:
            raise ValueError(f"风格描述不能超过 {MAX_STYLE_LENGTH} 字符")
        if len(lyrics) > MAX_LYRICS_LENGTH:
            raise ValueError(f"歌词不能超过 {MAX_LYRICS_LENGTH} 字符")
        duration = int(duration_seconds or DEFAULT_DURATION)
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError(f"时长需在 {MIN_DURATION}-{MAX_DURATION} 秒之间")
        fmt = str(output_format or "flac").strip().lower()
        if fmt not in ALLOWED_FORMATS:
            raise ValueError(f"输出格式仅支持 {'/'.join(ALLOWED_FORMATS)}")
        cot_value = str(cot or "full").strip().lower()
        if cot_value not in ALLOWED_COT:
            raise ValueError("CoT 模式仅支持 full/melody/off")
        clean_adapters = cls._clean_adapters(adapters)

        cls.client()  # 未配置时在提交前就给出引导性报错
        jid = f"music-{uuid.uuid4().hex[:12]}"
        timestamp = now()
        record = cls._store.create_music_job({
            "id": jid,
            "owner_user_id": owner_user_id,
            "title": title,
            "style": style,
            "lyrics": lyrics,
            "status": "queued",
            "progress": 0,
            "params": {
                "duration_seconds": duration,
                "output_format": fmt,
                "steps": steps,
                "seed": seed,
                "lm_seed": lm_seed,
                "cot": cot_value,
                "adapters": clean_adapters,
            },
            "chat_id": chat_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        })
        cls.kick()
        return record

    @classmethod
    def create_from_vibe(
        cls,
        owner_user_id: str,
        *,
        description: str,
        duration_seconds: int = DEFAULT_DURATION,
        instrumental: bool = False,
        llm_provider: Any,
    ) -> dict[str, Any]:
        """一句话 vibe 生成：大模型把自然语言描述扩写成 YuE2 参数后直接入队。"""
        text = str(description or "").strip()
        if not text:
            raise ValueError("请先描述你想要的歌")
        if len(text) > MAX_VIBE_LENGTH:
            raise ValueError(f"描述不能超过 {MAX_VIBE_LENGTH} 字")
        duration = int(duration_seconds or DEFAULT_DURATION)
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError(f"时长需在 {MIN_DURATION}-{MAX_DURATION} 秒之间")
        if llm_provider is None:
            raise MusicServiceError("大模型服务尚未初始化")
        user_content = f"用户的音乐描述：{text}\n\n目标时长：约 {duration} 秒。"
        if instrumental:
            user_content += "\n要求：纯音乐，不要歌词。"
        try:
            parsed = llm_provider.chat_json(MUSIC_VIBE_SYSTEM_PROMPT, user_content)
        except LlmError:
            # 原样透传：路由层把 LLM 上游失败映射为 502，区别于服务未配置的 503
            raise
        style = str(parsed.get("style") or "").strip()
        lyrics = str(parsed.get("lyrics") or "").strip()
        title = str(parsed.get("title") or "").strip()[:120]
        if not style:
            raise MusicServiceError("大模型未生成有效的风格描述，请重试或改用高级创作模式")
        if instrumental:
            lyrics = ""
        if len(lyrics) > MAX_LYRICS_LENGTH:
            lyrics = lyrics[:MAX_LYRICS_LENGTH]
        return cls.enqueue(
            owner_user_id,
            title=title,
            style=style,
            lyrics=lyrics,
            duration_seconds=duration,
            output_format="flac",
        )

    @staticmethod
    def _clean_adapters(adapters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in adapters or []:
            if not isinstance(item, dict):
                continue
            adapter_id = str(item.get("id") or "").strip()
            if not adapter_id:
                continue
            scales = item.get("scales")
            entry: dict[str, Any] = {"id": adapter_id}
            if isinstance(scales, dict) and scales:
                entry["scales"] = {str(k): float(v) for k, v in scales.items() if isinstance(v, (int, float))}
            cleaned.append(entry)
        return cleaned

    # ------------------------------------------------------------------ #
    # 派发与恢复
    # ------------------------------------------------------------------ #
    @classmethod
    def kick(cls) -> None:
        if cls._store is None:
            return
        if not cls._DISPATCH_LOCK.acquire(blocking=False):
            return
        try:
            with cls._ACTIVE_LOCK:
                if cls._ACTIVE:
                    return
            for row in cls._store.list_active_music_jobs():
                if str(row.get("status")) != "queued":
                    continue
                jid = str(row.get("id"))
                updated = cls._store.update_music_job(jid, status="running", progress=10)
                if updated is None or updated.get("status") != "running":
                    continue
                with cls._ACTIVE_LOCK:
                    cls._ACTIVE.add(jid)
                cls._EXECUTOR.submit(cls._run, jid)
                break
        finally:
            cls._DISPATCH_LOCK.release()

    @classmethod
    def recover_interrupted_jobs(cls) -> None:
        if cls._store is None:
            return
        for row in cls._store.list_active_music_jobs():
            cls._store.update_music_job(
                str(row.get("id")), status="failed", progress=0,
                error_message=_RECOVER_MESSAGE,
            )
        cls.kick()

    @classmethod
    def retry_job(cls, job_id: str, owner_user_id: str | None) -> dict[str, Any]:
        """重试失败任务：保留 remote_job_id，执行器会优先复用远端已生成的歌曲，避免整首重新生成。

        owner_user_id 为 None 表示不限制归属，供管理员跨账号重试；普通账号始终传本人 id。
        """
        if cls._store is None:
            raise MusicServiceError("音乐服务尚未初始化")
        record = cls._store.get_music_job(job_id, owner_user_id=owner_user_id)
        if not record:
            raise ValueError("音乐任务不存在")
        status = str(record.get("status"))
        if status in MUSIC_ACTIVE_STATUSES:
            raise MusicServiceError("任务正在执行中，无需重试")
        if status == "succeeded":
            raise MusicServiceError("任务已成功，无需重试")
        cls.client()  # 未配置时在重置前就给出引导性报错
        updated = cls._store.update_music_job(
            job_id, status="queued", progress=0, error_message=None, completed_at=None,
        )
        if updated is None:
            raise MusicServiceError("重试失败：任务记录不存在")
        cls.kick()
        return updated

    @classmethod
    def _resume_remote_job(
        cls, client: YuE2Client, remote_job_id: str,
        report_progress: Any, store: JobStore, job_id: str,
    ) -> dict[str, Any] | None:
        """失败重试时复用远端任务：已完成/仍在生成都续走下载上传；远端已失败或丢失则返回 None 重新生成。"""
        try:
            remote_job = client.get_job(remote_job_id)
        except YuE2Error:
            return None
        status = str(remote_job.get("status") or "").lower()
        if status in COMPLETED_STATUSES:
            return remote_job
        if status in FAILED_STATUSES:
            return None
        store.update_music_job(job_id, status="running", progress=25)
        return client.wait_for_job(
            remote_job_id, poll_interval=YUE2_POLL_INTERVAL, max_wait=YUE2_POLL_MAX_WAIT,
            on_progress=report_progress,
        )

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    @classmethod
    def _run(cls, job_id: str) -> None:
        store = cls._store
        try:
            record = store.get_music_job(job_id) if store else None
            if not record:
                return
            params = record.get("params") or {}
            store.update_music_job(job_id, status="running", progress=10)
            client = cls.client()

            def report_progress(remote_job: dict[str, Any]) -> None:
                phase = str(remote_job.get("phase") or "")
                progress = 30 if phase in ("", "queued", "planning") else 65
                store.update_music_job(job_id, status="running", progress=progress)

            # 重试路径：上次执行已拿到 remote_job_id 时优先续传，避免重复占用远端生成资源
            remote_job_id = str(record.get("remote_job_id") or "")
            finished: dict[str, Any] | None = None
            if remote_job_id:
                finished = cls._resume_remote_job(client, remote_job_id, report_progress, store, job_id)
                remote_job_id = ""
            if finished is None:
                remote_job = client.create_song(
                    style=str(record.get("style") or ""),
                    lyrics=str(record.get("lyrics") or ""),
                    title=str(record.get("title") or "") or None,
                    duration_seconds=params.get("duration_seconds"),
                    output_format=params.get("output_format"),
                    steps=params.get("steps"),
                    seed=params.get("seed"),
                    lm_seed=params.get("lm_seed"),
                    cot=params.get("cot"),
                    adapters=params.get("adapters") or None,
                    client_ref=job_id,
                )
                remote_job_id = str(remote_job.get("id") or "")
                store.update_music_job(job_id, remote_job_id=remote_job_id, status="running", progress=25)
                finished = client.wait_for_job(
                    remote_job_id, poll_interval=YUE2_POLL_INTERVAL, max_wait=YUE2_POLL_MAX_WAIT,
                    on_progress=report_progress,
                )
            song_id = cls._completed_song_id(finished)
            if not song_id:
                raise MusicServiceError("YuE2 任务完成但未返回歌曲 ID")
            audio = client.download_media(song_id)
            fmt = str((params.get("output_format") or "flac")).lower()
            filename = f"{cls._safe_title(str(record.get('title') or '') or song_id)}.{fmt}"
            result_url = cls._store_bytes("music/audio", filename, audio)
            cover_url: str | None = None
            cover = client.download_cover(song_id)
            if cover:
                cover_url = cls._store_bytes("music/covers", f"{song_id}.jpg", cover)
            store.update_music_job(
                job_id,
                status="succeeded",
                progress=100,
                result_url=result_url,
                result_format=fmt,
                cover_url=cover_url,
                remote_song_id=song_id,
                duration_seconds=params.get("duration_seconds"),
                completed_at=now(),
            )
        except (YuE2Error, MusicServiceError, ValueError, RuntimeError) as exc:
            if store:
                store.update_music_job(
                    job_id, status="failed", progress=0,
                    error_message=str(exc)[:500],
                    completed_at=now(),
                )
        except Exception as exc:  # 兜底：任何未知异常都不能静默挂起任务
            if store:
                store.update_music_job(
                    job_id, status="failed", progress=0,
                    error_message=f"音乐任务执行异常：{exc}"[:500],
                    completed_at=now(),
                )
        finally:
            with cls._ACTIVE_LOCK:
                cls._ACTIVE.discard(job_id)
            cls.kick()

    @staticmethod
    def _completed_song_id(remote_job: dict[str, Any]) -> str | None:
        song = remote_job.get("song")
        if isinstance(song, dict) and song.get("id"):
            return str(song["id"])
        songs = remote_job.get("songs")
        if isinstance(songs, list) and songs and isinstance(songs[0], dict) and songs[0].get("id"):
            return str(songs[0]["id"])
        audio_url = song.get("audio_url") if isinstance(song, dict) else None
        if isinstance(audio_url, str) and audio_url:
            tail = audio_url.rstrip("/").rsplit("/", 1)[-1]
            if tail:
                return tail
        return None

    @staticmethod
    def _safe_title(title: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in title).strip()
        return (cleaned or "song").replace(" ", "_")[:80]

    @classmethod
    def _store_bytes(cls, prefix: str, filename: str, content: bytes) -> str | None:
        storage = cls._resource_storage
        if storage is None:
            return None
        stored = storage.store_bytes(prefix, filename, content)
        return resource_object_url(storage, stored.key)
