from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Literal

from ...workflow_registry import WORKFLOWS, WorkflowDefinition, h3_length, workflow_for


@dataclass(frozen=True)
class TimelineRenderCapabilities:
    supports_timeline: bool = True
    supports_multi_segment: bool = True
    max_segments: int = 6
    max_total_frames: int = 1152
    supports_segment_continuity: bool = True
    supports_audio_batch: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_H3_DIRECTOR_CAPABILITIES = TimelineRenderCapabilities()

EpisodeVideoRenderMode = Literal["episode", "shot"]


def episode_video_render_mode(workflow_id: str | None) -> EpisodeVideoRenderMode:
    """Registry decides whole-episode Timeline vs per-shot graphs. Clients cannot override."""
    requested = str(workflow_id or "").strip()
    if not requested:
        return "shot"
    try:
        definition = workflow_for(requested)
    except KeyError:
        return "shot"
    if definition.supports_timeline and definition.supports_multi_segment:
        return "episode"
    return "shot"


def uses_director_timeline(workflow_id: str | None) -> bool:
    return episode_video_render_mode(workflow_id) == "episode"


def listed_episode_r2v_workflows() -> list[WorkflowDefinition]:
    """Workshop-selectable multi-reference video workflows (整集直出 + 逐镜)."""
    return [
        item for item in WORKFLOWS
        if item.media_type == "video"
        and item.reference_mode == "collection"
        and int(item.max_references or 0) >= 3
        and not item.hidden_from_catalog
    ]


def duration_seconds(shot: dict[str, Any], default: float = 8.0) -> float:
    value = shot.get("durationSec", shot.get("duration_sec", shot.get("video_duration", default)))
    try:
        return max(2.0, min(15.0, float(value)))
    except (TypeError, ValueError):
        return default


def frame_count(shot: dict[str, Any], fps: int = 24) -> int:
    return int(h3_length({"duration": duration_seconds(shot, 8.0)}))


def build_timeline_render_request(
    shots: Iterable[dict[str, Any]],
    *,
    render_scope: str,
    episode_id: str | None,
    workflow_id: str,
    render_pass: str = "final",
    task_type: str = "r2v",
) -> dict[str, Any]:
    items = list(shots)
    return {
        "renderScope": render_scope,
        "episodeId": episode_id,
        "workflowId": workflow_id,
        "renderPass": render_pass,
        "shots": [
            {
                "shotId": str(item.get("beat_id") or item.get("shotId") or ""),
                "prompt": str(item.get("prompt") or ""),
                "duration": duration_seconds(item),
                "references": item.get("uploaded_refs") or item.get("references") or [],
                "continuity": item.get("continuity") or {},
            }
            for item in items
        ],
        "timeline_data": {
            "segments": [
                {
                    "shotId": str(item.get("beat_id") or item.get("shotId") or ""),
                    "segmentIndex": index,
                    "duration": duration_seconds(item),
                    "frameCount": frame_count(item),
                    "prompt": str(item.get("prompt") or ""),
                    "references": item.get("uploaded_refs") or item.get("references") or [],
                    "continuity": item.get("continuity") or {},
                    "taskType": task_type,
                }
                for index, item in enumerate(items)
            ]
        },
    }


def plan_timeline_chunks(
    shots: list[dict[str, Any]],
    capabilities: TimelineRenderCapabilities = DEFAULT_H3_DIRECTOR_CAPABILITIES,
) -> list[list[dict[str, Any]]]:
    if not shots:
        return []
    if not capabilities.supports_timeline or not capabilities.supports_multi_segment:
        return [[shot] for shot in shots]
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    frames = 0
    for shot in shots:
        shot_frames = frame_count(shot)
        exceeds = current and (
            len(current) >= max(1, capabilities.max_segments)
            or frames + shot_frames > max(1, capabilities.max_total_frames)
        )
        if exceeds:
            # Prefer the latest scene boundary; if a single scene itself is too
            # long, fall back to the nearest shot boundary.
            split_at = 0
            for boundary in range(1, len(current)):
                previous = current[boundary - 1].get("scene_id") or current[boundary - 1].get("scene")
                current_scene = current[boundary].get("scene_id") or current[boundary].get("scene")
                if previous != current_scene:
                    split_at = boundary
            if split_at:
                chunks.append(current[:split_at])
                current = current[split_at:]
                frames = sum(frame_count(item) for item in current)
            else:
                chunks.append(current)
                current, frames = [], 0
        current.append(shot)
        frames += shot_frames
    if current:
        chunks.append(current)
    return chunks
