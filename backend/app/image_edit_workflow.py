"""ComfyUI 图片编辑工作流构建器（图片去背景 / 图层分离）。

图片类工作流此前只能经 GRS 执行器生成；本模块提供直接跑在当前连接 ComfyUI
实例上的图片编辑 graph。分割引擎使用远端已安装的 SAM3.1
（sam3.1_multiplex_fp16 + SAM3_Detect + CLIPTextEncode 文本概念提示），
alpha 输出用 SaveImageWithAlpha——不引入新模型、不部署第二套 ComfyUI。

文本提示 vs 点提示：SCAIL-2 的动作迁移走 positive_coords 点提示；
本工作流用 conditioning 文本概念（如 the main subject / the product），
无需用户点选即可自动分割。主体描述由任务的 prompt 字段提供。

输出节点 ID 固定，供 comfy_service 的交付与恢复链路（completed_outputs）使用：
- 去背景：节点 ``9``（原图 RGB + SAM3 mask 作为 alpha 的透明 PNG）
- 图层分离：节点 ``9``（前景层）/ ``10``（背景层，主体挖空的透明 PNG）
"""

from __future__ import annotations

from .models import JobMode

SAM3_OUTPUT_NODE = "9"
LAYER_FOREGROUND_NODE = "9"
LAYER_BACKGROUND_NODE = "10"

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
) -> dict:
    """图片去背景：文本概念提示分割主体，原图 RGB 配 SAM3 mask 作为 alpha。

    远端实测：SaveImageWithAlpha 把 mask 白色当作透明（与节点描述相反），
    主体 alpha 需先经 InvertMask 反相。
    """
    model_name, threshold, refine = _image_edit_options(options or {})
    graph = _sam3_detect_subgraph(filename, subject_prompt, model_name, threshold, refine)
    graph["8"] = {"class_type": "InvertMask", "inputs": {"mask": ["4", 0]}}
    graph[SAM3_OUTPUT_NODE] = {
        "class_type": "SaveImageWithAlpha",
        "inputs": {
            "images": ["1", 0],
            "mask": ["8", 0],
            "filename_prefix": f"{IMAGE_EDIT_OUTPUT_PREFIX}/background_remove",
        },
    }
    return graph


def build_image_layer_split_workflow(
    filename: str, *, subject_prompt: str = DEFAULT_SUBJECT_PROMPT, options: dict | None = None,
) -> dict:
    """图层分离：同一 SAM3 mask 派生前景层与背景层（主体挖空），画布叠放可还原原图。"""
    model_name, threshold, refine = _image_edit_options(options or {})
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


def build_image_edit_workflow(mode: JobMode | str, filename: str, prompt: str, options: dict) -> dict:
    """按工作流模式分发构建；供 comfy_service 调用。"""
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    subject_prompt = (prompt or "").strip() or DEFAULT_SUBJECT_PROMPT
    if key == JobMode.IMAGE_BACKGROUND_REMOVE.value:
        return build_image_background_remove_workflow(
            filename, subject_prompt=subject_prompt, options=options,
        )
    if key == JobMode.IMAGE_LAYER_SPLIT.value:
        return build_image_layer_split_workflow(
            filename, subject_prompt=subject_prompt, options=options,
        )
    raise ValueError(f"不支持的图片编辑工作流: {mode}")
