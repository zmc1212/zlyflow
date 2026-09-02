from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree
from typing import Any


HEADING_PATTERNS = (
    re.compile(r"^(第[零一二三四五六七八九十百千0-9]+[章节回部卷].*)$"),
    re.compile(r"^(Chapter\s+\d+.*)$", re.IGNORECASE),
    re.compile(r"^(#{1,3}\s+.+)$"),
)

ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".docx"}
MAX_INGEST_BYTES = 8 * 1024 * 1024
CHARS_PER_EPISODE = 3500
DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def detect_source_format(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"md", "markdown"}:
        return "md"
    if suffix == "docx":
        return "docx"
    return "txt"


def decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = content.decode(encoding)
            if text.strip():
                return text.replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文本编码，请另存为 UTF-8 或 GBK 后再上传")


def extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError("不是有效的 Word 文档（.docx）") from error
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{{{DOCX_NS['w']}}}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{{{DOCX_NS['w']}}}t")]
        line = "".join(parts).strip()
        paragraphs.append(line)
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ValueError("Word 文档没有可读取的正文")
    return text


def load_source_text(filename: str, content: bytes) -> tuple[str, str]:
    source_format = detect_source_format(filename)
    if source_format == "docx":
        return extract_docx_text(content), source_format
    return decode_text_bytes(content), source_format


def billed_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def estimated_episode_count(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, (char_count + CHARS_PER_EPISODE - 1) // CHARS_PER_EPISODE)


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.match(stripped) for pattern in HEADING_PATTERNS)


def parse_chapters(text: str) -> list[dict[str, Any]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headings = [index for index, line in enumerate(lines) if _is_heading(line)]
    chapters: list[dict[str, Any]] = []
    if not headings:
        body = text.strip()
        title = (body.split("\n", 1)[0].strip()[:40] if body else "全文") or "全文"
        chapters.append({"title": title, "content": body})
        return chapters

    preamble = "\n".join(lines[: headings[0]]).strip()
    if preamble:
        chapters.append({"title": "开篇", "content": preamble})

    for offset, start in enumerate(headings):
        end = headings[offset + 1] if offset + 1 < len(headings) else len(lines)
        title = lines[start].strip().lstrip("#").strip() or f"第{offset + 1}章"
        body = "\n".join(lines[start + 1 : end]).strip()
        chapters.append({"title": title, "content": body})

    return [item for item in chapters if item["content"] or item["title"]]
