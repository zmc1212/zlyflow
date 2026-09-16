import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService

eps = ProjectDetailService.list_episodes("proj-ebaf2e7234584b39")
for ep in eps:
    detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", ep["id"])
    print(f"Ep id={ep['id']} number={detail.get('number')}:")
    for b in detail.get("beats", []):
        print(f"  Beat seq={b.get('sequence')} speaker={b.get('speaker')} dialogue={b.get('dialogue')}")
