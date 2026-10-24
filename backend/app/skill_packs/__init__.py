"""Skill-pack recipes and registered pipeline steps.

Plaza 短剧模板是整条制作配方，不是生成页里的 H3 风格芯片。包文件夹提供
``meta.yaml`` + Markdown；平台只维护有限个 Python handler。
"""

from .aspect import (
    DEFAULT_ASPECT,
    WORKSHOP_ASPECT_KEY,
    aspect_orientation_zh,
    document_aspect_hint,
    format_aspect_template,
    persist_workshop_aspect_ratio,
    resolve_workshop_aspect_ratio,
    rewrite_aspect_copy,
    scan_script_aspect_hints,
    triptych_panel_geometry_en,
)
from .binding import (
    extra_mapping,
    merge_project_extra,
    persist_project_settings,
    project_extra_skill_pack_id,
    resolve_skill_pack_id,
    skill_pack_id_of,
    validate_skill_pack_id,
)
from .context import (
    active_skill_pack_id,
    craft_overlay_for_agent,
    craft_overlay_for_stage,
    packing_system_prompt_for,
    skill_pack_scope,
)
from .recipe import (
    DEFAULT_PACK_ID,
    HALF_NARRATED_PACK_ID,
    PackRecipe,
    UnknownSkillPackError,
    UnknownSkillStepError,
    all_packs,
    default_recipe,
    get_pack,
    list_pack_catalog,
    list_pack_payloads,
    list_packs,
    packing_overrides_of,
    recipe_from_mapping,
    skip_program_pack_enabled,
    require_pack,
    reset_pack_cache,
)
from .registry import get_handler, registered_step_ids
from .runner import SkillPipelineRunner, run_workshop_prompt

__all__ = [
    "DEFAULT_ASPECT",
    "DEFAULT_PACK_ID",
    "HALF_NARRATED_PACK_ID",
    "WORKSHOP_ASPECT_KEY",
    "aspect_orientation_zh",
    "document_aspect_hint",
    "format_aspect_template",
    "PackRecipe",
    "SkillPipelineRunner",
    "UnknownSkillPackError",
    "UnknownSkillStepError",
    "active_skill_pack_id",
    "all_packs",
    "craft_overlay_for_agent",
    "craft_overlay_for_stage",
    "default_recipe",
    "extra_mapping",
    "get_handler",
    "get_pack",
    "list_pack_catalog",
    "list_pack_payloads",
    "list_packs",
    "merge_project_extra",
    "packing_overrides_of",
    "packing_system_prompt_for",
    "persist_project_settings",
    "persist_workshop_aspect_ratio",
    "project_extra_skill_pack_id",
    "resolve_workshop_aspect_ratio",
    "recipe_from_mapping",
    "registered_step_ids",
    "require_pack",
    "reset_pack_cache",
    "resolve_skill_pack_id",
    "run_workshop_prompt",
    "skip_program_pack_enabled",
    "skill_pack_id_of",
    "rewrite_aspect_copy",
    "scan_script_aspect_hints",
    "skill_pack_scope",
    "triptych_panel_geometry_en",
    "validate_skill_pack_id",
]
