import time, os, sys
sys.path.append(os.getcwd())
from backend.app.db import open_database
from backend.app.storage import JobStore
db = open_database()
store = JobStore(db)

from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
from backend.app.media_studio.services.workshop_service import WorkshopService
from backend.app.media_studio.services.project_detail_service import ProjectDetailService
from backend.app.db import db_cursor

pid = 'proj-0f9c8015281149f0'
eid = 'ep-4d89a8df80a4'

start = time.monotonic()
try:
    with db_cursor() as cursor:
        ProjectDetailService.get_episode_detail(cursor, pid, eid)
    print(f"Detail: {(time.monotonic() - start)*1000:.0f}ms")
except Exception as e:
    print(f"Detail Error: {e}")

start = time.monotonic()
try:
    with db_cursor() as cursor:
        WorkshopService.read(cursor, pid, eid)
    print(f"Workshop: {(time.monotonic() - start)*1000:.0f}ms")
except Exception as e:
    print(f"Workshop Error: {e}")
