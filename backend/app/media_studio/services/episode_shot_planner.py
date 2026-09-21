"""按集规划可出片镜头：prompt、JSON 归一化、单镜时长夹取到 5–15 秒。"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from ...llm_minimax_skills import (
    load_import_shot_continuity_excerpt,
    load_shot_continuity_excerpt,
)
from ...skill_packs.aspect import (
    apply_confirmed_aspect_to_shot,
    aspect_orientation_zh,
    resolve_workshop_aspect_ratio,
)
from .script_parser import StandardScriptParser

SHOT_DURATION_MIN_SEC = 5
SHOT_DURATION_MAX_SEC = 15
DEFAULT_SHOT_DURATION_SEC = 8
SHOTS_SOURCE_LLM = "llm"
AI_PIPELINE_INPUT_MODE = "ai_pipeline"
CONTINUITY_WINDOW_SIZE = 5
CONTINUITY_WINDOW_OVERLAP = 1
CONTINUITY_REFINE_MIN_SHOTS = 2
CONTINUITY_EDITABLE_FIELDS = (
    "action",
    "visual_prompt",
    "opening_state",
    "closing_state",
    "transition_note",
)
SHOT_HANDOFF_FIELDS = ("opening_state", "closing_state", "transition_note")

SHOT_TEXT_FIELDS = (
    "title",
    "scene",
    "action",
    "camera",
    "dialogue",
    "visual_prompt",
    "audio",
    "subtitle",
    "raw_content",
    *SHOT_HANDOFF_FIELDS,
)
SHOT_LIST_FIELDS = ("characters", "props")
_DURATION_KEYS = ("duration_sec", "duration", "video_duration", "durationSec", "duration_seconds")
_FORBIDDEN_TEMPLATE_TERMS = ("口型", "内心覆盖", "近景定性")


def clamp_shot_duration_sec(
    value: Any,
    *,
    default: int = DEFAULT_SHOT_DURATION_SEC,
) -> int:
    numeric = _parse_duration_number(value)
    if numeric is None:
        numeric = float(default)
    rounded = int(round(numeric))
    return max(SHOT_DURATION_MIN_SEC, min(SHOT_DURATION_MAX_SEC, rounded))


def build_shot_plan_system_prompt(*, aspect_ratio: str | None = None) -> str:
    min_sec = SHOT_DURATION_MIN_SEC
    max_sec = SHOT_DURATION_MAX_SEC
    aspect = resolve_workshop_aspect_ratio(request=aspect_ratio)
    orientation = aspect_orientation_zh(aspect)
    return (
        "你是短剧分镜导演，只根据【这一集】已经写好的动作和对白，规划 MiniMax H3 可出片镜头列表。"
        "集数已由程序按「# 第N集」切好，禁止增删、合并或改集号。"
        f"每条镜头必须是 {min_sec}–{max_sec} 的整数秒；一条片子演不完动作或对白就拆成下一条，"
        f"短于 {min_sec} 秒的相邻节拍必须合并，不要留下不够起片的碎镜。"
        "剧本里已有的「### 镜头」只是素材（动作、对白、场景、人物），不是必须遵守的镜数。"
        f"能一镜拍完就只出一条；只有 {max_sec} 秒拍不下，或同一时间里调度互斥（例如必须换机位才能看清下一拍）时才加镜。"
        f"禁止用「{' / '.join(_FORBIDDEN_TEMPLATE_TERMS)}」这类关键词模板去拆镜；不要因为有开口、内心或推近就固定拆成三条。"
        "不发明剧情、人名、道具或台词。台词可以拆到不同镜，但必须从原文逐字截取，不得改写、概括或补词。"
        "每条镜头的 props 只列本镜实际使用、需要锁定或必须看见的道具；同场连续不等于继承上一镜全部桌面陈设。"
        "不要因为上一镜出现过电脑、台灯、笔记本等陈设，就把它们复制到下一镜；如果本镜只拍古籍下落，就只列古籍。"
        f"成片画幅以用户确认的 {aspect}（{orientation}）为权威。"
        "确认画幅为权威；剧本原文里的竖屏、横屏、方形、9:16、16:9 只是素材，禁止写进 title、camera、action、visual_prompt 来覆盖确认画幅。"
        f"新建镜头的 title 与 camera 按确认画幅 {aspect} 写，不要被原文竖屏/横屏或配方缺省带跑。"
        "先判切型再写动作。同场因果连续必须动作匹配切，下一镜开场继承上一镜落幅姿势；原文没写站起就保持坐。"
        "每条 action 必须以「开场：…」写开场站位（坐/站/走、朝向、手在哪），以「收束：…」写落幅。"
        "opening_state / closing_state / transition_note 用中文；禁止写 continuityIn / continuityOut。"
        "transition_note 只能是：动作匹配切 / 视线匹配切 / 方向匹配切 / 声音桥 / 硬切换场。"
        "\n\n"
        f"{load_shot_continuity_excerpt()}\n\n"
        f"{load_import_shot_continuity_excerpt()}\n\n"
        "只返回 JSON 对象，不要 markdown，不要解释。格式严格为："
        '{"shots":[{"title":"...","characters":["..."],"scene":"...","props":["..."],'
        '"action":"...","camera":"...","dialogue":"...","audio":"...","subtitle":"...",'
        '"visual_prompt":"...","opening_state":"...","closing_state":"...","transition_note":"动作匹配切",'
        '"duration_sec":8}]}'
        "shot_num 由程序重排，不要返回 episode_num。duration_sec 必须是整数。"
    )


def build_shot_plan_user_prompt(episode: dict[str, Any], *, aspect_ratio: str | None = None) -> str:
    episode_num = episode.get("episode_num")
    title = str(episode.get("title") or "").strip() or "未命名"
    summary = str(episode.get("summary") or "").strip() or "（无）"
    source = episode_source_text(episode)
    aspect = resolve_workshop_aspect_ratio(request=aspect_ratio)
    orientation = aspect_orientation_zh(aspect)
    source_shots = source_episode_shots(episode)
    parsed_shots = [
        _compact_source_shot(item)
        for item in source_shots
        if isinstance(item, dict)
    ]
    parsed_json = json.dumps(parsed_shots, ensure_ascii=False, indent=2)
    prop_scope_lines = []
    for index, shot in enumerate(source_shots, start=1):
        props = _as_name_list(shot.get("props")) if isinstance(shot, dict) else []
        prop_scope_lines.append(
            f"原镜头 {shot.get('shot_num') or index} 道具白名单：{', '.join(props) if props else '无（不要补写上一镜道具）'}"
        )
    prop_scope = "\n".join(prop_scope_lines) or "（无可用道具白名单；仍不得凭同场连续自动复制上一镜道具）"
    return (
        f"本集集号：{episode_num if episode_num is not None else '（未知）'}\n"
        f"本集标题：{title}\n"
        f"剧情摘要：{summary}\n\n"
        f"确认成片画幅：{aspect}（{orientation}）。这是权威值。"
        "原文中的竖屏/横屏/方形/9:16/16:9 只作剧情素材，不要覆盖确认画幅，也不要写进镜头卡的 title、camera、action、visual_prompt。\n\n"
        "本集原文（只读，按这里的动作和对白规划出片镜）：\n"
        f"{source or '（无正文）'}\n\n"
        "解析器已抽出的镜头字段（仅作素材，不是必须遵守的镜数）：\n"
        f"{parsed_json}\n\n"
        "道具范围合同（输出 props 只能是对应原镜头白名单的子集；合并镜头只保留当前动作确实需要的道具）：\n"
        f"{prop_scope}\n"
        "同一场景的连续镜头只继承人物姿势、视线、灯光和空间关系，不继承整组桌面陈设。"
        "如果动作不使用某件道具，不要在 props、action、visual_prompt 中把它写成主体；不要把纸质笔记本写成笔记本电脑。\n\n"
        f"请输出本集可出片 shots。单镜 {SHOT_DURATION_MIN_SEC}–{SHOT_DURATION_MAX_SEC} 整数秒。"
        "不要改集号，不要发明台词。"
        f"镜头卡画幅按确认的 {aspect} 写。"
        "相邻同场因果镜必须写 opening_state / closing_state / transition_note，并把开场姿势写进 action。"
    )


def episode_source_text(episode: dict[str, Any]) -> str:
    body = str(episode.get("body") or "").strip()
    if body:
        return body
    return render_episode_source_markdown(episode)


def render_episode_source_markdown(episode: dict[str, Any]) -> str:
    lines: list[str] = []
    number = episode.get("episode_num") or 1
    title = str(episode.get("title") or "").strip()
    header = f"# 第{number}集 {title}".rstrip()
    lines.append(header)
    summary = str(episode.get("summary") or "").strip()
    if summary:
        lines.append(f"剧情：{summary}")
    for index, shot in enumerate(episode.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            continue
        shot_num = shot.get("shot_num") or index
        shot_title = str(shot.get("title") or f"镜头 {shot_num}").strip()
        lines.append("")
        lines.append(f"### 镜头 {shot_num}｜{shot_title}")
        characters = _as_name_list(shot.get("characters"))
        if characters:
            lines.append(f"- 人物：{'、'.join(characters)}")
        scene = str(shot.get("scene") or "").strip()
        if scene:
            lines.append(f"- 场景：{scene}")
        props = _as_name_list(shot.get("props"))
        if props:
            lines.append(f"- 道具：{'、'.join(props)}")
        duration = shot.get("duration_sec")
        if duration not in (None, ""):
            lines.append(f"- 时长：{duration}秒")
        for label, key in (
            ("动作", "action"),
            ("运镜", "camera"),
            ("台词", "dialogue"),
            ("音效", "audio"),
            ("字幕", "subtitle"),
            ("提示词", "visual_prompt"),
            ("开场姿势", "opening_state"),
            ("落幅姿势", "closing_state"),
            ("切型", "transition_note"),
        ):
            value = str(shot.get(key) or "").strip()
            if value:
                lines.append(f"- {label}：{value}")
    return "\n".join(lines).strip()


def parse_shot_plan_response(raw: str) -> list[dict[str, Any]]:
    payload = _loads_json(raw)
    return _shots_from_payload(payload)


def normalize_planned_shots(planned: Any, *, aspect_ratio: Any = None) -> list[dict[str, Any]]:
    items = [_blank_shot(item) for item in _shots_from_payload(planned)]
    items = [item for item in items if _shot_has_content(item)]
    items = merge_short_adjacent_shots(items)
    confirmed = resolve_workshop_aspect_ratio(request=aspect_ratio) if aspect_ratio else None
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        shot = _blank_shot(item)
        shot["shot_num"] = index
        if not str(shot.get("title") or "").strip():
            shot["title"] = f"镜头 {index}"
        shot["duration_sec"] = clamp_shot_duration_sec(shot.get("duration_sec"))
        shot.pop("episode_num", None)
        if confirmed:
            shot = apply_confirmed_aspect_to_shot(shot, confirmed)
        shot = ensure_action_handoff_prose(shot)
        normalized.append(shot)
    return normalized


def source_episode_shots(episode: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return parser-owned shots from the original episode body when available.

    ``episode["shots"]`` is replaced by the last LLM plan, so it cannot be the
    authority for per-shot props on a forced re-plan. The original body remains
    the stable source and is parsed again here.
    """
    raw = episode if isinstance(episode, dict) else {}
    body = str(raw.get("body") or "").strip()
    if body:
        try:
            parsed = StandardScriptParser.parse(body)
            episodes = [item for item in (parsed.get("episodes") or []) if isinstance(item, dict)]
            target_num = raw.get("episode_num")
            target = next(
                (item for item in episodes if target_num is not None and item.get("episode_num") == target_num),
                None,
            )
            if target is None and len(episodes) == 1:
                target = episodes[0]
            parsed_shots = [item for item in (target or {}).get("shots") or [] if isinstance(item, dict)]
            if parsed_shots:
                return parsed_shots
        except Exception:
            pass
    return [item for item in (raw.get("shots") or []) if isinstance(item, dict)]


def constrain_planned_shot_props(
    planned: list[dict[str, Any]],
    source_shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep planned props within the matching parser-owned shot scope.

    The normalized planner output is re-numbered from one. For a re-plan with
    the same or fewer shots, sequence order is the only stable mapping that does
    not let LLM-invented prop names influence the match. Extra output shots have
    no parser-owned scope and therefore receive no named props.
    """
    if not planned or not source_shots:
        return planned
    if not any(_as_name_list(item.get("props")) for item in source_shots if isinstance(item, dict)):
        return planned
    constrained: list[dict[str, Any]] = []
    for index, shot in enumerate(planned):
        current = dict(shot)
        if index >= len(source_shots):
            current["props"] = []
            constrained.append(current)
            continue
        source_index = index
        allowed = {
            _prop_key(name)
            for name in _as_name_list((source_shots[source_index] or {}).get("props"))
            if _prop_key(name)
        }
        if allowed:
            current["props"] = [
                name for name in _as_name_list(current.get("props"))
                if _prop_key(name) in allowed
            ]
        else:
            current["props"] = []
        constrained.append(current)
    return constrained


def merge_short_adjacent_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return []
    merged: list[dict[str, Any]] = [dict(shots[0])]
    for item in shots[1:]:
        current = dict(item)
        previous = merged[-1]
        prev_duration = _parse_duration_number(previous.get("duration_sec"))
        current_duration = _parse_duration_number(current.get("duration_sec"))
        if (
            prev_duration is not None
            and current_duration is not None
            and prev_duration < SHOT_DURATION_MIN_SEC
            and current_duration < SHOT_DURATION_MIN_SEC
            and (prev_duration + current_duration) <= SHOT_DURATION_MAX_SEC
        ):
            merged[-1] = _combine_shots(previous, current)
            continue
        merged.append(current)
    if len(merged) >= 2:
        last_duration = _parse_duration_number(merged[-1].get("duration_sec"))
        prev_duration = _parse_duration_number(merged[-2].get("duration_sec"))
        if (
            last_duration is not None
            and last_duration < SHOT_DURATION_MIN_SEC
            and prev_duration is not None
            and (prev_duration + last_duration) <= SHOT_DURATION_MAX_SEC
        ):
            merged[-2] = _combine_shots(merged[-2], merged[-1])
            merged.pop()
    return merged


def is_ai_pipeline_document(input_mode: Any) -> bool:
    return str(input_mode or "").strip().lower() == AI_PIPELINE_INPUT_MODE


def needs_episode_shot_plan(episode: Any, *, input_mode: Any = "", force: bool = False) -> bool:
    if is_ai_pipeline_document(input_mode):
        return False
    if not isinstance(episode, dict):
        return False
    if force:
        return True
    return str(episode.get("shots_source") or "").strip().lower() != SHOTS_SOURCE_LLM


def shot_plan_episode_indexes(
    analysis: Any,
    *,
    input_mode: Any = "",
    force: bool = False,
    episode_num: int | None = None,
) -> list[int]:
    if is_ai_pipeline_document(input_mode) or not isinstance(analysis, dict):
        return []
    indexes: list[int] = []
    for index, episode in enumerate(analysis.get("episodes") or []):
        if not isinstance(episode, dict):
            continue
        if episode_num is not None and episode.get("episode_num") != episode_num:
            continue
        if needs_episode_shot_plan(episode, input_mode=input_mode, force=force):
            indexes.append(index)
    return indexes


def document_needs_shot_plan(analysis: Any, *, input_mode: Any = "") -> bool:
    return bool(shot_plan_episode_indexes(analysis, input_mode=input_mode))


def apply_episode_shot_plan(episode: dict[str, Any], planned: Any, *, aspect_ratio: Any = None) -> dict[str, Any]:
    """用规划结果覆盖本集 shots；空结果回退解析器镜头，且不改 episode_num。"""
    result = copy.deepcopy(episode) if isinstance(episode, dict) else {}
    episode_num = episode.get("episode_num") if isinstance(episode, dict) else None
    shots = normalize_planned_shots(planned, aspect_ratio=aspect_ratio)
    shots = constrain_planned_shot_props(shots, source_episode_shots(episode))
    if not shots:
        result["episode_num"] = episode_num
        return result
    result["shots"] = shots
    result["shots_count"] = len(shots)
    result["shots_source"] = SHOTS_SOURCE_LLM
    result["episode_num"] = episode_num
    return result


def ensure_action_handoff_prose(shot: dict[str, Any]) -> dict[str, Any]:
    """把开场/落幅姿势写进 action 正文，避免下游只读画面栏时丢掉衔接。"""
    updated = dict(shot)
    opening = str(updated.get("opening_state") or "").strip()
    closing = str(updated.get("closing_state") or "").strip()
    action = str(updated.get("action") or "").strip()
    if opening and not _has_handoff_marker(action, "开场"):
        action = f"开场：{opening}。{action}".strip()
    if closing and not _has_handoff_marker(action, "收束"):
        action = f"{action} 收束：{closing}。".strip()
    updated["action"] = action
    return updated


def overlapping_shot_windows(
    shots: list[dict[str, Any]],
    *,
    size: int = CONTINUITY_WINDOW_SIZE,
    overlap: int = CONTINUITY_WINDOW_OVERLAP,
) -> list[dict[str, Any]]:
    if len(shots) < CONTINUITY_REFINE_MIN_SHOTS:
        return []
    size = max(2, int(size))
    overlap = max(1, min(int(overlap), size - 1))
    windows: list[dict[str, Any]] = []
    start = 0
    while start < len(shots):
        end = min(len(shots), start + size)
        context_count = 0 if start == 0 else overlap
        context = shots[start:start + context_count]
        editable = shots[start + context_count:end]
        if not editable:
            break
        windows.append({
            "shots": context + editable,
            "context_shot_nums": [_shot_num(item) for item in context],
            "editable_shot_nums": [_shot_num(item) for item in editable],
        })
        if end >= len(shots):
            break
        start = end - overlap
    return windows


def build_shot_continuity_refine_system_prompt(*, aspect_ratio: str | None = None) -> str:
    aspect = resolve_workshop_aspect_ratio(request=aspect_ratio)
    orientation = aspect_orientation_zh(aspect)
    return (
        "你是短剧镜头衔接修订。输入是按镜号排列的一小段已规划出片镜。"
        "context_shot_nums 只读，用来看上一镜落幅；只改 editable_shot_nums 里的 "
        "action、visual_prompt、opening_state、closing_state、transition_note。"
        "禁止改对白、台词原文、duration_sec、shot_num、title、characters、scene、props、camera、集号。"
        "同场因果连续时，下一镜 opening_state 必须继承上一镜 closing_state 的姿势、左右、持物、灯光；"
        "原文没写站起就禁止写成站姿。"
        "action 必须以「开场：…」写开场姿势，以「收束：…」写落幅。"
        "transition_note 只能是：动作匹配切 / 视线匹配切 / 方向匹配切 / 声音桥 / 硬切换场。"
        "不要发明桥接剧情。不要写 continuityIn / continuityOut。"
        f"画幅仍以确认的 {aspect}（{orientation}）为权威。"
        "\n\n"
        f"{load_import_shot_continuity_excerpt()}\n\n"
        "只返回 JSON 对象，不要 markdown。格式："
        '{"shots":[{"shot_num":1,"action":"...","visual_prompt":"...",'
        '"opening_state":"...","closing_state":"...","transition_note":"动作匹配切"}]}'
    )


def build_shot_continuity_refine_user_prompt(window: dict[str, Any]) -> str:
    shots = [
        _compact_continuity_shot(item)
        for item in (window.get("shots") or [])
        if isinstance(item, dict)
    ]
    return (
        f"只读镜号：{window.get('context_shot_nums') or []}\n"
        f"可修订镜号：{window.get('editable_shot_nums') or []}\n"
        "只修订可编辑镜的衔接字段与 action / visual_prompt，不要重拆剧情。\n\n"
        f"{json.dumps(shots, ensure_ascii=False, indent=2)}"
    )


def apply_continuity_window_revision(
    shots: list[dict[str, Any]],
    revised: Any,
    *,
    editable_shot_nums: set[int],
) -> list[dict[str, Any]]:
    patches: dict[int, dict[str, Any]] = {}
    for item in _shots_from_payload(revised):
        number = _shot_num(item)
        if number in editable_shot_nums:
            patches[number] = item
    updated: list[dict[str, Any]] = []
    for shot in shots:
        number = _shot_num(shot)
        patch = patches.get(number)
        if not patch:
            updated.append(shot)
            continue
        merged = dict(shot)
        for key in CONTINUITY_EDITABLE_FIELDS:
            value = str(patch.get(key) or "").strip()
            if value:
                merged[key] = value
        updated.append(ensure_action_handoff_prose(_blank_shot(merged)))
    return updated


def _has_handoff_marker(action: str, marker: str) -> bool:
    text = str(action or "")
    return f"{marker}：" in text or f"{marker}:" in text


def _shot_num(shot: dict[str, Any]) -> int:
    try:
        return int(shot.get("shot_num") or 0)
    except (TypeError, ValueError):
        return 0


def _compact_continuity_shot(shot: dict[str, Any]) -> dict[str, Any]:
    compact = _blank_shot(shot)
    compact["shot_num"] = _shot_num(compact) or compact.get("shot_num") or 0
    if compact["duration_sec"] is None:
        compact.pop("duration_sec", None)
    if not compact["raw_content"]:
        compact.pop("raw_content", None)
    return compact


def _blank_shot(item: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = item if isinstance(item, dict) else {}
    shot: dict[str, Any] = {
        "shot_num": raw.get("shot_num") or 0,
        "title": str(raw.get("title") or "").strip(),
        "characters": _as_name_list(raw.get("characters")),
        "scene": str(raw.get("scene") or "").strip(),
        "props": _as_name_list(raw.get("props")),
        "action": str(raw.get("action") or "").strip(),
        "camera": str(raw.get("camera") or "").strip(),
        "dialogue": str(raw.get("dialogue") or "").strip(),
        "visual_prompt": str(raw.get("visual_prompt") or "").strip(),
        "audio": str(raw.get("audio") or "").strip(),
        "subtitle": str(raw.get("subtitle") or "").strip(),
        "duration_sec": _first_duration_value(raw),
        "raw_content": str(raw.get("raw_content") or "").strip(),
        "opening_state": str(raw.get("opening_state") or "").strip(),
        "closing_state": str(raw.get("closing_state") or "").strip(),
        "transition_note": str(
            raw.get("transition_note") or raw.get("transitionNote") or ""
        ).strip(),
    }
    return shot


def _shot_has_content(shot: dict[str, Any]) -> bool:
    if any(str(shot.get(key) or "").strip() for key in SHOT_TEXT_FIELDS):
        return True
    return any(shot.get(key) for key in SHOT_LIST_FIELDS)


def _combine_shots(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    combined = _blank_shot(left)
    right_shot = _blank_shot(right)
    if not combined["title"]:
        combined["title"] = right_shot["title"]
    combined["characters"] = _unique_join(combined["characters"], right_shot["characters"])
    if not combined["scene"]:
        combined["scene"] = right_shot["scene"]
    combined["props"] = _unique_join(combined["props"], right_shot["props"])
    for key in ("action", "camera", "dialogue", "visual_prompt", "audio", "subtitle", "raw_content"):
        combined[key] = _join_text(combined.get(key), right_shot.get(key))
    if not combined["opening_state"]:
        combined["opening_state"] = right_shot["opening_state"]
    combined["closing_state"] = right_shot["closing_state"] or combined["closing_state"]
    if not combined["transition_note"]:
        combined["transition_note"] = right_shot["transition_note"]
    left_duration = _parse_duration_number(left.get("duration_sec")) or 0.0
    right_duration = _parse_duration_number(right.get("duration_sec")) or 0.0
    combined["duration_sec"] = left_duration + right_duration
    return ensure_action_handoff_prose(combined)


def _join_text(left: Any, right: Any) -> str:
    first = str(left or "").strip()
    second = str(right or "").strip()
    if not first:
        return second
    if not second:
        return first
    if second in first:
        return first
    if first in second:
        return second
    return f"{first} {second}".strip()


def _unique_join(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for item in group:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            result.append(token)
    return result


def _as_name_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[、,，/|]+", value)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token:
                result.append(token)
        return result
    return []


def _prop_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _first_duration_value(item: dict[str, Any]) -> Any:
    for key in _DURATION_KEYS:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _parse_duration_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric != numeric or numeric in {float("inf"), float("-inf")}:
            return None
        return numeric
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    if not match:
        return None
    return float(match.group(1))


def _compact_source_shot(shot: dict[str, Any]) -> dict[str, Any]:
    compact = _blank_shot(shot)
    if compact["duration_sec"] is None:
        compact.pop("duration_sec", None)
    if not compact["raw_content"]:
        compact.pop("raw_content", None)
    return compact


def _shots_from_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("shots", "takes", "items"):
        items = value.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    nested = value.get("data")
    if nested is not None and nested is not value:
        return _shots_from_payload(nested)
    if _shot_has_content(_blank_shot(value)) or _first_duration_value(value) is not None:
        return [value]
    return []


def _loads_json(raw: str) -> Any | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```.*$", "", text, flags=re.S)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None
