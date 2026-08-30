from __future__ import annotations

from typing import Any, Iterable


FAILED_TAKE_STATUSES = {"failed", "interrupted", "cancelled", "stopped"}
SUCCEEDED_TAKE_STATUSES = {"succeeded", "partial"}


def take_key(take: dict[str, Any]) -> str:
    return str(take.get("id") or take.get("jobId") or "")


def take_is_usable(take: dict[str, Any]) -> bool:
    """Return whether a Take can still be previewed or resolved for export."""
    status = str(take.get("status") or "").lower()
    if status in FAILED_TAKE_STATUSES:
        return False
    return bool(take.get("videoUrl") or take.get("outputPath")) or status in SUCCEEDED_TAKE_STATUSES


def preferred_usable_take(
    shot: dict[str, Any],
    takes: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Honor a valid approval, otherwise use the newest playable Take."""
    candidates = [take for take in (takes if takes is not None else shot.get("takes") or []) if isinstance(take, dict)]
    approved = str(shot.get("approvedTakeId") or shot.get("approved_take_id") or "")
    if approved:
        approved_take = next((take for take in candidates if take_key(take) == approved), None)
        if approved_take is not None and take_is_usable(approved_take):
            return approved_take
    return next((take for take in reversed(candidates) if take_is_usable(take)), None)
