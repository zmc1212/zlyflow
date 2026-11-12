"""SCAIL-2 Replacement + SAM3.1, based on the verified 81-frame native graph."""
from __future__ import annotations

import json
import copy
import io
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

SCAIL_OUTPUT_NODE = "46"
SCAIL_DIAGNOSTIC_PREFIX = "scail2_diagnostics/"
SCAIL_DEFAULT_PROMPT = (
    "Each selected performer matches their corresponding reference character's appearance and clothing "
    "and follows their own actions, stepping rhythm, hand gestures, facial expressions and head movements "
    "in the driving video. The other people, camera "
    "movement and surrounding scene remain consistent with the driving video."
)
SCAIL_MODELS = {
    "UNETLoader": ("unet_name", "wan2.1_14B_SCAIL_2_int8_convrot.safetensors"),
    "CheckpointLoaderSimple": ("ckpt_name", "sam3.1_multiplex_fp16.safetensors"),
    "CLIPLoader": ("clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "CLIPVisionLoader": ("clip_name", "clip_vision_h.safetensors"),
    "VAELoader": ("vae_name", "Wan2_1_VAE_bf16.safetensors"),
}
DPO_LORA = "wan2.1_SCAIL_2_DPO_lora_bf16.safetensors"
LIGHT_LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"


def subject_points(value: str, label: str, subject_count: int = 1) -> list[dict]:
    """Normalized points belong to the displayed, orientation-correct source media."""
    try:
        points = json.loads(value)
        if not isinstance(points, list) or not 1 <= len(points) <= 20 * subject_count:
            raise ValueError()
        result = []
        for point in points:
            if not isinstance(point, dict) or set(point) - {"x", "y", "exclude", "subject"}:
                raise ValueError()
            x, y = point["x"], point["y"]
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
                raise ValueError()
            exclude = point.get("exclude", False)
            if not isinstance(exclude, bool):
                raise ValueError()
            subject = point.get("subject", 0)
            if type(subject) is not int or not 0 <= subject < subject_count:
                raise ValueError()
            result.append({"x": x, "y": y, "exclude": exclude, "subject": subject})
        for subject in range(subject_count):
            selected = [p for p in result if p["subject"] == subject]
            if len(selected) > 20 or not any(not p["exclude"] for p in selected):
                raise ValueError()
        return result
    except (ValueError, TypeError, KeyError):
        raise ValueError(f"请先在{label}上点击选中每一位要替换的人物，并按相同编号配对；标记需位于画面内。") from None


def scail_chunk_plan(length: int) -> list[dict[str, int]]:
    if not 16 <= length <= 481:
        raise ValueError("动作迁移帧数超出支持范围。")
    chunks, end = [], 0
    while end < length:
        start = max(0, end - 5) if chunks else 0
        count = min(81, 1 + 4 * math.ceil((length - start - 1) / 4))
        chunks.append({"start": start, "length": count})
        end = start + count
    return chunks


def resolve_scail_video_options(path: Path, duration: str) -> dict:
    from .motion_transfer_media import probe_video
    from .video_analysis import VideoAnalysisError

    try:
        probe = probe_video(path)
    except (VideoAnalysisError, OSError, ValueError) as error:
        raise ValueError("动作参考视频无法读取，请使用标准 MP4 / MOV / WebM 文件。") from error
    if duration == "full":
        if not 1 <= probe.duration <= 30:
            raise ValueError("完整原片模式支持 1–30 秒视频，请更换视频后重试。")
        length = math.ceil(probe.duration * 16)
    else:
        if probe.duration + 0.1 < 5:
            raise ValueError("动作参考视频不足 5 秒，请更换视频或选择完整原片。")
        length = 81
    chunks = scail_chunk_plan(length)
    return {"source_duration": probe.duration, "length": length,
            "conditioning_length": chunks[-1]["start"] + chunks[-1]["length"], "chunk_count": len(chunks)}


def _geometry(size: tuple[int, int], canvas: tuple[int, int]) -> tuple[int, int, int, int]:
    scale = min(canvas[0] / size[0], canvas[1] / size[1])
    w, h = (max(2, int(v * scale) // 2 * 2) for v in size)
    return w, h, (canvas[0] - w) // 2, (canvas[1] - h) // 2


def scail_canvas(size: tuple[int, int]) -> tuple[int, int]:
    scale = math.sqrt((512 * 896) / (size[0] * size[1]))
    return tuple(max(256, min(1280, round(v * scale / 32) * 32)) for v in size)


def probe_scail_canvas(video: Path) -> tuple[int, int]:
    from .director_export import find_ffmpeg

    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("动作迁移需要 FFmpeg，请安装后再试。")
    try:
        result = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(video),
                                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                                capture_output=True, check=True, timeout=30)
        with Image.open(io.BytesIO(result.stdout)) as frame:
            return scail_canvas(frame.size)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ValueError("动作参考视频首帧无法读取，请使用标准 MP4 文件。") from error


def scail_missing_message(info: dict, graph: dict) -> str | None:
    missing = sorted({v["class_type"] for v in graph.values()} - set(info))
    if missing:
        return "当前视频服务缺少动作迁移节点：" + "、".join(missing)
    for kind, (field, filename) in [*SCAIL_MODELS.items(),
                                   ("LoraLoaderModelOnly", ("lora_name", DPO_LORA)),
                                   ("LoraLoaderModelOnly", ("lora_name", LIGHT_LORA))]:
        choices = info[kind].get("input", {}).get("required", {}).get(field, [[]])[0]
        if isinstance(choices, list) and filename not in choices:
            return f"当前视频服务未发现动作迁移模型：{filename}"
    return None


def _pixel_points(points: list[dict], geometry: tuple[int, int, int, int]) -> tuple[str, str]:
    w, h, left, top = geometry
    def selected(exclude: bool) -> str:
        return json.dumps([{"x": left + min(w - 1, round(p["x"] * w)),
                            "y": top + min(h - 1, round(p["y"] * h))}
                           for p in points if p["exclude"] == exclude])
    return selected(False), selected(True)


def subject_prompt_points(points: list[dict], index: int) -> list[dict]:
    """Keep user exclusions, with one stable exclusion anchor per other person.

    Adding detail points to one person must not flood another person's SAM
    prompt with negatives, which can carve holes in hair and dark clothing.
    """
    own = [v for v in points if v["subject"] == index]
    seen = set()
    other = []
    for point in points:
        if point["subject"] != index and not point["exclude"] and point["subject"] not in seen:
            other.append(dict(point, exclude=True))
            seen.add(point["subject"])
    return own + other


def prepare_scail_inputs(image: Path, video: Path, directory: Path, options: dict) -> dict:
    from .director_export import find_ffmpeg

    ffmpeg = find_ffmpeg("ffmpeg")
    if not ffmpeg:
        raise ValueError("动作迁移需要 FFmpeg，请安装后再试。")
    directory.mkdir(parents=True, exist_ok=True)
    first = directory / "source-first.png"
    def run(args: list[str]) -> None:
        try:
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", *args],
                           capture_output=True, check=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("动作素材预处理失败，请使用可读取的图片与标准 MP4 视频。") from error
    run(["-i", str(video), "-frames:v", "1", str(first)])
    with Image.open(first) as frame:
        size = frame.size
    # Limit pixel cost to the verified ~0.46 MP envelope; preserve source framing.
    canvas = scail_canvas(size)
    source_geometry = _geometry(size, canvas)
    w, h, left, top = source_geometry
    with Image.open(first) as frame:
        prepared = Image.new("RGB", canvas)
        prepared.paste(frame.convert("RGB").resize((w, h), Image.Resampling.LANCZOS), (left, top))
        prepared.save(first)
    reference = directory / "character.png"
    with Image.open(image) as original:
        character = ImageOps.exif_transpose(original).convert("RGB")
        reference_geometry = _geometry(character.size, canvas)
        rw, rh, rx, ry = reference_geometry
        prepared = Image.new("RGB", canvas)
        prepared.paste(character.resize((rw, rh), Image.Resampling.LANCZOS), (rx, ry))
        prepared.save(reference)
    motion = directory / "motion.mp4"
    filters = f"fps=16,scale={w}:{h},pad={canvas[0]}:{canvas[1]}:{left}:{top},setsar=1,tpad=stop_mode=clone:stop_duration=0.2"
    frame_count = options.get("conditioning_length", 81)
    run(["-i", str(video), "-map", "0:v:0", "-map", "0:a:0?", "-vf", filters.replace("stop_duration=0.2", "stop_duration=0.3"),
         "-frames:v", str(frame_count), "-t", str(frame_count / 16), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(motion)])
    count = int(options.get("subject_count", "1"))
    source_points = subject_points(options["source_points"], "视频首帧", count)
    reference_points = subject_points(options["reference_points"], "形象图", count)
    def coordinates(points, geometry, index):
        return _pixel_points(subject_prompt_points(points, index), geometry)
    sources = [coordinates(source_points, source_geometry, i) for i in range(count)]
    references = [coordinates(reference_points, reference_geometry, i) for i in range(count)]
    return {"image": reference, "video": motion, "first": first, "width": canvas[0], "height": canvas[1],
            "source_coords": sources[0], "reference_coords": references[0],
            "source_coords_by_subject": sources, "reference_coords_by_subject": references}


def build_scail2_workflow(image: str, video: str, first: str, prompt: str, *,
                          width: int, height: int, source_coords: tuple[str, str],
                          reference_coords: tuple[str, str], seed: int, preserve_audio: bool = True,
                          length: int = 81, source_coords_by_subject: list | None = None,
                          reference_coords_by_subject: list | None = None) -> dict:
    def node(kind: str, **inputs) -> dict:
        return {"class_type": kind, "inputs": inputs}
    graph = {
        "1": node("LoadVideo", file=video),
        "2": node("GetVideoComponents", video=["1", 0]),
        "3": node("LoadImage", image=image),
        "4": node("CheckpointLoaderSimple", ckpt_name=SCAIL_MODELS["CheckpointLoaderSimple"][1]),
        "5": node("LoadImage", image=first),
        "8": node("SAM3_VideoTrack", images=["2", 0], model=["4", 0], initial_mask=["6", 0], detection_threshold=0.5, max_objects=1, detect_interval=1),
        "9": node("SAM3_VideoTrack", images=["3", 0], model=["4", 0], initial_mask=["7", 0], detection_threshold=0.5, max_objects=1, detect_interval=1),
        "10": node("SCAIL2ColoredMask", driving_track_data=["8", 0], ref_track_data=["9", 0], object_indices="", sort_by="left_to_right", replacement_mode=True),
        "21": node("SAM3_TrackToMask", track_data=["9", 0], object_indices=""),
        "22": node("EmptyImage", width=width, height=height, batch_size=1, color=0),
        "23": node("ImageCompositeMasked", destination=["22", 0], source=["3", 0], x=0, y=0, resize_source=False, mask=["21", 0]),
        "30": node("UNETLoader", unet_name=SCAIL_MODELS["UNETLoader"][1], weight_dtype="default"),
        "31": node("LoraLoaderModelOnly", model=["30", 0], lora_name=DPO_LORA, strength_model=1.0),
        "32": node("LoraLoaderModelOnly", model=["31", 0], lora_name=LIGHT_LORA, strength_model=0.8),
        "33": node("ModelSamplingSD3", model=["32", 0], shift=5.0),
        "34": node("CLIPLoader", clip_name=SCAIL_MODELS["CLIPLoader"][1], type="wan", device="default"),
        "35": node("CLIPTextEncode", clip=["34", 0], text=prompt.strip() or SCAIL_DEFAULT_PROMPT),
        "36": node("CLIPTextEncode", clip=["34", 0], text=""),
        "37": node("CLIPVisionLoader", clip_name=SCAIL_MODELS["CLIPVisionLoader"][1]),
        # The official template encodes the intact reference. WanSCAILToVideo
        # applies its identity mask internally; pre-matting also changes CLIP's
        # appearance features and can bake mask defects into the reference.
        "38": node("CLIPVisionEncode", clip_vision=["37", 0], image=["3", 0], crop="none"),
        "39": node("VAELoader", vae_name=SCAIL_MODELS["VAELoader"][1]),
        "40": node("WanSCAILToVideo", positive=["35", 0], negative=["36", 0], vae=["39", 0], width=width, height=height, length=81, batch_size=1, pose_strength=1.0, pose_start=0.0, pose_end=1.0, video_frame_offset=0, previous_frame_count=5, replacement_mode=True, pose_video=["2", 0], pose_video_mask=["10", 0], reference_image=["3", 0], reference_image_mask=["10", 1], clip_vision_output=["38", 0]),
        "41": node("KSamplerSelect", sampler_name="euler"),
        # Match the official replacement template: turbo sigmas come from the
        # LoRA model before ModelSamplingSD3; only the sampler uses the shifted model.
        "42": node("BasicScheduler", model=["32", 0], scheduler="simple", steps=6, denoise=1.0),
        "43": node("SamplerCustom", model=["33", 0], add_noise=True, noise_seed=seed, cfg=1.0, positive=["40", 0], negative=["40", 1], sampler=["41", 0], sigmas=["42", 0], latent_image=["40", 2]),
        "44": node("VAEDecode", samples=["43", 0], vae=["39", 0]),
        "45": node("CreateVideo", images=["44", 0], fps=16.0, bit_depth="auto", color_space="sRGB", **({"audio": ["2", 1]} if preserve_audio else {})),
        "46": node("SaveVideo", video=["45", 0], filename_prefix="video/scail2_replacement", format="auto"),
    }
    for key, source, coords in [("6", "5", source_coords), ("7", "3", reference_coords)]:
        graph[key] = node("SAM3_Detect", model=["4", 0], image=[source, 0], threshold=0.5,
                          refine_iterations=2, individual_masks=False, positive_coords=coords[0], negative_coords=coords[1])
    sources = source_coords_by_subject or [source_coords]
    references = reference_coords_by_subject or [reference_coords]
    if len(sources) != len(references) or len(sources) not in {1, 2}:
        raise ValueError("形象图与视频需选择相同数量的人物。")
    if len(sources) == 2:
        for key, source, coords in [("17", "5", sources[1]), ("19", "3", references[1])]:
            graph[key] = node("SAM3_Detect", model=["4", 0], image=[source, 0], threshold=0.5,
                              refine_iterations=2, individual_masks=False, positive_coords=coords[0], negative_coords=coords[1])
        graph["18"] = node("BatchMasksNode", **{"masks.mask0": ["6", 0], "masks.mask1": ["17", 0]})
        graph["20"] = node("BatchMasksNode", **{"masks.mask0": ["7", 0], "masks.mask1": ["19", 0]})
        graph["8"]["inputs"].update(initial_mask=["18", 0], max_objects=2)
        graph["9"]["inputs"].update(initial_mask=["20", 0], max_objects=2)
        # Preserve explicit UI pairing even when the two images have different left/right order.
        graph["10"]["inputs"]["sort_by"] = "none"
    # Persist exact native inputs for read-only quality diagnosis. These images
    # never feed generation or change the stable video output node 46. Schedule
    # them before video output so input defects are inspectable while sampling.
    prefix = f"{SCAIL_DIAGNOSTIC_PREFIX}{Path(image).stem}"
    audits = {
        "60": node("ImageFromBatch", image=["10", 0], batch_index=0, length=1),
        "61": node("SaveImage", images=["3", 0], filename_prefix=f"{prefix}/reference-original"),
        "62": node("SaveImage", images=["23", 0], filename_prefix=f"{prefix}/reference-matted"),
        "63": node("SaveImage", images=["10", 1], filename_prefix=f"{prefix}/reference-mask"),
        "64": node("SaveImage", images=["60", 0], filename_prefix=f"{prefix}/source-first-mask"),
        "65": node("MaskToImage", mask=["7", 0]),
        "66": node("SaveImage", images=["65", 0], filename_prefix=f"{prefix}/reference-seed-1"),
    }
    if len(references) == 2:
        audits["67"] = node("MaskToImage", mask=["19", 0])
        audits["68"] = node("SaveImage", images=["67", 0], filename_prefix=f"{prefix}/reference-seed-2")
    video_output = graph.pop("46")
    graph.update(audits)
    graph["46"] = video_output
    chunks = scail_chunk_plan(length)
    graph["40"]["inputs"]["length"] = chunks[0]["length"]
    previous_batch = "44"
    for index, chunk in enumerate(chunks[1:], 1):
        offset = 100 * index
        for original in [40, 41, 42, 43, 44]:
            entry = copy.deepcopy(graph[str(original)])
            for key, value in entry["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]).isdigit() and 40 <= int(value[0]) <= 44:
                    entry["inputs"][key] = [str(int(value[0]) + offset), value[1]]
            graph[str(original + offset)] = entry
        graph[str(40 + offset)]["inputs"].update(length=chunk["length"],
            previous_frames=[str(44 + offset - 100), 0], video_frame_offset=[str(40 + offset - 100), 3])
        trim, joined = str(50 + offset), str(1000 + index)
        graph[trim] = node("ImageFromBatch", image=[str(44 + offset), 0], batch_index=5, length=chunk["length"] - 5)
        graph[joined] = node("ImageBatch", image1=[previous_batch, 0], image2=[trim, 0])
        previous_batch = joined
    if len(chunks) > 1 or chunks[0]["length"] != length:
        graph["2000"] = node("ImageFromBatch", image=[previous_batch, 0], batch_index=0, length=length)
        graph["45"]["inputs"]["images"] = ["2000", 0]
    return graph
