"""CPU-only stage guards. No module-global monkey patches or upstream writes."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

PROTOCOL = "zly-h3-confirmation@1"
NODE_CLASS = "ZlyH3ConfirmedDirector"


class ConfirmationError(RuntimeError):
    pass


def clone_function(function, **bindings):
    """Create a private function namespace; never assign into upstream globals."""
    namespace = {**function.__globals__, **bindings}
    result = types.FunctionType(function.__code__, namespace, function.__name__,
                                function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def source_revision(prompt: dict, node_id: str) -> str:
    """Freeze all upstream graph ancestors, allowing only stage controls and MP."""
    pending, selected = [str(node_id)], {}
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        if key not in prompt:
            raise ConfirmationError("INVALID_GRAPH: missing ancestor")
        node = copy.deepcopy(prompt[key])
        node.pop("_meta", None)
        inputs = node.get("inputs", {})
        if key == str(node_id):
            for field in ("stage", "source_revision", "expected_instance_id"):
                inputs.pop(field, None)
        if node.get("class_type") == "MiniMaxH3DirectorRefine":
            inputs.pop("megapixels", None)
        selected[key] = node
        for value in inputs.values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                if str(value[0]) in prompt:
                    pending.append(str(value[0]))
    packed = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def valid_cache_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ConfirmationError("INVALID_CACHE_KEY: expected 32 lowercase hex characters")
    return value


@contextmanager
def exclusive_lock(path: Path):
    """Non-blocking OS lock, automatically released if ComfyUI terminates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConfirmationError("CACHE_BUSY: another stage is using this source") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StageGuard:
    """Guards the actual execution calls, not a racy HTTP cache preflight."""
    def __init__(self, stage, original_globals):
        if stage not in ("preview_only", "refine_only"):
            raise ConfirmationError("INVALID_STAGE")
        self.stage = stage
        self.original = original_globals
        self.loaded = set()
        self.saved = set()
        self.first_samples = 0
        self.refine_samples = 0

    def load(self, node_id, seg, plan):
        if self.stage == "preview_only":
            # A stale/matching cache must never advance preview into refinement.
            return None
        cached = self.original["load_first_pass_cache"](node_id, seg, plan)
        if cached is None:
            raise ConfirmationError("FIRST_PASS_CACHE_INVALID: 一采缓存已失效，原片仍可使用；继续二采需要重新生成一采预览")
        self.loaded.add(seg.index)
        return cached  # Executor retains this loaded latent through the second pass.

    def first(self, *args, **kwargs):
        if self.stage != "preview_only":
            raise ConfirmationError("STAGE_VIOLATION: refinement cannot sample first pass")
        result = self.original["sample_single_stage"](*args, **kwargs)
        self.first_samples += 1
        return result

    def refine(self, *args, **kwargs):
        if self.stage != "refine_only":
            raise ConfirmationError("STAGE_VIOLATION: preview cannot refine")
        result = self.original["apply_segment_refine"](*args, **kwargs)
        self.refine_samples += 1
        return result

    def save(self, node_id, seg, plan, **kwargs):
        if self.stage != "preview_only":
            raise ConfirmationError("STAGE_VIOLATION: refinement cannot overwrite first pass")
        self.original["save_first_pass_cache"](node_id, seg, plan, **kwargs)
        # Upstream save deliberately swallows failures; verify the actual latent.
        if self.original["load_first_pass_cache"](node_id, seg, plan) is None:
            raise ConfirmationError("FIRST_PASS_CACHE_WRITE_FAILED")
        self.saved.add(seg.index)

    def bindings(self):
        def reject_selflift(*args, **kwargs):
            raise ConfirmationError("UNSUPPORTED_RECIPE: SelfLift is not part of this recipe")
        return {
            "load_first_pass_cache": self.load,
            "sample_single_stage": self.first,
            "sample_selflift_stage": reject_selflift,
            "apply_segment_refine": self.refine,
            "save_first_pass_cache": self.save,
        }

    def verify(self, plan):
        expected = {seg.index for seg in plan.segments}
        if not expected:
            raise ConfirmationError("EMPTY_PLAN")
        if self.stage == "preview_only":
            valid = self.saved == expected and self.first_samples == len(expected) and self.refine_samples == 0
        else:
            valid = self.loaded == expected and self.refine_samples == len(expected) and self.first_samples == 0
        if not valid:
            raise ConfirmationError("STAGE_REPORT_INCOMPLETE")
        return {
            "stage": self.stage, "first_pass_samples": self.first_samples,
            "refine_samples": self.refine_samples, "segment_count": len(expected),
            "cached_segments": sorted(self.saved), "reused_segments": sorted(self.loaded),
        }
