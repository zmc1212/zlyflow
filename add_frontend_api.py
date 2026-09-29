import sys, os, re
path = "frontend/src/director2/workshop-api.ts"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

new_api = 'export const readWorkshopJobs = (project: string, episode: string) => requestJson<{jobs: any[]}>(${base(project, episode)}/workshop/jobs)'

if 'readWorkshopJobs' not in content:
    content = content.replace('export const readWorkshop = ', new_api + '\nexport const readWorkshop = ')
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched frontend API")
else:
    print("Already patched")
