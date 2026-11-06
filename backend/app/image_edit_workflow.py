"""ComfyUI 图片编辑工作流构建器（图片去背景 / 图层分离）。

图片类工作流此前只能经 GRS 执行器生成；本模块提供直接跑在当前连接 ComfyUI
实例上的图片编辑 graph。分割引擎使用远端已安装的 SAM3.1
（sam3.1_multiplex_fp16 + SAM3_Detect + CLIPTextEncode 文本概念提示），
alpha 输出用 SaveImageWithAlpha——不引入新模型、不部署第二套 ComfyUI。

文本提示 vs 点提示：SCAIL-2 的动作迁移走 positive_coords 点提示；
本工作流用 conditioning 文本概念（如 the main subject / the product），
无需用户点选即可自动分割。主体描述由任务的 prompt 字段提供。

图层分离三种拆分方式（对照即梦）：智能拆分沿用文本概念自动分割；
按描述拆分把用户描述作为 conditioning 文本；框选拆分把用户框选矩形的
中心换算为 positive_coords 正点提示（远端实测：SAM3 的 bboxes 框路径
在框完全落入均匀物体内部时返回空掩码、框带边距时返回稀疏噪声，而
点提示在两种情况下都稳定分割点下主体，与动作迁移的生产链路一致）。
三种方式输出节点一致，交付链路不变。

输出节点 ID 固定，供 comfy_service 的交付与恢复链路（completed_outputs）使用：
- 去背景：节点 ``9``（原图 RGB + SAM3 mask 作为 alpha 的透明 PNG）
- 图层分离：节点 ``9``（前景层）/ ``10``（背景层，主体挖空的透明 PNG）

去背景画布编辑器（对照即梦交互）支持用户用画笔/橡皮修正分割结果：
references[1] 为移除蒙版（白色=强制透明），references[2] 为保留蒙版（白色=强制不透明）。
蒙版在 graph 内用 MaskComposite 合成：alpha = Invert(SAM3 mask) ∪ 移除蒙版 − 保留蒙版，
对应节点 ``12``-``16``（``or`` 合并移除区，``multiply`` 减去保留区），不改动既有节点 ID。
"""

from __future__ import annotations

import json
import math

from .models import JobMode

SAM3_OUTPUT_NODE = "9"
LAYER_FOREGROUND_NODE = "9"
LAYER_BACKGROUND_NODE = "10"
# 去背景画布蒙版链（12=移除蒙版载入，13/14=保留蒙版载入并取反，15=并入移除区，16=减去保留区）。
MASK_REMOVE_LOAD_NODE = "12"
MASK_KEEP_LOAD_NODE = "13"
MASK_KEEP_INVERT_NODE = "14"
MASK_REMOVE_COMBINE_NODE = "15"
MASK_KEEP_COMBINE_NODE = "16"

IMAGE_EDIT_OUTPUT_PREFIX = "zly_image_edit"

DEFAULT_SAM3_MODEL = "sam3.1_multiplex_fp16.safetensors"
DEFAULT_SUBJECT_PROMPT = "the main subject"
DEFAULT_SAM3_THRESHOLD = 0.5
DEFAULT_SAM3_REFINE_ITERATIONS = 2


def _validate_threshold(threshold: float) -> float:
    value = float(threshold)
    if not 0.05 <= value <= 0.95:
        raise ValueError(f"分割阈值超出范围: {threshold}")
    return value


def _validate_refine_iterations(iterations: int) -> int:
    value = int(iterations)
    if not 0 <= value <= 5:
        raise ValueError(f"分割精修次数超出范围: {iterations}")
    return value


def normalize_split_box(box: dict) -> dict:
    """框选拆分的像素矩形：{x, y, width, height}，坐标必须落在图片内部（宽高 > 0）。"""
    if not isinstance(box, dict) or set(box) - {"x", "y", "width", "height"}:
        raise ValueError("框选区域格式不正确。")
    try:
        x, y = float(box["x"]), float(box["y"])
        width, height = float(box["width"]), float(box["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("框选区域格式不正确。") from error
    if min(x, y, width, height) < 0 or width <= 0 or height <= 0:
        raise ValueError("框选区域必须是有效的矩形。")
    return {"x": round(x), "y": round(y), "width": round(width), "height": round(height)}


def normalize_split_box_text(value: object) -> str:
    """框选拆分的千分比坐标串 "x0,y0,x1,y1"：校验范围并保留三位小数。

    坐标相对原图左上角（前端按显示尺寸换算），x1 > x0、y1 > y0，跨度至少 1‰。
    """
    parts = str(value or "").split(",")
    if len(parts) != 4:
        raise ValueError("框选拆分需要先在原图上框选区域。")
    try:
        x0, y0, x1, y1 = (float(part) for part in parts)
    except ValueError as error:
        raise ValueError("框选区域格式不正确。") from error
    if not all(math.isfinite(v) and 0 <= v <= 1000 for v in (x0, y0, x1, y1)):
        raise ValueError("框选区域超出原图范围。")
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise ValueError("框选区域太小，请框住要拆出的主体。")
    return ",".join(f"{v:.3f}" for v in (x0, y0, x1, y1))


def _sam3_detect_subgraph(
    image_ref: list, subject_prompt: str, model_name: str, threshold: float, refine_iterations: int,
) -> dict:
    """LoadImage + SAM3 检测子图；节点 1/2/3/4，返回可并入 graph 的片段。"""
    _validate_threshold(threshold)
    _validate_refine_iterations(refine_iterations)
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_ref}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model_name}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": subject_prompt}},
        "4": {
            "class_type": "SAM3_Detect",
            "inputs": {
                "model": ["2", 0],
                "image": ["1", 0],
                "threshold": threshold,
                "refine_iterations": refine_iterations,
                "individual_masks": False,
                "conditioning": ["3", 0],
            },
        },
    }


def _image_edit_options(options: dict) -> tuple[str, float, int]:
    model_name = str(options.get("model_name") or DEFAULT_SAM3_MODEL)
    threshold = float(options.get("threshold") or DEFAULT_SAM3_THRESHOLD)
    refine = int(options.get("refine_iterations") if options.get("refine_iterations") is not None
                 else DEFAULT_SAM3_REFINE_ITERATIONS)
    return model_name, threshold, refine


def build_image_background_remove_workflow(
    filename: str, *, subject_prompt: str = DEFAULT_SUBJECT_PROMPT, options: dict | None = None,
    mask_remove_filename: str | None = None, mask_keep_filename: str | None = None,
) -> dict:
    """图片去背景：文本概念提示分割主体，原图 RGB 配 SAM3 mask 作为 alpha。

    远端实测：SaveImageWithAlpha 把 mask 白色当作透明（与节点描述相反），
    主体 alpha 需先经 InvertMask 反相。
    传入用户蒙版时（画布编辑器的画笔/橡皮修正），alpha 在 graph 内继续合成：
    先用 ``or`` 把移除蒙版（白色=强制透明）并入 alpha，再用 ``multiply`` 减去
    反相后的保留蒙版（白色=强制不透明），两种输入都是 0-1 值不会越界。
    """
    model_name, threshold, refine = _image_edit_options(options or {})
    graph = _sam3_detect_subgraph(filename, subject_prompt, model_name, threshold, refine)
    graph["8"] = {"class_type": "InvertMask", "inputs": {"mask": ["4", 0]}}
    transparency: list = ["8", 0]
    if mask_remove_filename:
        graph[MASK_REMOVE_LOAD_NODE] = {
            "class_type": "LoadImageMask",
            "inputs": {"image": mask_remove_filename, "channel": "red"},
        }
        graph[MASK_REMOVE_COMBINE_NODE] = {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": transparency,
                "source": [MASK_REMOVE_LOAD_NODE, 0],
                "x": 0,
                "y": 0,
                "operation": "or",
            },
        }
        transparency = [MASK_REMOVE_COMBINE_NODE, 0]
    if mask_keep_filename:
        graph[MASK_KEEP_LOAD_NODE] = {
            "class_type": "LoadImageMask",
            "inputs": {"image": mask_keep_filename, "channel": "red"},
        }
        graph[MASK_KEEP_INVERT_NODE] = {"class_type": "InvertMask", "inputs": {"mask": [MASK_KEEP_LOAD_NODE, 0]}}
        graph[MASK_KEEP_COMBINE_NODE] = {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": transparency,
                "source": [MASK_KEEP_INVERT_NODE, 0],
                "x": 0,
                "y": 0,
                "operation": "multiply",
            },
        }
        transparency = [MASK_KEEP_COMBINE_NODE, 0]
    graph[SAM3_OUTPUT_NODE] = {
        "class_type": "SaveImageWithAlpha",
        "inputs": {
            "images": ["1", 0],
            "mask": transparency,
            "filename_prefix": f"{IMAGE_EDIT_OUTPUT_PREFIX}/background_remove",
        },
    }
    return graph


def build_image_layer_split_workflow(
    filename: str, *, subject_prompt: str = DEFAULT_SUBJECT_PROMPT, options: dict | None = None,
    split_box: dict | None = None,
) -> dict:
    """图层分离：同一 SAM3 mask 派生前景层与背景层（主体挖空），画布叠放可还原原图。

    三种拆分方式（对照即梦）：默认按文本概念自动分割；提供 split_box 时走
    框选拆分——把框中心换算为 positive_coords 正点，SAM 稳定分割点下主体
    （bboxes 框路径实测不可靠，见模块 docstring）；描述由 subject_prompt 承载。
    """
    model_name, threshold, refine = _image_edit_options(options or {})
    if split_box is not None:
        box = normalize_split_box(split_box)
        center = {"x": box["x"] + box["width"] // 2, "y": box["y"] + box["height"] // 2}
        graph = {
            "1": {"class_type": "LoadImage", "inputs": {"image": filename}},
            "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model_name}},
            "4": {
                "class_type": "SAM3_Detect",
                "inputs": {
                    "model": ["2", 0],
                    "image": ["1", 0],
                    "threshold": threshold,
                    "refine_iterations": refine,
                    "individual_masks": False,
                    "positive_coords": json.dumps([center]),
                },
            },
        }
    else:
        graph = _sam3_detect_subgraph(filename, subject_prompt, model_name, threshold, refine)
    # SaveImageWithAlpha 白=透明（远端实测）：前景层取反相 mask，背景层取原始 mask。
    graph["8"] = {"class_type": "InvertMask", "inputs": {"mask": ["4", 0]}}
    graph[LAYER_FOREGROUND_NODE] = {
        "class_type": "SaveImageWithAlpha",
        "inputs": {
            "images": ["1", 0],
            "mask": ["8", 0],
            "filename_prefix": f"{IMAGE_EDIT_OUTPUT_PREFIX}/layer_foreground",
        },
    }
    graph[LAYER_BACKGROUND_NODE] = {
        "class_type": "SaveImageWithAlpha",
        "inputs": {
            "images": ["1", 0],
            "mask": ["4", 0],
            "filename_prefix": f"{IMAGE_EDIT_OUTPUT_PREFIX}/layer_background",
        },
    }
    return graph


def build_image_edit_workflow(
    mode: JobMode | str, filename: str, prompt: str, options: dict, *,
    mask_remove_filename: str | None = None, mask_keep_filename: str | None = None,
    split_box: dict | None = None,
) -> dict:
    """按工作流模式分发构建；供 comfy_service 调用。蒙版仅去背景工作流消费。"""
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    subject_prompt = (prompt or "").strip() or DEFAULT_SUBJECT_PROMPT
    if key == JobMode.IMAGE_BACKGROUND_REMOVE.value:
        return build_image_background_remove_workflow(
            filename, subject_prompt=subject_prompt, options=options,
            mask_remove_filename=mask_remove_filename, mask_keep_filename=mask_keep_filename,
        )
    if key == JobMode.IMAGE_LAYER_SPLIT.value:
        if str(options.get("split_mode") or "auto") == "description" and not (prompt or "").strip():
            raise ValueError("按描述拆分需要填写主体描述。")
        return build_image_layer_split_workflow(
            filename, subject_prompt=subject_prompt, options=options, split_box=split_box,
        )
    raise ValueError(f"不支持的图片编辑工作流: {mode}")
