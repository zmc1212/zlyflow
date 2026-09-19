import { notifyUnauthorized } from "../api"

export type PromptStreamEpisodeFields = {
  episode_num?: number | null
  episode_index?: number
  episode_total?: number
}

export type WorkshopPromptStreamEvent =
  | {
    seq: number
    event: "status"
    data: {
      phase?: string
      message?: string
      reset?: boolean
      reasoning?: string
      text?: string
    } & PromptStreamEpisodeFields
  }
  | { seq: number; event: "reasoning"; data: { text?: string } & PromptStreamEpisodeFields }
  | { seq: number; event: "delta"; data: { text?: string } & PromptStreamEpisodeFields }
  | {
    seq: number
    event: "episode_done"
    data: {
      episode_num?: number | null
      episode_index?: number
      episode_total?: number
      shots?: Array<Record<string, unknown>>
      shots_count?: number
      shots_source?: string | null
      error?: string | null
    }
  }
  | {
    seq: number
    event: "done"
    data: {
      status?: string
      prompt?: string
      document_id?: string
      planned_episodes?: number
      failed_episodes?: number
      episodes_done?: Array<Record<string, unknown>>
    }
  }
  | { seq: number; event: "error"; data: { status?: string; message?: string } }
  | { seq: number; event: "keep-alive"; data: Record<string, unknown> }

const TERMINAL_EVENTS = new Set(["done", "error", "cancelled"])

export function isTerminalPromptStreamEvent(event: WorkshopPromptStreamEvent): boolean {
  return TERMINAL_EVENTS.has(event.event)
}

export function h3PromptJobEventsUrl(projectId: string, jobId: string, since = 0): string {
  const base = `/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/events`
  return since > 0 ? `${base}?since=${since}` : base
}

export type WorkshopPromptLiveState = {
  jobId: string
  phase: string
  message: string
  reasoning: string
  text: string
  startedAt: number
  working: boolean
  failed: boolean
}

export function emptyPromptLiveState(jobId = ""): WorkshopPromptLiveState {
  return {
    jobId,
    phase: "write",
    message: "正在生成提示词",
    reasoning: "",
    text: "",
    startedAt: Date.now(),
    working: Boolean(jobId),
    failed: false,
  }
}

export function applyPromptStreamEvent(
  state: WorkshopPromptLiveState,
  event: WorkshopPromptStreamEvent,
): WorkshopPromptLiveState {
  if (event.event === "keep-alive") return state
  if (event.event === "status") {
    const reset = Boolean(event.data.reset)
    return {
      ...state,
      phase: String(event.data.phase || state.phase || "write"),
      message: String(event.data.message || state.message || "正在生成提示词"),
      reasoning: reset ? String(event.data.reasoning || "") : (event.data.reasoning ?? state.reasoning),
      text: reset ? String(event.data.text || "") : (event.data.text ?? state.text),
      working: true,
      failed: false,
    }
  }
  if (event.event === "reasoning") {
    return { ...state, reasoning: String(event.data.text || ""), working: true, failed: false }
  }
  if (event.event === "delta") {
    return { ...state, text: String(event.data.text || ""), working: true, failed: false }
  }
  if (event.event === "episode_done") return state
  if (event.event === "done") {
    const prompt = String(event.data.prompt || state.text || "")
    return { ...state, text: prompt || state.text, working: false, failed: false, message: "提示词已生成" }
  }
  if (event.event === "error") {
    return { ...state, working: false, failed: true, message: String(event.data.message || "生成失败") }
  }
  return state
}

export function applyPromptJobSnapshot(
  state: WorkshopPromptLiveState,
  payload: { stream?: { phase?: string; message?: string; reasoning?: string; text?: string } | null } | null | undefined,
): WorkshopPromptLiveState {
  const stream = payload?.stream
  if (!stream) return state
  const nextReasoning = String(stream.reasoning || "")
  const nextText = String(stream.text || "")
  return {
    ...state,
    phase: String(stream.phase || state.phase),
    message: String(stream.message || state.message),
    reasoning: nextReasoning.length >= state.reasoning.length ? nextReasoning : state.reasoning,
    text: nextText.length >= state.text.length ? nextText : state.text,
  }
}

type StreamOptions = {
  since?: number
  signal?: AbortSignal
  shouldContinue?: () => boolean
}

const MAX_ATTEMPTS = 4
const RETRY_DELAYS_MS = [800, 1600, 3200]

function parseFrame(raw: string): WorkshopPromptStreamEvent | null {
  let eventName = "message"
  let seq = 0
  const dataLines: string[] = []
  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue
    const colon = line.indexOf(":")
    const field = colon < 0 ? line : line.slice(0, colon)
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "")
    if (field === "event") eventName = value
    else if (field === "id") seq = Number.parseInt(value, 10) || 0
    else if (field === "data") dataLines.push(value)
  }
  if (!dataLines.length) return null
  try {
    const data = JSON.parse(dataLines.join("\n")) as WorkshopPromptStreamEvent["data"]
    return { seq, event: eventName, data } as WorkshopPromptStreamEvent
  } catch {
    return null
  }
}

function extractResumeSeq(raw: string): number {
  let seq = 0
  for (const line of raw.split("\n")) {
    if (line.startsWith("id:")) seq = Number.parseInt(line.slice(3).trim(), 10) || seq
  }
  return seq
}

async function readStream(
  projectId: string,
  jobId: string,
  since: number,
  onEvent: (event: WorkshopPromptStreamEvent) => void,
  signal: AbortSignal,
  resume: { lastSeq: number },
): Promise<{ terminal: boolean }> {
  const response = await fetch(h3PromptJobEventsUrl(projectId, jobId, since), {
    signal,
    headers: { Accept: "text/event-stream" },
  })
  if (!response.ok || !response.body) {
    if (response.status === 401) notifyUnauthorized()
    throw new Error(`事件流连接失败（HTTP ${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""
  let terminal = false
  const handleFrame = (raw: string) => {
    resume.lastSeq = Math.max(resume.lastSeq, extractResumeSeq(raw))
    const event = parseFrame(raw)
    if (!event) return
    onEvent(event)
    if (isTerminalPromptStreamEvent(event)) terminal = true
  }
  try {
    while (!terminal) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
      let boundary = buffer.indexOf("\n\n")
      while (boundary >= 0) {
        handleFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf("\n\n")
      }
    }
  } finally {
    reader.releaseLock()
  }
  return { terminal }
}

export async function streamH3PromptJobEvents(
  projectId: string,
  jobId: string,
  onEvent: (event: WorkshopPromptStreamEvent) => void,
  options: StreamOptions = {},
): Promise<"terminal" | "aborted" | "failed"> {
  const signal = options.signal ?? new AbortController().signal
  const resume = { lastSeq: Math.max(0, options.since ?? 0) }
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    if (signal.aborted) return "aborted"
    if (options.shouldContinue && !options.shouldContinue()) return "aborted"
    try {
      const { terminal } = await readStream(projectId, jobId, resume.lastSeq, onEvent, signal, resume)
      if (terminal) return "terminal"
    } catch (error) {
      if (signal.aborted) return "aborted"
      if (options.shouldContinue && !options.shouldContinue()) return "aborted"
      if (error instanceof TypeError && attempt === 0) return "failed"
    }
    if (attempt < RETRY_DELAYS_MS.length) {
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt]))
    }
  }
  return "failed"
}
