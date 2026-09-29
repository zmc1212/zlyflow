import sys, os, re
path = "frontend/src/director2/workshop-api.ts"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'export const readWorkshop = (project: string, episode: string) => requestJson<WorkshopView>(${base(project, episode)}/workshop)',
    'export const readWorkshop = (project: string, episode: string, history = false) => requestJson<WorkshopView>(${base(project, episode)}/workshop + (history ? "?history=true" : ""))'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
