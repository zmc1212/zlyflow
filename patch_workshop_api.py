import sys, os, re
path = "frontend/src/director2/workshop-api.ts"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'export async function readWorkshop(project: string, episode: string): Promise<WorkshopView> {',
    'export async function readWorkshop(project: string, episode: string, history = false): Promise<WorkshopView> {\n  if (history) return fetchJson(base(project, episode) + "?history=true")'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
