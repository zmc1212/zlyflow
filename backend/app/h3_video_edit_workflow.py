"""Native H3 Ref2VA editing of a source clip, independent of pose/depth control."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

from .h3_depth_workflow import (
    H3_UNET_FILENAME, H3_CLIP_FILENAME, H3_VIDEO_VAE_FILENAME, H3_AUDIO_VAE_FILENAME,
)
from .video_analysis import VideoAnalysisError, probe_video

VIDEO_EDIT_OUTPUT_NODE = "14"
VIDEO_EDIT_LENGTHS = {"5s": 124, "10s": 243, "15s": 362}
# Keep the accepted 512x896 source intact; the former 0.26 MP trial lost small-face detail.
VIDEO_EDIT_MAX_PIXELS = 512 * 896
VIDEO_EDIT_MODELS = {
    "unet": H3_UNET_FILENAME, "clip": H3_CLIP_FILENAME,
    "video_vae": H3_VIDEO_VAE_FILENAME, "audio_vae": H3_AUDIO_VAE_FILENAME,
}


def video_edit_dimensions(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, math.sqrt(VIDEO_EDIT_MAX_PIXELS / max(1, width * height)))
    return max(32, int(width * scale) // 32 * 32), max(32, int(height * scale) // 32 * 32)


def validate_video_edit_source(path: Path, duration: str):
    try:
        source = probe_video(path)
    except (VideoAnalysisError, OSError, ValueError) as error:
        raise ValueError("原片无法读取，请上传包含视频画面的 MP4 / MOV / WebM。") from error
    required = VIDEO_EDIT_LENGTHS[duration] / 24
    if source.duration + 0.1 < required:
        raise ValueError(f"原片只有 {source.duration:.1f} 秒，不足本次 {required:.2f} 秒的视频编辑时长。")
    return source


def prepare_video_edit_source(source: Path, destination: Path, *, width: int, height: int, length: int) -> Path:
    # This preprocessing belongs to the platform worker. Retain the original BGM;
    # use the same 24 fps clip for visual conditioning and the native output audio.
    from .director_export import find_ffmpeg

    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("视频编辑需要 FFmpeg。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-vf",
            f"fps=24,scale={width}:{height}:flags=lanczos,tpad=stop_mode=clone:stop_duration=0.1",
            "-frames:v", str(length), "-t", str(length / 24), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(destination),
        ], check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError("视频编辑原片预处理失败，请换用标准 MP4 后重试。") from error
    if not destination.is_file() or not destination.stat().st_size:
        raise ValueError("视频编辑预处理没有输出可读视频。")
    return destination


def build_h3_video_edit_workflow(source_video: str, prompt: str, *, width: int, height: int,
                                 length: int = 124, steps: int = 20, seed: int = 0,
                                 preserve_audio: bool = True,
                                 model_files: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    def node(kind: str, **inputs: Any) -> dict[str, Any]:
        return {"class_type": kind, "inputs": inputs}

    models = {**VIDEO_EDIT_MODELS, **(model_files or {})}
    graph = {
        "1": node("UNETLoader", unet_name=models["unet"], weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=models["clip"], type="minimax", device="default"),
        "3": node("VAELoader", vae_name=models["video_vae"]),
        "4": node("VAELoader", vae_name=models["audio_vae"]),
        "20": node("LoadVideo", file=source_video),
        "21": node("GetVideoComponents", video=["20", 0]),
        "5": node("MiniMaxH3ReferenceToVideo", clip=["2", 0], vae=["3", 0], audio_vae=["4", 0],
                  prompt=prompt.strip(), width=width, height=height, length=length,
                  ref_image_size="match", **{"ref_videos.ref_video_0": ["21", 0]}),
        "16": node("ReservedVRAMSetter", anything=["1", 0], reserved=3.0, mode="manual", seed=0,
                   auto_max_reserved=0, clean_gpu_before=True),
        "17": node("MiniMaxH3MemoryEfficientSageAttentionPatch", model=["16", 0]),
        "6": node("BasicGuider", model=["17", 0], conditioning=["5", 0]),
        "7": node("BasicScheduler", model=["17", 0], scheduler="simple", steps=steps, denoise=1.0),
        "8": node("RandomNoise", noise_seed=seed),
        "9": node("KSamplerSelect", sampler_name="res_multistep"),
        "10": node("SamplerCustomAdvanced", noise=["8", 0], guider=["6", 0], sampler=["9", 0],
                   sigmas=["7", 0], latent_image=["5", 1]),
        "11": node("VAEDecode", samples=["10", 0], vae=["3", 0]),
        "13": node("CreateVideo", images=["11", 0], fps=24.0, bit_depth=8),
        "14": node("SaveVideo", video=["13", 0], filename_prefix="video/ZLY_H3_Video_Edit", format="auto", codec="auto"),
    }
    if preserve_audio:
        graph["13"]["inputs"]["audio"] = ["21", 1]
    return graph
