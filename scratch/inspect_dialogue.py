import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService
from server.services.episode_video_service import EpisodeVideoService
from server.services.h3_prompt_builder import H3PromptBuilder
from scratch.test_jjj_parser import parse_jjj_prompts

jjj_prompts = parse_jjj_prompts()
assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")
detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="proj-ebaf2e7234584b39")

for i, s in enumerate(shots):
    print(f"Shot {i+1} dialogue: {repr(s.get('dialogue'))}")
    p = jjj_prompts[1][i+1]
    import re
    d_tags = re.findall(r"<d>\[Chinese\]\s*(.*?)\s*</d>", p)
    print(f"Prompt dialogue tags: {d_tags}")
