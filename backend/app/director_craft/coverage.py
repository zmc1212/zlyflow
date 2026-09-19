from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


COVERAGE_CONTRACT_EXCERPT = """【覆盖合同】
- 动作必须写「画面停在谁身上」：腰 / 脸 / 胸腰 / 近景哪一个铺满竖屏，不要只写谁在看谁。
- 运镜只用短句：上摇、下摇、推近、固定。不要把「顺着视线」写成运镜。
- 开口时画面停在说话人；内心时钉被看的人的胸腰并闭嘴，不要同时推脸。
- 人已在室内就写已站定，不要写开门。"""

TAKE_ROLE_LABELS = {
    "lipsync": "口型",
    "inner_hold": "内心覆盖",
    "push_close": "近景定性",
}

H3_AMPLITUDE = "with small amplitude at slow speed"

CLAUSE_TILT_UP = (
    f"The camera tilts up {H3_AMPLITUDE} from a waist-level medium "
    "to a medium close-up of the face and holds a static shot."
)
CLAUSE_INNER_HOLD = (
    f"The camera tilts down {H3_AMPLITUDE} "
    "and holds a static shot on the chest-and-waist so the clothes fill the vertical frame; "
    "do not push in until this inner voice ends."
)
CLAUSE_PUSH_IN = (
    f"The camera pushes in {H3_AMPLITUDE} to a medium-close of {{who}} and holds a static shot."
)
CLAUSE_ALREADY_INSIDE = (
    "Already inside the closed cabin. Everyone is already standing in place. "
    "Doors stay shut. Do not show the doors opening."
)
CLAUSE_START_WAIST = "Start on a waist-level medium so the torso fills the lower frame."
CLAUSE_STATIC_HOLD = "The camera holds a static shot."

_TILT_UP_RE = re.compile(r"上摇|摇到脸|从腰.{0,16}脸|tilt(?:s|ing)?\s+up", re.I)
_PIN_RE = re.compile(
    r"钉胸腰|胸腰|下摇|衣服铺满|钉在|"
    r"tilt(?:s|ing)?\s+down|torso|chest-and-waist|camisole|mini skirt|clothes fill",
    re.I,
)
_PUSH_RE = re.compile(r"推近|再推|推到|近景定性|push(?:es)?\s+in", re.I)
_WAIST_RE = re.compile(r"从腰|腰部|先给腰|waist-level|starts at the waist", re.I)
_INSIDE_RE = re.compile(
    r"已在|已站定|不要开门|门保持关|轿厢内|already inside|doors stay shut",
    re.I,
)
_ELEVATOR_RE = re.compile(r"轿厢|电梯|elevator", re.I)
_GAZE_RE = re.compile(
    r"follows\s+(?:his|her|the)\s+(?:gaze|look)|eyes travel down|gaze tilting|顺着.{0,8}视线",
    re.I,
)
_NAME_EN = {
    "吴耐": "Wu Nai",
    "沙丽丽": "Sha Lili",
}


@dataclass
class CameraMove:
    kind: str
    clause: str


@dataclass
class CoveragePlan:
    blocking: list[str] = field(default_factory=list)
    moves: list[CameraMove] = field(default_factory=list)
    already_inside: bool = False
    start_at_waist: bool = False
    coverage_subject: str = ""
    push_subject: str = ""


@dataclass
class ProductionTakePlan:
    role: str
    label: str
    dialogue: str
    action: str
    camera: str
    speaker: str


def load_coverage_contract_excerpt() -> str:
    return COVERAGE_CONTRACT_EXCERPT


def english_who(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return "the speaker"
    return _NAME_EN.get(text, text)


def compile_coverage_plan(
    shot: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
) -> CoveragePlan:
    events = [item for item in (events or []) if str(item.get("text") or "").strip()]
    blob = _source_blob(shot)
    spoken = [item for item in events if item.get("kind") != "inner"]
    inner = [item for item in events if item.get("kind") == "inner"]
    take_role = str(shot.get("take_role") or "").strip()
    already_inside = bool(_INSIDE_RE.search(blob))
    start_at_waist = bool(_WAIST_RE.search(blob))
    in_elevator = bool(_ELEVATOR_RE.search(blob))
    has_tilt_up = bool(_TILT_UP_RE.search(blob))
    has_pin = bool(_PIN_RE.search(blob))
    has_push = bool(_PUSH_RE.search(blob))
    coverage_subject = _coverage_subject(shot, events)
    push_who = english_who(str((spoken[-1] or {}).get("speaker") or "") if spoken else "")
    if take_role == "push_close" and spoken:
        push_who = english_who(str(spoken[-1].get("speaker") or ""))
    elif take_role == "push_close":
        push_who = english_who(_first_character_name(shot))

    moves: list[CameraMove] = []
    if take_role == "lipsync":
        moves.append(CameraMove("tilt_up", CLAUSE_TILT_UP))
    elif take_role == "inner_hold":
        moves.append(CameraMove("inner_hold", CLAUSE_INNER_HOLD))
    elif take_role == "push_close":
        moves.append(CameraMove("push_in", CLAUSE_PUSH_IN.format(who=push_who)))
    else:
        if spoken and (has_tilt_up or start_at_waist or inner):
            moves.append(CameraMove("tilt_up", CLAUSE_TILT_UP))
        if inner:
            moves.append(CameraMove("inner_hold", CLAUSE_INNER_HOLD))
        if spoken and (has_push or (inner and has_pin)):
            moves.append(CameraMove("push_in", CLAUSE_PUSH_IN.format(who=push_who)))
        if not moves and spoken:
            moves.append(CameraMove("hold", CLAUSE_STATIC_HOLD))

    blocking: list[str] = []
    if already_inside:
        blocking.append(CLAUSE_ALREADY_INSIDE)
        if in_elevator:
            blocking.append("The setting is the closed stainless-steel elevator cabin.")
    if start_at_waist:
        blocking.append(CLAUSE_START_WAIST)

    return CoveragePlan(
        blocking=blocking,
        moves=moves,
        already_inside=already_inside,
        start_at_waist=start_at_waist,
        coverage_subject=coverage_subject,
        push_subject=push_who,
    )


def extra_control_moves(shot: dict[str, Any], events: list[dict[str, Any]] | None = None) -> bool:
    """True when action/camera/visual_prompt ask for a pin or a second push besides lip-sync."""
    blob = _source_blob(shot)
    if _PIN_RE.search(blob) or _PUSH_RE.search(blob):
        return True
    if _GAZE_RE.search(blob) and (events or []):
        return True
    return False


def coverage_enforced(shot: dict[str, Any]) -> bool:
    role = str(shot.get("take_role") or "").strip()
    if role in TAKE_ROLE_LABELS:
        return True
    blob = _source_blob(shot)
    return bool(
        _PIN_RE.search(blob)
        or _TILT_UP_RE.search(blob)
        or _PUSH_RE.search(blob)
        or _INSIDE_RE.search(blob)
    )


def fidelity_conflict(shot: dict[str, Any], events: list[dict[str, Any]] | None = None) -> bool:
    events = [item for item in (events or []) if str(item.get("text") or "").strip()]
    spoken = [item for item in events if item.get("kind") != "inner"]
    inner = [item for item in events if item.get("kind") == "inner"]
    if not spoken or not inner:
        return False
    return extra_control_moves(shot, events)


def plan_production_takes(
    shot: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
) -> list[ProductionTakePlan]:
    events = [item for item in (events or []) if str(item.get("text") or "").strip()]
    if not fidelity_conflict(shot, events):
        return []
    spoken = [item for item in events if item.get("kind") != "inner"]
    inner = [item for item in events if item.get("kind") == "inner"]
    first_inner = next((index for index, item in enumerate(events) if item.get("kind") == "inner"), -1)
    before = [item for index, item in enumerate(events) if index < first_inner and item.get("kind") != "inner"]
    after = [item for index, item in enumerate(events) if index > first_inner and item.get("kind") != "inner"]
    coverage = _coverage_subject(shot, events) or "被看的人"
    already = "轿厢内已站定，不要开门。" if _INSIDE_RE.search(_source_blob(shot)) else ""
    takes: list[ProductionTakePlan] = []
    if before:
        speaker = str(before[0].get("speaker") or "").strip()
        takes.append(ProductionTakePlan(
            role="lipsync",
            label=TAKE_ROLE_LABELS["lipsync"],
            dialogue=_format_events(before),
            action=_join_zh(
                already,
                f"画面停在{speaker or '说话人'}腰部，上摇到脸，口型同步。",
            ),
            camera="上摇，固定口型",
            speaker=speaker,
        ))
    if inner:
        speaker = str(inner[0].get("speaker") or "").strip()
        takes.append(ProductionTakePlan(
            role="inner_hold",
            label=TAKE_ROLE_LABELS["inner_hold"],
            dialogue=_format_events(inner),
            action=_join_zh(
                already,
                f"画面停在{coverage}胸腰，衣服铺满竖屏，固定机位，所有可见人物闭嘴。",
            ),
            camera="钉胸腰，固定",
            speaker=speaker,
        ))
    if after:
        speaker = str(after[0].get("speaker") or "").strip()
        takes.append(ProductionTakePlan(
            role="push_close",
            label=TAKE_ROLE_LABELS["push_close"],
            dialogue=_format_events(after),
            action=_join_zh(
                already,
                f"画面停在{speaker or '说话人'}近景，推近到中近景定性。",
            ),
            camera="推近",
            speaker=speaker,
        ))
    return takes if len(takes) >= 2 else []


def is_literary_gaze(clause: str) -> bool:
    return bool(_GAZE_RE.search(str(clause or "")))


def is_inner_pin_beat(clause: str) -> bool:
    text = str(clause or "")
    if is_literary_gaze(text):
        return False
    return bool(re.search(
        r"tilt(?:s|ing)?\s+down|chest-and-waist|clothes fill|torso|"
        r"static shot on (?:that |the )?(?:torso|chest)",
        text,
        re.I,
    ))


def is_tilt_up_beat(clause: str) -> bool:
    return bool(re.search(r"tilt(?:s|ing)?\s+up", str(clause or ""), re.I))


def is_push_in_beat(clause: str) -> bool:
    text = str(clause or "")
    if re.search(r"push(?:es)?\s+back", text, re.I):
        return False
    cleaned = re.sub(r"do not push(?:es)? in\b[^.]*", "", text, flags=re.I)
    return bool(re.search(r"push(?:es)?\s+in", cleaned, re.I))


def is_door_open_clause(clause: str) -> bool:
    text = str(clause or "").lower()
    if "stay shut" in text or "stay closed" in text or "do not show the doors opening" in text:
        return False
    return bool(re.search(r"doors? (just )?shut|doors? open|elevator doors", text, re.I))


_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_D_TAG_RE = re.compile(r"<d>\[Chinese\]\s*(.*?)</d>", re.S)
_INNER_CLOSED_RE = re.compile(
    r"off-screen|voice[\s-]?over|thinks|closed lips|lips closed|lips remain|mouths? stay",
    re.I,
)
_INNER_SAYS_RE = re.compile(r"\bsays\b|lip[\s-]?sync", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def coverage_prompt_errors(
    prompt: str,
    shot: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Deterministic coverage / landing checks. No LLM review."""
    text = str(prompt or "")
    events = [item for item in (events or []) if str(item.get("text") or "").strip()]
    plan = compile_coverage_plan(shot, events)
    errors: list[str] = []
    windows = _speech_windows(text, events)
    for event, window in windows:
        if event.get("kind") != "inner":
            continue
        if _INNER_SAYS_RE.search(window) and not _INNER_CLOSED_RE.search(window):
            errors.append("inner voice must keep visible mouths closed")
    if plan.already_inside:
        for sentence in _SENTENCE_RE.split(text) or [text]:
            if is_door_open_clause(sentence):
                errors.append("already-inside take must not show doors opening")
                break
    if not coverage_enforced(shot):
        return errors
    if is_literary_gaze(text):
        errors.append("literary gaze leftover: follows his gaze")
    if str(shot.get("timestamped_zh_prompt") or "").strip() or shot.get("faithful_zh_pack"):
        # 中文分秒稿是调度权威：不按「一句一落地」窗口要求 tilt-up / inner-hold / push-in。
        return errors
    kinds = {item.kind for item in plan.moves}
    for event, window in windows:
        if event.get("kind") == "inner" and "inner_hold" in kinds and not is_inner_pin_beat(window):
            errors.append("coverage subject missing from inner segment")
    spoken_windows = [window for event, window in windows if event.get("kind") != "inner"]
    if "tilt_up" in kinds and spoken_windows and not is_tilt_up_beat(spoken_windows[0]):
        errors.append("camera landing missing tilt up on first spoken beat")
    if "push_in" in kinds and spoken_windows and not is_push_in_beat(spoken_windows[-1]):
        errors.append("camera landing missing push-in on last spoken beat")
    return errors


def _speech_windows(prompt: str, events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    tags = list(_D_TAG_RE.finditer(str(prompt or "")))
    used: set[int] = set()
    windows: list[tuple[dict[str, Any], str]] = []
    for event in events:
        needle = "".join(_HAN_RE.findall(str(event.get("text") or "")))
        if not needle:
            continue
        match = None
        for index, tag in enumerate(tags):
            if index in used:
                continue
            body = "".join(_HAN_RE.findall(tag.group(1)))
            if needle == body or (len(needle) >= 6 and (needle in body or body in needle)):
                match = tag
                used.add(index)
                break
        if match is None:
            continue
        start = max(0, match.start() - 280)
        windows.append((event, str(prompt or "")[start:match.end() + 90]))
    return windows


def _source_blob(shot: dict[str, Any]) -> str:
    return " ".join(
        str(shot.get(key) or "")
        for key in ("action", "camera", "video_prompt_zh", "visual_prompt", "scene", "scene_name")
    )


def _first_character_name(shot: dict[str, Any]) -> str:
    for item in shot.get("character_references") or []:
        if isinstance(item, dict) and str(item.get("character_name") or "").strip():
            return str(item.get("character_name") or "").strip()
    for item in shot.get("characters") or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            return str(item.get("name") or "").strip()
        if str(item or "").strip():
            return str(item).strip()
    return ""


def _character_names(shot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in shot.get("character_references") or []:
        if isinstance(item, dict):
            name = str(item.get("character_name") or "").strip()
            if name and name not in names:
                names.append(name)
    for item in shot.get("characters") or []:
        name = str(item.get("name") if isinstance(item, dict) else item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _coverage_subject(shot: dict[str, Any], events: list[dict[str, Any]]) -> str:
    blob = str(shot.get("action") or "") + " " + str(shot.get("camera") or "")
    names = _character_names(shot)
    match = re.search(r"画面停在([^，。；\s]{1,12})|钉在([^，。；\s]{1,12})", blob)
    if match:
        return (match.group(1) or match.group(2) or "").strip()
    thinker = ""
    for item in events:
        if item.get("kind") == "inner":
            thinker = str(item.get("speaker") or "").strip()
            break
    others = [name for name in names if name and name != thinker]
    if others:
        return others[0]
    if names:
        return names[-1] if thinker and names[-1] != thinker else names[0]
    return "被看的人"


def _format_events(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in events:
        speaker = str(item.get("speaker") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if item.get("kind") == "inner":
            label = f"{speaker}（内心）" if speaker else "旁白"
            parts.append(f"{label}：“{text}”")
        elif speaker:
            parts.append(f"{speaker}：“{text}”")
        else:
            parts.append(f"“{text}”")
    return " ".join(parts)


def _join_zh(*parts: str) -> str:
    return "".join(str(item).strip() for item in parts if str(item or "").strip())
