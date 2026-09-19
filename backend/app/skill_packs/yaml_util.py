"""Minimal YAML subset loader for skill-pack ``meta.yaml`` files.

Pack recipes only need maps, lists, scalars, and comments. Keeping a small
parser avoids adding a PyYAML runtime dependency for this registry.
"""

from __future__ import annotations

from typing import Any


class SkillPackYamlError(ValueError):
    pass


def parse_yaml(text: str) -> Any:
    lines = [_Line(index, raw) for index, raw in enumerate(str(text or "").splitlines(), 1)]
    value, index = _parse_block(lines, 0, 0)
    if index < len(lines):
        leftover = lines[index]
        if leftover.content:
            raise SkillPackYamlError(f"第 {leftover.number} 行无法解析：{leftover.content}")
    return value if value is not None else {}


class _Line:
    def __init__(self, number: int, raw: str) -> None:
        stripped = _strip_comment(raw)
        self.number = number
        self.indent = len(stripped) - len(stripped.lstrip(" "))
        self.content = stripped.strip()


def _strip_comment(raw: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(raw):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return raw[:index].rstrip()
    return raw.rstrip()


def _parse_block(lines: list[_Line], start: int, min_indent: int) -> tuple[Any, int]:
    index = start
    while index < len(lines) and not lines[index].content:
        index += 1
    if index >= len(lines):
        return None, index
    first = lines[index]
    if first.indent < min_indent:
        return None, index
    if first.content.startswith("- "):
        return _parse_list(lines, index, first.indent)
    return _parse_map(lines, index, first.indent)


def _parse_map(lines: list[_Line], start: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.content:
            index += 1
            continue
        if line.indent < indent:
            break
        if line.indent > indent:
            raise SkillPackYamlError(f"第 {line.number} 行缩进无效")
        if line.content.startswith("- "):
            raise SkillPackYamlError(f"第 {line.number} 行期望键值，却遇到列表项")
        key, _, remainder = line.content.partition(":")
        key = key.strip()
        if not key or ":" not in line.content:
            raise SkillPackYamlError(f"第 {line.number} 行不是合法键值：{line.content}")
        remainder = remainder.strip()
        index += 1
        if remainder:
            result[key] = _parse_scalar(remainder)
            continue
        nested, index = _parse_block(lines, index, indent + 1)
        result[key] = {} if nested is None else nested
    return result, index


def _parse_list(lines: list[_Line], start: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.content:
            index += 1
            continue
        if line.indent < indent:
            break
        if line.indent > indent:
            raise SkillPackYamlError(f"第 {line.number} 行列表缩进无效")
        if not line.content.startswith("- "):
            break
        item_text = line.content[2:].strip()
        index += 1
        if not item_text:
            nested, index = _parse_block(lines, index, indent + 2)
            result.append({} if nested is None else nested)
            continue
        if ":" in item_text and not item_text.startswith(("[", "{", "'", '"')):
            key, _, remainder = item_text.partition(":")
            item: dict[str, Any] = {key.strip(): _parse_scalar(remainder.strip()) if remainder.strip() else {}}
            nested, index = _parse_map_continuation(lines, index, indent + 2, item)
            result.append(nested)
            continue
        result.append(_parse_scalar(item_text))
    return result, index


def _parse_map_continuation(
    lines: list[_Line],
    start: int,
    indent: int,
    current: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.content:
            index += 1
            continue
        if line.indent < indent or line.content.startswith("- "):
            break
        if line.indent > indent:
            raise SkillPackYamlError(f"第 {line.number} 行列表对象缩进无效")
        key, _, remainder = line.content.partition(":")
        key = key.strip()
        if not key or ":" not in line.content:
            raise SkillPackYamlError(f"第 {line.number} 行不是合法键值：{line.content}")
        remainder = remainder.strip()
        index += 1
        if remainder:
            current[key] = _parse_scalar(remainder)
            continue
        nested, index = _parse_block(lines, index, indent + 1)
        current[key] = {} if nested is None else nested
    return current, index


def _parse_scalar(text: str) -> Any:
    if text == "" or text in {"null", "Null", "NULL", "~"}:
        return None
    if text in {"true", "True", "TRUE", "yes", "Yes"}:
        return True
    if text in {"false", "False", "FALSE", "no", "No"}:
        return False
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in _split_inline(inner)]
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        return text[1:-1]
    if text.startswith(("+", "-")) and text[1:].isdigit():
        return int(text)
    if text.isdigit():
        return int(text)
    return text


def _split_inline(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    for char in text:
        if char == "'" and not in_double:
            in_single = not in_single
            buf.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            buf.append(char)
            continue
        if char == "," and not in_single and not in_double:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    if buf:
        parts.append("".join(buf).strip())
    return [part for part in parts if part]
