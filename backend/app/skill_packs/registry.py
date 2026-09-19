from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .recipe import UnknownSkillStepError

StepHandler = Callable[[Any], Any]

STEP_HANDLERS: dict[str, StepHandler] = {}


def register_step(step_id: str) -> Callable[[StepHandler], StepHandler]:
    def decorator(fn: StepHandler) -> StepHandler:
        STEP_HANDLERS[step_id] = fn
        return fn

    return decorator


def registered_step_ids() -> set[str]:
    if not STEP_HANDLERS:
        from . import handlers as _handlers  # noqa: F401
    return set(STEP_HANDLERS)


def get_handler(step_id: str) -> StepHandler:
    registered_step_ids()
    handler = STEP_HANDLERS.get(step_id)
    if handler is None:
        raise UnknownSkillStepError(f"未注册的技能包步骤：{step_id}")
    return handler
