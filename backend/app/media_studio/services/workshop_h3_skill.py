"""H3 performance writing contract. Shared voices belong to the v7 group."""
from collections import Counter
from pathlib import Path
import math
import re

SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "MINIMAXH3格式动作语气台词细化SKILL" / "SKILL.md"
DIALOGUE_TAIL_SECONDS = 0.5
CHARS_PER_SECOND = 4.0
SLOW_CHARS_PER_SECOND = 3.0
SLOW_MARKERS = ("停顿", "沉吟", "拖长", "哽咽", "发颤", "一字一顿")
FIELDS = ("主体", "动作", "镜头", "音效", "约束")
_TIME = r"(?:\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"[（(]\s*({_TIME})\s*(?:秒)?\s*[–—−-]\s*({_TIME})\s*秒?\s*[）)]")


def _name(value):
    return re.sub(r"[（(].*?[）)]", "", str(value or "")).strip()


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
        timecode_rule = "每镜独立时间码：每镜固定 [Shot 1] 00:00.00–本镜确认时长；本镜动作与台词时间窗以本镜相对秒计，从 0 秒开始。"
        timing_example = "本镜动作与台词时间窗以本镜相对秒计，从 0 秒开始"
    source_block = ""
    if source_text:
        source_block = "\n\n## 完整剧本上下文（仅作剧情与前后镜连续性依据，不得改动剧情、对白或镜头数量）\n" + str(source_text)
    return skill + f"""

## 本次 v7 工作台接入约定（覆盖示例的场景、编号和交付包装）
完整执行上述动作、语气、对白和约束写法。示例中的餐厅、人物、固定上传顺序与参考音频仅为示例，禁止带入本次剧情。
示例中的物件禁项只约束无关物件，不能禁止剧本要求的拿笔、翻书等动作。每个动作只按时间顺序描述一次，不先复述一遍再在台词行重复表演。
用简体中文；只补可执行的表演、视线、动作节奏和声画细节，不改变原剧情、对白、镜头数量或确认时长。
组公共设定是共享主体和声音的唯一来源；不得重写、复制到镜头正文或另起一套定义。图片只约束外观，没有音频就不得虚构参考音频。
严格使用组声音设定的姓名与 (S数字) 映射，不把 Subject/Picture 编号当作说话人编号。
道具与物件名称以剧本 props 的语义为准，参考图只约束外观、不锁语义：当剧本用词与绑定资产名冲突（例如剧本写「笔」而资产叫「毛笔」）时，正文按剧本用词书写，不得沿用资产名，也不得据此更换道具种类。
只生成每镜 detailed_description，禁止摘要、保留分析、六段式包装、主体定义和声音设定段。
{timecode_rule}
其后依次且各一次写非空的【主体】【动作】【镜头】【音效】【约束】。运镜、起止姿态、物件和光线须承接前后镜。
动作与台词时间窗必须精确到 0.1 秒，格式 (起–止秒)；{timing_example}。每个有台词的动作行前都有独立起止时间窗，不能拿镜头总时长代替；范围须有效、按顺序且不重叠。
每句对白独占一个动作行，格式：(起–止秒) 说话人姓名 (S数字) 视线/身体动作与音量、语速描述，说：<d>[中文] 原文台词</d>。说话人姓名与 (S数字) 必须与组声音设定完全一致，例如「沈砚 (S1)」；不要用 <Subject N> 或 <Picture N> 充当说话人。
对白必须位于【动作】内，每句原文恰好出现一次；不得新增人声。同一说话人使用同一编号。
最后一句对白结束后至少留 {DIALOGUE_TAIL_SECONDS:g} 秒无新台词的动作收束，写明闭口、停顿或承接姿态。不能只写“留安全尾部”而不给时间。
根据台词长度安排自然可说完的时间，不能把长句挤进短区间。自然中文对白先按约每秒 4 个字估算，出现低声、慢读、停顿、沉吟、哽咽等减速描述时按每秒 3 字估算；优先减少无意义的开场等待，把时间给对白和必要动作。无对白镜头不写 <d> 或说话人，不强造对白。
【约束】写人物/服装/物件/光线连续性、口型同步及本镜具体禁项，不改写剧情。
{source_block}
"""


def _compact(text):
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


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
        window = end - start
        spoken = tag[1]
        chars = len(_compact(spoken))
        if chars:
            attribution_lower = prefix[timing.end():].lower() + " " + prefix[:timing.start()].lower()
            slow = any(marker in attribution_lower for marker in SLOW_MARKERS)
            rate = SLOW_CHARS_PER_SECOND if slow else CHARS_PER_SECOND
            if window * rate < chars - 1e-6:
                need = math.ceil(chars / rate * 10) / 10.0
                errors.append(f"第 {i+1} 句对白 {chars} 字仅给 {window:g} 秒，不足每秒 {rate:g} 字，至少需要 {need:g} 秒；请把该句对白时间窗延长到至少 {need:g} 秒，并相应压缩本镜开场等待或前移台词起点")
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
