import sys, os, re
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(
    r"sql = \"SELECT id, project_id, episode_num, title, status, script_text, JSON_REMOVE\(data_json, '\$\.workshop_history', '\$\.workshop_legacy_prompts', '\$\.production'\) AS data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s\"",
    'sql = "SELECT id, project_id, episode_num, title, status, script_text, data_json FROM ai_project_episodes WHERE id=%s AND project_id=%s"',
    content, count=1
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Reverted WorkshopService.row")

path2 = "backend/app/media_studio/services/project_detail_service.py"
with open(path2, "r", encoding="utf-8") as f2:
    content2 = f2.read()

content2 = re.sub(
    r"ep_row = query_one\(\"SELECT id, project_id, episode_num, title, status, script_text, JSON_REMOVE\(data_json, '\$\.workshop_history', '\$\.workshop_legacy_prompts'\) AS data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s\", \(episode_id, project_id\)\)",
    'ep_row = query_one("SELECT * FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))',
    content2, count=1
)

with open(path2, "w", encoding="utf-8") as f2:
    f2.write(content2)
print("Reverted ProjectDetailService.get_episode_detail")
