"""Validate the editor's small JSON document and derive real asset bindings."""
from __future__ import annotations

import re
from typing import Any


def normalize_workshop_prompt(document: Any, assets: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(asset["id"]): asset for asset in assets}
    references: dict[tuple[str, str], dict[str, Any]] = {}
    nodes = 0
    text_size = 0

    def visit(node: Any, expected: str) -> tuple[dict[str, Any], str]:
        nonlocal nodes, text_size
        nodes += 1
        if nodes > 12000 or not isinstance(node, dict):
            raise ValueError("片段正文格式无效或内容过长")
        kind = node.get("type")
        if expected == "doc" or expected == "paragraph":
            if kind != expected or not isinstance(node.get("content", []), list):
                raise ValueError("片段正文格式无效")
            children = []
            texts = []
            for child in node.get("content", []):
                normalized, text = visit(child, "paragraph" if kind == "doc" else "inline")
                children.append(normalized)
                texts.append(text)
            return {"type": kind, "content": children}, ("\n\n" if kind == "doc" else "").join(texts)
        if kind == "text" and isinstance(node.get("text"), str):
            text = node["text"]
            text_size += len(text)
            if text_size > 120000:
                raise ValueError("片段正文过长，请拆分为多个片段")
            return {"type": "text", "text": text}, text
        if kind == "hardBreak":
            return {"type": "hardBreak"}, "\n"
        if kind != "assetReference" or not isinstance(node.get("attrs"), dict):
            raise ValueError("片段正文包含不支持的节点")
        attrs = node["attrs"]
        asset_id = str(attrs.get("id") or "")
        asset = by_id.get(asset_id)
        if not asset:
            raise ValueError("引用资产已删除或不属于当前工程，请替换引用")
        look_id = str(attrs.get("lookId") or "")
        if look_id:
            looks = (asset.get("extra") or {}).get("identities") or []
            if asset.get("kind") != "character" or not any(str(look.get("id")) == look_id for look in looks if isinstance(look, dict)):
                raise ValueError("引用造型已不可用，请重新选择")
        name = str(asset.get("name") or "")
        if attrs.get("label") != name:
            raise ValueError("资产名称已变化，请刷新资产后重新引用")
        reference = {"id": asset_id, "lookId": look_id or None, "label": name, "kind": asset["kind"]}
        references[(asset_id, look_id)] = reference
        return {"type": "assetReference", "attrs": reference}, name

    normalized, text = visit(document, "doc")
    refs = list(references.values())
    characters = [item for item in refs if item["kind"] == "character"]
    scenes = [item for item in refs if item["kind"] == "scene"]
    props = [item for item in refs if item["kind"] == "prop"]
    for char in characters:
        if any(other["id"] == char["id"] and other["lookId"] != char["lookId"] for other in characters):
            raise ValueError(f"同一片段中的“{char['label']}”请使用同一造型")
    if len(scenes) > 1:
        raise ValueError("一个片段只能绑定一个场景，请拆分片段或将其他场景转为普通文字")
    sections = re.split(r"\n\n+", text)
    def field(label: str) -> str:
        return "\n".join(re.sub(rf"^{label}[：:]\s*", "", section) for section in sections if re.match(rf"^{label}[：:]", section))
    return {
        "workshop_prompt_document": normalized, "video_prompt_zh": text,
        "action": "\n\n".join(section for section in sections if not re.match(r"^(对白|镜头)[：:]", section)),
        "dialogue": field("对白"), "camera": field("镜头"), "dialogue_turns": [],
        "character_ids": [item["id"] for item in characters],
        "characters": [item["label"] for item in characters],
        "character_look_ids": {item["id"]: item["lookId"] for item in characters if item["lookId"]},
        "character_look_id": characters[0]["lookId"] if characters else None,
        "scene_id": scenes[0]["id"] if scenes else None,
        "scene": scenes[0]["label"] if scenes else "",
        "prop_ids": [item["id"] for item in props], "props": [item["label"] for item in props],
    }


def invalidate_changed_prompt(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    if "workshop_prompt_document" not in updates:
        return updates
    keys = ("video_prompt_zh", "character_ids", "character_look_ids", "scene_id", "prop_ids")
    if any(target.get(key) != updates.get(key) for key in keys):
        return {**updates, "h3_prompt": None, "h3_prompt_source": "", "timestamped_zh_prompt": "", "authored_en_valid": False}
    return updates
