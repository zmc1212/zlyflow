import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService

detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
print("Episode keys:", list(detail.keys()))
print("number:", detail.get("number"))
print("title:", detail.get("title"))
for b in detail.get("beats", []):
    print("beat:", b.get("id"), "seq:", b.get("sequence"), "dialogue:", b.get("dialogue"))
