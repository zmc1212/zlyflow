import time
import sys
import os
sys.path.append(os.getcwd())
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService
start = time.monotonic()
EpisodeVideoService.recover_orphaned_jobs()
print(f"Time: {time.monotonic() - start}")
