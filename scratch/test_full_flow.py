import json
import sys
import re
from pathlib import Path
sys.path.insert(0, ".")

from server.services.project_detail_service import ProjectDetailService
from server.services.episode_video_service import EpisodeVideoService
from server.services.h3_prompt_builder import H3PromptBuilder

assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")
detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="proj-ebaf2e7234584b39")
print("Shots prepared successfully:", len(shots))

# Parse jjj prompts
parsed = EpisodeVideoService._parse_jjj_markdown()
ep_num = int(detail.get("number") or 1)
ep_shots = parsed.get(ep_num)
print("JJJ prompts found for ep:", len(ep_shots) if ep_shots else 0)

prompts = [ep_shots[shot["sequence"]] for shot in shots]
speaker_map = H3PromptBuilder._speaker_map(shots)
print("Speaker map:", speaker_map)

# Validate with min_english_words=200
errs = H3PromptBuilder.validate_prompts(shots, prompts, speaker_map, min_english_words=200)
print("Validation errors with min_english_words=200:", errs)
