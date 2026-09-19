// Hypit 复刻（hypit_replication）payload 类型与工厂。
// 与后端 director_hypit.py 的 normalize 规则一一对应。
// 与 shot_replication（VACE 锁运镜）并列，禁止混用。

export type HypitJobStatus = "idle" | "running" | "done" | "failed"
export type HypitLanguage = "zh" | "en"
export type HypitH3Quality = "safe" | "balanced" | "official"

export const HYPIT_H3_QUALITY_DEFAULT: HypitH3Quality = "safe"

export const HYPIT_H3_QUALITIES: ReadonlyArray<{
  value: HypitH3Quality
  megapixels: number
  width: number
  height: number
  label: string
  hint: string
}> = [
  { value: "safe", megapixels: 0.6, width: 608, height: 1056, label: "16GB 稳妥", hint: "608×1056，16GB 卡先选这项" },
  { value: "balanced", megapixels: 0.7, width: 640, height: 1152, label: "均衡", hint: "640×1152" },
  { value: "official", megapixels: 0.98, width: 768, height: 1344, label: "官方 768P", hint: "768×1344，16GB 卡上次会卡死" },
]

export type HypitSourceVideo = {
  path?: string | null
  url?: string | null
  name?: string | null
  width: number
  height: number
  fps: number
  durationSec: number
}

export type HypitPayload = {
  kind: "hypit_replication"
  schemaVersion: number
  title: string
  brief: string
  language: HypitLanguage
  h3Quality: HypitH3Quality
  workspacePath?: string | null
  sourceVideo: HypitSourceVideo | null
  transcript: {
    status: HypitJobStatus
    path?: string | null
    url?: string | null
    wordCount: number
    durationSec: number
    error?: string | null
    operationId?: string | null
    progress?: number
    message?: string | null
  }
  compile: {
    status: HypitJobStatus
    buildId?: string | null
    operationId?: string | null
    error?: string | null
    progress?: number
    message?: string | null
  }
  result: {
    path?: string | null
    url?: string | null
    buildId?: string | null
  }
}

export function hypitOperationMessage(kind: string | undefined): string {
  if (kind === "hypit_transcribe") return "正在拉片转写"
  if (kind === "hypit_compile") return "正在编译"
  return "正在处理"
}

export type HypitStatusLine = { progress: number; message?: string }

export function hypitStatusLineFromPayload(payload: HypitPayload): HypitStatusLine | null {
  const compile = payload.compile
  const transcript = payload.transcript
  if (compile.status === "running") {
    return {
      progress: compile.progress ?? 0,
      message: compile.message || hypitOperationMessage("hypit_compile"),
    }
  }
  if (transcript.status === "running") {
    return {
      progress: transcript.progress ?? 0,
      message: transcript.message || hypitOperationMessage("hypit_transcribe"),
    }
  }
  if (compile.status === "failed") {
    return {
      progress: compile.progress ?? 100,
      message: compile.message || compile.error || hypitOperationMessage("hypit_compile"),
    }
  }
  if (transcript.status === "failed") {
    return {
      progress: transcript.progress ?? 100,
      message: transcript.message || transcript.error || hypitOperationMessage("hypit_transcribe"),
    }
  }
  return null
}

type DirectorOperationLike = {
  id?: string
  kind?: string
  status?: string
  progress?: number
  result?: { message?: string }
}

export type HypitResumeTarget = {
  operationId: string
  progress: number
  message: string
}

export function hypitResumeFromProject(record: {
  payload?: unknown
  active_operation?: DirectorOperationLike | null
} | null | undefined): HypitResumeTarget | null {
  const active = record?.active_operation
  if (
    active?.id
    && (active.status === "queued" || active.status === "running")
    && (active.kind === "hypit_transcribe" || active.kind === "hypit_compile")
  ) {
    const stored = record?.payload && typeof record.payload === "object"
      ? hypitStatusLineFromPayload(normalizeHypitPayload(record.payload))
      : null
    return {
      operationId: active.id,
      progress: Math.max(stored?.progress ?? 0, typeof active.progress === "number" ? active.progress : 0),
      message: stored?.message || active.result?.message || hypitOperationMessage(active.kind),
    }
  }
  return null
}

export function conflictingDirectorOperationId(error: unknown): string | null {
  const text = error instanceof Error ? error.message : ""
  const match = text.match(/工程已有未完成的导演操作：(director-op-[a-f0-9]+)/i)
  return match?.[1] ?? null
}

export function isHypitPayload(payload: unknown): payload is HypitPayload {
  return Boolean(payload && typeof payload === "object" && (payload as { kind?: string }).kind === "hypit_replication")
}

export function createEmptyHypit(title = ""): HypitPayload {
  return {
    kind: "hypit_replication",
    schemaVersion: 1,
    title,
    brief: "",
    language: "zh",
    h3Quality: HYPIT_H3_QUALITY_DEFAULT,
    workspacePath: null,
    sourceVideo: null,
    transcript: {
      status: "idle",
      path: null,
      url: null,
      wordCount: 0,
      durationSec: 0,
      error: null,
      operationId: null,
      progress: 0,
      message: null,
    },
    compile: {
      status: "idle",
      buildId: null,
      operationId: null,
      error: null,
      progress: 0,
      message: null,
    },
    result: {
      path: null,
      url: null,
      buildId: null,
    },
  }
}

export function normalizeHypitPayload(raw: unknown): HypitPayload {
  const base = createEmptyHypit()
  if (!raw || typeof raw !== "object") return base
  const source = raw as Record<string, unknown>
  const sourceVideo = source.sourceVideo as Record<string, unknown> | null | undefined
  const transcript = source.transcript as Record<string, unknown> | null | undefined
  const compile = source.compile as Record<string, unknown> | null | undefined
  const result = source.result as Record<string, unknown> | null | undefined
  const number = (value: unknown, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback
  const text = (value: unknown) => (typeof value === "string" ? value.trim() : "")
  const status = (value: unknown): HypitJobStatus => {
    const item = text(value)
    return item === "running" || item === "done" || item === "failed" ? item : "idle"
  }
  const language = text(source.language) === "en" ? "en" : "zh"
  const qualityText = text(source.h3Quality)
  const h3Quality: HypitH3Quality = qualityText === "balanced" || qualityText === "official" ? qualityText : HYPIT_H3_QUALITY_DEFAULT
  return {
    ...base,
    title: text(source.title),
    brief: text(source.brief),
    language,
    h3Quality,
    workspacePath: text(source.workspacePath) || null,
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
    transcript: {
      status: status(transcript?.status),
      path: text(transcript?.path) || null,
      url: text(transcript?.url) || null,
      wordCount: number(transcript?.wordCount, 0),
      durationSec: number(transcript?.durationSec, 0),
      error: text(transcript?.error) || null,
      operationId: text(transcript?.operationId) || null,
      progress: Math.max(0, Math.min(100, Math.round(number(transcript?.progress, 0)))),
      message: text(transcript?.message) || null,
    },
    compile: {
      status: status(compile?.status),
      buildId: text(compile?.buildId) || null,
      operationId: text(compile?.operationId) || null,
      error: text(compile?.error) || null,
      progress: Math.max(0, Math.min(100, Math.round(number(compile?.progress, 0)))),
      message: text(compile?.message) || null,
    },
    result: {
      path: text(result?.path) || null,
      url: text(result?.url) || null,
      buildId: text(result?.buildId) || null,
    },
  }
}
