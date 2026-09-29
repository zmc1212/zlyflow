import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
from app.db import query_one

project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'

start = time.time()
r1 = query_one("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
print(f"SELECT * took {time.time() - start:.2f}s")

start = time.time()
r2 = query_one("SELECT id, project_id, episode_num, title, status, script_text, JSON_REMOVE(data_json, '.workshop_history', '.workshop_legacy_prompts', '.production') AS data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s", (episode_id, project_id))
print(f"JSON_REMOVE took {time.time() - start:.2f}s")
