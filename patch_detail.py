import sys, os, re
path = "backend/app/media_studio/services/project_detail_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# We need to strip heavy fields from data before returning it in get_episode_detail
# Let's find where data is returned
if '"data": data,' in content:
    content = content.replace('"data": data,', '"data": {k: v for k, v in data.items() if k not in ("workshop_history", "workshop_legacy_prompts")},')
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched project_detail_service.py successfully.")
else:
    print("Could not find '\"data\": data,'")

