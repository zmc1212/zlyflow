from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from scripts.blender_h3_pilot.pilot import REQUIRED_NODES, build_pilot_graph, preflight
from scripts.blender_h3_pilot.real_trial import build_real_graph
from scripts.blender_h3_pilot.fight_trial import PROMPT_HUAJIA, build_graph as build_fight_graph


class BlenderH3PilotTests(unittest.TestCase):
    def test_huajia_looks_and_clean_track_keep_picture_order(self) -> None:
        images = ["trial/wu-nai-look.png", "trial/sha-lili-look.png", "trial/track-clean.png"]
        graph = build_fight_graph(images, "trial/ue-fight-guide.mp4", PROMPT_HUAJIA)

        for index, filename in enumerate(images):
            node = str(20 + index)
            self.assertEqual(graph[node]["inputs"]["image"], filename)
            self.assertEqual(graph["5"]["inputs"][f"ref_images.ref_image_{index}"], [node, 0])
            self.assertIn(f"<Picture {index + 1}>", graph["5"]["inputs"]["prompt"])
        self.assertEqual(graph["18"]["inputs"]["file"], "trial/ue-fight-guide.mp4")
        self.assertEqual(graph["5"]["inputs"]["ref_videos.ref_video_0"], ["19", 0])
        self.assertIn("<Video 1>", graph["5"]["inputs"]["prompt"])

    def test_real_assets_stay_ordered_and_graybox_is_motion_only(self) -> None:
        images = ["pilot/character.png", "pilot/scene.png"]
        still = build_real_graph(images, None)
        moving = build_real_graph(images, "pilot/blender-preview.mp4")

        for graph in (still, moving):
            self.assertEqual(graph["20"]["inputs"]["image"], images[0])
            self.assertEqual(graph["21"]["inputs"]["image"], images[1])
            self.assertEqual(graph["5"]["inputs"]["ref_images.ref_image_0"], ["20", 0])
            self.assertEqual(graph["5"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
            self.assertIn("<Picture 1>", graph["5"]["inputs"]["prompt"])
            self.assertIn("<Picture 2>", graph["5"]["inputs"]["prompt"])
            self.assertNotIn("first-frame", json.dumps(graph))
        self.assertEqual(still["1"], moving["1"])
        self.assertEqual(still["8"], moving["8"])
        self.assertEqual(set(moving) - set(still), {"18", "19"})
        self.assertEqual(
            {node_id for node_id in still if still[node_id] != moving[node_id]},
            {"5"},
        )
        self.assertNotIn("ref_videos.ref_video_0", still["5"]["inputs"])
        self.assertEqual(moving["5"]["inputs"]["ref_videos.ref_video_0"], ["19", 0])
        self.assertIn("only camera path", moving["5"]["inputs"]["prompt"])

    def test_video_arm_adds_only_native_video_reference_chain(self) -> None:
        still = build_pilot_graph("pilot/first-frame.png", None)
        moving = build_pilot_graph("pilot/first-frame.png", "pilot/blender-preview.mp4")

        self.assertEqual(still["1"], moving["1"])
        self.assertEqual(still["8"], moving["8"])
        self.assertEqual(still["20"], moving["20"])
        self.assertNotIn("ref_videos.ref_video_0", still["5"]["inputs"])
        self.assertEqual(moving["18"], {
            "class_type": "LoadVideo", "inputs": {"file": "pilot/blender-preview.mp4"}
        })
        self.assertEqual(moving["19"], {
            "class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}
        })
        self.assertEqual(moving["5"]["inputs"]["ref_videos.ref_video_0"], ["19", 0])
        self.assertIn("<Video 1>", moving["5"]["inputs"]["prompt"])

    def test_missing_remote_video_node_is_reported_before_submission(self) -> None:
        session = Mock()

        def get(url: str, timeout: int):
            response = Mock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            name = url.rsplit("/", 1)[-1]
            response.json.return_value = {} if name == "LoadVideo" else {name: {}}
            return response

        session.get.side_effect = get
        with self.assertRaisesRegex(RuntimeError, "LoadVideo"):
            preflight(session, "http://configured-remote:8188")

    def test_remote_without_video_input_is_rejected(self) -> None:
        session = Mock()

        def get(url: str, timeout: int):
            response = Mock()
            response.raise_for_status.return_value = None
            name = url.rsplit("/", 1)[-1]
            response.json.return_value = {name: {"input": {"optional": {}}}} if name in REQUIRED_NODES else {}
            return response

        session.get.side_effect = get
        with self.assertRaisesRegex(RuntimeError, "ref_videos"):
            preflight(session, "http://configured-remote:8188")


if __name__ == "__main__":
    unittest.main()
