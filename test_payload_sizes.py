import time, os, sys, json
sys.path.append(os.getcwd())
from backend.app.media_studio.services.project_detail_service import ProjectDetailService
from backend.app.media_studio.services.workshop_service import WorkshopService

pid = 'proj-0f9c8015281149f0'
eid = 'ep-4d89a8df80a4'

try:
    detail = ProjectDetailService.get_episode_detail(pid, eid)
    work = WorkshopService.view(pid, eid)
    
    print(f"Detail size: {len(json.dumps(detail)) / 1024:.2f} KB")
    print(f"Work size: {len(json.dumps(work)) / 1024:.2f} KB")
except Exception as e:
    print(f"Error: {e}")
