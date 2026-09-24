"""Run an isolated A/B H3 camera-reference experiment against configured ComfyUI."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.media_studio.provider_bridge import comfy_row  # noqa: E402
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient  # noqa: E402
from backend.app.minimax_h3_workflow import build_minimax_h3_workflow  # noqa: E402
from backend.app.models import JobMode  # noqa: E402

REQUIRED_NODES = (
    "MiniMaxH3ReferenceToVideo",
    "LoadVideo",
    "GetVideoComponents",
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "ReservedVRAMSetter",
    "MiniMaxH3MemoryEfficientSageAttentionPatch",
)
SEED = 270923
OPTIONS = {
    "aspect_ratio": "16:9",
    "megapixels": 0.2,
    "duration": 5,
    "steps": 20,
    "lora_strength": 0,
    "reference_image_size": "match",
    "use_sage_attention": True,
}
PROMPT = (
    "[reference generation] [Shot 1] A lone adult in a simple dark outfit stands at the far end "
    "of a sparse industrial corridor. One continuous shot: the camera dollies forward and gently "
    "tracks to the right. A near foreground pillar crosses the lens, briefly occludes the person, "
    "then clears to reveal the person again. Keep the corridor axis, camera direction, pillar "
    "crossing, subject screen position, and perspective shift coherent. Natural cinematic lighting. "
    "No cuts, zoom, camera shake, extra people, or scene change. Ambient room tone, no speech."
)


def effective_comfy_url() -> str:
    """Use the same persisted provider setting as the production video services."""
    value = str(comfy_row().get("base_url") or "").strip().rstrip("/")
    if not value:
        raise RuntimeError("当前未配置 ComfyUI 地址")
    return value


def preflight(session: requests.Session, base_url: str) -> dict[str, object]:
    """Check the current remote instance without installing or changing nodes."""
    stats_response = session.get(f"{base_url}/system_stats", timeout=15)
    stats_response.raise_for_status()
    nodes: dict[str, bool] = {}
    for name in REQUIRED_NODES:
        response = session.get(f"{base_url}/object_info/{name}", timeout=15)
        response.raise_for_status()
        nodes[name] = name in response.json()
    missing = [name for name, present in nodes.items() if not present]
    if missing:
        raise RuntimeError(f"当前远端 ComfyUI 缺少节点：{', '.join(missing)}")
    info = session.get(f"{base_url}/object_info/MiniMaxH3ReferenceToVideo", timeout=15).json()
    optional = (info["MiniMaxH3ReferenceToVideo"].get("input") or {}).get("optional") or {}
    if "ref_videos" not in optional:
        raise RuntimeError("当前远端 H3 R2V 节点没有 ref_videos 输入")
    return {"base_url": base_url, "nodes": nodes, "reference_video_input": True}


def build_pilot_graph(image_filename: str, video_filename: str | None, *, seed: int = SEED) -> dict:
    """Keep both arms on the same R2V model, options, image, and seed."""
    prompt = PROMPT
    if video_filename:
        prompt += " <Video 1> is the moving camera and blocking blueprint for this shot."
    graph = build_minimax_h3_workflow(
        JobMode.MINIMAX_H3_R2V,
        prompt,
        [image_filename],
        dict(OPTIONS),
        seed,
    )
    if video_filename:
        graph["18"] = {"class_type": "LoadVideo", "inputs": {"file": video_filename}}
        graph["19"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}}
        graph["5"]["inputs"]["ref_videos.ref_video_0"] = ["19", 0]
    return graph


def upload_file(session: requests.Session, base_url: str, path: Path, subfolder: str) -> str:
    content_type = "video/mp4" if path.suffix.lower() == ".mp4" else "image/png"
    with path.open("rb") as source:
        response = session.post(
            f"{base_url}/upload/image",
            files={"image": (path.name, source, content_type)},
            data={"subfolder": subfolder, "type": "input", "overwrite": "true"},
            timeout=180,
        )
    response.raise_for_status()
    uploaded = response.json()
    name = str(uploaded.get("name") or path.name)
    folder = str(uploaded.get("subfolder") or subfolder).strip("/")
    return f"{folder}/{name}" if folder else name


def run(output_dir: Path, *, generate: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "first-frame.png"
    video_path = output_dir / "blender-preview.mp4"
    for path in (image_path, video_path):
        if not path.is_file():
            raise FileNotFoundError(f"缺少 Blender 预演产物：{path}")
    base_url = effective_comfy_url()
    session = requests.Session()
    manifest_path = output_dir / "manifest.json"
    try:
        capability = preflight(session, base_url)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        manifest.update({"capability": capability, "seed": SEED, "options": OPTIONS, "prompt": PROMPT})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if not generate:
            print(f"预检通过：{base_url}；使用 --generate 运行两组 H3 出片")
            return
        subfolder = f"zly-ai-media/blender-h3-pilot/{uuid.uuid4().hex[:12]}"
        uploaded_image = upload_file(session, base_url, image_path, subfolder)
        uploaded_video = upload_file(session, base_url, video_path, subfolder)
        client = ComfyVideoClient(base_url)
        results = dict(manifest.get("results") or {})
        for arm, video_reference in (("A", None), ("B", uploaded_video)):
            output_path = output_dir / f"h3-{arm}.mp4"
            if output_path.is_file() and results.get(arm, {}).get("status") == "succeeded":
                print(f"{arm} 已完成，跳过重复生成")
                continue
            graph = build_pilot_graph(uploaded_image, video_reference)
            graph["14"]["inputs"]["filename_prefix"] = f"video/blender-h3-pilot/{arm.lower()}"
            (output_dir / f"graph-{arm}.json").write_text(
                json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            started = time.monotonic()
            print(f"提交 {arm} 组到 {base_url}", flush=True)
            try:
                submitted, _, output = client.submit_and_wait(graph)
                output_path.write_bytes(client.download_output(output))
                results[arm] = {
                    "status": "succeeded",
                    "prompt_id": submitted["prompt_id"],
                    "seconds": round(time.monotonic() - started, 2),
                    "file": output_path.name,
                }
            except Exception as error:
                results[arm] = {
                    "status": "failed",
                    "seconds": round(time.monotonic() - started, 2),
                    "error": str(error),
                }
                raise
            finally:
                manifest["results"] = results
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"A/B 生成结束，结果：{output_dir}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test-results" / "blender-h3")
    parser.add_argument("--generate", action="store_true", help="预检通过后真实提交 A/B 两组视频")
    args = parser.parse_args()
    run(args.output_dir.resolve(), generate=args.generate)


if __name__ == "__main__":
    main()
