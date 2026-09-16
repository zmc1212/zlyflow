from __future__ import annotations

import json
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlencode

import requests


class ComfyVideoClient:
    TASK_PREFIX = "r2v"

    def __init__(self, base_url: str, *, timeout: int = 30):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def preflight(self) -> str:
        try:
            stats = self.session.get(f"{self.base_url}/system_stats", timeout=8)
            stats.raise_for_status()
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

    @staticmethod
    def build_timeline(
        shots: list[dict[str, Any]],
        task_type: str,
        width: int = 864,
        height: int = 480,
    ) -> dict[str, Any]:
        negative = (
            "camera shake, identity drift, face drift, age change, hairstyle change, "
            "costume change, inconsistent proportions, extra limbs, bad hands, broken lip sync, "
            "random text, subtitles, watermark, scene drift, plastic skin, oversaturated colors, low detail"
        )
        segments: list[dict[str, Any]] = []
        frame_cursor = 0
        for index, shot in enumerate(shots):
            frame_count = int(shot.get("frame_count") or 192)
            duration_seconds = int(shot.get("duration_seconds") or 8)
            refs = []
            for ref_index, uploaded in enumerate(shot["uploaded_refs"]):
                refs.append({"index": ref_index, **uploaded})
            segments.append({
                "id": str(shot["beat_id"]),
                "start": frame_cursor,
                "length": frame_count,
                "frameCount": frame_count,
                "durationSec": duration_seconds,
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
                "_videoFrameCount": frame_count,
                "previewFps": 24,
            })
            frame_cursor += frame_count
        total_frames = frame_cursor
        default_frame_count = int(shots[0].get("frame_count") or 192) if shots else 192
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
                "sourceWidth": width,
                "sourceHeight": height,
                "refAudios": [],
                "refVideos": [],
                "commonEnabled": True,
                "commonCollapsed": True,
            },
            "output": {
                "mode": "fixed",
                "aspectRatio": "16:9 (宽屏)",
                "megapixels": round((width * height) / 1_000_000, 2),
                "multiple": 32,
                "longEdge": max(width, height),
                "width": width,
                "height": height,
                "maxExportFrames": 0,
                "exportMode": "all",
                "audioMode": "generate",
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
            "width": width,
            "height": height,
            "refMaxSize": max(width, height),
            "gen": {"defaultFrameCount": default_frame_count},
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

    @staticmethod
    def build_workflow(
        timeline: dict[str, Any],
        task_type: str,
        filename_prefix: str,
        width: int = 864,
        height: int = 480,
        steps: int = 20,
    ) -> dict[str, Any]:
        total_frames = int(timeline["totalFrames"])
        return {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"
            }},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax", "device": "default"
            }},
            "3": {"class_type": "VAELoader", "inputs": {
                "vae_name": "minimax_h3_video_vae_fp16.safetensors"
            }},
            "4": {"class_type": "VAELoader", "inputs": {
                "vae_name": "minimax_h3_audio_vae_fp32.safetensors"
            }},
            "14": {"class_type": "PathchSageAttentionKJ", "inputs": {
                "model": ["1", 0], "sage_attention": "auto", "allow_compile": True
            }},
            "15": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {
                "model": ["14", 0]
            }},
            "12": {"class_type": "MiniMaxH3Director", "inputs": {
                "model": ["15", 0], "video_vae": ["3", 0], "audio_vae": ["4", 0], "clip": ["2", 0],
                "task_type": task_type, "global_prompt": "", "bd_grp_sample": "采样设置",
                "cfg": 1.0, "seed": 888, "frame_rate": 24.0, "width": width, "height": height,
                "ref_max_size": max(width, height), "total_frames": total_frames,
                "timeline_data": json.dumps(timeline, ensure_ascii=False),
                "bd_grp_advanced": "高级采样", "steps": steps, "sampler": "res_multistep",
                "scheduler": "simple", "shift_video": 12.0, "shift_audio": 3.0,
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

    def submit(self, workflow: dict[str, Any], client_id: str | None = None) -> dict[str, Any]:
        client_id = client_id or str(uuid.uuid4())
        response = self.session.post(
            f"{self.base_url}/prompt",
            json={"client_id": client_id, "prompt": workflow},
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(f"ComfyUI 提交失败，HTTP {response.status_code}: {response.text[:1000]}")
        data = response.json()
        if data.get("node_errors"):
            raise RuntimeError("ComfyUI 节点校验失败: " + json.dumps(data["node_errors"], ensure_ascii=False))
        if not data.get("prompt_id"):
            raise RuntimeError("ComfyUI 未返回 prompt_id")
        return {**data, "client_id": client_id}

    def wait_for_result(
        self,
        prompt_id: str,
        *,
        progress: Callable[[int], None] | None = None,
        poll_seconds: int = 5,
        timeout_seconds: int = 21600,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        started = time.monotonic()
        percent = 50
        while time.monotonic() - started < timeout_seconds:
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
            if progress:
                percent = min(95, percent + 1)
                progress(percent)
            time.sleep(poll_seconds)
        raise TimeoutError(f"ComfyUI 任务 {prompt_id} 等待超过 {timeout_seconds} 秒")

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
