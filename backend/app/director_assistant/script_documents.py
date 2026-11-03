from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from .repository import AssistantConflict, dumps
from ..media_studio.services.script_parser import StandardScriptParser, script_episode_spans


def document_analysis(row: dict | None) -> dict:
    if not row:
        return {}
    value = row.get("analysis_json")
    analysis = json.loads(value) if isinstance(value, str) and value else value or {}
    return deepcopy(analysis) if isinstance(analysis, dict) else {}


def primary_document(rows: list[dict]) -> dict | None:
    active = [row for row in rows if row.get("status") != "merged"]
    if not active:
        return None
    # A marked primary is stable after consolidation; legacy projects start
    # with their oldest script, rather than whichever episode was saved last.
    return min(active, key=lambda row: (
        not bool(document_analysis(row).get("primary_script")),
        str(row.get("created_at") or ""), str(row["id"]),
    ))


def episode_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = digit = 0
    for char in value:
        if char in digits:
            digit = digits[char]
        elif char in {"十", "百"}:
            total += (digit or 1) * {"十": 10, "百": 100}[char]
            digit = 0
    return total + digit


def episode_spans(text: str) -> list[tuple[int, int, int]]:
    spans = script_episode_spans(text)
    if len({number for number, _, _ in spans}) != len(spans):
        raise AssistantConflict("同一份剧本中集数重复，请先整理集标题")
    return spans


def parsed_script(text: str) -> dict:
    analysis = StandardScriptParser.parse(text)
    spans = episode_spans(text)  # Also guards duplicate numbers during adoption.
    bodies = {number: text[start:end].strip() for number, start, end in spans}
    for episode in analysis.get("episodes", []):
        if episode["episode_num"] in bodies:
            episode["body"] = bodies[episode["episode_num"]]
    return analysis


def merge_catalog(existing: list, incoming: list) -> list:
    result = deepcopy(existing)
    names = {str(item.get("name") or "") for item in result if isinstance(item, dict)}
    for item in incoming:
        if isinstance(item, dict) and str(item.get("name") or "") not in names:
            result.append(deepcopy(item)); names.add(str(item.get("name") or ""))
    return result


def script_values(existing: dict | None, artifact: dict, action: str) -> tuple[dict, str]:
    """Merge a scoped creative draft; production episodes and media are untouched."""
    content = artifact["content"]
    old_text = str((existing or {}).get("raw_text") or "")
    analysis = document_analysis(existing)
    section = "outline" if artifact["artifact_type"] == "episodes" else artifact.get("data", {}).get("section", "body")
    changed_numbers: list[int] = []
    if section == "setting":
        analysis["story_setting_text"] = content
        # A separately adopted setting supersedes metadata recovered from the
        # original body. Do not keep stale genre/hook fields ahead of this text.
        analysis["story_setting_fields"] = StandardScriptParser.parse(content).get("story_setting_fields", {})
        text = old_text
        label = "更新当前剧本 · 故事设定"
    elif section == "outline":
        incoming = artifact["data"]["episodes"]
        outlines = {int(item["episode_num"]): item for item in analysis.get("episode_outlines", [])}
        for item in incoming:
            number = int(item["episode_num"])
            outlines[number] = {"episode_num": number, "title": item["title"], "summary": item.get("summary") or item.get("script_text") or ""}
            changed_numbers.append(number)
        analysis["episode_outlines"] = [outlines[key] for key in sorted(outlines)]
        analysis["script_changes"] = {"section": "outline", "episode_nums": changed_numbers, "assets_need_review": False}
        text = old_text
        label = "更新当前剧本 · " + "、".join(f"第{num}集大纲" for num in changed_numbers)
    else:
        incoming_analysis = parsed_script(content)
        incoming = incoming_analysis.get("episodes") or []
        changed_numbers = [int(item["episode_num"]) for item in incoming]
        old_episodes = analysis.get("episodes") or (parsed_script(old_text).get("episodes") if old_text else []) or []
        known = {int(item["episode_num"]): item for item in old_episodes}
        overlap = set(known) & set(changed_numbers)
        if existing and action != "replace_document":
            if not episode_spans(content):
                raise AssistantConflict("续写或修改分集需要明确的集标题，例如「# 第2集：标题」，请先修订草稿")
            if action == "append_episodes" and overlap:
                raise AssistantConflict("、".join(f"第{num}集" for num in sorted(overlap)) + "已存在，请选择「更新草稿中的分集」")
            if action == "update_episodes" and set(changed_numbers) - set(known):
                raise AssistantConflict("要更新的分集尚不存在，请选择「追加新分集」")
            if not overlap:
                if known and min(changed_numbers, default=0) <= max(known):
                    raise AssistantConflict("新增分集编号应接在已有分集之后，请检查集标题")
                text = old_text + ("\n\n" if old_text else "") + content
            else:
                spans = episode_spans(old_text)
                if not spans:
                    if len(known) != 1 or set(changed_numbers) != set(known):
                        raise AssistantConflict("原剧本缺少明确的集标题，请先整理后再更新分集")
                    text = content
                else:
                    blocks = {int(ep["episode_num"]): ep["body"] for ep in incoming}
                    text = old_text
                    for number, start, end in reversed(spans):
                        if number in blocks:
                            text = text[:start] + blocks[number].rstrip() + ("\n\n" if end < len(old_text) else "") + text[end:]
            for item in incoming:
                known[int(item["episode_num"])] = item
            analysis["episodes"] = [known[number] for number in sorted(known)]
            for key in ("characters", "scenes", "props"):
                analysis[key] = merge_catalog(analysis.get(key) or [], incoming_analysis.get(key) or [])
        else:
            text, analysis = content, incoming_analysis
        label = ("更新" if overlap and existing else "新增") + " · " + "、".join(f"第{num}集" for num in changed_numbers)
        if not changed_numbers:
            label = "保存当前剧本正文"
        if existing:
            analysis["script_changes"] = {"section": "body", "episode_nums": changed_numbers, "assets_need_review": True}
    if len(text) > 500_000:
        raise ValueError("合并后的剧本正文最多 500000 个字符")
    analysis["primary_script"] = True
    values = {
        "filename": (existing or {}).get("filename") or artifact["title"], "file_size": len(text.encode("utf-8")),
        "input_mode": (existing or {}).get("input_mode") or "assistant_v2", "status": "ready",
        "spine_template": (existing or {}).get("spine_template") or "drama", "visual_style": (existing or {}).get("visual_style") or "",
        "raw_text": text, "analysis_json": dumps(analysis),
    }
    return values, label


def ensure_document_idle(conn: Any, project_id: str, row: dict | None) -> None:
    if not row:
        return
    if row.get("status") in {"planning", "analyzing", "processing", "merged"}:
        raise AssistantConflict("当前剧本正在解析、规划或已合并，请完成后重新预览")
    jobs = conn.execute("SELECT payload_json FROM ai_project_jobs WHERE project_id=? AND job_type IN ('shot_plan','document_analysis') AND status IN ('queued','preparing','running')", (project_id,)).fetchall()
    if any(str(json.loads(job["payload_json"] or "{}").get("document_id") or "") == row["id"] for job in jobs):
        raise AssistantConflict("当前剧本正在解析或规划镜头，请完成后重新预览")


def episode_locks(row: dict, productions: list[dict]) -> dict[int, str]:
    analysis = document_analysis(row)
    numbers = {int(ep["episode_num"]) for ep in [*analysis.get("episodes", []), *analysis.get("episode_outlines", [])]}
    result = {int(number): "资产已拆解，本集剧本不可修改" for number in analysis.get("assets_extracted_episode_nums", []) if int(number) in numbers}
    sources = {row.get("id"), *analysis.get("source_document_ids", [])}
    for production in productions:
        number = int(production.get("episode_num") or 0)
        if number not in numbers or production.get("status") in {"deleted", "archived"}:
            continue
        data = production.get("data_json") or {}
        data = json.loads(data) if isinstance(data, str) else data
        if data.get("source_document_id") and data["source_document_id"] not in sources:
            continue
        has_assets = any(beat.get("character_ids") or beat.get("scene_id") or beat.get("prop_ids") or beat.get("video_url") or beat.get("storyboard_image_url") for beat in data.get("beats", []))
        result[number] = "资产已拆解，本集剧本不可修改" if has_assets else "已进入制作工坊，本集剧本不可修改"
    return result


def locked_episodes(conn: Any, project_id: str, row: dict | None) -> dict[int, str]:
    if not row:
        return {}
    productions = conn.execute("SELECT episode_num,status,data_json FROM ai_project_episodes WHERE project_id=?", (project_id,)).fetchall()
    return episode_locks(row, productions)


def _body_blocks(row: dict) -> dict[int, str]:
    text = str(row.get("raw_text") or "")
    spans = episode_spans(text)
    blocks = {number: text[start:end].strip() for number, start, end in spans}
    numbers = {int(ep["episode_num"]) for ep in document_analysis(row).get("episodes", [])}
    # Old single-episode scripts can have only a story title. Its text becomes
    # the prefix before the first explicitly numbered continuation.
    if 1 in numbers and 1 not in blocks:
        blocks[1] = text[:spans[0][1] if spans else len(text)].strip()
    return blocks


def ensure_locked_bodies_unchanged(row: dict, values: dict, locks: dict[int, str]) -> None:
    if not locks or str(values.get("raw_text") or "") == str(row.get("raw_text") or ""):
        return
    before, after = _body_blocks(row), _body_blocks(values)
    for number, reason in locks.items():
        if number not in before or before[number] != after.get(number):
            raise AssistantConflict(f"第{number}集：{reason}")


def remove_script_episode(row: dict, number: int) -> dict:
    analysis = document_analysis(row)
    known = {int(ep["episode_num"]) for ep in [*analysis.get("episodes", []), *analysis.get("episode_outlines", [])]}
    if number not in known:
        raise ValueError("本集不存在或已删除，请刷新剧本")
    text = str(row.get("raw_text") or "")
    spans = episode_spans(text)
    span = next((item for item in spans if item[0] == number), None)
    if span:
        _, start, end = span
        prefix = text[:start]
        if end == len(text):
            prefix = re.sub(r"\r?\n\r?\n$", "", prefix)
        text = prefix + text[end:]
    elif number == 1 and not spans:
        text = ""
    elif any(int(ep["episode_num"]) == number for ep in analysis.get("episodes", [])):
        raise ValueError("本集缺少明确的集标题，请先整理集号")
    for key in ("episodes", "episode_outlines"):
        analysis[key] = [ep for ep in analysis.get(key, []) if int(ep["episode_num"]) != number]
    analysis["script_changes"] = {"section": "body", "kind": "delete", "episode_nums": [number], "assets_need_review": False}
    return {"raw_text": text, "analysis_json": dumps(analysis), "file_size": len(text.encode("utf-8"))}
