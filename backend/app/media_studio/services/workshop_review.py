"""Evidence-based text checks. Rule findings are not semantic or media acceptance."""
import math
import re

from .workshop_h3_skill import (CHARS_PER_SECOND, SLOW_CHARS_PER_SECOND, SLOW_MARKERS,
                                DIALOGUE_TAIL_SECONDS, DIRECT_VERSIONS, _RANGE, _seconds, _compact)
from .workshop_contract import shot_header


def sections_of(body):
    marks = list(re.finditer(r"【(主体|动作|镜头|音效|约束)】", body))
    return {mark[1]: body[mark.end():marks[i + 1].start() if i + 1 < len(marks) else len(body)].strip()
            for i, mark in enumerate(marks)}


def action_windows(body):
    action = sections_of(body).get("动作", "")
    marks = list(_RANGE.finditer(action))
    windows = []
    for i, mark in enumerate(marks):
        try:
            start, end = _seconds(mark[1]), _seconds(mark[2])
        except ValueError:
            start, end = -1, -1
        windows.append({"start": start, "end": end,
                        "text": action[mark.end():marks[i + 1].start() if i + 1 < len(marks) else len(action)].strip(),
                        "evidence": action[mark.start():marks[i + 1].start() if i + 1 < len(marks) else len(action)].strip()})
    return action, windows


def review_group(ordered, bodies, group):
    if group.get("contract_version") == "h3-skill-direct-v3":
        return {"structure_status": "passed", "content_status": "needs_review",
                "semantic_status": "pending_human", "media_status": "not_reviewed", "issues": [],
                "manual_checks": ["核对原剧本对白与说话人", "审阅人物动作、表演及镜间衔接", "实际成片对白与音画验收"]}
    issues = []
    def add(beat, code, evidence, suggestion, severity="warning"):
        if group.get("contract_version") in DIRECT_VERSIONS:
            severity = "warning"
        issues.append({"beat_id": beat["id"], "code": code, "severity": severity,
                       "evidence": evidence, "suggestion": suggestion})
    common = str(group.get("common_prompt") or "")
    if re.search(r"<Audio\s+\d+>", common):
        add(ordered[0], "fictional_audio", common, "本任务未提供参考音频，删除虚构的 Audio 编号。", "error")
    definitions = re.split(r"声音设定\s*[:：]", common, maxsplit=1)[0]
    defined = re.findall(r"^\s*<Subject\s+(\d+)>", definitions, re.M)
    if len(defined) != len(set(defined)):
        add(ordered[0], "duplicate_subject", definitions, "共享主体编号不得重复定义。", "error")
    if any(int(n) < 1 or int(n) > len(group.get("reference_slots") or []) for n in re.findall(r"<Picture\s+(\d+)>", common)):
        add(ordered[0], "unknown_picture", common, "主体定义只能引用有序参考中存在的 Picture。", "error")
    for beat, body in zip(ordered, bodies):
        parts = sections_of(body)
        action, windows = action_windows(body)
        _, start, end = shot_header(beat, group, ordered)
        if not windows:
            add(beat, "missing_action_timing", action, "为开场、关键动作转换和收束标注时间窗；无对白镜同样需要。", "error")
            continue
        marks = list(_RANGE.finditer(action))
        if action[:marks[0].start()].strip():
            add(beat, "untimed_action", action[:marks[0].start()], "将这段动作放入明确的时间窗。", "error")
        covered = start
        previous_start = start
        for window in windows:
            a, b, text = window["start"], window["end"], window["text"]
            if not start <= a < b <= end or a < previous_start:
                add(beat, "action_bounds", window["evidence"], "动作窗须按起始时间排序且位于本镜范围。", "error")
            if a > covered + 0.15:
                add(beat, "action_gap", window["evidence"], f"补齐 {covered:g}–{a:g} 秒的具体姿态或动作。", "error")
            if a < covered - 0.05 and not re.search(r"同时|并行|一边|另一|左手.*右手|右手.*左手", text):
                add(beat, "ambiguous_overlap", window["evidence"], "说明重叠动作由谁或哪只手并行完成，勿机械拆开自然声画重叠。")
            if not text:
                add(beat, "empty_action", window["evidence"], "时间窗内需要具体动作。", "error")
            spoken = re.search(r"<d>\s*\[中文\]\s*(.*?)</d>", text, re.S)
            if spoken:
                rate = SLOW_CHARS_PER_SECOND if any(m in text[:spoken.start()] for m in SLOW_MARKERS) else CHARS_PER_SECOND
                chars = len(_compact(spoken[1]))
                if chars > (b - a) * rate + 1e-6:
                    need = math.ceil(chars / rate * 10) / 10
                    add(beat, "speech_rate_risk", window["evidence"], f"{chars} 字 / {b-a:g} 秒；按每秒 {rate:g} 字估计需 {need:g} 秒。仅为风险提示，低声不等于慢读；人工评估节奏，必要时提出时长调整候选，不自动改台词。")
            covered = max(covered, b)
            previous_start = a
        if covered < end - 0.15:
            add(beat, "action_tail_gap", windows[-1]["evidence"], f"补齐 {covered:g}–{end:g} 秒收束。", "error")
        dialogue_windows = [w for w in windows if "<d>" in w["text"]]
        if dialogue_windows:
            last = dialogue_windows[-1]
            tail = [w for w in windows if w["start"] >= last["end"] and "<d>" not in w["text"]]
            if not tail or not any(re.search(r"闭口|合上嘴|停止说话|不再开口|不再说话|静默|无言", w["text"]) for w in tail) or end - last["end"] < DIALOGUE_TAIL_SECONDS - 1e-6:
                add(beat, "missing_silent_closure", windows[-1]["evidence"], "最后对白后至少留 0.5 秒，写明闭口/静默及具体承接姿态。", "error")
        if re.search(r"(?:选择|选了|决定)继续", windows[-1]["text"]) and not re.search(r"手|目光|视线|肩|身体|站|坐|按住|停在", windows[-1]["text"]):
            add(beat, "abstract_closure", windows[-1]["evidence"], "把抽象决定落到可见的手、目光和身体姿态。")
        # Narrow, quoted contradictions only; do not infer arbitrary hand occupancy.
        for verb in ("拿笔", "提笔", "写字", "翻页", "翻书"):
            if verb in str(beat.get("action") or "") and re.search(rf"(?:禁止|不得|不能){verb}", parts.get("约束", "")):
                add(beat, "constraint_conflict", parts["约束"], f"禁项与原剧情“{verb}”冲突，仅约束无关物件。")
        for window in windows:
            if re.search(r"(?:右手|左手)[^。；]{0,16}(?:仍|一直)(?:握|拿)[^。；]{0,8}笔[^。；]{0,16}(?:同一只手|该手)[^。；]{0,8}翻", window["text"]):
                add(beat, "hand_occupancy", window["evidence"], "核对同手持笔与翻页，补放笔或换手过程；不同手并行不应被拒绝。")
        sound = parts.get("音效", "")
        for masking in re.finditer(r"(?:环境声|音乐|背景声)(?:完全)?(?:盖过|掩盖|压过)(?:台词|对白|人声)", sound):
            # Match an asserted conflict, not the instruction to prevent it.
            # Check each occurrence: a later affirmative clause must still warn.
            prefix = sound[:masking.start()]
            if re.search(r"(?:不得|不能|不要|避免|禁止|不可|不允许)(?:让|使)?\s*$", prefix):
                continue
            add(beat, "masked_dialogue", sound, "对白期间降低环境声，确保人声可辨。")
            break
        if re.search(r"<Audio\s+\d+>", body):
            add(beat, "fictional_audio", body, "没有参考音频，不能引用 Audio 编号。", "error")
    return {"structure_status": "failed" if any(i["severity"] == "error" for i in issues) else "passed",
            "content_status": "needs_review" if issues else "rules_clear",
            "semantic_status": "pending_human", "media_status": "not_reviewed",
            "issues": issues, "manual_checks": ["刺激先于反应", "镜间落幅与开场、物件位置衔接",
                "人物任务与语气、手部占用及动作顺序", "示例污染与剧情约束冲突", "实际音画及中文对白听辨"]}
