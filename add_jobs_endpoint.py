import sys, os, re
path = "backend/app/media_studio/routers/project_router.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

new_endpoint = '''    @app.get("/api/projects/{project_id}/episodes/{episode_id}/workshop/jobs")
    def workshop_jobs(project_id: str, episode_id: str, user: dict = Depends(current_user)):
        from ..services.workshop_service import WorkshopService
        return WorkshopService.episode_jobs(project_id, episode_id)
'''

content = content.replace('    @app.get("/api/projects/{project_id}/episodes/{episode_id}/workshop")', new_endpoint + '\n    @app.get("/api/projects/{project_id}/episodes/{episode_id}/workshop")')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched project_router.py")
