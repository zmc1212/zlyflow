from __future__ import annotations

from typing import Any, Iterable

LIBRARY_DEFAULT_LIMIT = 40
LIBRARY_MAX_LIMIT = 100
LIBRARY_MAX_OFFSET = 1_000_000
LIBRARY_UNAVAILABLE_STATUSES = frozenset({"local", "expired"})
LIBRARY_KINDS = ("image", "video")


def _api_path(api_prefix: str, path: str) -> str:
    return f"{api_prefix.rstrip('/')}/{path.lstrip('/')}"


def build_library_entries(jobs: Iterable[dict], *, api_prefix: str = "/api") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        job_title = str(job.get("title") or "").strip()
        job_prompt = str(job.get("prompt") or "")
        for round_data in job.get("rounds") or []:
            created_at = str(round_data.get("created_at") or "")
            for item in round_data.get("generation_items") or []:
                item_id = str(item.get("id") or "")
                for output_index, output in enumerate(item.get("outputs") or []):
                    if not isinstance(output, dict):
                        continue
                    path = str(output.get("path") or "")
                    if not path:
                        continue
                    delivery_status = str(output.get("delivery_status") or "pending")
                    label = str(output.get("label") or "")
                    entries.append({
                        **output,
                        "kind": str(output.get("kind") or ""),
                        "path": path,
                        "label": label,
                        "delivery_status": delivery_status,
                        "download_url": (
                            None
                            if delivery_status == "local"
                            else _api_path(
                                api_prefix,
                                f"jobs/{job_id}/generations/{item_id}/outputs/{output_index}/download",
                            )
                        ),
                        "job_id": job_id or None,
                        "generation_item_id": item_id or None,
                        "output_index": output_index,
                        "job_title": job_title,
                        "created_at": created_at,
                        "_search_text": " ".join(
                            (job_title, job_prompt, label, path, job_id, item_id)
                        ).casefold(),
                    })
    return entries


def _matches_exact(
    entry: dict[str, Any],
    *,
    job_id: str,
    generation_item_id: str,
    output_index: int | None,
) -> bool:
    if job_id and entry.get("job_id") != job_id:
        return False
    if generation_item_id and entry.get("generation_item_id") != generation_item_id:
        return False
    if output_index is not None and entry.get("output_index") != output_index:
        return False
    return True


def _sort_key(entry: dict[str, Any]) -> str:
    return str(entry.get("created_at") or "")


def query_library_entries(
    entries: Iterable[dict[str, Any]],
    *,
    q: str | None = None,
    kind: str | None = None,
    limit: int = LIBRARY_DEFAULT_LIMIT,
    offset: int = 0,
    job_id: str | None = None,
    generation_item_id: str | None = None,
    output_index: int | None = None,
) -> dict[str, Any]:
    needle = (q or "").strip().casefold()
    exact_job_id = (job_id or "").strip()
    exact_item_id = (generation_item_id or "").strip()
    usable = [
        entry
        for entry in entries
        if entry.get("delivery_status") not in LIBRARY_UNAVAILABLE_STATUSES
    ]
    matched = [
        entry
        for entry in usable
        if _matches_exact(
            entry,
            job_id=exact_job_id,
            generation_item_id=exact_item_id,
            output_index=output_index,
        )
        and (not needle or needle in str(entry.get("_search_text") or ""))
    ]
    counts = {name: 0 for name in LIBRARY_KINDS}
    for entry in matched:
        entry_kind = str(entry.get("kind") or "")
        if entry_kind in counts:
            counts[entry_kind] += 1
    filtered = [entry for entry in matched if kind is None or entry.get("kind") == kind]
    ordered = sorted(filtered, key=_sort_key, reverse=True)
    total = len(ordered)
    bounded_limit = max(1, min(int(limit), LIBRARY_MAX_LIMIT))
    bounded_offset = max(0, min(int(offset), LIBRARY_MAX_OFFSET))
    page = ordered[bounded_offset:bounded_offset + bounded_limit]
    items = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in page]
    return {
        "items": items,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
        "has_more": bounded_offset + len(page) < total,
        "counts": counts,
    }
