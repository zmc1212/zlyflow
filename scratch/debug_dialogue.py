import json
import sys
import re
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService
from server.services.episode_video_service import EpisodeVideoService
from server.services.h3_prompt_builder import H3PromptBuilder
from scratch.test_jjj_parser import parse_jjj_prompts

jjj_prompts = parse_jjj_prompts()
assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")
detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="proj-ebaf2e7234584b39")
speaker_map = H3PromptBuilder._speaker_map(shots)
prompts = [jjj_prompts[1][shot["sequence"]] for shot in shots]

for i, s in enumerate(shots):
    p = prompts[i]
    turns = H3PromptBuilder._dialogue_turns(s)
    expected_dialogue = {str(turn.get("text") or "").strip() for turn in turns}
    actual_dialogue = {
        value.strip() for value in re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", p, flags=re.S)
        if value.strip()
    }
    with open("scratch/debug_dialogue.txt", "w", encoding="utf-8") as f:
        f.write(f"expected: {expected_dialogue}\n")
        f.write(f"actual: {actual_dialogue}\n")
        f.write(f"diff actual-expected: {actual_dialogue - expected_dialogue}\n")
        f.write(f"diff expected-actual: {expected_dialogue - actual_dialogue}\n")
    break
