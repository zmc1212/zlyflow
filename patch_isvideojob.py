import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

helper = '''
function isVideoJob(job: Director2Job | null): boolean {
  return job?.job_type === "video_generation"
}

const JobResultCell = memo(function JobResultCell'''

content = content.replace("const JobResultCell = memo(function JobResultCell", helper)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Added isVideoJob")
