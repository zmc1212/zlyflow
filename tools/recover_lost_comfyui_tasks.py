# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import requests

try:
    root_dir = Path(__file__).resolve().parents[1]
    if (root_dir / "backend").exists():
        sys.path.insert(0, str(root_dir))
except NameError:
    pass

if Path("/app/backend").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

from backend.app.config import settings
from backend.app.storage import JobStore

def main():
    comfy_url = settings.comfy_url
    store = JobStore(settings.runtime_database())
    try:
        stored = store.get_comfy_settings().get("base_url")
        if stored:
            comfy_url = str(stored).rstrip("/")
    except Exception:
        pass

    print(f"[*] 数据库: MySQL {settings.mysql_config['host']}:{settings.mysql_config['port']}/{settings.mysql_config['database']}")
    print(f"[*] ComfyUI 地址: {comfy_url}")

    with store.connection() as db:
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

        jobs_by_prompt = {}
        for row in jobs:
            prompt_text = row["prompt"]
            if not prompt_text:
                continue
            jobs_by_prompt.setdefault(prompt_text, []).append(row["id"])

        matched = 0
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

        for prompt_text, job_ids in jobs_by_prompt.items():
            matches = history_by_prompt.get(prompt_text, [])
            if not matches:
                continue
            pairs = zip(job_ids, matches)
            for job_id, comfy_prompt_id in pairs:
                print(f"[+] 成功匹配任务 {job_id} -> ComfyUI Prompt ID: {comfy_prompt_id}")
                db.execute(
                    "UPDATE generation_items SET comfy_prompt_id = ?, status = 'interrupted' WHERE id = ?",
                    (comfy_prompt_id, job_id),
                )
                matched += 1
            if len(matches) > len(job_ids):
                print(f"[*] 提示词 '{prompt_text[:10]}...' 在 ComfyUI 中有 {len(matches)} 个记录，但工作台只有 {len(job_ids)} 个失败任务，多余的记录将被忽略。")
            elif len(job_ids) > len(matches):
                print(f"[-] 提示词 '{prompt_text[:10]}...' 在工作台有 {len(job_ids)} 个失败任务，但 ComfyUI 只有 {len(matches)} 个记录，部分任务无法恢复。")

        if matched > 0:
            print(f"\n[*] 抢救完成！成功强行找回 {matched} 个任务的关联 ID。请重启本地视频工作台以生效。")
        else:
            print("\n[*] 抢救结束。未能在当前的 ComfyUI 内存历史中找到任何匹配记录（ComfyUI 可能已被重启）。")

if __name__ == "__main__":
    main()
