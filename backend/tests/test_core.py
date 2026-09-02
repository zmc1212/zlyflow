from __future__ import annotations

import tempfile
import unittest
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import local_video_studio as legacy

from backend.app.auth import AuthStore, csrf_token, validate_password, verify_password
from backend.app.config import Settings
from backend.app.models import JobMode, JobStatus
from backend.app.main import BROWSER_LOCAL_COMFY_VIEW_URL, DesktopDeliveryTickets, app, browser_direct_view_url, clear_login_failures_for_username, current_user, login_failures, output_response, public_job, _image_media_type
from backend.app.comfy_service import ComfyQueuePrompt, ComfyService, ComfyUnavailable, interpret_comfy_progress, resolve_minimax_picture_prompt, resolve_reference_prompt
from backend.app.minimax_h3_dual_accel_workflow import build_minimax_h3_dual_accel_workflow
from backend.app.minimax_h3_lightx2v_workflow import build_minimax_h3_lightx2v_workflow
from backend.app.minimax_h3_workflow import build_minimax_h3_workflow
from backend.app.minimax_h3_t8_workflow import build_minimax_h3_t8_workflow
from backend.app.storage import JobStore
from backend.app.resource_storage import BrowserLocalStagingStorage, BrowserStreamStorage, create_resource_storage
from backend.app.models import UserRole
from backend.app.worker import JobWorker
from backend.app.workflow_registry import (
    CATALOG_GROUP_CUSTOM, CATALOG_GROUP_DUAL_ACCEL, CATALOG_GROUP_LIGHTX2V, CATALOG_GROUP_OFFICIAL_H3,
    DUAL_ACCEL_LORA_NAME, H3_FL2VA_FULL, H3_FL2VA_PRUNED, H3_REF2VA_FULL, H3_REF2VA_PRUNED, LIGHTX2V_FL2V_4STEP_LORA,
    LIGHTX2V_FL2V_8STEP_LORA, LIGHTX2V_REF2V_4STEP_LORA, WORKFLOWS, generation_output_label,
    generation_stage, h3_dimensions, h3_length, normalize_options, validate_option_relationships,
    validate_references, workflow_for,
)


class WorkflowTests(unittest.TestCase):
    def test_reference_tokens_are_resolved_before_generation(self) -> None:
        prompt = resolve_reference_prompt("让 @图2 站在 @图1 中，采用 @图3 色调", 3)
        self.assertNotIn("@图", prompt)
        self.assertIn("主体参考图", prompt)
        self.assertIn("参考图约束", prompt)
        with self.assertRaises(legacy.ComfyError):
            resolve_reference_prompt("使用 @图2", 1)

    def test_minimax_picture_aliases_are_converted_and_missing_tags_are_injected(self) -> None:
        prompt = resolve_minimax_picture_prompt("让 @图片2 走进 @图片1 的场景。", 2)
        self.assertEqual(prompt, "让 <Picture 2> 走进 <Picture 1> 的场景。")
        injected = resolve_minimax_picture_prompt("雨夜城市中一辆汽车驶过霓虹灯", 2)
        self.assertIn("<Picture 1>", injected)
        self.assertIn("<Picture 2>", injected)
        self.assertNotIn("场景参考图", resolve_minimax_picture_prompt("@图片1 中的角色转身离开。", 1))
        with self.assertRaises(legacy.ComfyError):
            resolve_minimax_picture_prompt("使用 <Picture 3>", 1)

    def test_image_workflow_replaces_prompt_size_and_seed(self) -> None:
        workflow = legacy.build_text_to_image_workflow("测试提示词", "不要水印", "横版 1280 x 720")
        self.assertEqual(workflow[legacy.T2I_PROMPT_NODE]["inputs"]["text"], "测试提示词")
        self.assertEqual(workflow[legacy.T2I_NEGATIVE_PROMPT_NODE]["inputs"]["text"], "不要水印")
        self.assertEqual(workflow[legacy.T2I_LATENT_NODE]["inputs"]["width"], 1280)
        self.assertEqual(workflow[legacy.T2I_LATENT_NODE]["inputs"]["height"], 720)
        self.assertIsInstance(workflow[legacy.T2I_SEED_NODE]["inputs"]["seed"], int)

    def test_video_workflows_preserve_output_nodes(self) -> None:
        flux = legacy.build_flux_workflow(("a.png", "b.png", "c.png"), "首帧")
        ltx = legacy.build_ltx_workflow("frame.png", "运镜")
        vace = legacy.build_vace_multi_reference_workflow(("a.png", "b.png", "c.png"), "视频")
        self.assertEqual(flux[legacy.FLUX_OUTPUT_NODE]["class_type"], "SaveImage")
        self.assertEqual(ltx[legacy.LTX_IMAGE_NODE]["inputs"]["image"], "frame.png")
        self.assertIn(legacy.VACE_OUTPUT_NODE, vace)

    def test_vace_workflow_uses_the_multi_reference_node_contract(self) -> None:
        workflow = legacy.build_vace_multi_reference_workflow(("scene.png", "subject.png", "style.png"), "video")
        vace_node = workflow["12"]
        self.assertEqual(vace_node["class_type"], "WanVaceMultiReference")
        self.assertEqual(vace_node["inputs"]["reference_images"], ["11", 0])
        self.assertNotIn("reference_image", vace_node["inputs"])
        self.assertEqual(workflow["2"]["inputs"]["shift"], 16.0)
        self.assertEqual(workflow["13"]["inputs"]["steps"], 50)
        self.assertEqual(workflow["13"]["inputs"]["cfg"], 5.0)

    def test_legacy_workflows_are_not_registered_or_accepted(self) -> None:
        registered = {workflow.id for workflow in WORKFLOWS}
        self.assertNotIn(JobMode.IMAGE, registered)
        self.assertNotIn(JobMode.LTX_VIDEO, registered)
        self.assertNotIn(JobMode.VACE_VIDEO, registered)
        with self.assertRaisesRegex(ValueError, "已从当前工作台移除"):
            validate_references(JobMode.IMAGE, [])

    def test_minimax_h3_reference_workflow_grows_with_uploaded_images(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "16:9", "quality": "0.98", "duration": 5})
        workflow = build_minimax_h3_workflow(
            JobMode.MINIMAX_H3_R2V,
            "Use <Picture 1> and <Picture 2>.",
            ["character.png", "scene.png"],
            options,
            42,
        )
        self.assertEqual(h3_dimensions(options), (1344, 768))
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(workflow["5"]["inputs"]["width"], 1344)
        self.assertEqual(workflow["5"]["inputs"]["height"], 768)
        self.assertEqual(workflow["5"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
        self.assertEqual(workflow["5"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
        self.assertEqual(workflow["14"]["class_type"], "SaveVideo")
        self.assertEqual(options["speed"], "balanced")
        self.assertEqual(workflow["7"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], H3_REF2VA_FULL)
        self.assertEqual(workflow["15"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(workflow["16"]["class_type"], "ReservedVRAMSetter")
        self.assertEqual(workflow["16"]["inputs"]["reserved"], 3.0)
        self.assertTrue(workflow["16"]["inputs"]["clean_gpu_before"])
        self.assertEqual(workflow["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(workflow["6"]["inputs"]["model"], ["17", 0])
        quality = normalize_options(JobMode.MINIMAX_H3_R2V, {"speed": "quality", "duration": 5})
        quality_graph = build_minimax_h3_workflow(
            JobMode.MINIMAX_H3_R2V, "Use <Picture 1>.", ["character.png"], quality, 42,
        )
        self.assertEqual(quality_graph["1"]["inputs"]["unet_name"], H3_REF2VA_PRUNED)
        self.assertNotIn("15", quality_graph)

    def test_minimax_h3_accepts_arbitrary_positive_aspect_ratios(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "2:3", "quality": "0.98", "duration": 5})
        self.assertEqual(options["aspect_ratio"], "2:3")
        self.assertEqual(h3_dimensions(options), (832, 1248))
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_R2V, {"aspect_ratio": "2:0"})
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_R2V, {"unrecognized": True})

    def test_standard_h3_uses_the_official_two_megapixel_ceiling_without_a_local_canvas_cap(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T2V, {"aspect_ratio": "16:9", "quality": "2.0"})
        self.assertEqual(options["megapixels"], 2.0)
        self.assertEqual(h3_dimensions(options), (1920, 1088))

    def test_standard_h3_dimensions_match_comfyui_resolution_selector(self) -> None:
        expected_sizes = {
            "0.2": (608, 352),
            "0.7": (1152, 640),
            "0.98": (1344, 768),
            "1.0": (1376, 768),
            "2.0": (1920, 1088),
        }
        for quality, expected in expected_sizes.items():
            options = normalize_options(JobMode.MINIMAX_H3_T2V, {"aspect_ratio": "16:9", "quality": quality})
            self.assertEqual(h3_dimensions(options), expected)

    def test_minimax_h3_quality_presets_map_to_internal_megapixels_and_accept_legacy_mp(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T2V, {"quality": "0.98"})
        self.assertEqual(options["quality"], "0.98")
        self.assertEqual(options["megapixels"], 0.98)
        legacy = normalize_options(JobMode.MINIMAX_H3_T2V, {"megapixels": 0.3})
        self.assertEqual(legacy["quality"], "0.3")
        self.assertEqual(legacy["megapixels"], 0.3)
        legacy_named = normalize_options(JobMode.MINIMAX_H3_T2V, {"quality": "2K"})
        self.assertEqual(legacy_named["quality"], "0.3")
        self.assertEqual(legacy_named["megapixels"], 0.3)

    def test_minimax_h3_image_to_video_uses_first_and_last_frame(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_I2V, {})
        workflow = build_minimax_h3_workflow(JobMode.MINIMAX_H3_I2V, "Camera slowly pulls back.", ["start.png", "end.png"], options, 42)
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(workflow["5"]["inputs"]["first_frame"], ["20", 0])
        self.assertEqual(workflow["5"]["inputs"]["last_frame"], ["21", 0])
        with self.assertRaises(ValueError):
            validate_references(JobMode.MINIMAX_H3_R2V, [])

    def test_official_h3_reserves_vram_and_patches_sage_by_default(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_I2V, {})
        self.assertTrue(options["use_sage_attention"])
        graph = build_minimax_h3_workflow(
            JobMode.MINIMAX_H3_I2V, "Camera slowly pulls back.", ["start.png", "end.png"], options, 42,
        )
        self.assertEqual(graph["16"]["class_type"], "ReservedVRAMSetter")
        self.assertEqual(graph["16"]["inputs"]["anything"], ["15", 0])
        self.assertEqual(graph["16"]["inputs"]["reserved"], 3.0)
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["17"]["inputs"]["model"], ["16", 0])
        self.assertEqual(graph["6"]["inputs"]["model"], ["17", 0])
        disabled = normalize_options(JobMode.MINIMAX_H3_T2V, {"use_sage_attention": False})
        disabled_graph = build_minimax_h3_workflow(JobMode.MINIMAX_H3_T2V, "A preview.", [], disabled, 42)
        self.assertNotIn("17", disabled_graph)
        self.assertEqual(disabled_graph["6"]["inputs"]["model"], ["16", 0])

    def test_h3_duration_two_seconds_maps_to_aligned_frames(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T2V, {"duration": 2})
        self.assertEqual(options["duration"], 2)
        self.assertEqual(h3_length(options), 56)
        workflow = build_minimax_h3_workflow(JobMode.MINIMAX_H3_T2V, "A short beat.", [], options, 42)
        self.assertEqual(workflow["5"]["inputs"]["length"], 56)
        t8_options = normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {"duration": 2})
        t8 = build_minimax_h3_t8_workflow(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "A short beat.", [], t8_options)
        self.assertEqual(t8["3"]["inputs"]["length"], 56)
        with self.assertRaisesRegex(ValueError, "时长必须在 2 到 15 秒"):
            normalize_options(JobMode.MINIMAX_H3_T2V, {"duration": 1})
        with self.assertRaisesRegex(ValueError, "不能小于 2"):
            normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"duration": 1})

    def test_h3_speed_preset_maps_to_turbo_lora_and_steps(self) -> None:
        fast = normalize_options(JobMode.MINIMAX_H3_T2V, {"speed": "fast"})
        self.assertEqual(fast["speed"], "fast")
        self.assertEqual(fast["steps"], 4)
        self.assertEqual(fast["lora_strength"], 1.0)
        fast_graph = build_minimax_h3_workflow(JobMode.MINIMAX_H3_T2V, "A preview.", [], fast, 42)
        self.assertEqual(fast_graph["7"]["inputs"]["steps"], 4)
        self.assertEqual(fast_graph["1"]["inputs"]["unet_name"], "minimax_h3_fl2va_int8_convrot.safetensors")
        self.assertEqual(fast_graph["15"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(fast_graph["15"]["inputs"]["lora_name"], "minimax_h3_turbo_4STEPS_comfyui.safetensors")
        self.assertEqual(fast_graph["15"]["inputs"]["strength_model"], 1.0)

        quality = normalize_options(JobMode.MINIMAX_H3_T2V, {"speed": "quality"})
        self.assertEqual(quality["steps"], 20)
        self.assertEqual(quality["lora_strength"], 0.0)
        quality_graph = build_minimax_h3_workflow(JobMode.MINIMAX_H3_T2V, "A final pass.", [], quality, 42)
        self.assertEqual(quality_graph["7"]["inputs"]["steps"], 20)
        self.assertNotIn("15", quality_graph)
        self.assertEqual(quality_graph["16"]["inputs"]["anything"], ["1", 0])
        self.assertEqual(quality_graph["6"]["inputs"]["model"], ["17", 0])

        t8_fast = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "fast"})
        self.assertEqual(t8_fast["video_steps"], 4)
        self.assertEqual(t8_fast["audio_steps"], 4)
        t8_fast_graph = build_minimax_h3_t8_workflow(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "A preview.", [], t8_fast)
        self.assertEqual(t8_fast_graph["8"]["inputs"]["video_steps"], 4)
        self.assertEqual(t8_fast["unet_name"], "minimax_h3_fl2va_int8_convrot.safetensors")
        self.assertEqual(t8_fast_graph["16"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(t8_fast_graph["16"]["inputs"]["strength_model"], 1.0)

        t8_quality = normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {"speed": "quality"})
        self.assertEqual(t8_quality["steps"], 20)
        self.assertEqual(t8_quality["lora_strength"], 0.0)
        t8_quality_graph = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "A final pass.", [], t8_quality,
        )
        self.assertNotIn("16", t8_quality_graph)
        self.assertEqual(t8_quality_graph["1"]["inputs"]["unet_name"], H3_FL2VA_PRUNED)
        self.assertEqual(t8_quality_graph["8"]["inputs"]["model"], ["15", 0])

        t8_quality_ref = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "quality"})
        self.assertEqual(t8_quality_ref["video_steps"], 20)
        self.assertEqual(t8_quality_ref["audio_steps"], 20)
        self.assertEqual(t8_quality_ref["lora_strength"], 0.0)
        t8_balanced = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "balanced"})
        self.assertEqual(t8_balanced["video_steps"], 8)
        self.assertEqual(t8_balanced["audio_steps"], 10)

        t8_custom = normalize_options(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "custom", "custom_steps": 6},
        )
        self.assertEqual(t8_custom["video_steps"], 6)
        self.assertEqual(t8_custom["audio_steps"], 6)
        self.assertEqual(t8_custom["lora_strength"], 1.0)
        t8_custom_graph = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "A custom pass.", [], t8_custom,
        )
        self.assertEqual(t8_custom_graph["8"]["inputs"]["video_steps"], 6)
        self.assertEqual(t8_custom_graph["8"]["inputs"]["audio_steps"], 6)

        t8_custom_high = normalize_options(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "custom", "custom_steps": 12},
        )
        self.assertEqual(t8_custom_high["video_steps"], 12)
        self.assertEqual(t8_custom_high["lora_strength"], 0.0)
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_T2V, {"speed": "turbo"})
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "custom", "custom_steps": 0})
        with self.assertRaises(ValueError):
            normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "custom", "custom_steps": 41})

    def test_weight_profile_pruned_keeps_steps_and_skips_turbo_lora(self) -> None:
        cases = [
            (JobMode.MINIMAX_H3_T2V, {"speed": "fast", "weight_profile": "pruned"}, build_minimax_h3_workflow, H3_FL2VA_PRUNED, 4),
            (JobMode.MINIMAX_H3_LIGHTX2V_T2V, {"speed": "fast", "weight_profile": "pruned"}, build_minimax_h3_lightx2v_workflow, H3_FL2VA_PRUNED, 4),
            (JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, {"speed": "balanced", "weight_profile": "pruned"}, build_minimax_h3_dual_accel_workflow, H3_FL2VA_PRUNED, 8),
        ]
        for mode, raw, builder, unet, steps in cases:
            options = normalize_options(mode, raw)
            self.assertEqual(options["weight_profile"], "pruned")
            self.assertEqual(options["steps"], steps)
            self.assertEqual(options["lora_strength"], 0.0)
            graph = builder(mode, "A memory-safe pass.", [], options, 11)
            self.assertEqual(graph["1"]["inputs"]["unet_name"], unet)
            self.assertNotIn("15", graph)

        t8 = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "fast", "weight_profile": "pruned"})
        self.assertEqual(t8["video_steps"], 4)
        self.assertEqual(t8["lora_strength"], 0.0)
        self.assertEqual(t8["unet_name"], H3_FL2VA_PRUNED)
        t8_graph = build_minimax_h3_t8_workflow(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "A memory-safe pass.", [], t8)
        self.assertEqual(t8_graph["1"]["inputs"]["unet_name"], H3_FL2VA_PRUNED)
        self.assertNotIn("16", t8_graph)
        t8_ref = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "balanced", "weight_profile": "pruned"})
        t8_ref_graph = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "Use <Picture 1>.", ["character.png"], t8_ref,
        )
        self.assertEqual(t8_ref_graph["1"]["inputs"]["unet_name"], H3_REF2VA_PRUNED)
        self.assertNotIn("16", t8_ref_graph)
        official = normalize_options(JobMode.MINIMAX_H3_T2V, {"speed": "fast"})
        self.assertEqual(official["weight_profile"], "full")
        with self.assertRaisesRegex(ValueError, "模型体积"):
            normalize_options(JobMode.MINIMAX_H3_T2V, {"weight_profile": "tiny"})

    def test_t8_all_reference_builds_multirate_graph_and_grows_references(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"quality": "0.98"})
        workflow = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
            "Use <Picture 1> and <Picture 2>.",
            ["character.png", "scene.png"],
            options,
        )
        self.assertEqual(workflow["8"]["class_type"], "MiniMaxH3MultiRateSamplerEXPT8")
        self.assertEqual(workflow["8"]["inputs"]["video_steps"], 8)
        self.assertEqual(workflow["8"]["inputs"]["audio_steps"], 10)
        self.assertEqual(workflow["7"]["inputs"]["megapixels"], 0.98)
        self.assertEqual(workflow["3"]["inputs"]["task_type"], "Ref2VA")
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], H3_REF2VA_FULL)
        self.assertEqual(workflow["3"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
        self.assertEqual(workflow["3"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
        self.assertEqual(workflow["16"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(workflow["8"]["inputs"]["model"], ["16", 0])
        quality_ref = normalize_options(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, {"speed": "quality"})
        quality_ref_graph = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_ALL_REFERENCE,
            "Use <Picture 1>.",
            ["character.png"],
            quality_ref,
        )
        self.assertEqual(quality_ref_graph["1"]["inputs"]["unet_name"], H3_REF2VA_PRUNED)
        self.assertNotIn("16", quality_ref_graph)
        self.assertEqual(workflow["14"]["class_type"], "VHS_VideoCombine")
        self.assertTrue(workflow["14"]["inputs"]["save_output"])
        empty = build_minimax_h3_t8_workflow(JobMode.MINIMAX_H3_T8_ALL_REFERENCE, "Rain.", [], options)
        self.assertEqual(empty["3"]["inputs"]["task_type"], "T2VA")
        self.assertEqual(empty["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(empty["16"]["class_type"], "LoraLoaderBypassModelOnly")

    def test_t8_dual_clock_builds_source_sampler_contract(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {"quality": "0.98"})
        workflow = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "Rain on a roof.", [], options,
        )
        self.assertEqual(workflow["8"]["class_type"], "MiniMaxH3DualClockSamplerT8")
        self.assertEqual(workflow["8"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["7"]["inputs"]["megapixels"], 0.98)
        self.assertEqual(workflow["3"]["inputs"]["task_type"], "T2VA")
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], "minimax_h3_fl2va_int8_convrot.safetensors")
        self.assertEqual(workflow["16"]["class_type"], "LoraLoaderBypassModelOnly")

    def test_t8_dual_clock_single_reference_uses_i2va_first_frame(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {"speed": "fast"})
        workflow = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "A forest path.", ["start.png"], options,
        )
        self.assertEqual(workflow["3"]["inputs"]["task_type"], "I2VA")
        self.assertEqual(workflow["3"]["inputs"]["first_frame"], ["20", 0])
        self.assertNotIn("ref_images.ref_image_0", workflow["3"]["inputs"])
        self.assertEqual(workflow["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(workflow["16"]["class_type"], "LoraLoaderBypassModelOnly")
        self.assertEqual(workflow["8"]["inputs"]["steps"], 4)
        options_without_task_type = dict(options)
        options_without_task_type.pop("task_type", None)
        recovered = build_minimax_h3_t8_workflow(
            JobMode.MINIMAX_H3_T8_DUAL_CLOCK, "A forest path.", ["start.png"], options_without_task_type,
        )
        self.assertEqual(recovered["3"]["inputs"]["task_type"], "I2VA")

    def test_t8_options_validate_ranges_and_cross_field_rules(self) -> None:
        mode = JobMode.MINIMAX_H3_T8_ALL_REFERENCE
        normalized = normalize_options(mode, {"quality": "0.98", "video_steps": 6, "audio_steps": 8})
        self.assertEqual(normalized["quality"], "0.98")
        self.assertEqual(normalized["megapixels"], 0.98)
        self.assertEqual(normalize_options(mode, {})["quality"], "0.4")
        self.assertEqual(normalize_options(JobMode.MINIMAX_H3_T8_DUAL_CLOCK, {})["quality"], "0.7")
        self.assertEqual(normalized["video_steps"], 6)
        self.assertIsInstance(normalized["seed"], int)
        self.assertNotEqual(normalized["seed"], 123456789)
        self.assertNotEqual(normalized["seed"], normalize_options(mode, {"quality": "0.98"})["seed"])
        with self.assertRaises(ValueError):
            normalize_options(mode, {"audio_steps": 3, "video_steps": 4})
        with self.assertRaises(ValueError):
            normalize_options(mode, {"save_output": False})
        with self.assertRaises(ValueError):
            validate_option_relationships(mode, normalize_options(mode, {"task_type": "Ref2VA"}), 0)

    def test_generation_stage_follows_workflow_family(self) -> None:
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_LIGHTX2V_I2V), "LightX2V 正在生成视频")
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_LIGHTX2V_T2V), "LightX2V 正在生成视频")
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_LIGHTX2V_R2V), "LightX2V 正在生成视频")
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V), "八步双加速 正在生成视频")
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_I2V), "MiniMax H3 正在生成视频")
        self.assertEqual(generation_stage(JobMode.MINIMAX_H3_T8_DUAL_CLOCK), "MiniMax H3 正在生成视频")
        self.assertEqual(generation_output_label(JobMode.MINIMAX_H3_LIGHTX2V_I2V), "LightX2V 视频")
        self.assertEqual(generation_output_label(JobMode.MINIMAX_H3_DUAL_ACCEL_I2V), "八步双加速 视频")
        self.assertEqual(generation_output_label(JobMode.MINIMAX_H3_T2V), "MiniMax H3 视频")

    def test_resolve_director_workflow_uses_family_then_route(self) -> None:
        from backend.app.workflow_registry import resolve_director_workflow

        self.assertEqual(resolve_director_workflow(None, "t2v"), "minimax-h3-t2v")
        self.assertEqual(resolve_director_workflow("", "r2v"), "minimax-h3-r2v")
        self.assertEqual(resolve_director_workflow("lightx2v", "r2v"), "minimax-h3-lightx2v-r2v")
        self.assertEqual(resolve_director_workflow("dual_accel", "i2v"), "minimax-h3-dual-accel-i2v")
        self.assertEqual(resolve_director_workflow("unknown-family", "t2v"), "minimax-h3-t2v")


class ApiDocumentationTests(unittest.TestCase):
    def test_openapi_schema_contains_all_public_api_operations(self) -> None:
        schema = app.openapi()
        self.assertEqual(schema["info"]["title"], "ZLY AI 视频创作平台 API")
        self.assertIn("局域网 IPv4", schema["info"]["description"])
        self.assertIn("/api/jobs", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/references/{reference_index}", schema["paths"])
        self.assertIn("/api/auth/login", schema["paths"])
        self.assertIn("/api/admin/users", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/retry", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/cancel", schema["paths"])
        self.assertIn("/api/jobs/{job_id}/outputs/{output_index}/desktop-ticket", schema["paths"])
        self.assertIn("/api/modes/{mode_id}", schema["paths"])
        self.assertIn("/api/providers/grs/balance", schema["paths"])
        self.assertIn("/api/admin/providers/comfy", schema["paths"])
        balance_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/providers/grs/balance")
        self.assertIn(current_user, [dependency.call for dependency in balance_route.dependant.dependencies])
        self.assertIn("multipart/form-data", schema["paths"]["/api/jobs"]["post"]["requestBody"]["content"])
        self.assertIn("/api/openapi.json", app.openapi_url)
        self.assertIn("APIKeyCookie", schema["components"]["securitySchemes"])

    def test_openapi_has_chinese_operation_and_field_documentation(self) -> None:
        schema = app.openapi()
        declared_tags = {tag["name"] for tag in schema["tags"]}
        public_without_session = {
            ("get", "/api/health"),
            ("get", "/api/auth/status"),
            ("post", "/api/auth/setup"),
            ("post", "/api/auth/login"),
        }
        for path, path_item in schema["paths"].items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                self.assertTrue(operation.get("summary"), f"{method.upper()} {path} 缺少摘要")
                self.assertTrue(operation.get("description"), f"{method.upper()} {path} 缺少说明")
                self.assertTrue(set(operation.get("tags", [])).issubset(declared_tags))
                if (method, path) not in public_without_session:
                    self.assertEqual(operation.get("security"), [{"APIKeyCookie": []}])
                for parameter in operation.get("parameters", []):
                    self.assertTrue(parameter.get("description"), f"{method.upper()} {path} 参数缺少说明")
        for name, component in schema["components"]["schemas"].items():
            for property_name, property_schema in component.get("properties", {}).items():
                self.assertTrue(
                    property_schema.get("description"),
                    f"{name}.{property_name} 缺少字段说明",
                )
        create_job = schema["paths"]["/api/jobs"]["post"]
        form = create_job["requestBody"]["content"]["multipart/form-data"]
        self.assertIn("example", form)
        self.assertIn("X-CSRF-Token", schema["info"]["description"])

    def test_mode_parameter_schema_is_derived_from_the_registry(self) -> None:
        image_options = {item["name"]: item for item in workflow_for(JobMode.GRS_GPT_IMAGE_2).payload()["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(image_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(image_options["aspect_ratio"]["ui_companion"], "resolution")
        self.assertEqual(image_options["aspect_ratio"]["ui_options"][0], {"value": "auto", "label": "自动"})
        self.assertEqual(image_options["resolution"]["enum"], ["1K"])
        vip_image_options = {item["name"]: item for item in workflow_for(JobMode.GRS_GPT_IMAGE_2_VIP).payload()["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(vip_image_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(vip_image_options["aspect_ratio"]["ui_companion"], "resolution")
        self.assertIn({"value": "1:3", "label": "1:3"}, vip_image_options["aspect_ratio"]["ui_options"])
        self.assertEqual(vip_image_options["resolution"]["enum"], ["1K", "2K", "4K", "CUSTOM"])
        h3 = workflow_for(JobMode.MINIMAX_H3_R2V).payload()
        parameters = {item["name"]: item for item in h3["parameters"]}
        self.assertEqual(parameters["mode"]["values"], ["minimax-h3-r2v"])
        self.assertEqual(parameters["references"]["max_items"], 9)
        self.assertEqual(parameters["options"]["schema"]["properties"]["duration"]["minimum"], 2)
        self.assertEqual(parameters["options"]["schema"]["properties"]["duration"]["maximum"], 15)
        self.assertNotIn("enum", parameters["options"]["schema"]["properties"]["aspect_ratio"])
        self.assertIn("pattern", parameters["options"]["schema"]["properties"]["aspect_ratio"])
        self.assertEqual(parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_companion"], "quality")
        self.assertEqual(
            parameters["options"]["schema"]["properties"]["quality"]["enum"],
            ["0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.98", "1.0", "1.2", "1.5", "1.8", "2.0"],
        )
        self.assertEqual(parameters["options"]["schema"]["properties"]["duration"]["ui_control"], "duration-slider")
        self.assertEqual(parameters["options"]["schema"]["properties"]["speed"]["ui_group"], "primary")
        self.assertEqual(parameters["options"]["schema"]["properties"]["speed"]["enum"], ["fast", "balanced", "quality", "custom"])
        self.assertEqual(parameters["options"]["schema"]["properties"]["speed"]["default"], "balanced")
        self.assertEqual(parameters["options"]["schema"]["properties"]["custom_steps"]["ui_visible_when"], {"speed": "custom"})
        self.assertEqual(parameters["options"]["schema"]["properties"]["custom_steps"]["unit"], "步")
        self.assertEqual(parameters["options"]["schema"]["properties"]["weight_profile"]["ui_group"], "primary")
        self.assertEqual(parameters["options"]["schema"]["properties"]["weight_profile"]["enum"], ["full", "pruned"])
        self.assertEqual(parameters["options"]["schema"]["properties"]["steps"]["ui_group"], "internal")
        self.assertEqual(
            parameters["options"]["schema"]["properties"]["aspect_ratio"]["ui_options"][0],
            {"value": "16:9", "label": "16:9 横屏"},
        )
        t8 = workflow_for(JobMode.MINIMAX_H3_T8_ALL_REFERENCE).payload()
        t8_options = {item["name"]: item for item in t8["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(t8_options["video_steps"]["default"], 8)
        self.assertEqual(t8_options["audio_steps"]["default"], 10)
        self.assertEqual(t8_options["reserved_vram"]["unit"], "GB")
        self.assertIn("output_format", t8_options)
        self.assertTrue(all(option["ui_group"] in {"primary", "advanced", "internal"} for option in t8_options.values()))
        self.assertEqual(t8_options["aspect_ratio"]["ui_control"], "visual-settings")
        self.assertEqual(t8_options["duration"]["minimum"], 2)
        self.assertEqual(t8_options["duration"]["maximum"], 15)
        self.assertEqual(t8_options["duration"]["ui_control"], "duration-slider")
        self.assertEqual(
            {name for name, option in t8_options.items() if option["ui_group"] == "primary"},
            {"aspect_ratio", "duration", "speed", "custom_steps", "weight_profile"},
        )
        self.assertEqual(
            {name for name, option in t8_options.items() if option["ui_group"] == "advanced"},
            {"quality"},
        )
        self.assertEqual(t8_options["megapixels"]["ui_group"], "internal")
        self.assertEqual(t8_options["quality"]["enum"], ["0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.98"])
        dual_t8 = workflow_for(JobMode.MINIMAX_H3_T8_DUAL_CLOCK).payload()
        dual_t8_options = {item["name"]: item for item in dual_t8["parameters"]}["options"]["schema"]["properties"]
        self.assertEqual(dual_t8_options["quality"]["enum"], ["0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.98"])
        self.assertEqual(t8_options["seed"]["ui_group"], "internal")
        self.assertEqual(t8_options["task_type"]["ui_group"], "internal")
        self.assertEqual(t8_options["video_steps"]["ui_group"], "internal")
        self.assertTrue(all(workflow.id.startswith("minimax-h3-") for workflow in WORKFLOWS))
        groups = {workflow.catalog_group: workflow.payload() for workflow in WORKFLOWS}
        self.assertEqual(workflow_for(JobMode.MINIMAX_H3_LIGHTX2V_T2V).catalog_group, CATALOG_GROUP_LIGHTX2V)
        self.assertEqual(workflow_for(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V).catalog_group, CATALOG_GROUP_DUAL_ACCEL)
        self.assertEqual(workflow_for(JobMode.MINIMAX_H3_T2V).catalog_group, CATALOG_GROUP_OFFICIAL_H3)
        self.assertEqual(workflow_for(JobMode.MINIMAX_H3_T8_DUAL_CLOCK).catalog_group, CATALOG_GROUP_CUSTOM)
        self.assertEqual(groups[CATALOG_GROUP_LIGHTX2V]["catalog_group_label"], "LightX2V")
        self.assertEqual(groups[CATALOG_GROUP_DUAL_ACCEL]["catalog_group_label"], "八步双加速")
        self.assertEqual(groups[CATALOG_GROUP_OFFICIAL_H3]["catalog_group_label"], "官方 MiniMax H3")
        self.assertEqual(groups[CATALOG_GROUP_CUSTOM]["catalog_group_label"], "自定义")
        self.assertLess(groups[CATALOG_GROUP_LIGHTX2V]["catalog_group_order"], groups[CATALOG_GROUP_DUAL_ACCEL]["catalog_group_order"])
        self.assertLess(groups[CATALOG_GROUP_DUAL_ACCEL]["catalog_group_order"], groups[CATALOG_GROUP_OFFICIAL_H3]["catalog_group_order"])
        self.assertLess(groups[CATALOG_GROUP_OFFICIAL_H3]["catalog_group_order"], groups[CATALOG_GROUP_CUSTOM]["catalog_group_order"])

    def test_lightx2v_t2v_uses_euler_sigma_shift_and_one_megapixel_defaults(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_T2V, {})
        self.assertEqual(options["quality"], "1.0")
        self.assertEqual(options["megapixels"], 1.0)
        self.assertEqual(options["speed"], "fast")
        self.assertEqual(options["steps"], 4)
        self.assertEqual(options["lora_name"], LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(options["lora_strength"], 0.75)
        self.assertEqual(h3_dimensions(options), (1376, 768))
        graph = build_minimax_h3_lightx2v_workflow(JobMode.MINIMAX_H3_LIGHTX2V_T2V, "A stadium strike.", [], options, 7)
        self.assertEqual(graph["9"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(graph["15"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_FL2V_4STEP_LORA)
        self.assertEqual(graph["16"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(graph["17"]["inputs"]["shift_video"], 12.0)
        self.assertEqual(graph["7"]["inputs"]["steps"], 4)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(graph["14"]["class_type"], "SaveVideo")
        official = build_minimax_h3_workflow(
            JobMode.MINIMAX_H3_T2V, "A stadium strike.", [], normalize_options(JobMode.MINIMAX_H3_T2V, {"speed": "fast"}), 7,
        )
        self.assertEqual(official["9"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(official["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertNotIn("MiniMaxH3SigmaShift", {node["class_type"] for node in official.values()})

    def test_lightx2v_r2v_loads_ref2v_lora_and_quality_skips_acceleration(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_R2V, {"speed": "fast"})
        self.assertEqual(options["lora_name"], LIGHTX2V_REF2V_4STEP_LORA)
        graph = build_minimax_h3_lightx2v_workflow(
            JobMode.MINIMAX_H3_LIGHTX2V_R2V, "Use <Picture 1>.", ["character.png"], options, 9,
        )
        self.assertEqual(graph["5"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_REF2V_4STEP_LORA)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_REF2VA_FULL)
        balanced = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_T2V, {"speed": "balanced"})
        self.assertEqual(balanced["steps"], 8)
        self.assertEqual(balanced["lora_name"], LIGHTX2V_FL2V_8STEP_LORA)
        quality = normalize_options(JobMode.MINIMAX_H3_LIGHTX2V_T2V, {"speed": "quality"})
        quality_graph = build_minimax_h3_lightx2v_workflow(
            JobMode.MINIMAX_H3_LIGHTX2V_T2V, "A final pass.", [], quality, 11,
        )
        self.assertEqual(quality["steps"], 20)
        self.assertEqual(quality["lora_strength"], 0.0)
        self.assertNotIn("15", quality_graph)
        self.assertEqual(quality_graph["1"]["inputs"]["unet_name"], H3_FL2VA_PRUNED)

    def test_dual_accel_t2v_chains_lora_kj_sage_and_h3_sage(self) -> None:
        options = normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, {})
        self.assertEqual(options["quality"], "0.4")
        self.assertEqual(options["megapixels"], 0.4)
        self.assertEqual(options["speed"], "balanced")
        self.assertEqual(options["steps"], 8)
        self.assertEqual(options["lora_name"], DUAL_ACCEL_LORA_NAME)
        self.assertEqual(options["lora_strength"], 1.0)
        self.assertEqual(options["sampler_name"], "res_multistep")
        self.assertEqual(h3_dimensions(options), (864, 480))
        graph = build_minimax_h3_dual_accel_workflow(
            JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, "A stadium strike.", [], options, 7,
        )
        self.assertEqual(graph["9"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(graph["15"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_FL2V_8STEP_LORA)
        self.assertEqual(graph["15"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(graph["16"]["class_type"], "PathchSageAttentionKJ")
        self.assertEqual(graph["16"]["inputs"]["sage_attention"], "auto")
        self.assertFalse(graph["16"]["inputs"]["allow_compile"])
        self.assertEqual(graph["17"]["class_type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
        self.assertEqual(graph["17"]["inputs"]["model"], ["16", 0])
        self.assertEqual(graph["18"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual(graph["18"]["inputs"]["shift_video"], 12.0)
        self.assertEqual(graph["7"]["inputs"]["steps"], 8)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_FL2VA_FULL)
        self.assertEqual(graph["5"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(graph["14"]["class_type"], "SaveVideo")
        payload = workflow_for(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V).payload()
        speed = {item["name"]: item for item in payload["parameters"]}["options"]["schema"]["properties"]["speed"]
        self.assertEqual(speed["enum"], ["balanced", "quality", "custom"])
        self.assertEqual(speed["default"], "balanced")
        with self.assertRaisesRegex(ValueError, "生成速度"):
            normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, {"speed": "fast"})

    def test_dual_accel_i2v_and_r2v_and_quality_skip_lora(self) -> None:
        i2v = normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_I2V, {})
        i2v_graph = build_minimax_h3_dual_accel_workflow(
            JobMode.MINIMAX_H3_DUAL_ACCEL_I2V, "Camera pulls back.", ["start.png", "end.png"], i2v, 3,
        )
        self.assertEqual(i2v_graph["5"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(i2v_graph["5"]["inputs"]["first_frame"], ["20", 0])
        self.assertEqual(i2v_graph["5"]["inputs"]["last_frame"], ["21", 0])
        options = normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_R2V, {})
        self.assertEqual(options["lora_name"], DUAL_ACCEL_LORA_NAME)
        graph = build_minimax_h3_dual_accel_workflow(
            JobMode.MINIMAX_H3_DUAL_ACCEL_R2V, "Use <Picture 1>.", ["character.png"], options, 9,
        )
        self.assertEqual(graph["5"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(graph["15"]["inputs"]["lora_name"], LIGHTX2V_FL2V_8STEP_LORA)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], H3_REF2VA_FULL)
        quality = normalize_options(JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, {"speed": "quality"})
        quality_graph = build_minimax_h3_dual_accel_workflow(
            JobMode.MINIMAX_H3_DUAL_ACCEL_T2V, "A final pass.", [], quality, 11,
        )
        self.assertEqual(quality["steps"], 20)
        self.assertEqual(quality["lora_strength"], 0.0)
        self.assertNotIn("15", quality_graph)
        self.assertEqual(quality_graph["16"]["class_type"], "PathchSageAttentionKJ")
        self.assertEqual(quality_graph["1"]["inputs"]["unet_name"], H3_FL2VA_PRUNED)


class StoreTests(unittest.TestCase):
    def test_settings_default_comfy_root_uses_the_workspace_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_dir = Path(directory) / "workbench"
            settings = Settings(workspace_dir=workspace_dir)

            self.assertEqual(
                settings.comfy_output_dir,
                workspace_dir.parent / "整合包及模型" / "comfyui-integrate-v1.3" / "comfyui-integrate" / "Comfyui" / "output",
            )

    def test_settings_migrates_the_legacy_database_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            legacy_path = data_dir / "".join(("toon", "flow.db"))
            legacy_path.write_bytes(b"sqlite-data")
            (data_dir / f"{legacy_path.name}-wal").write_bytes(b"wal-data")

            database_path = Settings(data_dir_override=str(data_dir)).database_path

            self.assertEqual(database_path.name, "zly-ai-video-studio.db")
            self.assertEqual(database_path.read_bytes(), b"sqlite-data")
            self.assertEqual((data_dir / "zly-ai-video-studio.db-wal").read_bytes(), b"wal-data")
            self.assertFalse(legacy_path.exists())

    def test_public_job_uses_reference_urls_instead_of_local_paths(self) -> None:
        job = public_job({
            "id": "job-1",
            "mode": JobMode.MINIMAX_H3_R2V,
            "prompt": "Use the first reference.",
            "negative_prompt": "",
            "image_size": None,
            "reference_count": 2,
            "options": {"aspect_ratio": "2:3", "quality": "0.2", "megapixels": 0.2, "duration": 5},
            "submitted_options": {"aspect_ratio": "2:3", "quality": "0.2", "duration": 5},
            "options_submitted": True,
            "outputs": [],
        })
        self.assertEqual(
            job["references"],
            [
                {"index": 1, "url": "/api/jobs/job-1/references/1"},
                {"index": 2, "url": "/api/jobs/job-1/references/2"},
            ],
        )
        self.assertEqual(
            job["request_parameters"],
            [
                {"name": "mode", "label": "工作流", "value": "minimax-h3-r2v", "visibility": "primary"},
                {"name": "prompt", "label": "创作提示词", "value": "Use the first reference.", "visibility": "primary"},
                {"name": "references", "label": "参考图", "value": 2, "visibility": "primary"},
                {"name": "options.aspect_ratio", "label": "画面比例", "value": "2:3", "visibility": "primary"},
                {"name": "options.quality", "label": "分辨率", "value": "0.2", "visibility": "advanced"},
                {"name": "options.megapixels", "label": "内部像素面积", "value": 0.2, "visibility": "internal", "unit": "MP"},
                {"name": "options.duration", "label": "时长", "value": 5, "visibility": "primary", "unit": "秒"},
            ],
        )
        self.assertNotIn("submitted_options", job)

    def test_image_media_type_sniffs_extensionless_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "1_upload"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            self.assertEqual(_image_media_type(path), "image/png")
            jpeg = Path(directory) / "2.jpg"
            jpeg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 8)
            self.assertEqual(_image_media_type(jpeg), "image/jpeg")

    def test_request_parameters_omit_inactive_visible_when_options(self) -> None:
        fast = public_job({
            "id": "job-fast",
            "mode": JobMode.MINIMAX_H3_R2V,
            "prompt": "A forest path.",
            "negative_prompt": "",
            "image_size": None,
            "reference_count": 1,
            "options": {
                "aspect_ratio": "16:9",
                "quality": "0.2",
                "megapixels": 0.2,
                "duration": 3,
                "speed": "fast",
                "custom_steps": 8,
                "steps": 4,
                "lora_strength": 1,
            },
            "outputs": [],
        })
        fast_names = [item["name"] for item in fast["request_parameters"]]
        self.assertIn("options.speed", fast_names)
        self.assertNotIn("options.custom_steps", fast_names)
        self.assertIn("options.steps", fast_names)

        custom = public_job({
            "id": "job-custom",
            "mode": JobMode.MINIMAX_H3_R2V,
            "prompt": "A forest path.",
            "negative_prompt": "",
            "image_size": None,
            "reference_count": 1,
            "options": {
                "aspect_ratio": "16:9",
                "quality": "0.2",
                "megapixels": 0.2,
                "duration": 3,
                "speed": "custom",
                "custom_steps": 6,
                "steps": 6,
                "lora_strength": 1,
            },
            "outputs": [],
        })
        custom_names = [item["name"] for item in custom["request_parameters"]]
        self.assertIn("options.custom_steps", custom_names)
        self.assertEqual(
            next(item["value"] for item in custom["request_parameters"] if item["name"] == "options.custom_steps"),
            6,
        )

        preset_image = public_job({
            "id": "job-image",
            "mode": JobMode.GRS_GPT_IMAGE_2_VIP,
            "prompt": "A still.",
            "negative_prompt": "",
            "image_size": None,
            "reference_count": 0,
            "options": {
                "aspect_ratio": "16:9",
                "resolution": "1K",
                "count": 1,
                "custom_width": 1024,
                "custom_height": 1024,
            },
            "outputs": [],
        })
        image_names = [item["name"] for item in preset_image["request_parameters"]]
        self.assertNotIn("options.custom_width", image_names)
        self.assertNotIn("options.custom_height", image_names)

    def test_existing_database_adds_progress_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """CREATE TABLE jobs (
                        id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                        prompt TEXT NOT NULL, negative_prompt TEXT NOT NULL DEFAULT '', image_size TEXT,
                        options_json TEXT NOT NULL DEFAULT '{}', references_json TEXT NOT NULL,
                        outputs_json TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    )"""
                )
                connection.commit()
            finally:
                connection.close()
            JobStore(database_path)
            connection = sqlite3.connect(database_path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            finally:
                connection.close()
            self.assertIn("progress", columns)
            self.assertIn("submitted_options_json", columns)
            self.assertIn("options_submitted", columns)
            self.assertIn("comfy_prompt_id", columns)
            self.assertIn("comfy_client_id", columns)
            self.assertIn("comfy_phase", columns)

    def test_initialize_preserves_active_jobs_for_worker_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            store.update("job-1", status=JobStatus.RUNNING, stage="正在生成", progress=40)
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            reloaded = JobStore(Path(directory) / "test.db")
            job = reloaded.get("job-1")
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_job_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            created = store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            self.assertEqual(created["status"], JobStatus.QUEUED)
            self.assertEqual(created["progress"], 0)
            completed = store.update(
                "job-1", status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                outputs=[{"kind": "image", "path": "result.png", "label": "生成图片"}],
            )
            self.assertEqual(completed["outputs"][0]["path"], "result.png")
            self.assertEqual(store.list()[0]["status"], JobStatus.SUCCEEDED)
            self.assertEqual(store.list()[0]["progress"], 100)
            worker_job = store.get("job-1", include_references=True)
            self.assertEqual(worker_job["references"], [])
            self.assertNotIn("references", store.get("job-1"))

    def test_job_elapsed_is_frozen_after_success_and_survives_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            created = store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            self.assertIsNone(created.get("finished_at"))
            public_created = public_job(created)
            self.assertIsNone(public_created["elapsed_ms"])
            completed = store.update(
                "job-1", status=JobStatus.SUCCEEDED, stage="生成完成", progress=100,
                outputs=[{"kind": "video", "path": "a.mp4", "label": "MiniMax H3 视频"}],
                execution_elapsed_ms=123000,
            )
            self.assertIsNotNone(completed["finished_at"])
            self.assertEqual(completed["execution_elapsed_ms"], 123000)
            public_completed = public_job(completed)
            self.assertGreaterEqual(public_completed["elapsed_ms"], 0)
            self.assertEqual(public_completed["execution_elapsed_ms"], 123000)
            finished_at = completed["finished_at"]
            store.mark_output_delivered("job-1", 0, "2026-08-26T00:00:00+00:00")
            after_delivery = store.get("job-1")
            self.assertEqual(after_delivery["finished_at"], finished_at)
            self.assertEqual(after_delivery["execution_elapsed_ms"], 123000)
            retried = store.retry_terminal("job-1")
            self.assertIsNone(retried)
            store.update("job-1", status=JobStatus.FAILED, stage="生成失败", error="失败", outputs=[])
            retried = store.retry_terminal("job-1")
            self.assertIsNotNone(retried)
            self.assertIsNone(retried["finished_at"])
            self.assertIsNone(retried["execution_elapsed_ms"])

    def test_jobs_are_filtered_by_owner_and_delivery_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-a", JobMode.MINIMAX_H3_T2V, "A", "", None, [], owner_user_id="user-a")
            store.create("job-b", JobMode.MINIMAX_H3_T2V, "B", "", None, [], owner_user_id="user-b")
            store.update(
                "job-a", status=JobStatus.SUCCEEDED,
                outputs=[{"kind": "image", "path": "a.png", "label": "生成图片"}],
            )
            self.assertEqual([job["id"] for job in store.list_jobs("user-a")], ["job-a"])
            self.assertEqual([job["id"] for job in store.list_jobs("user-b")], ["job-b"])
            listed = store.list_jobs(None, 10)
            self.assertEqual({job["id"] for job in listed}, {"job-a", "job-b"})
            self.assertTrue(all(job["rounds"] for job in listed))
            store.update_metadata("job-a", pinned=True)
            store.create("job-c", JobMode.MINIMAX_H3_T2V, "C", "", None, [], owner_user_id="user-c")
            self.assertEqual([job["id"] for job in store.list_jobs(None, 2)], ["job-a", "job-c"])
            self.assertEqual(store.list_jobs(None, 2)[0]["rounds"][0]["reference_count"], 0)
            store.mark_output_delivered("job-a", 0, "2024-01-01T00:00:00Z")
            updated = store.get("job-a")
            self.assertEqual(updated["outputs"][0]["delivery_status"], "local")


class AuthenticationTests(unittest.TestCase):
    def test_password_minimum_length_is_six_characters(self) -> None:
        validate_password("secret")
        with self.assertRaisesRegex(ValueError, "至少需要 6 个字符"):
            validate_password("short")

    def test_password_reset_clears_login_failures_for_username_across_ips(self) -> None:
        login_failures.clear()
        self.addCleanup(login_failures.clear)
        login_failures.update({
            "10.0.0.10:staff": [1.0, 2.0],
            "10.0.0.11:staff": [3.0],
            "10.0.0.10:other": [4.0],
        })

        cleared = clear_login_failures_for_username(" Staff ")

        self.assertEqual(cleared, 2)
        self.assertEqual(login_failures, {"10.0.0.10:other": [4.0]})

    def test_user_password_session_and_revocation_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = AuthStore(Path(directory) / "auth.db")
            self.assertTrue(auth.setup_required())
            user = auth.create_user(
                "Admin", "管理员", "secure-pass-123", UserRole.SUPER_ADMIN,
                must_change_password=False,
            )
            self.assertFalse(auth.setup_required())
            self.assertEqual(auth.authenticate("admin", "secure-pass-123")["id"], user["id"])
            self.assertIsNone(auth.authenticate("admin", "wrong-password"))
            token, _ = auth.create_session(user["id"])
            self.assertEqual(auth.user_for_session(token)["id"], user["id"])
            self.assertEqual(len(csrf_token(token)), 64)
            auth.revoke_session(token)
            self.assertIsNone(auth.user_for_session(token))

    def test_password_reset_revokes_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = AuthStore(Path(directory) / "auth.db")
            user = auth.create_user("staff", "员工", "initial-pass-123", UserRole.EMPLOYEE)
            token, _ = auth.create_session(user["id"])
            updated = auth.set_password(user["id"], "changed-pass-123", must_change_password=False)
            self.assertFalse(updated["must_change_password"])
            self.assertIsNone(auth.user_for_session(token))
            self.assertIsNotNone(auth.authenticate("staff", "changed-pass-123"))
            connection = auth.connection()
            try:
                encoded = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
            finally:
                connection.close()
            self.assertTrue(verify_password("changed-pass-123", encoded))


class ResourceStorageTests(unittest.TestCase):
    def test_desktop_delivery_ticket_is_bound_to_one_user_and_output(self) -> None:
        tickets = DesktopDeliveryTickets()
        token = tickets.issue("employee-a", "job-a", 1)
        ticket = tickets.resolve(token, "job-a", 1)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.user_id, "employee-a")
        self.assertIsNone(tickets.resolve(token, "job-a", 0))
        self.assertIsNone(tickets.resolve(token, "job-b", 1))

    def test_browser_local_staging_is_removed_after_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BrowserLocalStagingStorage(Path(directory) / "staging")
            resource = storage.store_bytes("video", "source.mp4", b"video-bytes")
            self.assertEqual(storage.resolve(resource.key).read_bytes(), b"video-bytes")
            self.assertTrue(storage.delete(resource.key))
            self.assertIsNone(storage.resolve(resource.key))

    def test_browser_stream_keeps_completed_output_off_the_server_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BrowserStreamStorage(Path(directory) / "staging")
            service = ComfyService(Settings(workspace_dir=Path(directory)), storage)
            resource = service.download({"filename": "result.mp4", "subfolder": "h3", "type": "output"}, "video")

            self.assertIsNone(resource.local_path)
            self.assertIsNone(storage.resolve(resource.key))
            self.assertTrue(service.can_stream_output(resource.source_info))
            self.assertTrue(service.finalize_output_source(resource.source_info))
            self.assertTrue(storage.delete(resource.key))

    def test_browser_stream_rejects_an_unsafe_comfy_output_reference(self) -> None:
        service = ComfyService(Settings(), BrowserStreamStorage(Path(tempfile.gettempdir()) / "stream-test"))
        with self.assertRaisesRegex(legacy.ComfyError, "输出缺少 filename"):
            service.download({"filename": "../outside.mp4", "type": "output"}, "video")

    def test_provider_factory_fails_closed_for_unknown_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = create_resource_storage("browser-local", Path(directory) / "staging")
            self.assertEqual(storage.provider_id, "browser-local")
            self.assertEqual(
                create_resource_storage("browser-stream", Path(directory) / "staging").provider_id,
                "browser-stream",
            )
            with self.assertRaisesRegex(ValueError, "未知资源存储 provider"):
                create_resource_storage("qiniu-not-installed", Path(directory) / "staging")

    def test_comfy_output_cleanup_is_confined_to_fixed_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "comfy"
            output_dir = root / "output" / "video"
            output_dir.mkdir(parents=True)
            generated = output_dir / "result.mp4"
            generated.write_bytes(b"video")
            outside = root / "outside.mp4"
            outside.write_bytes(b"keep")
            test_settings = Settings(
                workspace_dir=Path(directory),
                comfy_root_override=str(root),
            )
            service = ComfyService(test_settings, BrowserLocalStagingStorage(Path(directory) / "staging"))
            self.assertTrue(service.delete_output_source({
                "filename": "result.mp4", "subfolder": "video", "type": "output",
            }))
            self.assertFalse(generated.exists())
            self.assertFalse(service.delete_output_source({
                "filename": "outside.mp4", "subfolder": "..", "type": "output",
            }))
            self.assertTrue(outside.exists())

    def test_public_job_never_exposes_comfy_output_locator(self) -> None:
        job = public_job({
            "id": "job-source", "mode": JobMode.MINIMAX_H3_T2V, "status": "succeeded",
            "prompt": "prompt", "negative_prompt": "", "image_size": None,
            "reference_count": 0, "options": {}, "submitted_options": {}, "options_submitted": False,
            "outputs": [{
                "kind": "image", "path": "result.png", "label": "生成图片",
                "_comfy_source": {"filename": "secret.png", "subfolder": "", "type": "output"},
            }],
        })
        self.assertNotIn("_comfy_source", job["outputs"][0])

    def test_public_job_uses_fallback_url_for_structural_sharing(self) -> None:
        class CloudStorage:
            def download_url(self, key: str) -> str | None:
                return f"https://media.example.com/{key}?signed=1"

        previous_storage = getattr(app.state, "resource_storage", None)
        app.state.resource_storage = CloudStorage()
        try:
            job = public_job({
                "id": "cloud-job", "mode": JobMode.MINIMAX_H3_T2V, "status": "succeeded",
                "prompt": "prompt", "negative_prompt": "", "image_size": None, "reference_count": 0,
                "options": {}, "submitted_options": {}, "options_submitted": False,
                "outputs": [{"kind": "video", "path": "video/key.mp4", "label": "视频", "delivery_status": "cloud"}], "rounds": [],
            })
            self.assertEqual(job["outputs"][0]["download_url"], "/api/jobs/cloud-job/outputs/0/download")
        finally:
            if previous_storage is None:
                del app.state.resource_storage
            else:
                app.state.resource_storage = previous_storage

    def test_public_job_exposes_download_when_failed_item_has_outputs(self) -> None:
        job = public_job({
            "id": "failed-with-image", "mode": JobMode.GRS_GPT_IMAGE_2, "status": "failed",
            "prompt": "prompt", "negative_prompt": "", "image_size": None, "reference_count": 0,
            "options": {}, "submitted_options": {}, "options_submitted": False,
            "outputs": [{"kind": "image", "path": "kept.png", "label": "生成图片", "delivery_status": "pending"}],
            "rounds": [{
                "id": "round-1", "sequence": 1, "mode": JobMode.GRS_GPT_IMAGE_2, "media_type": "image",
                "status": "failed", "prompt": "prompt", "negative_prompt": "", "image_size": None,
                "reference_count": 0, "options": {}, "submitted_options": {}, "options_submitted": False,
                "generation_items": [{
                    "id": "item-1", "index": 1, "status": "failed",
                    "outputs": [{"kind": "image", "path": "kept.png", "label": "生成图片", "delivery_status": "pending"}],
                }],
            }],
        })
        self.assertEqual(job["outputs"][0]["download_url"], "/api/jobs/failed-with-image/outputs/0/download")
        self.assertEqual(
            job["rounds"][0]["generation_items"][0]["outputs"][0]["download_url"],
            "/api/jobs/failed-with-image/generations/item-1/outputs/0/download",
        )

    def test_cloud_output_download_streams_bytes_instead_of_redirecting(self) -> None:
        class CloudStorage:
            def resolve(self, key: str):
                return None

            def download_url(self, key: str, expires_in_seconds: int = 300) -> str | None:
                return f"https://media.example.com/{key}?signed=1"

        class FakeUpstream:
            status_code = 200
            headers = {"Content-Type": "video/mp4", "Content-Length": "4"}

            def iter_content(self, chunk_size=1):
                yield b"mp4!"

            def close(self) -> None:
                return None

        previous_storage = getattr(app.state, "resource_storage", None)
        app.state.resource_storage = CloudStorage()
        try:
            with patch("backend.app.main.requests.get", return_value=FakeUpstream()) as fetch:
                response = output_response({"kind": "video", "path": "video/cloud-only.mp4", "label": "视频"})
            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.args[0], "https://media.example.com/video/cloud-only.mp4?signed=1")
            self.assertEqual(fetch.call_args.kwargs.get("allow_redirects"), True)
            self.assertEqual(response.status_code, 200)
            self.assertNotEqual(response.status_code, 307)

            async def collect() -> bytes:
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
                return b"".join(chunks)

            self.assertEqual(asyncio.run(collect()), b"mp4!")
        finally:
            if previous_storage is None:
                delattr(app.state, "resource_storage")
            else:
                app.state.resource_storage = previous_storage

    def test_browser_direct_view_url_uses_only_the_fixed_local_comfyui_origin(self) -> None:
        url = browser_direct_view_url({
            "filename": "result.mp4", "subfolder": "h3/output", "type": "output",
        })
        self.assertEqual(url, f"{BROWSER_LOCAL_COMFY_VIEW_URL}?filename=result.mp4&subfolder=h3%2Foutput&type=output")


class WorkerTests(unittest.TestCase):
    def test_comfy_progress_state_is_converted_to_percent(self) -> None:
        message = {
            "type": "progress_state",
            "data": {"prompt_id": "prompt-1", "nodes": {"10": {"state": "running", "value": 4, "max": 20}}},
        }
        self.assertEqual(ComfyService.progress_percent(message, "prompt-1"), 20)
        self.assertIsNone(ComfyService.progress_percent(message, "another-prompt"))

    def test_comfy_loader_progress_waits_for_workflow_switch(self) -> None:
        workflow = {
            "1": {"class_type": "UNETLoader"},
            "10": {"class_type": "SamplerCustomAdvanced"},
            "14": {"class_type": "SaveVideo"},
        }
        loader = interpret_comfy_progress(
            {"type": "executing", "data": {"node": "1", "prompt_id": "p1"}},
            "p1", workflow, "MiniMax H3 正在生成视频",
        )
        self.assertIsNotNone(loader)
        assert loader is not None
        self.assertEqual(loader.stage, "正在切换工作流")
        self.assertLess(loader.progress, 20)
        loader_state = interpret_comfy_progress(
            {
                "type": "progress_state",
                "data": {"prompt_id": "p1", "nodes": {"1": {"state": "running", "value": 3, "max": 4}}},
            },
            "p1", workflow, "MiniMax H3 正在生成视频",
        )
        self.assertIsNotNone(loader_state)
        assert loader_state is not None
        self.assertEqual(loader_state.stage, "正在切换工作流")
        self.assertLess(loader_state.progress, 20)
        sampler = interpret_comfy_progress(
            {
                "type": "progress_state",
                "data": {"prompt_id": "p1", "nodes": {"10": {"state": "running", "value": 6, "max": 8}}},
            },
            "p1", workflow, "MiniMax H3 正在生成视频",
        )
        self.assertIsNotNone(sampler)
        assert sampler is not None
        self.assertEqual(sampler.stage, "MiniMax H3 正在生成视频")
        self.assertEqual(sampler.progress, 75)

    def test_grs_image_progress_moves_within_two_minutes(self) -> None:
        from backend.app.worker import grs_image_progress

        self.assertEqual(grs_image_progress(0), 12)
        self.assertGreater(grs_image_progress(30), grs_image_progress(0))
        self.assertGreater(grs_image_progress(60), 40)
        self.assertEqual(grs_image_progress(120), 90)
        self.assertEqual(grs_image_progress(600), 90)

    def test_comfy_history_messages_are_converted_to_execution_elapsed_ms(self) -> None:
        record = {
            "status": {
                "status_str": "success",
                "messages": [
                    ["execution_start", {"prompt_id": "p1", "timestamp": 1_720_000_000.0}],
                    ["execution_success", {"prompt_id": "p1", "timestamp": 1_720_000_123.4}],
                ],
            }
        }
        self.assertEqual(ComfyService.execution_elapsed_ms(record), 123400)
        self.assertIsNone(ComfyService.execution_elapsed_ms({"status": {"messages": []}}))
        millis = {
            "status": {
                "messages": [
                    ["execution_start", {"timestamp": 1_720_000_000_000}],
                    ["execution_success", {"timestamp": 1_720_000_045_000}],
                ]
            }
        }
        self.assertEqual(ComfyService.execution_elapsed_ms(millis), 45_000)

    def test_worker_keeps_reference_paths_internal(self) -> None:
        class FakeComfy:
            received_references: list[str] | None = None
            last_execution_elapsed_ms = None

            def run(self, mode, references, prompt, negative_prompt, image_size, options, update_stage, on_submitted, save_partial_outputs, is_cancelled=None):
                self.received_references = references
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_R2V, "prompt", "", None, ["scene.png", "subject.png", "style.png"])
            comfy = FakeComfy()
            asyncio.run(JobWorker(store, comfy).execute("job-1"))
            self.assertEqual(comfy.received_references, ["scene.png", "subject.png", "style.png"])

    def test_worker_releases_queue_when_comfy_connection_is_interrupted(self) -> None:
        class InterruptedComfy:
            def run(self, *args, **kwargs):
                raise ComfyUnavailable("ComfyUI or FRP connection interrupted")

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            asyncio.run(JobWorker(store, InterruptedComfy()).execute("job-1"))
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.INTERRUPTED)
            self.assertIsNone(job["comfy_prompt_id"])
            self.assertIn("ComfyUI", job["stage"])

    def test_recover_auto_requeues_lost_comfy_job(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return []

            def prompt_state(self, prompt_id, active_prompt_ids):
                return "missing", None

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "lost-prompt", "client-1", "generation")
            worker = JobWorker(store, FakeComfy())
            recovered = worker.recover()
            job = store.get("job-1")
            self.assertEqual(recovered, ["job-1"])
            self.assertEqual(job["status"], JobStatus.QUEUED)
            self.assertIsNone(job["comfy_prompt_id"])
            self.assertIn("自动重新提交", job["stage"])

    def test_recover_resumes_interrupted_job_still_in_comfy_queue(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return [ComfyQueuePrompt("prompt-1", "client-1", "prompt", None)]

            def prompt_state(self, prompt_id, active_prompt_ids):
                return "active", None

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED, stage="ComfyUI 连接中断，恢复后将自动重新提交")
            worker = JobWorker(store, FakeComfy())
            recovered = worker.recover()
            job = store.get("job-1")
            self.assertEqual(recovered, ["job-1"])
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_recover_does_not_auto_requeue_when_comfy_is_unreachable(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED)
            worker = JobWorker(store, FakeComfy())
            self.assertEqual(worker.recover(), [])
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.INTERRUPTED)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_recover_stops_auto_requeue_after_max_attempts(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return []

            def prompt_state(self, prompt_id, active_prompt_ids):
                return "missing", None

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            worker = JobWorker(store, FakeComfy())
            for _ in range(JobWorker.MAX_AUTO_RETRIES):
                store.set_comfy_execution("job-1", "lost-prompt", "client-1", "generation")
                store.update("job-1", status=JobStatus.INTERRUPTED)
                self.assertEqual(worker.recover(), ["job-1"])
                self.assertEqual(store.get("job-1")["status"], JobStatus.QUEUED)
            store.set_comfy_execution("job-1", "lost-prompt", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED)
            self.assertEqual(worker.recover(), [])
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.INTERRUPTED)
            self.assertIn("已自动重试", job["stage"])

    def test_execute_resumes_interrupted_job_with_prompt_id(self) -> None:
        class FakeComfy:
            last_execution_elapsed_ms = None

            def resume(self, *args, **kwargs):
                return [{"kind": "video", "path": "recovered.mp4", "label": "视频"}]

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED)
            asyncio.run(JobWorker(store, FakeComfy()).execute("job-1"))
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.SUCCEEDED)
            self.assertIsNone(job["comfy_prompt_id"])

    def test_recover_does_not_preempt_in_flight_submit_without_prompt_id(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.update("job-1", status=JobStatus.RUNNING, stage="正在准备任务")
            worker = JobWorker(store, FakeComfy())
            worker.queued_job_ids.add("job-1")
            self.assertEqual(worker.recover(), [])
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertIsNone(job["comfy_prompt_id"])

    def test_recover_auto_requeues_stale_running_job_without_prompt_id(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return []

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.update("job-1", status=JobStatus.RUNNING, stage="正在准备任务")
            worker = JobWorker(store, FakeComfy())
            recovered = worker.recover()
            job = store.get("job-1")
            self.assertEqual(recovered, ["job-1"])
            self.assertEqual(job["status"], JobStatus.QUEUED)

    def test_interrupted_job_can_be_requeued_after_comfy_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            self.assertIsNone(store.retry_terminal("job-1"))
            store.set_comfy_execution("job-1", "stale-prompt", "client-1", "generation")
            store.update("job-1", status=JobStatus.INTERRUPTED)
            store.clear_comfy_execution("job-1")
            retried = store.retry_terminal("job-1")
            self.assertIsNotNone(retried)
            self.assertEqual(retried["status"], JobStatus.QUEUED)
            self.assertIsNone(retried["comfy_prompt_id"])
            self.assertIsNone(store.retry_terminal("job-1"))

    def test_failed_job_can_be_requeued_only_after_execution_id_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "active-prompt", "client-1", "generation")
            store.update("job-1", status=JobStatus.FAILED)
            self.assertIsNone(store.retry_terminal("job-1"))
            store.clear_comfy_execution("job-1")
            retried = store.retry_terminal("job-1")
            self.assertEqual(retried["status"], JobStatus.QUEUED)

    def test_worker_reconnects_interrupted_legacy_h3_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "提示词", "", None, [])
            store.update("job-1", status=JobStatus.INTERRUPTED, stage="应用已重启")
            created_at = datetime.fromisoformat(store.get("job-1")["created_at"])
            worker = JobWorker(store, object())
            worker.reconnect_legacy_jobs([ComfyQueuePrompt("prompt-1", "client-1", "提示词", created_at)])
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.RUNNING)
            self.assertEqual(job["comfy_prompt_id"], "prompt-1")

    def test_legacy_reconnection_pairs_duplicate_prompts_by_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            for job_id in ("older", "newer"):
                store.create(job_id, JobMode.MINIMAX_H3_T2V, "同一提示词", "", None, [])
                store.update(job_id, status=JobStatus.INTERRUPTED, stage="应用已重启")
            connection = store.connection()
            try:
                connection.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-08-07T02:15:46+00:00", "older"))
                connection.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ("2026-08-07T02:16:45+00:00", "newer"))
                connection.commit()
            finally:
                connection.close()
            worker = JobWorker(store, object())
            worker.reconnect_legacy_jobs([
                ComfyQueuePrompt("current", "client-current", "同一提示词", datetime.fromisoformat("2026-08-07T02:16:45.100+00:00")),
                ComfyQueuePrompt("finished", "client-finished", "同一提示词", datetime.fromisoformat("2026-08-07T02:15:46.100+00:00")),
            ])
            self.assertEqual(store.get("older")["comfy_prompt_id"], "finished")
            self.assertEqual(store.get("newer")["comfy_prompt_id"], "current")

    def test_mark_cancelled_clears_prompt_and_blocks_auto_requeue(self) -> None:
        class FakeComfy:
            def active_prompts(self):
                return []

            def prompt_state(self, prompt_id, active_prompt_ids):
                return "missing", None

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.set_comfy_execution("job-1", "prompt-1", "client-1", "generation")
            job, prompt_ids = store.mark_cancelled("job-1")
            self.assertIsNotNone(job)
            self.assertEqual(prompt_ids, ["prompt-1"])
            self.assertEqual(job["status"], JobStatus.CANCELLED)
            self.assertTrue(store.is_cancelled("job-1"))
            self.assertIsNone(job["comfy_prompt_id"])
            worker = JobWorker(store, FakeComfy())
            self.assertEqual(worker.recover(), [])
            self.assertEqual(store.get("job-1")["status"], JobStatus.CANCELLED)

    def test_cancelled_job_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.mark_cancelled("job-1")
            retried = store.retry_terminal("job-1")
            self.assertEqual(retried["status"], JobStatus.QUEUED)
            self.assertFalse(retried["rounds"][-1]["generation_items"][0]["cancel_requested"])

    def test_execute_keeps_cancelled_when_comfy_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])

            class FakeComfy:
                last_execution_elapsed_ms = None

                def run(self, *args, **kwargs):
                    store.mark_cancelled("job-1")
                    raise RuntimeError("ComfyUI 推理失败: interrupted")

            asyncio.run(JobWorker(store, FakeComfy()).execute("job-1"))
            job = store.get("job-1")
            self.assertEqual(job["status"], JobStatus.CANCELLED)
            self.assertEqual(job["stage"], "已停止生成")

    def test_stop_prompt_interrupts_running_and_deletes_pending(self) -> None:
        class FakeResponse:
            ok = True

            def json(self):
                return {
                    "queue_running": [[0, "run-1", {}, {}, []]],
                    "queue_pending": [[1, "pend-1", {}, {}, []]],
                }

        posts: list[tuple[str, dict]] = []

        class FakeRequests:
            @staticmethod
            def get(url, **kwargs):
                return FakeResponse()

            @staticmethod
            def post(url, **kwargs):
                posts.append((url, kwargs.get("json") or {}))
                return FakeResponse()

        with patch("backend.app.comfy_service.requests", FakeRequests):
            service = ComfyService(Settings())
            service.stop_prompt("run-1")
            service.stop_prompt("pend-1")
        self.assertEqual(posts[0], ("http://127.0.0.1:8188/interrupt", {"prompt_id": "run-1"}))
        self.assertEqual(posts[1], ("http://127.0.0.1:8188/queue", {"delete": ["pend-1"]}))

    def test_free_resources_posts_unload_when_comfy_queue_is_empty(self) -> None:
        class FakeResponse:
            ok = True

            def json(self):
                return {"queue_running": [], "queue_pending": [], "prompt_id": "cleanup-1"}

        posts: list[tuple[str, dict]] = []

        class FakeRequests:
            @staticmethod
            def get(url, **kwargs):
                return FakeResponse()

            @staticmethod
            def post(url, **kwargs):
                posts.append((url, kwargs.get("json") or {}))
                return FakeResponse()

        with patch("backend.app.comfy_service.requests", FakeRequests):
            self.assertTrue(ComfyService(Settings()).free_resources())
        self.assertEqual(posts[0], ("http://127.0.0.1:8188/free", {"unload_models": True, "free_memory": True}))
        self.assertEqual(posts[1][0], "http://127.0.0.1:8188/prompt")
        self.assertEqual(posts[1][1]["prompt"]["1"]["class_type"], "VRAMCleanup")
        self.assertEqual(posts[1][1]["prompt"]["2"]["class_type"], "RAMCleanup")
        self.assertFalse(posts[1][1]["prompt"]["2"]["inputs"]["clean_processes"])

    def test_free_resources_skips_when_comfy_still_has_prompts(self) -> None:
        class FakeResponse:
            ok = True

            def json(self):
                return {"queue_running": [[0, "run-1", {}, {}, []]], "queue_pending": []}

        posts: list[tuple[str, dict]] = []

        class FakeRequests:
            @staticmethod
            def get(url, **kwargs):
                return FakeResponse()

            @staticmethod
            def post(url, **kwargs):
                posts.append((url, kwargs.get("json") or {}))
                return FakeResponse()

        with patch("backend.app.comfy_service.requests", FakeRequests):
            self.assertFalse(ComfyService(Settings()).free_resources())
        self.assertEqual(posts, [])

    def test_worker_releases_comfy_resources_after_last_job(self) -> None:
        class FakeComfy:
            freed = False
            last_execution_elapsed_ms = None

            def run(self, *args, **kwargs):
                return []

            def free_resources(self):
                self.freed = True
                return True

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            comfy = FakeComfy()
            worker = JobWorker(store, comfy)
            asyncio.run(worker.execute("job-1"))
            asyncio.run(worker.release_comfy_resources_if_idle())
            self.assertEqual(store.get("job-1")["status"], JobStatus.SUCCEEDED)
            self.assertTrue(comfy.freed)

    def test_worker_keeps_models_loaded_when_more_jobs_are_queued(self) -> None:
        class FakeComfy:
            freed = False
            last_execution_elapsed_ms = None

            def run(self, *args, **kwargs):
                return []

            def free_resources(self):
                self.freed = True
                return True

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            store.create("job-1", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            store.create("job-2", JobMode.MINIMAX_H3_T2V, "prompt", "", None, [])
            comfy = FakeComfy()
            worker = JobWorker(store, comfy)
            asyncio.run(worker.execute("job-1"))
            asyncio.run(worker.release_comfy_resources_if_idle())
            self.assertFalse(comfy.freed)

    def test_worker_releases_comfy_resources_on_idle_start(self) -> None:
        class FakeComfy:
            freed = False

            def active_prompts(self):
                return []

            def free_resources(self):
                self.freed = True
                return True

        async def start_and_stop(worker: JobWorker) -> None:
            await worker.start()
            await worker.stop()

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "test.db")
            comfy = FakeComfy()
            asyncio.run(start_and_stop(JobWorker(store, comfy)))
            self.assertTrue(comfy.freed)


if __name__ == "__main__":
    unittest.main()
