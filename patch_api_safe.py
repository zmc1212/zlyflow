import sys, os
path = "frontend/src/director2/workshop-api.ts"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.split('\n')
for i, line in enumerate(lines):
    if 'export const readWorkshop =' in line:
        lines[i] = 'export const readWorkshop = (project: string, episode: string, history = false) => requestJson<WorkshopView>(`${base(project, episode)}/workshop` + (history ? "?history=true" : ""))'

with open(path, "w", encoding="utf-8") as f:
    f.write('\n'.join(lines))
print("done")
