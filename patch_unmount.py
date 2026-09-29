import sys, os
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target = 'setDetail(null); setView(null); setProduction(null); setTakeId(""); onDetailModeChange?.(Boolean(episodeId))'
repl = 'startTransition(() => { setDetail(null); setView(null); setProduction(null); setTakeId(""); onDetailModeChange?.(Boolean(episodeId)) })'

if target in content:
    content = content.replace(target, repl)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
