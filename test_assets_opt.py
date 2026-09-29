import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
from app.media_studio.db import query_all

project_id = 'proj-0f9c8015281149f0'

start = time.time()
assets = query_all("SELECT id, kind, name, description, visual_prompt, image_url, extra_json FROM ai_project_assets WHERE project_id=%s ORDER BY updated_at DESC", (project_id,))
print(f"ai_project_assets optimized took {time.time() - start:.2f}s, count: {len(assets)}")
