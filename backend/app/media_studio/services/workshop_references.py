"""Resolve live asset references for every v7 reader and command.

This is a pure projection: GET never persists an episode or calls a model.
Commands persist the same projection under the existing episode revision lock.
"""
from copy import deepcopy

from ...workflow_registry import workflow_for
from .character_looks import beat_era, classify_era, look_text


def _look(asset, beat, explicit=None):
    looks = [x for x in (asset.get("extra") or {}).get("identities", []) if isinstance(x, dict)]
    selected = explicit or (beat.get("character_look_ids") or {}).get(asset["id"])
    if selected:
        return next((x for x in looks if x.get("id") == selected), None)
    era = beat_era(beat)
    if era in {"modern", "ancient"}:
        exact = [x for x in looks if classify_era(look_text(x), for_look=True) == era]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return None
        looks = [x for x in looks if classify_era(look_text(x), for_look=True) in {"neutral", "mixed"}]
    return looks[0] if len(looks) == 1 else None


def _slot(asset, beat, explicit=None):
    extra = asset.get("extra") or {}
    look = _look(asset, beat, explicit) if asset["kind"] == "character" else None
    look_id = (look or {}).get("id")
    if asset["kind"] == "character":
        if extra.get("identities") or explicit or (beat.get("character_look_ids") or {}).get(asset["id"]):
            if not look:
                return None, f"「{asset['name']}」造型未明确或已删除，请选择本镜造型"
            url = look.get("image_url")
        else:
            url = extra.get("avatar_url") or asset.get("image_url")
    elif asset["kind"] == "prop":
        url = extra.get("reference_url") or extra.get("turnaround_url") or extra.get("detail_url") or asset.get("image_url")
    else:
        url = extra.get("master_url") or asset.get("image_url")
    if not url:
        label = (look or {}).get("name") or asset["name"]
        return None, f"「{label}」缺少设定图，请到资产库生成或上传"
    return {"asset_id": asset["id"], "look_id": look_id or None, "kind": asset["kind"],
            "name": asset["name"], "image_url": url}, None


def _prop_name_conflicts(beat, asset):
    """Report a semantic mismatch between the script's prop wording and the bound asset name."""
    script_names = [str(n).strip() for n in (beat.get("props") or [])]
    asset_name = str(asset.get("name") or "").strip()
    if not script_names or not asset_name:
        return None
    for script_name in script_names:
        if script_name == asset_name:
            return None
        if script_name in asset_name and len(asset_name) > len(script_name):
            return f"「{script_name}」绑定资产名为「{asset_name}」，语义可能不符，请确认是否重绑"
    return None


def resolve_state(data, assets):
    """Return effective shots and plan, retaining explicit/manual choices.

    Legacy empty groups become automatic; legacy populated groups are manual.
    Names only resolve exact, unique assets; explicit removed bindings stay removed.
    """
    result = deepcopy(data)
    plan = (result.get("prompt_authoring") or {}).get("director_plan") or {}
    if plan.get("schema_version") != 7:
        return result
    by_id = {a["id"]: a for a in assets}
    beats = result.get("beats") or []
    by_beat = {b["id"]: b for b in beats}
    name_issues = {}
    for beat in beats:
        problems = []
        for kind, names_key, ids_key in (("character", "characters", "character_ids"), ("prop", "props", "prop_ids")):
            ids = list(beat.get(ids_key) or [])
            if ids_key not in (beat.get("workshop_manual_bindings") or []):
                for name in beat.get(names_key) or []:
                    matches = [a for a in assets if a.get("kind") == kind and a.get("name", "").strip() == str(name).strip()]
                    if any(a["id"] in ids for a in matches):
                        continue
                    if len(matches) == 1:
                        ids.append(matches[0]["id"])
                    else:
                        problems.append(f"「{name}」资产不存在或有重名，请在本镜明确绑定")
            if ids != (beat.get(ids_key) or []):
                beat[ids_key] = ids
        name_issues[beat["id"]] = problems
    definition = workflow_for(plan["workflow_id"])
    for group in plan.get("groups") or []:
        policy = group.get("reference_policy") or ("manual" if group.get("reference_slots") else "auto")
        group["reference_policy"] = policy
        problems, slots = [], []
        local = [by_beat[bid] for bid in group["beat_ids"] if bid in by_beat]
        if policy == "auto" and definition.max_references:
            for beat in local:
                problems.extend(name_issues[beat["id"]])
                for aid in [*(beat.get("character_ids") or []), *(beat.get("prop_ids") or [])]:
                    asset = by_id.get(aid)
                    if not asset or asset.get("kind") not in {"character", "prop"}:
                        problems.append(f"镜头 {beat.get('sequence', beat['id'])} 的绑定资产不存在，请重新选择")
                        continue
                    slot, error = _slot(asset, beat)
                    if error:
                        problems.append(f"镜头 {beat.get('sequence', beat['id'])}：{error}")
                    elif asset.get("kind") == "prop":
                        conflict = _prop_name_conflicts(beat, asset)
                        if conflict:
                            problems.append(f"镜头 {beat.get('sequence', beat['id'])}：{conflict}")
                        if not any(s["asset_id"] == slot["asset_id"] and s["look_id"] == slot["look_id"] for s in slots):
                            slots.append(slot)
                    elif not any(s["asset_id"] == slot["asset_id"] and s["look_id"] == slot["look_id"] for s in slots):
                        slots.append(slot)
            if len(slots) > definition.max_references:
                problems.append(f"本组关联 {len(slots)} 张设定图，超过工作流上限 {definition.max_references}，请拆组或手动选择")
                slots = []  # Never silently truncate or submit an incomplete selection.
        elif policy == "manual":
            for previous in group.get("reference_slots") or []:
                if not previous.get("asset_id"):
                    slots.append(previous)  # Explicit external image, keep its order and URL.
                    continue
                asset = by_id.get(previous["asset_id"])
                if not asset:
                    problems.append(f"「{previous.get('name') or previous['asset_id']}」参考资产已删除，请重新选择")
                    slots.append(previous)
                    continue
                explicit = previous.get("look_id")
                if not explicit and asset.get("kind") == "character":
                    matches = [x for x in (asset.get("extra") or {}).get("identities", []) if x.get("image_url") and x.get("image_url") == previous.get("image_url")]
                    if len(matches) == 1:
                        explicit = matches[0].get("id")
                slot, error = _slot(asset, local[0] if local else {}, explicit)
                if error:
                    problems.append(error)
                    slots.append(previous)
                    continue
                # Preserve metadata/name representation so existing valid fingerprints survive.
                slots.append({**previous, "image_url": slot["image_url"]})
        if len(slots) < definition.min_references and not problems:
            problems.append(f"本组需要至少 {definition.min_references} 张人物／道具设定图，请绑定资产或手动选择参考")
        group["reference_slots"] = [{**s, "index": i, "token": f"<Picture {i}>"} for i, s in enumerate(slots, 1)]
        group["reference_issues"] = list(dict.fromkeys(problems))
    if definition.prompt_profile == "director_segments":
        from .workshop_h3_skill import ensure_sound_settings
        ensure_sound_settings(plan.get("groups") or [], beats)
    from .workshop_contract import digest, shot_fingerprint
    plan["reference_fingerprint"] = digest([
        [shot_fingerprint(b) for b in beats],
        [{k: g.get(k) for k in ("id", "beat_ids", "reference_slots", "reference_issues")} for g in plan.get("groups") or []],
    ])
    return result


def assert_ready(plan, beat_ids=None):
    wanted = set(beat_ids or [])
    errors = [f"第 {i} 组：{'；'.join(g['reference_issues'])}"
              for i, g in enumerate(plan.get("groups") or [], 1)
              if (not wanted or wanted.intersection(g["beat_ids"])) and g.get("reference_issues")]
    if errors:
        raise ValueError("参考素材尚未就绪：" + "；".join(errors))


def assert_reference_snapshot(plan, request):
    expected = request.get("expected_reference_fingerprint")
    if expected is not None and expected != plan.get("reference_fingerprint"):
        raise ValueError("VERSION_CONFLICT: 参考资产或造型已变化，请刷新后检查再提交")
