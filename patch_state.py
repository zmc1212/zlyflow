import sys, os
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

target = '''      setDetail(next); setView(work); setProduction(state); setError("")'''
repl = '''      setDetail(prev => JSON.stringify(prev) === JSON.stringify(next) ? prev : next)
      setView(prev => JSON.stringify(prev) === JSON.stringify(work) ? prev : work)
      setProduction(prev => JSON.stringify(prev) === JSON.stringify(state) ? prev : state)
      setError("")'''

if target in content:
    content = content.replace(target, repl)
else:
    print("target not found")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
