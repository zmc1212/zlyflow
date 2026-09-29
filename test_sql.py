import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
from app.db import query_all
project_id = 'proj-0f9c8015281149f0'
episode_id = 'ep-4d89a8df80a4'
job_types = ('h3_prompt_authoring', 'director_shot_plan')

start = time.time()
rows1 = query_all("SELECT id FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s)", (project_id, *job_types))
print(f"Full fetch took {time.time() - start:.2f}s, found {len(rows1)} rows")

start = time.time()
rows2 = query_all("SELECT id FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) AND payload_json LIKE %s ORDER BY created_at DESC LIMIT 12", (project_id, *job_types, f'%{episode_id}%'))
print(f"LIKE fetch took {time.time() - start:.2f}s, found {len(rows2)} rows")
