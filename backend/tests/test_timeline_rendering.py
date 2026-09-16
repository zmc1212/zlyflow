from __future__ import annotations

import unittest

from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.timeline_rendering import (
    DEFAULT_H3_DIRECTOR_CAPABILITIES,
    build_timeline_render_request,
    episode_video_render_mode,
    listed_episode_r2v_workflows,
    plan_timeline_chunks,
    uses_director_timeline,
)
from backend.app.workflow_registry import workflow_for


def shots(count: int, duration: float = 8, scene_size: int | None = None) -> list[dict]:
    result = []
    for index in range(count):
        scene = f"scene-{index // scene_size}" if scene_size else "scene-1"
        result.append({
            "beat_id": f"beat-{index + 1}",
            "prompt": f"shot {index + 1}",
            "duration_sec": duration,
            "scene_id": scene,
            "uploaded_refs": [],
        })
    return result


class TimelineRenderingTests(unittest.TestCase):
    def test_single_shot_is_a_single_segment_request(self):
        request = build_timeline_render_request(
            shots(1), render_scope="shot", episode_id="ep-1",
            workflow_id="minimax-h3-director-accel-r2v", task_type="r2v",
        )
        self.assertEqual("shot", request["renderScope"])
        self.assertEqual(["beat-1"], [item["shotId"] for item in request["shots"]])
        self.assertEqual(1, len(request["timeline_data"]["segments"]))

    def test_six_eight_second_shots_fit_one_timeline(self):
        chunks = plan_timeline_chunks(shots(6))
        self.assertEqual(1, len(chunks))
        self.assertEqual(6, len(chunks[0]))

    def test_twenty_shots_are_split_and_do_not_exceed_capability(self):
        chunks = plan_timeline_chunks(shots(20))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= DEFAULT_H3_DIRECTOR_CAPABILITIES.max_segments for chunk in chunks))
        self.assertEqual(20, sum(len(chunk) for chunk in chunks))

    def test_director_registry_exposes_timeline_capabilities(self):
        definition = workflow_for("minimax-h3-director-accel-r2v")
        self.assertTrue(definition.supports_timeline)
        self.assertTrue(definition.supports_multi_segment)
        self.assertEqual(6, definition.max_segments)
        self.assertEqual(1152, definition.max_total_frames)

    def test_client_uses_variable_duration_and_contiguous_starts(self):
        timeline = ComfyVideoClient.build_timeline(shots(2, duration=5), "r2v")
        self.assertEqual(124 * 2, timeline["totalFrames"])
        self.assertEqual([0, 124], [item["start"] for item in timeline["segments"]])

    def test_timeline_canvas_follows_quality_and_aspect_ratio(self):
        timeline = ComfyVideoClient.build_timeline(
            shots(1),
            "r2v",
            options={"aspect_ratio": "16:9", "quality": "1.0", "megapixels": 1.0},
        )
        self.assertEqual(1.0, timeline["output"]["megapixels"])
        self.assertEqual(1376, timeline["width"])
        self.assertEqual(768, timeline["height"])
        self.assertEqual("16:9 (宽屏)", timeline["output"]["aspectRatio"])

    def test_workflow_maps_weight_profile_and_steps(self):
        from backend.app.workflow_registry import H3_REF2VA_FULL, normalize_options

        options = normalize_options("minimax-h3-director-accel-r2v", {
            "quality": "0.4",
            "speed": "quality",
            "weight_profile": "full",
        })
        timeline = ComfyVideoClient.build_timeline(shots(1), "r2v", options=options)
        workflow = ComfyVideoClient.build_workflow(timeline, "r2v", "video/test", options=options)
        self.assertEqual(25, workflow["12"]["inputs"]["steps"])
        self.assertEqual(864, workflow["12"]["inputs"]["width"])
        self.assertEqual(480, workflow["12"]["inputs"]["height"])
        self.assertEqual(H3_REF2VA_FULL, workflow["1"]["inputs"]["unet_name"])


class EpisodeRenderModeTests(unittest.TestCase):
    def test_director_r2v_is_episode_and_other_r2v_are_shot(self):
        self.assertEqual("episode", episode_video_render_mode("minimax-h3-director-accel-r2v"))
        self.assertTrue(uses_director_timeline("minimax-h3-director-accel-r2v"))
        self.assertEqual("shot", episode_video_render_mode("minimax-h3-r2v"))
        self.assertEqual("shot", episode_video_render_mode("minimax-h3-lightx2v-r2v"))
        self.assertEqual("shot", episode_video_render_mode("minimax-h3-dual-accel-r2v"))
        self.assertEqual("shot", episode_video_render_mode("minimax-h3-t8-all-reference"))
        self.assertEqual("shot", episode_video_render_mode("missing-workflow"))

    def test_listed_r2v_covers_director_and_shot_families(self):
        ids = {item.id for item in listed_episode_r2v_workflows()}
        self.assertIn("minimax-h3-director-accel-r2v", ids)
        self.assertIn("minimax-h3-r2v", ids)
        self.assertIn("minimax-h3-lightx2v-r2v", ids)
        self.assertIn("minimax-h3-dual-accel-r2v", ids)
        self.assertIn("minimax-h3-t8-all-reference", ids)
        self.assertNotIn("minimax-h3-t2v", ids)
        self.assertNotIn("minimax-h3-i2v", ids)
        self.assertNotIn("minimax-h3-t8-dual-clock", ids)
        self.assertNotIn("wan21-vace-depth-v2v", ids)

    def test_mode_payload_exposes_timeline_flags_for_workshop(self):
        from backend.app.models import ModeResponse

        director = ModeResponse.model_validate(workflow_for("minimax-h3-director-accel-r2v").payload())
        official = ModeResponse.model_validate(workflow_for("minimax-h3-r2v").payload())
        self.assertTrue(director.supports_timeline)
        self.assertTrue(director.supports_multi_segment)
        self.assertFalse(official.supports_timeline)
        self.assertFalse(official.supports_multi_segment)

    def test_shot_graph_uses_official_builder_and_beat_duration(self):
        from backend.app.workflow_registry import h3_length, normalize_options

        options = normalize_options("minimax-h3-r2v", {"duration": 6, "quality": "0.4"})
        options["duration"] = 6
        refs = [{"imageFile": "refs/char.png", "fileName": "char.png", "subfolder": "refs"}]
        workflow = ComfyVideoClient.build_shot_workflow(
            "minimax-h3-r2v", "subject_definitions", refs, "video/test-shot", options=options,
        )
        class_types = [node["class_type"] for node in workflow.values()]
        self.assertIn("MiniMaxH3ReferenceToVideo", class_types)
        self.assertNotIn("MiniMaxH3Director", class_types)
        self.assertEqual(h3_length({"duration": 6}), workflow["5"]["inputs"]["length"])
        self.assertEqual("video/test-shot", workflow["14"]["inputs"]["filename_prefix"])
        self.assertEqual("refs/char.png", workflow["20"]["inputs"]["image"])

    def test_lightx2v_dual_accel_and_t8_builders_are_selected_by_workflow_id(self):
        from backend.app.media_studio.services.episode_video_service import EpisodeVideoService

        refs = [{"imageFile": "a.png", "fileName": "a.png"}]
        light = ComfyVideoClient.build_shot_workflow(
            "minimax-h3-lightx2v-r2v", "prompt", refs, "video/lx",
            options=EpisodeVideoService.resolve_generation_options({"workflow": "minimax-h3-lightx2v-r2v"}),
        )
        dual = ComfyVideoClient.build_shot_workflow(
            "minimax-h3-dual-accel-r2v", "prompt", refs, "video/dual",
            options=EpisodeVideoService.resolve_generation_options({"workflow": "minimax-h3-dual-accel-r2v"}),
        )
        t8 = ComfyVideoClient.build_shot_workflow(
            "minimax-h3-t8-all-reference", "prompt", refs, "video/t8",
            options=EpisodeVideoService.resolve_generation_options({"workflow": "minimax-h3-t8-all-reference"}),
        )
        self.assertIn("MiniMaxH3ReferenceToVideo", [node["class_type"] for node in light.values()])
        self.assertEqual("video/lx", light["14"]["inputs"]["filename_prefix"])
        self.assertIn("MiniMaxH3ReferenceToVideo", [node["class_type"] for node in dual.values()])
        self.assertIn("MiniMaxH3AudioConditioningT8", [node["class_type"] for node in t8.values()])
        self.assertNotIn("MiniMaxH3Director", [node["class_type"] for node in t8.values()])
        self.assertEqual("video/t8", t8["14"]["inputs"]["filename_prefix"])


if __name__ == "__main__":
    unittest.main()
