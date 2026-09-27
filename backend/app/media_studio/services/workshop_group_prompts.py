"""One author, complete group drafts, bounded repairs and durable evidence."""
from copy import deepcopy
from difflib import unified_diff
import json
import re
import time

from ...workflow_registry import workflow_for
from . import workshop_contract as contract
from .llm_service import LlmService
from .workshop_h3_skill import split_complete_group_draft, writing_contract_snapshot, AUTHORING_VERSION, DIALOGUE_TAIL_SECONDS, voice_map, source_dialogues
from .workshop_review import review_group
from .workshop_direct_input import dialogues_match, sha
from .workshop_h3_skill import DIRECT_VERSIONS


def is_director(plan):
    return workflow_for(plan["workflow_id"]).prompt_profile == "director_segments"


def expand_groups(plan, ids):
    selected = set(ids)
    return [bid for group in plan["groups"] if selected.intersection(group["beat_ids"])
            for bid in group["beat_ids"]]


def _creative_body(body):
    # Only container/time representation is normalized, never creative content.
    return re.sub(r"(?m)^\s*detailed_description\s*[:：]\s*|\[Shot \d+\]\s*\d+:\d+(?:\.\d+)?[–—-]\d+:\d+(?:\.\d+)?", "", body).strip()


def _performance_requirements(ordered):
    # Repeat executable constraints next to the actual input, including retries
    # using an immutable older system snapshot. Never rewrite the model's draft.
    dialogue_rows = [
        {"beat_id": beat["id"], "逐字对白": [
            {"说话人": owner, "原文": text.strip()}
            for owner, text in source_dialogues(beat)]}
        for beat in ordered]
    return ("\n逐镜对白核对：" + json.dumps(dialogue_rows, ensure_ascii=False)
            + "\n每句对白须在其自己的时间窗内重新写出姓名 (S数字)，紧随本句时间标记，"
              "再写动作、音量和语速及 <d>[中文] 原文</d>；前一个动作窗中的姓名或编号不算本句归属。"
              "原文及标点逐字保留，不增删引号。逐字对白为空的镜头不写 (S数字) 或 <d>，只用姓名/Subject 描述动作。"
            + f"最后对白之后单独安排至少 {DIALOGUE_TAIL_SECONDS:g} 秒的无对白收束时间窗，"
              "明确写出闭口或静默，并描述具体承接姿态；只有停顿、嘴唇动作或姿态而未明确静默不够。")


def generate_group(plan, group, beats, *, revision_beat_id=None, revision_note="", source_text="",
                   author=None, fact_extraction=None, audit=None, contract_snapshot=None, checkpoint=None):
    ordered = [next(b for b in beats if b["id"] == bid) for bid in group["beat_ids"]]
    targets = [b for b in ordered if not revision_beat_id or b["id"] == revision_beat_id]
    if not targets:
        raise ValueError("返修镜头不在当前组内")
    audit = plan if audit is None else audit
    snapshot = contract_snapshot or writing_contract_snapshot(source_text, contract.group_timecode_mode(group))
    if snapshot["version"] not in {AUTHORING_VERSION, *DIRECT_VERSIONS}:
        raise ValueError("任务写稿合同版本不受支持，请创建新任务；旧候选保留")
    direct = snapshot["version"] in DIRECT_VERSIONS
    system = snapshot["system"]
    slots = group.get("reference_slots") or []
    all_ids = [b["id"] for b in beats]
    first, last = all_ids.index(ordered[0]["id"]), all_ids.index(ordered[-1]["id"])
    neighbors = beats[max(0, first - 1):first] + beats[last + 1:last + 2]
    user = json.dumps({"画幅": plan["aspect_ratio"], "现有公共设定（候选可改善，采纳前不覆盖）": group.get("common_prompt"),
                       "显式锁定原文": group.get("locked_common_lines") or [],
                       "有序镜头": ordered, "前后镜上下文": neighbors, "有序参考图": slots,
                       "目标镜头": [b["id"] for b in targets]}, ensure_ascii=False)
    user += "\n完整稿编号 1..N 连续；逐镜时间要求：" + json.dumps([
        {"beat_id": b["id"], "draft_shot_number": i + 1,
         "start": contract.shot_header(b, group, ordered)[1], "end": contract.shot_header(b, group, ordered)[2]}
        for i, b in enumerate(ordered)], ensure_ascii=False)
    if revision_beat_id:
        user += "\n只返修目标镜头，完整返回整组；公共设定及其他镜正文逐字冻结。需要改共享设置时不得擅改，应说明需整组返修。返修意见：" + revision_note
        user += "\n同组已采纳正文：" + json.dumps({b["id"]: plan.get("shot_prompts", {}).get(b["id"], {}) for b in ordered}, ensure_ascii=False)
    images = [s["image_url"] for s in slots]
    for beat in ordered:
        refs = beat.get("workshop_writing_refs") or []
        if refs:
            user += f"\n随后附加的 {len(refs)} 张图片只供镜头 {beat['id']} 写稿参考，不分配 Picture 编号。"
            images.extend(refs)
    if direct:
        user = snapshot["user"]
        if sha(system) != snapshot["system_sha256"] or sha(user) != snapshot["user_sha256"] or contract.digest([system, user, images]) != snapshot["input_sha256"]:
            raise ValueError("写稿输入或参考图片与冻结快照不一致，请创建新任务")
        if fact_extraction:
            raise ValueError("纯 Skill 合同需要作者直接读取材料，不支持额外模型改写输入")
    else:
        user += _performance_requirements(ordered)
    base_user = user
    history = audit.setdefault("writing_history", [])
    seen, best, previous_raw = set(), None, ""
    def save():
        if checkpoint:
            checkpoint()
    for attempt in range(1 if direct else 3):
        entry = {"attempt": attempt + 1, "group_id": group["id"], "revision_beat_id": revision_beat_id,
                 "contract_version": snapshot["version"], "skill_sha256": snapshot["skill_sha256"],
                 "input": user, "image_urls": [] if direct else images, "raw": "", "errors": [], "reason": None}
        if direct:
            entry.update(image_hashes=snapshot["image_hashes"], input_sha256=snapshot["input_sha256"],
                         origin="manual_revision" if revision_beat_id else "initial", content_call_count=1)
        history.append(entry)
        started = time.monotonic()
        try:
            if len(system) + len(user) > 180000:
                raise ValueError("完整上下文超过本任务 180000 字符预算，未静默裁剪；请缩小镜头组或明确裁剪方案")
            raw, call_meta = LlmService.author_group(system, user, images, author=author, fact_extraction=fact_extraction,
                                                     max_tokens=24000, temperature=0.2)
        except Exception as err:
            entry.update(reason="作者调用失败", errors=[str(err)],
                         author={"requested_model": (author or {}).get("model"), "actual_model": None, "ok": False,
                                 "elapsed_ms": int((time.monotonic()-started)*1000), "fallback_from": None,
                                 **getattr(err, "author_meta", {})})
            save()
            raise
        entry.update(raw=raw, author=call_meta, diff="\n".join(unified_diff(previous_raw.splitlines(), raw.splitlines(), lineterm="")))
        candidates, errors, fatal = {}, [], False
        try:
            parsed = split_complete_group_draft(raw, ordered, group=group)
        except ValueError as err:
            parsed = None
            errors = [f"完整稿格式无法解析：{err}"]
        if parsed:
            effective = {**group, "common_prompt": parsed["common_prompt"], "contract_version": snapshot["version"]}
            names = [owner for beat in ordered for owner, _ in source_dialogues(beat) if owner]
            old_voices = dict(voice_map(group.get("common_prompt", ""), names))
            new_voices = dict(voice_map(parsed["common_prompt"], names))
            if snapshot["version"] != "h3-skill-direct-v3" and (not direct or revision_beat_id) and any(name in new_voices and new_voices[name] != number for name, number in old_voices.items()):
                errors.append("人物声音编号归属不可改变，请沿用原有姓名与 S 编号")
            if not parsed["common_prompt"]:
                errors.append("完整稿缺少公共主体与声音设定")
            for locked in group.get("locked_common_lines") or []:
                if locked not in parsed["common_prompt"]:
                    errors.append("违反显式锁定的公共设定：" + locked)
                    fatal = True
            if revision_beat_id:
                if parsed["common_prompt"].strip() != str(group.get("common_prompt") or "").strip():
                    errors.append("需整组返修：单镜返修不得修改公共主体或声音设定")
                    fatal = True
                for beat, body in zip(ordered, parsed["shots"]):
                    old = plan.get("shot_prompts", {}).get(beat["id"], {}).get("h3_prompt")
                    if beat["id"] != revision_beat_id and old and _creative_body(body) != _creative_body(old):
                        errors.append(f"需整组返修：非目标镜头 {beat['id']} 被修改")
                        fatal = True
            review = review_group(ordered, parsed["shots"], effective)
            entry["parsed"] = parsed
            entry["review"] = review
            for beat, body in zip(ordered, parsed["shots"]):
                if revision_beat_id and beat["id"] != revision_beat_id:
                    continue
                errors.extend(f"镜头 {beat['id']}：{e}" for e in contract.prompt_checks(body, beat, effective, h3=True, ordered_beats=ordered))
                expected_dialogue = [text.strip() for _, text in source_dialogues(beat)]
                actual_dialogue = [text.strip() for text in re.findall(r"<d>\s*\[中文\]\s*(.*?)</d>", body, re.S)]
                if snapshot["version"] != "h3-skill-direct-v3" and not dialogues_match(expected_dialogue, actual_dialogue, snapshot["version"]):
                    errors.append(f"镜头 {beat['id']}：新候选对白必须逐句逐字保留原文及标点，不得改写")
                errors.extend(f"镜头 {beat['id']}：{i['suggestion']}" for i in review["issues"] if i["severity"] == "error" and i["beat_id"] == beat["id"])
                candidates[beat["id"]] = {"h3_prompt": body, "fingerprint": contract.prompt_fingerprint(beat, group, plan),
                    "contract_version": snapshot["version"], "content_digest": contract.digest([body, effective["common_prompt"], plan.get("source_fingerprint"), snapshot["version"]]),
                    "review": review}
            if not revision_beat_id and parsed["common_prompt"].strip() != str(group.get("common_prompt") or "").strip():
                candidates["__common_prompt__"] = parsed["common_prompt"].strip()
        errors = list(dict.fromkeys(errors))
        entry["errors"] = errors
        if not errors:
            entry["reason"] = "结构通过；规则审查完成，语义与成片仍待人工验收"
            audit.setdefault("reviews", {})[group["id"]] = entry["review"]
            audit.get("rejected_groups", {}).pop(group["id"], None)
            save()
            return candidates
        rank = (1 if parsed is None else 0, len(errors), len(entry.get("review", {}).get("issues", [])))
        regression = best is not None and rank > best[0]
        if best is None or rank < best[0]:
            best = (rank, deepcopy(entry))
        audit.setdefault("rejected_groups", {})[group["id"]] = {**best[1], "not_approved": True}
        repeated = contract.digest(raw) in seen
        entry["reason"] = "原稿待人工处理，不自动返修" if direct else "锁定项越权" if fatal else "无进展" if repeated else "后稿退步，保留较好版本" if regression else "格式/结构返修"
        save()
        if direct or fatal or repeated or regression or attempt == 2:
            raise ValueError(entry["reason"] + "：" + "；".join(errors))
        seen.add(contract.digest(raw))
        previous_raw = raw
        user = base_user + "\n只修复以下报告中的问题；保留其他动作、剧情、逐字对白、镜头数量、确认时长、参考顺序与锁定项。不退回旧六段式。"
        user += "\n问题：" + json.dumps(errors, ensure_ascii=False) + "\n待修复原稿：\n" + raw
