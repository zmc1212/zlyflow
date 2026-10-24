from __future__ import annotations

import re
from pathlib import Path

from ..director_assistant.knowledge import extract_document
from .protocol import EXTENSIONS, MAX_CHARACTERS, MAX_FILE_BYTES, MAX_FILES, SourceInput

SECTION = re.compile(
    r"(?m)^[ \t#*]{0,8}((?:第\s*[0-9零〇一二三四五六七八九十百千两]+\s*[集章回]|Episode\s+\d+)[^\n]{0,70})",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()


def extract_source(filename: str, data: bytes) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError("支持 TXT、Markdown、DOCX 和文字型 PDF；DOC 或扫描件请先转换")
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("文件不能为空，且每份文件不能超过 20MB")
    # Keep the knowledge-base parser unchanged; .markdown is an alias of .md.
    name_for_parser = "script.md" if suffix == ".markdown" else filename
    try:
        pages = extract_document(name_for_parser, data)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("无法读取文档，请检查文件是否损坏，或转换为 TXT / DOCX 后重试") from exc
    text = normalize("\n\n".join(text for _, text in pages))
    if not text:
        raise ValueError("未提取到正文；扫描件请先转为文字型 PDF")
    if len(text) > MAX_CHARACTERS:
        raise ValueError("正文超过 10 万字符，请拆分剧本")
    return {"name": Path(filename.replace("\\", "/")).name[:255] or "剧本", "text": text}


def prepare_sources(values: list[dict]) -> list[dict]:
    if not 1 <= len(values) <= MAX_FILES:
        raise ValueError("一次需要 1–10 份剧本")
    sources = []
    for index, value in enumerate(values, 1):
        item = SourceInput.model_validate(value)
        text = normalize(item.text)
        if not text:
            raise ValueError(f"「{item.name}」没有正文，请移除或重新上传")
        sources.append({"id": f"s{index}", "name": item.name, "text": text})
    if sum(len(source["text"]) for source in sources) > MAX_CHARACTERS:
        raise ValueError("合并后的正文超过 10 万字符，请拆分诊断")
    return sources


def source_blocks(sources: list[dict]) -> list[dict]:
    """Lossless blocks: offsets refer to the frozen normalized source, in code points."""
    blocks = []
    for source in sources:
        text = source["text"]
        headings = [(m.start(), m.group(1).strip("* ")) for m in SECTION.finditer(text)]
        start, serial, heading_index, section = 0, 0, 0, source["name"]
        while start < len(text):
            while heading_index < len(headings) and headings[heading_index][0] <= start:
                section = headings[heading_index][1]
                heading_index += 1
            end = min(start + 1400, len(text))
            next_heading = headings[heading_index][0] if heading_index < len(headings) else len(text)
            if start < next_heading <= end:
                end = next_heading
            elif end < len(text):
                newline = text.rfind("\n", start + 1, end)
                if newline > start:
                    end = newline + 1
            serial += 1
            blocks.append({
                "source_id": source["id"], "block_id": f'{source["id"]}-b{serial}',
                "name": source["name"], "section": section, "start": start, "end": end,
                "text": text[start:end],
            })
            start = end
    return blocks


def segment_blocks(blocks: list[dict], limit: int = 6000) -> list[list[dict]]:
    segments, current, length = [], [], 0
    for block in blocks:
        if current and (
            length + len(block["text"]) > limit
            or (current[-1]["source_id"], current[-1]["section"]) != (block["source_id"], block["section"])
        ):
            segments.append(current)
            current, length = [], 0
        current.append(block)
        length += len(block["text"])
    if current:
        segments.append(current)
    return segments


def explicit_duration(text: str) -> float | None:
    """Only override an estimate when a total or every labelled shot is explicit."""
    text = text.replace("*", "").replace(chr(96), "")
    number = r"(\d+(?:\.\d+)?)\s*(秒|s\b|分钟|分|min\b)"
    total = re.findall(r"(?:本集|本章|本段|总|全片)时长\s*[:：]\s*" + number, text, re.I)
    convert = lambda value, unit: float(value) * (60 if unit.lower() in {"分钟", "分", "min"} else 1)
    if len(total) == 1:
        return convert(*total[0])
    shots = re.split(r"(?m)^[ \t#*]*(?:镜头|分镜)\s*\d+[^\n]*\n", text)[1:]
    if shots:
        durations = [re.findall(r"(?:时长|duration)\s*[:：]\s*" + number, shot, re.I) for shot in shots]
        if all(len(matches) == 1 for matches in durations):
            return sum(convert(*matches[0]) for matches in durations)
    return None
