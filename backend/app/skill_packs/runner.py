from __future__ import annotations

from typing import Any

from .handlers import StepContext
from .recipe import PackRecipe, default_recipe, get_pack
from .registry import get_handler


class SkillPipelineRunner:
    def run(
        self,
        recipe: PackRecipe | str | None,
        surface: str,
        ctx: StepContext | None = None,
        *,
        stage: str | None = None,
        steps: list[str] | None = None,
    ) -> StepContext:
        pack = recipe if isinstance(recipe, PackRecipe) else get_pack(recipe)
        context = ctx or StepContext(recipe=pack, surface=surface, stage=stage or "")
        context.recipe = pack
        context.surface = surface
        if stage:
            context.stage = stage
        sequence = steps if steps is not None else list(pack.steps_for(surface, stage=context.stage or stage))
        for step_id in sequence:
            handler = get_handler(step_id)
            handler(context)
        return context

    def run_workshop_shot(self, recipe: PackRecipe | str | None, ctx: StepContext) -> StepContext:
        return self.run(recipe, "workshop", ctx)


def run_workshop_prompt(beat_info: dict[str, Any], *, ctx: StepContext | None = None) -> str:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder
    from .binding import resolve_skill_pack_id

    info = dict(beat_info or {})
    pack_id = str(info.get("skill_pack_id") or "").strip()
    if not pack_id:
        pack_id = resolve_skill_pack_id(payload=info, project_id=info.get("project_id"))
        if pack_id:
            info["skill_pack_id"] = pack_id
    recipe = get_pack(pack_id) if pack_id else default_recipe()
    context = ctx or StepContext(recipe=recipe, surface="workshop", beat_info=info)
    context.recipe = recipe
    context.beat_info = dict(info)
    context.project_id = str(context.project_id or info.get("project_id") or "")
    context.episode_id = str(context.episode_id or info.get("episode_id") or "")
    context.beat_id = str(context.beat_id or info.get("beat_id") or "")
    context.assets = list(context.assets or info.get("assets") or [])
    if "enqueue_images" not in context.options:
        # H3 提示词路径默认不入队三联生图；工坊显式出图时再打开。
        context.options["enqueue_images"] = False
    if not context.assets and context.project_id:
        try:
            from ..media_studio.services.project_detail_service import ProjectDetailService

            context.assets = list(ProjectDetailService.list_assets(context.project_id) or [])
        except Exception:
            context.assets = []
    if not context.beat:
        context.beat = dict(info)
    runner = SkillPipelineRunner()
    runner.run_workshop_shot(recipe, context)
    prompt = str(context.data.get("h3_prompt") or context.beat_updates.get("h3_prompt") or "")
    if isinstance(beat_info, dict):
        zh_prompt = str(context.data.get("timestamped_zh_prompt") or context.beat_updates.get("timestamped_zh_prompt") or "")
        if zh_prompt:
            beat_info["timestamped_zh_prompt"] = zh_prompt
            if not str(beat_info.get("video_prompt_zh") or "").strip():
                beat_info["video_prompt_zh"] = zh_prompt
        if context.data.get("ref_images"):
            beat_info["ref_images"] = context.data["ref_images"]
        for key in (
            "authored_en_prompt",
            "authored_en_valid",
            "authored_en_attempted",
            "vision_status",
            "vision_model",
            "vision_image_count",
            "vision_source",
        ):
            if key in context.data:
                beat_info[key] = context.data[key]
            elif key in context.beat_updates:
                beat_info[key] = context.beat_updates[key]
    if prompt:
        return prompt
    if recipe.packing_overrides.skip_program_pack:
        from ..media_studio.services.llm_service import DualShotAuthorError

        raise DualShotAuthorError(
            "写稿未通过校验：英文六段缺失或标题不齐",
            errors=["英文六段缺失或标题不齐"],
            zh_prompt=str((beat_info or {}).get("timestamped_zh_prompt") or ""),
            en_prompt="",
        )
    shot = H3PromptBuilder.shot_from_beat_info(info)
    return H3PromptBuilder.render_ref2va(shot)
