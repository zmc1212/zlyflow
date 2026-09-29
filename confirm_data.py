import sys, os, re
path = "backend/app/media_studio/services/project_detail_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

print("workshop_history in data?" in content)
