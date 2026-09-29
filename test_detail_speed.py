import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
import app.main
from app.media_studio.services.project_detail_service import ProjectDetailService

project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'

start = time.time()
try:
    res = ProjectDetailService.get_episode_detail(project_id, episode_id)
    print(f"ProjectDetailService.get_episode_detail took {time.time() - start:.2f}s")
except Exception as e:
    print(f"Detail error: {e}")
