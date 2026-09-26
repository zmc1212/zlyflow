"""Pure, versioned episode production model. No database or media side effects."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any

MODES = {"shot", "director"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:24]


def asset_fingerprint(assets: list[dict], beats: list[dict]) -> str:
    referenced = {str(i) for b in beats for key in ("character_ids", "prop_ids") for i in (b.get(key) or [])}
    referenced.update(str(b.get("scene_id")) for b in beats if b.get("scene_id"))
    return digest(sorted([
        {"id": a["id"], "image_url": a.get("image_url"), "description": a.get("description"),
         "visual_prompt": a.get("visual_prompt"), "identities": (a.get("extra") or {}).get("identities"),
         "master_url": (a.get("extra") or {}).get("master_url"),
         "reference_url": (a.get("extra") or {}).get("reference_url")}
        for a in assets if str(a["id"]) in referenced
    ], key=lambda a: a["id"]))


def plan_context(detail: dict, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("未知制作方式")
    authoring = detail.get("prompt_authoring") or {}
    unified_plan = authoring.get("director_plan") or {}
    if unified_plan.get("schema_version") == 7:
        from .workshop_contract import shot_fingerprint
        beats = detail.get("beats") or []
        groups = {bid: g for g in unified_plan["groups"] for bid in g["beat_ids"]}
        return {"key": digest([unified_plan["id"], [(b["id"], shot_fingerprint(b)) for b in beats]]),
                "revision": unified_plan["revision"], "stale": not bool(beats), "snapshot": deepcopy(unified_plan),
                "units": [{"id": b["id"], "title": b.get("heading") or b["id"], "part_id": groups.get(b["id"], {}).get("id", ""),
                           "source_beat_ids": [b["id"]], "duration": b.get("video_duration", 8)} for b in beats]}
    if mode == "director":
        plan = authoring.get("director_plan") or {}
        units = [
            {"id": s["id"], "title": s.get("title") or f"段 {s.get('index', i + 1)}",
             "part_id": p["id"], "render_mode": p.get("render_mode", "director"),
             "workflow_id": p.get("workflow_id"), "source_beat_ids": s.get("source_beat_ids") or [],
             "duration": s.get("duration_seconds", 0)}
            for p in plan.get("parts", []) for i, s in enumerate(p.get("segments", []))
        ]
        return {"key": digest([plan.get("id"), plan.get("revision"), plan.get("source_fingerprint")]),
                "revision": plan.get("revision"), "units": units,
                "stale": not plan or plan.get("status") != "current", "snapshot": deepcopy(plan)}
    beats = sorted(detail.get("beats") or [], key=lambda b: int(b.get("sequence") or 0))
    fields = ("id", "sequence", "heading", "action", "dialogue", "dialogue_turns", "speaker", "camera",
              "scene", "scene_id", "character_ids", "character_look_ids", "prop_ids", "video_duration",
              "h3_prompt", "h3_prompt_context_fingerprint", "render_url", "triptych_url",
              "video_prompt_zh", "timestamped_zh_prompt", "visual_prompt", "visible_text", "narration",
              "voiceover", "audio", "soundscape", "duration_sec", "duration_seconds", "frame_count")
    source = [{k: b.get(k) for k in fields} for b in beats]
    records = authoring.get("full_reference") or {}
    references = {k: {"source_fingerprint": r.get("source_fingerprint"), "reference_slots": r.get("reference_slots")} for k, r in records.items()}
    return {"key": digest([detail.get("script_text"), source, detail.get("production_asset_fingerprint"), references]), "revision": None,
            "units": [{"id": b["id"], "title": b.get("heading") or f"来源分镜 {i + 1}",
                       "part_id": "", "source_beat_ids": [b["id"]], "duration": b.get("video_duration", 8)}
                      for i, b in enumerate(beats)],
            "stale": any(r.get("status") == "stale" for r in records.values()) or
                     any(b.get("h3_prompt_reference_state") in {"stale", "legacy_stale", "invalid"} for b in beats), "snapshot": source}


def version(state: dict, mode: str, key: str) -> dict:
    return state["modes"][mode]["versions"].setdefault(key, {"adopted": {}, "audio": [], "exports": []})


def register_material(state: dict, mode: str, material: dict, *, auto_adopt: bool = True) -> None:
    materials = state["modes"][mode]["materials"]
    if any(m["id"] == material["id"] for m in materials):
        return
    materials.append(deepcopy(material))
    v = version(state, mode, material["plan_key"])
    # Never partially auto-adopt a selection, and never replace an existing take.
    if auto_adopt and not any(u in v["adopted"] for u in material["unit_ids"]):
        v["adopted"].update({u: material["id"] for u in material["unit_ids"]})


def carry_unchanged_director_materials(state: dict, previous: dict, current: dict) -> int:
    """Copy verified adopted takes into a new plan only when group inputs and output match."""
    if not state or not previous or not current or int(previous.get("schema_version") or 0) != 5 or int(current.get("schema_version") or 0) != 5:
        return 0
    mode = (state.get("modes") or {}).get("director") or {}
    materials = mode.get("materials") or []
    versions = mode.get("versions") or {}
    old_key = digest([previous.get("id"), previous.get("revision"), previous.get("source_fingerprint")])
    new_key = digest([current.get("id"), current.get("revision"), current.get("source_fingerprint")])
    old_adopted = (versions.get(old_key) or {}).get("adopted") or {}
    if not old_adopted or old_key == new_key:
        return 0
    old_groups = {g.get("id"): g for g in previous.get("source_groups") or []}
    new_groups = {g.get("id"): g for g in current.get("source_groups") or []}
    old_parts_by_group: dict[str, list[dict]] = {}
    for part in previous.get("parts") or []:
        old_parts_by_group.setdefault(str(part.get("source_group_id") or ""), []).append(part)
    segment_map = {}
    seen_groups: dict[str, int] = {}
    for part in current.get("parts") or []:
        group_id = str(part.get("source_group_id") or "")
        group_position = seen_groups.get(group_id, 0)
        seen_groups[group_id] = group_position + 1
        prior_parts = old_parts_by_group.get(group_id) or []
        old = prior_parts[group_position] if group_position < len(prior_parts) else None
        if not old or not group_id:
            continue
        if not old_groups.get(group_id, {}).get("fingerprint") or old_groups[group_id]["fingerprint"] != new_groups.get(group_id, {}).get("fingerprint"):
            continue
        if any(old.get(key) != part.get(key) for key in ("render_mode", "workflow_id", "execution_options", "reference_slots")):
            continue
        old_segments, new_segments = old.get("segments") or [], part.get("segments") or []
        if len(old_segments) != len(new_segments):
            continue
        if any(any(a.get(key) != b.get(key) for key in ("prompt_text", "frame_count", "source_beat_ids"))
               for a, b in zip(old_segments, new_segments)):
            continue
        segment_map.update({a["id"]: b["id"] for a, b in zip(old_segments, new_segments)})
    if not segment_map:
        return 0
    target = versions.setdefault(new_key, {"adopted": {}, "audio": [], "exports": []})["adopted"]
    copied = 0
    for material in list(materials):
        ids = material.get("unit_ids") or []
        if material.get("plan_key") != old_key or not material.get("verified") or not ids or any(sid not in segment_map for sid in ids):
            continue
        if any(old_adopted.get(sid) != material.get("id") for sid in ids):
            continue
        mapped = [segment_map[sid] for sid in ids]
        if any(sid in target for sid in mapped):
            continue
        carried = deepcopy(material)
        carried.update(id="carried-" + digest([material["id"], new_key, mapped]), plan_key=new_key,
                       unit_ids=mapped, carried_from=material["id"])
        carried["ranges"] = {segment_map.get(sid, sid): value for sid, value in (material.get("ranges") or {}).items()}
        materials.append(carried)
        target.update({sid: carried["id"] for sid in mapped})
        copied += 1
    return copied


def carry_workshop_materials(state: dict, previous: dict, current: dict) -> dict:
    """Reuse by explicit identity and unchanged structure, never segment array position.

    Old versions and ambiguous takes remain intact. Only verified per-shot ranges or
    complete single-shot clips can enter the current selection automatically.
    """
    from .workshop_contract import shot_fingerprint
    state = deepcopy(state)
    key = plan_context(current, "director")["key"]
    if ((previous.get("prompt_authoring") or {}).get("director_plan") or {}).get("schema_version") == 7 and plan_context(previous, "director")["key"] == key:
        return state
    target = version(state, "director", key)
    old_beats = {b["id"]: b for b in previous.get("beats") or []}
    unchanged = {b["id"] for b in current.get("beats") or [] if b["id"] in old_beats and shot_fingerprint(b) == shot_fingerprint(old_beats[b["id"]])}
    old_plan = (previous.get("prompt_authoring") or {}).get("director_plan") or {}
    segments = [s for p in old_plan.get("parts", []) for s in p.get("segments", [])]
    occurrences = {}
    for segment in segments:
        for bid in segment.get("source_beat_ids") or []:
            occurrences[bid] = occurrences.get(bid, 0) + 1
    mapping = {s["id"]: s["source_beat_ids"][0] for s in segments if len(s.get("source_beat_ids") or []) == 1 and occurrences[s["source_beat_ids"][0]] == 1}
    choices = {}
    for mode in sorted(MODES):
        old_key = plan_context(previous, mode)["key"]
        old_version = version(state, mode, old_key)
        for material in list(state["modes"][mode]["materials"]):
            if material.get("plan_key") != old_key:
                continue
            ids = material.get("unit_ids") or []
            mapped = [mapping.get(i) if mode == "director" and old_plan.get("schema_version") != 7 else i for i in ids]
            if not ids or any(i is None for i in mapped) or len(set(mapped)) != len(mapped):
                continue
            if len(ids) > 1 and (not material.get("verified") or any(i not in (material.get("ranges") or {}) for i in ids)):
                continue
            retained = [(old_id, bid) for old_id, bid in zip(ids, mapped) if bid in unchanged]
            if not retained:
                continue
            ids, mapped = [x[0] for x in retained], [x[1] for x in retained]
            carried = deepcopy(material)
            carried.update(id="carried-" + digest([material["id"], key, mapped]), plan_key=key, unit_ids=mapped, carried_from=material["id"])
            carried["ranges"] = {mapped[ids.index(i)]: r for i, r in (material.get("ranges") or {}).items() if i in ids}
            register_material(state, "director", carried, auto_adopt=False)
            for old_id, bid in zip(ids, mapped):
                if old_version["adopted"].get(old_id) == material["id"]:
                    choices.setdefault(bid, []).append(carried["id"])
            for audio in old_version.get("audio") or []:
                if audio.get("material_id") == material["id"] and all(i in ids for i in audio.get("unit_ids", [])):
                    copied = deepcopy(audio)
                    copied.update(id="carried-" + digest([audio["id"], key]), material_id=carried["id"], unit_ids=[mapped[ids.index(i)] for i in audio.get("unit_ids", [])])
                    if not any(a["id"] == copied["id"] for a in target["audio"]):
                        target["audio"].append(copied)
    for bid, candidates in choices.items():
        if len(set(candidates)) == 1:
            target["adopted"].setdefault(bid, candidates[0])
    target["audio"] = [a for a in target["audio"] if all(target["adopted"].get(i) == a["material_id"] for i in a.get("unit_ids", []))]
    state.update(schema_version=2, active_mode="director")
    state["revision"] += 1
    return state


def hydrate(detail: dict) -> dict:
    """Compatibility projection; persisted by the next locked mutation, never by GET."""
    data = detail.get("data") or {}
    state = deepcopy(data.get("production") or {})
    if state.get("schema_version") not in (None, 1, 2):
        raise ValueError("制作数据版本不受支持")
    state.setdefault("schema_version", 1)
    state.setdefault("revision", 0)
    state.setdefault("active_mode", "director" if (detail.get("prompt_authoring") or {}).get("director_plan") else "shot")
    state.setdefault("modes", {})
    for mode in sorted(MODES):
        state["modes"].setdefault(mode, {"versions": {}, "materials": []})
        context = plan_context(detail, mode)
        version(state, mode, context["key"])
    if not state.get("legacy_imported"):
        shot_key = plan_context(detail, "shot")["key"]
        for b in detail.get("beats") or []:
            takes = list(b.get("video_takes") or [])
            if b.get("video_url") and not any(t.get("url") == b["video_url"] for t in takes):
                takes.append({"url": b["video_url"], "id": b.get("video_take_id")})
            for take in takes:
                if not take.get("url"):
                    continue
                m = {"id": "legacy-" + digest([b["id"], take["url"]]), "plan_key": shot_key,
                     "unit_ids": [b["id"]], "url": take["url"], "job_id": take.get("job_id", ""),
                     "ranges": {}, "duration": None, "verified": False, "legacy": True,
                     "title": b.get("heading") or b["id"]}
                register_material(state, "shot", m, auto_adopt=False)
                if take["url"] == b.get("video_url"):
                    version(state, "shot", shot_key)["adopted"][b["id"]] = m["id"]
        plan = (detail.get("prompt_authoring") or {}).get("director_plan") or {}
        key = plan_context(detail, "director")["key"]
        for p in plan.get("parts", []):
            renders = list(p.get("renders", []))
            renders.extend({"url": s["video_url"], "job_id": s.get("video_job_id"), "segment_ids": [s["id"]]}
                           for s in p.get("segments", []) if s.get("video_url") and not any(r.get("url") == s["video_url"] for r in renders))
            for render in renders:
                if not render.get("url") or not render.get("segment_ids"):
                    continue
                old = (detail.get("legacy_director_jobs") or {}).get(render.get("job_id")) or {}
                attributable = (old.get("director_plan_id") == plan.get("id")
                                and old.get("director_plan_revision") == plan.get("revision")
                                and old.get("segment_ids") == render["segment_ids"])
                register_material(state, "director", {
                    "id": "legacy-" + digest([render.get("job_id"), render["url"]]),
                    "plan_key": key if attributable else "unattributed-" + digest(render.get("job_id")),
                    "unit_ids": render["segment_ids"], "url": render["url"], "job_id": render.get("job_id", ""),
                    "ranges": {}, "duration": None, "verified": False, "legacy": True, "title": "历史连续选区",
                }, auto_adopt=False)
        historical = detail.get("legacy_director_output") or {}
        payload = historical.get("payload") or {}
        ids = [str(s.get("beat_id")) for s in payload.get("source_shots", [])]
        expected_ids = [u["id"] for u in plan_context(detail, "director")["units"]]
        if (historical.get("url") and ids and ids == expected_ids and payload.get("director_plan_id") == plan.get("id")
                and payload.get("director_plan_revision") == plan.get("revision")):
            m = {"id": "legacy-" + digest(historical["url"]), "plan_key": key,
                 "unit_ids": ids, "url": historical["url"], "job_id": historical.get("job_id", ""),
                 "ranges": {}, "duration": None, "verified": False, "legacy": True, "title": "历史 Director 整片"}
            register_material(state, "director", m)
            v = version(state, "director", key)
            v["exports"].append({"url": historical["url"], "job_id": historical.get("job_id"),
                                 "fingerprint": fingerprint(v), "source": "legacy_director"})
        # Unattributed episode films remain viewable history, not fabricated segment takes.
        state["legacy_exports"] = ([{"url": data["episode_video_url"], "job_id": data.get("episode_video_job_id"),
                                    "title": "历史成片（未验证分段边界）"}] if data.get("episode_video_url") else [])
        state["legacy_imported"] = True
    if ((detail.get("prompt_authoring") or {}).get("director_plan") or {}).get("schema_version") == 7:
        state["schema_version"] = 2
        state["active_mode"] = "director"
    return state


def timeline(state: dict, mode: str, context: dict) -> tuple[list[dict], list[str]]:
    v = version(state, mode, context["key"])
    materials = {m["id"]: m for m in state["modes"][mode]["materials"]}
    groups: list[dict] = []
    missing = []
    for unit in context["units"]:
        material = materials.get(v["adopted"].get(unit["id"]))
        if not material or material.get("plan_key") != context["key"]:
            missing.append(unit["title"])
            continue
        if groups and groups[-1]["material_id"] == material["id"]:
            groups[-1]["unit_ids"].append(unit["id"])
        else:
            groups.append({"material_id": material["id"], "unit_ids": [unit["id"]], "url": material["url"]})
    for g in groups:
        m = materials[g["material_id"]]
        ranges = m.get("ranges") or {}
        if m.get("verified") and all(u in ranges for u in g["unit_ids"]):
            g["start"] = ranges[g["unit_ids"][0]]["start"]
            g["end"] = ranges[g["unit_ids"][-1]]["end"]
            g["whole"] = g["unit_ids"] == m["unit_ids"]
        elif g["unit_ids"] == m["unit_ids"]:
            g.update(start=0, end=m.get("duration"), whole=True)
        else:
            missing.append("历史整片缺少可靠切点，请重做完整 Part 或整片")
        g["duration"] = (g.get("end") - g.get("start", 0)) if g.get("end") is not None else None
    return groups, missing


def adopt(state: dict, detail: dict, mode: str, material_id: str) -> None:
    context = plan_context(detail, mode)
    if context["stale"]:
        raise ValueError("当前方案已过期，请先更新方案")
    m = next((m for m in state["modes"][mode]["materials"] if m["id"] == material_id), None)
    if not m or m["plan_key"] != context["key"]:
        raise ValueError("素材不属于当前制作方案")
    ids = [u["id"] for u in context["units"]]
    positions = [ids.index(u) for u in m["unit_ids"] if u in ids]
    if not positions or len(positions) != len(m["unit_ids"]) or positions != list(range(min(positions), max(positions) + 1)):
        raise ValueError("素材覆盖范围无效")
    v = version(state, mode, context["key"])
    before = deepcopy(v["adopted"])
    v["adopted"].update({u: material_id for u in m["unit_ids"]})
    _, errors = timeline(state, mode, context)
    if any("切点" in e for e in errors):
        v["adopted"] = before
        raise ValueError("旧素材没有可靠切点，不能局部替换；请重做完整 Part 或整片")
    for audio in v["audio"]:
        if any(before.get(u) != v["adopted"].get(u) for u in audio.get("unit_ids", [])):
            audio["needs_alignment"] = True


def fingerprint(v: dict) -> str:
    return digest([v["adopted"], v["audio"]])


def summary(detail: dict, state: dict | None = None, mode: str | None = None) -> dict:
    state = state or hydrate(detail)
    if state.get("schema_version") == 2:
        mode = "director"
    mode = mode or state["active_mode"]
    if mode not in MODES:
        raise ValueError("未知制作方式")
    c = plan_context(detail, mode)
    v = version(state, mode, c["key"])
    clips, missing = timeline(state, mode, c)
    reasons = []
    if not c["units"]:
        reasons.append("请先准备本集制作方案")
    if c["stale"]:
        reasons.append("方案已过期，请根据当前剧本与资产更新")
    if missing:
        reasons.append("待补齐画面：" + "、".join(missing))
    for a in v["audio"]:
        if a.get("enabled", True) and a.get("needs_alignment"):
            reasons.append("补配画面已变化，请重新对齐声音")
    exports = v["exports"]
    current = next((e for e in reversed(exports) if e.get("fingerprint") == fingerprint(v)), None)
    return {"schema_version": state["schema_version"], "revision": state["revision"], "active_mode": mode,
            "plan_key": c["key"], "plan_revision": c["revision"], "plan_stale": c["stale"],
            "units": c["units"], "materials": state["modes"][mode]["materials"], "adopted": v["adopted"],
            "audio": v["audio"], "timeline": clips, "exports": exports,
            "legacy_exports": state.get("legacy_exports", []) + [e for key, old in state["modes"][mode]["versions"].items() if key != c["key"] for e in old["exports"]], "current_export": current,
            "ready": not reasons, "block_reasons": list(dict.fromkeys(reasons)),
            "needs_export": not current or c["stale"], "fingerprint": fingerprint(v)}


def validate_audio(state: dict, detail: dict, mode: str, records: list[dict]) -> list[dict]:
    from .dubbing_lines import expand_episode_lines
    lines = {line["id"]: line for line in expand_episode_lines(detail.get("beats") or [], [])}
    c = plan_context(detail, mode)
    v = version(state, mode, c["key"])
    materials = {m["id"]: m for m in state["modes"][mode]["materials"]}
    clips, _ = timeline(state, mode, c)
    result = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("声音编排格式无效")
        existing = next((a for a in v["audio"] if a["id"] == record.get("id")), None)
        if existing and all(record.get(k) == existing.get(k) for k in existing if k != "enabled"):
            result.append({**existing, "enabled": bool(record.get("enabled", True))})
            continue
        line = lines.get(record.get("line_id"))
        material = materials.get(record.get("material_id"))
        if not line or not material or not line.get("audio_url") or line.get("status") != "ready":
            raise ValueError("请先生成可用配音并选择已采用的画面")
        start, end = float(record.get("start", 0)), float(record.get("end", 0))
        if not all(math.isfinite(n) for n in (start, end)) or start < 0 or end <= start:
            raise ValueError("声音时间区间无效")
        clip = next((g for g in clips if g["material_id"] == material["id"]
                     and g.get("end") is not None and start >= g["start"] and end <= g["end"] + .001), None)
        if not clip:
            raise ValueError("声音必须落在已采用且已验证时长的素材区间内")
        duration = float(line.get("duration_sec") or 0)
        if duration <= 0 or duration > end - start + .001:
            raise ValueError("配音长度超过所选区间，请调整区间或重新配音；不会截断台词")
        ranges = material.get("ranges") or {}
        unit_ids = [u for u in clip["unit_ids"] if u not in ranges or
                    (ranges[u]["start"] < end and ranges[u]["end"] > start)]
        source_ids = {b for u in c["units"] if u["id"] in unit_ids for b in u["source_beat_ids"]}
        if line.get("beat_id") not in source_ids:
            raise ValueError("所选画面与台词来源不一致")
        mix = record.get("mix", "overlay")
        if mix not in {"overlay", "replace"}:
            raise ValueError("未知混音方式")
        result.append({"id": record.get("id") or "audio-" + digest([line["id"], material["id"], start]),
                       "line_id": line["id"], "material_id": material["id"], "unit_ids": unit_ids,
                       "source_beat_id": line.get("beat_id"), "text": line.get("text"),
                       "audio_url": line["audio_url"], "duration": duration, "start": start, "end": end,
                       "mix": mix, "enabled": bool(record.get("enabled", True)), "needs_alignment": False})
    if len({a["id"] for a in result}) != len(result):
        raise ValueError("声音条目重复")
    return result
