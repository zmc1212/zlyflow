import sys
import os
import json

sys.path.insert(0, os.path.abspath('d:/zlyun/Toonflow/本地视频工作台/backend'))
from app.db import open_database

db = open_database()
try:
    with db.connection() as conn:
        cursor = conn.execute("SELECT id, title, payload_json FROM director_projects ORDER BY updated_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            print("Project ID:", row['id'])
            print("Title:", row['title'])
            recipe_data = json.loads(row['payload_json'] or '{}')
            agent_status = recipe_data.get('agentStatus', [])
            print("Agent Status:")
            for s in agent_status:
                if s.get('status') in ('running', 'failed', 'pending'):
                    print(json.dumps(s, indent=2, ensure_ascii=False))
        else:
            print("No director_projects found.")
except Exception as e:
    print("Error:", e)
