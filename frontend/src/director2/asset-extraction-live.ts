import type { Director2Job } from "./api"
import type { WorkshopPromptStreamEvent } from "./workshop-prompt-stream"

export type AssetExtractionLiveState = {
  jobId: string
  phase: string
  message: string
  chars: number
  startedAt: number
  working: boolean
  error: string
}

export function emptyAssetExtractionLiveState(jobId = ""): AssetExtractionLiveState {
  return {
    jobId,
    phase: "queued",
    message: jobId ? "正在准备拆解资产" : "",
    chars: 0,
    startedAt: Date.now(),
    working: Boolean(jobId),
    error: "",
  }
}

export function applyAssetExtractionStreamEvent(
  state: AssetExtractionLiveState,
  event: WorkshopPromptStreamEvent,
): AssetExtractionLiveState {
  if (event.event === "keep-alive") return state
  const data = event.data && typeof event.data === "object" ? event.data as Record<string, unknown> : {}
  if (event.event === "status") {
    return {
      ...state,
      phase: String(data.phase || state.phase || "queued"),
      message: String(data.message || state.message || "正在准备拆解资产"),
      chars: Math.max(0, Number(data.chars ?? state.chars) || 0),
      working: true,
      error: "",
    }
  }
  if (event.event === "done") {
    const total = Number(data.total || 0)
    const skipped = Number(data.skipped_count || 0)
    const notice = total > 0 ? `已新增 ${total} 个制作资产` : "制作资产已核对完成"
    return {
      ...state,
      phase: "done",
      message: skipped > 0 ? `${notice}，${skipped} 项无法核对已跳过` : notice,
      working: false,
      error: "",
    }
  }
  if (event.event === "error") {
    const detail = String(data.message || "资产拆解未完成")
    return { ...state, phase: "failed", message: "资产拆解未完成", working: false, error: detail }
  }
  return state
}

export function applyAssetExtractionJobSnapshot(
  state: AssetExtractionLiveState,
  job: Director2Job | null | undefined,
): AssetExtractionLiveState {
  if (!job) return state
  const status = String(job.status || "")
  if (status === "failed") {
    return {
      ...state,
      phase: "failed",
      message: "资产拆解未完成",
      working: false,
      error: String(job.error_message || "资产拆解未完成"),
    }
  }
  if (status === "completed" || status === "succeeded") {
    const total = Number(job.payload?.total || 0)
    const skipped = Number(job.payload?.skipped_count || 0)
    const notice = total > 0 ? `已新增 ${total} 个制作资产` : "制作资产已核对完成"
    return {
      ...state,
      phase: "done",
      message: skipped > 0 ? `${notice}，${skipped} 项无法核对已跳过` : notice,
      working: false,
      error: "",
    }
  }
  return {
    ...state,
    phase: String(job.payload?.phase || state.phase),
    message: String(job.payload?.message || state.message),
    chars: Math.max(0, Number(job.payload?.chars ?? state.chars) || 0),
    working: true,
    error: "",
  }
}

export function assetExtractionElapsedLabel(startedAt: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${String(seconds % 60).padStart(2, "0")} 秒`
}

export function assetExtractionDescription(state: AssetExtractionLiveState, now: number): string {
  const elapsed = assetExtractionElapsedLabel(state.startedAt, now)
  if (state.error) return `已用时 ${elapsed} · 可重试，或先核对剧本中的角色、场景和道具名称是否写进了正文。`
  const parts = [`已用时 ${elapsed}`]
  if (state.chars > 0) parts.push(`模型已接收 ${state.chars} 字`)
  parts.push("通常需要 1–2 分钟，可切换到其他页面，任务会在后台继续")
  return parts.join(" · ")
}

export function assetExtractionFinishedNotice(state: AssetExtractionLiveState): string {
  return state.message || "制作资产已核对完成"
}
