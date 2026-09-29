import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
import app.main
from app.media_studio.services.workshop_service import WorkshopService

project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'

start = time.time()
try:
    res = WorkshopService.view(project_id, episode_id, include_history=False)
    print(f"WorkshopService.view took {time.time() - start:.2f}s")
except Exception as e:
    print(f"Workshop error: {e}")
