"""Director-craft excerpts and compilers shared by script agents and the H3 workshop."""

from .coverage import (
    COVERAGE_CONTRACT_EXCERPT,
    TAKE_ROLE_LABELS,
    compile_coverage_plan,
    coverage_prompt_errors,
    fidelity_conflict,
    plan_production_takes,
)
from .references import (
    character_subject_line,
    is_identity_portrait_clause,
    reference_authority_errors,
    scene_subject_line,
)

__all__ = [
    "COVERAGE_CONTRACT_EXCERPT",
    "TAKE_ROLE_LABELS",
    "character_subject_line",
    "compile_coverage_plan",
    "coverage_prompt_errors",
    "fidelity_conflict",
    "is_identity_portrait_clause",
    "plan_production_takes",
    "reference_authority_errors",
    "scene_subject_line",
]
