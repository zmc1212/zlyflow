from __future__ import annotations

import json
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests
import websocket

from ...comfy_service import ComfyService, IDLE_CLEANUP_WORKFLOW, interpret_comfy_progress
from ...minimax_h3_director_accel_workflow import (
    build_minimax_h3_director_accel_workflow,
    director_accel_unet,
)
from ...minimax_h3_dual_accel_workflow import build_minimax_h3_dual_accel_workflow
from ...minimax_h3_lightx2v_workflow import build_minimax_h3_lightx2v_workflow
from ...minimax_h3_t8_workflow import build_minimax_h3_t8_workflow
from ...minimax_h3_workflow import AUDIO_VAE, TEXT_ENCODER, VIDEO_VAE, build_minimax_h3_workflow
from ...models import JobMode
from ...rtx_vsr_workflow import (
    build_rtx_vsr_workflow,
    comfy_has_rtx_vsr_node,
    comfy_vram_device_name,
    comfy_vram_total_bytes,
    explain_comfy_prompt_rejection,
    RTX_VSR_NODE_TYPE,
    rtx_vsr_node_missing_message,
)
from ...workflow_registry import (
    DIRECTOR_ACCEL_WORKFLOWS,
    DUAL_ACCEL_WORKFLOWS,
    LIGHTX2V_WORKFLOWS,
    T8_WORKFLOWS,
    h3_dimensions,
)

from .timeline_rendering import (
    DEFAULT_H3_DIRECTOR_CAPABILITIES,
    build_timeline_render_request,
    duration_seconds,
    frame_count,
)


class ComfyVideoClient:
    TASK_PREFIX = "r2v"
    TIMELINE_CAPABILITIES = DEFAULT_H3_DIRECTOR_CAPABILITIES
    ASPECT_LABELS = {
        "16:9": "16:9 (宽屏)",
        "9:16": "9:16 (竖屏)",
        "1:1": "1:1 (方形)",
        "4:3": "4:3 (标准)",
        "3:4": "3:4 (竖版)",
        "3:2": "3:2 (摄影)",
        "2:3": "2:3 (竖版摄影)",
        "21:9": "21:9 (超宽屏)",
    }

    def __init__(self, base_url: str, *, timeout: int = 30):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self._system_stats: dict[str, Any] | None = None

    def ping(self) -> None:
        try:
            stats = self.session.get(f"{self.base_url}/system_stats", timeout=8)
            stats.raise_for_status()
            payload = stats.json()
            self._system_stats = payload if isinstance(payload, dict) else {}
        except requests.RequestException as err:
            self._system_stats = None
            raise ValueError(f"无法连接 ComfyUI {self.base_url}: {err}") from err
        except ValueError:
            self._system_stats = {}

    def vram_total_bytes(self) -> int | None:
        if self._system_stats is None:
            try:
                self.ping()
            except ValueError:
                return None
        return comfy_vram_total_bytes(self._system_stats or {})

    def vram_device_name(self) -> str:
        if self._system_stats is None:
            try:
                self.ping()
            except ValueError:
                return ""
        return comfy_vram_device_name(self._system_stats or {})

    def require_rtx_vsr_node(self) -> None:
        try:
            response = self.session.get(
                f"{self.base_url}/object_info/{RTX_VSR_NODE_TYPE}", timeout=12,
            )
            payload = response.json() if response.ok else {}
        except requests.RequestException as err:
            raise ValueError(f"无法连接 ComfyUI {self.base_url}: {err}") from err
        except ValueError:
            payload = {}
        if not comfy_has_rtx_vsr_node(payload if isinstance(payload, dict) else {}):
            raise ValueError(rtx_vsr_node_missing_message(self.base_url, self.vram_device_name()))

    def preflight(self, *, require_director: bool = True) -> str:
        self.ping()
        if not require_director:
            return self.TASK_PREFIX
        try:
            info_response = self.session.get(
                f"{self.base_url}/object_info/MiniMaxH3Director", timeout=12
            )
            info_response.raise_for_status()
        except requests.RequestException as err:
            raise ValueError(f"无法连接 ComfyUI {self.base_url}: {err}") from err
        info = info_response.json().get("MiniMaxH3Director") or {}
        choices = (((info.get("input") or {}).get("required") or {}).get("task_type") or [[]])[0]
        task_type = next((str(item) for item in choices if str(item).startswith(self.TASK_PREFIX)), "")
        if not task_type:
            raise ValueError("ComfyUI MiniMaxH3Director 未提供 r2v/Ref2VA 模式。")
        return task_type

    def upload_image(
        self,
        source_url: str,
        *,
        subfolder: str,
        preferred_name: str,
    ) -> dict[str, str]:
        last_error: Exception | None = None
        for _ in range(3):
            try:
                source = self.session.get(source_url, timeout=90, stream=True)
                source.raise_for_status()
                content = source.content
                if not content:
                    raise RuntimeError("下载结果为空")
                content_type = source.headers.get("Content-Type") or "application/octet-stream"
                uploaded = self.session.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (preferred_name, content, content_type)},
                    data={"subfolder": subfolder, "type": "input", "overwrite": "true"},
                    timeout=120,
                )
                uploaded.raise_for_status()
                data = uploaded.json()
                name = str(data.get("name") or preferred_name)
                remote_subfolder = str(data.get("subfolder") or subfolder).strip("/")
                return {
                    "imageFile": str(PurePosixPath(remote_subfolder, name)),
                    "fileName": name,
                    "type": str(data.get("type") or "input"),
                    "subfolder": remote_subfolder,
                }
            except Exception as err:
                last_error = err
                time.sleep(1)
        raise RuntimeError(f"参考图上传失败 {source_url}: {last_error}")

    @classmethod
    def canvas_from_options(cls, options: dict[str, Any] | None = None) -> dict[str, Any]:
        values = {key: value for key, value in dict(options or {}).items() if value is not None}
        aspect_ratio = str(values.get("aspect_ratio") or "16:9")
        if values.get("aspect_ratio") and (
            values.get("quality") is not None or values.get("megapixels") is not None
        ):
            try:
                width, height = h3_dimensions({**values, "aspect_ratio": aspect_ratio})
            except (KeyError, TypeError, ValueError):
                width = int(values.get("width") or 864)
                height = int(values.get("height") or 480)
        else:
            width = int(values.get("width") or 864)
            height = int(values.get("height") or 480)
        megapixels = float(values.get("megapixels") or (width * height / (1024 * 1024)))
        return {
            "width": width,
            "height": height,
            "megapixels": megapixels,
            "aspect_ratio": aspect_ratio,
            "aspect_label": cls.ASPECT_LABELS.get(aspect_ratio, aspect_ratio),
            "long_edge": max(width, height),
        }

    @classmethod
    def build_timeline(
        cls,
        shots: list[dict[str, Any]],
        task_type: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        negative = (
            "camera shake, identity drift, face drift, age change, hairstyle change, "
            "costume change, inconsistent proportions, extra limbs, bad hands, broken lip sync, "
            "random text, subtitles, watermark, scene drift, plastic skin, oversaturated colors, low detail"
        )
        canvas = cls.canvas_from_options(options)
        segments: list[dict[str, Any]] = []
        for index, shot in enumerate(shots):
            duration = duration_seconds(shot)
            frames = frame_count(shot)
            start = sum(int(item.get("frameCount") or 0) for item in segments)
            refs = []
            for ref_index, uploaded in enumerate(shot["uploaded_refs"]):
                refs.append({"index": ref_index, **uploaded})
            segments.append({
                "id": str(shot["beat_id"]),
                "start": start,
                "length": frames,
                "frameCount": frames,
                "durationSec": duration,
                "prompt": shot["prompt"],
                "negativePrompt": negative,
                "taskType": task_type,
                "refs": refs,
                "refAudios": [],
                "refVideos": [],
                "genImage": {"imageFile": "", "fileName": ""},
                "continuityFromPrev": False,
                "refImageSize": "match",
                "referenceVideo": {
                    "videoFile": "", "fileName": "", "type": "input", "subfolder": ""
                },
                "_videoFrameCount": frames,
                "previewFps": 24,
            })
        total_frames = sum(int(segment["frameCount"]) for segment in segments)
        return {
            "version": 5,
            "editMode": "segment",
            "totalFrames": total_frames,
            "frameRate": 24,
            "global": {
                "taskType": task_type,
                "prompt": "",
                "refs": [],
                "referenceVideo": {"videoFile": "", "fileName": "", "type": "input", "subfolder": ""},
                "continuousReference": False,
                "genImage": {"imageFile": ""},
                "sourceWidth": canvas["width"],
                "sourceHeight": canvas["height"],
                "refAudios": [],
                "refVideos": [],
                "commonEnabled": True,
                "commonCollapsed": True,
            },
            "output": {
                "mode": "fixed",
                "aspectRatio": canvas["aspect_label"],
                "megapixels": canvas["megapixels"],
                "multiple": 32,
                "longEdge": canvas["long_edge"],
                "width": canvas["width"],
                "height": canvas["height"],
                "maxExportFrames": 0,
                "exportMode": "all",
                "audioMode": str((options or {}).get("audio_mode") or "generate"),
                "exportSourceImages": False,
                "refImageSize": "match",
                "continuityEnabled": False,
                "continuityOverlapFrames": 5,
                "continuityMode": "guide",
                "continuityRedraw": 0.65,
            },
            "runSelectEnabled": False,
            "runSelection": [],
            "segments": segments,
            "timelineMode": "prompt_batch",
            "width": canvas["width"],
            "height": canvas["height"],
            "refMaxSize": canvas["long_edge"],
            "gen": {"defaultFrameCount": 192},
            "batchDetailMode": "solo",
            "batchWorkspaces": {
                "r2v": {
                    "selectedIndex": 0,
                    "editMode": "segment",
                    "runSelectEnabled": False,
                    "runSelection": [],
                    "segments": segments,
                    "globalCommon": {
                        "commonEnabled": True,
                        "commonCollapsed": True,
                        "prompt": "",
                        "refs": [],
                        "refAudios": [],
                        "refVideos": [],
                    },
                }
            },
        }

    @classmethod
    def build_render_request(
        cls,
        shots: list[dict[str, Any]],
        task_type: str,
        *,
        render_scope: str,
        episode_id: str | None,
        workflow_id: str,
        render_pass: str = "final",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = build_timeline_render_request(
            shots,
            render_scope=render_scope,
            episode_id=episode_id,
            workflow_id=workflow_id,
            render_pass=render_pass,
            task_type=task_type,
        )
        request["timeline_data"] = cls.build_timeline(shots, task_type, options=options)
        return request

    @classmethod
    def build_workflow(
        cls,
        timeline: dict[str, Any],
        task_type: str,
        filename_prefix: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = dict(options or {})
        canvas = cls.canvas_from_options({
            **values,
            "width": timeline.get("width") or values.get("width"),
            "height": timeline.get("height") or values.get("height"),
            "megapixels": (timeline.get("output") or {}).get("megapixels") or values.get("megapixels"),
            "aspect_ratio": values.get("aspect_ratio"),
        })
        total_frames = int(timeline["totalFrames"])
        steps = int(values.get("steps") or 20)
        sampler = str(values.get("sampler_name") or values.get("sampler") or "res_multistep")
        scheduler = str(values.get("scheduler") or "simple")
        cfg = float(values.get("cfg") or 1.0)
        seed = int(values.get("seed") or 888)
        shift_video = float(values.get("shift_video") or 12.0)
        shift_audio = float(values.get("shift_audio") or 3.0)
        sage_allow_compile = bool(values.get("sage_allow_compile", True))
        unet = director_accel_unet(True, values)
        return {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": unet, "weight_dtype": "default"
            }},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": TEXT_ENCODER,
                "type": "minimax", "device": "default"
            }},
            "3": {"class_type": "VAELoader", "inputs": {
                "vae_name": VIDEO_VAE
            }},
            "4": {"class_type": "VAELoader", "inputs": {
                "vae_name": AUDIO_VAE
            }},
            "14": {"class_type": "PathchSageAttentionKJ", "inputs": {
                "model": ["1", 0], "sage_attention": "auto", "allow_compile": sage_allow_compile
            }},
            "15": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {
                "model": ["14", 0]
            }},
            "12": {"class_type": "MiniMaxH3Director", "inputs": {
                "model": ["15", 0], "video_vae": ["3", 0], "audio_vae": ["4", 0], "clip": ["2", 0],
                "task_type": task_type, "global_prompt": "", "bd_grp_sample": "采样设置",
                "cfg": cfg, "seed": seed, "frame_rate": 24.0,
                "width": canvas["width"], "height": canvas["height"],
                "ref_max_size": canvas["long_edge"], "total_frames": total_frames,
                "timeline_data": json.dumps(timeline, ensure_ascii=False),
                "bd_grp_advanced": "高级采样", "steps": steps, "sampler": sampler,
                "scheduler": scheduler, "shift_video": shift_video, "shift_audio": shift_audio,
                "bd_grp_perf": "性能", "clear_vram_between_segments": False,
                "export_source_images": False,
            }},
            "6": {"class_type": "CreateVideo", "inputs": {
                "images": ["12", 0], "audio": ["12", 1], "fps": ["12", 2], "bit_depth": 8
            }},
            "7": {"class_type": "SaveVideo", "inputs": {
                "video": ["6", 0], "filename_prefix": filename_prefix, "format": "auto", "codec": "auto"
            }},
            "8": {"class_type": "PreviewAny", "inputs": {"source": ["12", 5]}},
        }

    @staticmethod
    def load_image_name(uploaded: dict[str, Any] | str) -> str:
        if isinstance(uploaded, str):
            return uploaded
        image_file = str(uploaded.get("imageFile") or "").strip()
        if image_file:
            return image_file
        name = str(uploaded.get("fileName") or uploaded.get("filename") or "").strip()
        subfolder = str(uploaded.get("subfolder") or "").strip("/")
        if subfolder and name:
            return f"{subfolder}/{name}"
        return name

    @staticmethod
    def _set_output_prefix(workflow: dict[str, Any], filename_prefix: str) -> dict[str, Any]:
        for node in workflow.values():
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and "filename_prefix" in inputs:
                inputs["filename_prefix"] = filename_prefix
        return workflow

    @classmethod
    def build_shot_workflow(
        cls,
        workflow_id: str,
        prompt: str,
        uploaded_refs: list[dict[str, Any] | str],
        filename_prefix: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            mode = JobMode(str(workflow_id))
        except ValueError as err:
            raise ValueError(f"不支持的逐镜视频工作流：{workflow_id}") from err
        values = dict(options or {})
        if values.get("duration") is None:
            values["duration"] = 8
        seed = int(values.get("seed") or 888)
        values["seed"] = seed
        references = [cls.load_image_name(item) for item in uploaded_refs if cls.load_image_name(item)]
        if mode in T8_WORKFLOWS:
            workflow = build_minimax_h3_t8_workflow(mode, prompt, references, values)
        elif mode in LIGHTX2V_WORKFLOWS:
            workflow = build_minimax_h3_lightx2v_workflow(mode, prompt, references, values, seed)
        elif mode in DUAL_ACCEL_WORKFLOWS:
            workflow = build_minimax_h3_dual_accel_workflow(mode, prompt, references, values, seed)
        elif mode in DIRECTOR_ACCEL_WORKFLOWS:
            workflow = build_minimax_h3_director_accel_workflow(mode, prompt, references, values, seed)
        else:
            workflow = build_minimax_h3_workflow(mode, prompt, references, values, seed)
        return cls._set_output_prefix(workflow, filename_prefix)

    def submit(self, workflow: dict[str, Any], client_id: str | None = None) -> dict[str, Any]:
        client_id = client_id or str(uuid.uuid4())
        response = self.session.post(
            f"{self.base_url}/prompt",
            json={"client_id": client_id, "prompt": workflow},
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(explain_comfy_prompt_rejection(
                response.status_code,
                response.text,
                comfy_url=self.base_url,
                device_name=comfy_vram_device_name(self._system_stats or {}),
            ))
        data = response.json()
        if data.get("node_errors"):
            raise RuntimeError("ComfyUI 节点校验失败: " + json.dumps(data["node_errors"], ensure_ascii=False))
        if not data.get("prompt_id"):
            raise RuntimeError("ComfyUI 未返回 prompt_id")
        return {**data, "client_id": client_id}

    def progress_socket(self, client_id: str):
        parsed = urlsplit(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        endpoint = urlunsplit(
            (scheme, parsed.netloc, f"{parsed.path.rstrip('/')}/ws", f"clientId={quote(client_id)}", "")
        )
        try:
            connection = websocket.create_connection(endpoint, timeout=3)
            connection.settimeout(1)
            return connection
        except (OSError, ValueError, websocket.WebSocketException):
            return None

    @staticmethod
    def progress_from_message(
        message: dict[str, Any],
        prompt_id: str,
        workflow: dict[str, Any] | None = None,
    ) -> int | None:
        tick = interpret_comfy_progress(message, prompt_id, workflow, "正在生成视频")
        if tick is not None and tick.progress is not None:
            return max(0, min(99, int(tick.progress)))
        percent = ComfyService.progress_percent(message, prompt_id)
        if percent is None:
            return None
        return max(0, min(99, int(percent)))

    def submit_and_wait(
        self,
        workflow: dict[str, Any],
        *,
        progress: Callable[[int], None] | None = None,
        on_submitted: Callable[[dict[str, Any]], None] | None = None,
        timeout_seconds: int = 21600,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
        client_id = str(uuid.uuid4())
        socket = self.progress_socket(client_id)
        try:
            submitted = self.submit(workflow, client_id)
            if on_submitted:
                on_submitted(submitted)
            history, output = self.wait_for_result(
                submitted["prompt_id"],
                progress=progress,
                client_id=client_id,
                workflow=workflow,
                progress_socket=socket,
                timeout_seconds=timeout_seconds,
            )
            return submitted, history, output
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass

    def wait_for_result(
        self,
        prompt_id: str,
        *,
        progress: Callable[[int], None] | None = None,
        client_id: str | None = None,
        workflow: dict[str, Any] | None = None,
        progress_socket: Any = None,
        poll_seconds: int = 2,
        timeout_seconds: int = 21600,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        started = time.monotonic()
        last_history_poll = 0.0
        last_percent: int | None = None
        owned_socket = False
        socket = progress_socket
        if socket is None and client_id:
            socket = self.progress_socket(client_id)
            owned_socket = socket is not None

        def emit(percent: int | None) -> None:
            nonlocal last_percent
            if percent is None or progress is None:
                return
            value = max(0, min(99, int(percent)))
            if value == last_percent:
                return
            last_percent = value
            progress(value)

        try:
            while time.monotonic() - started < timeout_seconds:
                if socket is not None:
                    try:
                        raw_message = socket.recv()
                        if isinstance(raw_message, str):
                            parsed = json.loads(raw_message)
                            if isinstance(parsed, dict):
                                emit(self.progress_from_message(parsed, prompt_id, workflow))
                    except websocket.WebSocketTimeoutException:
                        pass
                    except (ValueError, websocket.WebSocketException):
                        try:
                            socket.close()
                        except Exception:
                            pass
                        socket = None

                now = time.monotonic()
                if now - last_history_poll < poll_seconds:
                    if socket is None:
                        time.sleep(min(0.2, poll_seconds - (now - last_history_poll)))
                    continue
                last_history_poll = now
                history_response = self.session.get(
                    f"{self.base_url}/history/{prompt_id}", timeout=self.timeout
                )
                history_response.raise_for_status()
                history = history_response.json().get(prompt_id)
                if history:
                    status = history.get("status") or {}
                    if status.get("completed") and status.get("status_str") == "success":
                        output = self._find_video(history.get("outputs") or {})
                        if not output:
                            raise RuntimeError("ComfyUI 执行成功，但 SaveVideo 未返回 MP4 输出。")
                        return history, output
                    if status.get("status_str") in {"error", "failed"}:
                        raise RuntimeError(self._history_error(status))
                if socket is None:
                    time.sleep(poll_seconds)
            raise TimeoutError(f"ComfyUI 任务 {prompt_id} 等待超过 {timeout_seconds} 秒")
        finally:
            if owned_socket and socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass

    @staticmethod
    def _find_video(outputs: dict[str, Any]) -> dict[str, str] | None:
        def walk(value: Any) -> dict[str, str] | None:
            if isinstance(value, dict):
                filename = str(value.get("filename") or "")
                if filename.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                    return {
                        "filename": filename,
                        "subfolder": str(value.get("subfolder") or ""),
                        "type": str(value.get("type") or "output"),
                    }
                for nested in value.values():
                    found = walk(nested)
                    if found:
                        return found
            elif isinstance(value, list):
                for nested in value:
                    found = walk(nested)
                    if found:
                        return found
            return None
        return walk(outputs)

    @staticmethod
    def _history_error(status: dict[str, Any]) -> str:
        messages = status.get("messages") or []
        for item in reversed(messages):
            if isinstance(item, (list, tuple)) and item and item[0] == "execution_error":
                detail = item[1] if len(item) > 1 else {}
                if isinstance(detail, dict):
                    return "ComfyUI 执行失败: " + str(detail.get("exception_message") or detail)
        return "ComfyUI 执行失败: " + json.dumps(status, ensure_ascii=False)[:3000]

    def view_url(self, output: dict[str, str]) -> str:
        return f"{self.base_url}/view?{urlencode(output)}"

    def download_output(self, output: dict[str, str]) -> bytes:
        response = self.session.get(self.view_url(output), timeout=600)
        response.raise_for_status()
        return response.content

    def queue_busy(self) -> bool | None:
        try:
            response = self.session.get(f"{self.base_url}/queue", timeout=8)
            if not response.ok:
                return None
            payload = response.json()
        except (ValueError, requests.RequestException):
            return None
        running = payload.get("queue_running") or []
        pending = payload.get("queue_pending") or []
        return bool(running or pending)

    def wait_until_idle(self, *, timeout_seconds: int = 600) -> None:
        started = time.monotonic()
        while time.monotonic() - started < timeout_seconds:
            busy = self.queue_busy()
            if busy is False:
                return
            time.sleep(1)
        raise TimeoutError("ComfyUI 队列仍忙，无法开始 2x 超分")

    def free_resources(self, *, force: bool = True) -> bool:
        busy = self.queue_busy()
        if busy and not force:
            return False
        if busy:
            self.wait_until_idle()
        posted_free = False
        try:
            response = self.session.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=15,
            )
            posted_free = bool(response.ok)
        except requests.RequestException:
            posted_free = False
        try:
            self.submit(IDLE_CLEANUP_WORKFLOW)
            self.wait_until_idle(timeout_seconds=120)
            return True
        except Exception:
            return posted_free

    def upload_video_bytes(
        self,
        content: bytes,
        *,
        preferred_name: str,
        subfolder: str = "rtx-vsr",
    ) -> str:
        if not content:
            raise RuntimeError("超分原片为空")
        uploaded = self.session.post(
            f"{self.base_url}/upload/image",
            files={"image": (preferred_name, content, "video/mp4")},
            data={"subfolder": subfolder, "type": "input", "overwrite": "true"},
            timeout=120,
        )
        uploaded.raise_for_status()
        data = uploaded.json()
        name = str(data.get("name") or preferred_name)
        remote_subfolder = str(data.get("subfolder") or subfolder).strip("/")
        return f"{remote_subfolder}/{name}" if remote_subfolder else name

    def run_rtx_vsr(
        self,
        content: bytes,
        *,
        preferred_name: str,
        progress: Callable[[int], None] | None = None,
        on_submitted: Callable[[dict[str, Any]], None] | None = None,
        filename_prefix: str | None = None,
    ) -> dict[str, str]:
        self.require_rtx_vsr_node()
        self.free_resources(force=True)
        uploaded = self.upload_video_bytes(content, preferred_name=preferred_name)
        workflow = build_rtx_vsr_workflow(uploaded)
        if filename_prefix:
            self._set_output_prefix(workflow, filename_prefix)
        _submitted, _history, output = self.submit_and_wait(
            workflow,
            progress=progress,
            on_submitted=on_submitted,
        )
        return output
