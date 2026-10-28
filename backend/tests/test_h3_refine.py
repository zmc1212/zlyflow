import json
import unittest
from unittest.mock import patch

from backend.app.media_studio.services.episode_video_service import EpisodeVideoService

from backend.app.minimax_h3_refine_workflow import (
    PREVIEW_OUTPUT_NODE,
    PREVIEW_VIDEO_NODE,
    REFINE_LATENT_UPSCALER,
    build_minimax_h3_refine_workflow,
    continuation_workflow,
    first_pass_lora,
    first_pass_steps,
    first_pass_task_type,
    first_pass_unet,
    numeric_aspect_ratio,
    refine_tiling,
)
from backend.app.minimax_h3_director_accel_workflow import (
    TASK_TYPE_FL2V,
    TASK_TYPE_I2V,
    TASK_TYPE_R2V,
    TASK_TYPE_T2V,
)
from backend.app.models import JobMode
from backend.app.workflow_registry import (
    H3_FL2VA_FULL,
    H3_FL2VA_PRUNED,
    H3_REF2VA_FULL,
    H3_REF2VA_PRUNED,
    H3_STANDARD_OPTION_SCHEMA,
    H3_TURBO_LORA_NAME,
    H3_WORKFLOWS,
    LIGHTX2V_FL2V_4STEP_LORA,
    LIGHTX2V_FL2V_8STEP_LORA,
    LIGHTX2V_REF2V_4STEP_LORA,
    DUAL_ACCEL_LORA_NAME,
    normalize_options,
    refine_target_megapixels,
    workflow_for,
)


OFFICIAL_H3_MODES = (JobMode.MINIMAX_H3_T2V, JobMode.MINIMAX_H3_I2V, JobMode.MINIMAX_H3_R2V)


def t8_aspect(mode: JobMode, raw: dict) -> dict:
    if mode in {JobMode.MINIMAX_H3_T8_ALL_REFERENCE, JobMode.MINIMAX_H3_T8_DUAL_CLOCK}:
        raw.setdefault("aspect_ratio", "16:9 (Widescreen)")
    return raw


class H3RefineOptionTests(unittest.TestCase):
    def test_every_h3_workflow_exposes_two_pass_options_instead_of_rtx_upscale(self) -> None:
        for mode in sorted(H3_WORKFLOWS, key=lambda item: item.value):
            with self.subTest(mode=mode.value):
                definition = workflow_for(mode)
                schema = definition.option_schema or H3_STANDARD_OPTION_SCHEMA
                properties = schema["properties"]
                self.assertNotIn("upscale_after", properties)
                self.assertEqual(properties["refine_enabled"]["type"], "boolean")
                self.assertEqual(properties["refine_enabled"]["default"], False)
                self.assertEqual(properties["refine_enabled"]["ui_group"], "primary")
                self.assertEqual(properties["refine_quality"]["type"], "string")
                self.assertEqual(properties["refine_quality"]["default"], "1.0")
                self.assertEqual(properties["refine_quality"]["ui_group"], "primary")
                self.assertEqual(properties["refine_quality"]["ui_visible_when"], {"refine_enabled": True})
                self.assertEqual(properties["refine_quality_mode"]["type"], "string")
                self.assertEqual(properties["refine_quality_mode"]["default"], "auto")
                self.assertEqual(properties["refine_quality_mode"]["ui_group"], "primary")
                self.assertEqual(properties["refine_quality_mode"]["ui_visible_when"], {"refine_enabled": True})
                self.assertEqual(properties["refine_preview"]["type"], "boolean")
                self.assertEqual(properties["refine_preview"]["default"], True)
                self.assertEqual(properties["refine_preview"]["ui_group"], "internal")
                self.assertNotIn("ui_visible_when", properties["refine_preview"])
                self.assertEqual(properties["quality"]["ui_visible_when"], {"refine_enabled": False})
                self.assertEqual(properties["weight_profile"]["ui_visible_when"], {"refine_enabled": False})
                self.assertEqual(properties["speed"]["ui_visible_when"], {"refine_enabled": False})

    def test_refine_quality_accepts_one_or_two_megapixels_only(self) -> None:
        for mode in sorted(H3_WORKFLOWS, key=lambda item: item.value):
            with self.subTest(mode=mode.value):
                raw = t8_aspect(mode, {"refine_enabled": True, "refine_quality": "2.0"})
                normalized = normalize_options(mode, raw)
                self.assertTrue(normalized["refine_enabled"])
                self.assertEqual(normalized["refine_quality"], "2.0")
                self.assertEqual(normalized["quality"], "0.4")
                self.assertEqual(normalized["megapixels"], 0.4)
                self.assertNotIn("upscale_after", normalized)
                with self.assertRaises(ValueError):
                    normalize_options(mode, t8_aspect(mode, {"refine_enabled": True, "refine_quality": "3.0"}))

    def test_refine_stays_off_by_default(self) -> None:
        for mode in sorted(H3_WORKFLOWS, key=lambda item: item.value):
            with self.subTest(mode=mode.value):
                normalized = normalize_options(mode, t8_aspect(mode, {}))
                self.assertFalse(normalized["refine_enabled"])
                self.assertEqual(normalized["refine_quality"], "1.0")
                self.assertEqual(normalized["refine_quality_mode"], "auto")
                self.assertFalse(normalized["refine_preview"])
                self.assertNotIn("upscale_after", normalized)

    def test_refine_quality_mode_defaults_to_auto_and_rejects_unknown_values(self) -> None:
        for mode in sorted(H3_WORKFLOWS, key=lambda item: item.value):
            with self.subTest(mode=mode.value):
                forced = normalize_options(
                    mode,
                    t8_aspect(mode, {
                        "refine_enabled": True, "refine_quality": "1.0", "refine_quality_mode": "force",
                    }),
                )
                self.assertEqual(forced["refine_quality_mode"], "force")
                with self.assertRaises(ValueError):
                    normalize_options(
                        mode,
                        t8_aspect(mode, {"refine_enabled": True, "refine_quality_mode": "turbo"}),
                    )

    def test_refine_preview_is_platform_managed_and_disabled_without_two_pass(self) -> None:
        defaulted = normalize_options(
            JobMode.MINIMAX_H3_R2V, {"refine_enabled": True},
        )
        self.assertTrue(defaulted["refine_preview"])
        opted_out = normalize_options(
            JobMode.MINIMAX_H3_R2V, {"refine_enabled": True, "refine_preview": False},
        )
        self.assertTrue(opted_out["refine_preview"])
        disabled = normalize_options(
            JobMode.MINIMAX_H3_R2V, {"refine_enabled": False, "refine_preview": True},
        )
        self.assertFalse(disabled["refine_preview"])

    def test_legacy_upscale_flag_is_ignored(self) -> None:
        normalized = normalize_options(JobMode.MINIMAX_H3_R2V, {"upscale_after": True})
        self.assertFalse(normalized["refine_enabled"])
        self.assertNotIn("upscale_after", normalized)


class OfficialH3RefineTests(unittest.TestCase):
    def options(self, mode: JobMode, raw=None):
        return normalize_options(mode, {"refine_enabled": True, "aspect_ratio": "16:9", **(raw or {})})

    def test_refine_locks_the_verified_first_pass_and_ignores_conflicting_options(self) -> None:
        normalized = self.options(JobMode.MINIMAX_H3_I2V, {
            "quality": "2.0",
            "megapixels": 2.0,
            "weight_profile": "full",
            "speed": "quality",
            "upscale_after": True,
        })
        self.assertTrue(normalized["refine_enabled"])
        self.assertEqual(normalized["refine_quality"], "1.0")
        self.assertEqual(normalized["quality"], "0.4")
        self.assertEqual(normalized["megapixels"], 0.4)
        self.assertEqual(normalized["weight_profile"], "pruned")
        self.assertEqual(normalized["speed"], "balanced")
        self.assertEqual(normalized["steps"], 8)
        self.assertEqual(normalized["lora_name"], LIGHTX2V_FL2V_8STEP_LORA)
        self.assertEqual(normalized["lora_strength"], 1.0)
        self.assertNotIn("upscale_after", normalized)

    def test_i2v_graph_generates_two_passes_with_h3_latent_upscale(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_I2V, {"duration": 5, "refine_quality": "2.0"})
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_I2V,
            "Camera slowly pushes in.",
            ["start.png", "end.png"],
            options,
            42,
        )

        self.assertEqual(graph["1"]["class_type"], "UNETLoader")
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_PRUNED)
        self.assertEqual(graph["15"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_FL2V_8STEP_LORA)
        self.assertEqual(graph["15"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["18"]["class_type"], "ReservedVRAMSetter")
        self.assertEqual(graph["18"]["inputs"]["reserved"], 3.0)
        self.assertTrue(graph["18"]["inputs"]["clean_gpu_before"])
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")

        self.assertEqual(graph["30"]["class_type"], "MiniMaxH3DirectorGroupImageToVideo")
        self.assertEqual(graph["30"]["inputs"]["first_frame"], ["20", 0])
        self.assertEqual(graph["30"]["inputs"]["last_frame"], ["21", 0])
        self.assertEqual(graph["12"]["class_type"], "MiniMaxH3Director")
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_FL2V)
        self.assertEqual(graph["12"]["inputs"]["refine"], ["45", 0])
        self.assertEqual(graph["12"]["inputs"]["steps"], 8)
        self.assertEqual(graph["12"]["inputs"]["width"], 864)
        self.assertEqual(graph["12"]["inputs"]["height"], 480)
        self.assertEqual(graph["12"]["inputs"]["total_frames"], 124)
        self.assertTrue(graph["12"]["inputs"]["clear_vram_before_refine"])

        self.assertNotIn("40", graph)
        self.assertNotIn("41", graph)
        self.assertNotIn("42", graph)
        self.assertNotIn("43", graph)
        self.assertNotIn("refine_model", graph["45"]["inputs"])
        self.assertEqual(graph["44"]["inputs"]["model"], graph["12"]["inputs"]["model"])
        self.assertEqual(graph["44"]["class_type"], "BasicScheduler")
        self.assertEqual(graph["44"]["inputs"]["scheduler"], "beta")
        self.assertEqual(graph["44"]["inputs"]["steps"], 3)
        self.assertEqual(graph["44"]["inputs"]["denoise"], 0.2)
        self.assertEqual(graph["45"]["class_type"], "MiniMaxH3DirectorRefine")
        self.assertEqual(graph["45"]["inputs"]["mode"], "upscale")
        self.assertEqual(graph["45"]["inputs"]["upscale_method"], "h3_latent")
        self.assertEqual(graph["45"]["inputs"]["latent_upscale_model"], REFINE_LATENT_UPSCALER)
        self.assertEqual(graph["45"]["inputs"]["sampler"], "euler")
        self.assertEqual(graph["45"]["inputs"]["passes"], 1)
        self.assertEqual(graph["45"]["inputs"]["seed_mode"], "inherit")
        self.assertEqual(graph["45"]["inputs"]["aspect_ratio"], "跟随导演台")
        # 5 s = 124 frames; 2.0 MP is capped to 200/124 ≈ 1.6 MP.
        self.assertEqual(graph["45"]["inputs"]["megapixels"], 1.6)
        self.assertEqual(graph["45"]["inputs"]["width"], 1728)
        self.assertEqual(graph["45"]["inputs"]["height"], 960)
        self.assertFalse(graph["45"]["inputs"]["skip_fl2v"])
        self.assertFalse(graph["45"]["inputs"]["confirm_first_pass"])
        self.assertFalse(graph["45"]["inputs"]["enable_tiling"])
        self.assertTrue(graph["45"]["inputs"]["enable_latent_chunking"])
        self.assertFalse(graph["16"]["inputs"]["allow_compile"])

        self.assertEqual(graph["13"]["class_type"], "CreateVideo")
        self.assertEqual(graph["14"]["class_type"], "SaveVideo")
        self.assertEqual(graph["14"]["inputs"]["video"], ["13", 0])

    def test_r2v_graph_reuses_the_reference_first_pass_model_for_refine(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_R2V)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_R2V,
            "Use <Picture 1>.",
            ["character.png"],
            options,
            7,
        )

        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_REF2VA_PRUNED)
        self.assertEqual(graph["30"]["class_type"], "MiniMaxH3DirectorGroupReferenceToVideo")
        self.assertEqual(graph["30"]["inputs"]["ref_image_size"], "match")
        self.assertEqual(graph["30"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_R2V)
        self.assertEqual(graph["12"]["inputs"]["r2v_groups"], ["30", 0])
        self.assertEqual(graph["44"]["inputs"]["model"], graph["12"]["inputs"]["model"])
        self.assertNotIn("40", graph)
        self.assertTrue(graph["45"]["inputs"]["skip_fl2v"])

    def test_t2v_graph_skips_fl2v_refine_and_has_no_frames(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_T2V)
        graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_T2V, "A preview.", [], options, 7)

        self.assertEqual(graph["30"]["class_type"], "MiniMaxH3DirectorGroupImageToVideo")
        self.assertNotIn("first_frame", graph["30"]["inputs"])
        self.assertNotIn("last_frame", graph["30"]["inputs"])
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_T2V)
        self.assertTrue(graph["45"]["inputs"]["skip_fl2v"])

    def test_refine_quality_one_megapixel_sets_target_canvas(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_I2V, {"refine_quality": "1.0"})
        graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_I2V, "A preview.", ["start.png"], options, 7)

        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_I2V)
        self.assertEqual(graph["45"]["inputs"]["megapixels"], 1.0)
        self.assertEqual(graph["45"]["inputs"]["width"], 1376)
        self.assertEqual(graph["45"]["inputs"]["height"], 768)

    def test_long_clips_cap_the_refine_canvas_to_keep_sampling_fast(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_R2V, {"duration": 13, "refine_quality": "1.0"})
        graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_R2V, "Long take.", ["ref.png"], options, 7)

        self.assertEqual(options["refine_megapixels"], 0.6)
        self.assertEqual(graph["45"]["inputs"]["megapixels"], 0.6)
        self.assertEqual(graph["45"]["inputs"]["width"], 1056)
        self.assertEqual(graph["12"]["inputs"]["total_frames"], 328)

        larger = self.options(JobMode.MINIMAX_H3_R2V, {"duration": 13, "refine_quality": "2.0"})
        self.assertEqual(larger["refine_megapixels"], 0.6)
        self.assertEqual(larger["refine_quality"], "2.0")

    def test_force_mode_keeps_the_requested_canvas_on_long_clips(self) -> None:
        options = self.options(
            JobMode.MINIMAX_H3_R2V,
            {"duration": 13, "refine_quality": "1.0", "refine_quality_mode": "force"},
        )
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_R2V, "Long take.", ["ref.png"], options, 7,
        )

        self.assertEqual(options["refine_quality_mode"], "force")
        self.assertEqual(options["refine_megapixels"], 1.0)
        self.assertEqual(graph["45"]["inputs"]["megapixels"], 1.0)
        self.assertEqual(graph["45"]["inputs"]["width"], 1376)
        self.assertEqual(graph["45"]["inputs"]["height"], 768)

    def test_preview_graph_blocks_the_second_pass_and_exposes_first_pass_video(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_I2V, {"refine_preview": "true"})
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_I2V, "A preview.", ["start.png"], options, 7,
            preview=True,
        )

        self.assertTrue(graph["45"]["inputs"]["confirm_first_pass"])
        self.assertEqual(graph[PREVIEW_VIDEO_NODE]["class_type"], "CreateVideo")
        self.assertEqual(graph[PREVIEW_VIDEO_NODE]["inputs"]["images"], ["12", 6])
        self.assertEqual(graph[PREVIEW_OUTPUT_NODE]["class_type"], "SaveVideo")
        self.assertEqual(graph[PREVIEW_OUTPUT_NODE]["inputs"]["video"], [PREVIEW_VIDEO_NODE, 0])
        self.assertIn("MiniMax_H3_Refine_Preview", graph[PREVIEW_OUTPUT_NODE]["inputs"]["filename_prefix"])
        # The final output stays in the graph but is blocked downstream of the refine node.
        self.assertEqual(graph["14"]["class_type"], "SaveVideo")

        continuation = continuation_workflow(graph)
        self.assertNotIn(PREVIEW_VIDEO_NODE, continuation)
        self.assertNotIn(PREVIEW_OUTPUT_NODE, continuation)
        self.assertEqual(continuation["14"]["class_type"], "SaveVideo")
        self.assertTrue(continuation["45"]["inputs"]["confirm_first_pass"])
        self.assertEqual(graph["14"]["inputs"]["video"], ["13", 0])

    def test_refine_respects_sage_switch_and_short_clip_chunking(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_T2V, {"duration": 2})
        graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_T2V, "A beat.", [], options, 7)
        self.assertEqual(graph["12"]["inputs"]["total_frames"], 56)
        self.assertFalse(graph["45"]["inputs"]["enable_latent_chunking"])

        no_sage = self.options(JobMode.MINIMAX_H3_T2V, {"use_sage_attention": False})
        no_sage_graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_T2V, "A beat.", [], no_sage, 7)
        self.assertNotIn("16", no_sage_graph)
        self.assertNotIn("17", no_sage_graph)
        self.assertNotIn("42", no_sage_graph)
        self.assertNotIn("43", no_sage_graph)
        self.assertEqual(no_sage_graph["12"]["inputs"]["model"], ["18", 0])
        self.assertNotIn("refine_model", no_sage_graph["45"]["inputs"])
        self.assertEqual(no_sage_graph["44"]["inputs"]["model"], ["18", 0])

    def test_long_clips_tile_the_second_pass(self) -> None:
        ten = self.options(JobMode.MINIMAX_H3_I2V, {"duration": 10})
        ten_graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_I2V, "A preview.", ["start.png"], ten, 7,
        )
        self.assertEqual(ten_graph["12"]["inputs"]["total_frames"], 243)
        self.assertTrue(ten_graph["45"]["inputs"]["enable_tiling"])
        self.assertEqual(ten_graph["45"]["inputs"]["tile_count"], 2)
        self.assertEqual(ten_graph["45"]["inputs"]["tile_overlap"], 128)

        thirteen = self.options(JobMode.MINIMAX_H3_I2V, {"duration": 13})
        thirteen_graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_I2V, "A preview.", ["start.png"], thirteen, 7,
        )
        self.assertEqual(thirteen_graph["12"]["inputs"]["total_frames"], 328)
        self.assertTrue(thirteen_graph["45"]["inputs"]["enable_tiling"])
        self.assertEqual(thirteen_graph["45"]["inputs"]["tile_count"], 4)
        self.assertEqual(thirteen_graph["44"]["inputs"]["model"], thirteen_graph["12"]["inputs"]["model"])


class FamilyRefineNormalizationTests(unittest.TestCase):
    def test_lightx2v_keeps_its_speed_and_lora_in_the_first_pass(self) -> None:
        fl2v = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_I2V, {"refine_enabled": True})
        self.assertEqual(fl2v["quality"], "0.4")
        self.assertEqual(fl2v["megapixels"], 0.4)
        self.assertEqual(fl2v["speed"], "fast")
        self.assertEqual(fl2v["steps"], 4)
        self.assertEqual(fl2v["lora_name"], LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(fl2v["lora_strength"], 0.75)
        self.assertEqual(fl2v["sampler_name"], "euler")

        r2v = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_R2V, {"refine_enabled": True})
        self.assertEqual(r2v["lora_name"], LIGHTX2V_REF2V_4STEP_LORA)
        self.assertEqual(r2v["lora_strength"], 0.75)

    def test_dual_accel_keeps_eight_step_full_weight_first_pass(self) -> None:
        normalized = normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, {"refine_enabled": True})
        self.assertEqual(normalized["quality"], "0.4")
        self.assertEqual(normalized["speed"], "balanced")
        self.assertEqual(normalized["steps"], 8)
        self.assertEqual(normalized["weight_profile"], "full")
        self.assertEqual(normalized["lora_name"], DUAL_ACCEL_LORA_NAME)
        self.assertEqual(normalized["lora_strength"], 1.0)
        self.assertEqual(normalized["sampler_name"], "res_multistep")

    def test_director_accel_keeps_its_sampling_without_turbo_lora(self) -> None:
        normalized = normalize_options(JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V, {"refine_enabled": True})
        self.assertEqual(normalized["quality"], "0.4")
        self.assertEqual(normalized["speed"], "balanced")
        self.assertEqual(normalized["steps"], 20)
        self.assertEqual(normalized["weight_profile"], "pruned")
        self.assertEqual(normalized["lora_strength"], 0.0)
        self.assertEqual(normalized["sampler_name"], "res_multistep")
        self.assertTrue(normalized["sage_allow_compile"])

    def test_refine_locks_t8_first_pass_steps(self) -> None:
        multirate = normalize_options(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
            {"refine_enabled": True, "aspect_ratio": "16:9 (Widescreen)", "video_steps": 12, "audio_steps": 12},
        )
        self.assertEqual(multirate["quality"], "0.4")
        self.assertEqual(multirate["megapixels"], 0.4)
        self.assertEqual(multirate["video_steps"], 8)
        self.assertEqual(multirate["audio_steps"], 10)
        self.assertEqual(multirate["weight_profile"], "full")
        self.assertEqual(multirate["lora_name"], H3_TURBO_LORA_NAME)
        self.assertEqual(multirate["lora_strength"], 1.0)

        dual_clock = normalize_options(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK,
            {"refine_enabled": True, "aspect_ratio": "16:9 (Widescreen)", "steps": 6},
        )
        self.assertEqual(dual_clock["quality"], "0.4")
        self.assertEqual(dual_clock["steps"], 8)

    def test_refine_ignores_conflicting_first_pass_choices(self) -> None:
        director = normalize_options(
            JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V,
            {"refine_enabled": True, "weight_profile": "full", "speed": "quality", "steps": 25},
        )
        self.assertEqual(director["weight_profile"], "pruned")
        self.assertEqual(director["speed"], "balanced")
        self.assertEqual(director["steps"], 20)
        self.assertEqual(director["video_steps"], 20)
        self.assertEqual(director["audio_steps"], 20)
        self.assertEqual(director["lora_strength"], 0.0)

        lightx2v = normalize_options(
            JobMode.MINIMAX_H3_LIGHTX2V_I2V,
            {"refine_enabled": True, "weight_profile": "pruned", "speed": "quality", "steps": 25},
        )
        self.assertEqual(lightx2v["weight_profile"], "full")
        self.assertEqual(lightx2v["speed"], "fast")
        self.assertEqual(lightx2v["steps"], 4)
        self.assertEqual(lightx2v["lora_name"], LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(lightx2v["lora_strength"], 0.75)

        dual = normalize_options(
            JobMode.MINIMAX_H3_DUAL_ACCEL_T2V,
            {"refine_enabled": True, "weight_profile": "pruned", "speed": "quality", "steps": 25},
        )
        self.assertEqual(dual["weight_profile"], "full")
        self.assertEqual(dual["speed"], "balanced")
        self.assertEqual(dual["steps"], 8)
        self.assertEqual(dual["lora_name"], DUAL_ACCEL_LORA_NAME)
        self.assertEqual(dual["lora_strength"], 1.0)


class FamilyRefineGraphTests(unittest.TestCase):
    def options(self, mode: JobMode, raw=None):
        return normalize_options(mode, t8_aspect(mode, {"refine_enabled": True, **(raw or {})}))

    def test_reference_groups_supply_required_sizing_for_every_family(self) -> None:
        modes = (
            JobMode.MINIMAX_H3_R2V,
            JobMode.MINIMAX_H3_LIGHTX2V_R2V,
            JobMode.MINIMAX_H3_DUAL_ACCEL_R2V,
            JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V,
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
        )
        references = [f"reference-{index}.png" for index in range(1, 8)]
        for mode in modes:
            with self.subTest(mode=mode.value):
                options = self.options(mode)
                expected = options.get("reference_image_size", options.get("ref_image_size", "match"))
                graph = build_minimax_h3_refine_workflow(mode, "Use <Picture 1>.", references, options, 7)
                group = graph["30"]["inputs"]
                self.assertEqual(graph["30"]["class_type"], "MiniMaxH3DirectorGroupReferenceToVideo")
                self.assertTrue({"prompt", "duration_sec", "ref_image_size"}.issubset(group))
                self.assertEqual(group["ref_image_size"], expected)
                for index, reference in enumerate(references):
                    image_node = str(20 + index)
                    self.assertEqual(group[f"ref_images.ref_image_{index}"], [image_node, 0])
                    self.assertEqual(graph[image_node]["inputs"]["image"], reference)

    def test_lightx2v_graph_uses_four_step_first_pass_and_h3_sage_only(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_LIGHTX2V_I2V)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_LIGHTX2V_I2V, "A preview.", ["start.png"], options, 7,
        )

        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(graph["15"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(graph["15"]["inputs"]["strength_model"], 0.75)
        self.assertNotIn("16", graph)
        self.assertNotIn("18", graph)
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["12"]["inputs"]["steps"], 4)
        self.assertEqual(graph["12"]["inputs"]["sampler"], "euler")
        self.assertEqual(graph["12"]["inputs"]["width"], 864)
        self.assertEqual(graph["12"]["inputs"]["height"], 480)
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_I2V)
        self.assertEqual(graph["45"]["inputs"]["width"], 1376)
        self.assertEqual(graph["45"]["inputs"]["height"], 768)

    def test_lightx2v_r2v_graph_uses_reference_unet_and_lora(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_LIGHTX2V_R2V)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_LIGHTX2V_R2V, "Use <Picture 1>.", ["character.png"], options, 7,
        )

        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_REF2VA_FULL)
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_REF2V_4STEP_LORA)
        self.assertEqual(graph["30"]["class_type"], "MiniMaxH3DirectorGroupReferenceToVideo")
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_R2V)
        self.assertEqual(graph["44"]["inputs"]["model"], graph["12"]["inputs"]["model"])
        self.assertNotIn("40", graph)

    def test_dual_accel_graph_uses_eight_steps_and_dual_sage(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V)
        graph = build_minimax_h3_refine_workflow(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, "A preview.", [], options, 7)

        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(graph["15"]["inputs"]["lora_name"], DUAL_ACCEL_LORA_NAME)
        self.assertEqual(graph["15"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["16"]["class_type"], "PathchSageAttentionKJ")
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["12"]["inputs"]["steps"], 8)
        self.assertEqual(graph["12"]["inputs"]["sampler"], "res_multistep")

    def test_director_accel_graph_uses_its_own_unet_and_sampling(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V, "Use <Picture 1>.", ["character.png"], options, 7,
        )

        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_REF2VA_PRUNED)
        self.assertNotIn("15", graph)
        self.assertEqual(graph["16"]["class_type"], "PathchSageAttentionKJ")
        self.assertTrue(graph["16"]["inputs"]["allow_compile"])
        self.assertEqual(graph["44"]["inputs"]["model"], graph["12"]["inputs"]["model"])
        self.assertEqual(graph["12"]["inputs"]["steps"], 20)
        self.assertEqual(graph["12"]["inputs"]["sampler"], "res_multistep")
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_R2V)
        self.assertEqual(graph["45"]["inputs"]["width"], 1376)
        self.assertEqual(graph["45"]["inputs"]["height"], 768)

    def test_t8_all_reference_routes_to_director_two_pass_and_drops_t8_sampler(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "A preview.", [], options, 7,
        )

        self.assertEqual(graph["12"]["class_type"], "MiniMaxH3Director")
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(graph["15"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], H3_TURBO_LORA_NAME)
        self.assertNotIn("16", graph)
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["12"]["inputs"]["steps"], 8)
        self.assertEqual(graph["12"]["inputs"]["sampler"], "res_multistep")
        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_T2V)

    def test_t8_dual_clock_routes_one_reference_to_i2v(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "A preview.", ["start.png"], options, 7,
        )

        self.assertEqual(graph["12"]["inputs"]["task_type"], TASK_TYPE_I2V)
        self.assertEqual(graph["30"]["inputs"]["first_frame"], ["20", 0])
        self.assertEqual(graph["12"]["inputs"]["steps"], 8)

    def test_t8_first_pass_ignores_user_step_overrides(self) -> None:
        options = self.options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"video_steps": 12, "audio_steps": 12})
        self.assertEqual(first_pass_steps(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, options), 8)
        graph = build_minimax_h3_refine_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "A preview.", [], options, 7,
        )
        self.assertEqual(graph["12"]["inputs"]["steps"], 8)


class RefineHelperTests(unittest.TestCase):
    def test_first_pass_lora(self) -> None:
        self.assertEqual(first_pass_lora(4), LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(first_pass_lora(4, is_reference=True), LIGHTX2V_REF2V_4STEP_LORA)
        self.assertEqual(first_pass_lora(8), LIGHTX2V_FL2V_8STEP_LORA)
        self.assertEqual(first_pass_lora(8, is_reference=True), LIGHTX2V_FL2V_8STEP_LORA)
        self.assertIsNone(first_pass_lora(20))

    def test_first_pass_task_type_routes_each_family(self) -> None:
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_T2V, []), TASK_TYPE_T2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_I2V, ["a.png"]), TASK_TYPE_I2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_I2V, ["a.png", "b.png"]), TASK_TYPE_FL2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_R2V, ["a.png"]), TASK_TYPE_R2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, []), TASK_TYPE_T2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, ["a.png"]), TASK_TYPE_R2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, []), TASK_TYPE_T2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, ["a.png"]), TASK_TYPE_I2V)
        self.assertEqual(first_pass_task_type(JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V, ["a.png"]), TASK_TYPE_R2V)

    def test_first_pass_unet_follows_locked_family_settings(self) -> None:
        lightx2v = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_T2V, {"refine_enabled": True})
        self.assertEqual(first_pass_unet(JobMode.MINIMAX_H3_LIGHTX2V_T2V, TASK_TYPE_T2V, lightx2v), H3_FL2VA_FULL)
        overridden = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_T2V, {"refine_enabled": True, "speed": "quality"})
        self.assertEqual(overridden["speed"], "fast")
        self.assertEqual(first_pass_unet(JobMode.MINIMAX_H3_LIGHTX2V_T2V, TASK_TYPE_T2V, overridden), H3_FL2VA_FULL)
        director = normalize_options(JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V, {"refine_enabled": True})
        self.assertEqual(first_pass_unet(JobMode.MINIMAX_H3_DIRECTOR_ACCEL_R2V, TASK_TYPE_R2V, director), H3_REF2VA_PRUNED)

    def test_numeric_aspect_ratio_strips_t8_labels(self) -> None:
        self.assertEqual(numeric_aspect_ratio({"aspect_ratio": "16:9 (Widescreen)"}), "16:9")
        self.assertEqual(numeric_aspect_ratio({"aspect_ratio": " 9:16 "}), "9:16")
        self.assertEqual(numeric_aspect_ratio({}), "16:9")

    def test_refine_tiling_scales_with_clip_length(self) -> None:
        self.assertEqual(refine_tiling(56), (False, 2))
        self.assertEqual(refine_tiling(124), (False, 2))
        self.assertEqual(refine_tiling(191), (False, 2))
        self.assertEqual(refine_tiling(192), (True, 2))
        self.assertEqual(refine_tiling(243), (True, 2))
        self.assertEqual(refine_tiling(244), (True, 4))
        self.assertEqual(refine_tiling(328), (True, 4))

    def test_refine_target_megapixels_stays_under_the_frames_budget(self) -> None:
        self.assertEqual(refine_target_megapixels("2.0", 56), 2.0)
        self.assertEqual(refine_target_megapixels("2.0", 124), 1.6)
        self.assertEqual(refine_target_megapixels("1.0", 124), 1.0)
        self.assertEqual(refine_target_megapixels("1.0", 192), 1.0)
        self.assertEqual(refine_target_megapixels("2.0", 328), 0.6)
        self.assertEqual(refine_target_megapixels("1.0", 328), 0.6)
        self.assertEqual(refine_target_megapixels("1.0", 362), 0.5)
        self.assertEqual(refine_target_megapixels("1.0", 2000), 0.4)
        self.assertEqual(refine_target_megapixels("1.0", 328, force=True), 1.0)
        self.assertEqual(refine_target_megapixels("2.0", 328, force=True), 2.0)

    def test_normalized_options_echo_the_capped_refine_megapixels(self) -> None:
        for mode in sorted(H3_WORKFLOWS, key=lambda item: item.value):
            with self.subTest(mode=mode.value):
                long_clip = normalize_options(
                    mode, t8_aspect(mode, {"refine_enabled": True, "refine_quality": "1.0", "duration": 13}),
                )
                self.assertEqual(long_clip["refine_quality"], "1.0")
                self.assertEqual(long_clip["refine_quality_mode"], "auto")
                self.assertEqual(long_clip["refine_megapixels"], 0.6)
                forced_clip = normalize_options(
                    mode,
                    t8_aspect(mode, {
                        "refine_enabled": True, "refine_quality": "1.0", "refine_quality_mode": "force", "duration": 13,
                    }),
                )
                self.assertEqual(forced_clip["refine_megapixels"], 1.0)
                short_clip = normalize_options(
                    mode, t8_aspect(mode, {"refine_enabled": True, "refine_quality": "1.0", "duration": 5}),
                )
                self.assertEqual(short_clip["refine_megapixels"], 1.0)
                disabled = normalize_options(mode, t8_aspect(mode, {"duration": 13}))
                self.assertNotIn("refine_megapixels", disabled)

    def test_non_h3_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported H3 refine"):
            build_minimax_h3_refine_workflow(
                JobMode.WAN_VACE_DEPTH_V2V,
                "A preview.",
                [],
                {},
                7,
            )


class ConfirmedVideoResolutionTests(unittest.TestCase):
    @staticmethod
    def apply(resolution: str, options: dict) -> dict:
        settings = {"extra": {"video_resolution": resolution}} if resolution else {}
        with patch(
            "backend.app.media_studio.services.episode_video_service.query_one",
            return_value={"settings_json": json.dumps(settings)},
        ):
            return EpisodeVideoService.apply_confirmed_video_resolution("p", options)

    def test_768p_locks_requested_quality(self) -> None:
        options = self.apply("768p", {"workflow": "minimax-h3-director-accel-r2v", "quality": "0.4", "aspect_ratio": "9:16"})
        self.assertEqual(options["quality"], "0.98")

    def test_2k_locks_requested_quality(self) -> None:
        options = self.apply("2k", {"workflow": "minimax-h3-director-accel-r2v", "quality": "0.4"})
        self.assertEqual(options["quality"], "2.0")

    def test_refine_uses_confirmed_resolution_target(self) -> None:
        options = self.apply("768p", {"workflow": "minimax-h3-director-accel-r2v", "refine_enabled": True, "refine_quality": "2.0"})
        self.assertEqual(options["refine_quality"], "1.0")
        self.assertNotIn("quality", options)

    def test_workflow_with_lower_ceiling_uses_highest_preset(self) -> None:
        options = self.apply("2k", {"workflow": "minimax-h3-t8-all-reference", "quality": "0.4"})
        self.assertEqual(options["quality"], "0.98")

    def test_no_confirmed_resolution_keeps_incoming_options(self) -> None:
        options = self.apply("", {"workflow": "minimax-h3-director-accel-r2v", "quality": "0.4"})
        self.assertEqual(options["quality"], "0.4")


if __name__ == "__main__":
    unittest.main()
