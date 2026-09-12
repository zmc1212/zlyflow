// 复刻台（shot_replication）payload 类型与工厂。
// 与后端 director_replication.py 的 normalize 规则一一对应。

export type ReplicationAnalysisStatus = "idle" | "running" | "done" | "failed"
export type ReplicationShotStatus = "idle" | "ready" | "queued" | "running" | "succeeded" | "failed"
export type ReplicationEngine = "vace_depth" | "h3_r2v"

export type ReplicationSourceVideo = {
  path?: string | null
  url?: string | null
  name?: string | null
  width: number
  height: number
  fps: number
  durationSec: number
}

export type ReplicationAnalysis = {
  status: ReplicationAnalysisStatus
  mode: "smart" | "fixed"
  segmentSeconds: number
  sceneThreshold: number
  depthStatus: ReplicationAnalysisStatus
  depthPath?: string | null
  depthUrl?: string | null
  visionModel?: string | null
  error?: string | null
  startedAt?: string | null
  finishedAt?: string | null
}

export type ReplicationRenderSettings = {
  engine: ReplicationEngine
  keepFirstFrame: boolean
  artStyle: string
  vaceStrength: number
  steps: number
  seed: number | null
}

export type ReplicationSubject = {
  id: string
  name: string
  type: "character" | "scene" | "prop"
  description: string
  refPath?: string | null
  refUrl?: string | null
  shotIds: string[]
  hidden: boolean
}

export type ReplicationTake = {
  id: string
  takeNumber: number
  jobId?: string | null
  videoUrl?: string | null
  outputPath?: string | null
  status: string
  progress: number
  error?: string | null
  createdAt?: string | null
  promptSnapshot?: string | null
  workflowId?: string | null
  videoWorkflowFamily?: string | null
  options?: Record<string, unknown>
}

export type ReplicationShot = {
  id: string
  shotNumber: number
  timeStart: number
  timeEnd: number
  durationSec: number
  segmentPath?: string | null
  segmentUrl?: string | null
  keyframePaths: string[]
  keyframeUrls: string[]
  depthPath?: string | null
  depthUrl?: string | null
  promptText: string
  compiledPrompt: string
  negativePrompt: string
  subjectBindings: string[]
  keepFirstFrame: boolean
  status: ReplicationShotStatus
  jobId?: string | null
  progress: number
  error?: string | null
  analysisNote?: string | null
  cameraNote?: string | null
  takes: ReplicationTake[]
}

export type ReplicationPayload = {
  kind: "shot_replication"
  schemaVersion: number
  title: string
  sourceVideo: ReplicationSourceVideo | null
  analysis: ReplicationAnalysis
  renderSettings: ReplicationRenderSettings
  subjects: ReplicationSubject[]
  shots: ReplicationShot[]
}

export function isReplicationPayload(payload: unknown): payload is ReplicationPayload {
  return Boolean(payload && typeof payload === "object" && (payload as { kind?: string }).kind === "shot_replication")
}

export function createEmptyReplication(title = ""): ReplicationPayload {
  return {
    kind: "shot_replication",
    schemaVersion: 1,
    title,
    sourceVideo: null,
    analysis: {
      status: "idle",
      mode: "smart",
      segmentSeconds: 15,
      sceneThreshold: 0.35,
      depthStatus: "idle",
      depthPath: null,
      depthUrl: null,
      visionModel: null,
      error: null,
      startedAt: null,
      finishedAt: null,
    },
    renderSettings: {
      engine: "vace_depth",
      keepFirstFrame: true,
      artStyle: "",
      vaceStrength: 1.0,
      steps: 30,
      seed: null,
    },
    subjects: [],
    shots: [],
  }
}

/** 后端返回的 payload 宽松归一化：补齐缺省字段，容忍旧数据。 */
export function normalizeReplicationPayload(raw: unknown): ReplicationPayload {
  const base = createEmptyReplication()
  if (!raw || typeof raw !== "object") return base
  const source = raw as Record<string, unknown>
  const sourceVideo = source.sourceVideo as Record<string, unknown> | null | undefined
  const analysis = source.analysis as Record<string, unknown> | null | undefined
  const settings = source.renderSettings as Record<string, unknown> | null | undefined
  const number = (value: unknown, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback
  const text = (value: unknown) => (typeof value === "string" ? value : "")
  const shots = Array.isArray(source.shots) ? source.shots : []
  const subjects = Array.isArray(source.subjects) ? source.subjects : []
  return {
    ...base,
    title: text(source.title),
    sourceVideo: sourceVideo
      ? {
          path: text(sourceVideo.path) || null,
          url: text(sourceVideo.url) || null,
          name: text(sourceVideo.name) || null,
          width: number(sourceVideo.width, 0),
          height: number(sourceVideo.height, 0),
          fps: number(sourceVideo.fps, 0),
          durationSec: number(sourceVideo.durationSec, 0),
        }
      : null,
    analysis: {
      ...base.analysis,
      ...(analysis as Record<string, unknown> | undefined),
      status: (["idle", "running", "done", "failed"] as string[]).includes(text(analysis?.status))
        ? (analysis!.status as ReplicationAnalysisStatus)
        : "idle",
      depthStatus: (["idle", "running", "done", "failed"] as string[]).includes(text(analysis?.depthStatus))
        ? (analysis!.depthStatus as ReplicationAnalysisStatus)
        : "idle",
      mode: text(analysis?.mode) === "fixed" ? "fixed" : "smart",
      segmentSeconds: number(analysis?.segmentSeconds, 15),
      sceneThreshold: number(analysis?.sceneThreshold, 0.35),
    },
    renderSettings: {
      ...base.renderSettings,
      ...(settings as Record<string, unknown> | undefined),
      engine: text(settings?.engine) === "h3_r2v" ? "h3_r2v" : "vace_depth",
      keepFirstFrame: typeof settings?.keepFirstFrame === "boolean" ? (settings!.keepFirstFrame as boolean) : true,
      artStyle: text(settings?.artStyle),
      vaceStrength: number(settings?.vaceStrength, 1.0),
      steps: number(settings?.steps, 30),
      seed: typeof settings?.seed === "number" ? (settings!.seed as number) : null,
    },
    subjects: subjects as ReplicationSubject[],
    shots: (shots as Record<string, unknown>[]).map((shot, index) => ({
      ...shot,
      shotNumber: number(shot.shotNumber, index + 1),
      timeStart: number(shot.timeStart, 0),
      timeEnd: number(shot.timeEnd, 0),
      durationSec: number(shot.durationSec, 0),
      keyframePaths: Array.isArray(shot.keyframePaths) ? shot.keyframePaths : [],
      keyframeUrls: Array.isArray(shot.keyframeUrls) ? shot.keyframeUrls : [],
      subjectBindings: Array.isArray(shot.subjectBindings) ? shot.subjectBindings : [],
      promptText: text(shot.promptText),
      compiledPrompt: text(shot.compiledPrompt),
      negativePrompt: text(shot.negativePrompt),
      keepFirstFrame: typeof shot.keepFirstFrame === "boolean" ? (shot.keepFirstFrame as boolean) : true,
      status: (["idle", "ready", "queued", "running", "succeeded", "failed"] as string[]).includes(text(shot.status))
        ? (shot.status as ReplicationShotStatus)
        : "idle",
      progress: number(shot.progress, 0),
      takes: Array.isArray(shot.takes) ? (shot.takes as ReplicationTake[]) : [],
    })) as ReplicationShot[],
  }
}

export const REPLICATION_ANALYSIS_STATUS_LABEL: Record<ReplicationAnalysisStatus, string> = {
  idle: "待分析",
  running: "分析中",
  done: "已完成",
  failed: "失败",
}

export const REPLICATION_SHOT_STATUS_LABEL: Record<ReplicationShotStatus, string> = {
  idle: "待确认",
  ready: "待转绘",
  queued: "排队中",
  running: "转绘中",
  succeeded: "已完成",
  failed: "失败",
}
