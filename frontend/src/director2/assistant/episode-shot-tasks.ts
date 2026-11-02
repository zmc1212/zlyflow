import { director2ErrorDetail, type Director2Beat, type Director2Job } from "../api"

// Mirrors backend episode_video_service._ACTIVE_VIDEO_STATUSES.
const ACTIVE_VIDEO_STATUSES = new Set([
  "queued",
  "preparing",
  "prompt_generation",
  "uploading",
  "comfy_queued",
  "running",
  "upscaling",
  "assembling",
  "downloading",
  "awaiting_refine",
])

export type EpisodeVideoActivity = {
  blockingJobId: string
  activeBeatIds: string[]
}

export function activeEpisodeVideoJobs(jobs: Director2Job[], episodeId: string): EpisodeVideoActivity {
  const target = String(episodeId || "").trim()
  const blocking: string[] = []
  const activeBeatIds = new Set<string>()
  for (const job of jobs || []) {
    if (job.job_type !== "video_generation") continue
    if (!ACTIVE_VIDEO_STATUSES.has(String(job.status || ""))) continue
    const payload = job.payload || {}
    if (!target || String(payload.episode_id || "").trim() !== target) continue
    const scope = String(payload.render_scope || "episode")
    if (scope === "episode" || scope === "compose") {
      blocking.push(String(job.id || ""))
      continue
    }
    const ids = [payload.beat_id, ...(Array.isArray(payload.beat_ids) ? payload.beat_ids : [])]
    for (const id of ids) {
      const value = String(id || "").trim()
      if (value) activeBeatIds.add(value)
    }
  }
  return {
    blockingJobId: blocking.find(Boolean) || "",
    activeBeatIds: [...activeBeatIds],
  }
}

export type ShotTaskProgress = {
  index: number
  total: number
  sequence: number
}

export type ShotTaskFailure = {
  beatId: string
  sequence: number
  message: string
}

export type ShotTaskResult = {
  ok: boolean
  submitted: number
  skipped: number
  jobIds: string[]
  submittedBeatIds: string[]
  failures: ShotTaskFailure[]
}

export type ShotTaskApi = {
  generateBeatVideo: (beatId: string, options: Record<string, unknown>) => Promise<{ job_id?: string }>
}

export type ShotPromptPrepProgress = {
  index: number
  total: number
  sequence: number
  phase: "submit" | "wait"
}

export type ShotPromptPrepResult = {
  ok: boolean
  prepared: number
  failures: ShotTaskFailure[]
}

export type ShotPromptApi = {
  generateBeatPrompt: (beatId: string) => Promise<{ job_id?: string; prompt?: string; duplicate?: boolean }>
  listJobs: () => Promise<Director2Job[]>
}

// Mirrors backend h3_prompt job terminal statuses.
const TERMINAL_H3_PROMPT_STATUSES = new Set(["completed", "succeeded", "failed", "cancelled"])

function hasSavedH3Prompt(beat: Director2Beat): boolean {
  return Boolean(String(beat.h3_prompt || "").trim())
}

function orderedUniqueBeats(beats: Director2Beat[]): Director2Beat[] {
  const seen = new Set<string>()
  return [...(beats || [])]
    .filter((beat) => {
      const id = String(beat.id || "").trim()
      if (!id || seen.has(id)) return false
      seen.add(id)
      return true
    })
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => { setTimeout(resolve, ms) })
}

export async function ensureEpisodeShotPrompts({
  beats,
  skipBeatIds,
  api,
  onProgress,
  pollIntervalMs = 2500,
  timeoutMs = 15 * 60 * 1000,
}: {
  beats: Director2Beat[]
  skipBeatIds?: Iterable<string>
  api: ShotPromptApi
  onProgress?: (progress: ShotPromptPrepProgress) => void
  pollIntervalMs?: number
  timeoutMs?: number
}): Promise<ShotPromptPrepResult> {
  const skip = new Set([...(skipBeatIds || [])].map(String))
  const targets = orderedUniqueBeats(beats).filter((beat) => (
    !skip.has(String(beat.id || "").trim()) && !hasSavedH3Prompt(beat)
  ))
  const failures: ShotTaskFailure[] = []
  const jobBeats = new Map<string, Director2Beat>()
  let prepared = 0

  for (let index = 0; index < targets.length; index += 1) {
    const beat = targets[index]
    const beatId = String(beat.id || "").trim()
    const sequence = Number(beat.sequence || 0) || index + 1
    onProgress?.({ index: index + 1, total: targets.length, sequence, phase: "submit" })
    try {
      const result = await api.generateBeatPrompt(beatId)
      if (String(result?.prompt || "").trim()) {
        prepared += 1
        continue
      }
      const jobId = String(result?.job_id || "").trim()
      if (!jobId) throw new Error("后端没有返回任务 ID")
      jobBeats.set(jobId, beat)
    } catch (error) {
      failures.push({ beatId, sequence, message: director2ErrorDetail(error, "提示词任务提交失败") })
    }
  }

  const pending = new Set(jobBeats.keys())
  const deadline = Date.now() + timeoutMs
  while (pending.size) {
    const done = Math.max(0, targets.length - pending.size)
    onProgress?.({ index: done, total: targets.length, sequence: 0, phase: "wait" })
    if (Date.now() > deadline) {
      for (const jobId of pending) {
        const beat = jobBeats.get(jobId)
        failures.push({
          beatId: String(beat?.id || ""),
          sequence: Number(beat?.sequence || 0),
          message: "H3 提示词生成等待超时，请稍后重试",
        })
      }
      break
    }
    await delay(pollIntervalMs)
    let jobs: Director2Job[] = []
    try {
      jobs = await api.listJobs()
    } catch {
      continue
    }
    const byId = new Map((jobs || []).map((job) => [String(job.id || ""), job]))
    for (const jobId of [...pending]) {
      const job = byId.get(jobId)
      if (!job || !TERMINAL_H3_PROMPT_STATUSES.has(String(job.status || ""))) continue
      pending.delete(jobId)
      const beat = jobBeats.get(jobId)
      if (!beat) continue
      const status = String(job.status || "")
      if (status === "failed" || status === "cancelled") {
        failures.push({
          beatId: String(beat.id || ""),
          sequence: Number(beat.sequence || 0),
          message: String(job.error_message || "H3 提示词生成失败"),
        })
        continue
      }
      const prompt = String(job.payload?.h3_prompt || job.payload?.result_prompt || "").trim()
      if (prompt) prepared += 1
      else {
        failures.push({
          beatId: String(beat.id || ""),
          sequence: Number(beat.sequence || 0),
          message: "H3 提示词任务完成但没有返回提示词",
        })
      }
    }
  }

  return { ok: failures.length === 0, prepared, failures }
}

export async function submitEpisodeShotTasks({
  beats,
  options,
  skipBeatIds,
  inFlightBeatIds,
  api,
  onProgress,
}: {
  beats: Director2Beat[]
  options: Record<string, unknown>
  skipBeatIds?: Iterable<string>
  inFlightBeatIds?: Iterable<string>
  api: ShotTaskApi
  onProgress?: (progress: ShotTaskProgress) => void
}): Promise<ShotTaskResult> {
  const skip = new Set([...(skipBeatIds || [])].map(String))
  const inFlight = new Set([...(inFlightBeatIds || [])].map(String))
  const seen = new Set<string>()
  const ordered = [...(beats || [])]
    .filter((beat) => {
      const id = String(beat.id || "").trim()
      if (!id || seen.has(id)) return false
      seen.add(id)
      return true
    })
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
  let skipped = 0
  const targets: Director2Beat[] = []
  for (const beat of ordered) {
    const id = String(beat.id || "").trim()
    if (skip.has(id) || inFlight.has(id) || String(beat.video_url || "").trim()) {
      skipped += 1
      continue
    }
    targets.push(beat)
  }

  const jobIds: string[] = []
  const submittedBeatIds: string[] = []
  const failures: ShotTaskFailure[] = []
  for (let index = 0; index < targets.length; index += 1) {
    const beat = targets[index]
    const beatId = String(beat.id || "").trim()
    const sequence = Number(beat.sequence || 0) || index + 1
    onProgress?.({ index: index + 1, total: targets.length, sequence })
    try {
      const result = await api.generateBeatVideo(beatId, options)
      const jobId = String(result?.job_id || "").trim()
      if (!jobId) throw new Error("后端没有返回任务 ID")
      jobIds.push(jobId)
      submittedBeatIds.push(beatId)
    } catch (error) {
      failures.push({ beatId, sequence, message: director2ErrorDetail(error, "提交失败") })
    }
  }

  return {
    ok: failures.length === 0,
    submitted: jobIds.length,
    skipped,
    jobIds,
    submittedBeatIds,
    failures,
  }
}
