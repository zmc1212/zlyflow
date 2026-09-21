from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .aspect import (
    aspect_orientation_zh,
    format_aspect_template,
    resolve_workshop_aspect_ratio,
    rewrite_aspect_copy,
)
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
        "写稿可看角色卡、道具卡、场景卡与整张/裁切三联；R2V 只送角色卡和本镜绑定道具设定板。"
        "场景与三联必须转写为环境、起幅、主动作和落幅文字，禁止为它们生成 <Picture n>/<Subject n>。"
        "角色卡是多视图设定板，只锁身份，禁止把分格抄进镜头。有绑定道具则上传道具设定板，只锁外形与材质，禁止抄分格。"
    ),
    "workshop": (
        "按官方第 8 / 8.1 步看着本镜剧本与整张三联一次写出中文八块和英文六段。"
        "R2V 只上传角色卡和本镜绑定道具设定板；场景卡、三联母图与起幅/中格/结果裁切格仅供写稿，必须转成文字。"
        "角色卡是多视图设定板，只锁身份，禁止把分格抄进镜头。有绑定道具则上传道具设定板，只锁外形与材质，禁止抄分格。"
    ),
}

_CHARACTER_SHEET_LOCK = (
    "提供身份与外形连续性"
    "（只锁脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头）"
)
_PROP_SHEET_LOCK = (
    "只锁外形与材质，覆盖场景卡里同名陈设（台灯/书籍/电脑等），"
    "禁止把分格、白底或重复小物件带进镜头"
)


def _character_picture_label(name: str = "") -> str:
    who = str(name or "").strip()
    head = f"{who}角色卡" if who else "角色卡"
    return f"{head}，{_CHARACTER_SHEET_LOCK}"


def _prop_picture_label(name: str = "") -> str:
    who = str(name or "").strip()
    head = f"{who}道具卡" if who else "道具卡"
    return f"{head}（多视图设定板），{_PROP_SHEET_LOCK}"


_R2V_SLOT_LIMIT = 9
_COMPOSITION_DROP_ORDER = ("mid", "end")
_TRIPTYCH_PANEL_NAMES = {
    "start": "起幅构图",
    "mid": "中格构图",
    "end": "结果构图",
}


def _triptych_role_from_source(source: str) -> str:
    key = str(source or "").strip().lower()
    if key in {"triptych.mid", "mid"} or key.endswith(".mid"):
        return "mid"
    if key in {"triptych.end", "end"} or key.endswith(".end"):
        return "end"
    return "start"


def _pack_aspect(
    recipe: PackRecipe | None = None,
    *,
    aspect_ratio: Any = None,
    extra: Any = None,
    project_id: str | None = None,
    beat: dict[str, Any] | None = None,
    beat_info: dict[str, Any] | None = None,
) -> str:
    request = aspect_ratio
    if request is None and isinstance(beat_info, dict):
        request = beat_info.get("aspect_ratio")
    if request is None and isinstance(beat, dict):
        request = beat.get("aspect_ratio")
    return resolve_workshop_aspect_ratio(
        request=request,
        extra=extra if extra is not None else beat_info,
        recipe=recipe,
        project_id=project_id,
    )


def _triptych_panel_label(shot_no: str, role: str, aspect: str | None = None) -> str:
    output = resolve_workshop_aspect_ratio(request=aspect)
    crop = f"{output} 构图"
    if role == "mid":
        return (
            f"镜头{shot_no}中格（三联中格 {crop}），同一镜主动作时段构图路标；"
            f"不是新人物；成片始终单一 {output}"
        )
    if role == "end":
        return (
            f"镜头{shot_no}结果（三联右格 {crop}），同一镜落幅构图路标；"
            f"不是新人物；成片始终单一 {output}"
        )
    return (
        f"镜头{shot_no}起幅（三联左格 {crop}），同一镜 00:00 构图锚；"
        "这是时间路标不是新人物；禁止分栏、禁止把三格同时摆进画面、禁止把 16:9 母图当参考图"
    )


def _author_copy_fields(beat: dict[str, Any], aspect: str) -> tuple[str, str, str]:
    heading = rewrite_aspect_copy(
        beat.get("heading") or beat.get("scene") or "完成本镜剧情",
        aspect,
    ).strip() or "完成本镜剧情"
    action = rewrite_aspect_copy(beat.get("action") or "", aspect).strip() or "按已锁定的角色与场景完成这一镜。"
    camera = rewrite_aspect_copy(beat.get("camera") or "", aspect).strip() or "固定机位，必要时小幅度慢速运镜。"
    return heading, action, camera


def _fit_r2v_slots(
    identity: list[dict[str, Any]],
    composition: list[dict[str, Any]],
    limit: int = _R2V_SLOT_LIMIT,
) -> list[dict[str, Any]]:
    core = [item for item in identity if item.get("source") != "props"]
    props = [item for item in identity if item.get("source") == "props"]
    if len(core) >= limit:
        return core[:limit]
    remaining = limit - len(core)
    kept_props = props[:remaining]
    remaining -= len(kept_props)
    kept = list(composition)
    for role in _COMPOSITION_DROP_ORDER:
        if len(kept) <= remaining:
            break
        kept = [item for item in kept if item.get("role") != role]
    return core + kept_props + kept[:remaining]


_HEADING_RE = re.compile(r"^#{2,3}\s+(.+)$", re.M)
_TS_TOKEN = r"00:(?:00:)?(\d{2})(?:\.\d+)?"
_RANGE_RE = re.compile(rf"{_TS_TOKEN}\s*[–\-]\s*{_TS_TOKEN}")
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
_NO_THIRD_PERSON_NARRATION = "本镜无第三人称旁白。角色内心写在对白里，标（内心）。"
_NARRATION_LABEL_RE = re.compile(r"第三人称旁白|第一人称旁白")
ZH_BLOCK_MARK = "<<<ZH>>>"
EN_BLOCK_MARK = "<<<EN>>>"
_EN_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,3}[ \t]*|\*\*[ \t]*|__[ \t]*)?subject_definitions"
    r"(?:[ \t]*(?:\*\*|__))?[ \t]*(?:[:：].*|$)"
)
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
    info = ctx.beat_info if isinstance(ctx.beat_info, dict) else {}
    text = inject_craft_text(
        ctx.recipe,
        stage,
        aspect_ratio=ctx.options.get("aspect_ratio") or info.get("aspect_ratio"),
        extra=ctx.options.get("extra"),
        project_id=ctx.project_id,
    )
    ctx.data["craft_overlay"] = text
    return ctx


def inject_craft_text(
    recipe: PackRecipe,
    stage: str,
    *,
    aspect_ratio: Any = None,
    extra: Any = None,
    project_id: str | None = None,
) -> str:
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
    aspect = _pack_aspect(
        recipe,
        aspect_ratio=aspect_ratio,
        extra=extra,
        project_id=project_id,
    )
    focus = format_aspect_template(str(STAGE_CRAFT_FOCUS.get(stage) or "").strip(), aspect)
    format_note = ""
    if recipe.confirm_format or aspect_ratio or extra or project_id:
        duration_min = (recipe.confirm_format or {}).get("duration_min") or 5
        duration_max = (recipe.confirm_format or {}).get("duration_max") or 15
        format_note = f"\n确认画幅 {aspect}、单镜时长 {duration_min}–{duration_max} 秒后再写连续性。"
        if str((recipe.confirm_format or {}).get("resolution") or "").strip():
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
    info = ctx.beat_info if isinstance(ctx.beat_info, dict) else {}
    fmt["aspect_ratio"] = _pack_aspect(
        ctx.recipe,
        aspect_ratio=ctx.options.get("aspect_ratio") or info.get("aspect_ratio"),
        extra=ctx.options.get("extra"),
        project_id=ctx.project_id,
    )
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

    payload = dict(ctx.options.get("image_payload") or {})
    aspect = ctx.options.get("aspect_ratio")
    if aspect is None and isinstance(ctx.beat_info, dict):
        aspect = ctx.beat_info.get("aspect_ratio")
    if aspect and not payload.get("aspect_ratio"):
        payload["aspect_ratio"] = aspect
    result = StoryboardImageService.enqueue(
        ctx.project_id,
        ctx.episode_id,
        ctx.beat_id or str(beat.get("id") or ""),
        payload,
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
    has_start = bool(public_panel_url(existing.get("start")))
    missing_later = not public_panel_url(existing.get("mid")) or not public_panel_url(existing.get("end"))
    if has_start and not missing_later:
        ctx.data["triptych_panels"] = existing
        return ctx
    source = str(ctx.data.get("triptych_path") or beat.get("triptych_path") or "").strip()
    raw = ctx.data.get("triptych_bytes")
    remote = str(ctx.data.get("triptych_url") or beat.get("triptych_url") or "").strip()
    panels_bytes: dict[str, bytes] = {}
    try:
        if isinstance(raw, (bytes, bytearray)) and raw:
            panels_bytes = split_triptych_bytes(bytes(raw))
        elif source:
            panels_bytes = split_triptych_path(source)
        elif remote.startswith(("http://", "https://")):
            panels_bytes = split_triptych_url(remote)
    except Exception:
        if has_start:
            ctx.data["triptych_panels"] = existing
            return ctx
        raise
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
        prompt = H3PromptBuilder.normalize_authored_ref2va(authored)
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
    info = ctx.beat_info if isinstance(ctx.beat_info, dict) else {}
    aspect = _pack_aspect(
        ctx.recipe,
        aspect_ratio=ctx.options.get("aspect_ratio") or info.get("aspect_ratio"),
        extra=ctx.options.get("extra"),
        beat=ctx.merged_beat(),
        beat_info=info,
        project_id=ctx.project_id,
    )
    slots = bind_r2v_slot_images(ctx.recipe, ctx.merged_beat(), ctx.assets, aspect_ratio=aspect)
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


def build_timestamped_zh_author_system(
    recipe: PackRecipe,
    template: str,
    *,
    aspect_ratio: Any = None,
    extra: Any = None,
    beat_info: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> str:
    fmt = recipe.confirm_format or {}
    aspect = _pack_aspect(
        recipe,
        aspect_ratio=aspect_ratio,
        extra=extra,
        beat_info=beat_info,
        project_id=project_id,
    )
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
        "- 时间码从本镜 00:00 起，覆盖到总时长；只用整秒 00:03，不要 00:02.50，也不要 00:00:15.00。\n"
        "- 八块标题必须逐字，尤其是「参考素材：」。\n"
        "- 按旁白、对白和画面内容切内部分秒。\n"
        "- 禁止把全部台词塞进中间一段。多轮开口、内心、听完再反应必须落在不同的 00:00– 时间段。\n"
        "- 一条连续运镜路径上可以挂多句台词（例如上摇过程说完两句，再下摇内心，再推近）。\n"
        "- 三通道禁止串台：开口只进「对白」；角色内心只进「对白」并标「（内心）」；"
        "第三人称/第一人称旁白只写 user 里的旁白原文。本镜没有旁白时，「旁白」必须写「本镜无第三人称旁白」，"
        "禁止把内心或开口句填进去。\n"
        "- 角色内心挂在触发它的画面时段（如下摇看衣服），禁止因为起幅能看见衣服就在 00:00 先念。\n"
        "- 内心/旁白时段画内人物闭嘴，不要口型同步。"
        "英文开口用 Name (Sn) says:；英文内心必须用 says in an off-screen voiceover，并在 </d> 后写 while ... lips remain completely closed；"
        "禁止内心用 says:。\n"
        "- 每句中文只进一个 <d>；开口句禁止再当内心复制。<d> 顺序必须等于 user 里的表演顺序。\n"
        "- 台词必须逐字，不得改写、概括或翻译。同一人连续多句按问号/句号切开后每句都要出现；可以挂在相邻时间段，禁止改写成半句。\n"
        "- 参考图使用 <Picture n>，与 R2V 上传顺序一致。角色图是单人多视图设定板，只锁脸、发型和服装，不锁姿势；禁止把分格、白底或重复小人带进镜头。道具图是多视图设定板，只锁外形与材质，禁止把分格、白底或重复小物件带进镜头。\n"
        "- R2V 槽位只含角色设定板与本镜绑定道具设定板，按 user 给出的最终 Picture 顺序逐一引用；不得发明额外编号。\n"
        f"- 写稿附图可以看场景卡、整张 16:9 三联和三张 {aspect} 裁切格来写环境、00:00 起幅、主动作与落幅；这些图都不是 Picture 槽位，不上传视频模型。\n"
        f"- 成片必须是单一 {aspect}，禁止分栏、禁止把三格同时摆进画面。\n"
        "- 禁止只输出「官方八块中文分秒稿与英文六段稿」这种说明句。"
    )
    return "\n\n".join(
        part for part in (lock, rules, "官方八块模板（把【】换成这一镜的事实）：", fill)
        if str(part or "").strip()
    )


def build_dual_author_system(
    recipe: PackRecipe,
    template: str,
    *,
    duration_seconds: str | int = "8",
    aspect_ratio: Any = None,
    extra: Any = None,
    beat_info: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> str:
    zh_system = build_timestamped_zh_author_system(
        recipe,
        template,
        aspect_ratio=aspect_ratio,
        extra=extra,
        beat_info=beat_info,
        project_id=project_id,
    )
    aspect = _pack_aspect(
        recipe,
        aspect_ratio=aspect_ratio,
        extra=extra,
        beat_info=beat_info,
        project_id=project_id,
    )
    seconds = str(duration_seconds).strip() or "8"
    headings = " / ".join(f"{name}:" for name in _REF2VA_HEADINGS)
    dual_rules = (
        "一次性输出两块，不要 JSON，不要前言后语，不要 Markdown 围栏。\n"
        f"必须先写 {ZH_BLOCK_MARK}，然后是官方八块中文分秒稿。\n"
        f"再写 {EN_BLOCK_MARK}，然后是 MiniMax H3 Ref2VA 英文六段；每个标题必须独占一行并带英文冒号，顺序为：{headings}。\n"
        "禁止写成无冒号的 subject_definitions，也禁止用中文冒号或 Markdown 标题代替。\n"
        f"英文六段覆盖本镜 {seconds} 秒。detailed_description 必须跟随中文分秒的运镜顺序；"
        "上摇/下摇/短推可以挂多句台词，禁止一句对白一个运镜，禁止硬插 tilt-up / push-in。\n"
        "Three speech channels: spoken lines go only into Chinese 对白 and English Name (Sn) says: <d>[Chinese] ...</d>. "
        "Character inner voice goes only into 对白 marked （内心）; English must use the official off-screen voiceover and stay silent after </d>. "
        "Attach inner voice to the visual beat that triggers it (for example a tilt down onto the clothes); "
        "do not recite it at 00:00 just because the opening frame already shows the outfit. "
        "Third-person/first-person narration may copy only the narration field. "
        "If there is no narration, Chinese 旁白 must say there is no third-person narration; never fill it with inner or spoken lines. "
        "Each Chinese line occupies exactly one <d>; do not copy a spoken line into a second <d> as inner voice. "
        "<d> order must match the numbered performance order in the user message. "
        "Write every tag as <d>[Chinese] ...</d>. Use whole-second timecodes such as 00:00-00:03, not 00:02.50.\n"
        "开口台词写入 <d>[Chinese] ...</d>，保持中文原文，用 Name (Sn) says:。"
        "内心/旁白禁止口型同步 says:，必须用 MiniMax 官方画外音句式，闭嘴写在 </d> 后面：\n"
        "An off-screen inner voice (not produced by the on-screen mouth) "
        "says in an off-screen voiceover: <d>[Chinese] 原文</d> "
        "while all visible characters' lips remain completely closed.\n"
        "禁止：Name says: <d>内心原文</d>；禁止 thinks. In an off-screen inner voiceover。\n"
        "内心时段镜头不要顶在思考者嘴上。\n"
        "身份只锁 <Picture n> 的脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头；道具设定板只锁外形与材质，禁止把分格、白底或重复小物件带进镜头。\n"
        f"场景卡、整张 16:9 三联与三张 {aspect} 裁切格只供写稿，必须转写成环境与分秒构图文字；不得为它们生成 <Picture n>/<Subject n>，也不得上传到 R2V。\n"
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
    aspect_ratio: Any = None,
    extra: Any = None,
    project_id: str | None = None,
) -> str:
    info = beat_info if isinstance(beat_info, dict) else {}
    aspect = _pack_aspect(
        recipe,
        aspect_ratio=aspect_ratio,
        extra=extra,
        beat=beat,
        beat_info=info,
        project_id=project_id,
    )
    seconds = _clip_shot_seconds(recipe, beat)
    planned = bind_r2v_slot_images(recipe, beat, assets, aspect_ratio=aspect)
    shot_no = str(beat.get("story_shot") or beat.get("sequence") or beat.get("id") or "1").strip() or "1"
    heading, action, camera = _author_copy_fields(beat, aspect)
    lines = [
        f"镜号：镜头{shot_no}",
        f"时长：{seconds} 秒（内部时间从 00:00 起到 00:{seconds:02d}）",
        f"镜头目的：{heading}",
        f"动作：{action}",
        f"运镜原文：{camera}",
        f"场景：{str(beat.get('scene') or beat.get('scene_name') or info.get('scene_name') or '').strip() or '未命名场景'}",
    ]
    opening = str(info.get("opening_state") or beat.get("opening_state") or "").strip()
    closing = str(info.get("closing_state") or beat.get("closing_state") or "").strip()
    note = str(info.get("transition_note") or beat.get("transition_note") or "").strip()
    if opening:
        lines.append(f"开场姿势（00:00 必须与此一致，禁止无故改成另一种身体状态）：{opening}")
    if closing:
        lines.append(f"落幅姿势：{closing}")
    if note:
        lines.append(f"切型：{note}")
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
    order_items = _performance_speech_items(beat)
    if order_items:
        lines.append(
            "表演顺序（<d> 必须按此编号；每句中文只进一个 <d>；开口只进对白；"
            "内心只进对白并标（内心），不要写进旁白）："
        )
        for index, item in enumerate(order_items, 1):
            speaker = str(item.get("speaker") or "").strip() or ("角色" if item.get("kind") != "inner" else "旁白")
            label = "内心" if item.get("kind") == "inner" else "开口"
            lines.append(f"{index}. {speaker}（{label}）：{item.get('text')}")
        if any(item.get("kind") == "inner" for item in order_items):
            lines.append(
                "内心挂在触发它的画面时段（如下摇看衣服），不要因为起幅能看见衣服就在 00:00 先念。"
                "英文内心必须 says in an off-screen voiceover，</d> 后立刻 lips remain completely closed。"
            )
            if order_items[0].get("kind") != "inner":
                lines.append("表演顺序第 1 句不是内心：00:00 起幅只写画面或开口，禁止出现内心原文。")
        lines.append("英文每个 <d> 必须写成 <d>[Chinese] 原文</d>；时间码只用整秒，例如 00:00–00:03。")
        lines.append("对白块按表演顺序逐条写（可加时间段，不可改通道、不可漏句）：")
        for item in order_items:
            speaker = str(item.get("speaker") or "").strip() or (
                "角色" if item.get("kind") != "inner" else "旁白"
            )
            label = "内心" if item.get("kind") == "inner" else "开口"
            lines.append(f"- {speaker}（{label}）：{item.get('text')}")
    else:
        lines.append("表演顺序：本镜无开口、无角色内心。")
    narration = _third_person_narration(beat)
    if narration:
        lines.append(f"旁白原文（只进「旁白」块，不要改写成内心或开口）：{narration}")
        lines.append("「旁白」块必须只写上面这条旁白原文，不要抄内心或开口。")
    else:
        lines.append(
            "本镜无第三人称/第一人称旁白。「旁白」必须整段如下，一个字都不要改："
        )
        lines.append(f"- {_NO_THIRD_PERSON_NARRATION}")
    if planned:
        lines.append("最终视频 Picture 槽位（本地 H3 上传顺序；只含角色设定板与本镜道具设定板）：")
        for item in planned:
            lines.append(f"- <Picture {item['index']}> {item['label']}")
    lines.append(
        "场景卡与三联关键帧只供写稿理解环境、构图、调度和动作节奏，不是 Picture 槽位，"
        "不得在正文中为它们发明或保留 <Picture n>/<Subject n>。"
        f"成片始终单一 {aspect}；禁止从三联继承脸、发型、服装或场景风格。"
    )
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
        lines.append("写稿附图（仅供理解，不是 Picture 槽位）：角色/道具图对应上方 Picture；场景卡和三联只转写成环境、构图与时间段文字。")
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

    for item in bind_r2v_slot_images(recipe, beat, assets):
        add(item.get("url"))
    for item in h3_authoring_context_images(recipe, beat, assets):
        add(item.get("url"))
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
        if not _has_block_title(draft, title):
            errors.append(f"缺少八块标题：{title}")
    seconds = _clip_shot_seconds(recipe, beat)
    errors.extend(_timerange_span_errors(draft, seconds))
    planned = bind_r2v_slot_images(recipe, beat, assets or [])
    for item in planned:
        index = item.get("index")
        if index and not re.search(rf"<Picture\s+{re.escape(str(index))}\s*>", draft, flags=re.I):
            errors.append(f"缺少 <Picture {index}>")
    required = _required_speech_atoms(beat)
    han_draft = _han_only(draft)
    for line in required:
        han = _han_only(line)
        if han and han not in han_draft:
            errors.append(f"台词未逐字出现：{line[:80]}")
        elif not han and line not in draft:
            errors.append(f"台词未逐字出现：{line[:80]}")
    errors.extend(_speech_split_errors(draft, required))
    errors.extend(_speech_channel_errors(draft, beat))
    errors.extend(_inner_opening_errors(draft, beat))
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
    match = _EN_HEADING_RE.search(draft)
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
    aspect = _pack_aspect(recipe, beat=beat)
    heading, action, camera = _author_copy_fields(beat, aspect)
    planned = bind_r2v_slot_images(recipe, beat, assets, aspect_ratio=aspect)
    picture_lines = []
    for item in planned:
        picture_lines.append(f"<Picture {item['index']}> {item['label']}")
    values = {
        "duration": str(seconds),
        "aspect_ratio": aspect,
        "orientation": aspect_orientation_zh(aspect),
        "heading": heading,
        "action": action,
        "camera": camera,
        "dialogue": str(beat.get("dialogue") or beat.get("narration") or "").strip() or "本镜可无开口对白。",
        "pictures": "\n".join(picture_lines) or "本镜无 Picture 槽位，使用 T2V。",
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
    *,
    aspect_ratio: Any = None,
) -> list[dict[str, Any]]:
    identity: list[dict[str, Any]] = []
    composition: list[dict[str, Any]] = []
    by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
    full_triptych = str(beat.get("triptych_url") or "").strip()
    shot_no = str(beat.get("story_shot") or beat.get("sequence") or beat.get("id") or "1").strip() or "1"
    aspect = _pack_aspect(recipe, beat=beat, aspect_ratio=aspect_ratio)
    panels = normalize_panels(beat.get("triptych_panels"))
    for spec in recipe.r2v_slots:
        if spec.is_full_triptych:
            continue
        if spec.source == "characters":
            for character in _beat_characters(beat, by_id):
                url = str(character.get("url") or "").strip()
                if not url:
                    continue
                name = character.get("name") or "角色"
                identity.append({
                    "source": "characters",
                    "category": "character",
                    "name": name,
                    "label": _character_picture_label(str(name)),
                    "url": url,
                    "character_id": character.get("id") or "",
                })
        elif spec.source == "scene":
            scene = _beat_scene(beat, by_id)
            url = str(scene.get("url") or "").strip()
            if not url:
                continue
            scene_name = scene.get("name") or str(beat.get("scene") or "场景")
            identity.append({
                "source": "scene",
                "category": "scene",
                "name": scene_name,
                "label": f"{scene_name}场景卡，提供环境空间（不锁站位；桌面陈设以道具卡为准）",
                "url": url,
                "scene_id": scene.get("id") or beat.get("scene_id") or "",
            })
        elif spec.source == "props":
            for prop in _beat_props(beat, by_id):
                url = str(prop.get("url") or "").strip()
                if not url:
                    continue
                name = prop.get("name") or "道具"
                identity.append({
                    "source": "props",
                    "category": "prop",
                    "name": name,
                    "label": _prop_picture_label(str(name)),
                    "url": url,
                    "prop_id": prop.get("id") or "",
                })
        elif spec.source in {"triptych.start", "start", "triptych.mid", "mid", "triptych.end", "end"}:
            role = _triptych_role_from_source(spec.source)
            url = public_panel_url(panels.get(role))
            if not url or url == full_triptych:
                continue
            composition.append({
                "source": f"triptych.{role}" if spec.source in {"start", "mid", "end"} else spec.source,
                "category": "composition",
                "name": _TRIPTYCH_PANEL_NAMES[role],
                "label": _triptych_panel_label(shot_no, role, aspect),
                "url": url,
                "role": role,
            })
        else:
            continue
    slots = _fit_r2v_slots(identity, composition)
    return [{**item, "index": index} for index, item in enumerate(slots, 1)]


def bind_r2v_slot_images(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    aspect_ratio: Any = None,
) -> list[dict[str, Any]]:
    """Return the only images that may be uploaded to the video model.

    Scene cards and triptych frames are authoring context.  H3 cannot reliably
    consume them as composition-only references, so letting them enter R2V
    makes their faces and set dressing compete with the authoritative sheets.
    """
    by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
    planned: list[dict[str, Any]] = []
    for character in _beat_characters(beat, by_id):
        name = character.get("name") or "角色"
        planned.append({
            "source": "characters",
            "category": "character",
            "name": name,
            "label": _character_picture_label(str(name)),
            "url": character.get("url") or "",
            "character_id": character.get("id") or "",
        })
    for prop in _beat_props(beat, by_id):
        name = prop.get("name") or "道具"
        planned.append({
            "source": "props",
            "category": "prop",
            "name": name,
            "label": _prop_picture_label(str(name)),
            "url": prop.get("url") or "",
            "prop_id": prop.get("id") or "",
        })
    bound: list[dict[str, Any]] = []
    for item in planned:
        if item.get("category") not in {"character", "prop"}:
            continue
        url = public_panel_url(item.get("url"))
        if not url.startswith(("http://", "https://")):
            continue
        if any(existing.get("url") == url for existing in bound):
            continue
        bound.append({**item, "url": url, "index": len(bound) + 1})
        if len(bound) >= 9:
            break
    return bound


H3_REFERENCE_POLICY = "identity-props-v2"


def h3_authoring_context_images(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
    *,
    aspect_ratio: Any = None,
) -> list[dict[str, Any]]:
    """Images the writer may inspect, but must never label as Picture slots."""
    result: list[dict[str, Any]] = []
    for item in expand_r2v_slot_plan(recipe, beat, assets, aspect_ratio=aspect_ratio):
        if item.get("category") not in {"scene", "composition"}:
            continue
        url = public_panel_url(item.get("url"))
        if not url.startswith(("http://", "https://")):
            continue
        if any(existing.get("url") == url for existing in result):
            continue
        result.append({**item, "url": url, "authoring_only": True})
    if not any(item.get("category") == "scene" for item in result):
        by_id = {str(item.get("id") or ""): item for item in assets if item.get("id")}
        scene = _beat_scene(beat, by_id)
        scene_url = public_panel_url(scene.get("url"))
        if scene_url.startswith(("http://", "https://")):
            result.append({
                "source": "scene",
                "category": "scene",
                "name": scene.get("name") or str(beat.get("scene") or "场景"),
                "label": "仅供写稿理解环境，不上传视频模型",
                "url": scene_url,
                "scene_id": scene.get("id") or beat.get("scene_id") or "",
                "authoring_only": True,
            })
    panels = normalize_panels(beat.get("triptych_panels"))
    for role in ("start", "mid", "end"):
        url = public_panel_url(panels.get(role))
        if not url.startswith(("http://", "https://")) or any(item.get("url") == url for item in result):
            continue
        result.append({
            "source": f"triptych.{role}",
            "category": "composition",
            "name": _TRIPTYCH_PANEL_NAMES[role],
            "label": "仅供写稿理解构图与动作节奏，不上传视频模型",
            "url": url,
            "role": role,
            "authoring_only": True,
        })
    full = str(beat.get("triptych_url") or "").strip()
    if full.startswith(("http://", "https://")) and not any(item.get("url") == full for item in result):
        result.append({
            "source": "triptych.full",
            "category": "composition",
            "name": "三联关键帧母图",
            "label": "仅供写稿理解构图与动作节奏，不上传视频模型",
            "url": full,
            "authoring_only": True,
        })
    return result


def h3_prompt_context_fingerprint(
    beat: dict[str, Any],
    video_refs: list[dict[str, Any]],
    authoring_context: list[dict[str, Any]],
) -> str:
    import hashlib
    import json

    payload = {
        "policy": H3_REFERENCE_POLICY,
        "video_refs": [
            {
                "category": item.get("category"),
                "character_id": item.get("character_id"),
                "prop_id": item.get("prop_id"),
                "url": item.get("url"),
            }
            for item in video_refs
        ],
        "scene": {
            "id": beat.get("scene_id"),
            "name": beat.get("scene"),
        },
        "authoring_context": [
            {"source": item.get("source"), "url": item.get("url")}
            for item in authoring_context
        ],
        "triptych_job_id": beat.get("triptych_job_id"),
        "triptych_url": beat.get("triptych_url"),
        "triptych_panels": normalize_panels(beat.get("triptych_panels")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def h3_picture_reference_errors(prompt: Any, refs: list[dict[str, Any]]) -> list[str]:
    import re

    text = str(prompt or "")
    valid = {int(item.get("index")) for item in refs if str(item.get("index") or "").isdigit()}
    pictures = {int(value) for value in re.findall(r"<Picture\s+(\d+)\s*>", text, flags=re.I)}
    subjects = {int(value) for value in re.findall(r"<Subject\s+(\d+)\s*>", text, flags=re.I)}
    mentioned = pictures | subjects
    errors: list[str] = []
    for index in sorted(valid):
        if index not in pictures:
            errors.append(f"missing <Picture {index}>")
    invalid = sorted(index for index in mentioned if index not in valid)
    if invalid:
        errors.append("引用了未上传的 Picture 编号：" + "、".join(str(index) for index in invalid))
    if not valid and mentioned:
        errors.append("T2V 镜头不能引用 Picture/Subject")
    return errors


def h3_prompt_reference_state(
    beat: dict[str, Any],
    refs: list[dict[str, Any]],
    current_fingerprint: str,
) -> tuple[str, str]:
    prompt = str(beat.get("h3_prompt") or "").strip()
    if not prompt:
        return "missing", "尚未生成 H3 提示词"
    errors = h3_picture_reference_errors(prompt, refs)
    if str(beat.get("h3_prompt_source") or "").strip() == "generated":
        if str(beat.get("h3_reference_policy") or "").strip() != H3_REFERENCE_POLICY:
            return "stale", "提示词仍使用旧参考图规则，请按新规则重新生成"
        stored = str(beat.get("h3_prompt_context_fingerprint") or "").strip()
        if not stored or stored != current_fingerprint:
            return "stale", "角色、道具、场景或三联写稿上下文已变化，请重新生成 H3 提示词"
        if errors:
            return "stale", "；".join(errors)
        return "current", "提示词与当前角色/道具出片槽位一致"
    if errors:
        return "invalid", "手写提示词的参考编号无效：" + "；".join(errors)
    return "manual", "手写提示词已通过当前 Picture 编号校验"


def r2v_upload_urls(
    recipe: PackRecipe,
    beat: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[str]:
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
        if str(item.get("url") or "").strip() == url:
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
    from ..media_studio.services.character_looks import character_look_image_url

    result: list[dict[str, Any]] = []
    ids = [str(item) for item in (beat.get("character_ids") or []) if str(item)]
    if ids:
        for cid in ids:
            asset = by_id.get(cid) or {}
            result.append({
                "id": cid,
                "name": asset.get("name") or "角色",
                "url": character_look_image_url(asset, beat),
            })
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


def prop_sheet_url(asset: dict[str, Any] | None) -> str:
    from ..media_studio.services.asset_image_prompts import prop_sheet_url as _prop_sheet_url

    return _prop_sheet_url(asset)


def _beat_props(beat: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        url = str(item.get("url") or "").strip()
        if not url:
            return
        key = str(item.get("id") or item.get("name") or url).strip()
        if key and key in seen:
            return
        if key:
            seen.add(key)
        result.append(item)

    ids = [str(item) for item in (beat.get("prop_ids") or []) if str(item)]
    if ids:
        for pid in ids:
            asset = by_id.get(pid) or {}
            add({
                "id": pid,
                "name": asset.get("name") or "道具",
                "url": prop_sheet_url(asset),
            })
        return result
    for item in beat.get("props") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("image_url") or "").strip()
            pid = str(item.get("id") or "").strip()
            if not url and pid:
                url = prop_sheet_url(by_id.get(pid) or {})
            if not url and item.get("name"):
                match = next(
                    (
                        asset for asset in by_id.values()
                        if str(asset.get("name") or "").strip() == str(item.get("name") or "").strip()
                    ),
                    None,
                )
                url = prop_sheet_url(match)
            add({
                "id": pid,
                "name": item.get("name") or "道具",
                "url": url,
            })
            continue
        name = str(item).strip()
        if not name:
            continue
        match = next(
            (asset for asset in by_id.values() if str(asset.get("name") or "").strip() == name),
            None,
        )
        add({"id": str((match or {}).get("id") or ""), "name": name, "url": prop_sheet_url(match)})
    return result


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
    aspect = _pack_aspect(recipe, beat=beat)
    heading, action, camera = _author_copy_fields(beat, aspect)
    purpose = heading
    scene = str(beat.get("scene") or beat.get("heading") or "场景").strip()
    orientation = aspect_orientation_zh(aspect)
    picture_lines = [
        f"- <Picture {item['index']}> {item['label']}"
        for item in planned
    ] or ["- 本镜无 Picture 槽位，使用 T2V"]
    must_lines = [
        f"- {scene} 的空间关系、站位和谁铺满{orientation}",
        f"- {action}",
        f"- 用文字写清起幅、主动作与落幅的连续性，成片保持单一 {aspect}",
    ]
    order_items = _performance_speech_items(beat)
    if order_items:
        dialogue_lines = []
        for item in order_items:
            speaker = str(item.get("speaker") or "").strip() or (
                "角色" if item.get("kind") != "inner" else "旁白"
            )
            label = "内心" if item.get("kind") == "inner" else "开口"
            dialogue_lines.append(f"- {speaker}（{label}）：{item.get('text')}")
        dialogue_block = "\n".join(dialogue_lines)
    else:
        dialogue_block = "- 本镜可无开口对白；未开口人物嘴唇闭合"
    narration = _third_person_narration(beat)
    if narration:
        narration_block = f"- 旁白：“{narration}”"
    else:
        narration_block = f"- {_NO_THIRD_PERSON_NARRATION}"
    return {
        "shot_no": shot_no,
        "purpose": purpose,
        "header": f"镜头{shot_no}，总时长{seconds}秒，内部时间从00:00开始。",
        "镜头目的": f"{purpose}。",
        "参考素材": "\n".join(picture_lines),
        "必须出现的视觉内容": "\n".join(must_lines),
        "按旁白和画面内容切镜": (
            f"- {start_range}：用文字建立{scene}空间、人物关系与 00:00 起幅站位。\n"
            f"- {mid_range}：画面要补出{action}，镜头动作{camera}。\n"
            f"- {end_range}：用文字写明落幅并稳住，保持连续性。"
        ),
        "对白": dialogue_block,
        "旁白": narration_block,
        "画面要求": (
            f"- {camera}\n"
            "- 真人实拍短剧摄影，空间轴线稳定\n"
            f"- 场景卡和三联仅供写稿；把起幅→主动作→落幅转成文字，成片保持单一 {aspect}"
        ),
        "负向约束": (
            "- 不要插画、CG、文字、水印、美颜滤镜、人物消失、瞬移、反射重影\n"
            "- 场景卡、三联母图和三张裁切格都不上传本地 H3，不得声明为 Picture；"
            f"成片必须是单一 {aspect}，不许分栏、不许把三格同时摆进画面\n"
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


def _shot_like(beat: dict[str, Any]) -> dict[str, Any]:
    return {
        "dialogue": beat.get("dialogue"),
        "speaker": beat.get("speaker"),
        "dialogue_turns": beat.get("dialogue_turns"),
        "narration": beat.get("narration"),
        "characters": beat.get("characters") or [],
    }


def _zh_speech_turns(beat: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    return H3PromptBuilder.split_spoken_and_inner(_shot_like(beat))


def _third_person_narration(beat: dict[str, Any]) -> str:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    return H3PromptBuilder.third_person_narration(_shot_like(beat))


def _performance_speech_items(beat: dict[str, Any]) -> list[dict[str, str]]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    narration_han = _han_only(_third_person_narration(beat))
    items: list[dict[str, str]] = []
    for event in H3PromptBuilder.ordered_speech_events(_shot_like(beat)):
        kind = str(event.get("kind") or "spoken")
        speaker = str(event.get("speaker") or "").strip()
        text = str(event.get("text") or "").strip()
        if not text:
            continue
        if kind == "inner" and narration_han and _han_only(text) == narration_han and not speaker:
            continue
        for atom in H3PromptBuilder.split_speech_atoms(text):
            items.append({"kind": kind, "speaker": speaker, "text": atom})
    return items


def _extract_official_block(text: str, title: str) -> str:
    titles = "|".join(re.escape(item) for item in _OFFICIAL_BLOCK_TITLES)
    pattern = re.compile(
        rf"{re.escape(title)}：\s*\n(.*?)(?=\n(?:{titles})：|\Z)",
        re.S,
    )
    match = pattern.search(str(text or ""))
    return match.group(1).strip() if match else ""


def _speech_atoms_from_turns(turns: list[dict[str, Any]]) -> list[str]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    atoms: list[str] = []
    seen: set[str] = set()
    for item in turns:
        for atom in H3PromptBuilder.split_speech_atoms(str(item.get("text") or "")):
            key = _han_only(atom) or atom
            if not key or key in seen:
                continue
            seen.add(key)
            atoms.append(atom)
    return atoms


def _speech_channel_errors(text: str, beat: dict[str, Any]) -> list[str]:
    spoken_atoms = [
        str(item.get("text") or "").strip()
        for item in _performance_speech_items(beat)
        if item.get("kind") != "inner" and str(item.get("text") or "").strip()
    ]
    inner_atoms = [
        str(item.get("text") or "").strip()
        for item in _performance_speech_items(beat)
        if item.get("kind") == "inner" and str(item.get("text") or "").strip()
    ]
    draft = str(text or "")
    lines = [line.strip() for line in draft.splitlines() if str(line).strip()]
    errors: list[str] = []
    seen: set[str] = set()

    def add(message: str) -> None:
        if message not in seen:
            seen.add(message)
            errors.append(message)

    for atom in inner_atoms:
        han = _han_only(atom)
        if len(han) < 4:
            continue
        for line in lines:
            if han in _han_only(line) and _NARRATION_LABEL_RE.search(line):
                add(f"内心原文出现在第三人称/第一人称旁白：{atom[:80]}")
                break
    for atom in spoken_atoms:
        han = _han_only(atom)
        if len(han) < 4:
            continue
        for line in lines:
            if han in _han_only(line) and "内心" in line:
                add(f"开口原文被标成内心：{atom[:80]}")
                break
    if not _third_person_narration(beat):
        block_han = _han_only(_extract_official_block(draft, "旁白"))
        for atom in (*spoken_atoms, *inner_atoms):
            han = _han_only(atom)
            if len(han) >= 4 and han in block_han:
                add(f"无第三人称旁白时，旁白块不得写入开口或内心：{atom[:80]}")
    return errors


def _has_block_title(draft: str, title: str) -> bool:
    text = str(draft or "")
    if title in text:
        return True
    stripped = re.sub(r"\ufffd+", "", text)
    if title in stripped:
        return True
    for index in range(len(title)):
        candidate = title[:index] + title[index + 1 :]
        if len(candidate) < 3:
            continue
        if re.search(rf"^(?:\ufffd)*{re.escape(candidate)}：", text, flags=re.M):
            return True
        if re.search(rf"^{re.escape(candidate)}：", stripped, flags=re.M):
            return True
    return False


def _inner_opening_errors(text: str, beat: dict[str, Any]) -> list[str]:
    items = _performance_speech_items(beat)
    if not items or items[0].get("kind") == "inner":
        return []
    inner_atoms = [
        str(item.get("text") or "").strip()
        for item in items
        if item.get("kind") == "inner" and str(item.get("text") or "").strip()
    ]
    if not inner_atoms:
        return []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        found = _RANGE_RE.search(raw)
        if not found or int(found.group(1)) != 0:
            continue
        line_han = _han_only(raw)
        for atom in inner_atoms:
            han = _han_only(atom)
            if len(han) < 4 or han not in line_han:
                continue
            message = f"内心不要写在 00:00 起幅：{atom[:80]}"
            if message not in seen:
                seen.add(message)
                errors.append(message)
    return errors


def _required_speech_atoms(beat: dict[str, Any]) -> list[str]:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder

    spoken, inner = _zh_speech_turns(beat)
    lines: list[str] = []
    seen: set[str] = set()
    for item in (*spoken, *inner):
        for atom in H3PromptBuilder.split_speech_atoms(str(item.get("text") or "")):
            key = _han_only(atom) or atom
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(atom)
    return lines


def _timerange_span_errors(text: str, seconds: int) -> list[str]:
    spans = [
        (int(start), int(end))
        for start, end in _RANGE_RE.findall(str(text or ""))
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
    return """【画幅与时长】{{aspect_ratio}}，{{duration}} 秒。成片必须是单一{{orientation}}，不许分栏。
【参考图合同】
{{pictures}}
【空间建立】{{heading}}。{{start_range}} 锁定起幅站位与景深。
【分秒动作】
{{mid_range}} {{action}}
{{end_range}} 落到结果构图并稳住。
【运镜】{{camera}}
【对白与旁白】{{dialogue}}
内心/旁白闭嘴画外音，英文用 says in an off-screen voiceover，不要口型同步 says:。
【声音】环境声与动作同步，不要抢台词。
【禁止】不要把三联参考图画成一条胶片；不要姓名牌、字幕、水印。技能包：{{pack_name}}。"""
