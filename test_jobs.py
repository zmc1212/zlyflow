import time, os, sys
sys.path.append(os.getcwd())
from backend.app.db import open_database
from backend.app.media_studio.services.job_payload import serialize_job_row

pid = 'proj-0f9c8015281149f0'

db = open_database()
try:
    with db.connection() as conn:
        rows = conn.execute("SELECT * FROM media_studio_jobs WHERE project_id = ? ORDER BY created_at DESC", (pid,)).fetchall()
        jobs = [serialize_job_row(dict(row)) for row in rows]
    print(f"Jobs count: {len(jobs)}")
    import json
    data = json.dumps(jobs)
    print(f"JSON size: {len(data) / 1024 / 1024:.2f} MB")
except Exception as e:
    print(f"Error: {e}")
