#!/usr/bin/env python3
"""RelayVSR 远端 ComfyUI 只读探测器。

只发 GET 请求，不提交工作流、不改远端任何配置；本地也不写文件（除非显式 --report）。

检查项：
  1. 连通性与环境（/system_stats）：版本、Python、torch、GPU、显存
  2. 节点就位情况（/object_info）：已知三套 RelayVSR 社区节点包的特征节点逐个比对
  3. 模型目录就位情况（/models、/experiment/models、/models/<folder>）
  4. 权重文件对照：RelayVSR_X2 / RelayVSR_X4 / FL-RelayVSR 预期文件是否出现

用法：
  python tools/probe_relayvsr.py
  python tools/probe_relayvsr.py --url http://192.168.10.54:8188
  python tools/probe_relayvsr.py --report test-results/relayvsr-probe.md

退出码：0=全部就绪；1=有缺失（节点或模型）；2=连不上。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_URL = "http://192.168.10.54:8188"
USER_AGENT = "zly-relayvsr-probe/1.0 (read-only)"

# 已知社区节点包的特征节点：(object_info 的 node_id, 界面名, 来源包)
CANDIDATE_NODES: list[tuple[str, str, str]] = [
    ("RelayVSRModelLoader", "RelayVSR Model Loader", "Comfyui-Relay-VSR（注册 relayvsr 模型键）"),
    ("RelayVSRUpscale", "RelayVSR Upscale", "Comfyui-Relay-VSR（IMAGE 进 / IMAGE 出）"),
    ("RelayVSRUpscaleStreaming", "RelayVSR Upscale Streaming", "Comfyui-Relay-VSR（VIDEO 进 / 直接存文件）"),
    ("FLRelayVSRModelLoader", "FL RelayVSR Model Loader", "filliptm/ComfyUI-FL-RelayVSR（要求 Python 3.11+ 与 Triton）"),
    ("FLRelayVSRUpscale4x", "FL RelayVSR Upscale 4x", "filliptm/ComfyUI-FL-RelayVSR（固定 4×）"),
]

# 预期权重（bundle 目录, 文件名）。direct_read=True 表示该包直接按相对路径读文件，
# 不经过 ComfyUI 模型注册表，因此 /models 接口查不到。
BUNDLES: list[dict] = [
    {
        "label": "RelayVSR_X2（2×，LightX2V）",
        "folder": "relayvsr/RelayVSR_X2",
        "files": ["wan_x2.safetensors", "flash_x2.safetensors"],
        "direct_read": False,
    },
    {
        "label": "RelayVSR_X4（4×）",
        "folder": "relayvsr/RelayVSR_X4",
        "files": ["wan.safetensors", "flash.safetensors"],
        "direct_read": False,
    },
    {
        "label": "FL-RelayVSR（4×）",
        "folder": "RelayVSR",
        "files": ["wan.safetensors", "flash.safetensors"],
        "direct_read": True,
    },
]

# object_info 里除候选节点外，额外想确认的参照节点（判断实例是否已有别的 VSR 引擎）
REFERENCE_NODES = ["RTXVideoSuperResolution", "SeedVR2", "WavespeedFlashVSRNode"]


# ---------------------------------------------------------------- HTTP（只读）

def http_get(url: str, path: str, timeout: float) -> tuple[int, object]:
    """返回 (status, payload)。404 也当正常结果返回，便于判定“目录不存在”。"""
    req = urllib.request.Request(url.rstrip("/") + path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body) if body else None
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # 连接失败、超时等
        return -1, str(exc)


# ---------------------------------------------------------------- 输出排版

def disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - disp_width(text))


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [disp_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], disp_width(cell))
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [line, "| " + " | ".join(pad(h, widths[i]) for i, h in enumerate(headers)) + " |", line]
    for row in rows:
        out.append("| " + " | ".join(pad(c, widths[i]) for i, c in enumerate(row)) + " |")
    out.append(line)
    return "\n".join(out)


def mark(ok: bool | None) -> str:
    return {True: "OK   就位", False: "缺失   ", None: "-    无法判定"}[ok]


# ---------------------------------------------------------------- 各项探测

def probe_env(base: str, timeout: float) -> tuple[dict | None, list[list[str]]]:
    status, data = http_get(base, "/system_stats", timeout)
    if status != 200 or not isinstance(data, dict):
        return None, [["/system_stats", "200 JSON", f"{status} {data if status < 0 else ''}".strip(), "连不上"]]
    system = data.get("system") or {}
    devices = data.get("devices") or []
    rows = [
        ["ComfyUI 版本", "—", str(system.get("comfyui_version", "?")), "信息"],
        ["Python", "≥3.11（FL 包要求）", str(system.get("python_version", "?")).split(" ")[0], "信息"],
        ["PyTorch", "—", str(system.get("pytorch_version", "?")), "信息"],
    ]
    for dev in devices[:2]:
        total = dev.get("vram_total") or 0
        rows.append([
            f"设备 {dev.get('name', '?')}",
            "≥16GB（1080p 4× 需更多）",
            f"{total / 1024 ** 3:.1f} GB",
            "OK 够跑 2×" if total >= 15 * 1024 ** 3 else "注意：显存偏小",
        ])
    return data, rows


def probe_nodes(base: str, timeout: float) -> tuple[dict, list[list[str]], list[str]]:
    status, data = http_get(base, "/object_info", timeout)
    if status != 200 or not isinstance(data, dict):
        return {}, [[f"/object_info", "200 JSON", str(status), "读取失败"]], []
    node_types = set(data.keys())
    rows: list[list[str]] = []
    found: list[str] = []
    for node_id, display, pack in CANDIDATE_NODES:
        present = node_id in node_types
        if present:
            found.append(node_id)
        rows.append([f"{display}（{node_id}）", pack, "存在" if present else "不存在", mark(present)])
    for ref in REFERENCE_NODES:
        if ref in node_types:
            rows.append([f"（参照）{ref}", "既有引擎节点", "存在", "信息"])
    similar = sorted(n for n in node_types if "relay" in n.lower())
    return data, rows, similar + [n for n in found if n not in similar]


def probe_models(base: str, timeout: float) -> tuple[list[list[str]], dict[str, list[str]]]:
    rows: list[list[str]] = []
    listings: dict[str, list[str]] = {}

    status, folders = http_get(base, "/models", timeout)
    folder_list = folders if isinstance(folders, list) else []
    has_key = "relayvsr" in [str(f).lower() for f in folder_list]
    rows.append([
        "模型根目录键 `relayvsr`",
        "存在（bbaudio 包会注册）",
        "已注册" if has_key else "未注册",
        mark(has_key),
    ])

    status, exp = http_get(base, "/experiment/models", timeout)
    exp_paths: list[str] = []
    if isinstance(exp, list):
        for entry in exp:
            if str(entry.get("name", "")).lower() == "relayvsr":
                exp_paths = [str(p) for p in (entry.get("folders") or [])]
    rows.append([
        "`relayvsr` 物理目录",
        "至少 1 个可写路径",
        "；".join(exp_paths) if exp_paths else "无登记路径",
        mark(bool(exp_paths)),
    ])

    # /models/<root> 返回的是相对 root 的扁平列表（子目录以反斜杠分隔），
    # 所以按根键取一次，再按 bundle 子目录匹配。
    root_status, root_files = http_get(base, "/models/relayvsr", timeout)
    root_list = [str(f).replace("\\", "/") for f in root_files] if isinstance(root_files, list) else []
    for bundle in BUNDLES:
        folder = bundle["folder"]
        if bundle["direct_read"]:
            listings[folder] = []
            rows.append([
                bundle["label"],
                " + ".join(bundle["files"]),
                "该包直接读 models/RelayVSR，API 不可见，需人工核对",
                mark(None),
            ])
            continue
        sub = folder.split("/", 1)[1] if "/" in folder else ""
        prefix = f"{sub}/" if sub else ""
        matched = [name for name in bundle["files"] if any(path.endswith(prefix + name) for path in root_list)]
        available = len(matched) == len(bundle["files"])
        detail = (
            f"{len(matched)}/{len(bundle['files'])} 个文件"
            if root_status == 200
            else f"模型根键不可读（HTTP {root_status}）"
        )
        listings[folder] = root_list
        rows.append([bundle["label"], " + ".join(bundle["files"]), detail, mark(available)])
    return rows, listings


# ---------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RelayVSR 远端 ComfyUI 只读探测（不提交任务、不改远端）")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"ComfyUI 地址，默认 {DEFAULT_URL}")
    parser.add_argument("--timeout", type=float, default=40.0, help="单请求超时秒数，默认 40")
    parser.add_argument("--report", default="", help="可选：把对照表另存为 Markdown（建议放 test-results/）")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    started = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    out: list[str] = [f"# RelayVSR 远端只读探测", "", f"- 目标：`{base}`", f"- 时间：{started}", ""]

    env, env_rows = probe_env(base, args.timeout)
    if env is None:
        table = render_table(["检查项", "期望", "实测", "结论"], env_rows)
        print(table)
        msg = f"连不上 {base}：{env_rows[0][2]}"
        print(f"\n结论：{msg}")
        return 2

    object_info, node_rows, relay_hits = probe_nodes(base, args.timeout)
    model_rows, listings = probe_models(base, args.timeout)
    node_count = len(object_info) if object_info else None

    out += ["## 1. 环境", "", "```", render_table(["检查项", "期望", "实测", "结论"], env_rows), "```", ""]
    out += ["## 2. 节点", "", "```", render_table(["节点类名", "来源包", "实测", "结论"], node_rows), "```", ""]
    if relay_hits:
        out += [f"`object_info` 中名称含 relay 的节点：{', '.join(f'`{n}`' for n in relay_hits)}", ""]
    else:
        out += ["`object_info` 中没有任何名称含 `relay` 的节点。", ""]
    out += ["## 3. 模型", "", "```", render_table(["模型项", "期望", "实测", "结论"], model_rows), "```", ""]

    # 结论汇总
    pack_ready = any(n in relay_hits for n in ("RelayVSRModelLoader", "FLRelayVSRModelLoader"))
    x2_ready = any(r[0].startswith("RelayVSR_X2") and r[3].startswith("OK") for r in model_rows)
    x4_ready = any(r[0].startswith("RelayVSR_X4") and r[3].startswith("OK") for r in model_rows)
    python_note = ""
    py = ""
    for row in env_rows:
        if row[0] == "Python":
            py = row[2]
    if py and not py.startswith(("3.11", "3.12", "3.13", "3.14")):
        python_note = f"远端 Python 为 {py.split(' ')[0]}，低于 FL 包的 3.11+ 要求（bbaudio 包无此限制）。"

    verdict: list[str] = []
    verdict.append(f"- 节点：{'已装' if pack_ready else '未装任何 RelayVSR 节点'}；模型：{'2× 就位' if x2_ready else '2× 未就位'}，{'4× 就位' if x4_ready else '4× 未就位'}。")
    if node_count is not None:
        verdict.append(f"- 远端共 {node_count} 个节点类型。")
    if python_note:
        verdict.append(f"- 兼容性：{python_note}")
    if not (pack_ready and (x2_ready or x4_ready)):
        verdict.append("- 结论：**暂不可接入**，先在远端装节点并放权重，再复跑本脚本。")
    else:
        verdict.append("- 结论：**可以接入**，可按 `relay_vsr_workflow.py` 方案落地（仍需人工跑一段样片验证显存与出片）。")
    out += ["## 4. 结论", "", *verdict, ""]

    print("\n".join(out))

    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out))
            print(f"\n已写出报告：{args.report}")
        except OSError as exc:
            print(f"\n报告写入失败：{exc}")

    return 0 if (pack_ready and (x2_ready or x4_ready)) else 1


if __name__ == "__main__":
    sys.exit(main())
