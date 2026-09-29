import sys, os, re
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import_statement = "import { readWorkshop, writeWorkshop, planWorkshop, promptWorkshop, type WorkshopView } from \"../workshop-api\""
new_import_statement = "import { readWorkshop, writeWorkshop, planWorkshop, promptWorkshop, readWorkshopJobs, type WorkshopView } from \"../workshop-api\""
content = content.replace(import_statement, new_import_statement)

old_timer = "void load(); const timer = setInterval(() => void load(), 4000)\n      return () => { clearInterval(timer); requestSequence.current++ }"
new_timer = '''void load(); 
      let lastJobsStr = ""
      const timer = setInterval(async () => {
        if (document.hidden) return
        try {
          const res = await readWorkshopJobs(projectId, episodeId)
          const currentStr = JSON.stringify(res.jobs.map(j => j.status))
          if (lastJobsStr && currentStr !== lastJobsStr) {
            void load()
          }
          lastJobsStr = currentStr
          setView(prev => prev ? {...prev, jobs: res.jobs} : prev)
        } catch (e) {}
      }, 4000)
      return () => { clearInterval(timer); requestSequence.current++ }'''

content = content.replace(old_timer, new_timer)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched UnifiedWorkshopPane polling")
