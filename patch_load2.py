import sys, os
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re

# We need to replace the broken startTransition block
# Find the startTransition block up to the setError("")
match = re.search(r'startTransition\(\(\) => \{[\s\S]*?setError\(""\)\n\s*\}\)', content)

if not match:
    print("Could not find startTransition block!")
    sys.exit(1)

new_block = """startTransition(() => {
        const detailSig = (d: any) => d ? JSON.stringify({
          status: d.status,
          beats: d.beats?.map((b: any) => `${b.id}:${b.sketch_url}:${b.triptych_url}:${b.video_duration}:${b.camera}:${b.h3_prompt_reference_state}`)
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
      })"""

content = content[:match.start()] + new_block + content[match.end():]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
