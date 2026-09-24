"""Render the MCP-created .blend to a silent 24 fps MP4 and review frames."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw


def render(output_dir: Path, blender_exe: Path, ffmpeg_exe: Path) -> None:
    scene = output_dir / "corridor-previs.blend"
    if not scene.is_file():
        raise FileNotFoundError(f"先通过 MCP 创建场景：{scene}")
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (output_dir / "blender-render.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(blender_exe), "-b", str(scene), "-a"], check=True, stdout=log, stderr=subprocess.STDOUT)
    frames = sorted((output_dir / "frames").glob("frame-*.png"))
    if len(frames) != 124:
        raise RuntimeError(f"预期 124 帧，实际 {len(frames)} 帧")
    video = output_dir / "blender-preview.mp4"
    subprocess.run(
        [str(ffmpeg_exe), "-hide_banner", "-loglevel", "error", "-y", "-framerate", "24",
         "-i", str(output_dir / "frames" / "frame-%04d.png"), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-crf", "18", str(video)],
        check=True,
    )
    selected = [frames[index] for index in (0, 30, 61, 92, 123)]
    canvas = Image.new("RGB", (608 * len(selected), 386), "white")
    draw = ImageDraw.Draw(canvas)
    for index, frame in enumerate(selected):
        with Image.open(frame) as image:
            canvas.paste(image.convert("RGB"), (608 * index, 0))
        draw.text((608 * index + 8, 357), f"Blender frame {int(frame.stem.split('-')[-1])}", fill="black")
    canvas.save(output_dir / "blender-contact-sheet.png")
    (output_dir / "render-seconds.txt").write_text(str(round(time.monotonic() - started, 2)), encoding="utf-8")
    print(f"预演渲染完成：{video}，{len(frames)} 帧")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    default_blender = (Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Blender 5.2.2"
                       / "Blender Foundation" / "Blender 5.2" / "blender.exe")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=root / "test-results" / "blender-h3")
    parser.add_argument("--blender", type=Path, default=default_blender)
    parser.add_argument("--ffmpeg", type=Path, default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.blender.is_file() or not args.ffmpeg or not args.ffmpeg.is_file():
        raise FileNotFoundError("未找到 Blender 5.2 或 FFmpeg 可执行文件")
    render(args.output_dir.resolve(), args.blender.resolve(), args.ffmpeg.resolve())


if __name__ == "__main__":
    main()
