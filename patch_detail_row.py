import sys, os, re
path = "backend/app/media_studio/services/project_detail_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(
    r'ep_row = query_one\("SELECT \* FROM ai_project_episodes WHERE id = %s AND project_id = %s", \(episode_id, project_id\)\)',
    'ep_row = query_one("SELECT id, project_id, episode_num, title, status, script_text, JSON_REMOVE(data_json, \'$.workshop_history\', \'$.workshop_legacy_prompts\') AS data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))',
    content, count=1
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched ProjectDetailService.get_episode_detail successfully.")
