"""人声/伴奏分离（MelBand RoFormer）API graph 构建器。

远端 ComfyUI 需已安装 Mel-Band RoFormer 自定义节点与
``ComfyUI/models/diffusion_models/MelBandRoformer_fp16.safetensors`` 权重。
链路：LoadAudio -> MelBandRoFormerModelLoader -> MelBandRoFormerSampler
-> SaveAudio(vocals) + SaveAudio(instruments)。
"""
from __future__ import annotations

STEM_SPLIT_MODEL = "MelBandRoformer_fp16.safetensors"
STEM_SPLIT_VOCALS_NODE = "4"
STEM_SPLIT_INSTRUMENTS_NODE = "5"


def build_stem_split_workflow(audio_filename: str, *, model_name: str = STEM_SPLIT_MODEL) -> dict:
    """构建人声/伴奏分离 API graph；audio_filename 为已上传到 ComfyUI input 的文件名。"""
    return {
        "1": {"class_type": "MelBandRoFormerModelLoader", "inputs": {"model_name": model_name}},
        "2": {"class_type": "LoadAudio", "inputs": {"audio": audio_filename}},
        "3": {
            "class_type": "MelBandRoFormerSampler",
            "inputs": {"model": ["1", 0], "audio": ["2", 0]},
        },
        STEM_SPLIT_VOCALS_NODE: {
            "class_type": "SaveAudio",
            "inputs": {"audio": ["3", 0], "filename_prefix": "stem_split/vocals"},
        },
        STEM_SPLIT_INSTRUMENTS_NODE: {
            "class_type": "SaveAudio",
            "inputs": {"audio": ["3", 1], "filename_prefix": "stem_split/instruments"},
        },
    }
