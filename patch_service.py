import sys, os, re
path = "backend/app/media_studio/services/workshop_service.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'def view(cls, project_id, episode_id):',
    'def view(cls, project_id, episode_id, include_history=False):'
)

# Fix the return block
old_return = '''return {"plan": plan if plan.get("schema_version") == 7 else None, "source": source,
                "writing_author": {key: (plan.get("writing_author") or active_author).get(key) for key in public_fields},
                "writing_profiles": [{key: p.get(key) for key in public_fields} for p in profiles],
                "history": data.get("workshop_history") or [],
                "historical_media": [m for state in ((data.get("production") or {}).get("modes") or {}).values() for m in state.get("materials") or []],'''

new_return = '''return {"plan": plan if plan.get("schema_version") == 7 else None, "source": source,
                "writing_author": {key: (plan.get("writing_author") or active_author).get(key) for key in public_fields},
                "writing_profiles": [{key: p.get(key) for key in public_fields} for p in profiles],
                "history": data.get("workshop_history") or [] if include_history else [],
                "historical_media": [m for state in ((data.get("production") or {}).get("modes") or {}).values() for m in state.get("materials") or []] if include_history else [],'''

content = content.replace(old_return, new_return)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
