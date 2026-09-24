"""Send the fixed shot design to the running localhost mcp-for-blender addon."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def create_scene(output_dir: Path) -> None:
    started = time.monotonic()
    recipe = Path(__file__).with_name("scene_recipe.py").read_text(encoding="utf-8")
    code = f"OUTPUT_DIR = {str(output_dir)!r}\n" + recipe
    env = dict(os.environ)
    env.update({"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": "9876", "DISABLE_TELEMETRY": "true"})
    server = StdioServerParameters(
        command="uvx",
        args=["--from", "mcp-for-blender==2.0.3", "mcp-for-blender"],
        env=env,
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=5)) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            names = {tool.name for tool in tools}
            if "execute_blender_code" not in names:
                raise RuntimeError(f"mcp-for-blender 未提供 execute_blender_code；当前工具：{sorted(names)}")
            result = await session.call_tool("execute_blender_code", {"code": code})
            if result.isError:
                raise RuntimeError("Blender MCP 执行失败：" + " ".join(str(c) for c in result.content)[:1500])
            (output_dir / "mcp-seconds.txt").write_text(
                str(round(time.monotonic() - started, 2)), encoding="utf-8"
            )
            print("Blender MCP 场景制作完成")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=root / "test-results" / "blender-h3")
    args = parser.parse_args()
    asyncio.run(create_scene(args.output_dir.resolve()))


if __name__ == "__main__":
    main()
