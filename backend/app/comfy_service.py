from __future__ import annotations

import json
import mimetypes
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import websocket

import local_video_studio as legacy

from .config import Settings
from .minimax_h3_dual_accel_workflow import build_minimax_h3_dual_accel_workflow
from .minimax_h3_lightx2v_workflow import build_minimax_h3_lightx2v_workflow
from .minimax_h3_t8_workflow import build_minimax_h3_t8_workflow
from .minimax_h3_workflow import build_minimax_h3_workflow
from .models import JobMode
from .resource_storage import BrowserLocalStagingStorage, ResourceStorage, StoredResource
from .workflow_registry import (
    DUAL_ACCEL_WORKFLOWS,
    H3_WORKFLOWS,
    LIGHTX2V_WORKFLOWS,
    T8_WORKFLOWS,
    generation_output_label,
    generation_stage,
)


REFERENCE_ALIASES = {
    "@图1": "场景参考图",
    "@图2": "主体参考图",
    "@图3": "风格参考图",
    "@场景": "场景参考图",
    "@主体": "主体参考图",
    "@风格": "风格参考图",
}
H3_PICTURE_ALIAS_RE = re.compile(r"@图片\s*(\d+)|@图\s*(\d+)")
H3_PICTURE_TAG_RE = re.compile(r"<Picture\s+(\d+)>", flags=re.IGNORECASE)
IDLE_CLEANUP_WORKFLOW = {
    "1": {
        "class_type": "VRAMCleanup",
        "inputs": {"offload_model": True, "offload_cache": True},
    },
    "2": {
        "class_type": "RAMCleanup",
        "inputs": {
            "clean_file_cache": False,
            "clean_processes": False,
            "clean_dlls": True,
            "retry_times": 1,
        },
    },
}


@dataclass(frozen=True)
class ComfyQueuePrompt:
    prompt_id: str
    client_id: str | None
    prompt: str | None
    created_at: datetime | None


class ComfyUnavailable(legacy.ComfyError):
    """ComfyUI/FRP is unreachable long enough that the worker should release its slot."""


class ComfyCancelled(legacy.ComfyError):
    """The workbench user stopped this prompt; do not auto-retry."""


def resolve_reference_prompt(prompt: str, reference_count: int) -> str:
    """Turn UI mention tokens into model-readable reference instructions."""
    mentioned_numbers = [int(number) for number in re.findall(r"@图([1-3])", prompt)]
    if any(number > reference_count for number in mentioned_numbers):
        raise legacy.ComfyError(f"当前模式只上传了 {reference_count} 张参考图，不能引用 @图{max(mentioned_numbers)}。")
    used_reference = any(token in prompt for token in REFERENCE_ALIASES)
    text = prompt
    for token, label in REFERENCE_ALIASES.items():
        text = text.replace(token, label)
    if not used_reference:
        return text
    if reference_count == 1:
        return f"{text}\n参考图约束：以已上传的参考图作为主体、服装、风格或场景的视觉依据。"
    return (
        f"{text}\n参考图约束：场景参考图用于环境和构图；主体参考图用于人物或物体；"
        "风格参考图用于画面质感与色彩。仅在提示词中点名的参考图上继承对应特征。"
    )


def resolve_minimax_picture_prompt(prompt: str, reference_count: int) -> str:
    """Map MiniMax H3 mention aliases to official <Picture n> tags."""

    def replacement(match: re.Match) -> str:
        return f"<Picture {int(match.group(1) or match.group(2))}>"

    text = H3_PICTURE_ALIAS_RE.sub(replacement, prompt)
    picture_numbers = [int(value) for value in H3_PICTURE_TAG_RE.findall(text)]
    if picture_numbers and max(picture_numbers) > reference_count:
        raise legacy.ComfyError(
            f"当前只上传了 {reference_count} 张参考图，不能引用 <Picture {max(picture_numbers)}>。"
        )
    if reference_count > 0 and not picture_numbers:
        mentions = "、".join(f"<Picture {index}>" for index in range(1, reference_count + 1))
        text = f"{text.rstrip()}\n以{mentions}作为人物、服装、场景或风格依据。"
    return text


class ComfyService:
    """ComfyUI HTTP client that reuses the proven workflow node mappings."""

    def __init__(
        self,
        settings: Settings,
        resource_storage: ResourceStorage | None = None,
        url_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.resource_storage = resource_storage or BrowserLocalStagingStorage(settings.staging_dir)
        self._url_resolver = url_resolver
        self.last_execution_elapsed_ms: int | None = None

    @property
    def comfy_url(self) -> str:
        if self._url_resolver is not None:
            return self._url_resolver().rstrip("/")
        return self.settings.comfy_url

    @staticmethod
    def execution_elapsed_ms(record: dict | None) -> int | None:
        if not isinstance(record, dict):
            return None
        messages = record.get("status", {}).get("messages") or []
        start = end = None
        for item in messages:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            kind = item[0]
            payload = item[1] if isinstance(item[1], dict) else {}
            timestamp = payload.get("timestamp")
            if not isinstance(timestamp, (int, float)):
                continue
            if kind == "execution_start":
                start = float(timestamp)
            elif kind in {"execution_success", "execution_error", "execution_interrupted"}:
                end = float(timestamp)
        if start is None or end is None or end < start:
            return None
        delta = end - start
        if start > 1e11 and end > 1e11:
            return max(0, int(delta))
        return max(0, int(round(delta * 1000)))

    def health(self) -> dict:
        try:
            response = requests.get(f"{self.comfy_url}/system_stats", timeout=3)
            return {"reachable": response.ok, "url": self.comfy_url}
        except requests.RequestException as error:
            return {"reachable": False, "url": self.comfy_url, "error": str(error)}

    def upload_image(self, local_path: str, tag: str) -> str:
        source = Path(local_path)
        filename = f"{tag}_{int(time.time() * 1000)}_{secrets.token_hex(4)}{source.suffix.lower() or '.png'}"
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        try:
            with source.open("rb") as file:
                response = requests.post(
                    f"{self.comfy_url}/upload/image",
                    data={"overwrite": "true"}, files={"image": (filename, file, mime_type)}, timeout=(5, 30),
                )
        except requests.RequestException as error:
            raise ComfyUnavailable("ComfyUI 或 FRP 当前不可用，任务尚未提交。") from error
        if not response.ok:
            raise legacy.ComfyError(f"上传图像到 ComfyUI 失败: {response.text}")
        payload = response.json()
        name = payload.get("name")
        if not name:
            raise legacy.ComfyError(f"ComfyUI 上传接口未返回文件名: {payload}")
        return f"{payload.get('subfolder')}/{name}" if payload.get("subfolder") else name

    def progress_socket(self, client_id: str):
        parsed = urlsplit(self.comfy_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        endpoint = urlunsplit((scheme, parsed.netloc, f"{parsed.path.rstrip('/')}/ws", f"clientId={quote(client_id)}", ""))
        try:
            connection = websocket.create_connection(endpoint, timeout=3)
            connection.settimeout(1)
            return connection
        except (OSError, ValueError, websocket.WebSocketException):
            return None

    @staticmethod
    def progress_percent(message: dict, prompt_id: str) -> int | None:
        if message.get("type") != "progress_state":
            return None
        payload = message.get("data", {})
        if payload.get("prompt_id") != prompt_id:
            return None
        nodes = payload.get("nodes", {})
        active_nodes = [node for node in nodes.values() if node.get("state") == "running"]
        if not active_nodes:
            return None
        node = active_nodes[-1]
        maximum = node.get("max", 0)
        if not isinstance(maximum, (int, float)) or maximum <= 0:
            return None
        value = node.get("value", 0)
        if not isinstance(value, (int, float)):
            return None
        return max(0, min(100, round(value * 100 / maximum)))

    def submit(self, workflow: dict, client_id: str) -> str:
        try:
            response = requests.post(
                f"{self.comfy_url}/prompt", json={"prompt": workflow, "client_id": client_id}, timeout=(5, 30),
            )
        except requests.RequestException as error:
            raise ComfyUnavailable("ComfyUI 或 FRP 当前不可用，任务尚未提交。") from error
        if not response.ok:
            raise legacy.ComfyError(f"ComfyUI 拒绝工作流: {response.text}")
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise legacy.ComfyError("ComfyUI 未返回任务 ID。")
        return prompt_id

    @staticmethod
    def queue_prompt(entry: object) -> ComfyQueuePrompt | None:
        if not isinstance(entry, list) or len(entry) < 4 or not isinstance(entry[1], str):
            return None
        workflow = entry[2] if isinstance(entry[2], dict) else {}
        metadata = entry[3] if isinstance(entry[3], dict) else {}
        prompt = next(
            (
                inputs["prompt"]
                for node in workflow.values()
                if isinstance(node, dict)
                for inputs in [node.get("inputs", {})]
                if isinstance(inputs, dict) and isinstance(inputs.get("prompt"), str)
            ),
            None,
        )
        timestamp = metadata.get("create_time")
        created_at = None
        if isinstance(timestamp, (int, float)):
            created_at = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        client_id = metadata.get("client_id")
        return ComfyQueuePrompt(entry[1], client_id if isinstance(client_id, str) else None, prompt, created_at)

    def active_prompts(self) -> list[ComfyQueuePrompt] | None:
        try:
            response = requests.get(f"{self.comfy_url}/queue", timeout=(5, 15))
            if not response.ok:
                return None
            payload = response.json()
        except (ValueError, requests.RequestException):
            return None
        entries = [
            entry
            for key in ("queue_running", "queue_pending")
            for entry in payload.get(key, [])
        ]
        try:
            history = requests.get(f"{self.comfy_url}/history", timeout=(5, 15))
            if history.ok:
                entries.extend(
                    record.get("prompt")
                    for record in history.json().values()
                    if isinstance(record, dict) and isinstance(record.get("prompt"), list)
                )
        except (ValueError, requests.RequestException):
            pass
        prompts = [item for entry in entries if (item := self.queue_prompt(entry)) is not None]
        return list({item.prompt_id: item for item in prompts}.values())

    def live_queue_ids(self) -> tuple[set[str], set[str]] | None:
        try:
            response = requests.get(f"{self.comfy_url}/queue", timeout=(5, 15))
            if not response.ok:
                return None
            payload = response.json()
        except (ValueError, requests.RequestException):
            return None

        def ids_for(key: str) -> set[str]:
            values: set[str] = set()
            for entry in payload.get(key, []):
                if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], str):
                    values.add(entry[1])
            return values

        return ids_for("queue_running"), ids_for("queue_pending")

    def stop_prompt(self, prompt_id: str) -> None:
        running_ids: set[str] = set()
        pending_ids: set[str] = set()
        live = self.live_queue_ids()
        if live is not None:
            running_ids, pending_ids = live
        try:
            if prompt_id in pending_ids or live is None:
                requests.post(
                    f"{self.comfy_url}/queue", json={"delete": [prompt_id]}, timeout=(5, 15),
                )
            if prompt_id in running_ids or live is None:
                requests.post(
                    f"{self.comfy_url}/interrupt", json={"prompt_id": prompt_id}, timeout=(5, 15),
                )
        except requests.RequestException:
            return

    def free_resources(self) -> bool:
        """Unload ComfyUI models and drop caches when its queue is idle.

        ComfyUI keeps UNET/CLIP/VAE in VRAM and RAM after a prompt so the next
        run is faster. Workbench API graphs do not include cleanup nodes, so the
        worker must ask ComfyUI to unload once no local video job remains.

        POST /free only sets flags, and the prompt worker may wait up to 1000s
        when idle. A tiny VRAMCleanup prompt wakes that loop immediately.
        """
        live = self.live_queue_ids()
        if live is None:
            return False
        running_ids, pending_ids = live
        if running_ids or pending_ids:
            return False
        posted_free = False
        try:
            response = requests.post(
                f"{self.comfy_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=(5, 15),
            )
            posted_free = bool(response.ok)
        except requests.RequestException:
            posted_free = False
        try:
            self.submit(IDLE_CLEANUP_WORKFLOW, f"zly-ai-video-studio-free-{secrets.token_hex(4)}")
            return True
        except Exception:
            return posted_free

    def prompt_state(self, prompt_id: str, active_prompt_ids: set[str]) -> tuple[str, dict | None]:
        try:
            response = requests.get(f"{self.comfy_url}/history/{prompt_id}", timeout=(5, 15))
            if response.ok:
                record = response.json().get(prompt_id)
                if record:
                    status = record.get("status", {}).get("status_str")
                    if status == "error":
                        return "failed", record
                    if status == "success" or record.get("outputs"):
                        return "completed", record
        except (ValueError, requests.RequestException):
            return "unknown", None
        return ("active", None) if prompt_id in active_prompt_ids else ("missing", None)

    def wait(
        self, prompt_id: str, update_progress: Callable[[int], None], progress_socket=None,
        progress_range: tuple[int, int] = (0, 100),
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        started = time.monotonic()
        last_history_poll = 0.0
        unavailable_since: float | None = None
        missing_since: float | None = None
        while time.monotonic() - started < legacy.REQUEST_TIMEOUT_SECONDS:
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            if progress_socket is not None:
                try:
                    raw_message = progress_socket.recv()
                    if isinstance(raw_message, str):
                        percent = self.progress_percent(json.loads(raw_message), prompt_id)
                        if percent is not None:
                            start, end = progress_range
                            update_progress(round(start + (end - start) * percent / 100))
                except websocket.WebSocketTimeoutException:
                    pass
                except (ValueError, websocket.WebSocketException):
                    progress_socket.close()
                    progress_socket = None

            if time.monotonic() - last_history_poll < 2:
                time.sleep(0.2)
                continue
            last_history_poll = time.monotonic()
            try:
                # ComfyUI can temporarily stop answering HTTP requests while a
                # large model is loading or a long video step is running. The
                # prompt remains active, so a single polling read timeout must
                # not turn the job into a failed ZLY AI Video Studio task.
                response = requests.get(f"{self.comfy_url}/history/{prompt_id}", timeout=(5, 15))
            except requests.RequestException as error:
                unavailable_since = unavailable_since or time.monotonic()
                if time.monotonic() - unavailable_since >= 30:
                    raise ComfyUnavailable(
                        "ComfyUI 或 FRP 连接中断，任务已暂停。恢复后将自动重新提交。"
                    ) from error
                time.sleep(2)
                continue
            unavailable_since = None
            if response.ok:
                record = response.json().get(prompt_id)
                if record:
                    missing_since = None
                    status = record.get("status", {}).get("status_str")
                    if status == "error":
                        elapsed = self.execution_elapsed_ms(record)
                        if elapsed is not None:
                            self.last_execution_elapsed_ms = (self.last_execution_elapsed_ms or 0) + elapsed
                        raise legacy.ComfyError(f"ComfyUI 推理失败: {legacy.get_error_message(record)}")
                    if status == "success" or record.get("outputs"):
                        elapsed = self.execution_elapsed_ms(record)
                        if elapsed is not None:
                            self.last_execution_elapsed_ms = (self.last_execution_elapsed_ms or 0) + elapsed
                        return record
                else:
                    active_prompts = self.active_prompts()
                    if active_prompts is None or prompt_id in {item.prompt_id for item in active_prompts}:
                        missing_since = None
                    else:
                        missing_since = missing_since or time.monotonic()
                        if time.monotonic() - missing_since >= 30:
                            raise ComfyUnavailable(
                                "ComfyUI 重启后未找到原任务，任务已暂停。恢复后将自动重新提交。"
                            )
            else:
                unavailable_since = unavailable_since or time.monotonic()
                if time.monotonic() - unavailable_since >= 30:
                    raise ComfyUnavailable("ComfyUI 或 FRP 连接中断，任务已暂停。恢复后将自动重新提交。")
            time.sleep(2)
        raise ComfyUnavailable(f"等待 ComfyUI 超时（{legacy.REQUEST_TIMEOUT_SECONDS // 60} 分钟）。")

    def run_workflow(
        self, workflow: dict, stage: str, update_stage: Callable[[str, int | None], None],
        progress_range: tuple[int, int] = (0, 100),
        on_submitted: Callable[[str, str, str], None] | None = None, phase: str = "generation",
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        client_id = f"zly-ai-video-studio-{secrets.token_hex(8)}"
        connection = self.progress_socket(client_id)
        try:
            prompt_id = self.submit(workflow, client_id)
            if on_submitted is not None:
                on_submitted(prompt_id, client_id, phase)
            if is_cancelled is not None and is_cancelled():
                self.stop_prompt(prompt_id)
                raise ComfyCancelled("任务已停止")
            update_stage(stage, progress_range[0])
            return self.wait(
                prompt_id,
                lambda progress: update_stage(stage, progress),
                connection,
                progress_range,
                is_cancelled,
            )
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def output_source_info(file_info: dict) -> dict:
        filename = file_info.get("filename")
        if not isinstance(filename, str) or not filename or filename != Path(filename).name:
            raise legacy.ComfyError(f"ComfyUI 输出缺少 filename: {file_info}")
        raw_subfolder = file_info.get("subfolder", "")
        subfolder = str(raw_subfolder).replace("\\", "/")
        folder = PurePosixPath(subfolder)
        if folder.is_absolute() or ".." in folder.parts:
            raise legacy.ComfyError(f"ComfyUI 输出目录不合法: {file_info}")
        return {
            "filename": filename,
            "subfolder": subfolder,
            "type": str(file_info.get("type", "output")),
        }

    def open_output_stream(self, source_info: dict) -> requests.Response:
        source = self.output_source_info(source_info)
        if source["type"] != "output":
            raise legacy.ComfyError("仅允许交付 ComfyUI output 目录中的文件。")
        try:
            response = requests.get(
                f"{self.comfy_url}/view",
                params=source,
                stream=True,
                timeout=(5, 120),
            )
        except requests.RequestException as error:
            raise legacy.ComfyError(f"读取 ComfyUI 输出失败: {error}") from error
        if not response.ok:
            detail = response.text
            response.close()
            raise legacy.ComfyError(f"读取 ComfyUI 输出失败: {detail}")
        return response

    def can_stream_output(self, source_info: dict | None) -> bool:
        if not self.resource_storage.streams_outputs or not source_info:
            return False
        try:
            self.output_source_info(source_info)
        except legacy.ComfyError:
            return False
        return source_info.get("type", "output") == "output"

    def finalize_output_source(self, source_info: dict | None) -> bool:
        if self.resource_storage.retains_comfy_outputs:
            return True
        return self.delete_output_source(source_info)

    def download(self, file_info: dict, prefix: str, *, require_local: bool = False) -> StoredResource:
        source_info = self.output_source_info(file_info)
        filename = source_info["filename"]
        if self.resource_storage.streams_outputs and not require_local:
            stored = self.resource_storage.create_reference(prefix, filename)
            return StoredResource(stored.key, stored.local_path, source_info)
        response = self.open_output_stream(source_info)
        try:
            stored = self.resource_storage.store_bytes(prefix, filename, response.content)
        finally:
            response.close()
        return StoredResource(stored.key, stored.local_path, source_info)

    def output_payload(self, resource: StoredResource, kind: str, label: str) -> dict:
        return {
            "kind": kind,
            "path": resource.key,
            "label": label,
            "delivery_status": "cloud" if self.resource_storage.persistent_outputs else "pending",
            "delivered_at": None,
            "_comfy_source": resource.source_info,
        }

    def delete_output_source(self, source_info: dict | None) -> bool:
        if not source_info:
            return True
        if source_info.get("type", "output") != "output":
            return False
        filename = str(source_info.get("filename", ""))
        if not filename or filename != Path(filename).name:
            return False
        output_root = self.settings.comfy_output_dir.resolve()
        subfolder = str(source_info.get("subfolder", ""))
        candidate = (output_root / subfolder / filename).resolve()
        if candidate.parent != output_root and output_root not in candidate.parents:
            return False
        if not candidate.exists():
            return True
        if not candidate.is_file():
            return False
        candidate.unlink()
        return True

    def wait_for_existing(
        self, prompt_id: str, client_id: str | None, update_stage: Callable[[str, int | None], None],
        stage: str, progress_range: tuple[int, int] = (0, 100),
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        connection = self.progress_socket(client_id) if client_id else None
        try:
            update_stage(stage, progress_range[0])
            return self.wait(
                prompt_id,
                lambda progress: update_stage(stage, progress),
                connection,
                progress_range,
                is_cancelled,
            )
        finally:
            if connection is not None:
                connection.close()

    def completed_outputs(self, mode: JobMode, record: dict) -> list[dict]:
        if mode in H3_WORKFLOWS:
            output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3")
            return [self.output_payload(output, "video", generation_output_label(mode))]
        if mode is JobMode.IMAGE:
            output = self.download(legacy.output_file(record, legacy.T2I_OUTPUT_NODE, ("images",)), "text_to_image")
            return [self.output_payload(output, "image", "生成图片")]
        if mode is JobMode.VACE_VIDEO:
            output = self.download(legacy.output_file(record, legacy.VACE_OUTPUT_NODE, ("videos", "gifs", "images")), "wan_vace_multi_reference")
            return [self.output_payload(output, "video", "VACE 视频")]
        raise legacy.ComfyError(f"不支持恢复工作流模式: {mode}")

    def resume(
        self, mode: JobMode, prompt: str, prompt_id: str, client_id: str | None, phase: str,
        existing_outputs: list[dict], update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None], save_partial_outputs: Callable[[list[dict]], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[dict]:
        self.last_execution_elapsed_ms = None
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        if phase == "generation":
            record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "已重新连接 ComfyUI 任务", is_cancelled=is_cancelled,
            )
            return self.completed_outputs(mode, record)

        resolved_prompt = resolve_reference_prompt(prompt, 3)
        if phase == "flux-first-frame":
            frame_record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "正在恢复首帧生成", (0, 25), is_cancelled,
            )
            first_frame = self.download(
                legacy.output_file(frame_record, legacy.FLUX_OUTPUT_NODE, ("images",)), "first_frame", require_local=True,
            )
            outputs = [self.output_payload(first_frame, "image", "生成首帧")]
            save_partial_outputs(outputs)
            update_stage("首帧已完成，LTX 2.3 正在生成视频")
            frame_input = self.upload_image(str(first_frame.local_path), "generated_first_frame")
            video_record = self.run_workflow(
                legacy.build_ltx_workflow(frame_input, resolved_prompt), "首帧已完成，LTX 2.3 正在生成视频", update_stage,
                (25, 95), on_submitted, "ltx-video", is_cancelled,
            )
            video = self.download(legacy.output_file(video_record, legacy.LTX_OUTPUT_NODE, ("videos", "gifs", "images")), "video")
            return outputs + [self.output_payload(video, "video", "LTX 视频")]

        if phase == "ltx-video":
            video_record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "正在恢复 LTX 2.3 视频生成", (25, 95), is_cancelled,
            )
            video = self.download(legacy.output_file(video_record, legacy.LTX_OUTPUT_NODE, ("videos", "gifs", "images")), "video")
            return existing_outputs + [self.output_payload(video, "video", "LTX 视频")]

        raise legacy.ComfyError(f"不支持恢复任务阶段: {phase}")

    def run(
        self, mode: JobMode, references: list[str], prompt: str, negative_prompt: str,
        image_size: str | None, options: dict, update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None], save_partial_outputs: Callable[[list[dict]], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[dict]:
        self.last_execution_elapsed_ms = None
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        if mode in H3_WORKFLOWS:
            resolved_prompt = resolve_minimax_picture_prompt(prompt, len(references))
            update_stage("正在上传参考素材" if references else "正在提交文生视频任务")
            uploaded = []
            for index, path in enumerate(references, 1):
                if is_cancelled is not None and is_cancelled():
                    raise ComfyCancelled("任务已停止")
                uploaded.append(self.upload_image(path, f"h3_reference_{index}"))
            workflow = (
                build_minimax_h3_t8_workflow(mode, resolved_prompt, uploaded, options)
                if mode in T8_WORKFLOWS
                else build_minimax_h3_lightx2v_workflow(
                    mode, resolved_prompt, uploaded, options, secrets.randbits(63),
                )
                if mode in LIGHTX2V_WORKFLOWS
                else build_minimax_h3_dual_accel_workflow(
                    mode, resolved_prompt, uploaded, options, secrets.randbits(63),
                )
                if mode in DUAL_ACCEL_WORKFLOWS
                else build_minimax_h3_workflow(mode, resolved_prompt, uploaded, options, secrets.randbits(63))
            )
            record = self.run_workflow(
                workflow, generation_stage(mode), update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
            )
            output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3")
            return [self.output_payload(output, "video", generation_output_label(mode))]

        resolved_prompt = resolve_reference_prompt(prompt, len(references))
        if mode is JobMode.IMAGE:
            update_stage("正在上传参考素材" if references else "正在提交文生图任务")
            reference = self.upload_image(references[0], "image_reference") if references else None
            workflow = legacy.build_text_to_image_workflow(resolved_prompt, negative_prompt, image_size or "横版 1280 x 720", reference)
            record = self.run_workflow(
                workflow, "Flux2-Klein 正在生成图片", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
            )
            output = self.download(legacy.output_file(record, legacy.T2I_OUTPUT_NODE, ("images",)), "text_to_image")
            return [self.output_payload(output, "image", "生成图片")]

        if len(references) != 3:
            raise legacy.ComfyError("视频模式需要上传场景、主体和风格三张参考图。")
        update_stage("正在上传三张参考素材")
        uploaded = tuple(self.upload_image(path, f"reference_{index}") for index, path in enumerate(references, 1))
        if mode is JobMode.VACE_VIDEO:
            record = self.run_workflow(
                legacy.build_vace_multi_reference_workflow(uploaded, resolved_prompt), "Wan VACE 正在生成视频", update_stage,
                on_submitted=on_submitted, is_cancelled=is_cancelled,
            )
            output = self.download(legacy.output_file(record, legacy.VACE_OUTPUT_NODE, ("videos", "gifs", "images")), "wan_vace_multi_reference")
            return [self.output_payload(output, "video", "VACE 视频")]

        frame_record = self.run_workflow(
            legacy.build_flux_workflow(uploaded, resolved_prompt), "正在生成首帧", update_stage, (0, 25), on_submitted, "flux-first-frame",
            is_cancelled=is_cancelled,
        )
        first_frame = self.download(
            legacy.output_file(frame_record, legacy.FLUX_OUTPUT_NODE, ("images",)), "first_frame", require_local=True,
        )
        first_frame_output = [self.output_payload(first_frame, "image", "生成首帧")]
        save_partial_outputs(first_frame_output)
        update_stage("首帧已完成，LTX 2.3 正在生成视频")
        frame_input = self.upload_image(str(first_frame.local_path), "generated_first_frame")
        video_record = self.run_workflow(
            legacy.build_ltx_workflow(frame_input, resolved_prompt), "首帧已完成，LTX 2.3 正在生成视频", update_stage, (25, 95), on_submitted, "ltx-video",
            is_cancelled=is_cancelled,
        )
        video = self.download(legacy.output_file(video_record, legacy.LTX_OUTPUT_NODE, ("videos", "gifs", "images")), "video")
        return first_frame_output + [self.output_payload(video, "video", "LTX 视频")]
