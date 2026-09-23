"""Measured media intervals and deterministic production export (no LLM calls)."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError("媒体处理失败：" + result.stderr.decode("utf8", errors="replace")[-1200:])
    return result.stdout


def binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"系统未安装 {name}，无法验证媒体与导出成片")
    return path


def probe_file(path: Path) -> dict:
    info = json.loads(run([binary("ffprobe"), "-v", "error", "-count_frames", "-show_streams",
                           "-show_format", "-of", "json", str(path)]))
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("素材没有视频轨")
    fps = float(Fraction(stream.get("avg_frame_rate") or "0"))
    frames = int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0)
    duration = frames / fps if fps > 0 and frames > 0 else float(stream.get("duration") or info["format"]["duration"])
    if duration <= 0:
        raise ValueError("视频时长无效")
    return {"duration": duration, "fps": fps, "frames": frames,
            "width": int(stream["width"]), "height": int(stream["height"]),
            "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", []))}


def measure(content: bytes, units: list[dict]) -> dict:
    with tempfile.TemporaryDirectory(prefix="zly-production-") as directory:
        path = Path(directory) / "input.mp4"
        path.write_bytes(content)
        info = probe_file(path)
    expected = [int(u.get("frame_count") or 0) for u in units]
    verified = len(units) == 1 or (all(n > 0 for n in expected) and sum(expected) == info["frames"] and info["fps"] > 0)
    ranges = {}
    if verified:
        start = 0.0
        for i, u in enumerate(units):
            end = info["duration"] if i == len(units) - 1 else start + expected[i] / info["fps"]
            ranges[str(u["beat_id"])] = {"start": start, "end": end}
            start = end
    return {**info, "verified": verified, "ranges": ranges, "content_sha256": hashlib.sha256(content).hexdigest()}


def assemble(snapshot: dict, fetch_video, fetch_audio, on_progress=None) -> bytes:
    """Freeze clips/audio before enqueue; trim by measured media time, preserve original audio."""
    clips = snapshot["timeline"]
    audio = [a for a in snapshot["audio"] if a.get("enabled", True)]
    with tempfile.TemporaryDirectory(prefix="zly-production-export-") as directory:
        root = Path(directory)
        cached = {}
        outputs = []
        durations = []
        target = None
        for i, clip in enumerate(clips):
            url = clip["url"]
            if url not in cached:
                source = root / f"source-{len(cached)}.mp4"
                source.write_bytes(fetch_video(url))
                cached[url] = (source, probe_file(source))
            source, info = cached[url]
            start = float(clip.get("start") or 0)
            end = float(clip["end"]) if clip.get("end") is not None else info["duration"]
            if start < 0 or end > info["duration"] + .05 or end <= start:
                raise ValueError("采用区间超出实际媒体，必须重新验证素材")
            duration = end - start
            target = target or info
            args = [binary("ffmpeg"), "-v", "error", "-y", "-i", str(source)]
            overlays = [a for a in audio if a["material_id"] == clip["material_id"]
                        and a["start"] >= start and a["end"] <= end + .001]
            filters = [f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
                       f"scale={target['width']}:{target['height']}:force_original_aspect_ratio=decrease,"
                       f"pad={target['width']}:{target['height']}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                       f"fps={target['fps'] or 24}[v]"]
            base = (f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                    "aresample=48000,aformat=channel_layouts=stereo,apad" if info["has_audio"] else
                    "anullsrc=r=48000:cl=stereo")
            for a in overlays:
                if a["mix"] == "replace":
                    base += f",volume=0:enable='between(t,{a['start'] - start},{a['end'] - start})'"
            filters.append(base + f",atrim=duration={duration}[base]")
            audio_labels = ["[base]"]
            for n, a in enumerate(overlays, 1):
                wav = root / f"audio-{i}-{n}.wav"
                wav.write_bytes(fetch_audio(a["audio_url"]))
                # Validate actual decoded audio duration; never silently truncate a line.
                meta = json.loads(run([binary("ffprobe"), "-v", "error", "-show_format", "-of", "json", str(wav)]))
                if float(meta["format"]["duration"]) > a["end"] - a["start"] + .025:
                    raise ValueError("实际配音超出编排区间，请重新对齐")
                args.extend(["-i", str(wav)])
                delay = round((a["start"] - start) * 1000)
                filters.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}:all=1[a{n}]")
                audio_labels.append(f"[a{n}]")
            if overlays:
                filters.append("".join(audio_labels) + f"amix=inputs={len(audio_labels)}:duration=first:normalize=0[a]")
            else:
                filters.append("[base]anull[a]")
            output = root / f"clip-{i}.mp4"
            run(args + ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-t", str(duration), str(output)])
            outputs.append(output)
            durations.append(duration)
            if on_progress:
                on_progress(i + 1, len(clips))
        if not outputs:
            raise ValueError("没有可导出的采用素材")
        if len(outputs) == 1:
            return outputs[0].read_bytes()
        final = root / "final.mp4"
        args = [binary("ffmpeg"), "-v", "error", "-y"]
        for output in outputs:
            args.extend(["-i", str(output)])
        # Decode/trim AAC padding before concatenation: stream-copy would accumulate encoder delay.
        filters = []
        for i, duration in enumerate(durations):
            filters.extend([f"[{i}:v]setpts=PTS-STARTPTS[v{i}]",
                            f"[{i}:a]atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]"])
        filters.append("".join(f"[v{i}][a{i}]" for i in range(len(outputs))) +
                       f"concat=n={len(outputs)}:v=1:a=1[v][a]")
        run(args + ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac",
                    "-movflags", "+faststart", str(final)])
        return final.read_bytes()
