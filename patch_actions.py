import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'const { navigate, projectId, csrfToken, openDetail, handleUpscaleJob, upscalingJobId, getJobs, fetchJobs, openContentDocument, openWorkshopDubbing, handleRetry, jobUpscaleDisabledReason, jobUpscaleHint, jobCanShowUpscaleAction } = actions',
    'const { navigate, projectId, csrfToken, openDetail, handleUpscaleJob, upscalingJobId, getJobs, fetchJobs, openContentDocument, openWorkshopDubbing, handleRetry } = actions'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
