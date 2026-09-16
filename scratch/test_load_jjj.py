import re
from pathlib import Path

def parse_jjj_markdown():
    candidates = [
        Path("doc/jjj.md"),
        Path(__file__).resolve().parents[1] / "doc" / "jjj.md",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if not path:
        return {}
    content = path.read_text(encoding="utf-8")
    ep_pattern = re.compile(r"^# 第(\d+)集[：:](.*?)(?=^# 第\d+集|^# |\Z)", re.MULTILINE | re.DOTALL)
    shot_pattern = re.compile(r"^### 镜头(\d+)[｜|](.*?)(?=^### 镜头|\Z)", re.MULTILINE | re.DOTALL)
    prompt_pattern = re.compile(r"- H3视频生成提示词[：:]\s*```(?:text)?\s*\n(.*?)\n```", re.DOTALL)

    result = {}
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

parsed = parse_jjj_markdown()
print("Parsed episodes:", list(parsed.keys()))
for ep, shots in parsed.items():
    print(f"Episode {ep}: shots {list(shots.keys())}")
