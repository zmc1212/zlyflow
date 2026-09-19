// Hypit 复刻（hypit_replication）payload 类型与工厂。
// 与后端 director_hypit.py 的 normalize 规则一一对应。
// 与 shot_replication（VACE 锁运镜）并列，禁止混用。

export type HypitJobStatus = "idle" | "running" | "done" | "failed"
export type HypitLanguage = "zh" | "en"

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
  workspacePath?: string | null
  sourceVideo: HypitSourceVideo | null
  transcript: {
    status: HypitJobStatus
    path?: string | null
    url?: string | null
    wordCount: number
    durationSec: number
    error?: string | null
  }
  compile: {
    status: HypitJobStatus
    buildId?: string | null
    error?: string | null
  }
  result: {
    path?: string | null
    url?: string | null
    buildId?: string | null
  }
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
    workspacePath: null,
    sourceVideo: null,
    transcript: {
      status: "idle",
      path: null,
      url: null,
      wordCount: 0,
      durationSec: 0,
      error: null,
    },
    compile: {
      status: "idle",
      buildId: null,
      error: null,
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
  return {
    ...base,
    title: text(source.title),
    brief: text(source.brief),
    language,
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
    },
    compile: {
      status: status(compile?.status),
      buildId: text(compile?.buildId) || null,
      error: text(compile?.error) || null,
    },
    result: {
      path: text(result?.path) || null,
      url: text(result?.url) || null,
      buildId: text(result?.buildId) || null,
    },
  }
}
