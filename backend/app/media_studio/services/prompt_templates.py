"""Versioned Prompt Master templates and strict output parsers.

Only the two prompt profiles in this module are allowed to author H3 prompt
bodies for the director workshop.  Keeping assembly and parsing together makes
the persisted template version an honest reproduction boundary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


FULL_REFERENCE_TEMPLATE_VERSION = "prompt-master/full-reference@1"
DIRECTOR_TEMPLATE_VERSION = "prompt-master/continuous-story@2"
DIRECTOR_UNIT_PLANNER_VERSION = "prompt-master/atomic-units@1"

ZH_FULL_SECTIONS = (
    ("subject_definitions", "主体定义"),
    ("summary", "摘要"),
    ("retention_analysis", "保留分析"),
    ("detailed_description", "详细描述"),
    ("overall_soundscape", "整体声景"),
    ("non_diegetic_music", "非叙事配乐"),
)
EN_FULL_SECTIONS = (
    ("subject_definitions", "subject_definitions"),
    ("summary", "summary"),
    ("retention_analysis", "retention_analysis"),
    ("detailed_description", "detailed_description"),
    ("overall_soundscape", "overall_soundscape"),
    ("non_diegetic_music", "non_diegetic_music"),
)


class PromptTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSections:
    sections: dict[str, str]
    prompt_text: str


def normalize_language(value: Any) -> str:
    text = str(value or "zh-CN").strip().lower()
    return "en" if text.startswith("en") else "zh-CN"


def _section_spec(language: str, *, include_subject: bool = True) -> tuple[tuple[str, str], ...]:
    spec = EN_FULL_SECTIONS if normalize_language(language) == "en" else ZH_FULL_SECTIONS
    return spec if include_subject else spec[1:]


def _reference_context(reference_slots: list[dict[str, Any]]) -> str:
    if not reference_slots:
        return "无参考图片。不得编造 <Picture N>；可以在主体定义中用 <Subject N> 锁定文字角色。"
    rows = []
    for slot in reference_slots:
        rows.append(
            f"{slot['token']}：{slot.get('name') or '未命名资产'}"
            f"（{slot.get('kind') or 'asset'}，asset_id={slot.get('asset_id') or ''}，"
            f"look_id={slot.get('look_id') or ''}）"
        )
    return "\n".join(rows)


def build_full_reference_prompts(
    *,
    language: str,
    rewrite_mode: str,
    aspect_ratio: str,
    duration_seconds: float,
    source_text: str,
    reference_slots: list[dict[str, Any]],
) -> tuple[str, str]:
    lang = normalize_language(language)
    expand = str(rewrite_mode or "strict").strip().lower() == "expand"
    if lang == "en":
        system = """You are the MiniMax H3 Full-Reference prompt writer.
Output only six sections in this exact order and spelling:
subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music.
Start with `subject_definitions:` and end with the body of `non_diegetic_music:`. Do not use Markdown fences or commentary.
Keep <Subject N>, <Picture N>, <Video N>, <Audio N>, fully_preserved/partially_preserved and [Shot N] markers in English.
Never invent a <Picture N>. Describe identity, wardrobe and reference preservation precisely. Write actionable camera, motion, lighting, sound and music details.
Use the source material as truth; invent plot only when expansion is explicitly allowed."""
        mode = "Expansion is allowed: fill necessary visual, camera, timing and audio details." if expand else "Strict rewrite: do not invent plot, characters or events."
        user = f"""Output language: English
Target duration: {duration_seconds:g} seconds
Aspect ratio: {aspect_ratio}
Rewrite mode: {mode}

Reference media:
{_reference_context(reference_slots)}

Source material:
{source_text.strip()}

Return the clean six-section prompt only."""
        return system, user

    system = """你是 MiniMax H3 Full-Reference 六段式视频提示词编剧。
只输出六段，标题和顺序强制为：主体定义、摘要、保留分析、详细描述、整体声景、非叙事配乐。
必须以“主体定义:”开头，以“非叙事配乐:”正文结束。禁止 Markdown 代码围栏、寒暄、解释和过程描述。
参考标签 <Subject N>/<Picture N>/<Video N>/<Audio N>、关系标记 fully_preserved/partially_preserved、镜头标记 [Shot N] 保持英文。
不得编造不存在的 <Picture N>。主体身份、穿着和参考保留关系必须明确；运镜、动作、光线、声音和配乐必须可执行。
原始素材是事实边界；只有明确允许扩写时才能补全情节细节。"""
    mode = "允许扩写补全：可以补足必要的视觉、运镜、时间和声画细节。" if expand else "严格改写：不得编造新情节、新角色或新事件。"
    user = f"""输出语言：简体中文
目标时长：{duration_seconds:g} 秒
画幅：{aspect_ratio}
改写模式：{mode}

参考素材：
{_reference_context(reference_slots)}

原始素材：
{source_text.strip()}

仅返回干净的中文六段式提示词。"""
    return system, user


def build_director_unit_planning_prompts(
    *,
    language: str,
    beats: list[dict[str, Any]],
    units: list[dict[str, Any]],
) -> tuple[str, str]:
    """Build the structured allocation prompt used before prose generation.

    The writer must never infer ownership of an event from a duplicated full
    Beat. This pass assigns each source event and dialogue line to exactly one
    atomic unit before the six-section prompt is written.
    """
    lang = normalize_language(language)
    if lang == "en":
        system = """You are the Director atomic-unit planner. Return JSON only.
Create one object for every provided unit id. Assign each source Beat's events and dialogue to exactly one unit; never invent plot, characters, dialogue or events. Keep dialogue_owner text verbatim. required_events must be concise source-grounded event descriptions and must not repeat across units. start_state and handoff_state must describe visible continuity only. For adjacent units from the same Beat, copy the previous handoff_state verbatim into the next start_state.
JSON shape: {\"units\":[{\"unit_id\":\"...\",\"required_events\":[\"...\"],\"dialogue_owner\":[\"...\"],\"start_state\":\"...\",\"handoff_state\":\"...\"}]}"""
        beat_label = "Beat"
        unit_label = "Unit"
    else:
        system = """你是 Director 连续剧情的动作单元规划器。只返回 JSON，不要 Markdown 或解释。
为每个提供的 unit_id 返回一个对象。将原始 Beat 中的动作事件和对白逐项分配给且只分配给一个 unit；不得编造新剧情、人物、对白或事件。dialogue_owner 必须逐字保留原对白。required_events 只能是来源明确支持的简短动作事件，且不得跨单元重复。start_state 和 handoff_state 只描述可见的连续状态；同一 Beat 的相邻单元必须把上一单元的 handoff_state 原样复制为下一单元的 start_state。
JSON 结构：{\"units\":[{\"unit_id\":\"...\",\"required_events\":[\"...\"],\"dialogue_owner\":[\"...\"],\"start_state\":\"...\",\"handoff_state\":\"...\"}]}"""
        beat_label = "Beat"
        unit_label = "单元"

    beat_text = []
    for beat in beats:
        beat_text.append(
            f"{beat_label} {beat.get('id') or ''} / source shot {beat.get('source_shot_number') or beat.get('story_shot') or beat.get('sequence') or ''}:\n"
            f"heading: {beat.get('heading') or beat.get('scene') or ''}\n"
            f"action: {beat.get('action') or beat.get('visual_prompt') or ''}\n"
            f"camera: {beat.get('camera') or ''}\n"
            f"dialogue: {beat.get('dialogue') or ''}\n"
            f"audio: {beat.get('audio') or ''}"
        )
    unit_text = []
    for unit in units:
        unit_text.append(
            f"{unit_label} {unit.get('id')}: source_beat_id={unit.get('source_beat_id')}, "
            f"source_shot_number={unit.get('source_shot_number')}, "
            f"generated_shot_number={unit.get('generated_shot_number')}, "
            f"time={unit.get('start_sec', 0):g}-{unit.get('end_sec', 0):g}s"
        )
    user = (
        f"Output language: {'English' if lang == 'en' else '简体中文'}\n\n"
        "Source Beats:\n" + "\n\n".join(beat_text) + "\n\n"
        "Atomic units to allocate:\n" + "\n".join(unit_text) + "\n\n"
        "Every unit must be present exactly once in the JSON output."
    )
    return system, user


def parse_director_unit_plan(
    text: str,
    expected_units: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    source = str(text or "").strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.I | re.S).strip()
    try:
        payload = json.loads(source)
    except (TypeError, ValueError) as err:
        raise PromptTemplateError("动作单元规划不是合法 JSON") from err
    rows = payload.get("units") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise PromptTemplateError("动作单元规划缺少 units 数组")
    expected_ids = [str(item.get("id") or "").strip() for item in expected_units]
    actual_ids = [str(item.get("unit_id") or "").strip() for item in rows]
    if actual_ids != expected_ids:
        raise PromptTemplateError("动作单元必须按计划顺序逐一返回且不能重复")
    parsed: dict[str, dict[str, Any]] = {}
    for row, expected in zip(rows, expected_units):
        if not isinstance(row, dict):
            raise PromptTemplateError("动作单元对象格式无效")
        events = [str(value or "").strip() for value in row.get("required_events") or [] if str(value or "").strip()]
        dialogue = [str(value or "").strip() for value in row.get("dialogue_owner") or [] if str(value or "").strip()]
        if not events:
            raise PromptTemplateError(f"动作单元 {expected.get('id')} 缺少 required_events")
        if len(events) != len(dict.fromkeys(events)):
            raise PromptTemplateError(f"动作单元 {expected.get('id')} 的事件重复")
        parsed[expected["id"]] = {
            "id": expected["id"],
            "required_events": events,
            "dialogue_owner": dialogue,
            "start_state": str(row.get("start_state") or "").strip(),
            "handoff_state": str(row.get("handoff_state") or "").strip(),
        }
    return parsed


def build_director_prompts(
    *,
    language: str,
    rewrite_mode: str,
    aspect_ratio: str,
    segment_sources: list[dict[str, Any]],
    reference_slots: list[dict[str, Any]],
    previous_handoff: str | dict[str, Any] = "",
) -> tuple[str, str]:
    lang = normalize_language(language)
    n = len(segment_sources)
    if n < 2 or n > 8:
        raise PromptTemplateError("连续剧情每个 Part 必须包含 2–8 个提示词组")
    expand = str(rewrite_mode or "expand").strip().lower() == "expand"
    if lang == "en":
        system = f"""You write MiniMax H3 Director continuous stories. Output exactly two parts and nothing else.
Part 1 separator: ===== Public Settings =====. It contains only subject_definitions:.
Part 2 contains exactly {n} groups with separators ===== Prompt Group k ===== for k=1..{n}.
Each group contains only summary:, retention_analysis:, detailed_description:, overall_soundscape:, non_diegetic_music: in that order. Never repeat subject_definitions inside a group.
Preserve every provided [Shot N] exactly once in ascending order inside that group's detailed_description. Include every assigned required_events phrase verbatim exactly once. Describe only those assigned events; never replay an event or dialogue from a previous group.
Group 2+ detailed_description must start with "No hard cut. Immediately following the previous section."
Every detailed_description ends on a stable handoff pose. Timestamps reset to 00:00 in every group. Keep cast, wardrobe, space and music continuous; groups before the last must not fade out. Do not use replay, rewind, time echo, sensory echo or a second performance to fill time.
Never invent a <Picture N>. Do not use Markdown fences or commentary."""
    else:
        system = f"""你负责创作 MiniMax H3 Director 连续剧情。只输出两部分，不得输出其他内容。
第一部分分隔行：===== 公共设定 =====，其中只能写“主体定义:”。
第二部分严格输出 {n} 个组，分隔行依次为 ===== 提示词组 k =====（k=1..{n}）。
每组只能按顺序写：摘要、保留分析、详细描述、整体声景、非叙事配乐；组内禁止重复主体定义。
每组“详细描述”必须按升序保留该段提供的全部 [Shot N]，每个编号只出现一次；该段分配的每条 required_events 必须原样出现且只出现一次，只能描述这些已分配事件，不得重演上一组已完成的动作或对白。
第 2 组起“详细描述:”第一句必须是“无硬切。紧接上一段。”；每组时间码从 00:00 起算，详细描述以稳定交接姿态收束并以“不要乱说话”结束。
人物、服装、空间和配乐主题跨组连续；最后一组之前不得淡出。禁止时间回响、感知回响、回放、倒放、重新醒来或重复表演来填充时长。不得编造 <Picture N>。禁止 Markdown 代码围栏、寒暄和解释。"""

    segment_text = []
    for idx, segment in enumerate(segment_sources, start=1):
        unit_lines = []
        for unit in segment.get("source_units") or []:
            unit_lines.append(
                f"[Shot {unit.get('generated_shot_number') or idx}] "
                f"unit_id={unit.get('id')}; source_shot={unit.get('source_shot_number')}; "
                f"time={unit.get('start_sec', 0):g}-{unit.get('end_sec', 0):g}s\n"
                f"required_events: {'；'.join(unit.get('required_events') or [])}\n"
                f"dialogue_owner: {'；'.join(unit.get('dialogue_owner') or []) or '无'}\n"
                f"start_state: {unit.get('start_state') or '延续上一段可见状态'}\n"
                f"handoff_state: {unit.get('handoff_state') or '以本段最后动作后的稳定状态收束'}"
            )
        segment_text.append(
            f"第 {idx} 段（目标约 {segment.get('duration_seconds') or 5:g} 秒）：\n"
            + ("\n".join(unit_lines) or "缺少动作单元分配，禁止自行补写剧情。")
        )
    mode = "只允许补全必要的运镜、表演连接和声画细节；不得新增剧情事件" if expand else "严格遵循提供的动作单元事实，不编造"
    if isinstance(previous_handoff, dict):
        handoff = json.dumps(previous_handoff, ensure_ascii=False, separators=(",", ":"))
    else:
        handoff = str(previous_handoff or "").strip()
    handoff = handoff or "无（这是首个 Part）"
    if lang == "en":
        user = f"""Output language: English
Aspect ratio: {aspect_ratio}
Rewrite mode: {mode}
Previous Part handoff: {handoff}

Reference media:
{_reference_context(reference_slots)}

Planned continuous segments:
{chr(10).join(segment_text)}

Return Public Settings and exactly {n} Prompt Groups."""
    else:
        user = f"""输出语言：简体中文
画幅：{aspect_ratio}
改写模式：{mode}
上一 Part 交接状态：{handoff}

参考素材：
{_reference_context(reference_slots)}

计划的连续段落：
{chr(10).join(segment_text)}

输出一次公共设定和严格 {n} 个提示词组。"""
    return system, user


def _parse_sections(
    text: str,
    language: str,
    *,
    include_subject: bool,
    only_subject: bool = False,
) -> ParsedSections:
    source = str(text or "").strip()
    if not source:
        raise PromptTemplateError("模型没有返回提示词")
    spec = _section_spec(language, include_subject=include_subject)
    if only_subject:
        spec = spec[:1]
    matches: list[tuple[int, int, str, str]] = []
    for key, label in spec:
        found = list(re.finditer(rf"(?im)^\s*{re.escape(label)}\s*[:：]\s*", source))
        if len(found) != 1:
            raise PromptTemplateError(f"章节“{label}”必须且只能出现一次")
        match = found[0]
        matches.append((match.start(), match.end(), key, label))
    if [item[0] for item in matches] != sorted(item[0] for item in matches):
        raise PromptTemplateError("提示词章节顺序不正确")
    first_prefix = source[: matches[0][0]].strip()
    if first_prefix:
        raise PromptTemplateError("章节前存在额外内容")
    sections: dict[str, str] = {}
    normalized: list[str] = []
    for idx, (_, end, key, label) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(source)
        body = source[end:next_start].strip()
        if not body:
            raise PromptTemplateError(f"章节“{label}”不能为空")
        sections[key] = body
        normalized.append(f"{label}: {body}")
    return ParsedSections(sections=sections, prompt_text="\n\n".join(normalized))


def _validate_references(text: str, reference_slots: list[dict[str, Any]], *, subject_source: str = "") -> None:
    valid_pictures = {int(item.get("index") or 0) for item in reference_slots}
    used_pictures = {int(value) for value in re.findall(r"<Picture\s+(\d+)>", text, flags=re.I)}
    unknown_pictures = sorted(used_pictures - valid_pictures)
    if unknown_pictures:
        raise PromptTemplateError(f"输出引用了不存在的参考图：{unknown_pictures}")
    defined_subjects = {int(value) for value in re.findall(r"<Subject\s+(\d+)>", subject_source, flags=re.I)}
    if subject_source:
        used_subjects = {int(value) for value in re.findall(r"<Subject\s+(\d+)>", text, flags=re.I)}
        unknown_subjects = sorted(used_subjects - defined_subjects)
        if unknown_subjects:
            raise PromptTemplateError(f"提示词组引用了公共设定未定义的主体：{unknown_subjects}")


def _validate_language(text: str, language: str) -> None:
    """Reject an obviously wrong output language without rejecting names/dialogue literals."""
    han_count = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if normalize_language(language) == "zh-CN":
        if han_count < 4:
            raise PromptTemplateError("输出语言不是简体中文")
        return
    if latin_count < 20 or han_count > max(8, latin_count // 5):
        raise PromptTemplateError("输出语言不是英文")


def parse_full_reference(text: str, language: str, reference_slots: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = _parse_sections(text, language, include_subject=True)
    _validate_language(parsed.prompt_text, language)
    _validate_references(
        parsed.prompt_text,
        reference_slots,
        subject_source=parsed.sections["subject_definitions"],
    )
    return {"sections": parsed.sections, "prompt_text": parsed.prompt_text}


def parse_director_output(
    text: str,
    language: str,
    reference_slots: list[dict[str, Any]],
    *,
    expected_groups: int,
    expected_shots: list[list[int]] | None = None,
) -> dict[str, Any]:
    if expected_groups < 2 or expected_groups > 8:
        raise PromptTemplateError("连续剧情每个 Part 必须包含 2–8 个提示词组")
    source = str(text or "").strip()
    lang = normalize_language(language)
    public_pattern = r"={3,}\s*(?:公共设定|Public Settings)\s*={3,}"
    public_match = re.search(public_pattern, source, flags=re.I)
    if not public_match or source[: public_match.start()].strip():
        raise PromptTemplateError("连续剧情必须以公共设定分隔行开始")
    group_pattern = r"={3,}\s*(?:提示词组|Prompt Group)\s*(\d+)\s*={3,}"
    group_matches = list(re.finditer(group_pattern, source, flags=re.I))
    if len(group_matches) != expected_groups:
        raise PromptTemplateError(f"应输出 {expected_groups} 个提示词组，实际为 {len(group_matches)} 个")
    numbers = [int(item.group(1)) for item in group_matches]
    if numbers != list(range(1, expected_groups + 1)):
        raise PromptTemplateError("提示词组编号必须从 1 连续递增")
    public_body = source[public_match.end() : group_matches[0].start()].strip()
    public = _parse_sections(public_body, lang, include_subject=True, only_subject=True)
    if set(public.sections) != {"subject_definitions"}:
        raise PromptTemplateError("公共设定只能包含主体定义")
    _validate_references(public.prompt_text, reference_slots)
    _validate_language(public.prompt_text, lang)
    groups = []
    for idx, match in enumerate(group_matches):
        end = group_matches[idx + 1].start() if idx + 1 < len(group_matches) else len(source)
        body = source[match.end() : end].strip()
        parsed = _parse_sections(body, lang, include_subject=False)
        if idx > 0:
            detail = parsed.sections["detailed_description"].lstrip()
            required = "No hard cut. Immediately following the previous section." if lang == "en" else "无硬切。紧接上一段。"
            if not detail.startswith(required):
                raise PromptTemplateError(f"提示词组 {idx + 1} 未以规定的连续性语句开头")
        _validate_references(parsed.prompt_text, reference_slots, subject_source=public.sections["subject_definitions"])
        shot_numbers = [int(value) for value in re.findall(r"\[Shot\s+(\d+)]", parsed.prompt_text, flags=re.I)]
        if not shot_numbers:
            raise PromptTemplateError(f"提示词组 {idx + 1} 缺少 [Shot N] 镜头编号")
        if shot_numbers != sorted(set(shot_numbers)):
            raise PromptTemplateError(f"提示词组 {idx + 1} 的 [Shot N] 必须唯一且递增")
        if expected_shots is not None and idx < len(expected_shots):
            expected = list(dict.fromkeys(int(value) for value in expected_shots[idx]))
            if shot_numbers != expected:
                raise PromptTemplateError(
                    f"提示词组 {idx + 1} 的镜头编号应为 {expected}，实际为 {shot_numbers}"
                )
        _validate_language(parsed.prompt_text, lang)
        groups.append({"sections": parsed.sections, "prompt_text": parsed.prompt_text, "shot_numbers": shot_numbers})
    return {
        "common_setting": {
            "subject_definitions": public.sections["subject_definitions"],
            "prompt_text": public.prompt_text,
        },
        "groups": groups,
    }
