import time, os, sys
sys.path.append(os.getcwd())
from backend.app.db import open_database
from backend.app.storage import JobStore
db = open_database()
store = JobStore(db)
from backend.app.media_studio.services.project_detail_service import ProjectDetailService

pid = 'proj-0f9c8015281149f0'
eid = 'ep-4d89a8df80a4'

detail = ProjectDetailService(store).get_episode_detail(pid, eid)
print(f"Beats count: {len(detail.get('beats', []))}")
import json
print(f"JSON size: {len(json.dumps(detail))}")
