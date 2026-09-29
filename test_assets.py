import time
import os
import sys

sys.path.insert(0, os.path.abspath('backend'))
from app.media_studio.db import query_all

project_id = 'proj-0f9c8015281149f0'

start = time.time()
assets = query_all("SELECT * FROM ai_project_assets WHERE project_id=%s", (project_id,))
print(f"ai_project_assets took {time.time() - start:.2f}s, count: {len(assets)}")
