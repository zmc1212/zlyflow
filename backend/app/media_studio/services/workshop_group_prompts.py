"""Generate and validate a Director group as one indivisible candidate."""
import json

from ...workflow_registry import workflow_for
from . import workshop_contract as contract
from .llm_service import LlmService
from .workshop_h3_skill import writing_system


def is_director(plan):
    return workflow_for(plan["workflow_id"]).prompt_profile == "director_segments"


def expand_groups(plan, ids):
    selected = set(ids)
    return [bid for group in plan["groups"] if selected.intersection(group["beat_ids"])
            for bid in group["beat_ids"]]


def generate_group(plan, group, beats, *, revision_beat_id=None, revision_note="", source_text=""):
    ordered = [next(b for b in beats if b["id"] == bid) for bid in group["beat_ids"]]
    targets = [b for b in ordered if not revision_beat_id or b["id"] == revision_beat_id]
    if not targets:
        raise ValueError("返修镜头不在当前组内")
    slots = group.get("reference_slots") or []
    from ...llm_minimax_skills import H3_REF2VA_LABEL_DISCIPLINE
    mode = contract.group_timecode_mode(group)
    system = writing_system(timecode_mode=mode, source_text=source_text) + "\n" + H3_REF2VA_LABEL_DISCIPLINE
    system += '\n只输出 JSON 对象：{"shots":[{"beat_id":"目标镜头ID","prompt":"detailed_description:\\n[Shot N] 起–止\n【主体】...\n【动作】...\n【镜头】...\n【音效】...\n【约束】..."}]}。目标镜头恰好各一次、保持顺序。'
    user = json.dumps({"画幅": plan["aspect_ratio"], "组公共设定": group.get("common_prompt"),
                       "有序镜头": ordered, "有序参考图": slots,
                       "目标镜头": [b["id"] for b in targets]}, ensure_ascii=False)
    user += "\n逐镜时间要求：" + json.dumps([
        {"beat_id": b["id"], "header": f"[Shot {contract.shot_header(b, group, ordered)[0]}] {contract.fmt_timecode(contract.shot_header(b, group, ordered)[1])}–{contract.fmt_timecode(contract.shot_header(b, group, ordered)[2])}"}
        for b in targets], ensure_ascii=False)
    if revision_beat_id:
        user += "\n只返修目标镜头，不改变同组其他镜头、公共设定和确认时长。返修意见：" + revision_note
        user += "\n同组已采纳正文：" + json.dumps(plan.get("shot_prompts") or {}, ensure_ascii=False)
    images = [s["image_url"] for s in slots]
    for beat in ordered:
        refs = beat.get("workshop_writing_refs") or []
        if refs:
            user += f"\n随后附加的 {len(refs)} 张图片只供镜头 {beat['id']} 写稿参考，不分配 Picture 编号。"
            images.extend(refs)
    # One bounded repair uses the same inputs and contract. Never publish a
    # partial group or silently rewrite dialogue/timing in post-processing.
    for attempt in range(3):
        raw = (LlmService.chat_vision(system, user, images, max_tokens=24000, temperature=0.2) if images else
               LlmService.chat_text(system, user, max_tokens=24000, temperature=0.2))
        shots = LlmService._parse_json_object(raw).get("shots")
        if not isinstance(shots, list) or any(not isinstance(s, dict) for s in shots) or [s.get("beat_id") for s in shots] != [b["id"] for b in targets]:
            raise ValueError("整组候选镜头缺失、重复或顺序不符，请重试本组")
        candidates, errors = {}, []
        for beat, shot in zip(targets, shots):
            body = str(shot.get("prompt") or "").strip()
            errors.extend(f"镜头 {beat['id']}：{e}" for e in contract.prompt_checks(body, beat, group, h3=True, ordered_beats=ordered))
            candidates[beat["id"]] = {"h3_prompt": body, "fingerprint": contract.prompt_fingerprint(beat, group, plan)}
        if not errors:
            return candidates
        if attempt:
            raise ValueError("；".join(errors))
        user += "\n上次候选未通过校验，请保留剧情和公共设定、修复以下问题后重新输出目标镜头：" + json.dumps(errors, ensure_ascii=False)
        user += "\n待修复候选：" + raw
