from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import json
import secrets
import socket
import time
import warnings
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from starlette.datastructures import Headers

from ..db import IntegrityError
from ..workflow_registry import normalize_options, validate_option_relationships, validate_references
from .config import McpConfig
from .store import digest

MAX_REFERENCE_BYTES = 50 * 1024 * 1024
MAX_URL_IMPORT_REDIRECTS = 3
NON_IMAGE_SLOT_LABELS = {"video": "视频素材", "audio": "音频素材"}


class CreativeService:
    def __init__(self, app, config: McpConfig, *, settings, submit_generation, public_job,
                 listed_workflows, mode_payload, cancel_job, confirm_refine, skip_refine,
                 output_response, output_available):
        self.app, self.config, self.settings = app, config, settings
        self.submit_generation, self.public_job = submit_generation, public_job
        self.listed_workflows, self.mode_payload = listed_workflows, mode_payload
        self.cancel_handler, self.output_response, self.output_available = cancel_job, output_response, output_available
        self.confirm_refine_handler, self.skip_refine_handler = confirm_refine, skip_refine

    @property
    def records(self):
        return self.app.state.mcp_store

    @property
    def jobs(self):
        return self.app.state.store

    def owned_job(self, user: dict, job_id: str, *, references: bool = False) -> dict:
        try:
            job = self.jobs.get(job_id, include_references=references)
        except KeyError as error:
            raise HTTPException(404, "任务不存在") from error
        if job.get("owner_user_id") != user["id"]:
            raise HTTPException(404, "任务不存在")
        return job

    def workflow(self, workflow_id: str):
        definition = next((item for item in self.listed_workflows() if item.id == workflow_id), None)
        if definition is None:
            raise HTTPException(404, "工作流不存在或未启用")
        return definition

    @staticmethod
    def unsupported_slots(definition) -> list[str]:
        """MCP 参考素材只接受图片，需要视频或音频槽位的工作流无法从这里喂入。"""
        return [f"第 {index} 项需要{NON_IMAGE_SLOT_LABELS[definition.reference_kind(index)]}"
                for index in range(1, definition.max_references + 1)
                if definition.reference_kind(index) != "image"]

    def workflow_detail(self, workflow_id: str) -> dict:
        definition = self.workflow(workflow_id)
        unsupported = self.unsupported_slots(definition)
        if unsupported:
            raise HTTPException(422, "、".join(unsupported) + "；MCP 连接只支持图片参考，"
                "请在工作台 AI 工具中心使用该工作流，或改用图片参考的工作流")
        data = self.mode_payload(definition)
        data.pop("director_controls", None)
        for parameter in data["parameters"]:
            if parameter["name"] == "options":
                schema = dict(parameter["schema"])
                schema["properties"] = {key: value for key, value in schema.get("properties", {}).items() if value.get("ui_group", "internal") in {"primary", "advanced"}}
                schema["required"] = [key for key in schema.get("required", []) if key in schema["properties"]]
                parameter["schema"] = schema
                parameter["type"] = "object"
                parameter["default"] = {}
            elif parameter["name"] == "references":
                parameter["name"] = "reference_asset_ids"
                parameter["description"] = "按给定顺序传入自己的参考图素材 ID；<Picture n> 与此顺序一致"
        return data

    def workflows(self, media_type: str | None = None) -> list[dict]:
        if media_type not in {None, "image", "video"}:
            raise HTTPException(422, "media_type 必须为 image 或 video")
        return [{key: value for key, value in self.workflow_detail(item.id).items() if key != "parameters"}
                for item in self.listed_workflows()
                if (media_type is None or item.media_type == media_type) and not self.unsupported_slots(item)]

    def summary(self, job: dict) -> dict:
        data = self.public_job(job)
        return {"id": job["id"], "workflow_id": job["mode"], "media_type": job["media_type"],
                "title": job.get("title"), "status": job["status"], "stage": job.get("stage"), "progress": job.get("progress", 0),
                "error": job.get("error"), "created_at": job.get("created_at"),
                "job_url": self.config.base + "/generate/" + job["media_type"] + "/" + job["id"],
                "request_parameters": [parameter for parameter in data.get("request_parameters", []) if parameter.get("visibility") != "internal"],
                "rounds": [{"id": row["id"], "status": row["status"], "generation_items": [
                    {key: item.get(key) for key in ("id", "index", "status", "stage", "progress", "error")}
                    for item in row.get("generation_items", [])]} for row in data.get("rounds", [])]}

    def list_jobs(self, user: dict, limit: int = 20) -> list[dict]:
        return [self.summary(job) for job in self.jobs.list_jobs(user["id"], max(1, min(limit, 100)))]

    def _asset(self, user: dict, asset_id: str) -> dict:
        row = self.records.get("reference:" + asset_id)
        if not row or row["kind"] != "reference" or row["status"] != "active" or row["owner_id"] != user["id"]:
            raise HTTPException(404, "参考图不存在")
        return row

    def asset_path(self, user: dict, asset_id: str) -> tuple[dict, Path]:
        row = self._asset(user, asset_id)
        root = (self.settings.uploads_dir / user["id"] / "mcp").resolve()
        path = (self.settings.uploads_dir / row["payload"]["key"]).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(410, "参考图文件已不存在，请重新上传")
        return row, path

    @staticmethod
    def _public_asset(row: dict) -> dict:
        asset_id = row["id"].removeprefix("reference:")
        data = row["payload"]
        return {"id": asset_id, "name": data["name"], "width": data["width"], "height": data["height"],
                "size": data["size"], "mime_type": data["mime_type"], "created_at": row["created_at"],
                "preview_url": "/api/mcp/references/" + asset_id + "/preview"}

    def list_references(self, user: dict) -> list[dict]:
        return [self._public_asset(row) for row in self.records.list("reference", user["id"], 200, active_only=True)]

    def save_reference(self, user: dict, content: bytes, name: str) -> dict:
        if not content or len(content) > MAX_REFERENCE_BYTES:
            raise HTTPException(413, "参考图不能为空，单张不能超过 50 MB")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    width, height, image_format = image.width, image.height, image.format
                    image.verify()
            if image_format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("format")
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise HTTPException(422, "请上传有效的 PNG、JPEG 或 WebP 图片") from error
        asset_id = secrets.token_urlsafe(18)
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image_format]
        key = Path(user["id"]) / "mcp" / (asset_id + suffix)
        destination = self.settings.uploads_dir / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        payload = {"key": key.as_posix(), "name": Path(name).name[:200] or "参考图", "size": len(content),
                   "mime_type": "image/" + ("jpeg" if image_format == "JPEG" else image_format.lower()),
                   "width": width, "height": height}
        try:
            self.records.insert("reference:" + asset_id, "reference", payload, owner_id=user["id"])
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return self._public_asset(self.records.get("reference:" + asset_id))

    @staticmethod
    def _safe_image_target(url: str) -> str:
        """校验图片 URL 并确认解析结果均为公网地址，防止内网探测（SSRF）。"""
        try:
            parsed = urlsplit(url)
            _port = parsed.port  # 仅触发端口解析：端口非法时 urlsplit 会抛 ValueError
        except ValueError as error:
            raise HTTPException(422, "图片 URL 格式无效") from error
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422, "图片 URL 必须是不含凭据的 http/https 地址")
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
        except socket.gaierror as error:
            raise HTTPException(422, "图片 URL 域名无法解析") from error
        if not addresses:
            raise HTTPException(422, "图片 URL 域名无法解析")
        for value in addresses:
            ip = ipaddress.ip_address(value)
            if ip.version == 6 and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise HTTPException(422, "图片 URL 不能指向内网或保留地址")
        return url

    def import_reference_from_url(self, user: dict, url: str, name: str | None = None) -> dict:
        """把在线图片拉进参考图库，供 MCP 创作工具按 ID 引用。"""
        target = url
        response = None
        for _ in range(MAX_URL_IMPORT_REDIRECTS + 1):
            safe = self._safe_image_target(target)
            response = requests.get(safe, timeout=(10, 60), stream=True, allow_redirects=False,
                                    headers={"User-Agent": "zly-ai-studio-mcp/1.0", "Accept": "image/png,image/jpeg,image/webp"})
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("location")
            response.close()
            if not location:
                raise HTTPException(422, "图片 URL 重定向缺少目标地址")
            target = urljoin(safe, location)
        else:
            raise HTTPException(422, "图片 URL 重定向次数过多")
        try:
            if response.status_code != 200:
                raise HTTPException(422, f"图片 URL 拉取失败（HTTP {response.status_code}）")
            declared = int(response.headers.get("content-length") or 0)
            if declared > MAX_REFERENCE_BYTES:
                raise HTTPException(413, "参考图不能超过 50 MB")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=1024 * 256):
                size += len(chunk)
                if size > MAX_REFERENCE_BYTES:
                    raise HTTPException(413, "参考图不能超过 50 MB")
                chunks.append(chunk)
            content = b"".join(chunks)
        finally:
            response.close()
        candidate = (name or "").strip() or Path(urlsplit(target).path).name or "网络参考图"
        return self.save_reference(user, content, candidate)

    def import_reference_from_base64(self, user: dict, image_base64: str, name: str | None = None) -> dict:
        """解码 MCP 客户端传来的 base64 图片（允许 data URL 前缀）存入参考图库，本地图片可在对话里直接提交。"""
        payload = (image_base64 or "").strip()
        if payload.startswith("data:") and "," in payload[:200]:
            payload = payload.split(",", 1)[1]
        if len(payload) > (MAX_REFERENCE_BYTES + 2) // 3 * 4 + 8:
            raise HTTPException(413, "参考图不能超过 50 MB")
        try:
            content = base64.b64decode(payload, validate=True)
        except ValueError as error:
            raise HTTPException(422, "image_base64 不是有效的 base64 编码") from error
        return self.save_reference(user, content, (name or "").strip() or "对话参考图")

    def import_reference(self, user: dict, url: str | None = None, image_base64: str | None = None, name: str | None = None) -> dict:
        """参考图入库统一入口：url 与 image_base64 二选一。"""
        if bool(url) == bool(image_base64):
            raise HTTPException(422, "请提供 url 或 image_base64 中的其中一个")
        if image_base64:
            return self.import_reference_from_base64(user, image_base64, name)
        return self.import_reference_from_url(user, url or "", name)

    def delete_reference(self, user: dict, asset_id: str) -> None:
        row = self._asset(user, asset_id)
        try:
            _, path = self.asset_path(user, asset_id)
            path.unlink(missing_ok=True)
        except PermissionError as error:
            raise HTTPException(409, "参考图正在提交到任务，请稍后删除") from error
        except HTTPException as error:
            if error.status_code != 410:
                raise
        self.records.update(row["id"], status="deleted")

    def generated_images(self, user: dict) -> list[dict]:
        images = []
        for job in self.jobs.list_jobs(user["id"], 100):
            public = self.public_job(job)
            for row in public.get("rounds", []):
                for item in row.get("generation_items", []):
                    for index, output in enumerate(item.get("outputs", [])):
                        if output.get("kind") == "image" and output.get("download_url"):
                            images.append({"job_id": job["id"], "generation_item_id": item["id"], "output_index": index,
                                           "label": job.get("title") or output.get("label") or "生成图片", "preview_url": output["download_url"]})
                            if len(images) >= 100:
                                return images
        return images

    async def reference_from_output(self, user: dict, job_id: str, generation_item_id: str, output_index: int) -> dict:
        job = self.owned_job(user, job_id)
        item = next((item for row in job.get("rounds", []) for item in row.get("generation_items", []) if item["id"] == generation_item_id), None)
        if item is None or not 0 <= output_index < len(item.get("outputs", [])) or item["outputs"][output_index].get("kind") != "image":
            raise HTTPException(404, "生成图片不存在")
        output = item["outputs"][output_index]
        response = await asyncio.to_thread(self.output_response, output)
        if hasattr(response, "path"):
            path = Path(response.path)
            if path.stat().st_size > MAX_REFERENCE_BYTES:
                raise HTTPException(413, "图片超过 50 MB")
            content = await asyncio.to_thread(path.read_bytes)
        elif hasattr(response, "body_iterator"):
            chunks, size = [], 0
            try:
                async for chunk in response.body_iterator:
                    size += len(chunk)
                    if size > MAX_REFERENCE_BYTES:
                        raise HTTPException(413, "图片超过 50 MB")
                    chunks.append(chunk)
                content = b"".join(chunks)
            finally:
                if hasattr(response.body_iterator, "aclose"):
                    await response.body_iterator.aclose()
                if response.background:
                    await response.background()
        else:
            content = response.body
        return await asyncio.to_thread(self.save_reference, user, content, output.get("label") or "生成图片")

    async def create(self, user: dict, media_type: str, workflow_id: str, prompt: str, request_id: str,
                     options: dict | None = None, reference_asset_ids: list[str] | None = None,
                     negative_prompt: str = "", image_size: str | None = None, title: str | None = None) -> dict:
        if not request_id.strip() or len(request_id) > 128:
            raise HTTPException(422, "request_id 必须是 1–128 字符的唯一请求标识，重试时保持不变")
        if not prompt.strip() or len(prompt) > 32000 or len(negative_prompt) > 32000:
            raise HTTPException(422, "提示词不能为空且不能超过 32000 字符")
        options, reference_asset_ids = options or {}, reference_asset_ids or []
        payload = {"media_type": media_type, "workflow_id": workflow_id, "prompt": prompt, "options": options,
                   "reference_asset_ids": reference_asset_ids, "negative_prompt": negative_prompt, "image_size": image_size, "title": title}
        fingerprint = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        request_key = digest(user["id"] + ":" + request_id)
        record_id, job_id = "submission:" + request_key, "mcp" + request_key[:32]
        with self.records.transaction() as connection:
            self.records.insert(record_id, "submission", {"fingerprint": fingerprint, "job_id": job_id}, owner_id=user["id"], connection=connection, ignore=True)
            row = self.records.get(record_id, connection, lock=True)
            if row and row["payload"]["fingerprint"] != fingerprint:
                raise HTTPException(409, "request_id 已用于其他创作参数，请为新创作使用新的标识")
        try:
            existing = self.owned_job(user, job_id)
            return self.summary(existing)
        except HTTPException as error:
            if error.status_code != 404:
                raise
        definition = self.workflow(workflow_id)
        if definition.media_type != media_type:
            raise HTTPException(422, "工作流媒介与创建工具不一致")
        detail = self.workflow_detail(workflow_id)
        schema = next((parameter["schema"] for parameter in detail["parameters"] if parameter["name"] == "options"), {})
        if set(options) - set(schema.get("properties", {})):
            raise HTTPException(422, "包含未知或内部参数，请先查询工作流的创作参数")
        try:
            validate_references(workflow_id, reference_asset_ids)
            normalized = normalize_options(workflow_id, options)
            validate_option_relationships(workflow_id, normalized, len(reference_asset_ids))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with ExitStack() as stack:
            uploads = []
            for asset_id in reference_asset_ids:
                asset, path = self.asset_path(user, asset_id)
                handle = stack.enter_context(path.open("rb"))
                uploads.append(UploadFile(handle, filename=path.name, headers=Headers({"content-type": asset["payload"]["mime_type"]})))
            try:
                await self.submit_generation(user=user, mode=workflow_id, prompt=prompt, options=json.dumps(options),
                    negative_prompt=negative_prompt, image_size=image_size, title=title, references=uploads, job_id=job_id)
            except IntegrityError:
                # Concurrent identical requests have one deterministic jobs PK;
                # only the winning insert reaches the existing worker enqueue.
                self.owned_job(user, job_id)
        self.records.update(record_id, status="submitted")
        return self.summary(self.owned_job(user, job_id))

    async def cancel(self, user: dict, job_id: str) -> dict:
        self.owned_job(user, job_id)
        await self.cancel_handler(job_id=job_id, user=user)
        return self.summary(self.owned_job(user, job_id))

    async def confirm_refine(self, user: dict, job_id: str) -> dict:
        self.owned_job(user, job_id)
        await self.confirm_refine_handler(job_id=job_id, user=user)
        return self.summary(self.owned_job(user, job_id))

    async def skip_refine(self, user: dict, job_id: str) -> dict:
        self.owned_job(user, job_id)
        await self.skip_refine_handler(job_id=job_id, user=user)
        return self.summary(self.owned_job(user, job_id))

    def results(self, user: dict, job_id: str) -> dict:
        job = self.owned_job(user, job_id)
        result = {**self.summary(job), "outputs": [], "unavailable_outputs": [], "expires_in_seconds": 300}
        locators = [(item["id"], index, output) for row in job.get("rounds", []) for item in row.get("generation_items", [])
                    for index, output in enumerate(item.get("outputs", []))]
        if not locators:
            locators = [(None, index, output) for index, output in enumerate(job.get("outputs", []))]
        for item_id, index, output in locators:
            if output.get("delivery_status") in {"local", "expired"} or not self.output_available(output):
                result["unavailable_outputs"].append({"generation_item_id": item_id, "output_index": index,
                    "label": output.get("label"), "reason": "已交付本地，服务器暂存已清理" if output.get("delivery_status") == "local" else "资源已过期或不可读取"})
                continue
            url = self.app.state.resource_storage.download_url(output["path"], expires_in_seconds=300)
            if not url:
                ticket = self.app.state.desktop_delivery_tickets.issue(user["id"], job_id, index, item_id)
                prefix = "/api/jobs/" + job_id + ("/generations/" + item_id if item_id else "")
                url = self.config.base + prefix + "/outputs/" + str(index) + "/download?" + urlencode({"desktop_ticket": ticket})
            result["outputs"].append({"generation_item_id": item_id, "output_index": index, "kind": output.get("kind"),
                                      "label": output.get("label"), "download_url": url, "expires_at": time.time() + 300})
        return result
