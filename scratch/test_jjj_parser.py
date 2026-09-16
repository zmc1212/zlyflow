from __future__ import annotations

import re
from pathlib import Path

def parse_jjj_prompts() -> dict[int, dict[int, str]]:
    content = Path("doc/jjj.md").read_text(encoding="utf-8")
    # Matches # 第1集 ... up to next # 第 or end
    ep_pattern = re.compile(r"^# 第(\d+)集[：:](.*?)(?=^# 第\d+集|^# |\Z)", re.MULTILINE | re.DOTALL)
    shot_pattern = re.compile(r"^### 镜头(\d+)[｜|](.*?)(?=^### 镜头|\Z)", re.MULTILINE | re.DOTALL)
    prompt_pattern = re.compile(r"- H3视频生成提示词[：:]\s*```(?:text)?\s*\n(.*?)\n```", re.DOTALL)

    result: dict[int, dict[int, str]] = {}
    for ep_match in ep_pattern.finditer(content):
        ep_num = int(ep_match.group(1))
        ep_body = ep_match.group(2)
        result[ep_num] = {}
        for shot_match in shot_pattern.finditer(ep_body):
            shot_num = int(shot_match.group(1))
            shot_body = shot_match.group(2)
            pm = prompt_pattern.search(shot_body)
            if pm:
                result[ep_num][shot_num] = pm.group(1).strip()
    return result

if __name__ == "__main__":
    prompts = parse_jjj_prompts()
    print(f"Parsed {len(prompts)} episodes:")
    for ep, shots in sorted(prompts.items()):
        print(f"Episode {ep}: {len(shots)} shots")
        for s, p in sorted(shots.items()):
            first_line = p.splitlines()[0] if p else ""
            print(f"  Shot {s}: length={len(p)}, first_line={first_line}")
