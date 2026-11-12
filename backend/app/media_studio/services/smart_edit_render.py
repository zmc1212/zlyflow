"""CPU FFmpeg export; no model calls and no dependency on ComfyUI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .smart_edit_document import RATIOS, timeline_duration, validate_document, wrap_text

FILTERS = {
    "none": "null", "mono": "hue=s=0", "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "warm": "colorbalance=rs=.08:bs=-.06", "cool": "colorbalance=rs=-.06:bs=.08",
    "vivid": "eq=saturation=1.35:contrast=1.08", "soft": "gblur=sigma=2", "fade": "eq=contrast=.85:brightness=.04:saturation=.8",
}


def run_ffmpeg(arguments: list[str], root: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未安装 FFmpeg，暂时无法导出 MP4")
    result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1", *arguments], cwd=root, capture_output=True, timeout=1800)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[-1800:]
        raise RuntimeError(f"视频导出失败：{detail}")


def probe(path: Path) -> dict:
    binary = shutil.which("ffprobe")
    if not binary:
        raise RuntimeError("系统未安装 ffprobe，无法读取素材信息")
    result = subprocess.run([binary, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=45)
    if result.returncode:
        raise ValueError("无法解码这个素材，请上传常见的视频、图片或音频文件")
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in streams)
    if not video and not audio:
        raise ValueError("文件中没有可用的画面或音频")
    duration = float((data.get("format") or {}).get("duration") or (video or {}).get("duration") or 5)
    return {"duration": max(.04, duration), "width": (video or {}).get("width", 0), "height": (video or {}).get("height", 0), "has_audio": audio, "has_video": bool(video)}


def atempo(speed: float) -> str:
    values = []
    while speed < .5:
        values.append("atempo=0.5")
        speed *= 2
    while speed > 2:
        values.append("atempo=2")
        speed /= 2
    values.append(f"atempo={speed:g}")
    return ",".join(values)


def audio_filters(clip: dict, duration: float | None = None, head_fade: float = 0.0, tail_fade: float = 0.0) -> str:
    """Audio chain for one clip; auto fades come from transitions and never shrink user fades."""
    duration = clip["duration"] if duration is None else duration
    speed = clip["speed"]
    fade_in = max(float(clip["fade_in"]), head_fade)
    fade_out = max(float(clip["fade_out"]), tail_fade)
    filters = ["asetpts=PTS-STARTPTS", atempo(speed), f"volume={0 if clip['muted'] else clip['volume']:g}", "aresample=48000", "aformat=channel_layouts=stereo", "apad", f"atrim=duration={duration:.8f}"]
    if fade_in:
        filters.append(f"afade=t=in:d={fade_in:g}")
    if fade_out:
        filters.append(f"afade=t=out:st={max(0, duration - fade_out):.8f}:d={fade_out:g}")
    return ",".join(filters)


def caption_image(clip: dict, width: int, height: int, font_path: Path, output: Path) -> Path:
    """Use explicit centered line boxes, independent of FFmpeg font line metrics."""
    font_size = clip["font_size"] * width / 1920
    font = ImageFont.truetype(str(font_path), max(1, round(font_size)))
    lines = wrap_text(clip["text"], clip["font_size"]).split("\n")
    widths = [font.getlength(line) for line in lines]
    line_height, pad_x, pad_y = font_size * 1.4, font_size * .4, font_size * .2
    block_width = max(widths, default=0) + pad_x * 2
    block_height = len(lines) * line_height + pad_y * 2
    left = width * (.5 + clip["x"] / 100) - block_width / 2
    top = height * (.5 + clip["y"] / 100) - block_height / 2
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, top, left + block_width, top + block_height), fill=(0, 0, 0, 119))
    for index, (line, text_width) in enumerate(zip(lines, widths)):
        if not line:
            continue
        bbox = font.getbbox(line)
        y = top + pad_y + index * line_height + (line_height - (bbox[3] - bbox[1])) / 2 - bbox[1]
        if y > height + font_size or y < -font_size * 2:
            continue
        draw.text((left + (block_width - text_width) / 2, y), line, font=font, fill=clip["color"])
    image.save(output)
    return output


def _render_workers() -> int:
    try:
        configured = int(os.environ.get("ZLY_SMART_EDIT_RENDER_WORKERS", "2"))
    except ValueError:
        configured = 2
    return max(1, min(4, configured))


def _dip_color(transition: str) -> str:
    return "#ffffff" if transition == "white" else "#000000"


def _video_segments(doc: dict, duration: float) -> list[dict]:
    """Timeline slices: real video clips plus a background fill for every gap."""
    segments: list[dict] = []
    cursor = 0.0
    for clip in sorted((c for c in doc["clips"] if c["track"] == "video"), key=lambda c: c["start"]):
        if clip["start"] - cursor > .001:
            segments.append({"start": cursor, "duration": clip["start"] - cursor})
        segments.append(clip)
        cursor = clip["start"] + clip["duration"]
    if duration - cursor > .001:
        segments.append({"start": cursor, "duration": duration - cursor})
    return segments


def _group_units(segments: list[dict]) -> list[dict]:
    """Join clips connected by dissolve transitions into one render unit each.

    Background gap segments and dip/hard-cut boundaries always start a new unit.
    """
    units: list[dict] = []
    for segment in segments:
        if "track" not in segment:
            units.append({"start": segment["start"], "duration": segment["duration"], "clips": []})
            continue
        if (units and units[-1]["clips"] and segment.get("transition") == "dissolve"
                and abs(units[-1]["start"] + units[-1]["duration"] - segment["start"]) <= .001):
            units[-1]["clips"].append(segment)
            units[-1]["duration"] += segment["duration"]
        else:
            units.append({"start": segment["start"], "duration": segment["duration"], "clips": [segment]})
    return units


def render_document(document: dict, root: Path, resolve: Callable[[dict, Path], Path], progress: Callable[[int], None] = lambda _: None, quality: int = 1080) -> Path:
    doc = validate_document(document)
    duration = timeline_duration(doc)
    if not duration:
        raise ValueError("时间线为空，请先添加素材或文字")
    width, height = RATIOS[doc["settings"]["ratio"]]
    width, height = (round(value * quality / 1080 / 2) * 2 for value in (width, height))
    fps, background = doc["settings"]["fps"], doc["settings"]["background"]
    by_asset = {a["id"]: a for a in doc["assets"]}
    paths, metadata = {}, {}
    used = {c["asset_id"] for c in doc["clips"] if c["track"] != "text"}
    for index, asset_id in enumerate(sorted(used)):
        paths[asset_id] = resolve(by_asset[asset_id], root / f"source-{index}.media")
        metadata[asset_id] = probe(paths[asset_id])
        progress(5 + int(20 * (index + 1) / max(1, len(used))))
    video_clips = sorted((c for c in doc["clips"] if c["track"] == "video"), key=lambda c: c["start"])
    next_video = {video_clips[i]["id"]: video_clips[i + 1] for i in range(len(video_clips) - 1)}
    text_clips = sorted((c for c in doc["clips"] if c["track"] == "text"), key=lambda c: c["start"])
    font_candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc", Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), Path("/System/Library/Fonts/PingFang.ttc"), Path("/System/Library/Fonts/Supplemental/Songti.ttc"), Path("/Library/Fonts/Arial Unicode.ttf")]
    font = next((path for path in font_candidates if path.exists()), None)
    if text_clips and not font:
        raise RuntimeError("缺少中文字体，请安装 Noto Sans CJK 或微软雅黑后重试")
    caption_paths: dict[str, Path] = {}
    for index, clip in enumerate(text_clips):
        caption_paths[clip["id"]] = caption_image(clip, width, height, font, root / f"caption-{index}.png")

    def unit_dips(unit: dict) -> tuple[float, str | None, float, str | None]:
        """(head seconds, head colour, tail seconds, tail colour) of a unit."""
        clips = unit["clips"]
        head = tail = 0.0
        head_color = tail_color = None
        if clips:
            first, last = clips[0], clips[-1]
            if first.get("transition") in {"black", "white"}:
                head = first["transition_duration"] / 2
                head_color = _dip_color(first["transition"])
            following = next_video.get(last["id"])
            if following and following.get("transition") in {"black", "white"} \
                    and abs(unit["start"] + unit["duration"] - following["start"]) <= .001:
                tail = following["transition_duration"] / 2
                tail_color = _dip_color(following["transition"])
        return head, head_color, tail, tail_color

    def render_unit(index: int, unit: dict, target: Path) -> None:
        start, unit_duration = unit["start"], unit["duration"]
        clips = unit["clips"]
        arguments: list[str] = []
        graph: list[str] = []
        base = f"color=c={background}:s={width}x{height}:r={fps}:d={unit_duration:.8f}"
        head_dip, head_dip_color, tail_dip, tail_dip_color = unit_dips(unit)
        picture_label = "v"
        if not clips:
            graph = [f"{base},format=yuv420p[v]", f"anullsrc=r=48000:cl=stereo,atrim=duration={unit_duration:.8f}[a]"]
        else:
            chain = len(clips) > 1
            picture_label = "bg"
            graph.append(f"{base}[bg]")
            for position, clip in enumerate(clips):
                length = clip["duration"]
                offset = sum(item["duration"] for item in clips[:position])
                # Inside a unit every incoming transition is a dissolve; the
                # extension lets the previous picture keep playing underneath.
                dissolve_in = clip["transition_duration"] if position and clip.get("transition") == "dissolve" else 0.0
                dissolve_out = clips[position + 1]["transition_duration"] if chain and position + 1 < len(clips) else 0.0
                ext = length + dissolve_out
                asset = by_asset[clip["asset_id"]]
                info = metadata[asset["id"]]
                if not info["has_video"]:
                    raise ValueError(f"素材「{asset['name']}」缺少画面")
                if asset["kind"] != "image" and clip["in_point"] + length * clip["speed"] > info["duration"] + .12:
                    raise ValueError(f"素材「{asset['name']}」实际时长不足，请重新导入后裁切")
                arguments += ["-loop", "1"] if asset["kind"] == "image" else ["-ss", f"{clip['in_point']:.8f}"]
                arguments += ["-i", str(paths[asset["id"]])]
                scaled_w = max(2, round(width * clip["scale"] / 2) * 2)
                scaled_h = max(2, round(height * clip["scale"] / 2) * 2)
                visual = [f"setpts=(PTS-STARTPTS)/{clip['speed']:g}", f"fps={fps}",
                          f"tpad=stop_mode=clone:stop_duration={max(0.12, ext - length + 0.12):.8f}",
                          f"trim=duration={ext:.8f}",
                          f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={background}", "setsar=1",
                          FILTERS[clip["effect"]], f"scale={scaled_w}:{scaled_h}", "format=rgba",
                          f"colorchannelmixer=aa={clip['opacity']:g}"]
                if clip["rotation"]:
                    visual.append(f"rotate={clip['rotation']:g}*PI/180:ow=rotw({clip['rotation']:g}*PI/180):oh=roth({clip['rotation']:g}*PI/180):c=none")
                if position and dissolve_in:
                    fade_in = max(clip["fade_in"], dissolve_in)
                    visual.append(f"fade=t=in:d={fade_in:g}:alpha=1")
                elif clip["fade_in"]:
                    visual.append(f"fade=t=in:d={clip['fade_in']:g}:alpha=1")
                if clip["fade_out"]:
                    visual.append(f"fade=t=out:st={length-clip['fade_out']:.8f}:d={clip['fade_out']:g}:alpha=1")
                if position:
                    visual.append(f"setpts=PTS-STARTPTS+{offset:.8f}/TB")
                picture = f"picture{position}"
                graph.append(f"[{position}:v]{','.join(visual)}[{picture}]")
                overlay = f"[{picture_label}][{picture}]overlay=x=(W-w)/2+{width*clip['x']/100:g}:y=(H-h)/2+{height*clip['y']/100:g}"
                if position:
                    overlay += f":enable='gte(t,{offset:.8f})'"
                else:
                    overlay += ":shortest=1" if not chain else ""
                picture_label = f"composite{position}"
                graph.append(f"{overlay}[{picture_label}]")
            # Audio: each clip's own track is faded in/out across the transition
            # windows, delayed to its unit offset and mixed into one lane.
            for position, clip in enumerate(clips):
                length = clip["duration"]
                offset = sum(item["duration"] for item in clips[:position])
                dissolve_out = clips[position + 1]["transition_duration"] if chain and position + 1 < len(clips) else 0.0
                ext = length + dissolve_out
                asset = by_asset[clip["asset_id"]]
                info = metadata[asset["id"]]
                head_auto = clip["transition_duration"] if position and clip.get("transition") == "dissolve" else 0.0
                if position == 0 and head_dip:
                    head_auto = max(head_auto, head_dip)
                tail_auto = dissolve_out
                if position == len(clips) - 1 and tail_dip:
                    tail_auto = max(tail_auto, tail_dip)
                if info["has_audio"] and asset["kind"] != "image":
                    graph.append(f"[{position}:a]{audio_filters(clip, ext, head_auto, tail_auto)}[a{position}]")
                else:
                    graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={ext:.8f}[a{position}]")
                graph.append(f"[a{position}]adelay={round(offset*1000)}:all=1[d{position}]")
            mixed = "".join(f"[d{position}]" for position in range(len(clips))) + f"amix=inputs={len(clips)}:duration=longest:normalize=0"
            if chain:
                mixed += ",alimiter=limit=.95"
            mixed += f",apad,atrim=duration={unit_duration:.8f}[a]"
            graph.append(mixed)
        # Solid-colour dip layers fade the picture to black/white and back
        # without overlapping the timeline; only unit edges can carry them.
        if head_dip and clips:
            f = head_dip
            graph.append(f"color=c={head_dip_color}:s={width}x{height}:r={fps}:d={f:.8f},fade=t=out:st=0:d={f:.8f}:alpha=1[dip-head]")
            graph.append(f"[{picture_label}][dip-head]overlay=enable='lt(t,{f:.8f})'[dipped-head]")
            picture_label = "dipped-head"
        if tail_dip and clips:
            window = unit_duration - tail_dip
            graph.append(f"color=c={tail_dip_color}:s={width}x{height}:r={fps}:d={tail_dip:.8f},fade=t=in:st=0:d={tail_dip:.8f}:alpha=1,setpts=PTS-STARTPTS+{window:.8f}/TB[dip-tail]")
            graph.append(f"[{picture_label}][dip-tail]overlay=enable='gte(t,{window:.8f})'[dipped-tail]")
            picture_label = "dipped-tail"
        # Captions are burned into every unit they overlap, in unit-local time.
        overlapping = [clip for clip in text_clips
                       if clip["start"] < start + unit_duration - .001 and clip["start"] + clip["duration"] > start + .001]
        for caption_index, clip in enumerate(overlapping):
            arguments += ["-loop", "1", "-framerate", str(fps), "-i", str(caption_paths[clip["id"]])]
            input_index = len(clips) + caption_index if clips else caption_index
            label = f"caption{caption_index}"
            local_start, local_end = clip["start"] - start, clip["start"] + clip["duration"] - start
            filters = ["format=rgba", f"colorchannelmixer=aa={clip['opacity']:g}"]
            # A caption may straddle the unit boundary: fade windows that started
            # before the unit are clamped, never negative.
            if clip["fade_in"] and local_start >= 0:
                filters.append(f"fade=t=in:st={local_start:.8f}:d={clip['fade_in']:g}:alpha=1")
            if clip["fade_out"]:
                fade_out_start = local_end - clip["fade_out"]
                if fade_out_start >= 0:
                    filters.append(f"fade=t=out:st={fade_out_start:.8f}:d={clip['fade_out']:g}:alpha=1")
                elif local_end > 0:
                    filters.append(f"fade=t=out:st=0:d={local_end:.8f}:alpha=1")
            graph.append(f"[{input_index}:v]{','.join(filters)}[{label}]")
            graph.append(f"[{picture_label}][{label}]overlay=x=0:y=0:shortest=1:enable='gte(t,{local_start:.8f})*lt(t,{local_end:.8f})'[t{caption_index}]")
            picture_label = f"t{caption_index}"
        run_ffmpeg([*arguments, "-filter_complex", ";".join(graph), "-map", f"[{picture_label}]", "-map", "[a]",
                    "-t", f"{unit_duration:.8f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-threads", "2", "-c:a", "aac", "-ar", "48000", "-video_track_timescale", "90000", str(target)], root)

    units = _group_units(_video_segments(doc, duration))
    files: list[Path] = []
    if units:
        failures: list[BaseException | None] = [None] * len(units)
        done = 0
        progress(25)

        def render_one(item) -> None:
            index, unit = item
            try:
                render_unit(index, unit, root / f"part-{index:04d}.mp4")
            except BaseException as error:  # noqa: BLE001 - re-raised below
                failures[index] = error

        workers = min(_render_workers(), len(units))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="smart-edit-unit") as pool:
            futures = [pool.submit(render_one, item) for item in enumerate(units)]
            for future in as_completed(futures):
                future.result()
                done += 1
                progress(25 + int(65 * done / len(units)))
        failure = next((error for error in failures if error is not None), None)
        if failure is not None:
            raise failure
        files = [root / f"part-{index:04d}.mp4" for index in range(len(units))]
    (root / "concat.txt").write_text("".join(f"file '{path.name}'\n" for path in files), encoding="utf-8")
    assembled = root / "assembled.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", str(assembled)], root)
    progress(92)
    output = root / "final.mp4"
    soundtracks = [c for c in doc["clips"] if c["track"] in {"audio", "music"}]
    if soundtracks:
        arguments = ["-i", str(assembled)]
        graph, sound_labels = [], ["[0:a]"]
        for index, clip in enumerate(soundtracks):
            arguments += ["-ss", f"{clip['in_point']:.8f}", "-i", str(paths[clip["asset_id"]])]
            graph.append(f"[{index+1}:a]{audio_filters(clip)},adelay={round(clip['start']*1000)}:all=1[s{index}]")
            sound_labels.append(f"[s{index}]")
        graph.append(f"{''.join(sound_labels)}amix=inputs={len(sound_labels)}:duration=longest:normalize=0,alimiter=limit=.95,apad,atrim=duration={duration:.8f}[audio]")
        run_ffmpeg([*arguments, "-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[audio]",
                    "-t", f"{duration:.8f}", "-c:v", "copy", "-c:a", "aac", "-ar", "48000",
                    "-movflags", "+faststart", str(output)], root)
    else:
        run_ffmpeg(["-i", str(assembled), "-c", "copy", "-movflags", "+faststart", str(output)], root)
    progress(95)
    return output


def export_otio(document: dict, media_names: dict[str, str] | None = None) -> dict:
    doc = validate_document(document)
    fps = doc["settings"]["fps"]
    by_asset = {a["id"]: a for a in doc["assets"]}
    def time(value):
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": round(value * fps)}
    def span(start, duration):
        return {"OTIO_SCHEMA": "TimeRange.1", "start_time": time(start), "duration": time(duration)}
    tracks = []
    for lane in ("video", "audio", "music", "text"):
        children, cursor = [], 0.0
        for clip in sorted((c for c in doc["clips"] if c["track"] == lane), key=lambda c: c["start"]):
            if clip["start"] > cursor + .001:
                children.append({"OTIO_SCHEMA": "Gap.1", "source_range": span(0, clip["start"] - cursor)})
            asset = by_asset.get(clip.get("asset_id"))
            media = {"OTIO_SCHEMA": "ExternalReference.1", "target_url": (media_names or {}).get(asset["id"], asset["url"]), "available_range": span(0, asset["duration"])} if asset else {"OTIO_SCHEMA": "MissingReference.1"}
            children.append({"OTIO_SCHEMA": "Clip.2", "name": asset["name"] if asset else clip["text"], "media_references": {"DEFAULT_MEDIA": media}, "active_media_reference_key": "DEFAULT_MEDIA", "source_range": span(clip["in_point"], clip["duration"] * clip["speed"]), "effects": [{"OTIO_SCHEMA": "LinearTimeWarp.1", "name": "Speed", "effect_name": "LinearTimeWarp", "time_scalar": clip["speed"]}] if clip["speed"] != 1 else [], "metadata": {"zly_smart_edit": clip}})
            cursor = clip["start"] + clip["duration"]
        tracks.append({"OTIO_SCHEMA": "Track.1", "name": {"video": "画面", "audio": "配音", "music": "音乐", "text": "文字"}[lane], "kind": "Audio" if lane in {"audio", "music"} else "Video", "children": children})
    return {"OTIO_SCHEMA": "Timeline.1", "name": doc["name"], "global_start_time": time(0), "tracks": {"OTIO_SCHEMA": "Stack.1", "children": tracks}, "metadata": {"zly_smart_edit": doc}}


def export_xml(document: dict, media_names: dict[str, str] | None = None) -> bytes:
    doc = validate_document(document)
    fps, duration = doc["settings"]["fps"], timeline_duration(doc)
    width, height = RATIOS[doc["settings"]["ratio"]]
    assets = {a["id"]: a for a in doc["assets"]}
    root = ET.Element("xmeml", version="5")
    seq = ET.SubElement(root, "sequence", id="zly-sequence")
    def value(parent, key, content):
        ET.SubElement(parent, key).text = str(content)
    def rate(parent):
        r = ET.SubElement(parent, "rate")
        value(r, "timebase", fps)
        value(r, "ntsc", "FALSE")
    value(seq, "name", doc["name"])
    value(seq, "duration", round(duration * fps))
    rate(seq)
    media = ET.SubElement(seq, "media")
    video, audio = ET.SubElement(media, "video"), ET.SubElement(media, "audio")
    sample = ET.SubElement(ET.SubElement(video, "format"), "samplecharacteristics")
    value(sample, "width", width)
    value(sample, "height", height)
    value(sample, "pixelaspectratio", "square")
    rate(sample)
    lanes = [(ET.SubElement(video, "track"), "video", False), (ET.SubElement(audio, "track"), "video", True), (ET.SubElement(audio, "track"), "audio", True), (ET.SubElement(audio, "track"), "music", True)]
    for lane, track, is_audio in lanes:
        for clip in sorted((c for c in doc["clips"] if c["track"] == track), key=lambda c: c["start"]):
            asset = assets[clip["asset_id"]]
            if is_audio and (asset["kind"] == "image" or (track == "video" and asset.get("has_audio") is False)):
                continue
            item = ET.SubElement(lane, "clipitem", id=clip["id"] + ("-a" if is_audio else "-v"))
            value(item, "name", asset["name"])
            value(item, "enabled", "FALSE" if is_audio and clip["muted"] else "TRUE")
            rate(item)
            for key, seconds in (("start", clip["start"]), ("end", clip["start"] + clip["duration"]), ("in", clip["in_point"]), ("out", clip["in_point"] + clip["duration"] * clip["speed"]), ("duration", asset["duration"])):
                value(item, key, round(seconds * fps))
            file = ET.SubElement(item, "file", id="file-" + asset["id"] + ("-a" if is_audio else "-v"))
            value(file, "name", asset["name"])
            value(file, "pathurl", (media_names or {}).get(asset["id"], asset["url"]))
            rate(file)
            value(file, "duration", round(asset["duration"] * fps))
            filemedia = ET.SubElement(file, "media")
            characteristics = ET.SubElement(ET.SubElement(filemedia, "audio" if is_audio else "video"), "samplecharacteristics")
            if is_audio:
                value(characteristics, "samplerate", 48000)
                value(characteristics, "channelcount", 2)
            else:
                value(characteristics, "width", asset.get("width") or width)
                value(characteristics, "height", asset.get("height") or height)
                rate(characteristics)
            sourcetrack = ET.SubElement(item, "sourcetrack")
            value(sourcetrack, "mediatype", "audio" if is_audio else "video")
            value(sourcetrack, "trackindex", 1)
            if clip["speed"] != 1:
                effect = ET.SubElement(ET.SubElement(item, "filter"), "effect")
                for key, content in (("name", "Time Remap"), ("effectid", "timeremap"), ("effectcategory", "motion"), ("effecttype", "motion"), ("mediatype", "video")):
                    value(effect, key, content)
                parameter = ET.SubElement(effect, "parameter")
                value(parameter, "parameterid", "speed")
                value(parameter, "name", "speed")
                value(parameter, "value", clip["speed"] * 100)
            if is_audio:
                effect = ET.SubElement(ET.SubElement(item, "filter"), "effect")
                value(effect, "name", "Audio Levels")
                value(effect, "effectid", "audiolevels")
                value(effect, "effecttype", "audiolevels")
                value(effect, "mediatype", "audio")
                parameter = ET.SubElement(effect, "parameter")
                value(parameter, "parameterid", "level")
                value(parameter, "value", 0 if clip["muted"] else clip["volume"])
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="utf-8")


def export_jianying(document: dict, media_names: dict[str, str] | None = None) -> tuple[dict, dict]:
    """Basic draft adapter, following this repo's jianying-draft-builder.ts.

    Proprietary effects/text are deliberately left in the lossless ZLY sidecar.
    Actual compatibility still depends on the installed Jianying version.
    """
    doc = validate_document(document)
    width, height = RATIOS[doc["settings"]["ratio"]]
    materials: dict[str, list] = {key: [] for key in ("videos", "audios", "speeds", "canvases", "transitions", "stickers", "texts", "effects")}
    by_asset = {a["id"]: a for a in doc["assets"]}
    tracks = []
    for lane in ("video", "audio", "music"):
        segments = []
        for clip in sorted((c for c in doc["clips"] if c["track"] == lane), key=lambda c: c["start"]):
            asset = by_asset[clip["asset_id"]]
            material_id, speed_id, canvas_id = (uuid.uuid4().hex for _ in range(3))
            material = {"id": material_id, "material_name": asset["name"], "path": (media_names or {}).get(asset["id"], asset["url"]), "duration": round(asset["duration"] * 1_000_000), "type": "photo" if asset["kind"] == "image" else "video" if lane == "video" else "music" if lane == "music" else "extract_music", "is_ai_generate_content": False}
            if lane == "video":
                material.update(width=asset.get("width") or width, height=asset.get("height") or height, crop_ratio="free", crop_scale=1, crop={"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0, "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1})
                materials["canvases"].append({"id": canvas_id, "type": "canvas_color", "color": doc["settings"]["background"], "blur": 0, "image": "", "image_id": ""})
            materials["videos" if lane == "video" else "audios"].append(material)
            materials["speeds"].append({"id": speed_id, "type": "speed", "mode": 0, "speed": clip["speed"], "curve_speed": None})
            segments.append({"id": clip["id"], "material_id": material_id, "source_timerange": {"start": round(clip["in_point"] * 1_000_000), "duration": round(clip["duration"] * clip["speed"] * 1_000_000)}, "target_timerange": {"start": round(clip["start"] * 1_000_000), "duration": round(clip["duration"] * 1_000_000)}, "speed": clip["speed"], "volume": 0 if clip["muted"] else clip["volume"], "extra_material_refs": [speed_id, canvas_id] if lane == "video" else [speed_id], "render_index": 0, "enable_adjust": True, "clip": {"alpha": clip["opacity"], "rotation": clip["rotation"], "scale": {"x": clip["scale"], "y": clip["scale"]}, "transform": {"x": clip["x"] / 50, "y": -clip["y"] / 50}, "flip": {"horizontal": False, "vertical": False}}})
        tracks.append({"id": uuid.uuid4().hex, "type": "video" if lane == "video" else "audio", "name": {"video": "主视频轨", "audio": "配音", "music": "音乐"}[lane], "attribute": 0, "flag": 0, "is_default_name": True, "segments": segments})
    draft_id = uuid.uuid4().hex
    meta = {"draft_id": draft_id, "draft_name": doc["name"], "draft_fold_path": "", "draft_root_path": "", "draft_timeline_materials_size_": 0, "draft_removable_storage_device": ""}
    content = {"id": draft_id, "version": 3000000, "fps": doc["settings"]["fps"], "duration": round(timeline_duration(doc) * 1_000_000), "canvas_config": {"width": width, "height": height, "ratio": doc["settings"]["ratio"]}, "materials": materials, "tracks": tracks}
    return meta, content
