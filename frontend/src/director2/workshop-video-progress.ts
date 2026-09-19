/** 剧集工坊从 `/jobs` 抽出本集视频/合成进度，供镜头卡与轮询使用。 */

export const WORKSHOP_VIDEO_TERMINAL_STATUSES = new Set([
  "completed",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
])

export const WORKSHOP_IDLE_POLL_MS = 3000
export const WORKSHOP_VIDEO_POLL_MS = 1000

export type WorkshopVideoJobLike = {
  job_type?: string | null
  status: string
  progress?: number | null
    payload?: {
    episode_id?: string | null
    beat_id?: string | null
    beat_ids?: string[] | null
    render_scope?: string | null
    runtime_stage?: string | null
  } | null
}

export type WorkshopShotVideoProgress = {
  status: string
  progress: number
  scope?: string
  stage?: string
}

export type WorkshopEpisodeVideoScope = "episode" | "compose"

export type WorkshopEpisodeVideoProgress = {
  status: string
  progress: number
  scope: WorkshopEpisodeVideoScope
}

export type WorkshopVideoProgress = {
  beats: Record<string, WorkshopShotVideoProgress>
  episode: WorkshopEpisodeVideoProgress | null
}

export function isActiveWorkshopJobStatus(status: string): boolean {
  return Boolean(status) && !WORKSHOP_VIDEO_TERMINAL_STATUSES.has(status)
}

export function clampWorkshopProgress(value: unknown): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

/** 工坊已有阶段文案：排队中 / 准备素材 / 生成中 / 保存结果。 */
export function workshopVideoStageLabel(status: string, extra?: { scope?: string; stage?: string }): string {
  if (status === "upscaling" || extra?.scope === "upscale" || extra?.stage === "upscaling") return "2x 超分中"
  if (status === "queued") return "排队中"
  if (
    status === "preparing"
    || status === "prompt_generation"
    || status === "uploading"
    || status === "comfy_queued"
  ) {
    return "准备素材"
  }
  if (status === "storing" || status === "assembling" || status === "downloading") return "保存结果"
  if (status === "failed") return "生成失败"
  if (status === "running" || isActiveWorkshopJobStatus(status)) return "生成中"
  return ""
}

export function workshopVideoOverlayLabel(
  status: string,
  progress: number,
  extra?: { scope?: string; stage?: string },
): string {
  const stage = workshopVideoStageLabel(status, extra)
  if (!stage) return ""
  if (status === "running" || status === "upscaling") return `${stage} ${clampWorkshopProgress(progress)}%`
  return stage
}

export function workshopVideoPercentLabel(progress: number): string {
  return `${clampWorkshopProgress(progress)}%`
}

export function hasActiveWorkshopVideoProgress(progress: WorkshopVideoProgress): boolean {
  return Boolean(progress.episode) || Object.keys(progress.beats).length > 0
}

function episodeScope(value: string): WorkshopEpisodeVideoScope | null {
  if (value === "episode" || value === "compose") return value
  return null
}

/**
 * 本集 `video_generation` 任务 → 逐镜 / 整集或合成进度。
 * 同一镜或多条整集任务取列表中第一条（与全部任务 `updated_at DESC` 一致）。
 */
export function mapWorkshopVideoProgress(
  jobs: WorkshopVideoJobLike[],
  episodeId: string,
): WorkshopVideoProgress {
  const beats: Record<string, WorkshopShotVideoProgress> = {}
  let episode: WorkshopEpisodeVideoProgress | null = null
  if (!episodeId) return { beats, episode }

  for (const job of jobs) {
    if (job.job_type !== "video_generation") continue
    if (String(job.payload?.episode_id || "") !== episodeId) continue
    if (!isActiveWorkshopJobStatus(job.status)) continue

    const progress = clampWorkshopProgress(job.progress)
    const scope = String(job.payload?.render_scope || "")
    const beatIds = [
      ...((Array.isArray(job.payload?.beat_ids) ? job.payload.beat_ids : []) as Array<string | null | undefined>),
      job.payload?.beat_id,
    ].map((item) => String(item || "").trim()).filter(Boolean)
    if (scope === "shot" || scope === "selection" || scope === "upscale") {
      for (const beatId of beatIds) {
        if (beatId in beats) continue
        beats[beatId] = {
          status: job.status,
          progress,
          scope,
          stage: String(job.payload?.runtime_stage || ""),
        }
      }
      continue
    }
    const episodeOrCompose = episodeScope(scope)
    if (episodeOrCompose && !episode) {
      episode = { status: job.status, progress, scope: episodeOrCompose }
    }
  }

  return { beats, episode }
}
