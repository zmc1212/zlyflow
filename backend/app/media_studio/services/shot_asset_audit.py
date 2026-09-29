"""Final association audit: no story, dialogue, timing or camera edits allowed."""
from copy import deepcopy
import json

from .asset_pipeline_prompts import adapter, request, strict_object, VERSION
from .workshop_contract import digest, shot_fingerprint


def stamp(beats, source, manifest):
    return digest([source, manifest["version"], [shot_fingerprint(b) for b in beats]])


def validate_audit(result, beats, manifest, source):
    if not isinstance(result, dict) or not isinstance(result.get("shots"), list) or any(not isinstance(s, dict) for s in result["shots"]):
        raise ValueError("INVALID_AUDIT: shots 必须为数组")
    if [s.get("id") for s in result["shots"]] != [b["id"] for b in beats]:
        raise ValueError("INVALID_AUDIT: 核对必须按顺序覆盖每镜，不得改镜数")
    entries = {e["id"]: e for e in manifest["entries"]}
    output = []
    for item, beat in zip(result["shots"], beats):
        if set(item) != {"id", "references", "issues"} or not isinstance(item["references"], list) or not isinstance(item["issues"], list):
            raise ValueError("INVALID_AUDIT: 核对只能返回关联和歧义")
        refs = []
        local = "\n".join(str(beat.get(k) or "") for k in ("action", "dialogue", "opening_state", "closing_state", "scene", "visual_prompt"))
        for ref in item["references"]:
            if not isinstance(ref, dict) or set(ref) != {"manifest_id", "appearance", "location", "evidence"}:
                raise ValueError("INVALID_AUDIT: 关联字段不符合合同")
            if any(not isinstance(ref[k], str) for k in ("manifest_id", "appearance", "location", "evidence")):
                raise ValueError("INVALID_AUDIT: 关联标识、分类、位置和证据必须为字符串")
            entry = entries.get(ref["manifest_id"])
            if not entry:
                raise ValueError("UNKNOWN_ASSET: 模型引用了清单外标识")
            if ref["appearance"] not in {"visible", "offscreen", "mentioned"} or ref["location"] not in {"action", "opening_state", "closing_state", "dialogue", "scene"}:
                raise ValueError("INVALID_AUDIT: 出现方式或位置无效")
            if not isinstance(ref["evidence"], str) or not ref["evidence"].strip() or (ref["evidence"] not in source and ref["evidence"] not in local):
                raise ValueError(f"INVALID_EVIDENCE: 镜头 {beat['id']} 关联 {ref['manifest_id']} 的 evidence 不是连续原文：{ref['evidence']}。只取一段连续逐字引用，禁止拼接动作和对白")
            refs.append({**ref, "asset_id": entry["asset_id"], "look_id": entry.get("look_id"),
                         "kind": entry["kind"], "name": entry["name"], "era": entry.get("era"), "confirmed": False})
        issues = [str(i) for i in item["issues"]]
        # Name scanning is a suspicion detector only, never a visible-role decision.
        for entry in manifest["entries"]:
            if entry["kind"] == "character" and entry["name"] in local and not any(r["asset_id"] == entry["asset_id"] for r in refs):
                issues.append(f"文本含「{entry['name']}」但核对未分类，请确认出镜／画外／提及")
        visible = [r for r in refs if r["appearance"] == "visible"]
        chars = [r for r in visible if r["kind"] == "character"]
        if len({r["asset_id"] for r in chars}) != len(chars):
            issues.append("同一人物存在多个可见造型，请确认")
        if sum(r["kind"] == "scene" for r in visible) > 1:
            issues.append("本镜存在多个场景，请确认主场景或返回规划调整")
        output.append({"id": beat["id"], "references": refs, "issues": list(dict.fromkeys(issues))})
    return output


def project_references(beat, references):
    result = deepcopy(beat)
    visible = [r for r in references if r["appearance"] == "visible"]
    chars = [r for r in visible if r["kind"] == "character"]
    props = [r for r in visible if r["kind"] == "prop"]
    scenes = [r for r in visible if r["kind"] == "scene"]
    result.update(asset_references=deepcopy(references), characters=list(dict.fromkeys(r["name"] for r in chars)),
                  character_ids=list(dict.fromkeys(r["asset_id"] for r in chars)),
                  character_look_ids={r["asset_id"]: r["look_id"] for r in chars if r.get("look_id")},
                  props=list(dict.fromkeys(r["name"] for r in props)), prop_ids=list(dict.fromkeys(r["asset_id"] for r in props)),
                  scene_id=scenes[0]["asset_id"] if scenes else None,
                  workshop_manual_bindings=["character_ids", "prop_ids"])
    # Scene prose describes staging; scene_id is the separately confirmed binding.
    # Replacing prose with a catalog label would also change untouched group boundaries.
    return result


def audit(beats, source, manifest, evidence, checkpoint):
    system = """你是逐镜资产核对员。原剧本、已确认清单和最终镜头为只读；仅修订关联，不改剧情、对白、镜数、运镜或时长。
覆盖静默人物、被看者、背影、手部、开场与收束人物。区分 visible 实际可见、offscreen 画外发声、mentioned 仅提及。
全剧存在不等于每镜可见，跨场不继承演员。姓名匹配不是可见判断，代词需有证据。造型选择以本镜时代为准。
禁止将“几个村民/路人/群体”分配给清单中任意具名角色。原场景没有明确身份对应证据时，只写 issues“群体缺少可证实的资产映射”，references 不得填猜测的身份；不能先猜测绑定再用 issues 免责。
开场/收束状态是本镜画面契约。状态若明确描写互动对象的身体姿态或动作，且运镜把画面带到其所在位置，该对象应判 visible；中景跟随一个人不等于画面只能出现这个人，不能仅因 camera 字段没重复另一人的名字而漏掉收束画面中的人。手部、背影、静默身体同样属于可见。
单独“看着某人”且没有对方身体状态或位置，不足以证明入画；结合具体机位保留待确认。明确画外、仅在对白回忆或提及、构图明确排除的人不能判 visible。不得把全场演员表当本镜画面。
仅用输入 manifest 的 id，不输出数据库 ID。每镜返回所有角色、场景、道具；有歧义写 issues。
返回且只返回 {"shots":[{"id":"输入镜头id","references":[{"manifest_id":"清单id","appearance":"visible|offscreen|mentioned","location":"action|opening_state|closing_state|dialogue|scene","evidence":"原文或本镜逐字引用"}],"issues":[]}]}。"""
    results = []
    for offset in range(0, len(beats), 8):
        batch = beats[offset:offset+8]
        context = {"source": source, "manifest": manifest["entries"], "shots": batch}
        user = json.dumps(context, ensure_ascii=False)
        for attempt in range(2):
            raw = request("asset_audit", system, user, evidence, checkpoint, max_tokens=10000, temperature=0.1)
            try:
                rows = validate_audit(strict_object(raw, {"shots"}), batch, manifest, source)
                evidence[-1]["parsed"] = rows
                if any(r["issues"] for r in rows) and attempt == 0:
                    user = json.dumps(context, ensure_ascii=False) + "\n仅一次有证据纠正；仍有歧义请保留 issues。上一版：" + raw + "\n疑点：" + json.dumps(rows, ensure_ascii=False)
                    continue
                results.extend(rows)
                break
            except ValueError as err:
                evidence[-1]["validation_error"] = str(err)
                if attempt == 1:
                    raise
                user = json.dumps(context, ensure_ascii=False) + "\n上版合同错误：" + str(err) + "\n上版：" + raw
    projected = [project_references(b, row["references"]) for b, row in zip(beats, results)]
    return projected, {"version": VERSION, "manifest_version": manifest["version"], "shots": results,
                       "status": "pending" if any(r["issues"] for r in results) else "passed",
                       "input_fingerprint": stamp(beats, source, manifest)}


def plan_shots(episode, aspect, manifest, workflow_id, evidence, checkpoint):
    from ...workflow_registry import workflow_for, H3_STANDARD_OPTION_SCHEMA
    from .episode_shot_planner import (shot_plan_scene_batches, parse_shot_plan_response, normalize_planned_shots,
        overlapping_shot_windows, build_shot_continuity_refine_system_prompt, build_shot_continuity_refine_user_prompt,
        apply_continuity_window_revision)
    definition = workflow_for(workflow_id)
    rule = ((definition.option_schema or H3_STANDARD_OPTION_SCHEMA).get("properties") or {}).get("duration") or H3_STANDARD_OPTION_SCHEMA["properties"]["duration"]
    spec = adapter("shots")
    evidence.append({"stage": "prompt_source", **{k: v for k, v in spec.items() if k != "system"}})
    system = spec["system"] + "\n本期每镜就是一个可生成单元，单镜时长必须满足以下工作流合同（不能生成短闪剪后拉长）：" + json.dumps(rule, ensure_ascii=False)
    system += '\n仅返回 {"shots":[{"title":"镜头标题","characters":[],"scene":"场景","props":[],"action":"开场：…动作…收束：…","camera":"拍摄意图","dialogue":"逐字对白","audio":"声音","visual_prompt":"画面","opening_state":"姿势空间","closing_state":"姿势空间","transition_note":"动作匹配切","duration_sec":8}]}。角色名和造型从清单取；完整覆盖剧情和对白。'
    system += '\n清单只是可用资产，不是本场演员表。原文未明确对应的无名群体/画外声音保留原称谓，禁止擅自分配给清单中的具名角色。逐字保留对白，也必须保留原说话人身份与不确定性。'
    system += '\nprops 仅列本镜承担独立剧情作用或需辨认独特外观的关键道具；普通衣服、裤裙、鞋、佩饰保留在人物造型与动作，普通杂物陈设保留在场景文字，不列独立道具。仅拿着、穿着、碰触或发声不足以单列；确为原文线索或关键交接物的服饰可例外。不删原文动作、穿着和声音细节，不为参考图额度删改剧情。'
    combined = []
    for batch in shot_plan_scene_batches(episode):
        user = json.dumps({"source": batch, "manifest": manifest["entries"], "aspect_ratio": aspect,
                           "max_references": definition.max_references}, ensure_ascii=False)
        for attempt in range(2):
            raw = request("shot_planning", system, user, evidence, checkpoint, max_tokens=12000, temperature=0.2)
            try:
                parsed = parse_shot_plan_response(raw)
                validate_source_identities(parsed, batch, manifest)
                if not parsed or any(type(s.get("duration_sec")) is not int or not rule.get("minimum", 0) <= s["duration_sec"] <= rule.get("maximum", 999) for s in parsed):
                    raise ValueError("镜头时长超出所选工作流合同")
                import re
                compact = lambda s: re.sub(r"[\W_]+", "", s)
                dialogue = compact("\n".join(str(s.get("dialogue") or "") for s in parsed))
                lines = source_dialogue_lines(str(batch.get("body") or ""))
                if any(compact(line) not in dialogue for line in lines):
                    raise ValueError("镜头遗漏原文对白")
                shots = normalize_planned_shots(parsed, aspect_ratio=aspect)
                # Normalizer's legacy 5–15 clamp must not override this workflow's valid duration.
                if len(shots) != len(parsed):
                    raise ValueError("镜头归一化改变数量，请使用完整可生成镜头")
                for s, original in zip(shots, parsed):
                    s["duration_sec"] = original["duration_sec"]
                evidence[-1]["parsed"] = deepcopy(shots)
                break
            except ValueError as err:
                evidence[-1]["validation_error"] = str(err)
                if attempt:
                    raise
                user += "\n上版错误：" + str(err) + "\n请完整修正：" + raw
        for window in overlapping_shot_windows(shots):
            raw = request("continuity", build_shot_continuity_refine_system_prompt(aspect_ratio=aspect),
                          build_shot_continuity_refine_user_prompt(window), evidence, checkpoint, max_tokens=4000, temperature=0.1)
            shots = apply_continuity_window_revision(shots, parse_shot_plan_response(raw), editable_shot_nums=set(window.get("editable_shot_nums") or []))
            evidence[-1]["parsed"] = deepcopy(shots)
            validate_source_identities(shots, batch, manifest)
        combined.extend(shots)
    for index, shot in enumerate(combined, 1):
        shot["shot_num"] = index
    return combined


def validate_source_identities(shots, episode, manifest):
    """A generated name cannot become its own evidence for a catalog identity."""
    import re
    source = str(episode.get("body") or "")
    for entry in manifest["entries"]:
        if entry.get("kind") != "character":
            continue
        names = [entry.get("name"), *(entry.get("aliases") or [])]
        names = [name for name in names if isinstance(name, str) and name]
        if any(name in source for name in names):
            continue
        for shot in shots:
            narrative = "\n".join(str(shot.get(k) or "") for k in
                                  ("action", "dialogue", "opening_state", "closing_state", "visual_prompt", "audio", "camera"))
            if any(name in (shot.get("characters") or []) or re.search(re.escape(name), narrative) for name in names):
                raise ValueError(f"UNSUPPORTED_IDENTITY: 本场原文未证明角色 {entry['name']} 的身份；不得把无名群体分配给清单具名角色，保留原称谓")


def source_dialogue_lines(source):
    """Quoted speech, including consecutive voices embedded in narration.

    Written labels are visual source facts, not mandatory spoken dialogue.
    """
    import re
    result, previous_end = [], -1
    for match in re.finditer(r'“([^”\n]+)”|"([^"\n]+)"', source):
        prefix = source[source.rfind("\n", 0, match.start()) + 1:match.start()]
        clause = re.split(r"[。！？!?]", prefix)[-1]
        speech = bool(re.search(r"(?:声音|喊声|喊道|喊着|说道|说着|问道|答道|念道|念诵|低语|嘀咕|呼喊|争吵)[^“”\n]{0,18}[：:—\-\s]*$", clause))
        labelled = bool(re.fullmatch(r"[^：:]{1,30}[：:]\s*", prefix))
        written = bool(re.search(r"写着|写有|题着|题为|标注|书名|标题|牌匾", clause)) and not speech
        consecutive = previous_end >= 0 and bool(re.fullmatch(r"[\s，,、；;—\-]*", source[previous_end:match.start()]))
        if (speech or labelled or consecutive) and not written:
            result.append(match.group(1) or match.group(2))
            previous_end = match.end()
        else:
            previous_end = -1
    return result
