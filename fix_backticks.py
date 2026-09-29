import sys, os, re
path = "frontend/src/director2/workshop-api.ts"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'export const readWorkshopJobs = (project: string, episode: string) => requestJson<{jobs: any[]}>(/workshop/jobs)',
    'export const readWorkshopJobs = (project: string, episode: string) => requestJson<{jobs: any[]}>(\/workshop/jobs)'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched frontend API backticks")
