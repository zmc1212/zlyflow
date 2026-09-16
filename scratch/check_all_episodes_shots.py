import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService
from server.services.episode_video_service import EpisodeVideoService

assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")
eps = ProjectDetailService.list_episodes("proj-ebaf2e7234584b39")
for ep in eps:
    detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", ep["id"])
    try:
        shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="proj-ebaf2e7234584b39")
        print(f"Ep {ep['id']} (no. {detail.get('number')}): OK, {len(shots)} shots")
    except Exception as e:
        print(f"Ep {ep['id']} (no. {detail.get('number')}): ERROR: {e}")
