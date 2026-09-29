import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
from app.media_studio.db import query_one

project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'

start = time.time()
r2 = query_one("SELECT id, JSON_EXTRACT(data_json, '$.prompt_authoring') AS prompt_authoring, JSON_EXTRACT(data_json, '$.beats') AS beats FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
print(f"JSON_EXTRACT took {time.time() - start:.2f}s")
