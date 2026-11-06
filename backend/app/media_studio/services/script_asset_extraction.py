from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


ASSET_EXTRACTION_REVISION = 1
ASSET_GROUPS = ("characters", "scenes", "props")
_NAME_SEPARATORS = ("、", "与", "和", "及", "＋", "+", "＆", "&", "/", "／")
_NAME_PARENS = re.compile(r"[（(][^（）()]{0,40}[）)]")


class AssetGroundingError(ValueError):
    """The model returned names or citations that cannot be found in the script."""

    def __init__(self, message: str, names: list[str] | None = None) -> None:
        super().__init__(message)
        self.names = [name for name in (names or []) if name]


class ExtractedAssets(dict[str, list[dict[str, Any]]]):
    """Asset lists keyed by group, plus items the source could not confirm."""

    def __init__(self, assets: dict[str, list[dict[str, Any]]], skipped: list[dict[str, str]] | None = None) -> None:
        super().__init__(assets)
        self.skipped = list(skipped or [])


def asset_source_hash(raw_text: str, analysis: dict[str, Any]) -> str:
    source = {"raw_text": raw_text, "story_setting_text": analysis.get("story_setting_text") or "",
              "story_setting_fields": analysis.get("story_setting_fields") or {}}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def script_asset_extraction_required(raw_text: str, analysis: dict[str, Any] | None) -> bool:
    analysis = analysis or {}
    prose = any(isinstance(ep, dict) and str(ep.get("body") or "").strip() and not ep.get("shots")
                for ep in analysis.get("episodes") or [])
    if not raw_text.strip() or not prose:
        return False
    receipt = analysis.get("script_asset_extraction") or {}
    return not (isinstance(receipt, dict) and receipt.get("revision") == ASSET_EXTRACTION_REVISION
                and receipt.get("source_hash") == asset_source_hash(raw_text, analysis))


def _plain(value: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[*_`#]", "", value))


def _source_text(raw_text: str, analysis: dict[str, Any]) -> str:
    fields = analysis.get("story_setting_fields") or {}
    values = [value for value in fields.values() if isinstance(value, str)] if isinstance(fields, dict) else []
    return "\n\n".join([raw_text, str(analysis.get("story_setting_text") or ""), *values])


def _context_name(name: str, context: str) -> bool:
    if name in context:
        return True
    if not name or len(name) > 40:
        return False
    # A short location label may join source words (现实 + 房间). Every part
    # must occur in the same cited paragraph, not somewhere else in the script.
    reachable = {0: 0}
    for start in range(len(name)):
        if start not in reachable or reachable[start] >= 3:
            continue
        for end in range(start + 2, len(name) + 1):
            if name[start:end] in context:
                reachable[end] = min(reachable.get(end, 4), reachable[start] + 1)
    return len(name) in reachable


def _name_variants(name: str) -> list[str]:
    base = [name]
    stripped = _NAME_PARENS.sub("", name).strip()
    if stripped and stripped != name:
        base.append(stripped)
    variants = list(base)
    pattern = "|".join(re.escape(separator) for separator in _NAME_SEPARATORS)
    for candidate in base:
        if not re.search(pattern, candidate):
            continue
        for separator in _NAME_SEPARATORS:
            variants.append(re.sub(pattern, separator, candidate))
    return [variant for variant in dict.fromkeys(variants) if variant]


def _grounded_name(name: str, evidence: str, source: str, group: str) -> str | None:
    variants = _name_variants(name)
    for candidate in variants:
        if candidate in source:
            return candidate
    # Scene and prop labels may be a short combination of two source words from
    # the same cited paragraph (现实+房间, 摊位+招牌). Person names may not.
    if group in {"scenes", "props"}:
        plain_evidence = _plain(evidence)
        for candidate in variants:
            if _context_name(candidate, plain_evidence):
                return candidate
    return None


def _paragraph_for_name(name: str, paragraphs: list[str], group: str) -> str:
    variants = _name_variants(name)
    for part in paragraphs:
        plain_part = _plain(part)
        for candidate in variants:
            if candidate in plain_part:
                return part.strip()
        if group in {"scenes", "props"}:
            for candidate in variants:
                if _context_name(candidate, plain_part):
                    return part.strip()
    return ""


def _source_paragraphs(raw_text: str, analysis: dict[str, Any]) -> list[str]:
    return [part.strip() for part in re.split(r"\n[ \t]*\n", _source_text(raw_text, analysis)) if part.strip()]


def collect_name_context(
    raw_text: str,
    analysis: dict[str, Any],
    name: str,
    group: str,
    *,
    limit: int = 6,
    max_chars: int = 12000,
) -> str:
    """Source paragraphs that mention one frozen asset name, capped for the describe pass."""
    plain_name = _plain(name)
    variants = _name_variants(plain_name)
    picked: list[str] = []
    total = 0
    for part in _source_paragraphs(raw_text, analysis):
        plain_part = _plain(part)
        matched = any(candidate in plain_part for candidate in variants)
        if not matched and group in {"scenes", "props"}:
            matched = _context_name(plain_name, plain_part)
        if not matched or part in picked:
            continue
        picked.append(part)
        total += len(part)
        if len(picked) >= limit or total >= max_chars:
            break
    return "\n\n".join(picked)


def normalize_name_candidates(
    payload: Any,
    raw_text: str,
    analysis: dict[str, Any],
    hints: dict[str, list[str]],
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    """Freeze the name list before descriptions run; ungrounded names are reported, never described."""
    if not isinstance(payload, dict):
        raise ValueError("资产名称清单格式不完整，请重试")
    source = _plain(_source_text(raw_text, analysis))
    paragraphs = _source_paragraphs(raw_text, analysis)
    frozen: dict[str, list[dict[str, str]]] = {}
    skipped: list[dict[str, str]] = []
    for group in ASSET_GROUPS:
        items = payload.get(group)
        entries: dict[str, dict[str, str]] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or re.search(r"[。！？\r\n]", name):
                skipped.append({"group": group, "name": str(name or "未命名条目")[:80], "reason": "名称格式不完整"})
                continue
            evidence = item.get("evidence")
            evidence_text = evidence.strip() if isinstance(evidence, str) else ""
            grounded = _grounded_name(_plain(name.strip()), evidence_text, source, group)
            if not grounded:
                skipped.append({"group": group, "name": name.strip(), "reason": "名称未在原文出现"})
                continue
            paragraph = evidence_text if evidence_text and _plain(evidence_text) in source else (
                _paragraph_for_name(grounded, paragraphs, group) or evidence_text
            )
            entries.setdefault(grounded, {"name": grounded, "evidence": paragraph})
        for hint in hints.get(group) or []:
            plain_hint = _plain(hint)
            if not plain_hint or plain_hint in entries or plain_hint not in source:
                continue
            entries[plain_hint] = {"name": plain_hint, "evidence": _paragraph_for_name(plain_hint, paragraphs, group)}
        frozen[group] = list(entries.values())[:150]
    return frozen, skipped


def _match_frozen_name(value: Any, allowed: dict[str, dict[str, str]]) -> str:
    if not isinstance(value, str):
        return ""
    plain = _plain(value.strip())
    if plain in allowed:
        return plain
    variants = set(_name_variants(plain))
    for name in allowed:
        if name in variants or any(variant in _name_variants(name) for variant in variants):
            return name
    return ""


def normalize_group_items(
    payload: Any,
    group: str,
    frozen: list[dict[str, str]],
    raw_text: str,
    analysis: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate one skill's descriptions, keeping valid items and naming the ones to repair."""
    if not isinstance(payload, dict):
        raise ValueError("资产整理结果格式不完整，请重试")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = payload.get(group)
    if not isinstance(raw_items, list):
        raise ValueError("资产整理结果缺少条目，请重试")
    allowed = {entry["name"]: entry for entry in frozen if entry.get("name")}
    source = _plain(_source_text(raw_text, analysis))
    paragraphs = _source_paragraphs(raw_text, analysis)
    values: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    for item in raw_items[:150]:
        if not isinstance(item, dict):
            continue
        match = _match_frozen_name(item.get("name"), allowed)
        if not match:
            failed.append(str(item.get("name") or "未命名条目")[:80])
            continue
        description = item.get("description")
        if not isinstance(description, str) or not description.strip() or len(description) > 10000:
            failed.append(match)
            continue
        evidence = item.get("evidence")
        evidence_text = evidence.strip() if isinstance(evidence, str) else ""
        if not evidence_text or _plain(evidence_text) not in source:
            evidence_text = _paragraph_for_name(match, paragraphs, group) or (allowed[match].get("evidence") or "")
        if not evidence_text or _plain(evidence_text) not in source:
            failed.append(match)
            continue
        value: dict[str, Any] = {"name": match, "description": description.strip(), "evidence": evidence_text,
                                 "visual_prompt": str(item.get("visual_prompt") or "")[:20000]}
        if group == "characters":
            value.update(role=str(item.get("role") or "剧本出场角色")[:64], fixed_props=[], shots_count=0)
        elif group == "scenes":
            value.update(type="剧本拍摄场景", elements=[], shots_count=0, related_shots=[])
        else:
            value.update(kind="剧本关键道具", related_character=str(item.get("related_character") or "场景公用")[:255], count=1)
        values[match] = value
    missing = [name for name in allowed if name not in values]
    return list(values.values()), list(dict.fromkeys([*failed, *missing]))


def check_asset_coverage(result: dict[str, list[dict[str, Any]]], raw_text: str, *, strict: bool = True) -> list[str]:
    """Explicit script labels must be reflected; strict mode turns gaps into extraction errors."""
    warnings: list[str] = []
    labeled_text = re.sub(r"[*_`#]", "", raw_text)
    cast = re.search(r"(?m)^\s*(?:[-+•]\s*)?(?:主角|男主角|女主角|男主|女主)[：:]\s*([^\n]+)", labeled_text)
    if cast and cast.group(1).strip() not in {"无", "无人物", "无人"} and not result["characters"]:
        warnings.append("原文点名的主角没有进入角色资产")
    prop_label = re.search(r"(?m)^\s*(?:[-+•]\s*)?(?:固定道具|关键道具|道具)[：:][ \t]*([^\n]*)", labeled_text)
    if prop_label and prop_label.group(1).strip() not in {"无", "无道具"} and not result["props"]:
        warnings.append("原文列出的道具没有进入道具资产")
    scene_headers = re.findall(r"(?m)^\s*场景[ \t]*[0-9一二三四五六七八九十]+[ \t]*[：:][ \t]*([^\n]+)", labeled_text)
    locations = {re.split(r"\s*[-—/／|]\s*", value, maxsplit=1)[0].strip() for value in scene_headers}
    if len(locations) > 1 and len(result["scenes"]) < 2:
        warnings.append("原文有多个分场地点，但场景资产不足 2 个")
    if strict and warnings:
        raise ValueError("资产拆解尚未覆盖原文关键信息，请重试")
    return warnings


def ground_asset_evidence(payload: Any, raw_text: str, analysis: dict[str, Any]) -> Any:
    """Use an actual source paragraph when a model paraphrases its citation."""
    grounded = deepcopy(payload)
    if not isinstance(grounded, dict):
        return grounded
    source = _source_text(raw_text, analysis)
    plain_source = _plain(source)
    paragraphs = re.split(r"\n[ \t]*\n", source)
    for group in ASSET_GROUPS:
        for item in grounded.get(group) if isinstance(grounded.get(group), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            evidence = item.get("evidence")
            if isinstance(evidence, str) and evidence.strip() and _plain(evidence) in plain_source:
                continue
            name = _plain(item["name"])
            if not name:
                continue
            paragraph = _paragraph_for_name(name, paragraphs, group)
            if paragraph:
                item["evidence"] = paragraph
    return grounded


def normalize_extracted_assets(payload: Any, raw_text: str, analysis: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("资产拆解结果格式不完整，请重试")
    source = _plain(_source_text(raw_text, analysis))
    result: dict[str, list[dict[str, Any]]] = {}
    bad_names: list[str] = []
    bad_evidence: list[str] = []
    for group in ASSET_GROUPS:
        items = payload.get(group)
        if not isinstance(items, list) or len(items) > 150:
            raise ValueError("资产拆解结果分类不完整，请重试")
        normalized: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("资产拆解结果缺少有效条目，请重试")
            name = item.get("name")
            evidence = item.get("evidence")
            description = item.get("description")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or re.search(r"[。！？\r\n]", name):
                bad_names.append(name.strip() if isinstance(name, str) else "未命名条目")
                continue
            evidence_text = evidence.strip() if isinstance(evidence, str) else ""
            grounded_name = _grounded_name(_plain(name.strip()), evidence_text, source, group)
            if not grounded_name:
                bad_names.append(name.strip())
                continue
            if not evidence_text or _plain(evidence_text) not in source:
                bad_evidence.append(name.strip())
                continue
            if not isinstance(description, str) or not description.strip() or len(description) > 10000:
                raise ValueError(f"资产「{name.strip()}」缺少有效描述，请重试")
            value = {"name": grounded_name, "description": description.strip(), "evidence": evidence_text,
                     "visual_prompt": str(item.get("visual_prompt") or "")[:20000]}
            if group == "characters":
                value.update(role=str(item.get("role") or "剧本出场角色")[:64], fixed_props=[], shots_count=0)
            elif group == "scenes":
                value.update(type="剧本拍摄场景", elements=[], shots_count=0, related_shots=[])
            else:
                value.update(kind="剧本关键道具", related_character=str(item.get("related_character") or "场景公用")[:255], count=1)
            normalized.setdefault(grounded_name, value)
        result[group] = list(normalized.values())
    if bad_names:
        unique = list(dict.fromkeys(bad_names))
        shown = "、".join(unique[:5])
        suffix = f" 等 {len(unique)} 项" if len(unique) > 5 else ""
        raise AssetGroundingError(f"资产拆解包含原文未出现的名称：{shown}{suffix}，请重试", names=unique)
    if bad_evidence:
        unique = list(dict.fromkeys(bad_evidence))
        shown = "、".join(unique[:5])
        suffix = f" 等 {len(unique)} 项" if len(unique) > 5 else ""
        raise AssetGroundingError(f"资产「{shown}」缺少可核对的原文依据{suffix}，请重试", names=unique)
    if not any(result.values()):
        raise ValueError("未从原文提取到制作资产，请核对剧本后重试")
    check_asset_coverage(result, raw_text)
    return result


def merge_extracted_assets(analysis: dict[str, Any], extracted: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    merged = dict(analysis)
    for group in ASSET_GROUPS:
        catalog = {}
        for item in analysis.get(group) or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            # The old brief fallback used the entire environment paragraph as a
            # scene's name and description. Keep real named/manual catalog items.
            if (group == "scenes" and item.get("type") == "固定场景库"
                    and ("。" in name or re.match(r"^(?:一|这|该)[栋座间处所]", name))
                    and name == str(item.get("description") or "").rstrip("。")):
                continue
            catalog[name] = dict(item)
        for item in extracted[group]:
            previous = catalog.get(item["name"]) or {}
            catalog[item["name"]] = {**item, **{key: value for key, value in previous.items() if value not in (None, "", [], {})}}
        merged[group] = list(catalog.values())
    return merged
