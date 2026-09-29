import sys, os
path = "backend/app/media_studio/services/project_detail_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_str = '"data": {k: v for k, v in data.items() if k not in ("workshop_history", "workshop_legacy_prompts")},'
new_str = '"data": {k: v for k, v in data.items() if k not in ("workshop_history", "workshop_legacy_prompts", "beats", "production")},'

if old_str in content:
    content = content.replace(old_str, new_str)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched successfully.")
else:
    print("Could not find old string!")

