import sys, os
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re
content = re.sub(
    r'for job in query_all\("SELECT .*? FROM ai_project_jobs WHERE project_id=%s AND job_type IN \(%s,%s\).*? \(\w+, \*cls\.JOB_TYPES.*?:\n',
    'for job in query_all("SELECT id,status,job_type,payload_json,error_message FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) ORDER BY created_at DESC LIMIT 200", (project_id, *cls.JOB_TYPES)):\n',
    content, count=1
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched successfully.")
