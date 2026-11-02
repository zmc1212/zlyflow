export type ProgramPreviewShot = {
  beat_id?: string | null
  prompt?: string | null
}

export type ProgramPreviewJob = {
  id?: string | null
  status?: string | null
  payload?: {
    episode_id?: string | null
    prompt_source?: string | null
    shots?: ProgramPreviewShot[] | null
  } | null
}

export type ProgramPreviewPrompts = {
  jobId: string
  status: string
  prompts: Record<string, string>
}

export function programPreviewPrompts(
  jobs: ProgramPreviewJob[] | null | undefined,
  episodeId: string | null | undefined,
): ProgramPreviewPrompts | null {
  const target = String(episodeId || "").trim()
  if (!target) return null
  for (const job of jobs || []) {
    const payload = job?.payload
    if (!payload || String(payload.episode_id || "").trim() !== target) continue
    if (payload.prompt_source !== "program_preview") continue
    const prompts: Record<string, string> = {}
    for (const shot of payload.shots || []) {
      const beatId = String(shot?.beat_id || "").trim()
      const prompt = String(shot?.prompt || "").trim()
      if (beatId && prompt) prompts[beatId] = prompt
    }
    if (Object.keys(prompts).length) {
      return { jobId: String(job.id || ""), status: String(job.status || ""), prompts }
    }
  }
  return null
}

export function sameProgramPreviewPrompts(
  left: ProgramPreviewPrompts | null,
  right: ProgramPreviewPrompts | null,
): boolean {
  if (left === right) return true
  if (!left || !right) return false
  if (left.jobId !== right.jobId || left.status !== right.status) return false
  const leftKeys = Object.keys(left.prompts)
  const rightKeys = Object.keys(right.prompts)
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => left.prompts[key] === right.prompts[key])
}
