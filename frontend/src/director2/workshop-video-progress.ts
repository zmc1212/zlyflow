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

type WorkshopRenderProgress = { total: number; completed: number; current: number }

export type WorkshopVideoJobLike = {
  id?: string | null
  job_type?: string | null
  status: string
  progress?: number | null
  error_message?: string | null
  result_url?: string | null
  payload?: {
    episode_id?: string | null
    beat_id?: string | null
    beat_ids?: string[] | null
    render_scope?: string | null
    runtime_stage?: string | null
    strategy?: string | null
    segment_index?: number | string | null
    segment_total?: number | string | null
    preparation?: { stage?: string; message?: string } | null
    prompt_generation_progress?: { completed?: number; total?: number } | null
    render_progress?: WorkshopRenderProgress | null
    shot_status?: Record<string, string> | null
    shots?: Array<{ beat_id?: string | null; video_url?: string | null }> | null
  } | null
}

export type WorkshopShotVideoProgress = {
  status: string
  progress: number
  scope?: string
  stage?: string
  jobId?: string
  previewUrl?: string
  shotCount?: number
  message?: string
  renderProgress?: WorkshopRenderProgress
  /** 本镜在整批分段里的渲染阶段：succeeded / running / queued / awaiting_refine。 */
  shotStage?: string
  /** 段级发布已落地的本镜成片地址，整批拼接完成前就能播。 */
  shotUrl?: string
}

export type WorkshopEpisodeVideoScope = "episode" | "compose"

export type WorkshopEpisodeVideoProgress = {
  status: string
  progress: number
  scope: WorkshopEpisodeVideoScope
  jobId?: string
  stage?: string
  message?: string
  renderProgress?: WorkshopRenderProgress
  promptProgress?: { completed: number; total: number }
  shotCount?: number
  /** gap_fill 补跑任务：本任务在区间序列中的位置，横幅显示「补跑区间 i / n」。 */
  gapSegment?: { index: number; total: number }
}

export type WorkshopVideoProgress = {
  beats: Record<string, WorkshopShotVideoProgress>
  episode: WorkshopEpisodeVideoProgress | null
}

export function isActiveWorkshopJobStatus(status: string): boolean {
  return Boolean(status) && !WORKSHOP_VIDEO_TERMINAL_STATUSES.has(status)
}

export function isAwaitingRefineStatus(status: string | null | undefined): boolean {
  return status === "awaiting_refine"
}

export function clampWorkshopProgress(value: unknown): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

/** Distinguish the workbench queue from a task already submitted remotely. */
export function workshopVideoStageLabel(status: string, extra?: Pick<WorkshopShotVideoProgress, "scope" | "stage" | "message" | "renderProgress" | "shotStage">): string {
  if (status === "awaiting_refine") return "一采预览待确认"
  if (status === "upscaling" || extra?.scope === "upscale" || extra?.stage === "upscaling") return "智能超清中"
  if (status === "queued") return "排队中"
  const render = extra?.renderProgress
  if (extra?.shotStage === "saving") return "画面已渲染 · 正在保存成片"
  if (extra?.shotStage === "succeeded") return render && render.total > 1 ? `本镜已出片 · 整批 ${render.completed} / ${render.total} 组` : "本镜已出片"
  if (extra?.shotStage === "queued" && render && render.total > 1) return `排队中 · 第 ${render.current} / ${render.total} 组`
  if (status === "comfy_queued") return render && render.total > 1 ? `第 ${render.current} / ${render.total} 组远端排队` : "远端排队"
  if (status === "prompt_generation") return extra?.message || "整理生成指令"
  if (status === "preparing" && extra?.message) return extra.message
  if (
    status === "preparing"
    || status === "prompt_generation"
    || status === "uploading"
  ) {
    return "准备素材"
  }
  if (status === "storing" || status === "assembling" || status === "downloading") return "保存结果"
  if (status === "failed") return "生成失败"
  if (status === "running" && render && render.total > 1) return `正在生成第 ${render.current} / ${render.total} 组`
  if (status === "running" || isActiveWorkshopJobStatus(status)) return "生成中"
  return ""
}

export function workshopVideoOverlayLabel(
  status: string,
  progress: number,
  extra?: Pick<WorkshopShotVideoProgress, "scope" | "stage" | "message" | "renderProgress" | "shotStage">,
): string {
  const stage = workshopVideoStageLabel(status, extra)
  if (!stage) return ""
  if (extra?.shotStage === "succeeded" || extra?.shotStage === "queued") return stage
  if (status === "running" && extra?.renderProgress && extra.renderProgress.total > 1) return `${stage} · 当前步骤 ${clampWorkshopProgress(progress)}%`
  if (status === "running" || status === "upscaling") return `${stage} ${clampWorkshopProgress(progress)}%`
  return stage
}

/** 本镜所在分段已渲染完成、成片也已落地；整批还在跑，但这一镜不再需要进度条。 */
export function isWorkshopShotRendered(progress?: Pick<WorkshopShotVideoProgress, "shotStage"> | null): boolean {
  return progress?.shotStage === "succeeded"
}

export function workshopVideoPercentLabel(progress: number): string {
  return `${clampWorkshopProgress(progress)}%`
}

/** 整集横幅基础文案：从提示词整理、准备素材、分段渲染到保存，全程都有可读进度。 */
function workshopEpisodeStageBaseLabel(progress: WorkshopEpisodeVideoProgress): string {
  if (progress.scope === "compose") return "整集合片中"
  const render = progress.renderProgress
  const renderTotal = Number(render?.total) || 0
  const renderCurrent = Number(render?.current) || 0
  const completed = Number(render?.completed) || 0
  const percent = workshopVideoPercentLabel(progress.progress)
  switch (progress.status) {
    case "prompt_generation":
      return progress.promptProgress && progress.promptProgress.total > 0
        ? `整理生成指令 ${progress.promptProgress.completed} / ${progress.promptProgress.total}`
        : "整理生成指令"
    case "queued":
      return "排队中"
    case "preparing":
      return progress.message || "准备素材"
    case "comfy_queued":
      return renderTotal > 1 ? `第 ${renderCurrent} / ${renderTotal} 组远端排队` : "远端排队"
    case "running":
      return renderTotal > 1
        ? `正在生成第 ${renderCurrent} / ${renderTotal} 组 · 已完成 ${completed} · ${percent}`
        : `生成中 ${percent}`
    case "storing":
    case "assembling":
    case "downloading":
      return renderTotal > 1 ? `保存结果 · 已完成 ${completed} / ${renderTotal} 组` : "保存结果"
    default:
      return workshopVideoStageLabel(progress.status, { scope: progress.scope, stage: progress.stage, message: progress.message, renderProgress: progress.renderProgress }) || (progress.message ? String(progress.message) : "生成中")
  }
}

/** 整集横幅阶段文案：gap_fill 补跑任务在前面叠加「补跑区间 i / n」。 */
export function workshopEpisodeStageLabel(progress: WorkshopEpisodeVideoProgress): string {
  const base = workshopEpisodeStageBaseLabel(progress)
  return progress.gapSegment && progress.gapSegment.total > 0
    ? `补跑区间 ${progress.gapSegment.index} / ${progress.gapSegment.total} · ${base}`
    : base
}

/** 工坊顶部横幅整句：拼接片的阶段文案自带「整集」语义，不再叠加前缀，避免出现「整集生成中 · 整集合片中」。 */
export function workshopEpisodeBannerLabel(progress: WorkshopEpisodeVideoProgress): string {
  if (progress.scope === "compose") return workshopEpisodeStageLabel(progress)
  if (progress.gapSegment) return `整集补跑中 · ${workshopEpisodeStageBaseLabel(progress)}`
  return `整集生成中 · ${workshopEpisodeStageLabel(progress)}`
}

export function hasActiveWorkshopVideoProgress(progress: WorkshopVideoProgress): boolean {
  if (progress.episode && !isAwaitingRefineStatus(progress.episode.status)) return true
  return Object.values(progress.beats).some((item) => !isAwaitingRefineStatus(item.status))
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
      stampShotBeats(beats, job, beatIds, progress)
      // gap_fill 补跑任务同时驱动顶部横幅（补跑区间 i / n），镜头卡由 stampShotBeats 正常回显。
      if (scope === "selection" && String(job.payload?.strategy || "") === "gap_fill" && !episode) {
        const gapTotal = Number(job.payload?.segment_total) || 0
        const gapIndex = Number(job.payload?.segment_index) || 0
        if (gapTotal > 0) {
          episode = {
            status: job.status,
            progress,
            scope: "episode",
            jobId: String(job.id || ""),
            gapSegment: { index: gapIndex || 1, total: gapTotal },
          }
        }
      }
      continue
    }
    const episodeOrCompose = episodeScope(scope)
    if (episodeOrCompose && !episode) {
      const promptProgress = job.payload?.prompt_generation_progress
      const message = job.status === "prompt_generation" && Number(promptProgress?.total) > 1
        ? `整理生成指令 ${promptProgress?.completed || 0} / ${promptProgress?.total}`
        : job.payload?.preparation?.message
      episode = {
        status: job.status,
        progress,
        scope: episodeOrCompose,
        jobId: String(job.id || ""),
        ...(String(job.payload?.runtime_stage || "") ? { stage: String(job.payload?.runtime_stage || "") } : {}),
        ...(message ? { message } : {}),
        ...(job.payload?.render_progress ? { renderProgress: job.payload.render_progress } : {}),
        ...(promptProgress && Number(promptProgress.total) > 0
          ? { promptProgress: { completed: Number(promptProgress.completed) || 0, total: Number(promptProgress.total) || 0 } }
          : {}),
      }
    }
    // 整集直出进入分段渲染后，任务里已带逐镜状态；回填镜头卡，让用户看到「哪几镜已出片」。
    // 提示词整理阶段还没有 shot_status，此时镜头卡保持空白，由顶部整集横幅（A）承载进度。
    if (episodeOrCompose === "episode") {
      const shotBeatIds = [...new Set([
        ...Object.keys(job.payload?.shot_status || {}),
        ...(job.payload?.shots || []).map((item) => String(item?.beat_id || "")).filter(Boolean),
      ])].filter(Boolean)
      stampShotBeats(beats, job, shotBeatIds, progress)
      if (episode) episode.shotCount = shotBeatIds.length || episode.shotCount
    }
  }

  return { beats, episode }
}

/** 把一条视频任务里已有的逐镜状态铺到镜头卡；shot/selection/upscale 与整集分段渲染共用。 */
function stampShotBeats(
  beats: Record<string, WorkshopShotVideoProgress>,
  job: WorkshopVideoJobLike,
  beatIds: string[],
  progress: number,
): void {
  const scope = String(job.payload?.render_scope || "")
  const promptProgress = job.payload?.prompt_generation_progress
  const preparationMessage = job.status === "prompt_generation" && Number(promptProgress?.total) > 1
    ? `整理生成指令 ${promptProgress?.completed || 0} / ${promptProgress?.total}`
    : job.payload?.preparation?.message
  const shotStatus = job.payload?.shot_status || {}
  const shotUrls = new Map<string, string>()
  for (const item of job.payload?.shots || []) {
    const id = String(item?.beat_id || "").trim()
    const url = String(item?.video_url || "").trim()
    if (id && url) shotUrls.set(id, url)
  }
  const tracksShotUrls = Boolean(job.payload?.shots?.length)
  for (const beatId of beatIds) {
    if (beatId in beats) continue
    const rawStage = String(shotStatus[beatId] || "")
    const shotUrl = shotUrls.get(beatId) || ""
    // 分段渲染完 ≠ 成片已落地：任务里还没有本镜地址时只能说「正在保存」，否则界面报「已出片」却放不出画面。
    const shotStage = rawStage === "succeeded" && !shotUrl && tracksShotUrls ? "saving" : rawStage
    beats[beatId] = {
      status: job.status,
      progress,
      scope,
      stage: String(job.payload?.runtime_stage || ""),
      jobId: String(job.id || ""),
      previewUrl: String(job.result_url || ""),
      shotCount: beatIds.length,
      ...(preparationMessage ? { message: preparationMessage } : {}),
      ...(job.payload?.render_progress ? { renderProgress: job.payload.render_progress } : {}),
      ...(shotStage ? { shotStage } : {}),
      ...(shotUrl ? { shotUrl } : {}),
    }
  }
}

/** Only show the latest failed submission; a newer success clears an older error. */
export function mapWorkshopVideoFailures(jobs: WorkshopVideoJobLike[], episodeId: string, allBeatIds: string[] = []): Record<string, WorkshopShotVideoProgress & { error: string }> {
  const seen = new Set<string>()
  const failures: Record<string, WorkshopShotVideoProgress & { error: string }> = {}
  for (const job of jobs) {
    if (job.job_type !== "video_generation" || job.payload?.episode_id !== episodeId) continue
    const scope = job.payload.render_scope
    if (scope === "compose" || scope === "upscale") continue
    const ids = scope === "episode" ? allBeatIds : [...(job.payload.beat_ids || []), job.payload.beat_id || ""]
    for (const id of ids.filter(Boolean)) {
      if (seen.has(id)) continue
      seen.add(id)
      if (job.status === "failed") failures[id] = {
        status: "failed", progress: 0, jobId: job.id || "",
        error: /(?:missing|缺少)\s*<Picture\s*\d+>/i.test(job.error_message || "")
          ? "生成指令未完整引用角色或场景参考图，请重试当前步骤。"
          : job.error_message || "生成失败，已完成的准备步骤会保留",
      }
    }
  }
  return failures
}
