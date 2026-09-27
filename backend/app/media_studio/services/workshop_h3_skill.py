"""H3 performance writing contract. Shared voices belong to the v7 group."""
from collections import Counter
from pathlib import Path
import math
import re
import hashlib

from ..db import query_one
from ..provider_bridge import credential_manager, llm_row, vlm_row
from ...vision_capability import row_supports_vision

SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "MINIMAXH3格式动作语气台词细化SKILL" / "SKILL.md"
DIALOGUE_TAIL_SECONDS = 0.5
CHARS_PER_SECOND = 4.0
SLOW_CHARS_PER_SECOND = 3.0
SLOW_MARKERS = ("慢读", "语速缓慢", "语速略慢", "停顿", "沉吟", "拖长", "哽咽", "发颤", "一字一顿")
AUTHORING_VERSION = "h3-complete-group-v1"
FIELDS = ("主体", "动作", "镜头", "音效", "约束")
_TIME = r"(?:\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"[（(]\s*({_TIME})\s*(?:秒)?\s*[–—−-]\s*({_TIME})\s*秒?\s*[）)]")
_SHOT_HEAD_RE = re.compile(
    rf"^\s*(?:[\[【]Shot\s+(\d+)\s*[\]】]｜\s*|【Shot\s+(\d+)｜[^】]*】)\s*"
    rf"(?:(\d{{1,2}}):(\d{{2}}(?:\.\d+)?)\s*[–—−-]\s*(\d{{1,2}}):(\d{{2}}(?:\.\d+)?))?",
    re.M,
)


def writing_author(config=None, *, plan=None):
    """Resolve the explicit Director author from the request or saved plan.

    Defaults to the active LLM row; a profile_id selects a saved profile and
    optional model / reasoning_effort overrides win per call. Never reads or
    copies Codex private credentials.
    """
    cfg = {}
    if isinstance(config, dict):
        cfg = config
    elif not cfg and isinstance(plan, dict):
        cfg = plan.get("writing_author") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    base = llm_row() or {}
    row = dict(base)
    profile_id = str(cfg.get("profile_id") or "").strip()
    if profile_id:
        profile = query_one(
            "SELECT * FROM llm_provider_profiles WHERE profile_id=%s",
            (profile_id,),
        ) or {}
        if not profile.get("base_url") and not profile.get("model"):
            raise ValueError("所选写稿供应商配置不存在，请在管理设置中重新选择")
        row = dict(profile)
    model = str(cfg.get("model") or row.get("model") or "").strip()
    reasoning_effort = str(cfg.get("reasoning_effort") or row.get("reasoning_effort") or "low").strip().lower()
    base_url = str(row.get("base_url") or "").strip().rstrip("/")
    if cfg.get("base_url") and str(cfg["base_url"]).rstrip("/") != base_url:
        raise ValueError("写稿供应商地址已改变，任务快照不能切换端点；请创建新任务")
    api_key = credential_manager().decrypt(row.get("api_key_encrypted")) if row.get("api_key_encrypted") else None
    if not base_url or not model or not api_key:
        raise ValueError("写稿模型配置不完整，请检查服务地址、模型与 API Key")
    row["model"] = model
    supports_vision = row_supports_vision(row)
    return {
        "profile_id": profile_id or str(row.get("profile_id") or "custom"),
        "base_url": base_url,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "api_key": api_key,
        "supports_vision": supports_vision,
        "vision_row": row,
    }


def vlm_fact_extraction_author():
    """Explicit VLM fact-extraction author for the opt-in two-step mode."""
    from ...vision_runtime import endpoint_from_row, overlay_vlm_credentials
    row = overlay_vlm_credentials(vlm_row(), llm_row())
    endpoint = endpoint_from_row("vlm", row, credential_manager().decrypt, require_vision=True, probe_unknown=True)
    if endpoint is None:
        raise ValueError("VLM 视觉能力未验证，无法提取外观事实，请重新探测。")
    return {"profile_id": str(row.get("profile_id") or "vlm"), "base_url": endpoint.base_url,
            "model": endpoint.model, "api_key": endpoint.api_key, "reasoning_effort": "none", "supports_vision": True}


def _name(value):
    return re.sub(r"[（(].*?[）)]", "", str(value or "")).strip()


_SUBJECT_DEF_RE = re.compile(r"^\s*subject_definitions(?:（主体定义）)?\s*[:：]\s*$", re.M)
_SOUND_DEF_RE = re.compile(r"^\s*声音设定\s*[:：]\s*$", re.M)
_DETAIL_RE = re.compile(r"^\s*detailed_description(?:\s*[:：])?\s*$", re.M)
_SHOT_MARK_RE = re.compile(r"^\s*[\[【]Shot\s+(\d+)\s*[\]】｜|]?\s*", re.M)


def _fmt_timecode(seconds):
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    return f"{minutes:02}:{total - minutes * 60:05.2f}"


def _shot_header_parts(block):
    """Read the authored shot header line into (authored_range, descriptor).

    Supports both the skill's canonical 【Shot N｜起–止秒｜景别·描述】 style and
    the v7 storage style [Shot N] mm:ss–mm:ss. Returns (None, "") pieces when
    the header carries no explicit timeline.
    """
    first = block.splitlines()[0] if block.splitlines() else ""
    authored = None
    descriptor = ""
    bracket = re.match(r"^\s*【\s*Shot\s+\d+\s*｜([^】]*)】", first)
    if bracket:
        inner = [part.strip() for part in bracket.group(1).split("｜") if part.strip()]
        range_match = re.match(rf"^({_TIME})\s*秒?\s*[–—−-]\s*({_TIME})\s*秒?$", inner[0]) if inner else None
        if range_match:
            authored = (_seconds(range_match.group(1)), _seconds(range_match.group(2)))
            descriptor = "｜".join(inner[1:])
        else:
            descriptor = "｜".join(inner)
        rest = first[bracket.end():].strip(" ：:，,")
        if rest and not descriptor:
            descriptor = rest
    else:
        timeline = re.search(
            r"(\d{1,2}:\d{2}(?:\.\d+)?)\s*[–—−-]\s*(\d{1,2}:\d{2}(?:\.\d+)?)", first)
        if timeline:
            authored = (_seconds(timeline.group(1)), _seconds(timeline.group(2)))
            descriptor = first[timeline.end():].strip(" ：:，,")
    return authored, descriptor


def split_complete_group_draft(raw, ordered_beats, group=None):
    """Split one authored group draft into shared settings and per-shot bodies.

    Only explicit boundaries are used: the subject/voice header, the
    detailed_description container, and ordered 【Shot N】 marks. Creative
    content (action, dialogue, sound, constraints) is preserved verbatim; the
    only conversion is the per-shot storage header, which is rewritten to the
    group's timecode contract so saved bodies pass the same checks as manual
    edits. Authored timelines that disagree with the confirmed durations are
    rejected instead of silently rewritten.
    """
    from .workshop_contract import group_timecode_mode, duration

    text = str(raw or "").strip()
    marks = list(_SHOT_MARK_RE.finditer(text))
    if not marks:
        raise ValueError("完整稿缺少【Shot N】镜头标记，无法确定性拆分")
    numbers = [int(_SHOT_MARK_RE.match(text, mark.start()).group(1)) for mark in marks]
    if numbers != list(range(1, len(ordered_beats) + 1)):
        raise ValueError(f"镜头编号需为 1..{len(ordered_beats)} 连续出现，得到 {numbers}")
    detail_match = _DETAIL_RE.search(text)
    if detail_match and marks[0].start() < detail_match.start():
        raise ValueError("detailed_description 应位于各镜头之前")
    cumulative = group_timecode_mode(group or {}) == "cumulative"
    running = 0.0
    shots = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        block = text[mark.start():end].strip()
        beat = ordered_beats[index]
        seconds = duration(beat)
        start_sec = running if cumulative else 0.0
        end_sec = start_sec + seconds
        running = end_sec
        authored, descriptor = _shot_header_parts(block)
        if authored and (abs(authored[0] - start_sec) > 0.05 or abs(authored[1] - end_sec) > 0.05):
            raise ValueError(
                f"镜头 {index + 1} 起止时间与确认时长不符，需为 "
                f"{_fmt_timecode(start_sec)}–{_fmt_timecode(end_sec)}"
            )
        # Drop stray container lines inside the block; each stored body gets
        # exactly one container header plus the storage-contract shot header.
        lines = [line for line in block.splitlines()
                 if not re.match(r"^\s*detailed_description\s*[:：]?\s*$", line)]
        shot_no = index + 1 if cumulative else 1
        header = f"[Shot {shot_no}] {_fmt_timecode(start_sec)}–{_fmt_timecode(end_sec)}"
        if descriptor:
            header += f" {descriptor}"
        lines[0] = header
        shots.append("detailed_description:\n" + "\n".join(lines).strip())
    head = text[:detail_match.start()] if detail_match else text[:marks[0].start()]
    subject_match = _SUBJECT_DEF_RE.search(head)
    sound_match = _SOUND_DEF_RE.search(head)
    if subject_match and sound_match and sound_match.start() < subject_match.start():
        raise ValueError("声音设定必须位于主体定义之后")
    subject_block = head[subject_match.start():] if subject_match else head.strip()
    return {
        "common_prompt": subject_block.strip(),
        "shots": shots,
        "subject_definitions": subject_block.strip(),
    }


def source_dialogues(beat):
    """Retain separate turns and their owners; never guess among multiple people."""
    text = str(beat.get("dialogue") or "").strip()
    if text in {"", "无", "无对白", "（无）", "—"}:
        return []
    fallback = _name(beat.get("speaker"))
    if not fallback and len(beat.get("characters") or []) == 1:
        fallback = _name(beat["characters"][0])
    turns = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^\s*([^：:\n“\"]{1,40})[：:]\s*(.*)$", line)
        owner, spoken = (_name(match[1]), match[2]) if match else (fallback, line.strip())
        turns.append((owner, spoken.strip().strip('“”"')))
    return turns


def voice_map(common, names=()):
    """Accept named lines and the skill's Subject/Picture voice definitions."""
    sound = re.split(r"声音设定\s*[:：]", str(common), maxsplit=1)[-1] if re.search(r"声音设定\s*[:：]", str(common)) else ""
    result = [(m[1].strip(), m[2]) for m in re.finditer(r"^\s*([^\n()：:<>]+?)\s*\(S([1-9]\d*)\)\s*[：:]\s*\S.+$", sound, re.M)]
    for name in names:
        if any(n == name for n, _ in result):
            continue
        tokens = []
        definitions = re.split(r"声音设定\s*[:：]", str(common), maxsplit=1)[0]
        for line in definitions.splitlines():
            if name in line:
                tokens.extend(re.findall(r"<(?:Subject|Picture)\s+\d+>", line))
        for line in sound.splitlines():
            if name in line or any(token in line for token in tokens):
                result.extend((name, n) for n in re.findall(r"\(S([1-9]\d*)\)", line))
    return result


def ensure_sound_settings(groups, beats):
    """Pure caller-owned projection; preserve existing explicit sound settings.

    IDs follow episode speaking order, and existing explicit IDs reserve their
    numbers. GET only projects this; the existing command transaction persists it.
    """
    names = list(dict.fromkeys(owner for b in beats for owner, _ in source_dialogues(b) if owner))
    known = {}
    used = set()
    for group in groups:
        for name, number in voice_map(group.get("common_prompt", ""), names):
            known.setdefault(name, number)
            used.add(number)
    for name in names:
        if name not in known:
            number = next(str(n) for n in range(1, len(used) + 2) if str(n) not in used)
            known[name] = number
            used.add(number)
    for group in groups:
        common = str(group.get("common_prompt") or "").strip()
        # User-authored sound sections remain authoritative, including invalid
        # ones: validation reports them rather than overwriting creative choices.
        if re.search(r"声音设定\s*[:：]", common):
            continue
        local = list(dict.fromkeys(owner for b in beats if b["id"] in group["beat_ids"]
                                   for owner, _ in source_dialogues(b) if owner))
        lines = [f"{name} (S{known[name]})：自然人声，同一人物的音色在全片保持一致；没有提供参考音频，不从图片推断音色。" for name in local]
        group["common_prompt"] = common + "\n声音设定：\n" + ("\n".join(lines) if lines else "本组无对白，不添加旁白或其他人声，保留剧本环境音。")


def writing_system(timecode_mode="per_shot", source_text=""):
    skill = SKILL_PATH.read_text(encoding="utf-8").strip()
    if timecode_mode == "cumulative":
        timecode_rule = "组内时间码累计：本镜编号与起止秒按组内顺序累计，例如第 1 镜 [Shot 1] 00:00.00–00:08.00，第 2 镜 [Shot 2] 00:08.00–00:16.00；起始秒等于前序镜头时长之和。"
        timing_example = "本镜动作与台词时间窗也使用组内累计秒（从本镜起始秒起算），例如第 2 镜写 (8–10.2秒)，不是从 0 开始"
    else:
        timecode_rule = "每镜独立时间码：完整稿中的【Shot N】按组内顺序连续编号 1..N，但每镜起止时间均从 0 秒开始；保存时程序将每镜存储头映射为 [Shot 1]。"
        timing_example = "本镜动作与台词时间窗以本镜相对秒计，从 0 秒开始"
    source_block = ""
    if source_text:
        source_block = "\n\n## 完整剧本上下文（仅作剧情与前后镜连续性依据，不得改动剧情、对白或镜头数量）\n" + str(source_text)
    return skill + f"""

## 本次 v7 工作台接入约定（覆盖示例的场景、编号和交付包装）
完整执行上述动作、语气、对白和约束写法。示例中的餐厅、人物、固定上传顺序与参考音频仅为示例，禁止带入本次剧情。
示例中的物件禁项只约束无关物件，不能禁止剧本要求的拿笔、翻书等动作。每个动作只按时间顺序描述一次，不先复述一遍再在台词行重复表演。
用简体中文；只补可执行的表演、视线、动作节奏和声画细节，不改变原剧情、对白、镜头数量或确认时长。
公共设定与镜头一次统筹创作；现有自动设定可提出改善候选，用户显式锁定项不可改。候选采纳前不覆盖正式稿。图片只约束外观，不虚构参考音频。
沿用人物身份与已有姓名 / (S数字) 归属，不把 Subject/Picture 编号当作说话人编号；正文只引用本次完整稿的共享定义。
道具与物件名称以剧本 props 的语义为准，参考图只约束外观、不锁语义：当剧本用词与绑定资产名冲突（例如剧本写「笔」而资产叫「毛笔」）时，正文按剧本用词书写，不得沿用资产名，也不得据此更换道具种类。
本次输出一次完整组稿，严格按 skill「整体结构」顺序：先写 subject_definitions（主体定义）与声音设定，再写 detailed_description，并在其中依次且各一次写出本组全部镜头的【Shot N】。
主体定义与声音设定由本次完整稿统一创作：场景、人物、道具各写一条定义行；本组每句对白的说话人给出姓名与 (S数字) 映射。没有提供参考音频就明确写不提供参考音频，不虚构编号。镜头正文只引用这些共享标签，不得重写、复制或另起一套定义。
禁止摘要、保留分析、六段式包装、JSON 包装、检查清单或解释，直接输出完整稿正文。
{timecode_rule}
每镜在【Shot N｜起–止秒｜景别·描述】后依次且各一次写非空的【主体】【动作】【镜头】【音效】【约束】。运镜、起止姿态、物件和光线须承接前后镜。
关键动作与台词用 (起–止秒) 标注，{timing_example}。覆盖开场、转换、对白和收束，无对白镜也须有动作窗。对白各自有独立时间窗；明确不同主体/肢体的并行动作允许重叠。时间精度是指导粒度，不保证模型逐 0.1 秒执行。
每句对白独占一个动作行，格式：(起–止秒) 说话人姓名 (S数字) 视线/身体动作与音量、语速描述，说：<d>[中文] 原文台词</d>。说话人姓名与 (S数字) 必须与组声音设定完全一致，例如「沈砚 (S1)」；不要用 <Subject N> 或 <Picture N> 充当说话人。
对白必须位于【动作】内，每句原文恰好出现一次；不得新增人声。同一说话人使用同一编号。
最后一句对白结束后至少留 {DIALOGUE_TAIL_SECONDS:g} 秒无新台词的独立动作收束时间窗，明确写出闭口或静默，并描述具体承接姿态。不能只写停顿或姿态，也不能只写“留安全尾部”而不给时间。
字速只作风险估计：自然中文约每秒 {CHARS_PER_SECOND:g} 字；出现 {"、".join(SLOW_MARKERS)} 时约每秒 {SLOW_CHARS_PER_SECOND:g} 字。低声是音量，不等同慢语速。不可为通过估计机械前移对白、改原文或改时长；容纳不了时保留剧情并显式报告冲突。无对白镜头不写 <d> 或说话人。
【约束】写人物/服装/物件/光线连续性、口型同步及本镜具体禁项，不改写剧情。
{source_block}
"""


def _compact(text):
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def writing_contract_snapshot(source_text="", timecode_mode="per_shot"):
    skill = SKILL_PATH.read_text(encoding="utf-8")
    return {"version": AUTHORING_VERSION, "skill_path": "skills/MINIMAXH3格式动作语气台词细化SKILL/SKILL.md",
            "skill_sha256": hashlib.sha256(skill.encode()).hexdigest(), "skill_text": skill,
            "system": writing_system(timecode_mode, source_text),
            "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
            "context_policy": "full_source_no_truncation"}


def _seconds(text):
    parts = text.split(":")
    if len(parts) == 2:
        if float(parts[1]) >= 60:
            raise ValueError("invalid seconds")
        return int(parts[0]) * 60 + float(parts[1])
    return float(text)


def performance_checks(body, beat, group, offset_sec=0.0):
    errors = []
    common = str(group.get("common_prompt") or "")
    if not re.search(r"声音设定\s*[:：]\s*\S", common):
        errors.append("组公共设定缺少声音设定，请补齐后重新生成本组提示词")
    if re.search(r"subject_definitions|主体定义\s*[:：]|声音设定\s*[:：]", body, re.I):
        errors.append("主体定义和声音设定只保存在组公共设定，不得写入镜头正文")
    if not re.search(r"(?:detailed_description|详细描述)\s*[:：]", body):
        errors.append("H3 镜头正文需要 detailed_description: 容器")
    if re.search(r"(?:摘要|保留分析|整体声景|非叙事配乐|summary|retention_analysis|overall_soundscape|non_diegetic_music)\s*[:：]", body, re.I):
        errors.append("请使用动作语气技能正文，不要混入旧六段式包装")
    matches = list(re.finditer(r"【(主体|动作|镜头|音效|约束)】", body))
    sections = {}
    if [m[1] for m in matches] != list(FIELDS):
        errors.append("H3 正文必须依次包含【主体】【动作】【镜头】【音效】【约束】，各一次")
    else:
        for i, m in enumerate(matches):
            sections[m[1]] = body[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)].strip()
            if not sections[m[1]]:
                errors.append(f"【{m[1]}】不能为空")
    expected = source_dialogues(beat)
    tags = list(re.finditer(r"<d>\s*\[中文\]\s*(.*?)\s*</d>", body, re.S))
    if body.count("<d>") != len(tags) or body.count("</d>") != len(tags):
        errors.append("对白必须使用完整的 <d>[中文] 原文</d> 标签")
    if Counter(_compact(t[1]) for t in tags) != Counter(_compact(t) for _, t in expected):
        errors.append("每句原文对白必须在 <d>[中文]…</d> 内恰好出现一次，不能遗漏、重复或新增")
    if not expected and re.search(r"\(S\d+\)", sections.get("动作", "")):
        errors.append("无对白镜头不得新增说话人")
    voices = voice_map(common, [name for name, _ in expected if name])
    mapping = dict(voices)
    if len(mapping) != len(voices) or len(set(mapping.values())) != len(mapping):
        errors.append("组声音设定的姓名与 (S编号) 必须一一对应，不可重复")
    action = sections.get("动作", "")
    action_tags = list(re.finditer(r"<d>\s*\[中文\]\s*(.*?)\s*</d>", action, re.S))
    if len(action_tags) != len(tags):
        errors.append("所有对白必须写在【动作】内")
    previous_end, cursor = float(offset_sec), 0
    total = offset_sec + float(beat.get("video_duration") or beat.get("duration_seconds") or 0)
    for i, tag in enumerate(action_tags):
        prefix = action[cursor:tag.start()]
        cursor = tag.end()
        ranges = list(_RANGE.finditer(prefix))
        if not ranges:
            errors.append(f"第 {i+1} 句对白缺少独立起止时间，如 (2–6秒)")
            continue
        timing = ranges[-1]
        try:
            start, end = _seconds(timing[1]), _seconds(timing[2])
        except ValueError:
            errors.append(f"第 {i+1} 句对白时间无效")
            continue
        if start < previous_end or not offset_sec <= start < end <= total:
            errors.append(f"第 {i+1} 句对白时间越界、重叠或顺序错误")
        previous_end = end
        if total - end < DIALOGUE_TAIL_SECONDS - 1e-6:
            errors.append(f"第 {i+1} 句对白结束后不足 {DIALOGUE_TAIL_SECONDS:g} 秒安全尾部，请前移台词或调整镜头时长")
        # Character rate is advisory content evidence, never a structural gate.
        owner = expected[i][0] if i < len(expected) else ""
        attribution = prefix[timing.end():]
        number = mapping.get(owner)
        labels = [owner] if owner else []
        definitions = re.split(r"声音设定\s*[:：]", common, maxsplit=1)[0]
        for line in definitions.splitlines():
            if owner and owner in line:
                labels.extend(re.findall(r"<Subject\s+\d+>", line))
        if not owner or not number or not any(re.search(rf"{re.escape(label)}\s*\(S{re.escape(number)}\)", attribution) for label in labels):
            errors.append(f"第 {i+1} 句对白须使用组声音设定中“{owner or '原说话人'} (S编号)”的稳定归属")
        if i < len(expected) and _compact(tag[1]) != _compact(expected[i][1]):
            errors.append("对白顺序必须与原镜头一致")
    if action_tags and not action[action_tags[-1].end():].strip():
        errors.append("最后一句对白后须在【动作】中写出无新台词的收束姿态")
    return list(dict.fromkeys(errors))
