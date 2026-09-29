import copy
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from comfyui_nodes.zly_h3_confirmation.protocol import (
    ConfirmationError, StageGuard, clone_function, exclusive_lock,
    source_revision, valid_cache_key,
)
from backend.app.minimax_h3_confirm_workflow import (
    build_confirmation_preview, build_confirmation_refine, validate_confirmation_report,
)
from backend.app.minimax_h3_director_refine_workflow import baseline
from comfyui_nodes.zly_h3_confirmation.node import ZlyH3ConfirmedDirector


def dependency():
    return "original"


def caller():
    return dependency()


# A CPU-only author simulator exercises the real adapter's namespace and state handling.
def load_first_pass_cache(node_id, seg, plan):
    return {"av_latent": {"samples": "saved"}}


def save_first_pass_cache(*args, **kwargs):
    pass


def sample_single_stage(*args, **kwargs):
    return {"samples": "first"}


def apply_segment_refine(*args, **kwargs):
    return {"samples": "refined"}


def execute_director_plan_core(plan, node_id=None, **kwargs):
    executor_options(kwargs)
    seg = plan.segments[0]
    cached = load_first_pass_cache(node_id, seg, plan)
    if cached is None:
        sample_single_stage()
        save_first_pass_cache(node_id, seg, plan, av_latent={})
    else:
        apply_segment_refine()
    return tuple(range(8))


executor_options = Mock()


def finalize_director_outputs(*args, **kwargs):
    return tuple(range(8))


class FakeAuthor:
    def execute(self, unique_id=None, **kwargs):
        plan = SimpleNamespace(segments=[SimpleNamespace(index=0, task_key="r2v")], run_indices=None,
                               refine=copy.deepcopy(kwargs.get("refine") or {}))
        result = execute_director_plan_core(plan, node_id=unique_id)
        return finalize_director_outputs(result)


class StageGuardTests(unittest.TestCase):
    def setUp(self):
        self.functions = {key: Mock() for key in (
            "load_first_pass_cache", "save_first_pass_cache", "sample_single_stage", "apply_segment_refine")}
        self.functions["load_first_pass_cache"].return_value = {"av_latent": {"samples": "latent"}}
        self.seg = SimpleNamespace(index=0)
        self.plan = SimpleNamespace(segments=[self.seg])

    def test_preview_ignores_existing_cache_and_cannot_refine(self):
        guard = StageGuard("preview_only", self.functions)
        self.assertIsNone(guard.load("key", self.seg, self.plan))
        self.functions["load_first_pass_cache"].assert_not_called()
        with self.assertRaises(ConfirmationError):
            guard.refine()
        self.functions["apply_segment_refine"].assert_not_called()
        guard.first()
        guard.save("key", self.seg, self.plan, av_latent={})
        self.assertEqual(guard.verify(self.plan)["cached_segments"], [0])

    def test_refinement_missing_cache_fails_without_first_pass(self):
        guard = StageGuard("refine_only", self.functions)
        # A preflight may have succeeded; actual load now reports missing.
        self.functions["load_first_pass_cache"].return_value = None
        with self.assertRaisesRegex(ConfirmationError, "FIRST_PASS_CACHE_INVALID"):
            guard.load("key", self.seg, self.plan)
        with self.assertRaisesRegex(ConfirmationError, "STAGE_VIOLATION"):
            guard.first()
        self.functions["sample_single_stage"].assert_not_called()

    def test_refinement_holds_loaded_latent_and_never_overwrites_source(self):
        guard = StageGuard("refine_only", self.functions)
        cached = guard.load("key", self.seg, self.plan)
        self.functions["load_first_pass_cache"].return_value = None
        self.assertEqual(cached["av_latent"]["samples"], "latent")
        guard.refine()
        self.assertEqual(guard.verify(self.plan)["first_pass_samples"], 0)
        with self.assertRaises(ConfirmationError):
            guard.save("key", self.seg, self.plan)
        self.functions["save_first_pass_cache"].assert_not_called()

    def test_swallowed_upstream_cache_write_error_is_failure(self):
        guard = StageGuard("preview_only", self.functions)
        self.functions["load_first_pass_cache"].return_value = None
        with self.assertRaisesRegex(ConfirmationError, "WRITE_FAILED"):
            guard.save("key", self.seg, self.plan)

    def test_partial_report_not_success(self):
        guard = StageGuard("refine_only", self.functions)
        guard.load("key", self.seg, self.plan)
        with self.assertRaisesRegex(ConfirmationError, "INCOMPLETE"):
            guard.verify(self.plan)

    def test_private_binding_never_changes_original_or_other_request(self):
        private = clone_function(caller, dependency=lambda: "private")
        other = clone_function(caller, dependency=lambda: "other")
        self.assertEqual(private(), "private")
        self.assertEqual(other(), "other")
        self.assertEqual(caller(), "original")

    def test_cache_key_cannot_escape_namespace(self):
        for key in ("../12", "12", "A" * 32, "x" * 32):
            with self.subTest(key=key), self.assertRaises(ConfirmationError):
                valid_cache_key(key)
        self.assertEqual(valid_cache_key("a" * 32), "a" * 32)

    def test_same_cache_lock_rejects_concurrent_stage_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.lock"
            with exclusive_lock(path):
                with self.assertRaisesRegex(ConfirmationError, "CACHE_BUSY"):
                    with exclusive_lock(path):
                        self.fail("Acquired same source twice")
            with exclusive_lock(path):
                pass


class ConfirmationGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_confirmation_preview({
            "totalFrames": 53, "global": {"refs": [{"imageFile": "a.png"}]},
            "segments": [{"id": "one", "frameCount": 53, "prompt": "test"}],
        }, "16:9", 0, "a" * 32, "video/preview")
        self.report = {"protocol": "zly-h3-confirmation@1", "stage": "preview_only",
                       "source_revision": source_revision(self.graph, "12"),
                       "cache_key": "a" * 32, "instance_id": "b" * 32,
                       "segment_count": 1, "first_pass_samples": 1, "refine_samples": 0,
                       "cached_segments": [0], "reused_segments": []}

    def test_copied_graph_preserves_models_and_sampling(self):
        original = baseline()
        for key in ("1", "2", "3", "4", "15", "16", "30", "31", "32", "33"):
            self.assertEqual(self.graph[key], original[key])
        self.assertEqual(self.graph["23"]["class_type"], "ExperimentalW4A8UNETLoader")
        self.assertEqual(self.graph["23"]["inputs"], {"unet_name": original["23"]["inputs"]["unet_name"]})
        self.assertEqual(original["23"]["class_type"], "UNETLoader")
        self.assertEqual(self.graph["12"]["inputs"]["seed"], 0)
        self.assertEqual(self.graph["12"]["inputs"]["stage"], "preview_only")

    def test_refinement_uses_frozen_graph_only_and_retains_revision(self):
        frozen = copy.deepcopy(self.graph)
        for quality in (1.0, 2.0):
            refined = build_confirmation_refine(self.graph, self.report, quality, "video/refine")
            self.assertEqual(source_revision(refined, "12"), self.report["source_revision"])
            self.assertEqual(refined["12"]["inputs"]["seed"], 0)
            self.assertEqual(refined["38"]["inputs"]["megapixels"], 0.98 if quality == 1.0 else quality)
        self.assertEqual(self.graph, frozen)

    def test_source_changes_invalidate_revision(self):
        for key, field, value in (("12", "seed", 1), ("12", "timeline_data", "changed"),
                                  ("23", "unet_name", "changed"), ("38", "sampler", "changed")):
            graph = copy.deepcopy(self.graph)
            graph[key]["inputs"][field] = value
            self.assertNotEqual(source_revision(graph, "12"), self.report["source_revision"])

    def test_comfy_success_or_video_is_not_stage_report(self):
        with self.assertRaises(ValueError):
            validate_confirmation_report({"status": "success", "video": "first.mp4"}, "refine_only")
        with self.assertRaises(ValueError):
            validate_confirmation_report(self.report, "refine_only")


class AdapterStateTests(unittest.TestCase):
    def setUp(self):
        ConfirmationGraphTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = SimpleNamespace(get_output_directory=lambda: self.temp.name)
        patchers = [patch.dict(sys.modules, {"folder_paths": folder,
                    "torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))}),
                    patch("comfyui_nodes.zly_h3_confirmation.node.author_class", return_value=FakeAuthor),
                    patch("comfyui_nodes.zly_h3_confirmation.node.verify_author")]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def execute(self, graph):
        inputs = copy.deepcopy(graph["12"]["inputs"])
        inputs["refine"] = {"enabled": True, "mode": "upscale", "upscale_method": "h3_latent",
                            "megapixels": graph["38"]["inputs"]["megapixels"], "passes": 1,
                            "sample_model": "original"}
        return ZlyH3ConfirmedDirector().execute(prompt=graph, unique_id="12", **inputs)

    def test_full_preview_confirm_and_quality_versions(self):
        preview = self.execute(self.graph)
        report = preview["ui"]["zly_h3_confirmation"][0]
        validate_confirmation_report(report, "preview_only")
        self.assertEqual(preview["result"][:8], tuple(range(8)))
        for quality in (1.0, 2.0):
            graph = build_confirmation_refine(self.graph, report, quality, "test")
            result = self.execute(graph)
            refined = result["ui"]["zly_h3_confirmation"][0]
            validate_confirmation_report(refined, "refine_only")
            self.assertEqual(refined["source_revision"], report["source_revision"])
        self.assertEqual(execute_director_plan_core.__globals__["load_first_pass_cache"], load_first_pass_cache)

    def test_16gb_policy_reuses_unchanged_first_pass_identity(self):
        report = self.execute(self.graph)["ui"]["zly_h3_confirmation"][0]
        graph = build_confirmation_refine(self.graph, report, 1.0, "test")
        fake_cuda = SimpleNamespace(is_available=lambda: True, current_device=lambda: 0,
            get_device_properties=lambda _: SimpleNamespace(total_memory=16 * 1024**3))
        with patch.dict(sys.modules, {"torch": SimpleNamespace(cuda=fake_cuda)}), \
            patch("comfyui_nodes.zly_h3_confirmation.node.compatible_refine", side_effect=lambda fn, evidence: fn), \
             patch("comfyui_nodes.zly_h3_confirmation.node.static_refinement_clone", return_value="static") as clone:
            result = self.execute(graph)["ui"]["zly_h3_confirmation"][0]
        clone.assert_called_once_with("original")
        self.assertFalse(result["memory_policy"]["dynamic_vram"])
        self.assertTrue(result["memory_policy"]["clear_vram_before_refine"])
        executor_options.assert_called_with({"clear_vram_before_refine": True, "clear_vram_between_segments": True})
        self.assertEqual(result["source_revision"], report["source_revision"])
        self.assertEqual(result["first_pass_samples"], 0)
        self.assertEqual(result["reused_segments"], [0])
        self.assertEqual(result["memory_policy"]["tile_count"], 4)

    def test_repeated_preview_cannot_overwrite_ready_source(self):
        self.execute(self.graph)
        with self.assertRaisesRegex(ConfirmationError, "ALREADY_COMPLETE"):
            self.execute(self.graph)

    def test_instance_or_source_change_rejected_before_sampling(self):
        report = self.execute(self.graph)["ui"]["zly_h3_confirmation"][0]
        graph = build_confirmation_refine(self.graph, report, 1.0, "test")
        with patch(__name__ + ".apply_segment_refine") as refine:
            changed = copy.deepcopy(graph)
            changed["12"]["inputs"]["expected_instance_id"] = "wrong"
            with self.assertRaisesRegex(ConfirmationError, "INSTANCE_CHANGED"):
                self.execute(changed)
            changed = copy.deepcopy(graph)
            changed["12"]["inputs"]["seed"] = 7
            with self.assertRaisesRegex(ConfirmationError, "SOURCE_REVISION_CONFLICT"):
                self.execute(changed)
            refine.assert_not_called()

    def test_failed_refinement_keeps_ready_source_and_can_retry(self):
        report = self.execute(self.graph)["ui"]["zly_h3_confirmation"][0]
        graph = build_confirmation_refine(self.graph, report, 1.0, "test")
        manifest_path = Path(self.temp.name) / "zly_h3_confirmation" / ("a" * 32 + ".json")
        before = manifest_path.read_bytes()
        with patch(__name__ + ".apply_segment_refine", side_effect=RuntimeError("cancelled")):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.execute(graph)
        self.assertEqual(manifest_path.read_bytes(), before)
        result = self.execute(graph)
        validate_confirmation_report(result["ui"]["zly_h3_confirmation"][0], "refine_only")


if __name__ == "__main__":
    unittest.main()
