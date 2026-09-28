"""Add-on adapter: imports the installed author node without modifying it."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import time
import uuid
from pathlib import Path

from .protocol import (
    NODE_CLASS, PROTOCOL, ConfirmationError, StageGuard, atomic_json,
    clone_function, exclusive_lock, source_revision as graph_revision, valid_cache_key,
)

# Author revision a8938feb6ada0b7981f977b1a6be59341f0c6d10, verified on target.
PINNED = {
    "nodes/director.py": "640090027e562004d8cb0e486812a122432624a247683d88a9dc781a1f2b0185",
    "nodes/director_common.py": "be4782b420f2722cbc7b17131b96c5823ecbb16320806b2b819fe8ea2128b001",
    "director/executor_core.py": "ead1b442a2f1b0bf96ed880d180b5ee6d0e55aa5d5e65b74a185c79e5ef876b1",
    "director/segment_cache.py": "211acfe976295f76e82a0c6e96f4b528b65bd10864c57528e18d524603f1f540",
}


def author_class():
    import nodes
    result = nodes.NODE_CLASS_MAPPINGS.get("MiniMaxH3Director")
    if result is None:
        raise ConfirmationError("AUTHOR_NODE_MISSING: install the original MiniMax H3 Director")
    return result


def verify_author(author):
    root = Path(inspect.getfile(author)).resolve().parents[1]
    for relative, expected in PINNED.items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ConfirmationError(f"AUTHOR_VERSION_MISMATCH: {relative}; original workflow remains available")


class ZlyH3ConfirmedDirector:
    @classmethod
    def INPUT_TYPES(cls):
        result = copy.deepcopy(author_class().INPUT_TYPES())
        result["required"].update({
            "stage": (["preview_only", "refine_only"],),
            "cache_key": ("STRING", {"default": ""}),
            "source_revision": ("STRING", {"default": ""}),
            "expected_instance_id": ("STRING", {"default": ""}),
        })
        result["hidden"]["prompt"] = "PROMPT"
        return result

    RETURN_TYPES = ("IMAGE", "AUDIO", "FLOAT", "INT", "IMAGE", "STRING", "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("images", "audio", "fps", "frame_count", "source_images", "report",
                    "images_pre_refine", "images_pre_face_refine", "confirmation_report")
    OUTPUT_IS_LIST = (True, True, False, False, True, False, True, True, False)
    FUNCTION = "execute"
    CATEGORY = "ZLY/H3 Confirmation"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Stage guards must run even if ComfyUI has memoized an identical graph.
        return float("nan")

    def execute(self, stage, cache_key, source_revision, expected_instance_id,
                prompt=None, unique_id=None, **kwargs):
        import folder_paths
        valid_cache_key(cache_key)
        if not prompt or str(unique_id) not in prompt:
            raise ConfirmationError("FROZEN_GRAPH_REQUIRED")
        if prompt[str(unique_id)].get("class_type") != NODE_CLASS:
            raise ConfirmationError("INVALID_GRAPH")
        author = author_class()
        verify_author(author)
        revision = graph_revision(prompt, str(unique_id))
        root = Path(folder_paths.get_output_directory()) / "zly_h3_confirmation"
        with exclusive_lock(root / "instance.lock"):
            instance_path = root / "instance.json"
            if not instance_path.exists():
                atomic_json(instance_path, {"id": uuid.uuid4().hex})
            instance_id = json.loads(instance_path.read_text(encoding="utf-8"))["id"]
        with exclusive_lock(root / (cache_key + ".lock")):
            manifest_path = root / (cache_key + ".json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
            if stage == "preview_only":
                if source_revision or expected_instance_id:
                    raise ConfirmationError("PREVIEW_MUST_HAVE_NEW_SOURCE")
                if manifest and manifest.get("state") == "ready":
                    raise ConfirmationError("PREVIEW_ALREADY_COMPLETE: use saved preview or a new cache key")
            elif stage == "refine_only":
                if not manifest or manifest.get("state") != "ready":
                    raise ConfirmationError("FIRST_PASS_CACHE_INVALID: regenerate a preview")
                if expected_instance_id != instance_id:
                    raise ConfirmationError("INSTANCE_CHANGED: restore original ComfyUI or generate a new preview")
                if source_revision != revision or manifest.get("source_revision") != revision:
                    raise ConfirmationError("SOURCE_REVISION_CONFLICT")
            else:
                raise ConfirmationError("INVALID_STAGE")
            # Only the copied author recipe is supported. No selective runs or extras.
            for name in ("selflift", "semantic_bridge", "face_refine", "i2v_groups", "r2v_groups"):
                if kwargs.get(name) is not None:
                    raise ConfirmationError("UNSUPPORTED_RECIPE: " + name)
            pack = dict(kwargs.get("refine") or {})
            if not pack.get("enabled") or pack.get("mode") != "upscale" or pack.get("upscale_method") != "h3_latent":
                raise ConfirmationError("AUTHOR_REFINE_PACK_REQUIRED")
            if float(pack.get("megapixels", 0)) not in (1.0, 2.0) or int(pack.get("passes", 0)) != 1:
                raise ConfirmationError("UNSUPPORTED_REFINE_QUALITY")
            pack["confirm_first_pass"] = True
            kwargs["refine"] = pack
            core = author.execute.__globals__["execute_director_plan_core"]
            guard = StageGuard(stage, core.__globals__)
            execute_core = clone_function(core, **guard.bindings())
            proof = {}

            def guarded_core(plan, **core_args):
                indices = set(range(len(plan.segments)))
                if plan.run_indices is not None and set(plan.run_indices) != indices:
                    raise ConfirmationError("PARTIAL_PLAN_UNSUPPORTED")
                if any(seg.task_key != "r2v" for seg in plan.segments):
                    raise ConfirmationError("R2V_REQUIRED")
                result = execute_core(plan, **core_args)
                proof.update(guard.verify(plan))
                return result

            original_finalize = author.execute.__globals__["finalize_director_outputs"]

            def finalize(*args, **output_kwargs):
                if stage == "preview_only":
                    # In preview, the combined frames are first-pass output, deliberately exposed.
                    output_kwargs["block_final_images"] = False
                return original_finalize(*args, **output_kwargs)

            run = clone_function(author.execute, execute_director_plan_core=guarded_core,
                                 finalize_director_outputs=finalize)
            started = time.time()
            # A distinct nonnumeric namespace cannot collide with author UI node IDs.
            result = run(author(), unique_id="zly_confirm_" + cache_key, **kwargs)
            report = {
                "protocol": PROTOCOL, "cache_key": cache_key, "source_revision": revision,
                "instance_id": instance_id, "started_at": started, "completed_at": time.time(),
                **proof,
            }
            if stage == "preview_only":
                atomic_json(manifest_path, {**report, "state": "ready"})
            encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
            return {"ui": {"zly_h3_confirmation": [report]}, "result": tuple(result) + (encoded,)}
