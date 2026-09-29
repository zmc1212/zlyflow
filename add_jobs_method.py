import sys, os, re
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

new_method = '''    @classmethod
    def episode_jobs(cls, project_id, episode_id):
        jobs = []
        for job in query_all("SELECT id,status,job_type,payload_json,error_message FROM ai_project_jobs WHERE project_id=%s AND job_type IN (%s,%s) ORDER BY created_at DESC LIMIT 100", (project_id, *cls.JOB_TYPES)):
            payload = json.loads(job.get("payload_json") or "{}")
            if payload.get("episode_id") == episode_id:
                jobs.append({"id": job["id"], "status": job["status"], "kind": job["job_type"], "error": job.get("error_message")})
                if len(jobs) >= 12:
                    break
        return {"jobs": jobs}
'''

content = content.replace("    @classmethod\n    def view(cls, project_id, episode_id, include_history=False):", new_method + "\n    @classmethod\n    def view(cls, project_id, episode_id, include_history=False):")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched WorkshopService.episode_jobs")
