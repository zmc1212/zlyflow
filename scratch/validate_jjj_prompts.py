import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService
from server.services.episode_video_service import EpisodeVideoService
from server.services.h3_prompt_builder import H3PromptBuilder
from scratch.test_jjj_parser import parse_jjj_prompts

jjj_prompts = parse_jjj_prompts()
assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")

# Validate Episode 1
detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
ep_num = int(detail.get("number") or 1)
shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="proj-ebaf2e7234584b39")
print(f"Episode {ep_num} prepared {len(shots)} shots")

prompts_for_ep = [jjj_prompts[ep_num][shot["sequence"]] for shot in shots]
speaker_map = H3PromptBuilder._speaker_map(shots)
print("Speaker map:", speaker_map)

errors = H3PromptBuilder.validate_prompts(shots, prompts_for_ep, speaker_map)
print("Validation errors:", errors)
