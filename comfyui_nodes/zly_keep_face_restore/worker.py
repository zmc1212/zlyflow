"""Reference KEEP inference called inside ComfyUI's inference context."""
from __future__ import annotations

import ast
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
import gc
import torch
from comfy import model_management

from .geometry import choose_face, frame_windows


def run(config, emit):
    import cv2
    paths = sys.path[:]
    threads = torch.get_num_threads()
    cv_threads = cv2.getNumThreads()
    resources = {}
    try:
        return _run(config, emit, resources)
    finally:
        for name in ("base", "source"):
            capture = resources.pop(name, None)
            if capture is not None:
                capture.close() if isinstance(capture, VideoFrames) else capture.release()
        for name in ("aligned", "sums"):
            array = resources.pop(name, None)
            if array is not None:
                array._mmap.close()
        for name in ("net", "detector", "parser"):
            model = resources.pop(name, None)
            if model is not None:
                model.to(model_management.unet_offload_device())
        resources.clear()
        sys.path[:] = paths
        torch.set_num_threads(threads)
        cv2.setNumThreads(cv_threads)
        gc.collect()
        model_management.soft_empty_cache()


def frame_count(capture, cv2):
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if count <= 0:
        while capture.read()[0]:
            count += 1
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return count


class VideoFrames:
    def __init__(self, path, fps, width, height, cv2):
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(path)
        self.source_fps = self.capture.get(cv2.CAP_PROP_FPS)
        if not self.capture.isOpened() or not math.isfinite(self.source_fps) or self.source_fps <= 0:
            self.capture.release()
            raise ValueError("修脸输入视频无法读取，请重新上传完整原片。")
        self.fps, self.width, self.height = fps, width, height
        self.index = -1
        self.last = None

    def at(self, index):
        wanted = round(index * self.source_fps / self.fps)
        while self.index < wanted:
            ok, image = self.capture.read()
            if not ok:
                return None
            self.index += 1
            self.last = image
        if self.last is None:
            return None
        if self.last.shape[:2] != (self.height, self.width):
            return self.cv2.resize(self.last, (self.width, self.height), interpolation=self.cv2.INTER_LANCZOS4)
        return self.last

    def close(self):
        self.capture.release()


def _run(config, progress, resources):
    runtime = Path(config["runtime"])
    deps = runtime / "modules/deps"
    sys.path[:0] = [config["comfy_root"], str(runtime / "isolated_dependencies"), str(deps)]
    # Load the inference packages without importing their unrelated training stack.
    for name, relative in [("wm_basicsr", "wm_basicsr"), ("wm_basicsr.archs", "wm_basicsr/archs"), ("wm_facelib", "wm_facelib")]:
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(deps / relative)]
            sys.modules[name] = package
    import cv2
    import av
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
    from torchvision.transforms.functional import normalize
    from wm_basicsr.archs.keep_arch import KEEP
    from wm_facelib.parsing import init_parsing_model
    from wm_facelib.utils.face_restoration_helper import FaceRestoreHelper

    began = time.monotonic()
    torch.set_num_threads(4)
    cv2.setNumThreads(4)
    temp = Path(config["temp_dir"])
    base = cv2.VideoCapture(config["base_video"])
    resources["base"] = base
    width, height = int(base.get(cv2.CAP_PROP_FRAME_WIDTH)), int(base.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(base.get(cv2.CAP_PROP_FPS))
    count = frame_count(base, cv2)
    if not base.isOpened() or min(width, height, count, fps) <= 0 or not math.isfinite(fps):
        raise ValueError("视频无法读取，请换用标准 MP4 文件。")
    if config["duration"] == "5s":
        count = min(count, max(1, round(5 * fps)))
    point = np.asarray(config["point"], np.float32) * [width, height]
    if not np.isfinite(point).all() or not (0 <= point[0] <= width and 0 <= point[1] <= height):
        raise ValueError("人脸标记无效，请重新选择。")
    helper = FaceRestoreHelper(1, face_size=512, crop_ratio=(1, 1), det_model="retinaface_resnet50",
                               use_parse=False, device=model_management.get_torch_device(),
                               model_rootpath=str(Path(config["detector"]).parent))
    helper.face_parse = init_parsing_model("parsenet", device=model_management.get_torch_device(),
                                          model_rootpath=str(Path(config["parser"]).parent))
    device = model_management.get_torch_device()
    resources.update(detector=helper.face_detector, parser=helper.face_parse)
    landmarks = np.full((count, 5, 2), np.nan, np.float32)
    source = VideoFrames(config["source_video"], fps, width, height, cv2)
    resources["source"] = source
    previous = None
    velocity = np.zeros(2, np.float32)
    span = min(width, height)
    lost = 0
    yy, xx = np.mgrid[:704, :704].astype(np.float32)
    for index in range(count):
        if index % 12 == 0:
            progress(2 + 16 * index / count, stage="tracking", frame=index, frames=count)
        frame = source.at(index)
        if frame is None or lost > 8:
            continue
        expected = point if previous is None else previous.mean(axis=0) + velocity
        old_width = None if previous is None else float(np.ptp(previous[:, 0]))
        search = max(128, old_width * 5.5) if old_width else max(128, min(width, height) * .5)
        left, top = expected - search / 2
        crop = cv2.remap(frame, np.asarray(left + (xx + .5) * search / 704 - .5, dtype=np.float32),
                         np.asarray(top + (yy + .5) * search / 704 - .5, dtype=np.float32), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT)
        helper.clean_all()
        helper.read_image(crop)
        helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
        candidates = [(np.asarray(p) + .5) * search / 704 + [left-.5, top-.5] for p in helper.all_landmarks_5]
        chosen = choose_face(candidates, expected, span, first=previous is None, expected_width=old_width)
        if chosen is None:
            if previous is None:
                raise ValueError("所选位置未检测到人脸，请在首帧点击清晰的人脸中心。")
            lost += 1
            velocity *= .5
            continue
        current = np.asarray(candidates[chosen], np.float32)
        if previous is not None:
            velocity = (current.mean(axis=0) - previous.mean(axis=0)) * .6 + velocity * .4
        previous = current
        landmarks[index] = current
        lost = 0
    source.close()
    valid = np.isfinite(landmarks).all(axis=(1, 2))
    smoothed = landmarks.copy()
    runs = list(frame_windows(valid, count + 1, 0))
    for start, end in runs:
        if config["landmark_sigma"] > 0:
            smoothed[start:end] = gaussian_filter1d(landmarks[start:end], config["landmark_sigma"], axis=0)
    aligned = np.lib.format.open_memmap(temp / "aligned.npy", mode="w+", dtype=np.uint8, shape=(count, 512, 512, 3))
    resources["aligned"] = aligned
    affine = np.zeros((count, 2, 3), np.float32)
    source = VideoFrames(config["source_video"], fps, width, height, cv2)
    resources["source"] = source
    for index in range(count):
        if index % 12 == 0:
            progress(18 + 2 * index / count, stage="alignment")
        frame = source.at(index)
        if not valid[index] or frame is None:
            continue
        helper.clean_all()
        helper.read_image(frame)
        helper.all_landmarks_5 = [smoothed[index]]
        helper.align_warp_face()
        aligned[index] = helper.cropped_faces[0]
        affine[index] = helper.affine_matrices[0]
    source.close()
    definitions = {}
    for node in ast.parse((runtime / "modules/utils.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"KEEP_MODEL_CONFIGS", "default_arch_params"}:
            definitions[node.targets[0].id] = ast.literal_eval(node.value)
    architecture = dict(definitions["KEEP_MODEL_CONFIGS"]["KEEP"]["architecture"])
    for key, value in definitions["default_arch_params"].items():
        architecture.setdefault(key, value)
    net = KEEP(**architecture)
    resources["net"] = net
    checkpoint = torch.load(config["model"], map_location="cpu", weights_only=True)
    state = checkpoint["params_ema"]
    state = {k.replace("cross_fuse", "cfa").replace("fuse_convs_dict", "cft"): v for k, v in state.items()}
    net.load_state_dict(state, strict=True)
    del checkpoint, state
    net = net.eval().to(device=device, dtype=torch.float32)
    sums = np.lib.format.open_memmap(temp / "restored.npy", mode="w+", dtype=np.float32, shape=(count, 512, 512, 3))
    resources["sums"] = sums
    sums[:] = 0
    weights = np.zeros(count, np.float32)
    windows = list(frame_windows(valid, config["chunk_length"], config["overlap"]))
    if not torch.is_inference_mode_enabled():
        raise RuntimeError("KEEP 必须在 ComfyUI 的推理上下文中执行。")
    if windows:
        for number, (start, end) in enumerate(windows):
            tensor = torch.from_numpy(np.ascontiguousarray(aligned[start:end, :, :, ::-1].transpose(0, 3, 1, 2))).float().div_(255).mul_(2).sub_(1).unsqueeze(0).to(device)
            if end - start == 1:
                tensor = torch.cat([tensor, tensor], dim=1)
            prediction = net(tensor, need_upscale=False)[:, :end-start]
            rgb = prediction[0].clamp(-1, 1).add(1).mul(127.5).permute(0, 2, 3, 1).cpu().numpy()
            weight = np.ones(end-start, np.float32)
            overlap = config["overlap"]
            if start and valid[start-1]:
                n = min(overlap, end-start)
                weight[:n] = np.arange(1, n+1) / (n+1)
            if end < count and valid[end]:
                n = min(overlap, end-start)
                if n:
                    weight[-n:] = np.arange(n, 0, -1) / (n+1)
            sums[start:end] += rgb[:, :, :, ::-1] * weight[:, None, None, None]
            weights[start:end] += weight
            del tensor, prediction, rgb
            progress(20 + 55 * (number+1) / len(windows), stage="restoration")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        args = [ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0"]
        if config["preserve_audio"]:
            args += ["-i", config["base_video"], "-map", "0:v:0", "-map", "1:a:0?"]
        if width % 2 or height % 2:
            args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        args += ["-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p"]
        if config["preserve_audio"]:
            with av.open(config["base_video"]) as media:
                audio = next(iter(media.streams.audio), None)
                codec = audio.codec_context.name if audio is not None else ""
            args += ["-c:a", "copy" if codec in {"", "aac", "mp3", "ac3", "eac3", "alac"} else "aac"]
        args += ["-t", str(count / fps), "-movflags", "+faststart", config["output"]]
        error_log = (temp / "encode.log").open("wb")
        encoder = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=error_log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        face_labels = np.asarray([1, 2, 3, 4, 5, 6, 10, 11, 12, 13])
        encoded = 0
        try:
            for index in range(count):
                ok, frame = base.read()
                if not ok:
                    raise ValueError("视频画面提前结束，请重新上传完整视频。")
                if valid[index] and weights[index] > 0:
                    face = np.uint8(np.clip(np.rint(sums[index] / weights[index]), 0, 255))
                    tensor = torch.from_numpy(np.ascontiguousarray(aligned[index, :, :, ::-1].transpose(2, 0, 1))).float().div_(255).unsqueeze(0).to(device)
                    normalize(tensor, (.5, .5, .5), (.5, .5, .5), inplace=True)
                    labels = helper.face_parse(tensor)[0].argmax(dim=1).squeeze().cpu().numpy()
                    mask = np.isin(labels, face_labels).astype(np.float32)
                    mask = cv2.GaussianBlur(cv2.GaussianBlur(mask, (101, 101), 11), (101, 101), 11)
                    mask[:10] = 0; mask[-10:] = 0; mask[:, :10] = 0; mask[:, -10:] = 0
                    inverse = cv2.invertAffineTransform(affine[index])
                    patch = cv2.warpAffine(face, inverse, (width, height), flags=cv2.INTER_LINEAR)
                    alpha = cv2.warpAffine(mask, inverse, (width, height), flags=cv2.INTER_LINEAR)
                    alpha[alpha < 1/255] = 0
                    frame = np.uint8(np.clip(np.rint(frame.astype(np.float32)*(1-alpha[:, :, None]) + patch.astype(np.float32)*alpha[:, :, None]), 0, 255))
                encoder.stdin.write(frame.tobytes())
                encoded += 1
                if index % 12 == 0:
                    progress(76 + 23 * index / count, stage="encoding")
        finally:
            encoder.stdin.close()
            code = encoder.wait()
            error_log.close()
            base.release()
            del aligned, sums
        if code:
            raise RuntimeError((temp / "encode.log").read_text(encoding="utf-8", errors="replace")[-1600:])
    report = {"frames": encoded, "fps": fps, "width": width+width%2, "height": height+height%2,
              "repaired_frames": int(valid.sum()), "unrepaired_frames": int((~valid).sum()),
              "chunk_length": config["chunk_length"], "overlap": config["overlap"],
              "runtime_seconds": round(time.monotonic()-began, 3)}
    progress(100)
    return report
