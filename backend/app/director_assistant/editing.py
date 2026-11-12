"""Deterministic editing proposals shared by shortcuts and the language assistant."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid

from .repository import AssistantConflict, AssistantNotFound, dumps
from ..media_studio.services import smart_edit_service
from ..media_studio.services.project_detail_service import ProjectDetailService
from ..media_studio.services.smart_edit_document import empty_document, validate_document

OPERATION_TITLES = {
    "video_arrange": "智能铺轨",
    "subtitle_arrange": "自动字幕",
    "audio_subtitle": "音轨字幕",
    "subtitle_translate": "字幕翻译",
    "dialogue_cut": "对白精剪",
    "quick_cut": "成片速剪",
    "highlight_cut": "高光合集",
    "hook_cut": "引流剪辑",
}
CUT_OPERATIONS = {"dialogue_cut", "quick_cut", "highlight_cut", "hook_cut"}
HOOK_STRATEGIES = {
    "conflict_3s": {"label": "3秒进冲突", "principle": "从冲突起刀，丢掉开场铺垫和不重要的剧情；超过 1 分钟压到约 30 秒。"},
    "climax_only": {"label": "只留高潮", "principle": "只留理解分最高的高光场次，不讲完整故事。"},
    "quote_open": {"label": "金句开场", "principle": "先出最重要的对白金句，再接其余对白高光。"},
    "ending_hook": {"label": "结尾悬念", "principle": "只留后半段高光，掐掉结局收束。"},
    "trailer": {"label": "预告片", "principle": "爆点冷开，金句对切，结尾不给答案。"},
}
HIGHLIGHT_TERMS = (
    "冲突", "高潮", "反转", "爆点", "危机", "决战", "打斗", "追逐", "真相", "告白",
    "离别", "牺牲", "崩溃", "觉醒", "决裂", "生死", "高光", "钩子", "悬念", "救",
)
SUBTITLE_FONT = {"16:9": 56, "9:16": 46, "1:1": 52, "4:3": 52, "3:4": 50}
CAPTION_BREAKS = "，。！？；：、,.!?;: "
MAX_DOCUMENT_CLIPS = 200
AUDIO_CAPTION_MAX_CHARS = 30
AUDIO_CAPTION_MAX_SECONDS = 5.0
AUDIO_CAPTION_MIN_CHARS = 4
AUDIO_CAPTION_MIN_SECONDS = 0.35
SUBTITLE_TRANSLATE_BATCH = 40
SUBTITLE_TRANSLATE_SYSTEM = (
    "你是专业的影视字幕译者。把输入 JSON 中 lines 数组里的每条字幕文本翻译成简体中文："
    "忠实原意、口语自然、适合直接显示在视频画面上；保留说话人前缀和语气，人名使用通行中文译名；"
    "不添加解释、注释或多余引号；不合并、不拆分、不遗漏条目；"
    '只输出一个 JSON 对象 {"lines":["第一条译文","第二条译文"]}，条数和顺序与输入完全一致。'
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
TRANSCRIPT_MISSING_FALLBACK = "没有可用的音轨转写结果，请先转写音频并等待完成"
TRANSCRIPT_MISSING_MESSAGES = {
    "missing": "还没有音轨转写结果，请先转写音频后再生成音轨字幕",
    "stale": "时间线素材已变化，上一次音轨转写结果已过期，请重新转写",
    "queued": "音频转写正在进行，请等待完成后再生成音轨字幕",
    "running": "音频转写正在进行，请等待完成后再生成音轨字幕",
    "failed": "上一次音轨转写没有成功，请重新转写后再生成音轨字幕",
    "partial": "转写结果里没有可用的语音段落，请重新转写后再生成音轨字幕",
    "empty": "音轨里没有识别到语音，无法生成音轨字幕；需要按剧本铺字请改用「自动字幕」",
}


def document_hash(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _frame(seconds: float, fps: int) -> float:
    return math.floor(max(0.0, seconds) * fps + 1e-7) / fps


def _line_text(line: dict) -> str:
    return str(line.get("text") or "").strip()


def _line_seconds(line: dict) -> float:
    try:
        value = float(line.get("duration_sec") or line.get("duration") or 0)
    except (TypeError, ValueError):
        value = 0
    if not math.isfinite(value) or value <= 0:
        value = max(0.8, len(_line_text(line)) / 4.5)
    return min(30.0, max(0.4, value))


def _needs_chinese_translation(text: str) -> bool:
    """Japanese/Korean and latin-only captions need translating; CJK-only lines are already Chinese."""
    if _KANA_RE.search(text) or _HANGUL_RE.search(text):
        return True
    if _CJK_RE.search(text):
        return False
    return bool(_LATIN_RE.search(text))


def _beat_duration(beat: dict) -> float:
    try:
        value = float(beat.get("duration_sec") or beat.get("video_duration") or beat.get("duration") or 8)
    except (TypeError, ValueError):
        value = 8
    return min(120.0, max(0.5, value))


def _beat_dialogue(beat: dict) -> list[dict]:
    lines = [line for line in (beat.get("dubbing_lines") or []) if isinstance(line, dict) and _line_text(line)]
    if lines:
        return lines
    raw = str(beat.get("dialogue") or "").strip()
    return [{"text": part.strip()} for part in raw.replace("\r", "\n").split("\n") if part.strip()] if raw else []


def _beat_text(beat: dict) -> str:
    values = [
        beat.get("heading"), beat.get("title"), beat.get("scene"), beat.get("action"),
        beat.get("description"), beat.get("narration"), beat.get("script_text"),
    ]
    values.extend(_line_text(line) for line in _beat_dialogue(beat))
    return " ".join(str(value or "") for value in values)


def _beat_score_detail(beat: dict) -> tuple[float, list[str]]:
    text = _beat_text(beat)
    hits = [term for term in HIGHLIGHT_TERMS if term in text]
    dialogue = sum(_line_seconds(line) for line in _beat_dialogue(beat))
    score = len(hits) * 3.0 + min(6.0, dialogue * 0.4) + min(2.0, len(text) / 160.0)
    reasons = []
    if hits:
        reasons.append("冲突/高光：" + "、".join(hits[:4]))
    if dialogue:
        reasons.append(f"对白 {dialogue:.1f} 秒")
    if len(text) >= 160:
        reasons.append("剧情信息量高")
    return round(score, 2), reasons or ["常规叙事镜头"]


def _beat_score(beat: dict) -> float:
    return _beat_score_detail(beat)[0]


def _apply_understanding(meta: list[dict], understanding: dict[str, dict] | None) -> None:
    for item in meta:
        evidence = (understanding or {}).get(item["beat_id"])
        if not evidence:
            continue
        text = " ".join(filter(None, [
            str(evidence.get("description") or "").strip(),
            str(evidence.get("camera") or "").strip(),
            " ".join(str(subject.get("name") or "") for subject in evidence.get("subjects") or []),
        ])).strip()
        if not text:
            continue
        item["visual"] = text[:400]
        hits = [term for term in HIGHLIGHT_TERMS if term in text]
        if hits:
            item["score"] = round(item["score"] + min(6.0, len(hits) * 2.0), 2)
            item["reasons"] = ["画面理解：" + "、".join(hits[:4]), *item["reasons"]]
        else:
            item["reasons"] = ["画面理解：" + text[:60], *item["reasons"]]


def _video_by_beat(sources: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for source in sources:
        beat = source.get("beat_id")
        if source.get("kind") == "video" and beat and beat not in result:
            result[str(beat)] = source
    return result


def _audio_by_beat(sources: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for source in sources:
        beat = source.get("beat_id")
        if source.get("kind") == "audio" and beat:
            result.setdefault(str(beat), []).append(source)
    return result


def _add_assets(doc: dict, assets: list[dict]) -> None:
    known = {asset["id"] for asset in doc["assets"]}
    for asset in assets:
        if asset["id"] not in known:
            doc["assets"].append(dict(asset))
            known.add(asset["id"])


def arrange_videos(document: dict, sources: list[dict], *, free=False, asset_ids: list[str] | None = None) -> dict:
    doc = validate_document(document)
    assets = {a["id"]: a for a in doc["assets"]}
    ordered = []
    if not free:
        for source in sources:
            if source["kind"] != "video":
                continue
            asset = assets.get(source["id"])
            if asset is None:
                asset = dict(source)
                doc["assets"].append(asset)
                assets[asset["id"]] = asset
            ordered.append(asset)
    source_ids = {a["id"] for a in ordered}
    ordered.extend(a for a in doc["assets"] if a["kind"] == "video" and a["id"] not in source_ids and (free or not a.get("beat_id")))
    if asset_ids is not None:
        selected = []
        for asset_id in asset_ids:
            asset = assets.get(asset_id)
            if asset is None:
                asset = next((dict(source) for source in sources if source.get("id") == asset_id and source.get("kind") == "video"), None)
                if asset is None:
                    raise ValueError("铺轨清单包含不存在的视频，请重新读取素材")
                doc["assets"].append(asset)
                assets[asset["id"]] = asset
            selected.append(asset)
        ordered = selected
    used = [assets[c["asset_id"]] for c in doc["clips"] if c["track"] == "video" and assets[c["asset_id"]]["kind"] == "video"]
    ids, urls = {a["id"] for a in used}, {a["url"] for a in used}
    beats = {a["beat_id"] for a in used if a.get("beat_id")}
    fps = doc["settings"]["fps"]
    cursor = round(max((c["start"] + c["duration"] for c in doc["clips"] if c["track"] == "video"), default=0) * fps)
    start, items, skipped = cursor / fps, [], 0
    for asset in ordered:
        beat = asset.get("beat_id")
        if asset["id"] in ids or asset["url"] in urls or (beat and beat in beats):
            skipped += 1
            continue
        frames = math.floor(float(asset["duration"]) * fps + 1e-7)
        if frames < 1:
            raise ValueError(f"{asset['name']}时长不足一帧，请重新导入素材")
        clip = {"id": uuid.uuid4().hex, "asset_id": asset["id"], "track": "video",
                "start": cursor / fps, "duration": frames / fps, "in_point": 0, "speed": 1,
                "muted": False, "volume": 1}
        doc["clips"].append(clip)
        items.append({"asset_id": asset["id"], "name": asset["name"], "start": clip["start"], "duration": clip["duration"]})
        cursor += frames
        ids.add(asset["id"]); urls.add(asset["url"])
        if beat:
            beats.add(beat)
    missing = len({a["beat_id"] for a in sources if a["kind"] == "image" and a.get("beat_id")}) if not free else 0
    return {"document": validate_document(doc), "items": items, "count": len(items), "skipped_count": skipped,
            "missing_video_count": missing, "append_at": start, "total_duration": (cursor / fps - start)}


def place_subtitles(document: dict, beats: list[dict]) -> dict:
    """Lay dialogue text on the caption lane using the dubbing timings already in the episode."""
    doc = validate_document(document)
    if not beats:
        raise ValueError("自动字幕需要分集对白数据，请先选择具体分集")
    fps = doc["settings"]["fps"]
    assets = {asset["id"]: asset for asset in doc["assets"]}
    visual: dict[str, dict] = {}
    for clip in sorted(doc["clips"], key=lambda item: (item["start"], item["duration"])):
        if clip["track"] != "video":
            continue
        beat_id = assets.get(clip.get("asset_id") or "", {}).get("beat_id")
        if beat_id and str(beat_id) not in visual:
            visual[str(beat_id)] = clip
    if not visual:
        raise ValueError("时间线还没有分集成片，请先智能铺轨或完成本集视频")
    manual = [clip for clip in doc["clips"] if clip["track"] == "text" and clip.get("origin") != "auto_subtitle"]
    auto = [clip for clip in doc["clips"] if clip.get("origin") == "auto_subtitle"]
    doc["clips"] = [clip for clip in doc["clips"] if clip.get("origin") != "auto_subtitle"]
    font_size = SUBTITLE_FONT.get(doc["settings"]["ratio"], 52)
    items, skipped = [], 0
    for beat in sorted(beats, key=lambda item: int(item.get("sequence") or 0)):
        lines = _beat_dialogue(beat)
        target = visual.get(str(beat.get("id") or ""))
        if not lines or target is None:
            skipped += 1
            continue
        available = max(1 / fps, target["duration"] - 1 / fps)
        durations = [_line_seconds(line) for line in lines]
        total = sum(durations)
        scale = min(1.0, available / total) if total else 1.0
        cursor = target["start"]
        end = target["start"] + target["duration"] - 1 / fps
        for line, seconds in zip(lines, durations):
            duration = _frame(max(1 / fps, seconds * scale), fps)
            if cursor + duration > end + 1e-6:
                duration = _frame(end - cursor, fps)
            if duration < 1 / fps:
                skipped += 1
                break
            overlaps = any(cursor < clip["start"] + clip["duration"] - 1e-6 and
                           cursor + duration > clip["start"] + 1e-6 for clip in manual)
            if overlaps:
                skipped += 1
                cursor = cursor + duration
                continue
            caption = {"id": uuid.uuid4().hex, "track": "text", "start": cursor, "duration": duration,
                       "in_point": 0, "speed": 1, "volume": 1, "muted": False, "opacity": 1,
                       "scale": 1, "x": 0, "y": 36, "rotation": 0, "effect": "none",
                       "fade_in": 0, "fade_out": 0, "text": _line_text(line)[:200],
                       "color": "#ffffff", "font_size": font_size, "origin": "auto_subtitle",
                       "beat_id": beat.get("id")}
            doc["clips"].append(caption)
            items.append({"name": caption["text"], "start": caption["start"], "duration": caption["duration"],
                          "beat_id": beat.get("id"), "action": "add"})
            cursor = _frame(cursor + duration, fps)
    result = validate_document(doc)
    return {"document": result, "items": items, "count": len(items), "skipped_count": skipped,
            "replaced_count": len(auto), "total_duration": sum(item["duration"] for item in items)}


def _split_caption_text(text: str, limit: int) -> list[str]:
    """Cut a transcript segment into readable blocks without dropping any character."""
    pieces, current = [], ""
    for char in text:
        current += char
        if char in CAPTION_BREAKS:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    chunks: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        while len(piece) > limit:
            chunks.append(piece[:limit])
            piece = piece[limit:]
        if not piece:
            continue
        if chunks and len(chunks[-1]) + len(piece) <= limit:
            chunks[-1] += piece
        else:
            chunks.append(piece)
    return chunks


def _allocate_frames(available: int, weights: list[int]) -> list[int]:
    total = sum(weights) or 1
    counts = [max(1, math.floor(available * weight / total)) for weight in weights]
    while sum(counts) > available and max(counts) > 1:
        counts[counts.index(max(counts))] -= 1
    counts[-1] += available - sum(counts)
    return counts


def _caption_blocks(text: str, start: float, end: float, fps: int) -> list[tuple[str, float, float]]:
    """Keep blocks short enough to read, splitting the time window on whole frames."""
    window = end - start
    if window < 1 / fps:
        return []
    spoken = len(text) / window if window else AUDIO_CAPTION_MAX_CHARS
    limit = min(AUDIO_CAPTION_MAX_CHARS,
                max(AUDIO_CAPTION_MIN_CHARS, math.floor(AUDIO_CAPTION_MAX_SECONDS * spoken)))
    chunks = _split_caption_text(text, limit)
    available = round(window * fps)
    if available < len(chunks):
        chunks = [text]
        available = round(window * fps)
    counts = _allocate_frames(available, [len(chunk) for chunk in chunks])
    blocks, cursor = [], start
    for chunk, frames in zip(chunks, counts):
        blocks.append((chunk, cursor, cursor + frames / fps))
        cursor += frames / fps
    return blocks


def _audio_caption_candidates(evidence: dict[str, dict], fps: int) -> tuple[list[dict], int]:
    """Map source-local transcript segments onto every audible span of their media."""
    candidates, inaudible = [], 0
    for asset_id, item in evidence.items():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "素材")[:60]
        segments = [segment for segment in (item.get("segments") or []) if isinstance(segment, dict)]
        spans = sorted((span for span in (item.get("spans") or []) if isinstance(span, dict)),
                       key=lambda value: float(value.get("timeline_start") or 0))
        for segment in segments:
            text = str(segment.get("text") or "").strip()[:200]
            raw_start = float(segment.get("start") or 0)
            raw_end = float(segment.get("end") or 0)
            placed = 0
            for span in spans:
                speed = float(span.get("speed") or 1) or 1.0
                source_start = float(span.get("in_point") or 0)
                source_end = source_start + float(span.get("timeline_duration") or 0) * speed
                clipped_start, clipped_end = max(raw_start, source_start), min(raw_end, source_end)
                if not text or (clipped_end - clipped_start) / speed < AUDIO_CAPTION_MIN_SECONDS:
                    continue
                timeline_start = float(span.get("timeline_start") or 0)
                start = _frame(timeline_start + (clipped_start - source_start) / speed, fps)
                end = _frame(timeline_start + (clipped_end - source_start) / speed, fps)
                if end - start < 1 / fps:
                    continue
                blocks = _caption_blocks(text, start, end, fps)
                reasons = [f"来自「{name}」转写第 {int(float(segment.get('id') or 0)) + 1} 段"]
                if clipped_start > raw_start or clipped_end < raw_end:
                    reasons.append("已按镜头边界收短")
                if len(blocks) > 1:
                    reasons.append("长句已分行")
                reason = "；".join(reasons)
                for block, block_start, block_end in blocks:
                    candidates.append({"asset_id": asset_id, "beat_id": item.get("beat_id"),
                                       "segment_id": str(segment.get("id") or ""),
                                       "start": block_start, "duration": round(block_end - block_start, 6),
                                       "text": block, "reason": reason})
                placed += 1
            if not placed:
                inaudible += 1
    return candidates, inaudible


def place_audio_subtitles(document: dict, evidence: dict[str, dict]) -> dict:
    """Lay captions from real transcribed audio; script dialogue is never used as a fallback."""
    doc = validate_document(document)
    if not evidence:
        raise ValueError("时间线上还没有可用的音轨转写结果，请先点击「转写音频」并等待完成")
    fps = doc["settings"]["fps"]
    font_size = SUBTITLE_FONT.get(doc["settings"]["ratio"], 52)
    auto = [clip for clip in doc["clips"] if clip.get("origin") == "auto_subtitle"]
    doc["clips"] = [clip for clip in doc["clips"] if clip.get("origin") != "auto_subtitle"]
    occupied = sorted((float(clip["start"]), float(clip["start"]) + float(clip["duration"]))
                      for clip in doc["clips"] if clip["track"] == "text")
    candidates, inaudible = _audio_caption_candidates(evidence, fps)
    candidates.sort(key=lambda item: (item["start"], item["duration"], item["asset_id"], item["segment_id"]))
    items, skipped = [], 0
    for candidate in candidates:
        start, duration = candidate["start"], candidate["duration"]
        end = start + duration
        if len(doc["clips"]) >= MAX_DOCUMENT_CLIPS:
            skipped += 1
            continue
        if any(start < used_end - 1e-6 and end > used_start + 1e-6 for used_start, used_end in occupied):
            skipped += 1
            continue
        clip = {"id": uuid.uuid4().hex, "track": "text", "start": start, "duration": duration,
                "in_point": 0, "speed": 1, "volume": 1, "muted": False, "opacity": 1,
                "scale": 1, "x": 0, "y": 36, "rotation": 0, "effect": "none",
                "fade_in": 0, "fade_out": 0, "text": candidate["text"],
                "color": "#ffffff", "font_size": font_size, "origin": "auto_subtitle",
                "beat_id": candidate.get("beat_id")}
        doc["clips"].append(clip)
        occupied.append((start, end))
        items.append({"asset_id": candidate["asset_id"], "segment_id": candidate["segment_id"],
                      "beat_id": candidate.get("beat_id"), "name": candidate["text"], "start": start,
                      "duration": duration, "reason": candidate["reason"], "action": "add"})
    result = validate_document(doc)
    return {"document": result, "items": items, "count": len(items), "skipped_count": skipped,
            "inaudible_count": inaudible, "replaced_count": len(auto),
            "total_duration": round(sum(item["duration"] for item in items), 3)}


def subtitle_translation_targets(document: dict) -> list[dict]:
    """Collect caption texts that are not Simplified Chinese yet, keyed by their clip id."""
    doc = validate_document(document)
    targets = []
    for clip in doc["clips"]:
        if clip["track"] != "text":
            continue
        text = str(clip.get("text") or "").strip()
        if text and _needs_chinese_translation(text):
            targets.append({"clip_id": clip["id"], "text": text})
    return targets


def translate_subtitles(document: dict, translations: dict[str, str], *, strict: bool = True) -> dict:
    """Replace caption texts with translations; timing, layout and style stay untouched."""
    doc = validate_document(document)
    items, applied, skipped = [], [], 0
    for clip in doc["clips"]:
        if clip["track"] != "text":
            continue
        text = str(clip.get("text") or "").strip()
        if not text:
            continue
        if not _needs_chinese_translation(text):
            skipped += 1
            continue
        translated = str(translations.get(clip["id"]) or "").strip()
        if not translated:
            if strict:
                raise ValueError("部分字幕没有拿到翻译结果，请重试")
            skipped += 1
            continue
        clip["text"] = translated[:200]
        items.append({"clip_id": clip["id"], "name": clip["text"], "start": clip["start"],
                      "duration": clip["duration"], "reason": f"原文：{text[:120]}", "action": "update"})
        applied.append({"clip_id": clip["id"], "original": text, "translated": clip["text"]})
    return {"document": validate_document(doc), "items": items, "count": len(items),
            "skipped_count": skipped, "total_duration": round(sum(item["duration"] for item in items), 3),
            "translations": applied}


def _proposal_translation_map(record: dict) -> dict[str, str]:
    """Original text -> translated text stored on a succeeded subtitle_translate proposal."""
    entries = record.get("translations") or []
    mapping: dict[str, str] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("original") and entry.get("translated"):
                mapping[str(entry["original"])] = str(entry["translated"])
    if not mapping:
        # Proposals created before the reuse feature only kept the truncated
        # original inside items.reason; recover whatever is still matchable.
        for item in record.get("items") or []:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "")
            if reason.startswith("原文：") and item.get("name"):
                mapping[reason[3:]] = str(item["name"])
    return mapping


def subtitle_reapply_targets(document: dict, mapping: dict[str, str]) -> dict[str, str]:
    """Match current caption texts against a previous translation mapping."""
    doc = validate_document(document)
    targets: dict[str, str] = {}
    for clip in doc["clips"]:
        if clip["track"] != "text":
            continue
        text = str(clip.get("text") or "").strip()
        if text and text in mapping:
            targets[clip["id"]] = mapping[text]
    return targets


def make_subtitle_translator(llm):
    """Wrap the default chat model into a batched line translator for subtitle_translate."""
    def translate(texts: list[str]) -> list[str]:
        chat_json = getattr(llm, "chat_json", None)
        if not callable(chat_json):
            raise ValueError("字幕翻译能力未启用，请先在管理设置检查大模型配置")
        results: list[str] = []
        for index in range(0, len(texts), SUBTITLE_TRANSLATE_BATCH):
            batch = texts[index:index + SUBTITLE_TRANSLATE_BATCH]
            try:
                payload = chat_json(SUBTITLE_TRANSLATE_SYSTEM, dumps({"lines": batch}),
                                    temperature=0.2, max_tokens=8192)
            except Exception as error:
                raise ValueError("字幕翻译暂时失败，请稍后重试") from error
            lines = payload.get("lines") if isinstance(payload, dict) else None
            if (not isinstance(lines, list) or len(lines) != len(batch)
                    or not all(isinstance(line, str) and line.strip() for line in lines)):
                raise ValueError("字幕翻译模型返回的结果不完整，请重试")
            results.extend(line.strip() for line in lines)
        return results
    return translate


def _hook_plan(meta: list[dict], strategy: str) -> tuple[list[dict], int, int]:
    if strategy not in HOOK_STRATEGIES:
        raise ValueError("请选择引流剪辑策略：3秒进冲突、只留高潮、金句开场、结尾悬念或预告片")
    chronological = sorted(meta, key=lambda item: item["sequence"])
    total = sum(item["duration"] for item in meta)
    target = min(30.0, max(6.0, total * .5))
    chosen: dict[str, dict] = {}

    def add(item: dict, role: str, reason: str):
        keep = item["keep"]
        chosen[item["beat_id"]] = {**item, "role": role, "reason": reason, "trim": keep}

    def score_order():
        return sorted(meta, key=lambda item: (item["score"], item["duration"]), reverse=True)

    def fill(chosen_seconds: float, pool: list[dict], role: str):
        for item in score_order():
            if item["beat_id"] in chosen or item not in pool:
                continue
            if chosen_seconds >= target and chosen:
                break
            add(item, role, "；".join(item["reasons"]))
            chosen_seconds += item["keep"]
        return chosen_seconds

    if strategy == "climax_only":
        cap = max(1, math.ceil(len(meta) * .3))
        for item in score_order()[:cap]:
            add(item, "climax", "高光分最高：" + "；".join(item["reasons"]))
    elif strategy == "quote_open":
        dialogue = [item for item in meta if item["has_dialogue"]] or meta
        opener = max(dialogue, key=lambda item: (item["score"], item["duration"]))
        add(opener, "quote", "金句开场：" + "；".join(opener["reasons"]))
        kept = fill(opener["keep"], dialogue, "dialogue")
        scores = sorted(item["score"] for item in meta)
        fill(kept, [item for item in meta if item["score"] >= scores[len(scores) // 2]], "beat")
    elif strategy == "ending_hook":
        start = max(1, math.ceil(len(chronological) * .4))
        eligible = chronological[start:-1] or chronological[:-1] or chronological
        kept = 0.0
        for item in score_order():
            if item not in eligible or item["beat_id"] in chosen:
                continue
            if kept >= target and chosen:
                break
            add(item, "ending", "后半段高光：" + "；".join(item["reasons"]))
            kept += item["keep"]
    elif strategy == "trailer":
        opener = max(meta, key=lambda item: (item["score"], item["duration"]))
        add(opener, "hook", "爆点冷开：" + "；".join(opener["reasons"]))
        eligible = [item for item in chronological[:-1] if item["beat_id"] != opener["beat_id"]]
        kept, want_dialogue = opener["keep"], True
        while kept < target and eligible:
            pool = [item for item in eligible if item["has_dialogue"] == want_dialogue and item["beat_id"] not in chosen]
            pool = pool or [item for item in eligible if item["beat_id"] not in chosen]
            if not pool:
                break
            item = max(pool, key=lambda value: value["score"])
            add(item, "quote" if want_dialogue and item["has_dialogue"] else "beat", "金句对切：" + "；".join(item["reasons"]))
            kept += item["keep"]
            want_dialogue = not want_dialogue
    else:
        opener = max(meta, key=lambda item: (item["score"], item["duration"]))
        add(opener, "conflict", "冲突开场：" + "；".join(opener["reasons"]))
        after = [item for item in chronological if item["sequence"] > opener["sequence"]]
        kept = fill(opener["keep"], after, "beat")
        if kept < target * .5:
            fill(kept, [item for item in chronological if item["sequence"] < opener["sequence"]], "beat")

    ordered = [item for item in sorted(chosen.values(), key=lambda value: value["sequence"])]
    opener_id = next((item["beat_id"] for item in chosen.values() if item["role"] in {"conflict", "quote", "hook"}), None)
    if opener_id:
        opener = chosen[opener_id]
        ordered = [opener] + [item for item in ordered if item["beat_id"] != opener_id]
    trimmed = sum(1 for item in ordered if item["trim"] < item["duration"] - 0.01)
    return ordered, len(meta) - len(ordered), trimmed


def _cut_plan(operation: str, beats: list[dict], sources: list[dict], strategy: str | None = None,
              understanding: dict[str, dict] | None = None) -> tuple[list[dict], int, int]:
    videos = _video_by_beat(sources)
    usable = [beat for beat in beats if str(beat.get("id") or "") in videos]
    if not usable:
        raise ValueError("当前分集还没有可用于剪辑的镜头视频")
    meta = []
    for beat in usable:
        dialogue = _beat_dialogue(beat)
        dialogue_seconds = sum(_line_seconds(line) for line in dialogue)
        video_duration = float(videos[str(beat["id"])].get("duration") or 0)
        duration = min(_beat_duration(beat), max(.04, video_duration))
        keep = min(duration, max(2.0, min(8.0, dialogue_seconds + .6))) if dialogue else min(duration, 5.0)
        score, reasons = _beat_score_detail(beat)
        meta.append({"beat": beat, "beat_id": str(beat["id"]), "sequence": int(beat.get("sequence") or 0),
                     "duration": duration, "keep": round(keep, 3), "dialogue_seconds": dialogue_seconds,
                     "has_dialogue": bool(dialogue), "score": score, "reasons": reasons})
    _apply_understanding(meta, understanding)
    if operation == "hook_cut":
        return _hook_plan(meta, strategy or "")
    decisions: dict[str, dict] = {}
    if operation == "dialogue_cut":
        for item in meta:
            if item["has_dialogue"]:
                decisions[item["beat_id"]] = {"trim": min(item["duration"], max(1.2, item["dialogue_seconds"] + 0.6)), "action": "trim"}
        if not decisions:
            raise ValueError("没有检测到对白镜头，请先完成配音或补充对白")
    elif operation == "quick_cut":
        total = sum(item["duration"] for item in meta)
        target = max(6.0, total * 0.6)
        kept_seconds = 0.0
        for item in meta:
            if item["has_dialogue"]:
                decisions[item["beat_id"]] = {"trim": min(item["duration"], max(2.0, item["dialogue_seconds"] + 0.5)), "action": "trim"}
                kept_seconds += decisions[item["beat_id"]]["trim"]
        for item in sorted(meta, key=lambda value: value["score"], reverse=True):
            if kept_seconds >= target and decisions:
                break
            if item["beat_id"] in decisions:
                continue
            decisions[item["beat_id"]] = {"trim": min(item["duration"], 2.5), "action": "trim"}
            kept_seconds += decisions[item["beat_id"]]["trim"]
        if not decisions:
            for item in sorted(meta, key=lambda value: value["score"], reverse=True)[:3]:
                decisions[item["beat_id"]] = {"trim": min(item["duration"], 2.5), "action": "trim"}
    else:
        total = sum(item["duration"] for item in meta)
        target = max(8.0, min(60.0, total * 0.5))
        cap = min(20, max(3, math.ceil(target / 5.0)))
        kept_seconds = 0.0
        for item in sorted(meta, key=lambda value: value["score"], reverse=True):
            if len(decisions) >= cap:
                break
            if kept_seconds >= target and len(decisions) >= min(3, len(meta)):
                break
            decisions[item["beat_id"]] = {"trim": min(item["duration"], 5.0), "action": "trim"}
            kept_seconds += decisions[item["beat_id"]]["trim"]
        if not decisions:
            decisions[meta[0]["beat_id"]] = {"trim": min(meta[0]["duration"], 5.0), "action": "trim"}
    ordered = [{**item, "trim": decisions[item["beat_id"]]["trim"]} for item in meta if item["beat_id"] in decisions]
    trimmed = sum(1 for item in ordered if item["trim"] < item["duration"] - 0.01)
    return ordered, len(meta) - len(ordered), trimmed


def rebuild_cut(document: dict, sources: list[dict], beats: list[dict], operation: str, strategy: str | None = None,
                understanding: dict[str, dict] | None = None) -> dict:
    """Rebuild picture and dubbing lanes from the selected beats; manual text is preserved."""
    doc = validate_document(document)
    ordered, dropped_count, trimmed_count = _cut_plan(operation, beats, sources, strategy, understanding)
    videos, audios = _video_by_beat(sources), _audio_by_beat(sources)
    fps = doc["settings"]["fps"]
    manual_text = [clip for clip in doc["clips"] if clip["track"] == "text" and clip.get("origin") != "auto_subtitle"]
    doc["clips"] = list(manual_text)
    cursor, items = 0.0, []
    used_assets: list[dict] = []
    for item in ordered:
        video = videos[item["beat_id"]]
        used_assets.append(video)
        duration = _frame(min(item["duration"], item["trim"]), fps)
        if duration < 1 / fps:
            continue
        clip = {"id": uuid.uuid4().hex, "asset_id": video["id"], "track": "video",
                "start": _frame(cursor, fps), "duration": duration, "in_point": 0, "speed": 1,
                "muted": False, "volume": 1}
        doc["clips"].append(clip)
        items.append({"asset_id": video["id"], "beat_id": item["beat_id"], "name": video["name"],
                      "start": clip["start"], "duration": clip["duration"], "action": "trim" if duration < item["duration"] - 0.01 else "keep",
                      **({"reason": item["reason"]} if item.get("reason") else {})})
        audio_cursor = clip["start"]
        for audio in audios.get(item["beat_id"], []):
            used_assets.append(audio)
            length = _frame(min(float(audio["duration"]), clip["start"] + clip["duration"] - audio_cursor), fps)
            if length < 1 / fps:
                continue
            doc["clips"].append({"id": uuid.uuid4().hex, "asset_id": audio["id"], "track": "audio",
                                 "start": audio_cursor, "duration": length, "in_point": 0, "speed": 1,
                                 "muted": False, "volume": 1})
            audio_cursor = _frame(audio_cursor + length, fps)
        cursor = _frame(cursor + duration, fps)
    _add_assets(doc, used_assets)
    result = validate_document(doc)
    used_evidence = sum(1 for item in ordered if item["beat_id"] in (understanding or {}))
    used_shots = 0
    for item in ordered:
        evidence = (understanding or {}).get(item["beat_id"])
        if not evidence:
            continue
        used_shots += sum(1 for shot in evidence.get("shots") or [] if shot.get("status") == "succeeded")
    return {"document": result, "items": items, "count": len(items), "dropped_count": dropped_count,
            "trimmed_count": trimmed_count, "skipped_count": len(beats) - len(ordered),
            "understanding_used": used_evidence, "understanding_shots_used": used_shots,
            "total_duration": cursor}


class EditingActions:
    def __init__(self, repo, understanding=None, transcription=None, llm=None):
        self.repo = repo
        self.understanding = understanding
        self.transcription = transcription
        self.translate = make_subtitle_translator(llm) if llm is not None else None

    @staticmethod
    def public(record: dict, *, result=False) -> dict:
        return {k: v for k, v in record.items() if not k.startswith("_") and (result or k != "snapshot")}

    @staticmethod
    def target(conn, project: str, sequence: str):
        if not conn.execute("SELECT id FROM ai_projects WHERE id=?", (project,)).fetchone():
            raise AssistantNotFound("关联工程不存在")
        if sequence != "main" and not conn.execute("SELECT id FROM ai_project_episodes WHERE id=? AND project_id=?", (sequence, project)).fetchone():
            raise AssistantNotFound("该分集不属于当前工程")

    @staticmethod
    def snapshot(conn, owner: str, project: str, sequence: str, *, lock=False) -> dict:
        key = smart_edit_service.document_id(project, owner, sequence)
        row = conn.execute("SELECT * FROM ai_smart_edit_documents WHERE id=? AND owner_user_id=?", (key, owner), for_update=lock).fetchone()
        return {"revision": int(row["revision"]) if row else 0,
                "document": json.loads(row["document_json"]) if row else empty_document(), "draft_key": key}

    def read(self, owner: str, project: str, sequence: str) -> dict:
        with self.repo.store.connection() as conn:
            self.target(conn, project, sequence)
            snapshot = self.snapshot(conn, owner, project, sequence)
        doc = snapshot["document"]
        result = {"project_id": project, "sequence_id": sequence, "revision": snapshot["revision"],
                  "videos": [{k: a.get(k) for k in ("id", "name", "duration", "beat_id")} for a in doc["assets"] if a["kind"] == "video"],
                  "clips": [{k: c.get(k) for k in ("asset_id", "track", "start", "duration", "text") if k in c} for c in doc["clips"]]}
        if sequence == "main":
            result["analysis"] = {"kind": "free", "video_count": len(result["videos"]), "clip_count": len(doc["clips"])}
            if self.understanding:
                result["analysis"]["understanding"] = self.understanding.summary(owner, project, sequence)
            if self.transcription:
                result["analysis"]["transcript"] = self.transcription.summary(owner, project, sequence)
            return result
        sources = smart_edit_service.project_sources(project, sequence)
        beats = sorted(ProjectDetailService.get_episode_detail(project, sequence).get("beats") or [],
                       key=lambda beat: int(beat.get("sequence") or 0))
        videos = _video_by_beat(sources)
        candidates, dialogue_seconds = [], 0.0
        for beat in beats:
            beat_id = str(beat.get("id") or "")
            if beat_id not in videos:
                continue
            score, reasons = _beat_score_detail(beat)
            lines = _beat_dialogue(beat)
            dialogue_seconds += sum(_line_seconds(line) for line in lines)
            candidates.append({"beat_id": beat_id, "sequence": int(beat.get("sequence") or 0),
                               "heading": str(beat.get("heading") or beat.get("title") or ""),
                               "duration": round(_beat_duration(beat), 2),
                               "dialogue_seconds": round(sum(_line_seconds(line) for line in lines), 2),
                               "score": score, "reasons": reasons})
        result["analysis"] = {"kind": "episode", "beat_count": len(beats), "video_count": len(videos),
                              "dialogue_beat_count": sum(1 for item in candidates if item["dialogue_seconds"]),
                              "dialogue_seconds": round(dialogue_seconds, 2),
                              "highlight_candidates": sorted(candidates, key=lambda item: item["score"], reverse=True)[:8]}
        if self.understanding:
            result["analysis"]["understanding"] = self.understanding.summary(owner, project, sequence)
        if self.transcription:
            result["analysis"]["transcript"] = self.transcription.summary(owner, project, sequence)
        return result

    def preview(self, owner: str, project: str, sequence: str, *, revision=None, session_id=None,
                operation="video_arrange", run_id=None, asset_ids=None, strategy=None) -> dict:
        if operation not in OPERATION_TITLES:
            raise ValueError("尚未支持该剪辑功能")
        if asset_ids is not None and operation != "video_arrange":
            raise ValueError("只有智能铺轨支持自定义清单顺序")
        if operation == "hook_cut" and strategy not in HOOK_STRATEGIES:
            raise ValueError("请选择引流剪辑策略：3秒进冲突、只留高潮、金句开场、结尾悬念或预告片")
        if operation != "hook_cut" and strategy is not None:
            raise ValueError("只有引流剪辑支持策略选择")
        with self.repo.store.connection() as conn:
            self.target(conn, project, sequence)
            snapshot = self.snapshot(conn, owner, project, sequence)
        if revision is not None and revision != snapshot["revision"]:
            raise AssistantConflict("剪辑已变化，请保存后重新预览")
        sources = smart_edit_service.project_sources(project, sequence)
        beats = [] if sequence == "main" or operation in {"video_arrange", "audio_subtitle", "subtitle_translate"} else sorted(
            ProjectDetailService.get_episode_detail(project, sequence).get("beats") or [],
            key=lambda beat: int(beat.get("sequence") or 0))
        evidence, evidence_meta = ({}, {"status": "missing", "used_count": 0, "shot_used_count": 0})
        if operation in CUT_OPERATIONS and self.understanding:
            evidence, evidence_meta = self.understanding.evidence(owner, project, sequence)
        transcript_meta: dict = {}
        if operation == "audio_subtitle":
            if self.transcription is None:
                raise ValueError("音频转写能力未启用，请先在管理设置检查语音转写配置")
            transcript, transcript_meta = self.transcription.evidence(owner, project, sequence)
            if not transcript:
                raise ValueError(TRANSCRIPT_MISSING_MESSAGES.get(str(transcript_meta.get("status")),
                                                                 TRANSCRIPT_MISSING_FALLBACK))
        if operation == "video_arrange":
            plan = arrange_videos(snapshot["document"], sources, free=sequence == "main", asset_ids=asset_ids)
        elif operation == "subtitle_arrange":
            plan = place_subtitles(snapshot["document"], beats)
        elif operation == "audio_subtitle":
            plan = place_audio_subtitles(snapshot["document"], transcript)
        elif operation == "subtitle_translate":
            if self.translate is None:
                raise ValueError("字幕翻译能力未启用，请先在管理设置检查大模型配置")
            targets = subtitle_translation_targets(snapshot["document"])
            translations: dict[str, str] = {}
            if targets:
                translated = self.translate([target["text"] for target in targets])
                translations = {target["clip_id"]: translated[index] for index, target in enumerate(targets)}
            plan = translate_subtitles(snapshot["document"], translations)
        else:
            plan = rebuild_cut(snapshot["document"], sources, beats, operation, strategy, evidence)
        extra = {"strategy": strategy, "strategy_title": HOOK_STRATEGIES[strategy]["label"],
                 "principle": HOOK_STRATEGIES[strategy]["principle"]} if operation == "hook_cut" else {}
        if operation in CUT_OPERATIONS:
            extra["understanding"] = {**evidence_meta, "used_count": plan.pop("understanding_used", 0),
                                      "shot_used_count": plan.pop("understanding_shots_used", 0)}
        if operation == "audio_subtitle":
            extra["transcript"] = transcript_meta
        return self._store_proposal(owner, project, sequence, snapshot, operation, session_id, run_id, extra=extra, **plan)

    def _store_proposal(self, owner, project, sequence, snapshot, operation, session_id, run_id, *, extra=None, **plan):
        with self.repo.transaction() as conn:
            if session_id:
                session = self.repo.get(owner, session_id, "session", conn=conn, lock=True)
                context = session.get("context") or {}
                if session.get("project_id") != project or context != {"kind": "smart_edit", "sequence_id": sequence}:
                    raise AssistantConflict("剪辑会话与当前工程或分集不一致")
                if session.get("active_run_id") and session["active_run_id"] != run_id:
                    raise AssistantConflict("请等待助手当前回复完成")
            proposal = self.repo.insert(owner, "edit_proposal", {"operation": operation, "title": OPERATION_TITLES[operation],
                "project_id": project, "sequence_id": sequence, "session_id": session_id,
                "base_revision": snapshot["revision"], "_base_hash": document_hash(snapshot["document"]),
                "_document": plan.pop("document"), **plan, **(extra or {})},
                parent=session_id or snapshot["draft_key"], status="pending" if plan["count"] else "empty", conn=conn)
            if session_id and not run_id:
                self._message(owner, session, proposal["id"], conn)
        return self.public(proposal)

    def _message(self, owner, session, action_id, conn):
        sequence = int(session.get("message_sequence", 0)) + 1
        self.repo.insert(owner, "message", {"session_id": session["id"], "sequence": sequence, "role": "assistant",
            "run_id": "", "parts": [{"type": "edit_action", "action_id": action_id}], "selections": session["selections"]},
            parent=session["id"], status="succeeded", conn=conn)
        self.repo.update(owner, session, {"message_sequence": sequence}, conn=conn)

    def reorder(self, owner, project, sequence, action_id, asset_ids):
        with self.repo.transaction() as conn:
            record = self.repo.get(owner, action_id, "edit_proposal", conn=conn, lock=True)
            if record["project_id"] != project or record["sequence_id"] != sequence:
                raise AssistantNotFound("铺轨记录不属于当前工程或分集")
            self.target(conn, project, sequence)
            if record["status"] != "pending" or record["operation"] != "video_arrange":
                raise ValueError("只有待确认的智能铺轨清单可以调整顺序")
            current = self.snapshot(conn, owner, project, sequence, lock=True)
            if current["revision"] != record["base_revision"] or document_hash(current["document"]) != record["_base_hash"]:
                raise AssistantConflict("时间线已变化，请关闭并重新预览铺轨清单")
            sources = smart_edit_service.project_sources(project, sequence)
            plan = arrange_videos(current["document"], sources, free=sequence == "main", asset_ids=asset_ids)
            after = plan.pop("document")
            record = self.repo.update(owner, record, {**plan, "_document": after}, conn=conn)
            return self.public(record)

    def get(self, owner, project, sequence, action_id):
        record = self.repo.get(owner, action_id, "edit_proposal")
        if record["project_id"] != project or record["sequence_id"] != sequence:
            raise AssistantNotFound("铺轨记录不属于当前工程或分集")
        with self.repo.store.connection() as conn:
            self.target(conn, project, sequence)
        return self.public(record, result=True)

    def reapply(self, owner, project, sequence, action_id, *, revision=None, session_id=None, run_id=None):
        """Rebuild a subtitle_translate proposal from a succeeded record's original->translation mapping."""
        record = self.repo.get(owner, action_id, "edit_proposal")
        if record["project_id"] != project or record["sequence_id"] != sequence:
            raise AssistantNotFound("翻译记录不属于当前工程或分集")
        if record["status"] != "succeeded" or record["operation"] != "subtitle_translate":
            raise ValueError("只有已执行的字幕翻译可以重新应用")
        mapping = _proposal_translation_map(record)
        if not mapping:
            raise ValueError("该记录没有可复用的翻译对照，请重新执行字幕翻译")
        with self.repo.store.connection() as conn:
            self.target(conn, project, sequence)
            snapshot = self.snapshot(conn, owner, project, sequence)
        if revision is not None and revision != snapshot["revision"]:
            raise AssistantConflict("剪辑已变化，请保存后重新应用")
        plan = translate_subtitles(snapshot["document"], subtitle_reapply_targets(snapshot["document"], mapping), strict=False)
        return self._store_proposal(owner, project, sequence, snapshot, "subtitle_translate", session_id, run_id,
                                    extra={"reapplied_from": action_id}, **plan)

    def confirm(self, owner, project, sequence, action_id):
        with self.repo.transaction() as conn:
            record = self.repo.get(owner, action_id, "edit_proposal", conn=conn, lock=True)
            if record["project_id"] != project or record["sequence_id"] != sequence:
                raise AssistantNotFound("铺轨记录不属于当前工程或分集")
            self.target(conn, project, sequence)
            if record["status"] == "succeeded":
                return self.public(record, result=True)
            if record["status"] != "pending":
                raise ValueError("没有可执行的剪辑内容")
            # Serialize first writes as well as updates. Ordinary saves still use the revision CAS.
            conn.execute("SELECT id FROM ai_projects WHERE id=?", (project,), for_update=True).fetchone()
            current = self.snapshot(conn, owner, project, sequence, lock=True)
            if current["revision"] != record["base_revision"] or document_hash(current["document"]) != record["_base_hash"]:
                raise AssistantConflict("时间线已变化，请关闭并重新预览铺轨清单")
            doc = validate_document(record["_document"])
            revision, now = current["revision"] + 1, smart_edit_service.now_str()
            if current["revision"]:
                updated = conn.execute("UPDATE ai_smart_edit_documents SET document_json=?,revision=?,updated_at=? WHERE id=? AND owner_user_id=? AND revision=?",
                    (dumps(doc), revision, now, current["draft_key"], owner, current["revision"]))
                if updated.rowcount != 1:
                    raise AssistantConflict("时间线已变化，请重新预览")
            else:
                conn.execute("INSERT INTO ai_smart_edit_documents (id,project_id,owner_user_id,sequence_id,revision,document_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (current["draft_key"], project, owner, sequence, revision, dumps(doc), now, now))
            snapshot = {"document": doc, "revision": revision, "draft_key": current["draft_key"], "updated_at": now}
            record = self.repo.update(owner, record, {"snapshot": snapshot}, status="succeeded", conn=conn)
            return self.public(record, result=True)
