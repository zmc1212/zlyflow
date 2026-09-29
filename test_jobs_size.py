import time, os, sys
sys.path.append(os.getcwd())
from backend.app.media_studio.db import db_cursor
from backend.app.media_studio.services.project_detail_service import ProjectDetailService

pid = 'proj-0f9c8015281149f0'

try:
    jobs = ProjectDetailService.list_jobs(pid)
    import json
    data = json.dumps(jobs)
    print(f"Jobs count: {len(jobs)}")
    print(f"JSON size: {len(data) / 1024 / 1024:.2f} MB")
except Exception as e:
    print(f"Error: {e}")
