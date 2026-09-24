"""Create a compact three-row visual comparison of Blender, A, and B."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def extract(ffmpeg: Path, source: Path, seconds: float, target: Path) -> None:
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds),
         "-i", str(source), "-frames:v", "1", str(target)],
        check=True,
    )


def compare(output_dir: Path, ffmpeg: Path) -> Path:
    real_assets = output_dir.name == "blender-h3-real"
    sources = [
        ("Blender previs", output_dir / "blender-preview.mp4"),
        ("A: real images" if real_assets else "A: still", output_dir / "h3-A.mp4"),
        ("B: real images + previs" if real_assets else "B: still + video", output_dir / "h3-B.mp4"),
    ]
    for _, source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    times = (0.5, 3.0, 4.5) if real_assets else (0.5, 2.5, 4.5)
    width, height, label_height = 608, 352, 32
    sheet = Image.new("RGB", (width * len(times), (height + label_height) * len(sources)), "white")
    draw = ImageDraw.Draw(sheet)
    for row, (label, source) in enumerate(sources):
        for column, seconds in enumerate(times):
            frame = output_dir / f"compare-{row}-{column}.png"
            extract(ffmpeg, source, seconds, frame)
            with Image.open(frame) as image:
                fitted = image.convert("RGB").resize((width, height))
                sheet.paste(fitted, (column * width, row * (height + label_height)))
            draw.text(
                (column * width + 8, row * (height + label_height) + height + 6),
                f"{label} - {seconds:.1f}s", fill="black",
            )
            frame.unlink()
    path = output_dir / "comparison-contact-sheet.png"
    sheet.save(path)
    return path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=root / "test-results" / "blender-h3")
    parser.add_argument("--ffmpeg", type=Path, default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg or not args.ffmpeg.is_file():
        raise FileNotFoundError("未找到 FFmpeg")
    print(compare(args.output_dir.resolve(), args.ffmpeg.resolve()))


if __name__ == "__main__":
    main()
