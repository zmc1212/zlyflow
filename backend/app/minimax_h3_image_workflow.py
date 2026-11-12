from __future__ import annotations

from typing import Any

from .minimax_h3_image_prompts import (
    H3_IMAGE_PE_EDIT_USER_PROMPT,
    H3_IMAGE_PE_INPUT_PLACEHOLDER,
    H3_IMAGE_PE_SYSTEM_PROMPT,
    H3_IMAGE_PE_T2I_USER_PROMPT,
)
from .workflow_registry import (
    H3_IMAGE_CFG,
    H3_IMAGE_STEPS,
    h3_image_dimensions,
)

# MiniMax H3 Image（开源图像模型）：同一套权重支持文生图与 1-16 张参考图编辑。
# Graph 结构对照 ComfyUI 官方模板 image_minimax_h3_image_t2i / image_minimax_h3_image_edit
# （Comfy-Org/workflow_templates，要求 ComfyUI >= 0.45.0），仅按工作台参数接管。
H3_IMAGE_DIFFUSION_UNET = "minimax_h3_image_pruned_int8_convrot.safetensors"
H3_IMAGE_VAE_NAME = "minimax_h3_image_vae_fp16.safetensors"
# 文本编码器与 H3 视频工作流共用同一权重，远端实例已存在。
H3_IMAGE_TEXT_ENCODER_NAME = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
H3_IMAGE_PE_CLIP_NAME = "qwen3.5_9b_w4a8_gptq.safetensors"

# 官方模板采样契约：蒸馏 6 步、CFG=1（无负面提示词，euler/simple），常量定义在 workflow_registry。
H3_IMAGE_OUTPUT_NODE = "9"
H3_IMAGE_FILENAME_PREFIX = "image/ZLY_AI_VIDEO_STUDIO_MiniMax_H3_Image"

# 官方 T2I/Edit 模板 TextGenerateV2 的采样设置（widgets 原样保留，含 thinking）。
H3_IMAGE_PE_SAMPLING = {
    "temperature": 1.0,
    "top_k": 20,
    "top_p": 0.95,
    "min_p": 0.0,
    "repetition_penalty": 1.0,
    "presence_penalty": 0.0,
    "seed": 0,
}
H3_IMAGE_PE_MAX_LENGTH = 8196


def _pe_user_input(mode_key: str, prompt: str, options: dict[str, Any]) -> str:
    """按官方模板占位符契约组装 TextGenerateV2 的用户输入。"""
    if mode_key == "minimax-h3-image-edit":
        # 编辑模板契约：User Editing Instruction + User Aspect Ratio Selection 两行。
        aspect = str(options.get("aspect_ratio") or "auto")
        selection = "adaptive" if aspect == "auto" else aspect
        return f"User Editing Instruction: {prompt}\nUser Aspect Ratio Selection: {selection}"
    aspect = str(options.get("aspect_ratio") or "")
    if aspect and aspect != "auto":
        # T2I 扩展器自行选择画幅；画布已由用户选择钉死，补充一行避免构图与画幅打架。
        return f"{prompt}\nTarget canvas ratio: {aspect} (fixed)."
    return prompt


def build_minimax_h3_image_workflow(
    mode_key: str,
    prompt: str,
    references: list[str],
    options: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    """构建 MiniMax H3 Image 的 ComfyUI API graph（文生图 0 张 / 多参考 1-16 张）。"""
    pe_enabled = bool(options.get("prompt_expander", True))
    workflow: dict[str, dict[str, Any]] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": H3_IMAGE_DIFFUSION_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": H3_IMAGE_TEXT_ENCODER_NAME, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": H3_IMAGE_VAE_NAME}},
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["4", 1],
                "seed": seed,
                "steps": H3_IMAGE_STEPS,
                "cfg": H3_IMAGE_CFG,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        H3_IMAGE_OUTPUT_NODE: {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": H3_IMAGE_FILENAME_PREFIX},
        },
    }

    conditioning_inputs: dict[str, Any] = {"clip": ["2", 0], "vae": ["3", 0]}
    if pe_enabled:
        template = H3_IMAGE_PE_EDIT_USER_PROMPT if mode_key == "minimax-h3-image-edit" else H3_IMAGE_PE_T2I_USER_PROMPT
        user_input = template.replace(H3_IMAGE_PE_INPUT_PLACEHOLDER, _pe_user_input(mode_key, prompt, options))
        workflow["30"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": H3_IMAGE_PE_CLIP_NAME, "type": "minimax", "device": "default"}}
        workflow["31"] = {
            "class_type": "TextGenerateV2",
            "inputs": {
                "clip": ["30", 0],
                "prompt": user_input,
                "system_prompt": H3_IMAGE_PE_SYSTEM_PROMPT,
                "max_length": H3_IMAGE_PE_MAX_LENGTH,
                "sampling_mode": "on",
                **{f"sampling_mode.{key}": value for key, value in H3_IMAGE_PE_SAMPLING.items()},
                "thinking": True,
                "use_default_template": True,
                "mtp": "auto",
            },
        }
        workflow["32"] = {
            "class_type": "JsonExtractString",
            "inputs": {"json_string": ["31", 0], "key": "expanded_caption"},
        }
        conditioning_inputs["prompt"] = ["32", 0]
    else:
        conditioning_inputs["prompt"] = prompt

    # width/height 为 0 时节点自动跟随 image_1 的缩放尺寸（无参考图则 2048x2048），
    # 与官方模板的 GetImageSize 自适应路径一致。
    width, height = h3_image_dimensions(options)
    conditioning_inputs["width"] = width
    conditioning_inputs["height"] = height
    for index, filename in enumerate(references, start=20):
        node_id = str(index)
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        conditioning_inputs[f"images.image_{index - 19}"] = [node_id, 0]
    workflow["4"] = {"class_type": "MiniMaxH3ImageConditioning", "inputs": conditioning_inputs}
    workflow["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}}
    return workflow
