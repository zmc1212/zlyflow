import sys, os, re
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# We want to replace the startTransition block inside load function
old_block = '''startTransition(() => {
        setDetail(prev => JSON.stringify(prev) === JSON.stringify(next) ? prev : next)
        setView(prev => JSON.stringify(prev) === JSON.stringify(work) ? prev : work)
        setProduction(prev => JSON.stringify(prev) === JSON.stringify(state) ? prev : state)
        setError("")
      })'''

new_block = '''startTransition(() => {
        const detailSig = (d: any) => d ? JSON.stringify({
          status: d.status,
          beats: d.beats?.map((b: any) => ${b.id}:::::)
        }) : ""
        
        const viewSig = (w: any) => w ? JSON.stringify({
          jobs: w.jobs,
          source_changed: w.source_changed,
          planRev: w.plan?.planning_revision,
          legacyRev: w.legacy_plan?.revision,
          historyCount: w.history?.length
        }) : ""
        
        const prodSig = (p: any) => p ? JSON.stringify(p) : ""
        
        setDetail(prev => detailSig(prev) === detailSig(next) ? prev : next)
        setView(prev => viewSig(prev) === viewSig(work) ? prev : work)
        setProduction(prev => prodSig(prev) === prodSig(state) ? prev : state)
        setError("")
      })'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Replaced successfully.")
else:
    print("Could not find the block to replace!")
    sys.exit(1)
