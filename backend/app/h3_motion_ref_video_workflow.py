# -*- coding: utf-8 -*-
"""MiniMax H3 多人动作迁移（参考视频版）的 ComfyUI API graph 构建器。

与骨架 ControlNet 版(h3_motion_transfer_workflow)并行的第二条动作迁移路线:
不做 SDPose 骨架抽取,而是把动作参考视频直接作为 MiniMaxH3ReferenceToVideo 的
ref_videos.ref_video_0(<Video 1> 深度动作参考),1-6 张角色形象图走
ref_images.ref_image_0..5(<Picture n>),提示词以 <Subject> 模板把"图片角色"绑定到
"参考视频中的第 n 个表演者";动作片自带音轨时拼接 AV latent,保留原声与口型节奏。
链路已在远端 ComfyUI 实跑验证(单人竖版/双人横版/双人竖版)。
"""
from __future__ import annotations

from typing import Any

from .h3_motion_transfer_workflow import (
    MOTION_TRANSFER_FPS,
    snap_h3_length,
    snap_h3_size,
)

# 参考视频版对精度更敏感:使用非 pruned UNET 与 int8 CLIP(远端模型库已具备)。
MOTION_REF_UNET_FILENAME = "minimax_h3_ref2va_int8_convrot.safetensors"
MOTION_REF_CLIP_FILENAME = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
MOTION_REF_VIDEO_VAE_FILENAME = "minimax_h3_video_vae_int8_convrot.safetensors"
MOTION_REF_AUDIO_VAE_FILENAME = "minimax_h3_audio_vae_fp32.safetensors"
# 2026-11-04 对照远端官方 Aiden 多人模板(D:\动作迁移)发现:其替换链路挂了
# 专用 LoRA,此前工作台 graph 从未加载。文件原在 extra_model_paths 扫描范围外
# (D:\ComfyUI-Models\各种功能LORA),已复制 character_swap 的 ref2va 专用版到
# lightx2v 可见目录。本工作流 UNET 同为 ref2va 族,挂载该 LoRA 补上
# "视频替换人物"能力。不挂模板的 DMAD 4-step 加速 LoRA(本链路 20 步采样)。
MOTION_REF_SWAP_LORA = "minimaxh3-other\\minimax_h3_character_swap_v1.1_ref2va_fro.safetensors"
# 2026-11-04 官方 Aiden 多人模板另挂 DMAD 4-step 加速 LoRA(主采样 8 步 euler);
# 映射到本工作流 render_quality=preview 档:挂 DMAD + 8 步 + euler 快速出片。
# 标准/精细档不挂(20/30 步 res_multistep 不受 turbo LoRA 影响更稳)。
MOTION_REF_TURBO_LORA = "minimaxh3_turbo\\minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"

MOTION_REF_VIDEO_OUTPUT_NODE = "58"
MOTION_REF_VIDEO_FPS = MOTION_TRANSFER_FPS
MOTION_REF_MAX_CHARACTERS = 6
MOTION_REF_PERFORMER_COLORS = ("BLUE", "RED", "GREEN", "MAGENTA", "CYAN", "YELLOW")

MOTION_REF_VIDEO_DEFAULT_PROMPT = (
    "两名角色完整复刻 <Video 1> 中的舞蹈节奏与肢体轨迹,顺拐步伐、摆臂幅度与"
    "走向镜头的节拍和原片一致;前景持机角色保持自拍构图与轻微手持晃动,"
    "后方角色全身可见;白天江边步道,自然光,音画同步。"
)

# Aiden <Subject> 模板的紧凑产品化版本:角色绑定段 + 表演来源约束。
# 用户提示词注入 detailed_description 段;已自带 <Picture/subject_definitions 结构
# 的专家提示词则原样透传(见 compose_motion_ref_video_prompt)。
_MOTION_REF_TEMPLATE = """subject_definitions:
<Subject 1> is the target cast defined below, with one distinct role per entry:
{bindings}
Each entry links one image-defined target to one source performer. Preserve that target's own identity, physique, dimensions, proportions, materials and outfit. No character, category or setting is fixed by this template.
<Subject 2> is only each assigned performer's body action, facial expression and observable mouth state in <Video 1>, at the original times.
<Video 1> supplies performance only, not appearance, anatomy, body size, proportions, environment, lighting, composition or camera behaviour. Profile identifiers specify performance ownership only.
detailed_description:
{description}"""


def build_character_bindings(count: int, captions: list[str] | None = None) -> str:
    """为每张角色图生成一句"图片角色 → 参考视频表演者"绑定,超过已知人数用序号兜底。

    captions 为后端视觉模型生成的像素级外观描述(对齐官方模板的 ImageCaption 机制,
    但在建图前 bake 进模板,不依赖远端 caption 节点);缺失时保持原绑定句。
    """
    lines = []
    for index in range(max(1, min(int(count), MOTION_REF_MAX_CHARACTERS))):
        color = MOTION_REF_PERFORMER_COLORS[index] if index < len(MOTION_REF_PERFORMER_COLORS) else f"NUMBER {index + 1}"
        line = (
            f"Character {index + 1} is the target character in <Picture {index + 1}>, "
            f"assigned to the {color} source performer."
        )
        caption = str(captions[index] if captions and index < len(captions) else "").strip()
        if caption:
            line += f" Visual profile of Character {index + 1}: {caption}"
        lines.append(line)
    return "\n".join(lines)


def compose_motion_ref_video_prompt(
    user_prompt: str, character_count: int, character_captions: list[str] | None = None,
) -> str:
    """把用户创作描述包进 <Subject> 模板;专家用户已手写结构时原样透传。

    captions 只进绑定段(Visual profile)。描述段的外观主语句由服务层润色改写
    (_inject_appearance_into_prompt)提前写进 user_prompt:2026-11-04 实测图内
    间接引用、英文 caption 内嵌主语定义句(v1-v3)均无法让模型换人，唯一生效的
    是成功样本 xbzyTzeDkK6S 那种"中文外观主语紧贴动作"的描述段写法。
    """
    text = str(user_prompt or "").strip() or MOTION_REF_VIDEO_DEFAULT_PROMPT
    lowered = text.lower()
    if "<picture" in lowered or "subject_definitions" in lowered or "<video 1" in lowered:
        return text
    return _MOTION_REF_TEMPLATE.format(
        bindings=build_character_bindings(character_count, character_captions), description=text,
    )


def build_h3_motion_ref_video_workflow(
    character_image_filenames: list[str],
    motion_video_filename: str,
    prompt: str,
    *,
    width: int,
    height: int,
    length: int,
    steps: int = 20,
    seed: int,
    preserve_audio: bool = True,
    weight_dtype: str = "default",
    fps: int = MOTION_REF_VIDEO_FPS,
    character_captions: list[str] | None = None,
    turbo: bool = False,
) -> dict[str, dict[str, Any]]:
    """构建"1-6 张角色形象图 + 动作参考视频(可选原声) → 多人动作迁移"工作流。

    character_image_filenames 顺序即 <Picture n> 顺序;motion_video_filename 需已按
    画布尺寸/帧率/帧数预处理(带音轨时保留 aac);preserve_audio 仅在预处理探测到
    音轨时才应开启。character_captions 为后端视觉模型生成的各角色外观描述(可缺);
    turbo=True 时另挂 DMAD 加速 LoRA 并改用 euler 采样(快速预览档)。
    """
    characters = [str(name) for name in character_image_filenames if str(name).strip()]
    if not 1 <= len(characters) <= MOTION_REF_MAX_CHARACTERS:
        raise ValueError("多人动作迁移需要 1-6 张角色形象图。")
    safe_width = snap_h3_size(width)
    safe_height = snap_h3_size(height)
    frame_length = snap_h3_length(length)
    safe_steps = max(4, min(40, int(steps)))
    text = compose_motion_ref_video_prompt(prompt, len(characters), character_captions)

    workflow: dict[str, dict[str, Any]] = {
        "1": {
            "inputs": {"unet_name": MOTION_REF_UNET_FILENAME, "weight_dtype": weight_dtype},
            "class_type": "UNETLoader",
            "_meta": {"title": "加载 H3 Ref2VA 模型"},
        },
        "2": {
            "inputs": {"clip_name": MOTION_REF_CLIP_FILENAME, "type": "minimax", "device": "default"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "加载 Qwen3-VL 文本编码器"},
        },
        "3": {
            "inputs": {"vae_name": MOTION_REF_VIDEO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 视频 VAE"},
        },
        "4": {
            "inputs": {"vae_name": MOTION_REF_AUDIO_VAE_FILENAME},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 H3 音频 VAE"},
        },
        "5": {
            "inputs": {
                "anything": ["1", 0], "reserved": 3.0, "mode": "manual", "seed": int(seed),
                "auto_max_reserved": 0, "clean_gpu_before": True,
            },
            "class_type": "ReservedVRAMSetter",
            "_meta": {"title": "预留显存"},
        },
        "7": {
            "inputs": {"model": ["5", 0], "shift_video": 12.0, "shift_audio": 3.0},
            "class_type": "MiniMaxH3SigmaShift",
            "_meta": {"title": "H3 Sigma Shift"},
        },
        "8": {
            "inputs": {"model": ["7", 0]},
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "_meta": {"title": "省显存注意力"},
        },
        "9": {
            "inputs": {"model": ["8", 0], "lora_name": MOTION_REF_SWAP_LORA, "strength_model": 1.0},
            "class_type": "LoraLoaderModelOnly",
            "_meta": {"title": "视频替换人物 LoRA"},
        },
        "20": {
            "inputs": {"file": motion_video_filename},
            "class_type": "LoadVideo",
            "_meta": {"title": "动作参考视频"},
        },
        "21": {
            "inputs": {"video": ["20", 0]},
            "class_type": "GetVideoComponents",
            "_meta": {"title": "拆帧与音轨"},
        },
        "30": {
            "inputs": {
                "clip": ["2", 0],
                "vae": ["3", 0],
                "audio_vae": ["4", 0],
                "prompt": text,
                "width": safe_width,
                "height": safe_height,
                "length": frame_length,
                # 2026-11-04 实测:"match"会把角色图缩到生成画布面积(横屏 864x480 时
                # 脸部只剩几十像素),身份绑定完全失效;节点 tooltip 明确 "max" 用
                # 2048px 短边参考管线、身份保真最佳(代价是采样更慢)。
                "ref_image_size": "max",
                # V3 autogrow API links must be flattened; a nested dict is
                # accepted but silently ignored by ComfyUI.
                "ref_videos.ref_video_0": ["21", 0],
            },
            "class_type": "MiniMaxH3ReferenceToVideo",
            "_meta": {"title": "H3 参考生成(动作+身份)"},
        },
        "50": {
            "inputs": {"model": ["9", 0], "conditioning": ["30", 0]},
            "class_type": "BasicGuider",
            "_meta": {"title": "引导"},
        },
        "51": {"inputs": {"noise_seed": int(seed)}, "class_type": "RandomNoise", "_meta": {"title": "噪声"}},
        "52": {"inputs": {"sampler_name": "res_multistep"}, "class_type": "KSamplerSelect", "_meta": {"title": "采样器"}},
        "53": {
            "inputs": {"model": ["9", 0], "scheduler": "simple", "steps": safe_steps, "denoise": 1.0},
            "class_type": "BasicScheduler",
            "_meta": {"title": "调度"},
        },
        "54": {
            "inputs": {
                "noise": ["51", 0],
                "guider": ["50", 0],
                "sampler": ["52", 0],
                "sigmas": ["53", 0],
                "latent_image": ["30", 1],
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "采样"},
        },
        "55": {
            "inputs": {"samples": ["54", 0], "vae": ["3", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "解码视频帧"},
        },
        "57": {
            "inputs": {"images": ["55", 0], "fps": int(fps), "bit_depth": "auto", "color_space": "sRGB"},
            "class_type": "CreateVideo",
            "_meta": {"title": "合成的视频"},
        },
        MOTION_REF_VIDEO_OUTPUT_NODE: {
            "inputs": {
                "video": ["57", 0],
                "filename_prefix": "video/h3_motion_ref_video",
                "format": "auto",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存成片"},
        },
    }
    for index, filename in enumerate(characters):
        node_id = f"1{index + 10}"
        workflow[node_id] = {
            "inputs": {"image": filename},
            "class_type": "LoadImage",
            "_meta": {"title": f"角色形象图 {index + 1}"},
        }
        workflow["30"]["inputs"][f"ref_images.ref_image_{index}"] = [node_id, 0]

    if preserve_audio:
        # 原声链路:音轨裁剪 → 音频 VAE 编码 → 零遮罩 → 与视频 latent 拼成 AV latent。
        workflow["40"] = {
            "inputs": {"audio": ["21", 1], "start_index": 0.0, "duration": frame_length / max(1, int(fps))},
            "class_type": "TrimAudioDuration",
            "_meta": {"title": "裁剪原声"},
        }
        workflow["41"] = {
            "inputs": {"audio": ["40", 0], "vae": ["4", 0]},
            "class_type": "VAEEncodeAudio",
            "_meta": {"title": "编码音频 latent"},
        }
        workflow["42"] = {
            "inputs": {"value": 0.0, "width": 1, "height": 1},
            "class_type": "SolidMask",
            "_meta": {"title": "全零遮罩"},
        }
        workflow["43"] = {
            "inputs": {"samples": ["41", 0], "mask": ["42", 0]},
            "class_type": "SetLatentNoiseMask",
            "_meta": {"title": "锁定音频 latent"},
        }
        workflow["44"] = {
            "inputs": {"video_latent": ["30", 1], "audio_latent": ["43", 0]},
            "class_type": "LTXVConcatAVLatent",
            "_meta": {"title": "拼接 AV latent"},
        }
        workflow["54"]["inputs"]["latent_image"] = ["44", 0]
        workflow["56"] = {
            "inputs": {"samples": ["54", 0], "vae": ["4", 0]},
            "class_type": "VAEDecodeAudio",
            "_meta": {"title": "解码音频"},
        }
        workflow["57"]["inputs"]["audio"] = ["56", 0]

    if turbo:
        # 快速预览档：对齐官方 Aiden 模板 DMAD 链路——替换 LoRA 后再挂 turbo LoRA，
        # 主采样改 euler（steps 由上层 render_quality=preview 映射为 8，与模板一致）。
        workflow["91"] = {
            "inputs": {
                "model": ["9", 0],
                "lora_name": MOTION_REF_TURBO_LORA,
                "strength_model": 1.0,
            },
            "class_type": "LoraLoaderModelOnly",
            "_meta": {"title": "DMAD 4-step 加速 LoRA"},
        }
        workflow["50"]["inputs"]["model"] = ["91", 0]
        workflow["53"]["inputs"]["model"] = ["91", 0]
        workflow["52"]["inputs"]["sampler_name"] = "euler"
    return workflow
