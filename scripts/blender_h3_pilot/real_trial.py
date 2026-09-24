"""Compare real-world visual references with and without Blender camera previs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import pymysql
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.media_studio.db import get_mysql_config  # noqa: E402
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient  # noqa: E402
from backend.app.minimax_h3_workflow import build_minimax_h3_workflow  # noqa: E402
from backend.app.models import JobMode  # noqa: E402
from scripts.blender_h3_pilot.pilot import (  # noqa: E402
    OPTIONS,
    SEED,
    effective_comfy_url,
    preflight,
    upload_file,
)

PROMPT = (
    "[reference generation] [Shot 1] A photoreal live-action scene. "
    "<Picture 1> defines the sole adult woman's identity, face, hair, and clothing. "
    "<Picture 2> defines the real apartment corridor, wall color, doors, practical lights, "
    "floor, and materials. Place the woman at the far end of that corridor. "
    "One continuous shot: the camera dollies forward and gently tracks right. "
    "A near foreground structural pillar passes across the lens, briefly occluding the woman, "
    "then clears to reveal her again. Keep the corridor axis, camera direction, pillar crossing, "
    "subject screen position, and perspective shift coherent. Natural photographic texture, "
    "real human anatomy and skin. No animation, CG, gray blocks, cuts, zoom, camera shake, "
    "extra people, or scene change. Ambient room tone, no speech."
)
VIDEO_ROLE = (
    " <Video 1> supplies only camera path, lens framing, spatial blocking and pillar occlusion "
    "timing. It is a graybox motion guide: use the person and location from <Picture 1> and "
    "<Picture 2> for every visible appearance, material and color."
)


def build_real_graph(image_filenames: list[str], video_filename: str | None, *, seed: int = SEED) -> dict:
    if len(image_filenames) != 2:
        raise ValueError("真实素材试验需要有序的人物图和场景图各一张")
    graph = build_minimax_h3_workflow(
        JobMode.MINIMAX_H3_R2V,
        PROMPT + (VIDEO_ROLE if video_filename else ""),
        image_filenames,
        dict(OPTIONS),
        seed,
    )
    if video_filename:
        graph["18"] = {"class_type": "LoadVideo", "inputs": {"file": video_filename}}
        graph["19"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}}
        graph["5"]["inputs"]["ref_videos.ref_video_0"] = ["19", 0]
    return graph


def fetch_project_asset(session: requests.Session, project_id: str, kind: str, name: str, target: Path) -> dict:
    connection = pymysql.connect(**get_mysql_config(), connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, image_url FROM ai_project_assets "
                "WHERE project_id=%s AND kind=%s AND name=%s AND image_url IS NOT NULL "
                "AND image_url <> '' ORDER BY updated_at DESC LIMIT 1",
                (project_id, kind, name),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    if not row:
        raise ValueError(f"资产库缺少 {kind}：{name} ({project_id})")
    asset_id, url = row
    response = session.get(url, timeout=60)
    response.raise_for_status()
    if not response.headers.get("content-type", "").startswith("image/"):
        raise ValueError(f"资产不是图片：{kind} {name}")
    target.write_bytes(response.content)
    return {"id": asset_id, "kind": kind, "name": name, "source_url": url, "file": target.name}


def run(output_dir: Path, *, project_id: str, character: str, scene: str,
        scene_image: Path | None, generate: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_previs = ROOT / "test-results" / "blender-h3" / "blender-preview.mp4"
    if not source_previs.is_file():
        raise FileNotFoundError(source_previs)
    motion_path = output_dir / "blender-preview.mp4"
    if not motion_path.exists():
        shutil.copy2(source_previs, motion_path)
    base_url = effective_comfy_url()
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    session = requests.Session()
    try:
        capability = preflight(session, base_url)
        character_path = output_dir / "character.png"
        scene_path = output_dir / "scene.png"
        source_scene_path = output_dir / "scene-source.png" if scene_image else scene_path
        assets = [
            fetch_project_asset(session, project_id, "character", character, character_path),
            fetch_project_asset(session, project_id, "scene", scene, source_scene_path),
        ]
        if scene_image:
            if not scene_image.is_file():
                raise FileNotFoundError(scene_image)
            if scene_image.resolve() != scene_path.resolve():
                shutil.copy2(scene_image, scene_path)
            assets[1]["derived_file"] = scene_path.name
        manifest.update({
            "capability": capability,
            "assets": assets,
            "seed": SEED,
            "options": OPTIONS,
            "prompt": PROMPT,
            "video_role": VIDEO_ROLE,
            "motion_video": motion_path.name,
        })
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if not generate:
            print(f"素材与远端能力预检通过：{base_url}；使用 --generate 提交 A/B")
            return
        subfolder = f"zly-ai-media/blender-h3-real/{uuid.uuid4().hex[:12]}"
        images = [upload_file(session, base_url, path, subfolder) for path in (character_path, scene_path)]
        video = upload_file(session, base_url, motion_path, subfolder)
        client = ComfyVideoClient(base_url)
        results = dict(manifest.get("results") or {})
        for arm, motion_reference in (("A", None), ("B", video)):
            output_path = output_dir / f"h3-{arm}.mp4"
            if output_path.is_file() and results.get(arm, {}).get("status") == "succeeded":
                print(f"{arm} 已完成，跳过重复生成")
                continue
            graph = build_real_graph(images, motion_reference)
            graph["14"]["inputs"]["filename_prefix"] = f"video/blender-h3-real/{arm.lower()}"
            (output_dir / f"graph-{arm}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
            start = time.monotonic()
            print(f"提交 {arm} 组到 {base_url}", flush=True)
            try:
                submitted, _, output = client.submit_and_wait(graph)
                output_path.write_bytes(client.download_output(output))
                results[arm] = {
                    "status": "succeeded", "prompt_id": submitted["prompt_id"],
                    "seconds": round(time.monotonic() - start, 2), "file": output_path.name,
                }
            except Exception as error:
                results[arm] = {
                    "status": "failed", "seconds": round(time.monotonic() - start, 2),
                    "error": str(error),
                }
                raise
            finally:
                manifest["results"] = results
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"真实素材 A/B 生成结束：{output_dir}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test-results" / "blender-h3-real")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--scene-image", type=Path, help="可选：从原场景图处理的无人写实场景图")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    run(args.output_dir.resolve(), project_id=args.project_id, character=args.character,
        scene=args.scene, scene_image=args.scene_image, generate=args.generate)


if __name__ == "__main__":
    main()
