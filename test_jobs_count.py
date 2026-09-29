import time, os, sys
sys.path.append(os.getcwd())
from backend.app.media_studio.db import db_cursor

pid = 'proj-0f9c8015281149f0'

try:
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as c FROM ai_project_jobs WHERE project_id = %s", (pid,))
        count = cursor.fetchone().get("c", 0)
        print(f"Jobs count: {count}")
except Exception as e:
    print(f"Error: {e}")
