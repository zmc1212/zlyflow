import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService

eps = ProjectDetailService.list_episodes("proj-ebaf2e7234584b39")
print(f"Episodes count: {len(eps)}")
for ep in eps:
    print(f"id={ep.get('id')}, number={ep.get('number')}, title={ep.get('title')}")
