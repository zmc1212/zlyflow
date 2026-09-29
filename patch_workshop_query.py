import sys, os
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_str = 'for job in query_all("SELECT id,status,job_type,payload_json,error_message FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) ORDER BY created_at DESC", (project_id, *cls.JOB_TYPES)):'
new_str = 'for job in query_all("SELECT id,status,job_type,payload_json,error_message FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) AND payload_json LIKE %s ORDER BY created_at DESC LIMIT 50", (project_id, *cls.JOB_TYPES, f\\'%{episode_id}%\\')):'

if old_str in content:
    content = content.replace(old_str, new_str)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched successfully.")
else:
    print("Could not find the query loop string!")
