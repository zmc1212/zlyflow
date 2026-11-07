from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import re
import secrets
import tempfile
import time
import urllib.request
from urllib.error import URLError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import websocket
from PIL import Image

import local_video_studio as legacy

from .config import Settings
from .minimax_h3_director_accel_workflow import build_minimax_h3_director_accel_workflow
from .minimax_h3_action_workflow import build_minimax_h3_action_workflow
from .minimax_h3_dual_accel_workflow import build_minimax_h3_dual_accel_workflow
from .minimax_h3_lightx2v_workflow import build_minimax_h3_lightx2v_workflow
from .minimax_h3_refine_workflow import (
    PREVIEW_OUTPUT_NODE,
    build_minimax_h3_refine_workflow,
    continuation_workflow,
)
from .minimax_h3_t8_workflow import build_minimax_h3_t8_workflow
from .minimax_h3_avatar_workflow import build_minimax_h3_avatar_workflow
from .minimax_h3_lipsync_workflow import build_minimax_h3_lipsync_workflow
from .minimax_h3_workflow import build_minimax_h3_workflow
from .models import JobMode
from .motion_transfer_media import prepare_motion_reference_video, prepare_motion_video
from .keep_face_restore_workflow import (
    KEEP_NODE, KEEP_OUTPUT_NODE, KEEP_OUTPUT_LABEL,
    build_keep_face_restore_workflow, keep_missing_message,
)
from .scail2_workflow import SCAIL_OUTPUT_NODE, SCAIL_DIAGNOSTIC_PREFIX, build_scail2_workflow, prepare_scail_inputs, scail_missing_message
from .face_swap_workflow import (
    FACE_OUTPUT_NODE, build_face_swap_workflow, face_aspect_ratio, face_swap_missing_message,
)
from .video_analysis import probe_video
from .resource_storage import BrowserLocalStagingStorage, ResourceStorage, StoredResource, resource_object_url
from .rtx_vsr_workflow import (
    RTX_VSR_NODE_TYPE,
    RTX_VSR_PHASE,
    UPSCALE_OUTPUT_LABEL,
    VSR_OUTPUT_NODE,
    build_rtx_vsr_workflow,
    comfy_has_rtx_vsr_node,
    comfy_vram_device_name,
    comfy_vram_total_bytes,
    explain_comfy_prompt_rejection,
    original_video_output,
    rtx_vsr_node_missing_message,
    source_video_shape,
    vsr_memory_rejection,
    wants_upscale,
)
from .seedvr2_upscale_workflow import (
    SEEDVR2_OBJECT_INFO_TYPES,
    SEEDVR2_OUTPUT_LABEL,
    SEEDVR2_OUTPUT_NODE,
    SEEDVR2_PHASE,
    UPSCALE_ENGINE_RTX,
    UPSCALE_ENGINE_SEEDVR2,
    build_seedvr2_upscale_workflow,
    normalize_upscale_engine,
    seedvr2_missing_message,
)
from .video_depth_workflow import DEPTH_OUTPUT_NODE, build_depth_video_workflow
from .wan_vace_depth_workflow import VACE_OUTPUT_NODE, build_vace_depth_workflow
from .h3_motion_transfer_workflow import (
    MOTION_TRANSFER_DEFAULT_PROMPT,
    MOTION_TRANSFER_OUTPUT_NODE,
    build_h3_motion_transfer_workflow,
)
from .h3_motion_ref_video_workflow import (
    MOTION_REF_VIDEO_OUTPUT_NODE,
    build_h3_motion_ref_video_workflow,
)

# 2026-11-04 复刻官方 Aiden 多人模板的 ImageCaption 机制：后端视觉模型逐角色生成
# 像素级外观描述 bake 进 <Subject> 绑定，使用户不写角色长相也能稳定换人。
# 提示词沿用模板"像素级描述(by:阿丹)"的约束：忠实图片、描述体型比例、不描述手持物品。
MOTION_REF_CAPTION_SYSTEM = (
    "你是视频换人工作流的角色外观速记员。只看图片中唯一的主要角色，"
    "输出恰好一句 40-80 字的中文外观短语（以“的XX”结尾，可直接当句子主语），"
    "忠实图片只写：人设类型（真人/3D娃娃/卡通等）、身形、发型发色、"
    "服装款式与颜色、鞋。不要标题、引号、序号、解释，不要写手持物品和配饰，"
    "不要编造看不到的细节。"
)

# 2026-11-04 三代图内 caption 注入实测全部不换人，唯一成功样本 xbzyTzeDkK6S 的写法是
# 描述段首句用中文外观主语紧贴动作。润色改写就是把这个写法自动化。
MOTION_REF_POLISH_SYSTEM = (
    "你在为“多人动作迁移视频”改写创作描述。模型只认一种主语写法：描述段首句用"
    "“外观特征 + 身份”直接点名画面主角，紧接着写他要复刻的动作。规则："
    "1) 把每个角色的外观短语自然织入与其动作绑定的主语句（如“长直黑发、穿黑色"
    "吊带裙和白色运动鞋的女孩是画面中央的唯一主角，她完整复刻……”），主角动作的"
    "节拍、幅度、镜头、背景、音画同步等其余内容必须原意保留；"
    "2) 不得引入用户和外观短语里没有的新角色、新物品、新场景；"
    "3) 输出恰好一段纯中文创作描述，不写小标题、序号、英文模板、<Picture>、"
    "<Video>、subject_definitions 或任何解释。"
)

from .h3_inpaint_workflow import (
    INPAINT_OUTPUT_NODE,
    build_h3_inpaint_workflow,
    prepare_inpaint_source,
    validate_inpaint_video,
)
from .image_edit_workflow import (
    LAYER_BACKGROUND_NODE,
    LAYER_FOREGROUND_NODE,
    SAM3_OUTPUT_NODE,
    build_image_edit_workflow,
)
from .h3_depth_workflow import (
    DEPTH_OUTPUT_NODE as H3_DEPTH_OUTPUT_NODE,
    DEPTH_PREVIEW_NODE as H3_DEPTH_PREVIEW_NODE,
    DEPTH_DEFAULT_PROMPT,
    DEPTH_LENGTHS,
    build_h3_depth_workflow,
    prepare_depth_source,
    validate_depth_source,
)
from .h3_keyframe_workflow import (
    KEYFRAME_OUTPUT_NODE,
    build_h3_keyframe_workflow,
    resolve_keyframe_anchor_frames,
)
from .h3_video_edit_workflow import (
    VIDEO_EDIT_OUTPUT_NODE, build_h3_video_edit_workflow, prepare_video_edit_source,
    validate_video_edit_source, video_edit_dimensions,
)
from .stem_split_workflow import (
    STEM_SPLIT_MODEL,
    STEM_SPLIT_INSTRUMENTS_NODE,
    STEM_SPLIT_VOCALS_NODE,
    build_stem_split_workflow,
)
from .workflow_registry import (
    ACTION_WORKFLOWS,
    DIRECTOR_ACCEL_WORKFLOWS,
    DUAL_ACCEL_WORKFLOWS,
    H3_WORKFLOWS,
    LIGHTX2V_WORKFLOWS,
    T8_WORKFLOWS,
    coerce_bool_option,
    generation_output_label,
    generation_stage,
    is_comfy_image_workflow,
    is_rtx_vsr_workflow,
    is_seedvr2_upscale_workflow,
    normalize_options,
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
# Requests also uses the connect timeout while sending the request body. A
# 5-second value can abort large reference images sent through FRP.
COMFY_UPLOAD_TIMEOUT = (120, 180)
COMFY_UPLOAD_ATTEMPTS = 3
logger = logging.getLogger(__name__)
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


COMFY_SWITCH_STAGE = "正在切换工作流"
COMFY_PREPARE_STAGE = "正在准备任务"
COMFY_EXPORT_STAGE = "正在导出视频"
LOADER_CLASS_TYPES = frozenset({
    "UNETLoader", "CLIPLoader", "VAELoader", "CheckpointLoaderSimple",
    "LoraLoaderModelOnly", "LoraLoaderBypassModelOnly", "LoraLoader",
    "ReservedVRAMSetter", "MiniMaxH3MemoryEfficientSageAttentionPatch",
    "PathchSageAttentionKJ", "LoadImage", "LoadVideo", "VRAMCleanup", "RAMCleanup",
    "MiniMaxH3DirectorGroupImageToVideo", "MiniMaxH3DirectorGroupReferenceToVideo",
})
SAMPLER_CLASS_TYPES = frozenset({
    "SamplerCustomAdvanced", "SamplerCustom", "KSampler", "KSamplerAdvanced",
    "MiniMaxH3MultiRateSamplerEXPT8", "MiniMaxH3DualClockSamplerT8",
    "MiniMaxH3Director", RTX_VSR_NODE_TYPE, KEEP_NODE,
})
DECODE_CLASS_TYPES = frozenset({
    "VAEDecode", "VAEDecodeAudio", "CreateVideo", "SaveVideo",
    "VHS_VideoCombine", "MiniMaxH3AVDecodeT8", "SaveImage",
})


@dataclass(frozen=True)
class ComfyProgressTick:
    stage: str
    progress: int | None = None


def node_class_type(workflow: dict | None, node_id: object) -> str:
    if not workflow or node_id is None:
        return ""
    node = workflow.get(str(node_id))
    if isinstance(node, dict):
        return str(node.get("class_type") or "")
    return ""


def node_phase(class_type: str) -> str:
    if class_type in LOADER_CLASS_TYPES:
        return "loader"
    if class_type in SAMPLER_CLASS_TYPES:
        return "sampler"
    if class_type in DECODE_CLASS_TYPES:
        return "decode"
    return "other"


def node_percent(value: object, maximum: object) -> int | None:
    if not isinstance(maximum, (int, float)) or maximum <= 0:
        return None
    if not isinstance(value, (int, float)):
        return None
    return max(0, min(100, round(value * 100 / maximum)))


def interpret_comfy_progress(
    message: dict, prompt_id: str, workflow: dict | None, generation_stage: str,
) -> ComfyProgressTick | None:
    """Map ComfyUI socket traffic to a wait-for-switch stage or sampling percent."""
    if not isinstance(message, dict) or not workflow:
        return None
    msg_type = message.get("type")
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    incoming_prompt = data.get("prompt_id")
    if incoming_prompt not in (None, prompt_id):
        return None

    def tick_for(node_id: object, percent: int | None) -> ComfyProgressTick | None:
        entry = workflow.get(str(node_id), {})
        if (entry.get("class_type") == "SaveImage"
                and str(entry.get("inputs", {}).get("filename_prefix", "")).startswith(SCAIL_DIAGNOSTIC_PREFIX)):
            return ComfyProgressTick(COMFY_PREPARE_STAGE, 12)
        phase = node_phase(node_class_type(workflow, node_id))
        if phase == "loader":
            return ComfyProgressTick(COMFY_SWITCH_STAGE, 5 + round((percent or 0) * 13 / 100))
        if phase == "sampler":
            return ComfyProgressTick(generation_stage or "正在生成", percent)
        if phase == "decode":
            return ComfyProgressTick(COMFY_EXPORT_STAGE, min(98, 90 + round((percent or 0) * 8 / 100)))
        return ComfyProgressTick(
            COMFY_PREPARE_STAGE,
            12 if percent is None else min(20, 12 + round(percent * 8 / 100)),
        )

    if msg_type == "executing":
        node = data.get("node")
        if not node:
            return None
        return tick_for(node, None)
    if msg_type == "progress":
        return tick_for(data.get("node"), node_percent(data.get("value"), data.get("max")))
    if msg_type != "progress_state" or incoming_prompt != prompt_id:
        return None
    nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
    running = [
        (node_id, node) for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("state") == "running"
    ]
    if not running:
        return None
    node_id, node = running[-1]
    return tick_for(node_id, node_percent(node.get("value"), node.get("max")))


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


def _split_box_pixels(per_mille: object, source: str) -> dict:
    """框选拆分：把千分比坐标串 "x0,y0,x1,y1" 换算成原图像素矩形（供 graph 构建）。"""
    if not isinstance(per_mille, str) or not per_mille.strip():
        raise legacy.ComfyError("框选拆分需要在原图上先框选区域。")
    parts = per_mille.split(",")
    if len(parts) != 4:
        raise legacy.ComfyError("框选区域格式不正确。")
    try:
        x0, y0, x1, y1 = (float(part) for part in parts)
    except ValueError as error:
        raise legacy.ComfyError("框选区域格式不正确。") from error
    if not all(0 <= value <= 1000 for value in (x0, y0, x1, y1)) or x1 - x0 < 1 or y1 - y0 < 1:
        raise legacy.ComfyError("框选区域无效，请在原图上重新框选。")
    try:
        with Image.open(source) as image:
            width, height = image.size
    except OSError as error:
        raise legacy.ComfyError("原图无法读取，请重新上传。") from error
    return {
        "x": round(x0 / 1000 * width),
        "y": round(y0 / 1000 * height),
        "width": max(1, round((x1 - x0) / 1000 * width)),
        "height": max(1, round((y1 - y0) / 1000 * height)),
    }


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
        self.last_refine_state: dict | None = None

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
            stats = response.json() if response.ok else {}
            return {
                "reachable": response.ok,
                "url": self.comfy_url,
                "vram_total": comfy_vram_total_bytes(stats if isinstance(stats, dict) else {}),
                "gpu": comfy_vram_device_name(stats if isinstance(stats, dict) else {}),
            }
        except requests.RequestException as error:
            return {
                "reachable": False,
                "url": self.comfy_url,
                "error": str(error),
                "vram_total": None,
                "gpu": None,
            }

    def system_stats(self) -> dict:
        try:
            response = requests.get(f"{self.comfy_url}/system_stats", timeout=5)
            if not response.ok:
                return {}
            payload = response.json()
        except (requests.RequestException, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def reject_vsr_memory(self, mode: JobMode, options: dict | None) -> str | None:
        shape = source_video_shape(mode, options)
        if shape is None:
            return None
        stats = self.system_stats()
        return vsr_memory_rejection(
            *shape,
            vram_total=comfy_vram_total_bytes(stats),
            device_name=comfy_vram_device_name(stats),
        )

    def object_info(self, class_type: str = "") -> dict:
        suffix = f"/{class_type}" if class_type else ""
        try:
            response = requests.get(f"{self.comfy_url}/object_info{suffix}", timeout=12)
            if not response.ok:
                return {}
            payload = response.json()
        except (requests.RequestException, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def require_rtx_vsr_node(self) -> None:
        if not comfy_has_rtx_vsr_node(self.object_info(RTX_VSR_NODE_TYPE)):
            raise legacy.ComfyError(
                rtx_vsr_node_missing_message(self.comfy_url, comfy_vram_device_name(self.system_stats()))
            )

    def require_seedvr2(self) -> None:
        info: dict = {}
        for class_type in SEEDVR2_OBJECT_INFO_TYPES:
            info.update(self.object_info(class_type))
        reason = seedvr2_missing_message(
            info,
            comfy_url=self.comfy_url,
            device_name=comfy_vram_device_name(self.system_stats()),
        )
        if reason:
            raise legacy.ComfyError(reason)

    def require_keep_face_restore(self) -> None:
        reason = keep_missing_message(self.object_info(KEEP_NODE))
        if reason:
            raise legacy.ComfyError(reason)

    def upload_image(self, local_path: str, tag: str) -> str:
        source = Path(local_path)
        filename = f"{tag}_{int(time.time() * 1000)}_{secrets.token_hex(4)}{source.suffix.lower() or '.png'}"
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        size_mb = source.stat().st_size / 1_000_000
        upload_url = f"{self.comfy_url}/upload/image"
        for attempt in range(1, COMFY_UPLOAD_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                # Reopen from byte zero and reuse the remote name on retry so
                # a lost response cannot leave multiple copies of the image.
                with source.open("rb") as file:
                    response = requests.post(
                        upload_url,
                        data={"overwrite": "true"}, files={"image": (filename, file, mime_type)},
                        timeout=COMFY_UPLOAD_TIMEOUT,
                    )
                break
            except requests.RequestException as error:
                logger.warning(
                    "ComfyUI upload failed: file=%s size=%.2fMB attempt=%s/%s elapsed=%.2fs error=%s: %s",
                    source.name, size_mb, attempt, COMFY_UPLOAD_ATTEMPTS,
                    time.monotonic() - started, type(error).__name__, error,
                    exc_info=True,
                )
                if isinstance(error, (requests.ConnectionError, requests.Timeout)) and attempt < COMFY_UPLOAD_ATTEMPTS:
                    time.sleep(attempt)
                    continue
                raise ComfyUnavailable(
                    f"参考素材 {source.name}（{size_mb:.2f} MB）上传失败：{type(error).__name__}: {error}。"
                    "ComfyUI 或 FRP 连接中断，任务尚未提交。"
                ) from error
        if not response.ok:
            raise legacy.ComfyError(f"上传图像到 ComfyUI 失败: {response.text}")
        payload = response.json()
        name = payload.get("name")
        if not name:
            raise legacy.ComfyError(f"ComfyUI 上传接口未返回文件名: {payload}")
        return f"{payload.get('subfolder')}/{name}" if payload.get("subfolder") else name

    def upload_video(self, local_path: str, tag: str) -> str:
        """上传视频到 ComfyUI input 目录（/upload/image 接口接受任意文件，VHS 从该目录读取）。"""
        return self.upload_image(local_path, tag)

    def run_depth_extraction(
        self, video_path: str | Path, *, fps: int, frame_cap: int, resolution: int = 504,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> StoredResource:
        """把参考片交给 ComfyUI 的 Depth Anything 3 提取时序稳定深度视频，返回本地文件。"""
        filename = self.upload_video(str(video_path), "depth_source")
        workflow = build_depth_video_workflow(filename, fps=fps, frame_cap=frame_cap, resolution=resolution)
        record = self.run_workflow(
            workflow, "正在提取参考片深度视频", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        return self.download(
            legacy.output_file(record, DEPTH_OUTPUT_NODE, ("videos", "gifs", "images")),
            "depth_video", require_local=True,
        )

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
            raise legacy.ComfyError(explain_comfy_prompt_rejection(
                response.status_code,
                response.text,
                comfy_url=self.comfy_url,
                device_name=comfy_vram_device_name(self.system_stats()),
            ))
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

    def free_resources(self, *, force: bool = False) -> bool:
        """Unload ComfyUI models and drop caches when its queue is idle.

        ComfyUI keeps UNET/CLIP/VAE in VRAM and RAM after a prompt so the next
        run is faster. Workbench API graphs do not include cleanup nodes, so the
        worker must ask ComfyUI to unload once no local video job remains.

        POST /free only sets flags, and the prompt worker may wait up to 1000s
        when idle. A tiny VRAMCleanup prompt wakes that loop immediately.

        force=True is for RTX VSR: 12GB cards must unload H3 even when the
        workbench still has the next job queued. Comfy's own queue is still
        respected unless live queue lookup failed.
        """
        live = self.live_queue_ids()
        if live is None:
            if not force:
                return False
            running_ids, pending_ids = set(), set()
        else:
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
                    status = (record.get("status") or {}).get("status_str")
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
        *,
        workflow: dict | None = None,
        generation_stage: str | None = None,
        update_stage: Callable[[str, int | None], None] | None = None,
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
                        parsed = json.loads(raw_message)
                        tick = interpret_comfy_progress(
                            parsed, prompt_id, workflow, generation_stage or "",
                        )
                        start, end = progress_range
                        if tick is not None:
                            mapped = (
                                round(start + (end - start) * tick.progress / 100)
                                if tick.progress is not None else None
                            )
                            if update_stage is not None:
                                update_stage(tick.stage, mapped)
                            elif mapped is not None:
                                update_progress(mapped)
                        else:
                            percent = self.progress_percent(parsed, prompt_id)
                            if percent is not None:
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
            if response.ok:
                try:
                    record = response.json().get(prompt_id)
                except (ValueError, AttributeError):
                    # A proxy may answer 200 with a non-JSON or non-object
                    # body; treat that like a transient outage instead of
                    # failing the job. unavailable_since is only reset after a
                    # healthy parse so the 30s threshold can actually fire.
                    unavailable_since = unavailable_since or time.monotonic()
                    if time.monotonic() - unavailable_since >= 30:
                        raise ComfyUnavailable(
                            "ComfyUI 或 FRP 连接中断，任务已暂停。恢复后将自动重新提交。"
                        )
                    time.sleep(2)
                    continue
                unavailable_since = None
                if record:
                    missing_since = None
                    status = (record.get("status") or {}).get("status_str")
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
                    live = self.live_queue_ids()
                    if live is None or prompt_id in live[0] | live[1]:
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
            update_stage(COMFY_SWITCH_STAGE, 5 if progress_range[0] == 0 else progress_range[0])
            return self.wait(
                prompt_id,
                lambda progress: update_stage(stage, progress),
                connection,
                progress_range,
                is_cancelled,
                workflow=workflow,
                generation_stage=stage,
                update_stage=update_stage,
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
            content = response.content
            stored = self.resource_storage.store_bytes(prefix, filename, content)
            if require_local and stored.local_path is None:
                # 云端存储（如七牛）不保留本地文件，但调用方需要真实路径做本地处理
                #（拉片切分、首帧提取等），这里把手上的字节流落到 staging。
                stored = StoredResource(
                    stored.key, self._materialize_local(prefix, filename, content), source_info,
                )
        finally:
            response.close()
        return StoredResource(stored.key, stored.local_path, source_info)

    def _materialize_local(self, prefix: str, source_filename: str, content: bytes) -> Path:
        local_root = self.settings.staging_dir / "comfy-local"
        local_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(source_filename).suffix or ".bin"
        destination = local_root / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}{suffix}"
        destination.write_bytes(content)
        return destination

    def output_payload(self, resource: StoredResource, kind: str, label: str) -> dict:
        payload = {
            "kind": kind,
            "path": resource.key,
            "label": label,
            "delivery_status": "cloud" if self.resource_storage.persistent_outputs else "pending",
            "delivered_at": None,
            "_comfy_source": resource.source_info,
        }
        cloud_url = resource_object_url(self.resource_storage, resource.key)
        if cloud_url:
            payload["cloud_url"] = cloud_url
        if resource.local_path is not None:
            payload["_local_path"] = str(resource.local_path)
        return payload

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

    _VACE_MODEL_INFO_TTL_SEC = 300

    def _resolve_vace_model_names(self) -> dict[str, str]:
        """按远端 ComfyUI /object_info 实际清单解析 VACE 所需模型文件名。

        远端节点与模型路径以远端实例实际配置为准：优先精确匹配内置文件名，
        其次按特征匹配（vace unet / wan vae / umt5 clip），都找不到时给出
        可执行的放置指引而不是让远端校验报一堆 value_not_in_list。
        """
        cached = getattr(self, "_vace_model_names_cache", None)
        now = time.monotonic()
        if cached and now - cached[0] < self._VACE_MODEL_INFO_TTL_SEC:
            return cached[1]

        def filenames(class_type: str, field: str) -> list[str]:
            payload = self.object_info(class_type)
            spec = (payload.get(class_type) or {}).get("input", {}).get("required", {}).get(field, [])
            return [str(item) for item in (spec[0] if spec else []) if isinstance(item, str)]

        unets = filenames("UNETLoader", "unet_name")
        unet = next((n for n in unets if n == "wan2.1_vace_1.3B.safetensors"), None)
        unet = unet or next((n for n in unets if "vace" in n.lower()), None)
        if not unet:
            raise legacy.ComfyError(
                "远端 ComfyUI 缺少 Wan VACE 模型：请在其实例的 diffusion_models（unet）目录放置 "
                f"wan2.1_vace_1.3B.safetensors 后重试。当前可选 unet：{unets}。"
            )
        vaes = filenames("VAELoader", "vae_name")
        vae = next((n for n in vaes if n == "wan_2.1_vae.safetensors"), None)
        vae = vae or next((n for n in vaes if re.search(r"wan.?2.?1.*vae", n, re.IGNORECASE)), None)
        if not vae:
            raise legacy.ComfyError(
                f"远端 ComfyUI 缺少 Wan 2.1 VAE：请在其实例 vae 目录放置 wan_2.1_vae.safetensors。当前可选：{vaes}。"
            )
        clips = filenames("CLIPLoader", "clip_name")
        clip = next((n for n in clips if n == "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), None)
        clip = clip or next((n for n in clips if "umt5" in n.lower()), None)
        if not clip:
            raise legacy.ComfyError(
                f"远端 ComfyUI 缺少 UMT5 文本编码器：请在其实例 text_encoders（clip）目录放置 "
                f"umt5_xxl_fp8_e4m3fn_scaled.safetensors。当前可选：{clips}。"
            )
        resolved = {"unet": unet, "vae": vae, "clip": clip}
        self._vace_model_names_cache = (now, resolved)
        return resolved

    def _run_vace_depth_replication(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """复刻台专用：references[0] 为深度控制视频，其后为可选参考图（首帧/主体/风格）。"""
        if not references:
            raise legacy.ComfyError("深度复刻需要至少上传一个深度控制视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在上传深度控制视频")
        control_video = self.upload_video(references[0], "vace_depth_control")
        uploaded_refs: list[str] = []
        for index, path in enumerate(references[1:], 1):
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            uploaded_refs.append(self.upload_image(path, f"vace_reference_{index}"))
        normalized = normalize_options(JobMode.WAN_VACE_DEPTH_V2V, options or {})
        # registry 对 seed 字段始终随机化；这里读原始提交值，0 表示随机，
        # 并把实际使用的 seed 回写进生效参数快照以支持复现。
        requested_seed = int((options or {}).get("seed") or 0)
        seed = requested_seed if requested_seed > 0 else int(normalized.get("seed") or 0) or secrets.randbits(31)
        normalized["seed"] = seed
        model_names = self._resolve_vace_model_names()
        workflow = build_vace_depth_workflow(
            control_video,
            uploaded_refs,
            prompt,
            negative_prompt=negative_prompt,
            width=int(normalized.get("width") or 832),
            height=int(normalized.get("height") or 480),
            length=int(normalized.get("length") or 81),
            vace_strength=float(normalized.get("vace_strength") or 1.0),
            steps=int(normalized.get("steps") or 30),
            cfg=float(normalized.get("cfg") or 5.0),
            shift=float(normalized.get("shift") or 16.0),
            sampler=str(normalized.get("sampler") or "uni_pc"),
            scheduler=str(normalized.get("scheduler") or "simple"),
            seed=seed,
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            unet_name=model_names["unet"],
            clip_name=model_names["clip"],
            vae_name=model_names["vae"],
        )
        record = self.run_workflow(
            workflow, "Wan VACE 正在复刻镜头", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, VACE_OUTPUT_NODE, ("videos", "gifs", "images")), "wan_vace_depth",
        )
        return [self.output_payload(output, "video", "VACE 复刻视频")]

    def _run_keep_face_restore(
        self, references: list[str], options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        if not 1 <= len(references) <= 2:
            raise legacy.ComfyError("人脸高清修复需要待修复视频，可另外提供同一片段的高清前原片。")
        self.require_keep_face_restore()
        normalized = normalize_options(JobMode.KEEP_FACE_RESTORE, options or {})
        self.free_resources(force=True)
        uploaded = []
        for index, path in enumerate(references):
            if is_cancelled and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage("正在上传人脸修复素材", None)
            uploaded.append(self.upload_video(path, f"keep_face_{index}"))
        workflow = build_keep_face_restore_workflow(uploaded[0], uploaded[-1], normalized)
        record = self.run_workflow(workflow, "正在跟踪并高清修复所选人脸", update_stage,
                                   on_submitted=on_submitted, is_cancelled=is_cancelled)
        return self.completed_outputs(JobMode.KEEP_FACE_RESTORE, record)

    def _run_scail2_replacement(
        self, references: list[str], prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        if len(references) != 2:
            raise legacy.ComfyError("动作迁移需要角色形象图和动作参考视频。")
        def check_cancelled() -> None:
            if is_cancelled and is_cancelled():
                raise ComfyCancelled("任务已停止")
        check_cancelled()
        normalized = normalize_options(JobMode.SCAIL2_REPLACEMENT, options or {})
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        update_stage("正在准备动作片段与人物标记", None)
        with tempfile.TemporaryDirectory(prefix="scail2-", dir=self.settings.staging_dir) as directory:
            prepared = prepare_scail_inputs(Path(references[0]), Path(references[1]), Path(directory), normalized)
            check_cancelled()
            update_stage("正在上传人物与动作素材", None)
            image = self.upload_image(str(prepared["image"]), "scail2_character")
            check_cancelled()
            video = self.upload_video(str(prepared["video"]), "scail2_motion")
            check_cancelled()
            first = self.upload_image(str(prepared["first"]), "scail2_first")
        graph = build_scail2_workflow(image, video, first, prompt,
                                     width=prepared["width"], height=prepared["height"],
                                     source_coords=prepared["source_coords"], reference_coords=prepared["reference_coords"],
                                     seed=normalized["seed"], preserve_audio=normalized["preserve_audio"],
                                     length=normalized["length"],
                                     source_coords_by_subject=prepared.get("source_coords_by_subject"),
                                     reference_coords_by_subject=prepared.get("reference_coords_by_subject"))
        check_cancelled()
        reason = scail_missing_message(self.object_info(), graph)
        if reason:
            raise legacy.ComfyError(reason)
        record = self.run_workflow(graph, "正在跟踪人物并迁移动作与表情", update_stage,
                                   on_submitted=on_submitted, is_cancelled=is_cancelled)
        return self.completed_outputs(JobMode.SCAIL2_REPLACEMENT, record)

    def _run_face_swap(
        self, references: list[str], prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """H3 角色替换（换头修脸）：references[0] 为角色形象图，references[1] 为原片视频。
        形象图在远端由内嵌 yolov8m 子图自动裁成纯脸特写，避免半身参考图导致矩形鬼影。"""
        if len(references) != 2:
            raise legacy.ComfyError("角色替换需要上传角色形象图和原片视频。")
        def check_cancelled() -> None:
            if is_cancelled and is_cancelled():
                raise ComfyCancelled("任务已停止")
        check_cancelled()
        normalized = normalize_options(JobMode.MINIMAX_H3_FACE_SWAP, options or {})
        update_stage("正在上传角色形象图", None)
        reference_image = self.upload_image(references[0], "face_swap_reference")
        check_cancelled()
        update_stage("正在上传原片视频", None)
        source_video = self.upload_video(references[1], "face_swap_source")
        check_cancelled()
        # 交付链是“整段重生成→贴脸”，重生成底图画幅跟随原片方向；模板冻结的 9:16
        # 竖屏会把横屏原片重画成竖屏。探测失败时保留模板画幅，不因此阻断任务。
        aspect_ratio = ""
        try:
            probe = probe_video(Path(references[1]))
            aspect_ratio = face_aspect_ratio(int(probe.width), int(probe.height))
        except (OSError, ValueError, RuntimeError):  # VideoAnalysisError 继承 RuntimeError
            pass
        graph = build_face_swap_workflow(
            reference_image, source_video, prompt,
            crop_factor=normalized["crop_factor"],
            frame_load_cap=normalized["frame_load_cap"],
            confidence=normalized["confidence"],
            aspect_ratio=aspect_ratio or None,
        )
        reason = face_swap_missing_message(self.object_info(), graph)
        if reason:
            raise legacy.ComfyError(reason)
        record = self.run_workflow(graph, "正在检测人脸并替换角色身份", update_stage,
                                   on_submitted=on_submitted, is_cancelled=is_cancelled)
        return self.completed_outputs(JobMode.MINIMAX_H3_FACE_SWAP, record)

    def _run_motion_transfer(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """H3 动作迁移：references[0] 为角色形象图，references[1] 为动作参考视频。"""
        if len(references) != 2:
            raise legacy.ComfyError("动作迁移需要上传角色形象图和动作参考视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在上传角色形象图")
        character_image = self.upload_image(references[0], "motion_transfer_character")
        normalized = normalize_options(JobMode.MINIMAX_H3_MOTION_TRANSFER, options or {})
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在截取动作片段并对齐帧率")
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="motion-reference-", dir=self.settings.staging_dir) as directory:
            prepared = prepare_motion_video(
                Path(references[1]), Path(directory) / "motion.mp4",
                fps=normalized["fps"], length=normalized["length"],
            )
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage("正在上传动作参考视频")
            motion_video = self.upload_video(str(prepared), "motion_transfer_control")
        workflow = build_h3_motion_transfer_workflow(
            character_image,
            motion_video,
            prompt.strip() or MOTION_TRANSFER_DEFAULT_PROMPT,
            width=normalized["width"],
            height=normalized["height"],
            length=normalized["length"],
            control_strength=float(normalized.get("control_strength") or 1.0),
            steps=int(normalized.get("steps") or 20),
            seed=normalized["seed"],
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            fps=int(normalized.get("fps") or 24),
        )
        record = self.run_workflow(
            workflow, "H3 正在迁移动作", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, MOTION_TRANSFER_OUTPUT_NODE, ("videos", "gifs", "images")),
            "h3_motion_transfer",
        )
        return [self.output_payload(output, "video", "H3 动作迁移视频")]

    @staticmethod
    def _caption_image_data_url(path: str) -> str:
        """角色图缩到长边 1024 JPEG 再转 data URL：原图 base64 动辄 2MB，会撞上游
        输入长度上限，也会让部分视觉网关直接丢弃图片（模型谎称看不到图）。"""
        mime = mimetypes.guess_type(path)[0] or "image/png"
        raw = Path(path).read_bytes()
        try:
            image = Image.open(io.BytesIO(raw))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((1024, 1024))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")

    def _describe_motion_ref_characters(
        self, paths: list[str], is_cancelled: Callable[[], bool] | None,
    ) -> list[str]:
        """逐角色图生成像素级外观描述（复刻官方模板 ImageCaption 机制）。

        不走全局 authoring 路由（它会把名义可用的免费 VLM 当视觉），只选探针记录
        或模型名实锤能看图的端点。视觉服务缺失、未启用或单图失败时该项返回空串
        （构图时自然跳过，退化回旧行为），绝不阻断任务；取消信号照常抛出。
        """
        captions: list[str] = []
        try:
            from .llm_provider import model_supports_vision
            from .media_studio.provider_bridge import credential_manager, llm_row, vlm_row
            from .vision_runtime import (
                VisionEndpoint,
                chat_on_endpoint,
                endpoint_from_row,
                overlay_vlm_credentials,
            )
            decrypt = credential_manager().decrypt
            llm, vlm = dict(llm_row() or {}), dict(vlm_row() or {})
            endpoint = None
            for source, row in (("llm", llm), ("vlm", vlm)):
                candidate = endpoint_from_row(
                    source,
                    overlay_vlm_credentials(row, llm) if source == "vlm" else row,
                    decrypt,
                    require_vision=False,
                )
                if candidate is None:
                    continue
                probed = str(row.get("vision_capability") or "").lower() == "supported"
                if probed or model_supports_vision(candidate.model):
                    endpoint = VisionEndpoint(
                        source=candidate.source,
                        base_url=candidate.base_url,
                        model=candidate.model,
                        api_key=candidate.api_key,
                        attach_images=True,
                    )
                    break
            if endpoint is None:
                return [""] * len(paths)
        except Exception:
            # 配置不可读（隔离测试/未初始化）同样退化，不阻断建任务。
            return [""] * len(paths)
        consecutive_failures = 0
        for path in paths:
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            if consecutive_failures >= 2:
                # 视觉服务连续两张图都打不通（限流/网络死）就放弃余下角色，
                # 避免每张白等超时；单张审核失败（夹在成功之间）不会触发。
                captions.extend([""] * (len(paths) - len(captions)))
                break
            caption = ""
            try:
                text = chat_on_endpoint(
                    endpoint,
                    MOTION_REF_CAPTION_SYSTEM,
                    "用一句中文速记图片中主要角色的外观，可直接作句子主语。",
                    [self._caption_image_data_url(path)],
                    max_tokens=600,
                    temperature=0.3,
                    timeout=120.0,
                )
                caption = re.sub(r"\s+", " ", str(text or "")).strip().strip('"')[:400]
                if caption:
                    ascii_ratio = sum(1 for ch in caption if ord(ch) < 128) / max(len(caption), 1)
                    if ascii_ratio > 0.6:
                        # 要求输出中文短语；英文占比高说明模型在答非所问（如声称看不到图），
                        # 这种文本烧进 prompt 只会污染身份绑定，直接丢弃。
                        caption = ""
            except Exception:
                caption = ""
            consecutive_failures = consecutive_failures + 1 if not caption else 0
            captions.append(caption)
        return captions

    def _inject_appearance_into_prompt(
        self, prompt: str, captions: list[str], is_cancelled: Callable[[], bool] | None,
    ) -> str:
        """润色改写：把角色外观短语织成描述段首句的中文外观主语（复刻成功样本句式）。

        三代图内注入实测证明模型不做跨段引用推理，也不认长英文 caption 主语句，
        只认"中文外观主语紧贴动作"。改写失败或产出可疑（英文模板/乱码/过短）时
        原样返回用户提示词，绝不阻断建任务；取消信号照常抛出。
        """
        profiles = [
            f"角色 {index + 1}：{str(caption).strip()}"
            for index, caption in enumerate(captions)
            if str(caption or "").strip()
        ]
        text = str(prompt or "").strip()
        if not profiles or not text:
            return text
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        try:
            from .media_studio.provider_bridge import credential_manager, llm_row, vlm_row
            from .vision_runtime import complete_authoring

            rewritten, _meta = complete_authoring(
                llm_row(), vlm_row(), credential_manager().decrypt,
                MOTION_REF_POLISH_SYSTEM,
                "角色外观短语：\n" + "\n".join(profiles)
                + "\n\n用户的创作描述：\n" + text,
                None,
                max_tokens=1200,
                temperature=0.3,
                timeout=120.0,
            )
            rewritten = str(rewritten or "").strip()
            lowered = rewritten.lower()
            if (
                len(rewritten) < len(text) * 0.5
                or any(mark in lowered for mark in ("subject_definitions", "<picture", "<video", "character 1"))
                or sum(1 for ch in rewritten if "\u4e00" <= ch <= "\u9fff") < max(8, len(text) * 0.2)
            ):
                # 过短/夹带英文模板结构/几乎没中文都视为改写失败，退化用原文。
                return text
            return rewritten
        except ComfyCancelled:
            raise
        except Exception:
            return text

    def _run_motion_ref_video(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """多人参考视频版：references[0..N-1] 为角色形象图（<Picture n> 顺序），references[-1] 为动作参考视频。"""
        if not 2 <= len(references) <= 7:
            raise legacy.ComfyError("多人动作迁移需要 1-6 张角色形象图和 1 个动作参考视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在上传角色形象图")
        character_images: list[str] = []
        for index, path in enumerate(references[:-1]):
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            character_images.append(self.upload_image(path, f"motion_ref_character_{index + 1}"))
        normalized = normalize_options(JobMode.MINIMAX_H3_MOTION_REF_VIDEO, options or {})
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        # 自动 caption:用户不写角色长相也能稳定换人（失败静默退化，不阻断）。
        update_stage("正在生成角色外观描述")
        character_captions = self._describe_motion_ref_characters(references[:-1], is_cancelled)
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        # 润色改写：把外观短语织成描述段首句的中文外观主语（实测唯一生效的换人写法）。
        prompt = self._inject_appearance_into_prompt(prompt, character_captions, is_cancelled)
        update_stage("正在截取动作片段并保留原声")
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="motion-ref-video-", dir=self.settings.staging_dir) as directory:
            prepared, source_has_audio = prepare_motion_reference_video(
                Path(references[-1]), Path(directory) / "motion.mp4",
                fps=normalized["fps"], length=normalized["length"],
                width=normalized["width"], height=normalized["height"],
            )
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage("正在上传动作参考视频")
            motion_video = self.upload_video(str(prepared), "motion_ref_video_control")
        workflow = build_h3_motion_ref_video_workflow(
            character_images,
            motion_video,
            prompt,
            width=normalized["width"],
            height=normalized["height"],
            length=normalized["length"],
            steps=int(normalized.get("steps") or 20),
            seed=normalized["seed"],
            # 只有预处理实测到音轨才接 AV latent 链,否则 VAEEncodeAudio 会拿空音轨报错。
            preserve_audio=bool(normalized.get("preserve_audio", True)) and source_has_audio,
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            fps=int(normalized.get("fps") or 24),
            # 按位传入（个别失败留空串，不能过滤——否则描述与角色序号错位）。
            character_captions=character_captions if any(character_captions) else None,
            # 快速预览档 = DMAD turbo LoRA + 8 步 euler，对齐官方 Aiden 模板主采样。
            turbo=str(normalized.get("render_quality")) == "preview",
        )
        record = self.run_workflow(
            workflow, "H3 正在迁移多人动作", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, MOTION_REF_VIDEO_OUTPUT_NODE, ("videos", "gifs", "images")),
            "h3_motion_ref_video",
        )
        return [self.output_payload(output, "video", "H3 动作迁移视频")]

    def _run_inpaint(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """H3 局部重绘：references[0] 为重绘遮罩图(白色=重绘区)，references[1] 为原片视频。"""
        if not str(prompt or "").strip():
            raise legacy.ComfyError("请填写要把遮罩区域替换成什么内容。")
        if len(references) != 2:
            raise legacy.ComfyError("局部重绘需要上传重绘遮罩图和原片视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        normalized = normalize_options(JobMode.MINIMAX_H3_INPAINT, options or {})
        update_stage("正在上传重绘遮罩图")
        mask_image = self.upload_image(references[0], "inpaint_mask")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在截取原片并对齐帧率")
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="inpaint-source-", dir=self.settings.staging_dir) as directory:
            prepared = prepare_inpaint_source(
                Path(references[1]), Path(directory) / "source.mp4",
                fps=normalized["fps"], length=normalized["length"],
            )
            # 画布跟随原片宽高(32 对齐)，遮罩图与原片都会在图内自动对齐。
            # 探测与上传都必须在临时目录存活期内完成（prepared 随 with 块销毁）。
            probe = probe_video(prepared)
            width = max(32, min(2048, int(probe.width) // 32 * 32))
            height = max(32, min(2048, int(probe.height) // 32 * 32))
            normalized["width"], normalized["height"], normalized["length"] = width, height, normalized["length"]
            # registry 对 seed 字段始终随机化；这里读原始提交值，0 表示随机，
            # 并把实际使用的 seed 回写进生效参数快照以支持复现。
            requested_seed = int((options or {}).get("seed") or 0)
            seed = requested_seed if requested_seed > 0 else int(normalized.get("seed") or 0) or secrets.randbits(31)
            normalized["seed"] = seed
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage("正在上传原片")
            source_video = self.upload_video(str(prepared), "inpaint_source")
        workflow = build_h3_inpaint_workflow(
            mask_image,
            source_video,
            prompt,
            width=width,
            height=height,
            length=int(normalized.get("length") or 124),
            inpaint_strength=float(normalized.get("inpaint_strength") or 1.0),
            steps=int(normalized.get("steps") or 20),
            seed=seed,
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            fps=int(normalized.get("fps") or 24),
        )
        record = self.run_workflow(
            workflow, "H3 正在局部重绘", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, INPAINT_OUTPUT_NODE, ("videos", "gifs", "images")),
            "h3_inpaint",
        )
        return [self.output_payload(output, "video", "H3 局部重绘视频")]

    def _run_h3_depth(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """H3 深度捕捉：references[0] 为原片视频，深度锁定结构与运镜，提示词重塑画面。"""
        if len(references) != 1:
            raise legacy.ComfyError("深度捕捉需要上传 1 段原片视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        normalized = normalize_options(JobMode.MINIMAX_H3_DEPTH, options or {})
        duration = str(normalized.get("duration") or "5s")
        update_stage("正在校验原片")
        source = Path(references[0])
        validate_depth_source(source, duration)
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        update_stage("正在截取原片并对齐帧率")
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        # 探测画布与上传都必须在临时目录存活期内完成（prepared 随 with 块销毁）。
        with tempfile.TemporaryDirectory(prefix="depth-source-", dir=self.settings.staging_dir) as directory:
            prepared = prepare_depth_source(
                source, Path(directory) / "source.mp4",
                fps=int(normalized.get("fps") or 24), length=int(normalized.get("length") or 124),
            )
            # 画布跟随原片宽高(32 对齐)，深度图与成片都按该画布生成。
            probe = probe_video(prepared)
            width = max(32, min(2048, int(probe.width) // 32 * 32))
            height = max(32, min(2048, int(probe.height) // 32 * 32))
            normalized["width"], normalized["height"] = width, height
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage("正在上传原片")
            source_video = self.upload_video(str(prepared), "depth_capture_source")
        workflow = build_h3_depth_workflow(
            source_video,
            prompt.strip() or DEPTH_DEFAULT_PROMPT,
            width=width,
            height=height,
            length=int(normalized.get("length") or 124),
            control_strength=float(normalized.get("control_strength") or 1.0),
            steps=int(normalized.get("steps") or 20),
            seed=int(normalized.get("seed") or 0),
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            fps=int(normalized.get("fps") or 24),
            da3_resolution=int(normalized.get("da3_resolution") or 504),
        )
        record = self.run_workflow(
            workflow, "正在提取深度并重塑画面", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        return self._depth_capture_outputs(record)

    def _run_h3_video_edit(
        self, references: list[str], prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        if len(references) != 1 or not prompt.strip():
            raise legacy.ComfyError("视频编辑需要 1 段原片和修改要求。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        normalized = normalize_options(JobMode.MINIMAX_H3_VIDEO_EDIT, options or {})
        update_stage("正在准备视频编辑素材")
        source = Path(references[0])
        probe = validate_video_edit_source(source, normalized["duration"])
        width, height = video_edit_dimensions(probe.width, probe.height)
        self.settings.staging_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="h3-video-edit-", dir=self.settings.staging_dir) as directory:
            prepared = prepare_video_edit_source(source, Path(directory) / "source.mp4", width=width,
                                                 height=height, length=normalized["length"])
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            source_video = self.upload_video(str(prepared), "h3_video_edit_source")
        workflow = build_h3_video_edit_workflow(
            source_video, prompt, width=width, height=height, length=normalized["length"],
            steps=normalized["steps"], seed=normalized["seed"], preserve_audio=normalized["preserve_audio"],
            model_files={kind: normalized[f"model_{kind}"] for kind in ("unet", "clip", "video_vae", "audio_vae")},
        )
        record = self.run_workflow(workflow, "正在编辑原片画面", update_stage,
                                   on_submitted=on_submitted, is_cancelled=is_cancelled)
        return self.completed_outputs(JobMode.MINIMAX_H3_VIDEO_EDIT, record)

    def _run_keyframe_narrative(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """H3 关键帧叙事：references 为 2-4 张按叙事顺序排列的关键帧图片。"""
        if not str(prompt or "").strip():
            raise legacy.ComfyError("请填写关键帧之间的叙事描述。")
        if not 2 <= len(references) <= 4:
            raise legacy.ComfyError("关键帧叙事需要上传 2-4 张关键帧图片。")
        normalized = normalize_options(JobMode.MINIMAX_H3_KEYFRAME, options or {})
        keyframes: list[str] = []
        for index, path in enumerate(references, 1):
            if is_cancelled is not None and is_cancelled():
                raise ComfyCancelled("任务已停止")
            update_stage(f"正在上传关键帧 {index}/{len(references)}")
            keyframes.append(self.upload_image(path, f"h3_keyframe_{index}"))
        try:
            anchor_frames = resolve_keyframe_anchor_frames(
                normalized.get("anchor_seconds"), len(keyframes), int(normalized.get("length") or 124),
            )
        except ValueError as error:
            raise legacy.ComfyError(str(error)) from error
        workflow = build_h3_keyframe_workflow(
            keyframes,
            prompt,
            width=int(normalized.get("width") or 864),
            height=int(normalized.get("height") or 480),
            length=int(normalized.get("length") or 124),
            anchor_frames=anchor_frames,
            steps=int(normalized.get("steps") or 20),
            seed=int(normalized.get("seed") or 0),
            weight_dtype=str(normalized.get("weight_dtype") or "default"),
            fps=int(normalized.get("fps") or 24),
            use_sage_attention=bool(normalized.get("use_sage_attention", True)),
        )
        record = self.run_workflow(
            workflow, "H3 正在生成关键帧叙事", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, KEYFRAME_OUTPUT_NODE, ("videos", "gifs", "images")),
            "h3_keyframe",
        )
        return [self.output_payload(output, "video", "H3 关键帧叙事视频")]

    def _run_stem_split(
        self, references: list[str], prompt: str, negative_prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """人声/伴奏分离：references[0] 为待分离的音频或视频（LoadAudio 自动抽取视频音轨）。"""
        if len(references) != 1:
            raise legacy.ComfyError("人声/伴奏分离需要上传 1 段音频或视频。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        normalized = normalize_options(JobMode.STEM_SPLIT, options or {})
        update_stage("正在上传待分离素材")
        filename = self.upload_video(references[0], "stem_split_source")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        workflow = build_stem_split_workflow(
            filename, model_name=str(normalized.get("model_name") or STEM_SPLIT_MODEL),
        )
        record = self.run_workflow(
            workflow, "正在分离人声与伴奏", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        vocals = self.download(
            legacy.output_file(record, STEM_SPLIT_VOCALS_NODE, ("audio",)), "stem_split_vocals",
        )
        instruments = self.download(
            legacy.output_file(record, STEM_SPLIT_INSTRUMENTS_NODE, ("audio",)), "stem_split_instruments",
        )
        return [
            self.output_payload(vocals, "audio", "人声音轨"),
            self.output_payload(instruments, "audio", "伴奏音轨"),
        ]

    def _stem_split_outputs(self, record: dict) -> list[dict]:
        vocals = self.download(
            legacy.output_file(record, STEM_SPLIT_VOCALS_NODE, ("audio",)), "stem_split_vocals",
        )
        instruments = self.download(
            legacy.output_file(record, STEM_SPLIT_INSTRUMENTS_NODE, ("audio",)), "stem_split_instruments",
        )
        return [
            self.output_payload(vocals, "audio", "人声音轨"),
            self.output_payload(instruments, "audio", "伴奏音轨"),
        ]

    def _run_image_edit(
        self, mode: JobMode, references: list[str], prompt: str, options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> list[dict]:
        """ComfyUI 图片编辑工作流（去背景 / 图层分离）：references[0] 为原图。

        去背景画布编辑器可追加 references[1] 移除蒙版、references[2] 保留蒙版
        （PNG，白色生效）；图层分离仍只收 1 张原图。
        """
        if mode is JobMode.IMAGE_LAYER_SPLIT:
            if len(references) != 1:
                raise legacy.ComfyError("图层分离需要上传 1 张原图。")
        elif not 1 <= len(references) <= 3:
            raise legacy.ComfyError("图片去背景需要 1 张原图，以及可选的移除蒙版与保留蒙版。")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        normalized = normalize_options(mode, options or {})
        update_stage("正在上传原图")
        filename = self.upload_image(references[0], "image_edit_source")
        mask_remove = None
        mask_keep = None
        if len(references) > 1:
            update_stage("正在上传蒙版")
            mask_remove = self.upload_image(references[1], "image_edit_mask_remove")
        if len(references) > 2:
            mask_keep = self.upload_image(references[2], "image_edit_mask_keep")
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        split_box = None
        if mode is JobMode.IMAGE_LAYER_SPLIT and normalized.get("split_mode") == "box":
            split_box = _split_box_pixels(normalized.get("split_box"), references[0])
        workflow = build_image_edit_workflow(
            mode, filename, prompt, normalized,
            mask_remove_filename=mask_remove, mask_keep_filename=mask_keep,
            split_box=split_box,
        )
        record = self.run_workflow(
            workflow, "正在编辑图片", update_stage, on_submitted=on_submitted, is_cancelled=is_cancelled,
        )
        return self._image_edit_outputs(mode, record)

    def _image_edit_outputs(self, mode: JobMode, record: dict) -> list[dict]:
        if mode is JobMode.IMAGE_LAYER_SPLIT:
            foreground = self.download(
                legacy.output_file(record, LAYER_FOREGROUND_NODE, ("images",)), "image_layer_foreground",
            )
            background = self.download(
                legacy.output_file(record, LAYER_BACKGROUND_NODE, ("images",)), "image_layer_background",
            )
            return [
                self.output_payload(foreground, "image", "前景图层"),
                self.output_payload(background, "image", "背景图层"),
            ]
        output = self.download(
            legacy.output_file(record, SAM3_OUTPUT_NODE, ("images",)), "image_background_remove",
        )
        return [self.output_payload(output, "image", "去背景图片")]

    def _depth_capture_outputs(self, record: dict) -> list[dict]:
        """成片为主产物；深度预览视频为辅助产物，缺失时不阻塞成片交付。"""
        output = self.download(
            legacy.output_file(record, H3_DEPTH_OUTPUT_NODE, ("videos", "gifs", "images")),
            "h3_depth_capture",
        )
        outputs = [self.output_payload(output, "video", "H3 深度捕捉视频")]
        try:
            depth_output = self.download(
                legacy.output_file(record, H3_DEPTH_PREVIEW_NODE, ("videos", "gifs", "images")),
                "h3_depth_capture_depth",
            )
            outputs.append(self.output_payload(depth_output, "video", "深度预览"))
        except legacy.ComfyError:
            pass
        return outputs

    def local_path_for_output(self, output: dict) -> Path:
        extra = output.get("_local_path")
        if extra and Path(str(extra)).is_file():
            return Path(str(extra))
        key = str(output.get("path") or "").strip()
        resolved = self.resource_storage.resolve(key) if key else None
        if resolved is not None:
            return resolved
        for folder in (self.settings.staging_dir, getattr(self.settings, "results_dir", self.settings.staging_dir)):
            candidate = Path(folder) / Path(key).name
            if key and candidate.is_file():
                return candidate
        source_info = output.get("_comfy_source")
        if isinstance(source_info, dict):
            response = self.open_output_stream(source_info)
            try:
                content = response.content
            finally:
                response.close()
            dest = self.settings.staging_dir / f"vsr_{secrets.token_hex(8)}{Path(key).suffix or '.mp4'}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            return dest
        getter = getattr(self.resource_storage, "download_url", None)
        url = getter(key) if callable(getter) and key else None
        url = url or output.get("cloud_url")
        if url:
            dest = self.settings.staging_dir / f"vsr_{secrets.token_hex(8)}{Path(key).suffix or '.mp4'}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(str(url), timeout=120) as response:
                    dest.write_bytes(response.read())
            except (OSError, URLError, TimeoutError, ValueError) as error:
                dest.unlink(missing_ok=True)
                raise legacy.ComfyError(f"下载原片失败，无法超分: {error}") from error
            return dest
        raise legacy.ComfyError("找不到可用于超分的原片文件")

    def append_upscale_if_requested(
        self, mode: JobMode, outputs: list[dict], options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None],
        save_partial_outputs: Callable[[list[dict]], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[dict]:
        if not wants_upscale(options):
            return outputs
        save_partial_outputs(outputs)
        engine = normalize_upscale_engine((options or {}).get("upscale_engine"))
        if engine == UPSCALE_ENGINE_RTX:
            reason = self.reject_vsr_memory(mode, options)
            if reason:
                update_stage(f"原片已完成，已跳过 2x 超分：{reason}", 100)
                return outputs
        try:
            return outputs + [self.run_upscale_output(
                outputs, options, update_stage, on_submitted, is_cancelled,
                source_mode=mode, engine=engine,
            )]
        except ComfyCancelled:
            raise
        except Exception as error:
            update_stage(f"原片已完成，2x 超分失败：{error}", 100)
            return outputs

    def run_upscale_output(
        self, outputs: list[dict], options: dict | None,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None] | None,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        source_mode: JobMode | None = None,
        source_path: str | None = None,
        engine: str = UPSCALE_ENGINE_RTX,
    ) -> dict:
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        engine = normalize_upscale_engine(engine)
        seedvr2 = engine == UPSCALE_ENGINE_SEEDVR2
        check_mode = source_mode if source_mode is not None else (
            JobMode.SEEDVR2_UPSCALE if seedvr2 else JobMode.NVIDIA_RTX_VSR
        )
        if not seedvr2:
            reason = self.reject_vsr_memory(check_mode, options)
            if reason:
                raise legacy.ComfyError(reason)
        if getattr(self, "comfy_url", None):
            if seedvr2:
                self.require_seedvr2()
            else:
                self.require_rtx_vsr_node()
        if source_path:
            local = Path(source_path)
            if not local.is_file():
                raise legacy.ComfyError("找不到可用于超分的原片文件")
        else:
            original = original_video_output(outputs)
            if original is None:
                raise legacy.ComfyError("没有可超分的原片视频")
            local = self.local_path_for_output(original)
        update_stage("正在卸载生成模型", 96)
        self.free_resources(force=True)
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        if seedvr2:
            stage_text = "SeedVR2 正在高清增强"
            workflow = build_seedvr2_upscale_workflow(self.upload_video(str(local), "seedvr2_source"))
            phase, output_node, folder, label = SEEDVR2_PHASE, SEEDVR2_OUTPUT_NODE, "seedvr2_upscale", SEEDVR2_OUTPUT_LABEL
        else:
            stage_text = "正在 2x 超分"
            workflow = build_rtx_vsr_workflow(self.upload_video(str(local), "rtx_vsr_source"))
            phase, output_node, folder, label = RTX_VSR_PHASE, VSR_OUTPUT_NODE, "rtx_vsr", UPSCALE_OUTPUT_LABEL
        update_stage(stage_text, 97)
        record = self.run_workflow(
            workflow, stage_text, update_stage,
            on_submitted=on_submitted, phase=phase, is_cancelled=is_cancelled,
        )
        output = self.download(
            legacy.output_file(record, output_node, ("videos", "gifs", "images")), folder,
        )
        return self.output_payload(output, "video", label)

    def completed_outputs(self, mode: JobMode, record: dict) -> list[dict]:
        if mode is JobMode.KEEP_FACE_RESTORE:
            output = self.download(legacy.output_file(record, KEEP_OUTPUT_NODE, ("videos", "gifs", "images")), "keep_face_restore")
            return [self.output_payload(output, "video", KEEP_OUTPUT_LABEL)]
        if mode in H3_WORKFLOWS:
            output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3")
            return [self.output_payload(output, "video", generation_output_label(mode))]
        if is_rtx_vsr_workflow(mode):
            output = self.download(legacy.output_file(record, VSR_OUTPUT_NODE, ("videos", "gifs", "images")), "rtx_vsr")
            return [self.output_payload(output, "video", UPSCALE_OUTPUT_LABEL)]
        if is_seedvr2_upscale_workflow(mode):
            output = self.download(
                legacy.output_file(record, SEEDVR2_OUTPUT_NODE, ("videos", "gifs", "images")), "seedvr2_upscale",
            )
            return [self.output_payload(output, "video", SEEDVR2_OUTPUT_LABEL)]
        if mode is JobMode.IMAGE:
            output = self.download(legacy.output_file(record, legacy.T2I_OUTPUT_NODE, ("images",)), "text_to_image")
            return [self.output_payload(output, "image", "生成图片")]
        if mode is JobMode.VACE_VIDEO:
            output = self.download(legacy.output_file(record, legacy.VACE_OUTPUT_NODE, ("videos", "gifs", "images")), "wan_vace_multi_reference")
            return [self.output_payload(output, "video", "VACE 视频")]
        if mode is JobMode.WAN_VACE_DEPTH_V2V:
            output = self.download(legacy.output_file(record, VACE_OUTPUT_NODE, ("videos", "gifs", "images")), "wan_vace_depth")
            return [self.output_payload(output, "video", "VACE 复刻视频")]
        if mode is JobMode.SCAIL2_REPLACEMENT:
            output = self.download(legacy.output_file(record, SCAIL_OUTPUT_NODE, ("videos", "gifs", "images")), "scail2_replacement")
            return [self.output_payload(output, "video", "SCAIL-2 动作迁移视频")]
        if mode is JobMode.MINIMAX_H3_FACE_SWAP:
            output = self.download(legacy.output_file(record, FACE_OUTPUT_NODE, ("videos", "gifs", "images")), "face_swap")
            return [self.output_payload(output, "video", "角色替换视频")]
        if mode is JobMode.MINIMAX_H3_MOTION_TRANSFER:
            output = self.download(
                legacy.output_file(record, MOTION_TRANSFER_OUTPUT_NODE, ("videos", "gifs", "images")),
                "h3_motion_transfer",
            )
            return [self.output_payload(output, "video", "H3 动作迁移视频")]
        if mode is JobMode.MINIMAX_H3_MOTION_REF_VIDEO:
            output = self.download(
                legacy.output_file(record, MOTION_REF_VIDEO_OUTPUT_NODE, ("videos", "gifs", "images")),
                "h3_motion_ref_video",
            )
            return [self.output_payload(output, "video", "H3 动作迁移视频")]
        if mode is JobMode.MINIMAX_H3_INPAINT:
            output = self.download(
                legacy.output_file(record, INPAINT_OUTPUT_NODE, ("videos", "gifs", "images")),
                "h3_inpaint",
            )
            return [self.output_payload(output, "video", "H3 局部重绘视频")]
        if mode is JobMode.MINIMAX_H3_KEYFRAME:
            output = self.download(
                legacy.output_file(record, KEYFRAME_OUTPUT_NODE, ("videos", "gifs", "images")),
                "h3_keyframe",
            )
            return [self.output_payload(output, "video", "H3 关键帧叙事视频")]
        if mode is JobMode.MINIMAX_H3_DEPTH:
            return self._depth_capture_outputs(record)
        if mode is JobMode.MINIMAX_H3_VIDEO_EDIT:
            output = self.download(legacy.output_file(record, VIDEO_EDIT_OUTPUT_NODE, ("videos", "gifs", "images")), "h3_video_edit")
            return [self.output_payload(output, "video", "H3 视频编辑试片")]
        if mode is JobMode.STEM_SPLIT:
            return self._stem_split_outputs(record)
        if is_comfy_image_workflow(mode):
            return self._image_edit_outputs(mode, record)
        raise legacy.ComfyError(f"不支持恢复工作流模式: {mode}")

    def run_refine_continuation(
        self, refine_state: dict, *,
        update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None],
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[dict]:
        self.last_execution_elapsed_ms = None
        self.last_refine_state = None
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        workflow = refine_state.get("workflow")
        if not isinstance(workflow, dict) or not workflow:
            raise legacy.ComfyError("二采续跑缺少已保存的工作流，请重新生成。")
        preview_outputs = [item for item in (refine_state.get("preview_outputs") or []) if isinstance(item, dict)]
        update_stage("正在提交二采精修", 0)
        record = self.run_workflow(
            workflow, "二采精修正在生成", update_stage, on_submitted=on_submitted,
            phase="refine-final", is_cancelled=is_cancelled,
        )
        output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3_refine")
        return [self.output_payload(output, "video", "二采精修成片"), *preview_outputs]

    def resume(
        self, mode: JobMode, prompt: str, prompt_id: str, client_id: str | None, phase: str,
        existing_outputs: list[dict], update_stage: Callable[[str, int | None], None],
        on_submitted: Callable[[str, str, str], None], save_partial_outputs: Callable[[list[dict]], None],
        is_cancelled: Callable[[], bool] | None = None,
        options: dict | None = None,
        refine_state: dict | None = None,
    ) -> list[dict]:
        self.last_execution_elapsed_ms = None
        self.last_refine_state = None
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        if phase == "refine-preview":
            record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "正在恢复一采预览", is_cancelled=is_cancelled,
            )
            output = self.download(
                legacy.output_file(record, PREVIEW_OUTPUT_NODE, ("videos", "gifs", "images")),
                "minimax_h3_preview",
            )
            outputs = [self.output_payload(output, "video", "一采预览")]
            if refine_state:
                self.last_refine_state = {**refine_state, "status": "awaiting", "preview_outputs": outputs}
            return outputs
        if phase == "refine-final":
            record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "正在恢复二采精修", is_cancelled=is_cancelled,
            )
            output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3_refine")
            return [self.output_payload(output, "video", "二采精修成片"), *existing_outputs]
        if phase in (RTX_VSR_PHASE, SEEDVR2_PHASE):
            seedvr2 = phase == SEEDVR2_PHASE
            try:
                record = self.wait_for_existing(
                    prompt_id, client_id, update_stage,
                    "正在恢复高清增强" if seedvr2 else "正在恢复 2x 超分", (96, 100), is_cancelled,
                )
                if seedvr2:
                    output = self.download(
                        legacy.output_file(record, SEEDVR2_OUTPUT_NODE, ("videos", "gifs", "images")),
                        "seedvr2_upscale",
                    )
                    payload = self.output_payload(output, "video", SEEDVR2_OUTPUT_LABEL)
                else:
                    output = self.download(
                        legacy.output_file(record, VSR_OUTPUT_NODE, ("videos", "gifs", "images")), "rtx_vsr",
                    )
                    payload = self.output_payload(output, "video", UPSCALE_OUTPUT_LABEL)
            except ComfyCancelled:
                raise
            except Exception as error:
                if existing_outputs:
                    update_stage(f"原片已完成，2x 超分失败：{error}", 100)
                    return existing_outputs
                raise
            if is_rtx_vsr_workflow(mode) or is_seedvr2_upscale_workflow(mode):
                return [payload]
            return existing_outputs + [payload]
        if phase == "generation":
            record = self.wait_for_existing(
                prompt_id, client_id, update_stage, "已重新连接 ComfyUI 任务", is_cancelled=is_cancelled,
            )
            outputs = self.completed_outputs(mode, record)
            return self.append_upscale_if_requested(
                mode, outputs, options, update_stage, on_submitted, save_partial_outputs, is_cancelled,
            )

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
        self.last_refine_state = None
        if is_cancelled is not None and is_cancelled():
            raise ComfyCancelled("任务已停止")
        if mode is JobMode.KEEP_FACE_RESTORE:
            return self._run_keep_face_restore(references, options, update_stage, on_submitted, is_cancelled)
        if is_rtx_vsr_workflow(mode) or is_seedvr2_upscale_workflow(mode):
            if not references:
                raise legacy.ComfyError("超分需要原片视频。")
            return [self.run_upscale_output(
                [], options, update_stage, on_submitted, is_cancelled,
                source_mode=mode, source_path=references[0],
                engine=UPSCALE_ENGINE_SEEDVR2 if is_seedvr2_upscale_workflow(mode) else UPSCALE_ENGINE_RTX,
            )]
        if is_comfy_image_workflow(mode):
            return self._run_image_edit(
                mode, references, prompt, options, update_stage, on_submitted, is_cancelled,
            )
        if mode in H3_WORKFLOWS:
            if mode is JobMode.MINIMAX_H3_AVATAR or mode is JobMode.MINIMAX_H3_LIP_SYNC:
                # 数字人/口型同步的 references 是 [视频或形象图, 音频]，不走 <Picture n> 标签注入。
                resolved_prompt = prompt
            else:
                resolved_prompt = resolve_minimax_picture_prompt(prompt, len(references))
            update_stage("正在上传参考素材" if references else "正在提交文生视频任务")
            uploaded = []
            for index, path in enumerate(references, 1):
                if is_cancelled is not None and is_cancelled():
                    raise ComfyCancelled("任务已停止")
                uploaded.append(self.upload_image(path, f"h3_reference_{index}"))
            seed = secrets.randbits(63)
            refine_preview = False
            if coerce_bool_option(options.get("refine_enabled", False), label="二采精修"):
                refine_preview = coerce_bool_option(options.get("refine_preview", False), label="先预览一采")
                workflow = build_minimax_h3_refine_workflow(
                    mode, resolved_prompt, uploaded, options, seed, preview=refine_preview,
                )
            elif mode in T8_WORKFLOWS:
                workflow = build_minimax_h3_t8_workflow(mode, resolved_prompt, uploaded, options)
            elif mode is JobMode.MINIMAX_H3_AVATAR:
                workflow = build_minimax_h3_avatar_workflow(resolved_prompt, uploaded, options)
            elif mode is JobMode.MINIMAX_H3_LIP_SYNC:
                workflow = build_minimax_h3_lipsync_workflow(resolved_prompt, uploaded, options)
            elif mode in LIGHTX2V_WORKFLOWS:
                workflow = build_minimax_h3_lightx2v_workflow(mode, resolved_prompt, uploaded, options, seed)
            elif mode in DUAL_ACCEL_WORKFLOWS:
                workflow = build_minimax_h3_dual_accel_workflow(mode, resolved_prompt, uploaded, options, seed)
            elif mode in DIRECTOR_ACCEL_WORKFLOWS:
                workflow = build_minimax_h3_director_accel_workflow(mode, resolved_prompt, uploaded, options, seed)
            elif mode in ACTION_WORKFLOWS:
                workflow = build_minimax_h3_action_workflow(mode, resolved_prompt, uploaded, options, seed)
            else:
                workflow = build_minimax_h3_workflow(mode, resolved_prompt, uploaded, options, seed)
            if refine_preview:
                # Persist before submission so a restart mid-first-pass can still
                # resume with the exact graph and hit the ComfyUI refine cache.
                self.last_refine_state = {
                    "status": "awaiting",
                    "workflow": continuation_workflow(workflow),
                    "seed": seed,
                    "preview_outputs": [],
                    "refine_quality": str(options.get("refine_quality") or "1.0"),
                    "refine_quality_mode": str(options.get("refine_quality_mode") or "auto"),
                }
            record = self.run_workflow(
                workflow, generation_stage(mode), update_stage, on_submitted=on_submitted,
                phase="refine-preview" if refine_preview else "generation",
                is_cancelled=is_cancelled,
            )
            if refine_preview:
                output = self.download(
                    legacy.output_file(record, PREVIEW_OUTPUT_NODE, ("videos", "gifs", "images")),
                    "minimax_h3_preview",
                )
                outputs = [self.output_payload(output, "video", "一采预览")]
                self.last_refine_state = {
                    **self.last_refine_state,
                    "preview_outputs": outputs,
                }
                return outputs
            output = self.download(legacy.output_file(record, "14", ("videos", "gifs", "images")), "minimax_h3")
            outputs = [self.output_payload(output, "video", generation_output_label(mode))]
            return self.append_upscale_if_requested(
                mode, outputs, options, update_stage, on_submitted, save_partial_outputs, is_cancelled,
            )

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

        if mode is JobMode.WAN_VACE_DEPTH_V2V:
            return self._run_vace_depth_replication(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

        if mode is JobMode.SCAIL2_REPLACEMENT:
            return self._run_scail2_replacement(references, prompt, options, update_stage, on_submitted, is_cancelled)

        if mode is JobMode.MINIMAX_H3_FACE_SWAP:
            return self._run_face_swap(references, prompt, options, update_stage, on_submitted, is_cancelled)

        if mode is JobMode.MINIMAX_H3_MOTION_TRANSFER:
            return self._run_motion_transfer(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

        if mode is JobMode.MINIMAX_H3_MOTION_REF_VIDEO:
            return self._run_motion_ref_video(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

        if mode is JobMode.MINIMAX_H3_INPAINT:
            return self._run_inpaint(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

        if mode is JobMode.MINIMAX_H3_DEPTH:
            return self._run_h3_depth(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )
        if mode is JobMode.MINIMAX_H3_VIDEO_EDIT:
            return self._run_h3_video_edit(references, prompt, options, update_stage, on_submitted, is_cancelled)

        if mode is JobMode.MINIMAX_H3_KEYFRAME:
            return self._run_keyframe_narrative(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

        if mode is JobMode.STEM_SPLIT:
            return self._run_stem_split(
                references, prompt, negative_prompt, options, update_stage, on_submitted, is_cancelled,
            )

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
