/**
 * 剧本工作台：把后端聚合视图（GET /api/projects/:id/workbench）派生成节点图。
 *
 * 边界：业务数据永远实时派生（不落画布表），本模块只负责
 * 1) 图结构（节点/边/自动布局） 2) 进度关卡展示数据 3) 布局坐标的本地存取。
 * 与后端 workbench_service.py 的字段保持同构。
 */

import type { WorkshopVideoJobLike } from "./workshop-video-progress"

export type WorkbenchStageKey = "script" | "assets" | "prompts" | "shots"
export type WorkbenchStageStatus = "locked" | "empty" | "active" | "done"

export type WorkbenchStage = {
  key: WorkbenchStageKey
  label: string
  done: number
  total: number
  ratio: number
  status: WorkbenchStageStatus
}

export type WorkbenchProgress = {
  stages: Record<WorkbenchStageKey, { done: number; total: number; ratio: number; status: WorkbenchStageStatus }>
  overall_pct: number
  beats_total: number
  prompts_done: number
  shots_done: number
  assets_total: number
  assets_ready: number
}

export type WorkbenchNextAction = {
  kind: "go-script" | "fix-assets" | "make-prompt" | "wait" | "confirm" | "render" | "compose" | "go-episode"
  label: string
  beat_id?: string
  episode_id?: string
  target?: string
}

export type WorkbenchAsset = {
  id: string
  kind: string
  name: string
  image_url: string
  ready: boolean
  ready_label: string
  looks_total: number
  looks_ready: number
  ref_beats: number
}

export type WorkbenchBeat = {
  id: string
  sequence: number
  kind: string
  heading: string
  title: string
  text: string
  speaker: string
  dialogue: string
  character_ids: string[]
  scene_id: string
  prop_ids: string[]
  has_prompt: boolean
  has_video: boolean
  video_url: string
  video_duration: string
  awaiting_refine: boolean
  task_status: "idle" | "queued" | "running" | "awaiting_refine" | "succeeded" | "failed" | string
  /** 工坊轮询盖进来的实时渲染百分比（仅 running/queued 时有值）。 */
  live_progress?: number | null
}

export type WorkbenchEdgePayload = { id: string; source: string; target: string; kind: "reference" | "sequence" | "output" }

export type WorkbenchPayload = {
  project: { id: string; name: string; cover_url: string }
  episode: {
    id: string
    number: number
    title: string
    status: string
    script_text: string
    summary: string
    episode_video_url: string
    episode_video_job_id: string
  }
  assets: WorkbenchAsset[]
  beats: WorkbenchBeat[]
  edges: WorkbenchEdgePayload[]
  progress: WorkbenchProgress
  next_action: WorkbenchNextAction
}

export type WorkbenchNodeKind = "wb-script" | "wb-asset" | "wb-beat" | "wb-episode"
export type WorkbenchPosition = { x: number; y: number }

export type WorkbenchGraphNode = {
  id: string
  type: WorkbenchNodeKind
  position: WorkbenchPosition
  data: Record<string, unknown>
}

export type WorkbenchGraphEdge = {
  id: string
  source: string
  target: string
  sourceHandle: string
  targetHandle: string
  type: "smoothstep"
  kind: WorkbenchEdgePayload["kind"]
  className: string
}

// 布局常量：三列派生图 —— 左（剧本+资产）→ 中（镜头链）→ 右（成片）
export const WB_SCRIPT_SIZE = { width: 236, height: 108 }
export const WB_ASSET_SIZE = { width: 236, height: 84 }
export const WB_BEAT_SIZE = { width: 268, height: 128 }
export const WB_EPISODE_SIZE = { width: 256, height: 148 }
const BEAT_ROWS_PER_COLUMN = 4
const BEAT_COLUMN_GAP = 92
const BEAT_ROW_GAP = 44
const BEAT_COLUMN_X0 = 392
const BEAT_Y0 = 24
const STAGE_LABELS: Record<WorkbenchStageKey, string> = {
  script: "剧本成型",
  assets: "出片素材",
  prompts: "生成指令",
  shots: "镜头出片",
}

const STAGE_ORDER: WorkbenchStageKey[] = ["script", "assets", "prompts", "shots"]

export function stageChips(progress: WorkbenchProgress | null | undefined): WorkbenchStage[] {
  if (!progress) return STAGE_ORDER.map(key => ({ key, label: STAGE_LABELS[key], done: 0, total: 0, ratio: 0, status: "locked" as const }))
  return STAGE_ORDER.map(key => {
    const stage = progress.stages?.[key] || { done: 0, total: 0, ratio: 0, status: "locked" as const }
    return { key, label: STAGE_LABELS[key], done: stage.done, total: stage.total, ratio: stage.ratio, status: stage.status }
  })
}

export function stageChipLabel(stage: WorkbenchStage): string {
  if (stage.status === "locked") return `${stage.label} · 未开始`
  if (!stage.total) return `${stage.label} · 暂无`
  return `${stage.label} ${stage.done}/${stage.total}`
}

/** 把工坊轮询的实时镜头进度盖到派生 beats 上（不改后端数据，只影响展示）。 */
export function applyLiveBeatStatus(
  beats: WorkbenchBeat[],
  live: Record<string, { status: string; shotStage?: string; shotUrl?: string; progress?: number; message?: string }>,
): WorkbenchBeat[] {
  if (!beats.length) return beats
  return beats.map(beat => {
    const shot = live[beat.id]
    if (!shot) return beat
    if (beat.has_video) return beat
    const stage = String(shot.shotStage || shot.status || "").trim()
    if (!stage) return beat
    const task_status = stage === "succeeded" ? beat.task_status : stage
    return {
      ...beat,
      task_status,
      awaiting_refine: stage === "awaiting_refine" || beat.awaiting_refine,
      video_url: shot.shotUrl || beat.video_url,
      has_video: beat.has_video || Boolean(shot.shotUrl),
      live_progress: task_status === "running" || task_status === "queued"
        ? (typeof shot.progress === "number" ? shot.progress : null)
        : undefined,
    }
  })
}

export function buildWorkbenchGraph(
  payload: WorkbenchPayload,
  savedPositions: Record<string, WorkbenchPosition> = {},
): { nodes: WorkbenchGraphNode[]; edges: WorkbenchGraphEdge[] } {
  const nodes: WorkbenchGraphNode[] = []
  const edges: WorkbenchGraphEdge[] = []

  nodes.push({
    id: "script-node",
    type: "wb-script",
    position: savedPositions["script-node"] || { x: 0, y: 0 },
    data: {
      episodeId: payload.episode.id,
      number: payload.episode.number,
      title: payload.episode.title,
      summary: payload.episode.summary,
      beatsTotal: payload.beats.length,
      overallPct: payload.progress.overall_pct,
    },
  })

  let assetY = WB_SCRIPT_SIZE.height + 56
  for (const asset of payload.assets) {
    const id = `asset-${asset.id}`
    nodes.push({
      id,
      type: "wb-asset",
      position: savedPositions[id] || { x: 0, y: assetY },
      data: { asset },
    })
    assetY += WB_ASSET_SIZE.height + 32
  }

  const ordered = [...payload.beats].sort((a, b) => (a.sequence || 0) - (b.sequence || 0))
  ordered.forEach((beat, index) => {
    const id = `beat-${beat.id}`
    const column = Math.floor(index / BEAT_ROWS_PER_COLUMN)
    const row = index % BEAT_ROWS_PER_COLUMN
    const position = savedPositions[id] || {
      x: BEAT_COLUMN_X0 + column * (WB_BEAT_SIZE.width + BEAT_COLUMN_GAP),
      y: BEAT_Y0 + row * (WB_BEAT_SIZE.height + BEAT_ROW_GAP),
    }
    nodes.push({ id, type: "wb-beat", position, data: { beat } })
  })

  const lastColumn = ordered.length ? Math.floor((ordered.length - 1) / BEAT_ROWS_PER_COLUMN) : 0
  const episodeX = ordered.length
    ? BEAT_COLUMN_X0 + (lastColumn + 1) * (WB_BEAT_SIZE.width + BEAT_COLUMN_GAP) + 24
    : BEAT_COLUMN_X0
  const beatBlockHeight = Math.min(ordered.length || 1, BEAT_ROWS_PER_COLUMN) * (WB_BEAT_SIZE.height + BEAT_ROW_GAP)
  nodes.push({
    id: "episode-video",
    type: "wb-episode",
    position: savedPositions["episode-video"] || { x: episodeX, y: BEAT_Y0 + Math.max(0, beatBlockHeight / 2 - WB_EPISODE_SIZE.height / 2) },
    data: {
      episodeId: payload.episode.id,
      number: payload.episode.number,
      title: payload.episode.title,
      videoUrl: payload.episode.episode_video_url,
      overallPct: payload.progress.overall_pct,
      shotsDone: payload.progress.shots_done,
      beatsTotal: payload.progress.beats_total,
    },
  })

  for (const edge of payload.edges) {
    edges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: "out",
      targetHandle: "in",
      kind: edge.kind,
      type: "smoothstep",
      className: `wb-edge wb-edge--${edge.kind}`,
    })
  }
  // 资产/剧本节点若被拖动过，边仍然由 payload 派生；这里补一条剧本→首镜的引导边。
  const firstBeat = ordered[0]
  if (firstBeat) {
    edges.push({ id: "e-script-entry", source: "script-node", target: `beat-${firstBeat.id}`, sourceHandle: "out", targetHandle: "in", type: "smoothstep", kind: "sequence", className: "wb-edge wb-edge--entry" })
  }
  return { nodes, edges }
}

export const WORKBENCH_LAYOUT_STORAGE_PREFIX = "workbench-layout-v1:"

export function workbenchLayoutKey(projectId: string, episodeId: string): string {
  return `${WORKBENCH_LAYOUT_STORAGE_PREFIX}${projectId}:${episodeId}`
}

export function loadWorkbenchLayout(projectId: string, episodeId: string): Record<string, WorkbenchPosition> {
  try {
    const raw = window.localStorage.getItem(workbenchLayoutKey(projectId, episodeId))
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object") return {}
    const result: Record<string, WorkbenchPosition> = {}
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      const position = value as WorkbenchPosition | null
      if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
        result[id] = { x: Number(position.x), y: Number(position.y) }
      }
    }
    return result
  } catch {
    return {}
  }
}

export function saveWorkbenchLayout(projectId: string, episodeId: string, positions: Record<string, WorkbenchPosition>) {
  try {
    window.localStorage.setItem(workbenchLayoutKey(projectId, episodeId), JSON.stringify(positions))
  } catch {
    /* 隐私模式 / 配额不足时布局不持久化，功能不受影响 */
  }
}

export function collectWorkbenchPositions(nodes: WorkbenchGraphNode[]): Record<string, WorkbenchPosition> {
  const result: Record<string, WorkbenchPosition> = {}
  for (const node of nodes) result[node.id] = { x: node.position.x, y: node.position.y }
  return result
}

/** 节点上的状态灯语义：颜色与文案统一从这里出。 */
export function beatStatusLamp(beat: Pick<WorkbenchBeat, "task_status" | "has_video" | "awaiting_refine" | "has_prompt" | "live_progress">): { tone: "ok" | "busy" | "warn" | "bad" | "idle"; label: string } {
  if (beat.has_video || beat.task_status === "succeeded") return { tone: "ok", label: "已出片" }
  if (beat.awaiting_refine || beat.task_status === "awaiting_refine") return { tone: "warn", label: "待确认" }
  const percent = typeof beat.live_progress === "number" ? ` ${Math.round(beat.live_progress)}%` : ""
  if (beat.task_status === "running") return { tone: "busy", label: `生成中${percent}` }
  if (beat.task_status === "queued") return { tone: "busy", label: `排队中${percent}` }
  if (beat.task_status === "failed") return { tone: "bad", label: "待修复" }
  return { tone: "idle", label: beat.has_prompt ? "待出片" : "缺指令" }
}

/** 运营待办：需要人工介入的镜头（二采待确认 / 出片失败）。 */
export function attentionBeats(beats: WorkbenchBeat[]): Array<{ beat: WorkbenchBeat; reason: "awaiting_refine" | "failed" }> {
  const result: Array<{ beat: WorkbenchBeat; reason: "awaiting_refine" | "failed" }> = []
  for (const beat of beats) {
    if (beat.awaiting_refine || beat.task_status === "awaiting_refine") result.push({ beat, reason: "awaiting_refine" })
    else if (beat.task_status === "failed") result.push({ beat, reason: "failed" })
  }
  return result.sort((a, b) => (a.beat.sequence || 0) - (b.beat.sequence || 0))
}

export type WorkbenchOverviewEpisode = {
  id: string
  number: number
  title: string
  beats_total: number
  prompts_done: number
  shots_done: number
  overall_pct: number
  running: boolean
  awaiting_refine: boolean
  failed?: boolean
  episode_video_url: string
}

/**
 * 失败镜头的可重试任务：取「最新一次提到该失败 beat 且已终态失败」的 video_generation 任务 id，
 * 去重后交给既有 /jobs/{id}/retry（复用已完成准备步骤）。进行中/已成功的任务不参与。
 */
export function retryableFailedJobIds(jobs: WorkshopVideoJobLike[], failedBeatIds: string[]): string[] {
  const failed = new Set(failedBeatIds.map(String))
  if (!failed.size) return []
  const result: string[] = []
  for (const job of jobs) {
    if (job.job_type !== "video_generation") continue
    if (String(job.status || "") !== "failed") continue
    const id = String(job.id || "")
    if (!id || result.includes(id)) continue
    const beatIds = (job.payload?.beat_ids || []).map(String)
    const singleBeat = String(job.payload?.beat_id || "")
    if (beatIds.some(beatId => failed.has(beatId)) || (singleBeat && failed.has(singleBeat))) {
      result.push(id)
    }
  }
  return result
}

/** 总览分集卡的徽标文案：状态优先于百分比。 */
export function overviewEpisodeBadge(episode: Pick<WorkbenchOverviewEpisode, "running" | "awaiting_refine" | "failed" | "beats_total" | "shots_done" | "overall_pct">): { tone: "ok" | "busy" | "warn" | "bad" | "idle"; label: string } {
  if (episode.running) return { tone: "busy", label: "出片中" }
  if (episode.awaiting_refine) return { tone: "warn", label: "有待确认镜头" }
  if (episode.failed) return { tone: "bad", label: "有镜头出片失败" }
  if (episode.beats_total && episode.shots_done >= episode.beats_total) return { tone: "ok", label: "镜头已全部出片" }
  if (!episode.beats_total) return { tone: "idle", label: "还没有分镜" }
  return { tone: "idle", label: `${episode.shots_done}/${episode.beats_total} 镜已出片` }
}

export function assetStatusLamp(asset: Pick<WorkbenchAsset, "ready" | "looks_ready" | "looks_total">): { tone: "ok" | "warn"; label: string } {
  if (asset.ready) return { tone: "ok", label: "素材就绪" }
  return { tone: "warn", label: asset.looks_total > 1 ? `${asset.looks_ready}/${asset.looks_total} 造型` : "缺图" }
}
