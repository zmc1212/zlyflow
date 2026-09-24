"""Pull reviewed action plans and render them through the local Blender MCP addon.

Run this on the Windows Blender host; no inbound network port is required except
the mcp-for-blender addon listening on localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import socket
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

# The ComfyUI portable Python is an embedded 3.10 build without venv. Keep this
# worker's dependencies in its own vendor directory instead of changing the
# integrated package's site-packages.
_VENDOR = Path(os.getenv("ZLY_ACTION_VENDOR_DIR") or Path(__file__).with_name("vendor"))
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR.resolve()))
    if sys.platform == "win32":
        pywin32_dir = _VENDOR / "pywin32_system32"
        if pywin32_dir.is_dir():
            os.add_dll_directory(str(pywin32_dir.resolve()))
        for subdir in ("win32", "win32/lib", "Pythonwin"):
            path = _VENDOR / subdir
            if path.is_dir():
                sys.path.insert(0, str(path.resolve()))

import requests

ARTIFACTS = {"video": "preview.mp4", "blend": "scene.blend", "contact_sheet": "contact_sheet.jpg", "report": "report.json"}


def executable(name: str, setting: str) -> str | None:
    configured = os.getenv(setting, "").strip()
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() else None
    return shutil.which(name)


class Api:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def post(self, path: str, data: dict) -> dict:
        response = self.session.post(self.base + path, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def upload(self, path: str, file: Path, lease: str) -> None:
        with file.open("rb") as body:
            response = self.session.put(self.base + path, data=body,
                                        headers={"X-Action-Lease": lease}, timeout=180)
        response.raise_for_status()


def preflight(asset: Path) -> dict:
    checks = {
        "python": sys.version.split()[0],
        "makehuman_fbx": str(asset) if asset.is_file() else None,
        "uvx": executable("uvx", "ZLY_ACTION_UVX_PATH"),
        "ffmpeg": executable("ffmpeg", "ZLY_ACTION_FFMPEG_PATH"),
        "mcp_python": importlib.util.find_spec("mcp") is not None,
        "blender_mcp_localhost": False,
    }
    try:
        with socket.create_connection(("127.0.0.1", int(os.getenv("ZLY_ACTION_MCP_PORT", "9876"))), timeout=2):
            checks["blender_mcp_localhost"] = True
    except OSError:
        pass
    return {"ready": all(checks[k] for k in ("makehuman_fbx", "uvx", "ffmpeg", "mcp_python", "blender_mcp_localhost")),
            "checks": checks}


async def render_through_mcp(plan: dict, asset: Path, output: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    output.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS.values():
        (output / name).unlink(missing_ok=True)
    recipe = Path(__file__).with_name("scene_recipe.py").read_text(encoding="utf-8")
    # The plan has already passed the backend's bounded JSON schema. No model
    # authored Python is ever sent to Blender.
    code = "PLAN = json.loads(" + repr(json.dumps(plan, ensure_ascii=False)) + ")\n"
    code += "ASSET_PATH = " + repr(str(asset)) + "\nOUTPUT_DIR = " + repr(str(output)) + "\n"
    code += "FFMPEG_PATH = " + repr(executable("ffmpeg", "ZLY_ACTION_FFMPEG_PATH")) + "\n"
    code = "import json\n" + code + recipe
    env = dict(os.environ)
    env.update({"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": os.getenv("ZLY_ACTION_MCP_PORT", "9876"),
                "DISABLE_TELEMETRY": "true"})
    server = StdioServerParameters(command=executable("uvx", "ZLY_ACTION_UVX_PATH") or "uvx",
                                  args=["--from", "mcp-for-blender==2.0.3", "mcp-for-blender"], env=env)
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=40)) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            if "execute_blender_code" not in names:
                raise RuntimeError("mcp-for-blender 缺少 execute_blender_code")
            result = await session.call_tool("execute_blender_code", {"code": code})
            detail = " ".join(getattr(block, "text", "") for block in result.content)
            if result.isError or detail.startswith("Error executing code:"):
                raise RuntimeError("Blender MCP 执行失败：" + detail[:1600])
    missing = [name for name in ARTIFACTS.values() if not (output / name).is_file()]
    if missing:
        raise RuntimeError("Blender 未输出完整产物：" + ", ".join(missing) + "；MCP 返回：" + detail[:1600])


def run_job(api: Api, job: dict, asset: Path, root: Path) -> None:
    project_id, job_id, lease = (str(job[key]) for key in ("project_id", "job_id", "lease_token"))
    stem = f"/api/internal/action-previs/{project_id}/{job_id}"
    output = root / job_id
    output.mkdir(parents=True, exist_ok=True)
    done = threading.Event()
    cancelled = threading.Event()

    def heartbeat() -> None:
        while not done.wait(30):
            try:
                state = api.post(stem + "/heartbeat", {"lease_token": lease, "progress": 55, "stage": "rendering"})
                if state.get("cancelled"):
                    cancelled.set()
                    return
            except requests.RequestException as exc:
                print(f"心跳暂时失败：{exc}", flush=True)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        asyncio.run(render_through_mcp(job["plan"], asset, output))
        if cancelled.is_set():
            print(f"{job_id} 已取消，丢弃渲染结果", flush=True)
            return
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        for slot, name in ARTIFACTS.items():
            api.upload(stem + f"/artifacts/{slot}", output / name, lease)
        api.post(stem + "/complete", {"lease_token": lease, "report": report})
        print(f"{job_id} 已回传，passed={report.get('passed')}", flush=True)
    except Exception as exc:
        print(f"{job_id} 失败：{exc}", file=sys.stderr, flush=True)
        try:
            api.post(stem + "/fail", {"lease_token": lease, "message": str(exc)[:1600]})
        except requests.RequestException:
            pass
    finally:
        done.set()
        thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Render bundled two-rig, three-camera diagnostic plan")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "test-results" / "action-previs")
    args = parser.parse_args()
    asset = Path(os.getenv("ZLY_ACTION_MAKEHUMAN_FBX", "")).expanduser()
    checks = preflight(asset)
    print(json.dumps(checks, ensure_ascii=False, indent=2), flush=True)
    if args.preflight:
        sys.exit(0 if checks["ready"] else 2)
    if not checks["ready"]:
        sys.exit("远端 Blender 预检未通过")
    if args.smoke:
        sample = json.loads(Path(__file__).with_name("smoke_plan.json").read_text(encoding="utf-8"))
        target = args.output_dir / "smoke"
        target.mkdir(parents=True, exist_ok=True)
        asyncio.run(render_through_mcp(sample, asset, target))
        print((target / "report.json").read_text(encoding="utf-8"), flush=True)
        return
    base = os.getenv("ZLY_ACTION_STUDIO_URL", "").strip()
    token = os.getenv("ZLY_ACTION_PREVIS_WORKER_TOKEN", "").strip()
    if not base.startswith(("http://", "https://")) or not token:
        sys.exit("请配置 ZLY_ACTION_STUDIO_URL 与 ZLY_ACTION_PREVIS_WORKER_TOKEN")
    api = Api(base, token)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    worker_id = socket.gethostname() + "-" + str(os.getpid())
    while True:
        try:
            job = api.post("/api/internal/action-previs/claim", {"worker_id": worker_id}).get("job")
            if job:
                run_job(api, job, asset, args.output_dir)
            elif args.once:
                return
            else:
                time.sleep(10)
        except requests.RequestException as exc:
            print(f"领取任务失败：{exc}", file=sys.stderr, flush=True)
            if args.once:
                raise
            time.sleep(15)
        if args.once:
            return


if __name__ == "__main__":
    main()
