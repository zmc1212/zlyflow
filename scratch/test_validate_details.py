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
speaker_map = H3PromptBuilder._speaker_map(shots)
prompts = [jjj_prompts[1][shot["sequence"]] for shot in shots]

for i, (shot, prompt) in enumerate(zip(shots, prompts)):
    errs = H3PromptBuilder.validate_prompts([shot], [prompt], speaker_map)
    print(f"Shot {i+1} errs count: {len(errs)}")
    for e in errs:
        print(f"  - {e}")
