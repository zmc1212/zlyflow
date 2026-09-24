"""Story-first Director design, followed by deterministic capacity packing."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .prompt_templates import PromptTemplateError
from .director_plan_quality import beat_duration


def normalize_common_setting(value: dict) -> dict:
    """Compile structured character/visual notes to one immutable text block."""
    def lines(item: Any) -> str:
        if isinstance(item, dict):
            return "\n".join(f"{key}：{lines(text)}" for key, text in item.items())
        if isinstance(item, list):
            return "\n".join(lines(text) for text in item)
        return str(item or "").strip()
    subject = lines(value.get("subject_definitions"))
    if not subject:
        raise PromptTemplateError("导演设计缺少公共设定")
    return {"subject_definitions": subject}


def reference_common_setting(source: dict, request: dict) -> dict | None:
    """Compile selected identities from actual reference slots, not model repetition."""
    assets = {a["id"]: a for a in source.get("assets", [])}
    rows = []
    for slot in request.get("reference_slots") or []:
        asset = assets.get(slot.get("asset_id"), {})
        name = str(slot.get("name") or asset.get("name") or "").strip()
        token = str(slot.get("token") or "").strip()
        if name and token:
            rows.append(f"{token} {name}：以该参考图锁定对应主体的外观，不复制设定板分格。")
    return {"subject_definitions": "\n".join(rows)} if rows else None


def design_prompts(source: dict, facts: dict, request: dict, definition: Any) -> tuple[str, str]:
    source = dict(source)
    selected_ids = {s.get("asset_id") for s in request.get("reference_slots") or []}
    selected_ids.update(b.get("scene_id") for b in source.get("beats", []))
    for beat in source.get("beats", []):
        selected_ids.update(beat.get("character_ids") or [])
        selected_ids.update(beat.get("prop_ids") or [])
    source["assets"] = [{k: a.get(k) for k in ("id", "kind", "name", "description", "visual_prompt")}
                        for a in source.get("assets", []) if a.get("id") in selected_ids]
    return (
        "你是影视导演。阅读本集完整剧本、戏剧目标、资产设定与前后文，先组织镜头再考虑容量，不按秒数均分剧情。"
        "只返回 JSON：{dramatic_intent,visual_strategy,common_setting:{subject_definitions},units:[],quality_notes:[]}。"
        "common_setting 是全剧组共用的人物造型、场景光线与视觉规则；只使用已有参考图 token。"
        "subject_definitions 应为一段完整文字，不是对象。若提供 locked_common_setting 则由程序保留，禁止改写。"
        "每个 unit 是不可再分的完整动作/对白轮次或情绪转折，不为凑目标段数重复事件或空镜。"
        "unit 字段：source_beat_id,event_ids,dialogue_ids,duration_seconds,start_state,handoff_state,"
        "shot_size,camera,movement,performance,dialogue_timing,purpose,scene_key,transition_type。"
        "字段不可省略；event_ids/dialogue_ids 是事实ID字符串数组，duration_seconds 是数字，其余字段是字符串。"
        "无对白时 dialogue_ids=[]、dialogue_timing=无对白；同场下一镜 start_state 逐字复制上一镜 handoff_state。"
        "scene_key 使用明确的地点+时间，同场必须相同；换场或时间跳跃的首单元 transition_type=cut，其余 continuous。"
        "源 Beat 按顺序完整覆盖，事实 ID 只能属于对应 Beat，事件与对白各恰好一次，不改台词。"
        "persistent_states 与 camera_requirements 是可持续复用的约束，不是重复演出的事件。"
        "每个 Beat 单元总秒数等于该 Beat 时长；不要切断一句对白。动作与对白同步时放同一单元。"
        "起幅继承同场前单元落幅（姿势、视线、持物、光线）；转场可以重新建立状态。"
        "每镜说明为什么这样拍，选一个主要运镜，表演与机位必须可同时执行。"
        "不要缩短正常语速、发明剧情或强加动作来适配容量；无法拍完写 quality_notes 的具体风险。",
        json.dumps({"source": source, "facts": facts, "reference_slots": request.get("reference_slots"),
                    "locked_common_setting": request.get("locked_common_setting"),
                    "language": request.get("language"), "aspect_ratio": request.get("aspect_ratio"),
                    "preferred_segment_count": request.get("target_segment_count"),
                    "max_segments_per_part": definition.max_segments, "max_frames_per_part": definition.max_total_frames}, ensure_ascii=False),
    )


def pack_design(design: dict, beats: list[dict], facts: dict, definition: Any, fps: int, *, mixed: bool = False) -> list[dict]:
    from ...dialogue_timing import resolve_shot_duration_sec, estimate_dialogue_duration_sec
    units = design.get("units")
    if not isinstance(units, list) or not units or not design.get("dramatic_intent") or not design.get("visual_strategy"):
        raise PromptTemplateError("导演设计缺少戏剧目的、视觉策略或镜头单元")
    if any(not isinstance(design.get(k), str) for k in ("dramatic_intent", "visual_strategy")):
        raise PromptTemplateError("戏剧目的与视觉策略必须是文字")
    if not isinstance(design.get("quality_notes", []), list) or any(not isinstance(n, str) for n in design.get("quality_notes", [])):
        raise PromptTemplateError("quality_notes 必须为文字数组")
    if not isinstance(design.get("common_setting"), dict) or not design["common_setting"].get("subject_definitions"):
        raise PromptTemplateError("导演设计缺少公共设定")
    max_frames = int(definition.max_total_frames)
    max_segments = int(definition.max_segments)
    beat_order = {str(b["id"]): i for i, b in enumerate(beats)}
    elapsed: Counter = Counter()
    last_beat = -1
    prepared = []
    owners: Counter = Counter()
    for i, raw in enumerate(units):
        if not isinstance(raw, dict) or raw.get("source_beat_id") not in beat_order:
            raise PromptTemplateError("导演设计引用未知分镜")
        bid = raw["source_beat_id"]
        raw = dict(raw)
        if raw.get("dialogue_ids") == [] and not raw.get("dialogue_timing"):
            raw["dialogue_timing"] = "无对白"
        if beat_order[bid] < last_beat:
            raise PromptTemplateError("导演设计改变了剧情先后顺序")
        last_beat = beat_order[bid]
        for key in ("start_state", "handoff_state", "shot_size", "camera", "movement", "performance", "purpose", "scene_key", "dialogue_timing"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise PromptTemplateError(f"导演单元 {i + 1} 缺少 {key}")
        try:
            frames = round(float(raw["duration_seconds"]) * fps)
        except (ValueError, TypeError, KeyError, OverflowError) as err:
            raise PromptTemplateError("导演单元时长无效") from err
        if frames <= 0 or frames >= max_frames:
            raise PromptTemplateError("单个动作超出连续画面容量，请调整分镜或使用逐镜生成")
        refs = {}
        for key, field in (("event_ids", "events"), ("dialogue_ids", "dialogues")):
            lookup = {x["id"]: x for x in facts[bid][field]}
            ids = raw.get(key)
            if not isinstance(ids, list) or any(not isinstance(x, str) or x not in lookup for x in ids):
                raise PromptTemplateError("导演设计包含未知事实 ID")
            owners.update(ids)
            refs[field] = [lookup[x] for x in ids]
        if not refs["events"] and not refs["dialogues"]:
            raise PromptTemplateError("导演设计存在无剧情单元，禁止用空镜凑段数")
        spoken_seconds = sum(estimate_dialogue_duration_sec(x["text"]) for x in refs["dialogues"])
        if spoken_seconds > frames / fps:
            raise PromptTemplateError(f"导演单元 {i + 1} 的对白无法按正常语速演完，需至少 {spoken_seconds:.1f} 秒；请调整分镜时长或使用逐镜生成")
        scene_cut = not prepared or prepared[-1]["scene_key"] != raw["scene_key"] or raw.get("transition_type") == "cut"
        if raw.get("transition_type") not in {"cut", "continuous"}:
            raise PromptTemplateError("导演设计未明确连续或转场")
        if prepared and not scene_cut and raw["start_state"] != prepared[-1]["handoff_state"]:
            raise PromptTemplateError("同场开场状态必须承接上一镜落幅，请统一姿势、视线、持物与空间描述")
        start = elapsed[bid]
        elapsed[bid] += frames
        unit = {**raw, "id": f"story-unit-{i + 1}", "generated_shot_number": i + 1,
                "source_shot_number": beats[beat_order[bid]].get("story_shot") or beat_order[bid] + 1,
                "start_sec": start / fps, "end_sec": elapsed[bid] / fps, "duration_seconds": frames / fps,
                "event_refs": refs["events"], "dialogue_refs": refs["dialogues"],
                "required_events": [x["text"] for x in refs["events"]], "dialogue_owner": [x["text"] for x in refs["dialogues"]],
                "frames": frames, "scene_cut": scene_cut}
        prepared.append(unit)
    expected = {x["id"] for f in facts.values() for kind in ("events", "dialogues") for x in f[kind]}
    if set(owners) != expected or any(v != 1 for v in owners.values()):
        raise PromptTemplateError("剧情动作和对白必须完整覆盖且各分配一次")
    for beat in beats:
        if abs(elapsed[str(beat["id"])] - round(beat_duration(beat) * fps)) > 1:
            raise PromptTemplateError("导演设计改变了分镜总时长，请按完整动作重排或先修改分镜")
    # Partition at scene changes and at capacity. Never force a cut into a continuous Part.
    chunks: list[list[dict]] = []
    for unit in prepared:
        if not chunks or unit["scene_cut"] or len(chunks[-1]) >= max_segments or sum(u["frames"] for u in chunks[-1]) + unit["frames"] > max_frames:
            chunks.append([])
        chunks[-1].append(unit)
    for i, chunk in enumerate(chunks):
        if len(chunk) == 1 and i and not chunk[0]["scene_cut"] and len(chunks[i - 1]) > 2:
            previous = chunks[i - 1]
            if previous[-1]["frames"] + chunk[0]["frames"] <= max_frames:
                chunk.insert(0, previous.pop())
        if len(chunk) < 2 and not mixed:
            raise PromptTemplateError(f"场景「{chunk[0]['scene_key']}」不足以组成至少两段的 Director Part；请调整动作边界或选择逐镜生成")
    parts = []
    for p, chunk in enumerate(chunks, 1):
        segments = [{"id": f"story-segment-{u['generated_shot_number']}", "index": i + 1, "title": u["purpose"],
                     "frame_count": u["frames"], "duration_seconds": u["duration_seconds"], "source_beat_ids": [u["source_beat_id"]],
                     "source_units": [u], "continuity_from_prev": not u["scene_cut"], "story_designed": True} for i, u in enumerate(chunk)]
        parts.append({"id": f"story-part-{p}", "index": p, "frame_count": sum(u["frames"] for u in chunk), "segments": segments,
                      "transition_type": "cut" if chunk[0]["scene_cut"] else "continuous"})
    return parts
