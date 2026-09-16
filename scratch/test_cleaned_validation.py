import re
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

# Clean dialogue in shots
for shot in shots:
    speaker = shot.get("speaker") or ""
    dialogue = shot.get("dialogue") or ""
    if speaker:
        dialogue = re.sub(rf"^{re.escape(speaker)}[：:]\s*", "", dialogue).strip()
    dialogue = re.sub(r'^[“"\'「](.*?)[”"\'」]$', r'\1', dialogue).strip()
    shot["dialogue"] = dialogue

prompts = [jjj_prompts[1][shot["sequence"]] for shot in shots]
speaker_map = H3PromptBuilder._speaker_map(shots)

errs = H3PromptBuilder.validate_prompts(shots, prompts, speaker_map)
print("Validation errors after clean dialogue:", errs)
