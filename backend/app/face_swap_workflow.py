"""MiniMax H3 角色替换（换头 / 修脸 / 表情迁移）——"模板 + 补丁"式建图。

与 scail2_workflow 的程序化从零建图不同，这里以远端已验证出片的干净模板
``face_swap_template.json``（190 节点 API 图，chovy 实测 MINIMAX_00009 质量达标）为基线，
只覆盖三类输入旋钮，并内嵌一段"远端 yolov8 参考图裁脸"子图：

- ``1068`` VHS_LoadVideo.video            -> 上传后的原片视频（含 frame_load_cap 控制时长）
- ``9000`` LoadImage / ``9001`` H3FaceTrackCrop -> 上传后的角色形象图，在远端用 face_yolov8m
  检测最大人脸并裁成方脸特写，作为身份参考
- ``138``  PrimitiveStringMultiline       -> 换脸提示词

模板冻结自一段较长的 chovy 测试片，除换头成品输出 ``161`` 外还挂着一条“整段重生成”旁路输出
（``412`` 及其上游按源片长度派生的分段循环 / 帧区间切片 / 音频偏移裁剪节点）。这些旁路节点对短
上传普遍越界（``GetImageRangeFromBatch`` “Start index is out of range”、``TrimAudioDuration``
“start ... within the audio length”），却与被换头的画面交付毫无关系。建图最后把图裁剪到只保留
``161`` 的祖先闭包，旁路分支（含 ``412``）整体不出现在提交图里，远端自然不会执行它们。

注意：``161`` 分支的真实语义是“整段重生成（``752`` ResolutionSelector 画幅）→ 逐段裁脸重绘 →
face_only 贴回重生成的底”。模板把 ``752`` 冻结为博主竖屏素材的 ``9:16``，横屏原片会被先重画成
竖屏再贴脸导致画面错位；因此建图时必须按原片宽高比覆盖 ``752.aspect_ratio``（``aspect_ratio`` 参数）。

六个 MiniMaxH3ReferenceToVideo 的身份参考槽（模板里原本挂在 ``371`` / ``265`` 两张半身参考图）
统一重指向裁脸输出，避免"头肩半身 + 背景"被整块塞进脸部框导致的矩形鬼影。

离网站点约束：H3FaceTrackCrop 的 ``identity_track`` 必须保持 False（insightface buffalo_l 在离网
GPU 上联网下载会不可中断死锁）；单人场景由 yolov8m 检测框即可完成人脸定位。

贴回质量约束：源侧人脸跟踪必须带人体兜底检测器（``segm\\person_yolov8m-seg.pt``）。yolov8m 在
转头/手遮挡帧丢失人脸时，H3FaceStitch 的 face_only 因 transform 缺 face_rect 退化为中央 50% 方块，
把整块生成 crop（含头发与生成背景）贴回原片，形成矩形鬼影；兜底器用人形框顶部给出真实头部位置，
保证 face_rect 逐帧存在。参考图裁剪（9001）为单帧图像、不存在插值问题，保持 ``none`` 检不到即报错。
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

TEMPLATE_PATH = Path(__file__).with_name("face_swap_template.json")

# ---- integration input knobs (the only nodes the backend ever patches) ----
SOURCE_VIDEO_NODE = "1068"
PROMPT_NODE = "138"
RESOLUTION_NODE = "752"        # ResolutionSelector：整段重生成底图的画幅（模板冻结为 9:16 竖屏）
FACE_OUTPUT_NODE = "161"          # H3FaceStitch branch -> the deliverable video (the kept output)
# reference images the template originally wired into every MiniMaxH3ReferenceToVideo slot
LEGACY_REFERENCE_NODES = ("371", "265")
# embedded remote face-crop subgraph (added by the builder, not present in the template)
CROP_LOAD_NODE = "9000"
CROP_DETECT_NODE = "9001"

FACE_DETECTOR = "bbox\\face_yolov8m.pt"
# 源侧丢脸帧的头部兜底（远端 models/ultralytics/segm 下已安装，object_info 动态可见）
FACE_FALLBACK_DETECTOR = "segm\\person_yolov8m-seg.pt"
FACE_CROP_CANVAS = 640
FACE_CROP_CONFIDENCE = 0.35
# 1.8 实测仍会把发际与背景带进身份参考（chovy 实测矩形鬼影），收紧到贴近纯脸特写
FACE_CROP_FACTOR = 1.4

FACE_SWAP_DEFAULT_PROMPT = (
    "Replace ONLY the face of the central person with the exact face of the character in "
    "<Picture 1> (人物的面部特征参考 <Picture 1>). Preserve the target identity, skin tone and "
    "hairstyle in every frame. CRITICAL: keep the original video's background, setting, lighting, "
    "camera framing, body position, hands and clothing EXACTLY as in the source — do NOT introduce "
    "any new background, sky or city. The new face must synchronize with the original video's body "
    "movements, gestures, facial expressions, eye gaze and lip sync."
)

# ResolutionSelector 的画幅预设（KJNodes 标准串，前缀 W:H 会被解析）
FACE_ASPECT_LANDSCAPE = "16:9 (Widescreen)"
FACE_ASPECT_PORTRAIT = "9:16 (Portrait Widescreen)"
FACE_ASPECT_SQUARE = "1:1 (Square)"


def face_aspect_ratio(width: int, height: int) -> str:
    """Bucket the source video frame into one of the three canvas presets."""
    if width <= 0 or height <= 0:
        return FACE_ASPECT_LANDSCAPE
    ratio = width / height
    if ratio >= 1.15:
        return FACE_ASPECT_LANDSCAPE
    if ratio <= 0.87:
        return FACE_ASPECT_PORTRAIT
    return FACE_ASPECT_SQUARE


# class_types the graph relies on that are not part of stock ComfyUI
FACE_SWAP_CUSTOM_NODES = (
    "H3FaceTrackCrop",
    "H3FaceStitch",
    "MiniMaxH3ReferenceToVideo",
    "VHS_LoadVideo",
    "VHS_VideoCombine",
)


@lru_cache(maxsize=1)
def _template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _ancestor_closure(graph: dict, root: str) -> set:
    """Node ids reachable from ``root`` by walking input links (``root`` included).

    Anything outside this set is not needed to render the deliverable, so the builder
    drops it before submitting — ComfyUI then cannot execute the long-clip bypass branch.
    """
    keep = set()
    stack = [root]
    while stack:
        node_id = stack.pop()
        if node_id in keep or node_id not in graph:
            continue
        keep.add(node_id)
        for value in (graph[node_id].get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                stack.append(value[0])
    return keep


def build_face_swap_workflow(
    reference_image: str, source_video: str, prompt: str, *,
    crop_factor: float = FACE_CROP_FACTOR, frame_load_cap: int = 240,
    confidence: float = FACE_CROP_CONFIDENCE, aspect_ratio: str | None = None,
) -> dict:
    """Return an executable ComfyUI API graph for single-person face replacement.

    ``reference_image`` and ``source_video`` are filenames already uploaded into the remote
    ComfyUI ``input`` directory. The reference is auto-cropped to a face close-up on the remote
    via the embedded yolov8 detection subgraph.
    """
    graph = copy.deepcopy(_template())

    # 1) source video: point the loader at the uploaded clip and cap the processed length.
    graph[SOURCE_VIDEO_NODE]["inputs"]["video"] = source_video
    graph[SOURCE_VIDEO_NODE]["inputs"]["frame_load_cap"] = int(frame_load_cap)

    # 2) swap prompt (fall back to the validated face-focused default when empty).
    graph[PROMPT_NODE]["inputs"]["value"] = (prompt or "").strip() or FACE_SWAP_DEFAULT_PROMPT

    # 2b) the deliverable pastes faces onto the *regenerated* base, whose canvas the template
    #     froze to 9:16 (the blogger's portrait clip). Override it with the source orientation so
    #     landscape/square uploads are not re-drawn as portrait video.
    if aspect_ratio:
        graph[RESOLUTION_NODE]["inputs"]["aspect_ratio"] = aspect_ratio

    # 3) embed the remote face-crop subgraph: LoadImage(ref) -> H3FaceTrackCrop -> crops.
    graph[CROP_LOAD_NODE] = {"class_type": "LoadImage", "inputs": {"image": reference_image}}
    graph[CROP_DETECT_NODE] = {"class_type": "H3FaceTrackCrop", "inputs": {
        "images": [CROP_LOAD_NODE, 0],
        "detector": FACE_DETECTOR,
        "confidence": float(confidence),
        "crop_factor": float(crop_factor),
        "canvas_width": FACE_CROP_CANVAS,
        "canvas_height": FACE_CROP_CANVAS,
        "canvas_mode": "manual",
        "smooth_window": 1,
        "size_smooth_window": 1,
        "smooth_method": "gaussian",
        "size_mode": "per_frame",
        "identity_track": False,          # offline GPU: insightface would deadlock
        "select": "largest_face",
        "fallback_detector": "none",
        "cut_detection": "none",
    }}

    # 4) rewire every legacy half-body reference slot to the cropped face close-up.
    for node in graph.values():
        for field, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and value[0] in LEGACY_REFERENCE_NODES:
                node["inputs"][field] = [CROP_DETECT_NODE, 0]

    # 4b) source-side face trackers get the person-shaped fallback detector so frames where
    #     yolov8m loses the face (head turn, hand occlusion) still yield a real head rect instead
    #     of a missing face_rect — without it H3FaceStitch's face_only degrades to a centre 50%
    #     block and pastes the whole regenerated crop (hair + generated background) back.
    for node_id, node in graph.items():
        if node_id == CROP_DETECT_NODE or node.get("class_type") != "H3FaceTrackCrop":
            continue
        node["inputs"]["fallback_detector"] = FACE_FALLBACK_DETECTOR
        node["inputs"].setdefault("fallback_head_frac", 0.5)

    # 5) keep only the deliverable branch. The template carries a long-clip "whole re-generation"
    #    bypass output (node 412) whose upstream segmentation / frame-range / audio-offset nodes
    #    overflow any short upload; they sit outside node 161's closure, so dropping everything the
    #    deliverable does not depend on guarantees the remote never runs them.
    keep = _ancestor_closure(graph, FACE_OUTPUT_NODE)
    return {node_id: node for node_id, node in graph.items() if node_id in keep}


def face_swap_missing_message(info: dict, graph: dict) -> str | None:
    """Return a human-readable blocker if the connected ComfyUI cannot run this graph."""
    missing = sorted({node["class_type"] for node in graph.values()} - set(info))
    if missing:
        return "当前 ComfyUI 缺少角色替换所需节点：" + "、".join(missing)
    detector_choices = (info.get("H3FaceTrackCrop", {}).get("input", {})
                        .get("required", {}).get("detector", [[]])[0])
    if isinstance(detector_choices, list) and FACE_DETECTOR not in detector_choices:
        return f"当前 ComfyUI 未发现人脸检测模型：{FACE_DETECTOR}"
    fallback_choices = (info.get("H3FaceTrackCrop", {}).get("input", {})
                        .get("optional", {}).get("fallback_detector", [[]])[0])
    # 仅在远端确实提供了兜底器清单但缺少该模型时拦截；旧版节点无此参数（回退会被忽略）不拦。
    if isinstance(fallback_choices, list) and fallback_choices and FACE_FALLBACK_DETECTOR not in fallback_choices:
        return (f"当前 ComfyUI 未安装头部兜底检测模型：{FACE_FALLBACK_DETECTOR}"
                "（请放入远端 models/ultralytics/segm 目录）")
    return None
