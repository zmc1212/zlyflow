from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from .director_recipe import flatten_recipe_shots, normalize_recipe_payload
from .storage import JobStore


ExecutionScope = Literal["render", "still", "tts", "assets", "frame", "audio", "mux", "all"]

RENDER_SHOT_FIELDS = (
    "jobId", "status", "progress", "error", "compiledPrompt",
    "outputVideoUrl", "outputPath",
)
STILL_SHOT_FIELDS = ("stillUrl", "stillJobId", "stillStatus")
TTS_SHOT_FIELDS = ("ttsStatus", "ttsUrl", "ttsPath", "ttsError", "voiceId")
FRAME_SHOT_FIELDS = (
    "firstFrameUrl", "firstFramePath", "firstFrameJobId",
    "endFrameUrl", "endFramePath", "endFrameJobId",
)
CHARACTER_EXECUTION_FIELDS = ("imageJobId", "imageUrl", "voicePreviewUrl")
LOCATION_EXECUTION_FIELDS = ("imageJobId", "imageUrl")
EXPORT_EXECUTION_FIELDS = (
    "muxStatus", "muxUrl", "muxPath", "muxDurationSec", "muxError", "muxAt",
)


def _take_id(take: dict[str, Any]) -> str:
    return str(take.get("id") or take.get("jobId") or "").strip()


def merge_take_execution(
    latest_takes: list[dict[str, Any]], incoming_takes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge append-only takes without dropping jobs added by another request."""
    merged = [deepcopy(item) for item in latest_takes if isinstance(item, dict)]
    index = {_take_id(item): position for position, item in enumerate(merged) if _take_id(item)}
    for incoming in incoming_takes:
        if not isinstance(incoming, dict):
            continue
        identity = _take_id(incoming)
        if identity and identity in index:
            merged[index[identity]].update(deepcopy(incoming))
        else:
            if identity:
                index[identity] = len(merged)
            merged.append(deepcopy(incoming))
    return merged


def _copy_fields(target: dict[str, Any], source: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in source:
            target[field] = deepcopy(source[field])


def _merge_shot_execution(
    target: dict[str, Any], source: dict[str, Any], scope: ExecutionScope,
) -> None:
    if scope in {"render", "all"}:
        _copy_fields(target, source, RENDER_SHOT_FIELDS)
        source_takes = [item for item in (source.get("takes") or []) if isinstance(item, dict)]
        target_takes = [item for item in (target.get("takes") or []) if isinstance(item, dict)]
        merged_takes = merge_take_execution(target_takes, source_takes)
        target["takes"] = merged_takes
        source_index = source.get("activeTakeIndex")
        if isinstance(source_index, int) and 0 <= source_index < len(source_takes):
            active_id = _take_id(source_takes[source_index])
            if active_id:
                merged_index = next(
                    (index for index, take in enumerate(merged_takes) if _take_id(take) == active_id),
                    None,
                )
                if merged_index is not None:
                    target["activeTakeIndex"] = merged_index
    if scope in {"still", "all"}:
        _copy_fields(target, source, STILL_SHOT_FIELDS)
    if scope in {"tts", "all"}:
        _copy_fields(target, source, TTS_SHOT_FIELDS)
    if scope in {"frame", "all"}:
        _copy_fields(target, source, FRAME_SHOT_FIELDS)


def merge_recipe_execution(
    latest: dict[str, Any],
    incoming: dict[str, Any],
    *,
    scope: ExecutionScope,
    shot_ids: list[str] | set[str] | None = None,
    character_id: str | None = None,
) -> dict[str, Any]:
    """Overlay server-owned execution state onto the latest creative recipe."""
    target = normalize_recipe_payload(latest)
    source = normalize_recipe_payload(incoming)
    wanted = {str(item) for item in (shot_ids or []) if str(item)}
    source_shots = {str(item.get("id")): item for item in flatten_recipe_shots(source)}
    for shot in flatten_recipe_shots(target):
        shot_id = str(shot.get("id") or "")
        if wanted and shot_id not in wanted:
            continue
        source_shot = source_shots.get(shot_id)
        if source_shot is not None:
            _merge_shot_execution(shot, source_shot, scope)

    if scope in {"assets", "all"}:
        for collection, fields in (
            ("characters", CHARACTER_EXECUTION_FIELDS),
            ("locations", LOCATION_EXECUTION_FIELDS),
        ):
            source_items = {
                str(item.get("id")): item
                for item in (source.get(collection) or [])
                if isinstance(item, dict)
            }
            for item in target.get(collection) or []:
                if not isinstance(item, dict):
                    continue
                source_item = source_items.get(str(item.get("id") or ""))
                if source_item is not None:
                    _copy_fields(item, source_item, fields)

    if scope == "tts" and character_id:
        source_characters = {
            str(item.get("id")): item
            for item in (source.get("characters") or [])
            if isinstance(item, dict)
        }
        source_character = source_characters.get(character_id)
        if source_character is not None:
            for character in target.get("characters") or []:
                if isinstance(character, dict) and str(character.get("id") or "") == character_id:
                    _copy_fields(character, source_character, ("voiceId", "voicePreviewUrl"))
                    break
    if scope in {"audio", "all"}:
        target_audio = target.get("audio") if isinstance(target.get("audio"), dict) else {}
        source_audio = source.get("audio") if isinstance(source.get("audio"), dict) else {}
        _copy_fields(target_audio, source_audio, ("bgmUrl", "bgmPath"))
        target["audio"] = target_audio
    if scope in {"mux", "all"}:
        target_export = target.get("export") if isinstance(target.get("export"), dict) else {}
        source_export = source.get("export") if isinstance(source.get("export"), dict) else {}
        _copy_fields(target_export, source_export, EXPORT_EXECUTION_FIELDS)
        target["export"] = target_export
    return target


def persist_recipe_execution(
    store: JobStore,
    project_id: str,
    incoming: dict[str, Any],
    *,
    scope: ExecutionScope,
    shot_ids: list[str] | set[str] | None = None,
    character_id: str | None = None,
) -> dict[str, Any]:
    return store.mutate_director_project_payload(
        project_id,
        lambda latest: merge_recipe_execution(
            latest,
            incoming,
            scope=scope,
            shot_ids=shot_ids,
            character_id=character_id,
        ),
        content_update=False,
    )


def merge_recipe_creative(latest: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Apply user-authored content while preserving all current execution state."""
    target = normalize_recipe_payload(incoming)
    current = normalize_recipe_payload(latest)
    target["agentStatus"] = deepcopy(current.get("agentStatus") or [])
    target["pipelineRun"] = deepcopy(current.get("pipelineRun"))

    current_shots = {str(item.get("id")): item for item in flatten_recipe_shots(current)}
    for shot in flatten_recipe_shots(target):
        current_shot = current_shots.get(str(shot.get("id") or ""))
        if current_shot is not None:
            _merge_shot_execution(shot, current_shot, "all")
            _copy_fields(shot, current_shot, FRAME_SHOT_FIELDS)

    for collection, fields in (
        ("characters", CHARACTER_EXECUTION_FIELDS),
        ("locations", LOCATION_EXECUTION_FIELDS),
    ):
        current_items = {
            str(item.get("id")): item
            for item in (current.get(collection) or [])
            if isinstance(item, dict)
        }
        for item in target.get(collection) or []:
            if not isinstance(item, dict):
                continue
            current_item = current_items.get(str(item.get("id") or ""))
            if current_item is not None:
                _copy_fields(item, current_item, fields)

    target_audio = target.get("audio") if isinstance(target.get("audio"), dict) else {}
    current_audio = current.get("audio") if isinstance(current.get("audio"), dict) else {}
    _copy_fields(target_audio, current_audio, ("bgmUrl", "bgmPath"))
    target["audio"] = target_audio
    target_export = target.get("export") if isinstance(target.get("export"), dict) else {}
    current_export = current.get("export") if isinstance(current.get("export"), dict) else {}
    _copy_fields(target_export, current_export, EXPORT_EXECUTION_FIELDS)
    target["export"] = target_export
    return normalize_recipe_payload(target)
