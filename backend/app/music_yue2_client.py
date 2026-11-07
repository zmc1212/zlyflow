"""
YuE2 Studio REST 客户端（远端本地音乐生成服务）。

接口以官方源码 crates/music-server/src/lib.rs（v3.8.3）为准，2026-11-07 已对
远端实例实测：所有端点都需要 ``Authorization: Bearer <access_key>``。

- POST /v1/music/jobs            创建生成任务，返回 MusicJob
- GET  /v1/music/jobs/{job_id}   轮询任务状态（queued/running/completed/failed）
- GET  /v1/library/media/{song_id}        音频文件流（支持 Range）
- GET  /v1/library/songs/{song_id}        歌曲元数据及可选的 metadata.lrc
- GET  /v1/library/songs/{song_id}/cover  封面图（可能 404，封面是可选元数据）
- GET  /v1/adapters              已安装的 LoRA 风格适配器列表
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

YUE2_SUBMIT_TIMEOUT = (12.0, 60.0)
YUE2_POLL_TIMEOUT = (12.0, 30.0)
YUE2_DOWNLOAD_TIMEOUT = (15.0, 300.0)
YUE2_POLL_INTERVAL = 5.0     # 引擎单机串行，任务分钟级，5s 轮询足够
YUE2_POLL_MAX_WAIT = 1500.0  # 默认曲长 210s，加上排队与慢卡余量
MAX_AUDIO_BYTES = 300 * 1024 * 1024

ACTIVE_STATUSES = {"queued", "running"}
COMPLETED_STATUSES = {"completed"}
FAILED_STATUSES = {"failed", "cancelled", "canceled"}


class YuE2Error(RuntimeError):
    pass


class YuE2Client:
    def __init__(self, base_url: str, access_key: str) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.access_key = access_key or ""
        self._session = requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_key}"}

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise YuE2Error("YuE2 服务地址未配置")
        return f"{self.base_url}{path}"

    # ------------------------------------------------------------------ #
    # 服务探活
    # ------------------------------------------------------------------ #
    def ping(self) -> dict[str, Any]:
        """GET /health，返回解析后的 JSON（服务不可达或认证失败时抛错）。"""
        try:
            resp = self._session.get(self._url("/health"), headers=self._headers, timeout=(8.0, 15.0))
        except requests.RequestException as e:
            raise YuE2Error(f"YuE2 服务不可达: {e}") from e
        if resp.status_code == 401:
            raise YuE2Error("YuE2 访问密钥缺失或不正确")
        if resp.status_code >= 400:
            raise YuE2Error(f"YuE2 健康检查失败 (HTTP {resp.status_code})")
        try:
            return resp.json()
        except ValueError:
            return {"status": str(resp.text or "ok")[:200]}

    # ------------------------------------------------------------------ #
    # 生成任务
    # ------------------------------------------------------------------ #
    def create_song(self, *, style: str, lyrics: str, title: str | None = None,
                    duration_seconds: float | None = None, output_format: str | None = None,
                    steps: int | None = None, seed: int | None = None, lm_seed: int | None = None,
                    cot: str | None = None, adapters: list[dict[str, Any]] | None = None,
                    client_ref: str | None = None) -> dict[str, Any]:
        """POST /v1/music/jobs，返回远端 MusicJob。"""
        body: dict[str, Any] = {"style": style, "lyrics": lyrics}
        if title:
            body["title"] = title
        if duration_seconds is not None:
            body["duration_seconds"] = duration_seconds
        if output_format:
            body["output_format"] = output_format
        if steps is not None:
            body["steps"] = steps
        if seed is not None:
            body["seed"] = seed
        if lm_seed is not None:
            body["lm_seed"] = lm_seed
        if cot:
            body["cot"] = cot
        if adapters:
            body["adapters"] = adapters
        if client_ref:
            body["client_ref"] = client_ref
        try:
            resp = self._session.post(
                self._url("/v1/music/jobs"), headers=self._headers, json=body,
                timeout=YUE2_SUBMIT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise YuE2Error(f"YuE2 提交失败: {e}") from e
        if resp.status_code == 401:
            raise YuE2Error("YuE2 访问密钥缺失或不正确")
        if resp.status_code >= 400:
            raise YuE2Error(f"YuE2 提交被拒绝 (HTTP {resp.status_code}): {resp.text[:200]}")
        try:
            job = resp.json()
        except ValueError as e:
            raise YuE2Error("YuE2 提交返回了无效 JSON") from e
        if not job.get("id"):
            raise YuE2Error(f"YuE2 提交成功但未返回任务 ID，响应：{job}")
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        """GET /v1/music/jobs/{job_id}，返回远端 MusicJob。"""
        try:
            resp = self._session.get(
                self._url(f"/v1/music/jobs/{job_id}"), headers=self._headers,
                timeout=YUE2_POLL_TIMEOUT,
            )
        except requests.RequestException as e:
            raise YuE2Error(f"YuE2 任务查询失败: {e}") from e
        if resp.status_code == 404:
            raise YuE2Error("YuE2 任务不存在（可能服务端已重启清空任务）")
        if resp.status_code >= 400:
            raise YuE2Error(f"YuE2 任务查询失败 (HTTP {resp.status_code})")
        try:
            return resp.json()
        except ValueError as e:
            raise YuE2Error("YuE2 任务查询返回了无效 JSON") from e

    def wait_for_job(self, job_id: str, *, poll_interval: float = YUE2_POLL_INTERVAL,
                     max_wait: float = YUE2_POLL_MAX_WAIT,
                     on_progress: Any | None = None) -> dict[str, Any]:
        """轮询直到 completed/failed，返回终态 MusicJob。on_progress(job) 用于汇报进度。"""
        deadline = time.time() + max_wait
        while True:
            time.sleep(poll_interval)
            job = self.get_job(job_id)
            if callable(on_progress):
                try:
                    on_progress(job)
                except Exception:  # 进度回调失败不影响主流程
                    pass
            status = str(job.get("status") or "").lower()
            if status in COMPLETED_STATUSES:
                return job
            if status in FAILED_STATUSES:
                message = str(job.get("message") or "").strip()
                raise YuE2Error(f"YuE2 生成失败：{message or status}")
            if time.time() >= deadline:
                raise YuE2Error(f"YuE2 生成超时（超过 {int(max_wait)}s）")

    # ------------------------------------------------------------------ #
    # 媒体下载
    # ------------------------------------------------------------------ #
    def download_media(self, song_id: str) -> bytes:
        """GET /v1/library/media/{song_id}，返回完整音频字节。"""
        return self._download(f"/v1/library/media/{song_id}", "音频")

    def get_song_lrc(self, song_id: str) -> str:
        try:
            with self._session.get(
                self._url(f"/v1/library/songs/{quote(song_id, safe='')}"),
                headers=self._headers, timeout=YUE2_POLL_TIMEOUT,
            ) as response:
                if response.status_code == 404:
                    return ""
                response.raise_for_status()
                song = response.json()
        except (requests.RequestException, ValueError) as error:
            raise YuE2Error("无法读取 YuE2 歌词时间轴") from error
        metadata = song.get("metadata") if isinstance(song, dict) else None
        lrc = metadata.get("lrc") if isinstance(metadata, dict) else None
        return lrc if isinstance(lrc, str) else ""

    def download_cover(self, song_id: str) -> bytes | None:
        """GET /v1/library/songs/{song_id}/cover；封面是可选元数据，404 返回 None。"""
        try:
            return self._download(f"/v1/library/songs/{song_id}/cover", "封面")
        except YuE2Error as e:
            if "404" in str(e):
                return None
            raise

    def list_adapters(self) -> list[dict[str, Any]]:
        """GET /v1/adapters，返回已安装 LoRA 列表。"""
        try:
            resp = self._session.get(
                self._url("/v1/adapters"), headers=self._headers, timeout=YUE2_POLL_TIMEOUT,
            )
        except requests.RequestException as e:
            raise YuE2Error(f"YuE2 适配器列表查询失败: {e}") from e
        if resp.status_code >= 400:
            raise YuE2Error(f"YuE2 适配器列表查询失败 (HTTP {resp.status_code})")
        try:
            data = resp.json()
        except ValueError as e:
            raise YuE2Error("YuE2 适配器列表返回了无效 JSON") from e
        if isinstance(data, dict):
            data = data.get("installed")
        if not isinstance(data, list):
            return []
        installed = []
        for adapter in data:
            if not isinstance(adapter, dict) or not adapter.get("id") or adapter.get("error"):
                continue
            name = adapter.get("name")
            if isinstance(name, dict):
                adapter = {**adapter, "name": name.get("zh") or name.get("en") or adapter["id"]}
            installed.append(adapter)
        return installed

    def _download(self, path: str, label: str) -> bytes:
        try:
            resp = self._session.get(self._url(path), headers=self._headers, timeout=YUE2_DOWNLOAD_TIMEOUT, stream=True)
        except requests.RequestException as e:
            raise YuE2Error(f"YuE2 {label}下载失败: {e}") from e
        if resp.status_code >= 400:
            resp.close()
            raise YuE2Error(f"YuE2 {label}下载失败 (HTTP {resp.status_code})")
        content = bytearray()
        try:
            for chunk in resp.iter_content(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_AUDIO_BYTES:
                    raise YuE2Error(f"YuE2 {label}超过 300 MB，拒绝下载")
        finally:
            resp.close()
        return bytes(content)
