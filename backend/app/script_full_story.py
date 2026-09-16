from __future__ import annotations

import re

_EPISODE_HEADER_RE = re.compile(
    r"^#\s*第\s*([0-9一二三四五六七八九十百]+)\s*集",
    re.MULTILINE,
)
_SHOT_HEADER_RE = re.compile(r"^#{1,3}\s*镜头", re.MULTILINE)
_SCENE_SPLIT_RE = re.compile(r"(?=【|(?<!#)#{1,3}\s*镜头)")
_SCENE_HEADER_RE = re.compile(r"^【([^】]+)】\s*(.*)$")
_BEAT_HEAD_RE = re.compile(r"^Beat\s*(\d+)\s*[：:.．]?\s*(.*)$", re.IGNORECASE)
_BEAT_ANY_RE = re.compile(r"(?m)^Beat\s*\d+", re.IGNORECASE)
_DIALOGUE_HEAD_RE = re.compile(r"^对白[：:]\s*(.*)$")
_ANCHOR_HEAD_RE = re.compile(r"^视觉锚点[：:]\s*(.*)$")
_SHOT_LINE_RE = re.compile(r"^#{1,3}\s*镜头")
_FIELD_LINE_RE = re.compile(r"^[-*]\s*(?:人物|场景|道具|动作|镜头|台词|音效|字幕)[：:]")
_STRUCTURAL_BREAK_RE = re.compile(
    r"(?<!\n)\s*("
    r"【[^】\n]{1,40}】"
    r"|Beat\s*\d+"
    r"|(?<!#)#{1,3}\s*镜头"
    r"|#\s*第\s*[0-9一二三四五六七八九十百]+\s*集"
    r"|#{1,2}\s*视频定位"
    r"|#{1,3}\s*(?:一[、.])?\s*主要人物固定设定"
    r"|\*\*剧情[：:]\*\*"
    r"|视觉锚点[：:]"
    r"|对白[：:]"
    r"|[-*]\s*(?:人物|场景|道具|动作|镜头|台词|音效|字幕)[：:]"
    r")",
    re.IGNORECASE,
)


def normalize_script_full_story(text: str, *, title: str = "") -> str:
    """Make LLM script output wrap and follow content-library Markdown shots.

    Already-valid Markdown is only tidied. Beat ledgers and glued wall text are
    broken onto lines and converted to ``### 镜头N｜场景`` blocks.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return raw
    spaced = _insert_structural_newlines(raw)
    if _BEAT_ANY_RE.search(spaced):
        spaced = _convert_beats_to_shots(spaced)
    spaced = _collapse_blank_lines(spaced)
    return _ensure_episode_header(spaced, title=title).strip()


def split_story_into_scene_texts(full_story: str) -> list[str]:
    """Split a script into scene/shot chunks on ``【`` or ``### 镜头``."""
    text = str(full_story or "")
    if not text.strip():
        return [text]
    parts = _SCENE_SPLIT_RE.split(text)
    scenes: list[str] = []
    preamble = ""
    current = ""
    for part in parts:
        if not part:
            continue
        stripped = part.strip()
        is_start = stripped.startswith("【") or bool(re.match(r"#{1,3}\s*镜头", stripped))
        if is_start:
            if current.strip():
                scenes.append(current.strip())
            if preamble.strip() and not scenes:
                current = preamble.rstrip() + "\n\n" + part.lstrip()
            else:
                current = part
            preamble = ""
        elif current:
            current += part
        else:
            preamble += part
    if current.strip():
        scenes.append(current.strip())
    elif preamble.strip():
        scenes.append(preamble.strip())
    return scenes if scenes else [text]


def _insert_structural_newlines(text: str) -> str:
    return _STRUCTURAL_BREAK_RE.sub(r"\n\1", text)


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _ensure_episode_header(text: str, *, title: str = "") -> str:
    if not _SHOT_HEADER_RE.search(text):
        return text
    if _EPISODE_HEADER_RE.search(text):
        return text
    heading = f"# 第1集：{title}" if str(title or "").strip() else "# 第1集"
    return f"{heading}\n\n{text.lstrip()}"


def _is_block_boundary(line: str) -> bool:
    return bool(
        _SCENE_HEADER_RE.match(line)
        or _BEAT_HEAD_RE.match(line)
        or _SHOT_LINE_RE.match(line)
        or _ANCHOR_HEAD_RE.match(line)
        or line.startswith("#")
        or _FIELD_LINE_RE.match(line)
    )


def _consume_dialogue_block(lines: list[str], start: int) -> tuple[list[str], int]:
    collected: list[str] = []
    index = start
    while index < len(lines):
        nxt = lines[index].strip()
        match = _DIALOGUE_HEAD_RE.match(nxt)
        if not match:
            break
        remainder = match.group(1).strip()
        if remainder:
            collected.append(remainder)
        index += 1
        while index < len(lines):
            follow = lines[index].strip()
            if not follow:
                break
            if _DIALOGUE_HEAD_RE.match(follow) or _is_block_boundary(follow):
                break
            collected.append(follow)
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    return collected, index


def _convert_beats_to_shots(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    current_scene = ""
    pending_anchor = ""
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            index += 1
            continue

        scene_match = _SCENE_HEADER_RE.match(line)
        if scene_match:
            current_scene = scene_match.group(1).strip()
            rest = scene_match.group(2).strip()
            if rest:
                lines[index] = rest
                continue
            index += 1
            continue

        anchor_match = _ANCHOR_HEAD_RE.match(line)
        if anchor_match:
            pending_anchor = anchor_match.group(1).strip()
            index += 1
            continue

        beat_match = _BEAT_HEAD_RE.match(line)
        if beat_match:
            number = beat_match.group(1)
            action = beat_match.group(2).strip()
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            dialogue_lines, index = _consume_dialogue_block(lines, index)
            scene_label = current_scene or "场景"
            out.append(f"### 镜头{number}｜{scene_label}")
            scene_parts = [part for part in (current_scene, pending_anchor) if part]
            pending_anchor = ""
            if scene_parts:
                out.append(f"- 场景：{'。'.join(scene_parts)}")
            if action:
                out.append(f"- 动作：{action}")
            for item in dialogue_lines:
                out.append(f"- 台词：{item}")
            out.append("")
            continue

        leftover = _DIALOGUE_HEAD_RE.match(line)
        if leftover:
            remainder = leftover.group(1).strip()
            if remainder:
                out.append(f"- 台词：{remainder}")
            index += 1
            continue

        out.append(raw.rstrip())
        index += 1
    return "\n".join(out)
