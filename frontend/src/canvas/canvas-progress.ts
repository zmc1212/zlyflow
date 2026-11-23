/**
 * 画布生成进度：把散落在节点数据与 liveJobs 里的任务状态汇聚成右上角面板可渲染的条目。
 *
 * 纯函数，便于单测；面板只负责展示与跳转。
 */
import type { CanvasGeneratorLive } from "./canvas-generation"
import { canvasJobStatusLabel, canvasJobStatusTone, isCanvasJobActive } from "./canvas-generation"
import type { CanvasNode } from "./canvas-model"
import { canvasAudioTitle } from "./canvas-audio"

export type CanvasProgressKind = "image" | "video" | "audio" | "text"

export type CanvasProgressFilter = "all" | CanvasProgressKind

/** 任务类型 → 文案。面板按「图片 / 视频 / 音频」固定列页签（对齐即梦），文本类型有任务时自动出现。 */
export const CANVAS_PROGRESS_KIND_LABELS: Record<CanvasProgressKind, string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
  text: "文本",
}

/** 固定展示的类型页签（文本先只在真有任务时出现）。 */
const PINNED_PROGRESS_KINDS: CanvasProgressKind[] = ["image", "video", "audio"]

export type CanvasProgressEntry = {
  nodeId: string
  jobId: string
  kind: CanvasProgressKind
  /** 节点标题，与画布上的节点标题一致（未命名时按媒体类型取「图片生成 / 视频生成」）。 */
  title: string
  /** 工作流名称（如「H3 图像 文生图」），用于区分同标题的多个任务。 */
  workflowName: string
  status: string
  stage?: string
  progress: number | null
  active: boolean
  /** 排序与展示用的时间戳：优先实时更新时间，其次提交时间。 */
  updatedAt: number
  error: string | null
  previewUrl: string | null
  completedCount?: number
  requestedCount?: number
}

/** 结果/节拍里的类型值转成面板类型，未知值按图片处理，避免整行被丢弃。 */
export function canvasProgressKind(value: unknown): CanvasProgressKind {
  return value === "video" || value === "audio" || value === "text" ? value : "image"
}

/** 与 GeneratorCanvasNode 标题栏同一口径，避免面板和节点叫法不一致。 */
export function canvasGeneratorTitle(label: string | undefined, kind: CanvasProgressKind): string {
  const text = (label ?? "").trim()
  if (!text || text === "生成" || text === "画面生成") {
    return `${CANVAS_PROGRESS_KIND_LABELS[kind]}生成`
  }
  return text
}

function finiteTimestamp(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0
}

/**
 * 生成节点 → 进度条目。
 * 已完成的历史任务同样保留（面板要能当生成记录看），按「进行中优先、时间倒序」排序。
 */
export function canvasProgressEntries(
  nodes: CanvasNode[],
  liveJobs: Record<string, CanvasGeneratorLive>,
  workflowName: (workflowId: string | undefined) => string,
  limit = 24,
): CanvasProgressEntry[] {
  const entries: CanvasProgressEntry[] = []
  for (const node of nodes) {
    if (node.type === "audio") {
      const status = String(node.data.jobStatus ?? "")
      if (!status) continue
      const mode = node.data.audioMode === "music" ? "music" : "tts"
      const jobId = typeof node.data.jobId === "string" && node.data.jobId ? node.data.jobId : `${node.id}:tts`
      const progress = typeof node.data.jobProgress === "number" && Number.isFinite(node.data.jobProgress)
        ? Math.max(0, Math.min(100, node.data.jobProgress))
        : null
      entries.push({
        nodeId: node.id,
        jobId,
        kind: "audio",
        title: canvasAudioTitle(node.data.label, mode),
        workflowName: mode === "music" ? "本地音乐生成" : "TTS 配音",
        status,
        stage: undefined,
        progress,
        active: isCanvasJobActive(status),
        updatedAt: 0,
        error: node.data.jobError ?? null,
        previewUrl: node.data.resultUrl ?? null,
      })
      continue
    }
    if (node.type !== "generator") continue
    const jobId = typeof node.data.jobId === "string" && node.data.jobId ? node.data.jobId : ""
    if (!jobId) continue
    const live = liveJobs[jobId]
    const status = live?.status ?? node.data.jobStatus ?? ""
    if (!status) continue
    const kind: CanvasProgressKind = canvasProgressKind(live?.result?.kind ?? node.data.resultKind)
    const progress = typeof live?.progress === "number" && Number.isFinite(live.progress)
      ? Math.max(0, Math.min(100, live.progress))
      : null
    entries.push({
      nodeId: node.id,
      jobId,
      kind,
      title: canvasGeneratorTitle(node.data.label, kind),
      workflowName: workflowName(node.data.workflowId),
      status,
      stage: live?.stage,
      progress,
      active: isCanvasJobActive(status),
      updatedAt: finiteTimestamp(live?.updatedAt) || finiteTimestamp(node.data.lastRun?.submittedAt),
      error: live?.error ?? node.data.jobError ?? null,
      previewUrl: live?.result?.url ?? node.data.resultUrl ?? live?.results?.[0]?.url ?? null,
      completedCount: live?.completedCount,
      requestedCount: live?.requestedCount,
    })
  }
  return entries
    .sort((a, b) => Number(b.active) - Number(a.active) || b.updatedAt - a.updatedAt)
    .slice(0, limit)
}

/** 面板筛选页签：图片/视频/音频固定列出（与即梦一致），文本有任务时自动补上。 */
export function canvasProgressTabs(
  entries: CanvasProgressEntry[],
): Array<{ key: CanvasProgressFilter; label: string; count: number }> {
  const tabs: Array<{ key: CanvasProgressFilter; label: string; count: number }> = [
    { key: "all", label: "全部", count: entries.length },
  ]
  const kinds = [...PINNED_PROGRESS_KINDS]
  if (entries.some((entry) => entry.kind === "text")) kinds.push("text")
  for (const kind of kinds) {
    tabs.push({
      key: kind,
      label: CANVAS_PROGRESS_KIND_LABELS[kind],
      count: entries.filter((entry) => entry.kind === kind).length,
    })
  }
  return tabs
}

/** 空列表时的提示文案，说明当前页签确实没有任务。 */
export function canvasProgressEmptyText(filter: CanvasProgressFilter): string {
  return filter === "all" ? "暂无生成任务" : `暂无${CANVAS_PROGRESS_KIND_LABELS[filter]}任务`
}

export function filterCanvasProgress(entries: CanvasProgressEntry[], filter: CanvasProgressFilter): CanvasProgressEntry[] {
  return filter === "all" ? entries : entries.filter((entry) => entry.kind === filter)
}

export function canvasProgressActiveCount(entries: CanvasProgressEntry[]): number {
  return entries.filter((entry) => entry.active).length
}

/** 头部的状态摘要：有进行中显示数量与当前进度，否则显示最近一条的终态。 */
export function canvasProgressSummary(entries: CanvasProgressEntry[]): string {
  const active = entries.filter((entry) => entry.active)
  if (active.length) {
    const running = active.find((entry) => typeof entry.progress === "number")
    return running ? `${active.length} 个进行中 · ${Math.round(running.progress as number)}%` : `${active.length} 个进行中`
  }
  const latest = entries[0]
  return latest ? canvasJobStatusLabel(latest.status) : "空闲"
}

/** 行内状态文案：进行中优先展示后端阶段，部分完成补数量。 */
export function canvasProgressStatusText(entry: CanvasProgressEntry): string {
  if (entry.active) return entry.stage?.trim() || canvasJobStatusLabel(entry.status)
  if (entry.status === "partial" && entry.completedCount && entry.requestedCount) {
    return `${canvasJobStatusLabel(entry.status)} ${entry.completedCount}/${entry.requestedCount}`
  }
  return canvasJobStatusLabel(entry.status)
}

export function canvasProgressTone(entry: CanvasProgressEntry): ReturnType<typeof canvasJobStatusTone> {
  return canvasJobStatusTone(entry.status)
}

/** 面板时间戳：HH:mm，跨天不展示日期，与即梦的紧凑列表一致。 */
export function canvasProgressClock(timestamp: number): string {
  if (!timestamp) return ""
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ""
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
}
