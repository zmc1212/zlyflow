import re
import sys
sys.path.insert(0, ".")
from scratch.test_jjj_parser import parse_jjj_prompts

def clean_dialogue(text: str, speaker: str = "") -> str:
    s = str(text or "").strip()
    if speaker:
        s = re.sub(rf"^{re.escape(speaker)}[：:]\s*", "", s).strip()
    s = re.sub(r'^[“"\'「](.*?)[”"\'」]$', r'\1', s).strip()
    return s

prompts = parse_jjj_prompts()
for ep, shots in sorted(prompts.items()):
    for s, p in sorted(shots.items()):
        d_tags = re.findall(r"<d>\[Chinese\]\s*(.*?)\s*</d>", p)
        print(f"Ep {ep} Shot {s} tags: {d_tags}")
