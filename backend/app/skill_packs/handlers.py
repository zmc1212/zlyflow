from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .recipe import PackRecipe
from .registry import register_step
from .triptych import (
    normalize_panels,
    persist_panel_bytes,
    public_panel_url,
    split_triptych_bytes,
    split_triptych_path,
    split_triptych_url,
)

STAGE_SECTION_HEADINGS = {
    "script": (
        "1. inspiration and concept",
        "2. story and script",
        "灵感",
        "故事与剧本",
    ),
    "assets": (
        "3. character and scene cards",
        "角色卡",
        "场景卡",
        "定妆",
    ),
    "episodes": (
        "2. story and script",
        "故事与剧本",
        "分集",
    ),
    "storyboard": (
        "4. storyboard and shot contract",
        "5. keyframe generation",
        "分镜",
        "镜头合同",
    ),
    "optimize": (
        "8. video generation",
        "8.1 video prompt assembly order",
        "成片",
        "提示词",
    ),
    "workshop": (
        "5. keyframe generation",
        "8. video generation",
        "8.1 video prompt assembly order",
        "三联",
        "提示词",
    ),
}

STAGE_CRAFT_FOCUS = {
    "script": (
        "本阶段只写故事与剧本：对白/旁白与画面说明必须分开（双通道）。"
        "不要把台词写进动作段，也不要把调度写进台词。本包 MiniMax-H3 单镜 5–15 整数秒，不要再用 2–15。"
    ),
    "assets": (
        "本阶段只写角色卡与场景卡：16:9 纯白底 continuity 卡。"
        "角色左特写、右为正侧背半身；场景无人、无标题水印。promptText 按 casting / continuity photo 写，不要概念插画。"
    ),
    "episodes": (
        "本阶段只切分集结构与节奏：对白与画面说明保持分离，不要另写一套故事，也不要发明未声明的工具。"
    ),
    "storyboard": (
        "本阶段写成可执行镜头合同：MiniMax-H3 单镜 5–15 整数秒，短于 5 秒的相邻节拍合并；"
        "时间码从本镜 00:00 起。列出角色卡、场景卡与三联关键帧映射。"
    ),
    "optimize": (
        "按官方第 8 / 8.1 步一次看图写出中文八块分秒稿和英文六段 Ref2VA，不要按一句对白重排运镜。"
        "R2V 只送角色卡、场景卡和三联起幅，不要把整张三联送进本地 H3。"
        "角色卡是多视图设定板，只锁身份，禁止把分格抄进镜头。"
    ),
    "workshop": (
        "按官方第 8 / 8.1 步看着本镜剧本与三联一次写出中文八块和英文六段。"
        "末槽只用起幅单帧，中格/右格用文字分秒演。"
        "角色卡是多视图设定板，只锁身份，禁止把分格抄进镜头。"
    ),
}

_CHARACTER_SHEET_LOCK = (
    "提供身份与外形连续性"
    "（只锁脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头）"
)


def _character_picture_label(name: str = "") -> str:
    who = str(name or "").strip()
    head = f"{who}角色卡" if who else "角色卡"
    return f"{head}，{_CHARACTER_SHEET_LOCK}"


_HEADING_RE = re.compile(r"^#{2,3}\s+(.+)$", re.M)
_RANGE_RE = re.compile(r"00:\d{2}\s*[–\-]\s*00:\d{2}")
_TEMPLATE_FENCE_RE = re.compile(r"```(?:text)?\s*\n(.*?)```", re.S)
_OFFICIAL_BLOCK_TITLES = (
    "镜头目的",
    "参考素材",
    "必须出现的视觉内容",
    "按旁白和画面内容切镜",
    "对白",
    "旁白",
    "画面要求",
    "负向约束",
)
ZH_BLOCK_MARK = "<<<ZH>>>"
EN_BLOCK_MARK = "<<<EN>>>"
_EN_HEADING_RE = re.compile(r"(?im)^subject_definitions:\s*")
_REF2VA_HEADINGS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


@dataclass
class StepContext:
    recipe: PackRecipe
    surface: str = "workshop"
    stage: str = ""
    project_id: str = ""
    episode_id: str = ""
    beat_id: str = ""
    beat: dict[str, Any] = field(default_factory=dict)
    assets: list[dict[str, Any]] = field(default_factory=list)
    beat_info: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    beat_updates: dict[str, Any] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)

    def merged_beat(self) -> dict[str, Any]:
        return {**self.beat, **self.beat_updates}


@register_step("inject_craft")
def inject_craft(ctx: StepContext) -> StepContext:
    stage = ctx.stage or ctx.surface
    text = inject_craft_text(ctx.recipe, stage)
    ctx.data["craft_overlay"] = text
    return ctx


def inject_craft_text(recipe: PackRecipe, stage: str) -> str:
    markdown = recipe.skill_markdown()
    if not markdown:
        return ""
    sections = _split_markdown_sections(markdown)
    hints = STAGE_SECTION_HEADINGS.get(stage, ())
    picked: list[str] = []
    for heading, body in sections:
        if _heading_matches(heading, hints):
            picked.append(f"## {heading}\n{body.strip()}".strip())
    if not picked:
        picked = [markdown]
    header = (
        f"【技能包 {recipe.name}】把下面的官方章节写进本阶段输出。"
        "不要改成另一套导演台阶段，也不要发明未声明的工具调用。"
    )
    focus = str(STAGE_CRAFT_FOCUS.get(stage) or "").strip()
    format_note = ""
    if recipe.confirm_format:
        aspect = recipe.confirm_format.get("aspect_ratio") or "9:16"
        duration_min = recipe.confirm_format.get("duration_min") or 5
        duration_max = recipe.confirm_format.get("duration_max") or 15
        format_note = f"\n确认画幅 {aspect}、单镜时长 {duration_min}–{duration_max} 秒后再写连续性。"
        if str(recipe.confirm_format.get("resolution") or "").strip():
            format_note += " 出片前由用户确认视频分辨率 2K 或 768P，整集统一。"
    visual = f"\nvisual_lock={recipe.visual_lock}" if recipe.visual_lock else ""
    parts = [header + visual + format_note]
    if focus:
        parts.append(focus)
    parts.extend(picked)
    return "\n\n".join(parts).strip()


@register_step("confirm_format")
def confirm_format(ctx: StepContext) -> StepContext:
    fmt = dict(ctx.recipe.confirm_format or {})
    fmt.setdefault("aspect_ratio", "9:16")
    fmt.setdefault("duration_min", 5)
    fmt.setdefault("duration_max", 15)
    ctx.data["confirm_format"] = fmt
    return ctx


@register_step("generate_shot_triptych")
def generate_shot_triptych(ctx: StepContext) -> StepContext:
    beat = ctx.merged_beat()
    if str(beat.get("triptych_url") or "").strip():
        ctx.data["triptych_skipped"] = "already_present"
        return ctx
    if not _has_character_and_scene(beat):
        ctx.data["triptych_skipped"] = "missing_refs"
        return ctx
    if ctx.options.get("enqueue_images") is False or not ctx.project_id or not ctx.episode_id:
        ctx.data["triptych_would_enqueue"] = True
        return ctx
    from ..media_studio.services.storyboard_image_service import StoryboardImageService

    result = StoryboardImageService.enqueue(
        ctx.project_id,
        ctx.episode_id,
        ctx.beat_id or str(beat.get("id") or ""),
        ctx.options.get("image_payload") or {},
        "triptych",
    )
    ctx.jobs.append(result)
    ctx.data["triptych_job"] = result
    if result.get("job_id"):
        ctx.beat_updates["triptych_job_id"] = result["job_id"]
    return ctx


@register_step("extract_triptych_panels")
def extract_triptych_panels(ctx: StepContext) -> StepContext:
    beat = ctx.merged_beat()
    existing = normalize_panels(beat.get("triptych_panels"))
    if public_panel_url(existing.get("start")):
        ctx.data["triptych_panels"] = existing
        return ctx
    source = str(ctx.data.get("triptych_path") or beat.get("triptych_path") or "").strip()
    raw = ctx.data.get("triptych_bytes")
    remote = str(ctx.data.get("triptych_url") or beat.get("triptych_url") or "").strip()
    panels_bytes: dict[str, bytes] = {}
    if isinstance(raw, (bytes, bytearray)) and raw:
        panels_bytes = split_triptych_bytes(bytes(raw))
    elif source:
        panels_bytes = split_triptych_path(source)
    elif remote.startswith(("http://", "https://")):
        panels_bytes = split_triptych_url(remote)
    if not panels_bytes:
        ctx.data["triptych_panels"] = existing
        return ctx
    stored = _store_panel_bytes(ctx, panels_bytes)
    ctx.beat_updates["triptych_panels"] = stored
    ctx.data["triptych_panels"] = stored
    return ctx


@register_step("write_timestamped_zh_prompt")
def write_timestamped_zh_prompt(ctx: StepContext) -> StepContext:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder
    from ..media_studio.services.llm_service import DualShotAuthorError, DualShotAuthorResult, LlmService

    template = (
        ctx.recipe.reference_text("h3-video-prompt-template.md")
        or ctx.recipe.reference_text("shot-prompt-template.md")
    )
    beat = ctx.merged_beat()
    authored = LlmService.author_timestamped_zh_prompt(
        ctx.recipe,
        beat,
        ctx.assets,
        template,
        beat_info=ctx.beat_info,
    )
    result = authored if isinstance(authored, DualShotAuthorResult) else None
    text = str((result.zh_prompt if result is not None else authored) or "").strip()
    if result is not None and ctx.beat_info is not None:
        LlmService._apply_author_result(ctx.beat_info, result)
    skip_pack = bool(ctx.recipe.packing_overrides.skip_program_pack)
    authored_en = str((result.en_prompt if result is not None else "") or "").strip()
    if skip_pack and (
        result is None
        or not result.en_valid
        or not H3PromptBuilder.has_ref2va_headings(authored_en)
    ):
        raise DualShotAuthorError(
            "写稿未通过校验：英文六段缺失或标题不齐",
            errors=["英文六段缺失或标题不齐"],
            zh_prompt=text,
            en_prompt=authored_en,
            vision=result.vision if result is not None else None,
        )
    if not text:
        raise DualShotAuthorError(
            "写稿未通过校验：中文分秒稿为空",
            errors=["中文分秒稿为空"],
            zh_prompt=text,
            en_prompt=authored_en,
            vision=result.vision if result is not None else None,
        )
    ctx.beat_updates["timestamped_zh_prompt"] = text
    ctx.data["timestamped_zh_prompt"] = text
    if result is not None:
        ctx.data["authored_en_prompt"] = result.en_prompt
        ctx.data["authored_en_valid"] = result.en_valid
        ctx.data["authored_en_attempted"] = True
        ctx.data.update(result.vision.as_dict())
        ctx.beat_updates["authored_en_prompt"] = result.en_prompt
        ctx.beat_updates["authored_en_valid"] = result.en_valid
        ctx.beat_updates.update(result.vision.as_dict())
        if result.en_valid and result.en_prompt:
            ctx.data["h3_prompt"] = result.en_prompt
    if not str(beat.get("video_prompt_zh") or "").strip():
        ctx.beat_updates["video_prompt_zh"] = text
    return ctx


@register_step("polish_ref2va")
def polish_ref2va(ctx: StepContext) -> StepContext:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    if ctx.recipe.r2v_slots:
        slots = bind_r2v_slot_images(ctx.recipe, ctx.merged_beat(), ctx.assets)
        if slots:
            ctx.data["ref_images"] = slots
            ctx.beat_info = {**(ctx.beat_info or {}), "ref_images": slots}
    skip_pack = bool(ctx.recipe.packing_overrides.skip_program_pack)
    authored = str(
        ctx.data.get("authored_en_prompt")
        or ctx.merged_beat().get("authored_en_prompt")
        or (ctx.beat_info or {}).get("authored_en_prompt")
        or ""
    ).strip()
    shot = _shot_from_context(ctx)
    if skip_pack:
        if not authored or not H3PromptBuilder.has_ref2va_headings(authored):
            from ..media_studio.services.llm_service import DualShotAuthorError

            raise DualShotAuthorError(
                "写稿未通过校验：英文六段缺失或标题不齐",
                errors=["英文六段缺失或标题不齐"],
                zh_prompt=str(ctx.data.get("timestamped_zh_prompt") or ""),
                en_prompt=authored,
            )
        prompt = H3PromptBuilder.canonicalize_reference_tags(authored)
    else:
        prompt = H3PromptBuilder.render_ref2va(shot)
        zh_prompt = str(
            ctx.data.get("timestamped_zh_prompt")
            or ctx.merged_beat().get("timestamped_zh_prompt")
            or ""
        )
        prompt = apply_timeranges_to_ref2va(prompt, zh_prompt, ctx.recipe.packing_overrides.as_dict())
    ctx.data["h3_prompt"] = prompt
    from .context import packing_system_prompt_for

    ctx.data["polish_system_prompt"] = packing_system_prompt_for(
        "Ref2VA",
        shot.get("duration_seconds") or 8,
        ctx.recipe.id,
    )
    ctx.beat_updates["h3_prompt"] = prompt
    return ctx


@register_step("bind_r2v_slots")
def bind_r2v_slots(ctx: StepContext) -> StepContext:
    slots = bind_r2v_slot_images(ctx.recipe, ctx.merged_beat(), ctx.assets)
    ctx.data["ref_images"] = slots
    ctx.beat_updates["ref_images"] = slots
    if ctx.beat_info is not None:
        ctx.beat_info["ref_images"] = slots
    return ctx


@register_step("render_ref2va_default")
def render_ref2va_default(ctx: StepContext) -> StepContext:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    shot = _shot_from_context(ctx)
    prompt = H3PromptBuilder.render_ref2va(shot)
    ctx.data["h3_prompt"] = prompt
    ctx.beat_updates["h3_prompt"] = prompt
    return ctx


def build_timestamped_zh_author_system(recipe: PackRecipe, template: str) -> str:
    fmt = recipe.confirm_format or {}
    aspect = str(fmt.get("aspect_ratio") or "9:16")
    duration_min = fmt.get("duration_min") or 5
    duration_max = fmt.get("duration_max") or 15
    fill = _extract_official_fill_skeleton(template) or str(template or "").strip()
    lock = (
        f"你是半解说真人短剧的双稿作者。visual_lock={recipe.visual_lock or 'photoreal-live-action-short-drama'}。"
        f"成片 {aspect}，单镜 {duration_min}–{duration_max} 秒。"
        "不要写字幕、Design 平台步骤或工作流说明。"
    )
    rules = (
        "中文块只写官方八块分秒稿；可见回复必须是完整两块正文，"
        f"先输出 {ZH_BLOCK_MARK} 再输出 {EN_BLOCK_MARK}，不要前言后语，不要 Markdown 围栏。\n"
        "硬规则：\n"
        "- 时间码从本镜 00:00 起，覆盖到总时长；按旁白、对白和画面内容切内部分秒。\n"
        "- 禁止把全部台词塞进中间一段。多轮开口、内心、听完再反应必须落在不同的 00:00– 时间段。\n"
        "- 一条连续运镜路径上可以挂多句台词（例如上摇过程说完两句，再下摇内心，再推近）。\n"
        "- 内心/旁白时段画内人物闭嘴，不要口型同步。\n"
        "- 台词必须逐字，不得改写、概括或翻译。\n"
        "- 参考图使用 <Picture n>，与 R2V 上传顺序一致。角色图是单人多视图设定板，只锁脸、发型和服装，不锁姿势；禁止把分格、白底或重复小人带进镜头。\n"
        "- 末槽写明起幅单帧锚点，中格/右格用文字分秒演；不要把整张三联送进本地 H3。\n"
        f"- 成片必须是单一 {aspect}，禁止分栏。\n"
        "- 禁止只输出「官方八块中文分秒稿与英文六段稿」这种说明句。"
    )
    return "\n\n".join(
        part for part in (lock, rules, "官方八块模板（把【】换成这一镜的事实）：", fill)
        if str(part or "").strip()
    )


def build_dual_author_system(recipe: PackRecipe, template: str, *, duration_seconds: str | int = "8") -> str:
    zh_system = build_timestamped_zh_author_system(recipe, template)
    seconds = str(duration_seconds).strip() or "8"
    headings = " / ".join(_REF2VA_HEADINGS)
    dual_rules = (
        "一次性输出两块，不要 JSON，不要前言后语，不要 Markdown 围栏。\n"
        f"必须先写 {ZH_BLOCK_MARK}，然后是官方八块中文分秒稿。\n"
        f"再写 {EN_BLOCK_MARK}，然后是 MiniMax H3 Ref2VA 英文六段，标题必须齐全且按此顺序：{headings}。\n"
        f"英文六段覆盖本镜 {seconds} 秒。detailed_description 必须跟随中文分秒的运镜顺序；"
        "上摇/下摇/短推可以挂多句台词，禁止一句对白一个运镜，禁止硬插 tilt-up / push-in。\n"
        "开口台词写入 <d>[Chinese] ...</d>，保持中文原文；内心/旁白闭嘴画外，不要口型同步。\n"
        "身份只锁 <Picture n> 的脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头；场景卡不锁站位。\n"
        "本地 H3 仍只吃角色卡、场景卡和起幅，不要把整张三联写进 R2V 槽位。\n"
        "禁止装箱器口吻：不要只输出英文成品稿；不要禁止对话标签；"
        "不要用占位符代替逐字中文台词；不要灌水凑词；不要省略中文八块。\n"
        "可见回复必须是两块完整正文，不要先写计划或摘要，"
        "禁止只写「官方八块中文分秒稿与」「英文六段稿。」"
    )
    return "\n\n".join(part for part in (zh_system, dual_rules) if str(part or "").strip())


def build_timestamped_zh_author_user(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    beat_info: dict[str, Any] | None = None,
) -> str:
    info = beat_info if isinstance(beat_info, dict) else {}
    seconds = _clip_shot_seconds(recipe, beat)
    planned = expand_r2v_slot_plan(recipe, beat, assets)
    shot_no = str(beat.get("story_shot") or beat.get("sequence") or beat.get("id") or "1").strip() or "1"
    lines = [
        f"镜号：镜头{shot_no}",
        f"时长：{seconds} 秒（内部时间从 00:00 起到 00:{seconds:02d}）",
        f"镜头目的：{str(beat.get('heading') or beat.get('scene') or '完成本镜剧情').strip()}",
        f"动作：{str(beat.get('action') or '').strip() or '按已锁定的角色与场景完成这一镜。'}",
        f"运镜原文：{str(beat.get('camera') or '').strip() or '固定机位，必要时小幅度慢速运镜。'}",
        f"场景：{str(beat.get('scene') or beat.get('scene_name') or info.get('scene_name') or '').strip() or '未命名场景'}",
    ]
    scene_desc = str(beat.get("scene_desc") or beat.get("scene_description") or info.get("scene_desc") or "").strip()
    if scene_desc:
        lines.append(f"场景卡描述：{scene_desc}")
    by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
    characters = _beat_characters(beat, by_id)
    if characters:
        lines.append("角色卡：")
        for item in characters:
            asset = by_id.get(str(item.get("id") or "")) or {}
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            desc = str(
                item.get("look_desc")
                or item.get("desc")
                or extra.get("description")
                or extra.get("look_desc")
                or ""
            ).strip()
            lines.append(f"- {item.get('name') or '角色'}" + (f"：{desc}" if desc else ""))
    spoken, inner = _zh_speech_turns(beat)
    if spoken:
        lines.append("开口对白（开口 vs 内心已拆开，必须逐字写入对应时间段）：")
        for turn in spoken:
            speaker = str(turn.get("speaker") or "").strip() or "角色"
            lines.append(f"- {speaker}（开口）：{turn.get('text')}")
    else:
        lines.append("开口对白：本镜可无开口对白。")
    if inner:
        lines.append("内心/旁白（画内闭嘴）：")
        for turn in inner:
            speaker = str(turn.get("speaker") or "").strip() or "旁白"
            lines.append(f"- {speaker}（内心/旁白）：{turn.get('text')}")
    narration = str(beat.get("narration") or "").strip()
    if narration and not any(narration == str(item.get("text") or "") for item in inner):
        lines.append(f"旁白原文：{narration}")
    if planned:
        lines.append("R2V 槽位（本地 H3 上传顺序；末槽只是起幅单帧）：")
        for item in planned:
            lines.append(f"- <Picture {item['index']}> {item['label']}")
    lines.append("三联左/中/右职责：左格=空间建立，中格=主动作，右格=结果或情绪收束。中格/右格用文字分秒演，不要把整张三联当参考图。")
    previous = str(
        info.get("previous_shot")
        or info.get("previous_shot_summary")
        or beat.get("previous_shot")
        or beat.get("previous_shot_summary")
        or ""
    ).strip()
    if previous:
        lines.append(f"上一镜承接：{previous}")
    image_notes = collect_zh_author_image_urls(recipe, beat, assets)
    if image_notes:
        lines.append("附图顺序（若已随请求发送）：角色卡、场景卡，然后是整张三联母图或左/中/右裁切，供看图写分秒。")
        for index, url in enumerate(image_notes, 1):
            lines.append(f"- 图{index}: {url}")
    lines.append(
        "从下一行开始直接输出完整 <<<ZH>>> 和 <<<EN>>> 两块正文。"
        "不要输出「官方八块中文分秒稿与英文六段稿」这种说明。"
    )
    return "\n".join(lines)


def collect_zh_author_image_urls(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[str]:
    urls: list[str] = []

    def add(url: Any) -> None:
        text = str(url or "").strip()
        if text.startswith(("http://", "https://")) and text not in urls:
            urls.append(text)

    planned = expand_r2v_slot_plan(recipe, beat, assets)
    for item in planned:
        source = str(item.get("source") or "")
        if source in {"characters", "scene"}:
            add(item.get("url"))
    full = str(beat.get("triptych_url") or "").strip()
    if full.startswith(("http://", "https://")):
        add(full)
    else:
        panels = normalize_panels(beat.get("triptych_panels"))
        for key in ("start", "mid", "end"):
            add(public_panel_url(panels.get(key)))
    return urls[:8]


def is_stub_zh_prompt(text: str) -> bool:
    draft = str(text or "").strip()
    if not draft:
        return True
    compact = re.sub(r"\s+", "", draft)
    titled = sum(1 for title in _OFFICIAL_BLOCK_TITLES if title in draft)
    if re.search(r"官方八块|英文六段稿|说明句", compact) and titled < 4:
        return True
    return titled < 4 and (len(draft) < 120 or not _RANGE_RE.search(draft))


def is_stub_en_prompt(text: str) -> bool:
    draft = str(text or "").strip()
    if not draft:
        return True
    compact = re.sub(r"\s+", "", draft)
    lower = draft.lower()
    headings = sum(
        1
        for title in (
            "subject_definitions",
            "summary",
            "retention_analysis",
            "detailed_description",
            "overall_soundscape",
            "non_diegetic_music",
        )
        if title in lower
    )
    if re.search(r"英文六段|official eight|instruction", compact, re.I) and headings < 3:
        return True
    return headings < 3 and len(draft) < 80


def validate_timestamped_zh_prompt(
    text: str,
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]] | None = None,
) -> list[str]:
    draft = _extract_timestamped_zh_prompt(text)
    errors: list[str] = []
    if not draft:
        return ["中文分秒稿为空"]
    if is_stub_zh_prompt(draft):
        return [
            "上轮只输出了说明句，必须在 <<<ZH>>> 里从「镜头目的：」写到「负向约束：」，并写分秒和对白原文"
        ]
    for title in _OFFICIAL_BLOCK_TITLES:
        if title not in draft:
            errors.append(f"缺少八块标题：{title}")
    seconds = _clip_shot_seconds(recipe, beat)
    errors.extend(_timerange_span_errors(draft, seconds))
    planned = expand_r2v_slot_plan(recipe, beat, assets or [])
    for item in planned:
        index = item.get("index")
        if index and not re.search(rf"<Picture\s+{re.escape(str(index))}\s*>", draft, flags=re.I):
            errors.append(f"缺少 <Picture {index}>")
    spoken, inner = _zh_speech_turns(beat)
    required = [str(item.get("text") or "").strip() for item in (*spoken, *inner) if str(item.get("text") or "").strip()]
    han_draft = _han_only(draft)
    for line in required:
        han = _han_only(line)
        if han and han not in han_draft:
            errors.append(f"台词未逐字出现：{line[:80]}")
    errors.extend(_speech_split_errors(draft, required))
    return errors


def extract_timestamped_zh_prompt(text: str) -> str:
    return _extract_timestamped_zh_prompt(text)


def parse_dual_author_output(raw: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if not text:
        return "", ""
    zh_at = text.find(ZH_BLOCK_MARK)
    en_at = text.find(EN_BLOCK_MARK)
    if zh_at >= 0 and en_at >= 0:
        if zh_at < en_at:
            zh = text[zh_at + len(ZH_BLOCK_MARK) : en_at]
            en = text[en_at + len(EN_BLOCK_MARK) :]
        else:
            en = text[en_at + len(EN_BLOCK_MARK) : zh_at]
            zh = text[zh_at + len(ZH_BLOCK_MARK) :]
        return zh.strip(), en.strip()
    if zh_at >= 0:
        return text[zh_at + len(ZH_BLOCK_MARK) :].strip(), ""
    if en_at >= 0:
        return "", text[en_at + len(EN_BLOCK_MARK) :].strip()
    has_zh = "镜头目的" in text
    en_match = _EN_HEADING_RE.search(text)
    if has_zh and en_match:
        return text[: en_match.start()].strip(), text[en_match.start() :].strip()
    if en_match and not has_zh:
        return "", text
    return text, ""


def extract_ref2va_prompt(text: str) -> str:
    draft = str(text or "").strip()
    if not draft:
        return ""
    if draft.startswith("```"):
        draft = re.sub(r"^```(?:text|markdown|md)?\s*", "", draft)
        draft = re.sub(r"\s*```$", "", draft).strip()
    match = re.search(r"(?im)^subject_definitions:\s*", draft)
    if match:
        draft = draft[match.start() :]
    return draft.strip()


def fill_timestamped_zh_prompt(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    template: str,
) -> str:
    """骨架填空仅供模板单测，不进入工坊成功路径。"""
    seconds = _clip_shot_seconds(recipe, beat)
    start_range, mid_range, end_range = _shot_time_ranges(seconds)
    planned = expand_r2v_slot_plan(recipe, beat, assets)
    picture_lines = []
    for item in planned:
        picture_lines.append(f"<Picture {item['index']}> {item['label']}")
    values = {
        "duration": str(seconds),
        "aspect_ratio": (recipe.confirm_format or {}).get("aspect_ratio") or "9:16",
        "heading": str(beat.get("heading") or beat.get("scene") or "本镜"),
        "action": str(beat.get("action") or "").strip() or "按已锁定的角色与场景完成这一镜。",
        "camera": str(beat.get("camera") or "").strip() or "固定机位，必要时小幅度慢速运镜。",
        "dialogue": str(beat.get("dialogue") or beat.get("narration") or "").strip() or "本镜可无开口对白。",
        "pictures": "\n".join(picture_lines) or f"<Picture 1> {_character_picture_label()}",
        "start_range": start_range,
        "mid_range": mid_range,
        "end_range": end_range,
        "pack_name": recipe.name,
    }
    raw_template = template.strip() if template.strip() else ""
    if "{{duration}}" in raw_template or "{{pictures}}" in raw_template:
        text = raw_template
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", str(value))
        if "00:00" not in text:
            text += f"\n\n【分秒动作】\n{start_range} {values['action']}"
        return text.strip()
    skeleton = _extract_official_fill_skeleton(raw_template)
    if skeleton:
        return _fill_official_skeleton(recipe, beat, planned, seconds, start_range, mid_range, end_range, skeleton)
    return _fill_official_h3_template(recipe, beat, planned, seconds, start_range, mid_range, end_range)


def apply_timeranges_to_ref2va(prompt: str, zh_prompt: str, packing_overrides: dict[str, Any] | None = None) -> str:
    overrides = packing_overrides or {}
    if overrides.get("skip_program_pack") or not overrides.get("allow_timeranges"):
        return prompt
    ranges = _range_lines(zh_prompt)
    if not ranges:
        ranges = ["00:00–00:05 opening composition from the start-frame still, then the main action."]
    marker = "detailed_description:"
    if marker not in prompt:
        return prompt
    head, tail = prompt.split(marker, 1)
    body = tail.strip()
    if _RANGE_RE.search(body):
        return prompt
    injected = " ".join(ranges)
    if body.startswith("[Shot 1]"):
        body = body.replace("[Shot 1]", f"[Shot 1] {injected}", 1)
    else:
        body = f"[Shot 1] {injected} {body}"
    return f"{head}{marker}\n{body}".strip()


def expand_r2v_slot_plan(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
    for spec in recipe.r2v_slots:
        if spec.is_full_triptych:
            continue
        if spec.source == "characters":
            for character in _beat_characters(beat, by_id):
                name = character.get("name") or "角色"
                slots.append({
                    "source": "characters",
                    "category": "character",
                    "name": name,
                    "label": _character_picture_label(str(name)),
                    "url": character.get("url") or "",
                    "character_id": character.get("id") or "",
                })
        elif spec.source == "scene":
            scene = _beat_scene(beat, by_id)
            scene_name = scene.get("name") or str(beat.get("scene") or "场景")
            slots.append({
                "source": "scene",
                "category": "scene",
                "name": scene_name,
                "label": f"{scene_name}场景卡，提供环境空间（不锁站位）",
                "url": scene.get("url") or "",
                "scene_id": scene.get("id") or beat.get("scene_id") or "",
            })
        elif spec.source in {"triptych.start", "start"}:
            panels = normalize_panels(beat.get("triptych_panels"))
            start_url = public_panel_url(panels.get("start"))
            if not start_url:
                continue
            shot_no = str(beat.get("story_shot") or beat.get("sequence") or beat.get("id") or "1").strip() or "1"
            slots.append({
                "source": "triptych.start",
                "category": "composition",
                "name": "起幅构图",
                "label": (
                    f"镜头{shot_no}起幅单帧（三联左格裁切），提供构图锚点；"
                    "中格/右格用文字分秒演，不要把整张三联送进本地 H3"
                ),
                "url": start_url,
                "role": "start",
            })
        elif spec.source in {"triptych.mid", "mid", "triptych.end", "end"}:
            key = "mid" if "mid" in spec.source else "end"
            panels = normalize_panels(beat.get("triptych_panels"))
            slots.append({
                "source": spec.source,
                "category": "composition",
                "name": "中格" if key == "mid" else "结果构图",
                "label": f"三联{key}格，默认不送进 R2V。",
                "url": public_panel_url(panels.get(key)),
                "role": key,
            })
        else:
            continue
    indexed: list[dict[str, Any]] = []
    for index, item in enumerate(slots[:9], 1):
        indexed.append({**item, "index": index})
    return indexed


def bind_r2v_slot_images(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planned = expand_r2v_slot_plan(recipe, beat, assets)
    full_triptych = str(beat.get("triptych_url") or "").strip()
    bound: list[dict[str, Any]] = []
    for item in planned:
        url = public_panel_url(item.get("url"))
        if item.get("source") == "triptych.start" and url and url == full_triptych:
            continue
        if item.get("source") in {"triptych", "triptych.full"}:
            continue
        if url == full_triptych and item.get("role") not in {"start", "mid", "end"}:
            continue
        bound.append({**item, "url": url})
    return bound


def r2v_upload_urls(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[str]:
    if recipe.is_default or not recipe.r2v_slots:
        return []
    return [
        str(item.get("url") or "").strip()
        for item in bind_r2v_slot_images(recipe, beat, assets)
        if str(item.get("url") or "").startswith(("http://", "https://"))
    ]


def slot_contains_full_triptych(slots: list[dict[str, Any]], triptych_url: str) -> bool:
    url = str(triptych_url or "").strip()
    if not url:
        return False
    for item in slots:
        source = str(item.get("source") or "")
        if source in {"triptych", "triptych.full", "triptych_url"}:
            return True
        if source == "triptych.start":
            continue
        if str(item.get("url") or "").strip() == url and item.get("role") not in {"start", "mid", "end"}:
            return True
    return False


def _heading_matches(heading: str, hints: tuple[str, ...]) -> bool:
    key = str(heading or "").strip().lower()
    key = re.sub(r"^#+\s*", "", key)
    return any(str(hint or "").strip().lower() in key for hint in hints if str(hint or "").strip())


def _split_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        return [("SKILL", markdown)]
    sections: list[tuple[str, str]] = []
    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        sections.append(("概述", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[match.end():end].strip()))
    return sections


def _has_character_and_scene(beat: dict[str, Any]) -> bool:
    characters = beat.get("character_ids") or beat.get("characters") or []
    scene = beat.get("scene_id") or beat.get("scene")
    return bool(characters) and bool(str(scene or "").strip())


def _beat_characters(beat: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids = [str(item) for item in (beat.get("character_ids") or []) if str(item)]
    if ids:
        for cid in ids:
            asset = by_id.get(cid) or {}
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            identities = extra.get("identities") if isinstance(extra.get("identities"), list) else []
            look_ids = beat.get("character_look_ids") if isinstance(beat.get("character_look_ids"), dict) else {}
            selected_id = str(look_ids.get(cid) or beat.get("character_look_id") or "").strip()
            selected = next((item for item in identities if str((item or {}).get("id") or "") == selected_id), None)
            url = ""
            if isinstance(selected, dict):
                url = str(selected.get("image_url") or "").strip()
            if not url:
                url = str(extra.get("avatar_url") or asset.get("image_url") or "").strip()
            if not url:
                for look in identities:
                    if not isinstance(look, dict):
                        continue
                    url = str(look.get("image_url") or "").strip()
                    if url:
                        break
            result.append({"id": cid, "name": asset.get("name") or "角色", "url": url})
        return result
    for item in beat.get("characters") or []:
        if isinstance(item, dict):
            result.append({
                "id": item.get("id") or "",
                "name": item.get("name") or "角色",
                "url": item.get("url") or item.get("image_url") or "",
            })
        elif str(item).strip():
            result.append({"id": "", "name": str(item).strip(), "url": ""})
    return result


def _beat_scene(beat: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scene_id = str(beat.get("scene_id") or "").strip()
    asset = by_id.get(scene_id) if scene_id else {}
    extra = asset.get("extra") if isinstance((asset or {}).get("extra"), dict) else {}
    url = str(extra.get("master_url") or extra.get("image_url") or (asset or {}).get("image_url") or "").strip()
    return {
        "id": scene_id,
        "name": (asset or {}).get("name") or beat.get("scene") or "场景",
        "url": url,
    }


def _shot_from_context(ctx: StepContext) -> dict[str, Any]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    beat_info = dict(ctx.beat_info or {})
    beat = ctx.merged_beat()
    if ctx.data.get("ref_images"):
        beat_info["ref_images"] = ctx.data["ref_images"]
    elif beat.get("ref_images"):
        beat_info["ref_images"] = beat.get("ref_images")
    if not beat_info:
        beat_info = {
            "action": beat.get("action") or "",
            "camera": beat.get("camera") or "",
            "dialogue": beat.get("dialogue") or "",
            "characters": beat.get("characters") or [],
            "scene_name": beat.get("scene") or "",
            "duration_seconds": beat.get("duration_seconds") or beat.get("video_duration") or 8,
            "ref_images": beat.get("ref_images") or [],
        }
    shot = H3PromptBuilder.shot_from_beat_info(
        beat_info,
        beat_id=str(ctx.beat_id or beat.get("id") or "beat"),
        sequence=int(beat.get("sequence") or 1),
    )
    zh_prompt = str(
        ctx.data.get("timestamped_zh_prompt")
        or beat.get("timestamped_zh_prompt")
        or beat_info.get("timestamped_zh_prompt")
        or ""
    ).strip()
    if zh_prompt:
        shot["timestamped_zh_prompt"] = zh_prompt
    if ctx.recipe.packing_overrides.faithful_zh_pack:
        shot["faithful_zh_pack"] = True
        shot["skill_pack_id"] = ctx.recipe.id
    return shot


def _clip_shot_seconds(recipe: PackRecipe, beat: dict[str, Any]) -> int:
    fmt = recipe.confirm_format or {}
    try:
        lo = max(1, int(float(fmt.get("duration_min") or 5)))
    except (TypeError, ValueError):
        lo = 5
    try:
        hi = max(lo, int(float(fmt.get("duration_max") or 15)))
    except (TypeError, ValueError):
        hi = 15
    raw = str(beat.get("duration_seconds") or beat.get("video_duration") or "").strip()
    try:
        seconds = int(float(raw)) if raw else max(lo, min(hi, 8))
    except (TypeError, ValueError):
        seconds = max(lo, min(hi, 8))
    return max(lo, min(hi, seconds))


def _shot_time_ranges(seconds: int) -> tuple[str, str, str]:
    start_end = max(2, min(seconds - 2, int(seconds * 0.3 + 0.5)))
    mid_end = max(start_end + 1, min(seconds - 1, int(seconds * 0.7 + 0.5)))
    return (
        f"00:00–00:{start_end:02d}",
        f"00:{start_end:02d}–00:{mid_end:02d}",
        f"00:{mid_end:02d}–00:{seconds:02d}",
    )


def _extract_official_fill_skeleton(template: str) -> str:
    if not template:
        return ""
    match = _TEMPLATE_FENCE_RE.search(template)
    if not match:
        return ""
    block = match.group(1).strip()
    if "镜头【编号】" in block or "内部时间从00:00开始" in block:
        return block
    return ""


def _replace_official_block(text: str, title: str, body: str) -> str:
    titles = "|".join(re.escape(item) for item in _OFFICIAL_BLOCK_TITLES)
    pattern = re.compile(
        rf"({re.escape(title)}：\s*\n)(.*?)(?=\n(?:{titles})：|\Z)",
        re.S,
    )

    def repl(match: re.Match[str]) -> str:
        return match.group(1) + body.rstrip() + "\n"

    updated, count = pattern.subn(repl, text, count=1)
    return updated if count else text


def _official_prompt_blocks(
    recipe: PackRecipe,
    beat: dict[str, Any],
    planned: list[dict[str, Any]],
    seconds: int,
    start_range: str,
    mid_range: str,
    end_range: str,
) -> dict[str, str]:
    shot_no = str(beat.get("story_shot") or beat.get("sequence") or beat.get("id") or "1").strip() or "1"
    purpose = str(beat.get("heading") or beat.get("action") or beat.get("scene") or "完成本镜剧情").strip()
    action = str(beat.get("action") or "").strip() or "按已锁定的角色与场景完成这一镜。"
    camera = str(beat.get("camera") or "").strip() or "固定机位，必要时小幅度慢速运镜。"
    scene = str(beat.get("scene") or beat.get("heading") or "场景").strip()
    picture_lines = [
        f"- <Picture {item['index']}> {item['label']}"
        for item in planned
    ] or [f"- <Picture 1> {_character_picture_label()}"]
    must_lines = [
        f"- {scene} 的空间关系、站位和谁铺满竖屏",
        f"- {action}",
        "- 起幅构图与结果构图的连续性，成片保持单一 9:16",
    ]
    speaker = str(beat.get("speaker") or "").strip() or "角色"
    dialogue = str(beat.get("dialogue") or "").strip()
    if dialogue:
        dialogue_block = (
            f"- {speaker}在 {mid_range} 说：“{dialogue}”\n"
            "- 其他人物不说话，嘴唇闭合"
        )
    else:
        dialogue_block = "- 本镜可无开口对白；未开口人物嘴唇闭合"
    narration = str(beat.get("narration") or "").strip()
    if narration:
        narration_block = f"- {end_range} 旁白：“{narration}”"
    else:
        narration_block = "- 本镜可无旁白；旁白/内心时段人物嘴唇闭合"
    return {
        "shot_no": shot_no,
        "purpose": purpose,
        "header": f"镜头{shot_no}，总时长{seconds}秒，内部时间从00:00开始。",
        "镜头目的": f"{purpose}。",
        "参考素材": "\n".join(picture_lines),
        "必须出现的视觉内容": "\n".join(must_lines),
        "按旁白和画面内容切镜": (
            f"- {start_range}：建立{scene}空间与人物关系，用起幅构图锁站位。\n"
            f"- {mid_range}：画面要补出{action}，镜头动作{camera}。\n"
            f"- {end_range}：画面收束到结果构图并稳住，保持连续性。"
        ),
        "对白": dialogue_block,
        "旁白": narration_block,
        "画面要求": (
            f"- {camera}\n"
            "- 真人实拍短剧摄影，空间轴线稳定\n"
            "- 起幅图只作构图锚点；中格/右格用文字分秒演"
        ),
        "负向约束": (
            "- 不要插画、CG、文字、水印、美颜滤镜、人物消失、瞬移、反射重影\n"
            "- 不要把整张三联参考图送进本地 H3；成片必须是单一 9:16，不许分栏\n"
            f"- 技能包：{recipe.name}"
        ),
    }


def _fill_official_skeleton(
    recipe: PackRecipe,
    beat: dict[str, Any],
    planned: list[dict[str, Any]],
    seconds: int,
    start_range: str,
    mid_range: str,
    end_range: str,
    skeleton: str,
) -> str:
    blocks = _official_prompt_blocks(recipe, beat, planned, seconds, start_range, mid_range, end_range)
    text = skeleton
    text = re.sub(r"镜头【编号】", f"镜头{blocks['shot_no']}", text, count=1)
    text = re.sub(r"总时长【X】秒", f"总时长{seconds}秒", text, count=1)
    text = re.sub(r"【这个镜头在剧情里要完成什么】", blocks["purpose"], text, count=1)
    for title in _OFFICIAL_BLOCK_TITLES:
        text = _replace_official_block(text, title, blocks[title])
    return text.strip()


def _fill_official_h3_template(
    recipe: PackRecipe,
    beat: dict[str, Any],
    planned: list[dict[str, Any]],
    seconds: int,
    start_range: str,
    mid_range: str,
    end_range: str,
) -> str:
    blocks = _official_prompt_blocks(recipe, beat, planned, seconds, start_range, mid_range, end_range)
    return (
        f"{blocks['header']}\n"
        f"镜头目的：{blocks['镜头目的']}\n\n"
        f"参考素材：\n{blocks['参考素材']}\n\n"
        f"必须出现的视觉内容：\n{blocks['必须出现的视觉内容']}\n\n"
        f"按旁白和画面内容切镜：\n{blocks['按旁白和画面内容切镜']}\n\n"
        f"对白：\n{blocks['对白']}\n\n"
        f"旁白：\n{blocks['旁白']}\n\n"
        f"画面要求：\n{blocks['画面要求']}\n\n"
        f"负向约束：\n{blocks['负向约束']}"
    )


def _store_panel_bytes(ctx: StepContext, panels: dict[str, bytes]) -> dict[str, str]:
    stored = normalize_panels(ctx.merged_beat().get("triptych_panels"))
    if ctx.options.get("store_panels") is False:
        for key, data in panels.items():
            stored[key] = f"memory:{key}:{len(data)}"
        return stored
    uploaded = persist_panel_bytes(panels)
    for key, url in uploaded.items():
        stored[key] = url or stored.get(key) or ""
    return stored


def _range_lines(zh_prompt: str) -> list[str]:
    lines: list[str] = []
    for raw in str(zh_prompt or "").splitlines():
        if _RANGE_RE.search(raw):
            lines.append(raw.strip())
    return lines


def _han_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", str(text or "")))


def _extract_timestamped_zh_prompt(text: str) -> str:
    draft = str(text or "").strip()
    if not draft:
        return ""
    if draft.startswith("```"):
        draft = re.sub(r"^```(?:text|markdown|md)?\s*", "", draft)
        draft = re.sub(r"\s*```$", "", draft).strip()
    start = draft.find("镜头")
    if start < 0:
        start = draft.find("镜头目的")
    if start > 0:
        draft = draft[start:]
    return draft.strip()


def _zh_speech_turns(beat: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    shot = {
        "dialogue": beat.get("dialogue"),
        "speaker": beat.get("speaker"),
        "dialogue_turns": beat.get("dialogue_turns"),
        "narration": beat.get("narration"),
        "characters": beat.get("characters") or [],
    }
    return H3PromptBuilder.split_spoken_and_inner(shot)


def _timerange_span_errors(text: str, seconds: int) -> list[str]:
    spans = [
        (int(start), int(end))
        for start, end in re.findall(r"00:(\d{2})\s*[–\-]\s*00:(\d{2})", str(text or ""))
    ]
    if not spans:
        return ["缺少分秒时间码"]
    errors: list[str] = []
    if min(start for start, _end in spans) != 0:
        errors.append("时间码必须从 00:00 起")
    if max(end for _start, end in spans) < int(seconds):
        errors.append(f"分秒未覆盖到总时长 00:{int(seconds):02d}")
    return errors


def _speech_split_errors(text: str, required: list[str]) -> list[str]:
    lines = [str(item or "").strip() for item in required if str(item or "").strip()]
    if len(lines) < 2:
        return []
    range_lines = _range_lines(text)
    if not range_lines:
        return ["多轮对白缺少分秒时间段"]
    assigned: list[str] = []
    for line in lines:
        han = _han_only(line)
        if not han:
            continue
        matched = ""
        for raw in range_lines:
            if han in _han_only(raw):
                found = _RANGE_RE.search(raw)
                if found:
                    matched = found.group(0)
                    break
        if matched:
            assigned.append(matched)
    if len(assigned) >= 2 and len(set(assigned)) == 1:
        return ["多轮对白必须拆进不同时间段，禁止整段落在同一段"]
    if len(set(assigned)) < 2:
        return ["多轮对白必须拆进不同时间段，禁止整段落在同一段"]
    return []


def _fallback_zh_template() -> str:
    return """【画幅与时长】{{aspect_ratio}}，{{duration}} 秒。成片必须是单一竖屏，不许分栏。
【参考图合同】
{{pictures}}
【空间建立】{{heading}}。{{start_range}} 锁定起幅站位与景深。
【分秒动作】
{{mid_range}} {{action}}
{{end_range}} 落到结果构图并稳住。
【运镜】{{camera}}
【对白与旁白】{{dialogue}}
内心/旁白闭嘴画外音，不要口型同步。
【声音】环境声与动作同步，不要抢台词。
【禁止】不要把三联参考图画成一条胶片；不要姓名牌、字幕、水印。技能包：{{pack_name}}。"""
