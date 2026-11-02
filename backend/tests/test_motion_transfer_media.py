from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.app.motion_transfer_media import prepare_motion_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration")
class MotionVideoPreparationTests(unittest.TestCase):
    def test_clips_and_resamples_the_pose_window_instead_of_loading_the_entire_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            output = Path(directory) / "prepared.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=64x48:rate=30", "-t", "6", "-c:v", "libx264", str(source)],
                           check=True, capture_output=True)
            prepare_motion_video(source, output, fps=24, length=124)
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                     "stream=codec_type,r_frame_rate,nb_frames:format=duration", "-of", "json", str(output)],
                                    check=True, capture_output=True, text=True)
            data = json.loads(result.stdout)
            self.assertEqual(len(data["streams"]), 1)
            self.assertEqual(data["streams"][0]["r_frame_rate"], "24/1")
            self.assertEqual(int(data["streams"][0]["nb_frames"]), 124)
            self.assertAlmostEqual(float(data["format"]["duration"]), 124 / 24, places=2)


if __name__ == "__main__":
    unittest.main()
