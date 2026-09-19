from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_active_pack_id: ContextVar[str | None] = ContextVar("skill_pack_id", default=None)

AGENT_TO_STAGE = {
    "script": "script",
    "characters": "assets",
    "locations": "assets",
    "props": "assets",
    "episodes": "episodes",
    "storyboard": "storyboard",
}


@contextmanager
def skill_pack_scope(pack_id: str | None) -> Iterator[str | None]:
    token = _active_pack_id.set(str(pack_id or "").strip() or None)
    try:
        yield _active_pack_id.get()
    finally:
        _active_pack_id.reset(token)


def active_skill_pack_id() -> str | None:
    return _active_pack_id.get()


def craft_overlay_for_stage(stage: str, pack_id: str | None = None) -> str:
    from .handlers import inject_craft_text
    from .recipe import get_pack

    recipe = get_pack(pack_id if pack_id is not None else active_skill_pack_id())
    if recipe.is_default:
        return ""
    step = str(recipe.director2_overlay.get(stage) or "").strip()
    if stage == "optimize":
        step = step or ("inject_craft" if "optimize" in recipe.surfaces else "")
    if step != "inject_craft":
        return ""
    return inject_craft_text(recipe, stage)


def craft_overlay_for_agent(agent_id: str, pack_id: str | None = None) -> str:
    stage = AGENT_TO_STAGE.get(str(agent_id or "").strip(), str(agent_id or "").strip())
    return craft_overlay_for_stage(stage, pack_id)


def packing_system_prompt_for(
    mode: str,
    duration_seconds: str | int = "8",
    pack_id: str | None = None,
) -> str:
    from ..media_studio.services.h3_prompt_builder import H3PromptBuilder
    from .recipe import packing_overrides_of

    return H3PromptBuilder.packing_system_prompt(
        mode,
        duration_seconds,
        packing_overrides=packing_overrides_of(pack_id),
    )
