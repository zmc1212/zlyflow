import sys, os
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re
content = re.sub(
    r'def row\(project_id, episode_id\):\n\s*row = query_one\("SELECT \* FROM ai_project_episodes WHERE id=%s AND project_id=%s", \(episode_id, project_id\)\)',
    '''def row(project_id, episode_id, include_history=False):
        if include_history:
            sql = "SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s"
        else:
            sql = "SELECT id, project_id, episode_num, title, status, script_text, JSON_REMOVE(data_json, '$.workshop_history', '$.workshop_legacy_prompts', '$.production') AS data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s"
        row = query_one(sql, (episode_id, project_id))''',
    content, count=1
)

content = re.sub(
    r'row, data = cls\.row\(project_id, episode_id\)',
    'row, data = cls.row(project_id, episode_id, include_history=include_history)',
    content, count=1
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched WorkshopService.row successfully.")
