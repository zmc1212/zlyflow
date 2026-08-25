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

    # 按照提示词将数据库中失败的任务分组
    jobs_by_prompt = {}
    for job_id, prompt_text in jobs:
        if not prompt_text:
            continue
        jobs_by_prompt.setdefault(prompt_text, []).append(job_id)

    matched = 0
    
    # 按照提示词将 ComfyUI 历史记录分组
    history_by_prompt = {}
    for prompt_id, data in history.items():
        try:
            workflow = data["prompt"][2]
            for node_id, node in workflow.items():
                if node.get("class_type") in ["MiniMaxH3ReferenceToVideo", "MiniMaxH3ImageToVideo", "MiniMaxH3TextToVideo"]:
                    p = node.get("inputs", {}).get("prompt")
                    if p:
                        history_by_prompt.setdefault(p, []).append(prompt_id)
        except Exception:
            pass

    # 针对每种提示词进行一对一绑定
    for prompt_text, job_ids in jobs_by_prompt.items():
        matches = history_by_prompt.get(prompt_text, [])
        if not matches:
            continue
            
        # 如果有重复重试的任务，直接按顺序一对一配对
        pairs = zip(job_ids, matches)
        for job_id, comfy_prompt_id in pairs:
            print(f"[+] 成功匹配任务 {job_id} -> ComfyUI Prompt ID: {comfy_prompt_id}")
            db.execute("UPDATE generation_items SET comfy_prompt_id = ?, status = 'interrupted' WHERE id = ?", (comfy_prompt_id, job_id))
            matched += 1
            
        if len(matches) > len(job_ids):
            print(f"[*] 提示词 '{prompt_text[:10]}...' 在 ComfyUI 中有 {len(matches)} 个记录，但工作台只有 {len(job_ids)} 个失败任务，多余的记录将被忽略。")
        elif len(job_ids) > len(matches):
            print(f"[-] 提示词 '{prompt_text[:10]}...' 在工作台有 {len(job_ids)} 个失败任务，但 ComfyUI 只有 {len(matches)} 个记录，部分任务无法恢复。")

    if matched > 0:
        db.commit()
        print(f"\n[*] 抢救完成！成功强行找回 {matched} 个任务的关联 ID。请重启本地视频工作台以生效。")
    else:
        print("\n[*] 抢救结束。未能在当前的 ComfyUI 内存历史中找到任何匹配记录（ComfyUI 可能已被重启）。")

if __name__ == "__main__":
    main()
