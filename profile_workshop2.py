import time
import os
import sys
import cProfile
import pstats

sys.path.insert(0, os.path.abspath('backend'))
from app.media_studio.services.workshop_service import WorkshopService

project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'

profiler = cProfile.Profile()
profiler.enable()

try:
    res = WorkshopService.view(project_id, episode_id, include_history=False)
except Exception as e:
    print(f"Workshop error: {e}")

profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumtime')
stats.print_stats(30)
