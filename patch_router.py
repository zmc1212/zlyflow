import sys, os, re
path = "backend/app/media_studio/routers/project_router.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'def workshop_view(project_id: str, episode_id: str, user: dict = Depends(current_user)):',
    'def workshop_view(project_id: str, episode_id: str, history: bool = False, user: dict = Depends(current_user)):'
)

content = content.replace(
    'return WorkshopService.view(project_id, episode_id)',
    'return WorkshopService.view(project_id, episode_id, include_history=history)'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
