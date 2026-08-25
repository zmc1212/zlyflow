# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import sqlite3
import requests

try:
    root_dir = Path(__file__).resolve().parents[1]
    if (root_dir / "backend").exists():
        sys.path.insert(0, str(root_dir))
except NameError:
    pass # __file__ not defined, rely on PYTHONPATH

# Docker 环境下通常已经在 /app 目录，不需要改 sys.path
if Path("/app/backend").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

from backend.app.config import settings

def main():
    db_path = settings.database_path
    comfy_url = settings.comfy_url

    print(f"[*] 数据库路径: {db_path}")
    print(f"[*] ComfyUI 地址: {comfy_url}")

    db = sqlite3.connect(db_path)
    
    # 查找所有已经失败并且没有 comfy_prompt_id 的任务
    jobs = db.execute(
        "SELECT i.id, r.prompt FROM generation_items i "
        "JOIN job_rounds r ON r.id = i.round_id "
        "WHERE i.status = 'failed' AND i.comfy_prompt_id IS NULL"
    ).fetchall()

    print(f"[*] 找到了 {len(jobs)} 个丢失了追踪 ID 的失败任务。")
    if not jobs:
        print("[*] 没有需要抢救的任务，退出。")
        return

    try:
        print("[*] 正在获取 ComfyUI 历史记录...")
        history = requests.get(f"{comfy_url}/history", timeout=(5, 30)).json()
    except Exception as e:
        print(f"[!] 无法连接到 ComfyUI ({comfy_url})，请确保它正在运行。错误信息: {e}")
        return

    matched = 0
    for job_id, prompt_text in jobs:
        if not prompt_text:
            continue
        
        matches = []
        for prompt_id, data in history.items():
            try:
                # ComfyUI 的历史记录结构中，prompt 字段的索引 2 为完整的 workflow JSON
                workflow = data["prompt"][2]
                for node_id, node in workflow.items():
                    # 匹配 MiniMax 系列的节点类名
                    if node.get("class_type") in ["MiniMaxH3ReferenceToVideo", "MiniMaxH3ImageToVideo", "MiniMaxH3TextToVideo"]:
                        # 比提示词是否完全一致
                        if node.get("inputs", {}).get("prompt") == prompt_text:
                            matches.append(prompt_id)
            except Exception:
                pass
                
        if len(matches) == 1:
            print(f"[+] 成功匹配任务 {job_id} -> ComfyUI Prompt ID: {matches[0]}")
            # 找回后，状态修改为 interrupted（中断），下次工作台重启或工作流轮询时就能自动重连
            db.execute("UPDATE generation_items SET comfy_prompt_id = ?, status = 'interrupted' WHERE id = ?", (matches[0], job_id))
            matched += 1
        elif len(matches) > 1:
            print(f"[-] 任务 {job_id} 匹配到 {len(matches)} 条 ComfyUI 记录，因为无法确定哪一条是正确的，为安全起见已跳过。")
        else:
            pass # 没找到就不打印了，避免日志过多

    if matched > 0:
        db.commit()
        print(f"\n[*] 抢救完成！成功强行找回 {matched} 个任务的关联 ID。请重启本地视频工作台以生效。")
    else:
        print("\n[*] 抢救结束。未能在当前的 ComfyUI 内存历史中找到任何匹配记录（ComfyUI 可能已被重启）。")

if __name__ == "__main__":
    main()
