"""Streaming support for director operations.

Two pieces:

- :class:`AgentStreamTracker` turns the *accumulated* raw text that the LLM
  client's ``on_chunk`` callback reports into display events for an agent's
  JSON reply: scalar-field deltas (``agent_delta``) and completed array items
  (``agent_item``).  The upstream callback may fire mid-JSON, inside ```
  fences or while a ``<think>`` block is still open, so extraction is
  intentionally tolerant: it only ever looks for the spec's known keys and
  decodes partial JSON string escapes.  Multi-call agents (storyboard) call
  :meth:`AgentStreamTracker.begin_call` between LLM calls; item indices stay
  continuous across calls.
- :class:`DirectorOperationEventBus` fans operation events out to SSE
  subscribers.  Events are buffered per operation so a client that reconnects
  with ``?since=<seq>`` can replay what it missed.  Emitters run partly on
  worker threads (the LLM pipeline lives in ``asyncio.to_thread``), so
  ``emit`` schedules publication onto the service loop.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}

TERMINAL_OPERATION_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}

MAX_FINISH_ITEMS = 200


def _field_pattern(name: str) -> re.Pattern[str]:
    return re.compile(r'"' + re.escape(name) + r'"\s*:\s*"')


def _strip_closed_think_blocks(text: str) -> str:
    while "<think>" in text and "</think>" in text:
        text = text.split("<think>", 1)[0] + text.split("</think>", 1)[1]
    return text


def _json_scan_start(text: str) -> int:
    """Index the JSON object is expected to start at (skips fences/thinking)."""
    probe = text
    if "```json" in probe:
        probe = probe.split("```json", 1)[1]
    elif "```" in probe:
        probe = probe.split("```", 1)[1]
    brace = probe.find("{")
    return -1 if brace < 0 else brace


def _repair_truncated_json(snippet: str) -> str:
    in_string = False
    escape = False
    stack: list[str] = []
    for character in snippet:
        if in_string:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            continue
        if character == "{":
            stack.append("}")
        elif character == "[":
            stack.append("]")
        elif character in "}]":
            if stack and stack[-1] == character:
                stack.pop()
    repaired = snippet.rstrip()
    if in_string:
        repaired += '"'
    repaired = repaired.rstrip().rstrip(",")
    while stack:
        repaired += stack.pop()
    return repaired


def _decode_partial_string(text: str, start: int) -> tuple[str, bool]:
    """Decode the JSON string starting just after its opening quote.

    Returns ``(decoded, completed)``.  Stops at the first unescaped ``"``;
    when the text ends first, the string is still streaming and a trailing
    incomplete escape is held back until the next flush completes it.
    """
    out: list[str] = []
    index = start
    end = len(text)
    while index < end:
        char = text[index]
        if char == '"':
            return "".join(out), True
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= end:
            break  # escape sequence split across chunks
        escaped = text[index + 1]
        if escaped == "u":
            if index + 6 > end:
                break  # \uXXXX split across chunks
            try:
                out.append(chr(int(text[index + 2 : index + 6], 16)))
            except ValueError:
                out.append(text[index : index + 6])
            index += 6
            continue
        out.append(_SIMPLE_ESCAPES.get(escaped, escaped))
        index += 2
    return "".join(out), False


@dataclass(frozen=True)
class AgentArraySpec:
    """An array field whose items are streamed as cards/rows."""

    key: str
    display_fields: tuple[str, ...]
    # Extract the item list from the final parsed payload (defaults to top
    # level ``data[key]``); used for nested shapes such as storyboard shots.
    extractor: Callable[[dict[str, Any]], list[Any]] | None = None


@dataclass(frozen=True)
class AgentStreamSpec:
    agent_id: str
    scalar_fields: tuple[str, ...] = ()
    arrays: tuple[AgentArraySpec, ...] = ()


def _flatten_storyboard_shots(data: dict[str, Any]) -> list[Any]:
    shots: list[Any] = []
    for scene in data.get("scenes") or []:
        if isinstance(scene, dict):
            shots.extend(item for item in scene.get("shots") or [] if isinstance(item, dict))
    return shots


AGENT_STREAM_SPECS: dict[str, AgentStreamSpec] = {
    "script": AgentStreamSpec("script", scalar_fields=("title", "summary", "fullStory")),
    "research": AgentStreamSpec("research", scalar_fields=("notes",)),
    "music": AgentStreamSpec("music", scalar_fields=("globalMusic", "globalSoundscape")),
    "characters": AgentStreamSpec("characters", arrays=(
        AgentArraySpec("characters", ("name", "role", "description")),
        AgentArraySpec("props", ("name", "description")),
    )),
    "locations": AgentStreamSpec("locations", arrays=(AgentArraySpec("locations", ("name", "description")),)),
    "voice": AgentStreamSpec("voice", arrays=(AgentArraySpec("characters", ("name", "voiceId")),)),
    "storyboard": AgentStreamSpec("storyboard", arrays=(
        AgentArraySpec("scenes", ("title",)),
        AgentArraySpec("shots", ("title", "description", "dialogue"), extractor=_flatten_storyboard_shots),
    )),
    # 分镜打磨（按秒分配/校验衔接）的独立直播命名空间：每个分块用全新 tracker，
    # 索引从 0 重来，前端只作瞬时直播字幕渲染，不落到 storyboard 的 items 里。
    "storyboard_polish": AgentStreamSpec("storyboard_polish", arrays=(
        AgentArraySpec("shots", ("description", "dialogue")),
    )),
    "clarify": AgentStreamSpec("clarify", arrays=(AgentArraySpec("questions", ("question", "why")),)),
}

_SHOT_NUMBER_PATTERN = re.compile(r'"shotNumber"\s*:\s*(\d+)')


def scan_current_shot_number(text: str) -> int | None:
    """Latest ``"shotNumber": N`` in an accumulated LLM stream, or None.

    Skips fenced code markers and closed ``<think>`` blocks so a model that
    reasons about shot numbers out loud does not skew the result; an open
    think block means the JSON has not started yet.
    """
    if not text:
        return None
    if "<think>" in text and "</think>" not in text:
        return None
    probe = _strip_closed_think_blocks(text)
    if "```json" in probe:
        probe = probe.split("```json", 1)[1]
    elif "```" in probe:
        probe = probe.split("```", 1)[1]
    last = None
    for match in _SHOT_NUMBER_PATTERN.finditer(probe):
        last = int(match.group(1))
    return last


def _array_starts(text: str, key: str) -> list[int]:
    return [match.end() - 1 for match in re.finditer(r'"' + re.escape(key) + r'"\s*:\s*\[', text)]


def _iter_array_objects(text: str, bracket: int) -> list[tuple[int, int | None]]:
    """Top-level ``{...}`` objects of the array starting at ``bracket``.

    Returns ``(start, end)`` pairs; the last entry has ``end=None`` when the
    text stops inside the object (still streaming).
    """
    index = bracket + 1
    objects: list[tuple[int, int | None]] = []
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n,":
            index += 1
        if index >= length or text[index] != "{":
            break
        depth = 0
        in_string = False
        escape = False
        end: int | None = None
        cursor = index
        while cursor < length:
            char = text[cursor]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = cursor
                    break
            cursor += 1
        objects.append((index, end))
        if end is None:
            break
        index = end + 1
    return objects


class AgentStreamTracker:
    """Emit per-agent display events from the accumulated raw LLM stream."""

    def __init__(self, spec: AgentStreamSpec, emit: Callable[[dict[str, Any]], None]) -> None:
        self._spec = spec
        self._emit = emit
        self._scalars: dict[str, str] = {name: "" for name in spec.scalar_fields}
        self._bases = {array.key: 0 for array in spec.arrays}
        self._counts = {array.key: 0 for array in spec.arrays}
        # (array_key, display_field) -> (global item ordinal, decoded value)
        self._active: dict[tuple[str, str], tuple[int, str]] = {}
        self._done = False

    # -- public API -------------------------------------------------------

    def begin_call(self) -> None:
        """Fold finished calls into the bases and reset per-call scan state."""
        for key in self._bases:
            self._bases[key] += self._counts[key]
            self._counts[key] = 0
        self._scalars = {name: "" for name in self._spec.scalar_fields}
        self._active.clear()
        self._done = False

    def feed(self, accumulated: str) -> None:
        if self._done or not accumulated:
            return
        if "<think>" in accumulated and "</think>" not in accumulated:
            return  # model still thinking; JSON has not started yet
        text = _strip_closed_think_blocks(accumulated)
        self._feed_scalars(text)
        self._feed_arrays(text)

    def finish(self, final: dict[str, Any] | None) -> None:
        """Push authoritative parsed values once the agent reply is complete."""
        self._done = True
        if not isinstance(final, dict):
            return
        for name in self._spec.scalar_fields:
            value = str(final.get(name) or "").strip()
            if value and value != self._scalars.get(name):
                self._scalars[name] = value
                self._emit_delta(name, None, value, True)
        for array in self._spec.arrays:
            items = array.extractor(final) if array.extractor is not None else final.get(array.key)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items[:MAX_FINISH_ITEMS]):
                if isinstance(item, dict) and item:
                    self._emit_item(array.key, index, item)

    # -- scalars ----------------------------------------------------------

    def _feed_scalars(self, text: str) -> None:
        if not self._spec.scalar_fields:
            return
        scan_from = _json_scan_start(text)
        if scan_from < 0:
            return
        completed = 0
        for name in self._spec.scalar_fields:
            match = _field_pattern(name).search(text, scan_from)
            if match is None:
                continue
            value, done = _decode_partial_string(text, match.end())
            if done:
                completed += 1
            if value == self._scalars[name]:
                continue
            previous = self._scalars[name]
            self._scalars[name] = value
            if previous and value.startswith(previous):
                self._emit_delta(name, None, value[len(previous):], False)
            elif not previous:
                self._emit_delta(name, None, value, False)
            else:
                # Model revised the text (retry or mojibake repair): resync.
                self._emit_delta(name, None, value, True)
        if self._spec.scalar_fields and completed == len(self._spec.scalar_fields):
            self._done = True

    # -- arrays -----------------------------------------------------------

    def _feed_arrays(self, text: str) -> None:
        for array in self._spec.arrays:
            index_in_call = 0
            for bracket in _array_starts(text, array.key):
                for start, end in _iter_array_objects(text, bracket):
                    if end is None:
                        # Still-streaming last object: stream its display
                        # fields if it has not been emitted yet.
                        if index_in_call >= self._counts[array.key]:
                            self._stream_active_item(array, text[start:], self._bases[array.key] + index_in_call)
                        break
                    if index_in_call >= self._counts[array.key]:
                        try:
                            item = json.loads(text[start : end + 1])
                        except json.JSONDecodeError:
                            item = None
                        if isinstance(item, dict) and item:
                            self._emit_item(array.key, self._bases[array.key] + index_in_call, item)
                        self._counts[array.key] = index_in_call + 1
                        self._active = {
                            key: value for key, value in self._active.items() if key[0] != array.key
                        }
                    index_in_call += 1

    def _stream_active_item(self, array: AgentArraySpec, slice_text: str, global_ordinal: int) -> None:
        for name in array.display_fields:
            match = _field_pattern(name).search(slice_text)
            if match is None:
                continue
            value, _ = _decode_partial_string(slice_text, match.end())
            state = self._active.get((array.key, name))
            if state is not None and state[0] != global_ordinal:
                state = None  # moved on to a new item: resync below
            if state is not None:
                previous_ordinal, previous = state
                if value == previous:
                    continue
                if value.startswith(previous):
                    self._active[(array.key, name)] = (previous_ordinal, value)
                    self._emit_delta(name, global_ordinal, value[len(previous):], False)
                else:
                    self._active[(array.key, name)] = (global_ordinal, value)
                    self._emit_delta(name, global_ordinal, value, True)
            else:
                self._active[(array.key, name)] = (global_ordinal, value)
                if value:
                    # 新（数组，字段，序号）状态的首条 delta 带 reset：场景/镜头的
                    # 显示字段同名同序号（如都叫 title/0），前端按 key 替换而非拼接。
                    self._emit_delta(name, global_ordinal, value, True)

    # -- emission ---------------------------------------------------------

    def _emit_delta(self, field_name: str, index: int | None, delta: str, reset: bool) -> None:
        self._emit({
            "event": "agent_delta",
            "data": {"agent": self._spec.agent_id, "field": field_name, "index": index, "delta": delta, "reset": reset},
        })

    def _emit_item(self, field_name: str, index: int, item: dict[str, Any]) -> None:
        self._emit({
            "event": "agent_item",
            "data": {"agent": self._spec.agent_id, "field": field_name, "index": index, "item": item},
        })


class DirectorOperationEventBus:
    """Per-operation event buffer with SSE subscriber fan-out."""

    def __init__(self, *, max_operations: int = 128) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._closed: set[str] = set()
        self._max_operations = max_operations

    # -- emission ---------------------------------------------------------

    def emit(self, operation_id: str, event: dict[str, Any]) -> None:
        """Publish an event; safe to call from worker threads."""
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._publish, operation_id, event)
                return
            except RuntimeError:
                pass
        self._publish(operation_id, event)

    def _publish(self, operation_id: str, event: dict[str, Any]) -> None:
        terminal = bool(event.get("terminal"))
        if terminal:
            self._closed.add(operation_id)
        buffer = self._buffers.setdefault(operation_id, [])
        sequenced = {"seq": len(buffer) + 1, **event}
        buffer.append(sequenced)
        for queue in self._subscribers.get(operation_id, []):
            queue.put_nowait(sequenced)
            if terminal:
                queue.put_nowait(None)
        if terminal:
            self._subscribers.pop(operation_id, None)
            self._evict()

    def _evict(self) -> None:
        if len(self._buffers) <= self._max_operations:
            return
        for operation_id in list(self._buffers):
            if len(self._buffers) <= self._max_operations:
                break
            if operation_id in self._closed:
                del self._buffers[operation_id]

    # -- subscription -----------------------------------------------------

    def subscribe(
        self, operation_id: str, since: int = 0
    ) -> tuple[asyncio.Queue[dict[str, Any] | None], list[dict[str, Any]]]:
        """Register a subscriber and get the replayable backlog (seq > since).

        Must run on the event loop.  Live events queued between registration
        and backlog delivery are deduplicated by the caller via ``seq``.
        """
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._subscribers.setdefault(operation_id, []).append(queue)
        if operation_id in self._closed:
            queue.put_nowait(None)
        replay = [event for event in self._buffers.get(operation_id, []) if event.get("seq", 0) > since]
        return queue, replay

    def unsubscribe(self, operation_id: str, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        subscribers = self._subscribers.get(operation_id)
        if not subscribers:
            return
        remaining = [item for item in subscribers if item is not queue]
        if remaining:
            self._subscribers[operation_id] = remaining
        else:
            self._subscribers.pop(operation_id, None)

    def is_closed(self, operation_id: str) -> bool:
        return operation_id in self._closed

    def close(self) -> None:
        for queues in self._subscribers.values():
            for queue in queues:
                queue.put_nowait(None)
        self._subscribers.clear()
        self._buffers.clear()
        self._closed.clear()


def terminal_event_for_status(status: str, *, result: Any = None, message: str | None = None) -> dict[str, Any]:
    """Map an operation status to the SSE terminal event frame."""
    if status == "succeeded":
        return {"event": "done", "terminal": True, "data": {"status": status, "result": result or {}}}
    name = "cancelled" if status == "cancelled" else "error"
    return {"event": name, "terminal": True, "data": {"status": status, "message": message or ""}}
