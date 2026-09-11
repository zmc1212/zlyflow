/**
 * SSE client for director operation event streams.
 *
 * Connects to `GET /api/director/operations/{id}/events`, parses the
 * `text/event-stream` frames by hand (the platform has no EventSource helper
 * and we need `since=` resume plus AbortController support), and reports every
 * event to the caller. Transient disconnects are retried with `since=` resume;
 * callers keep the existing 1.2s polling as the safety net, so a permanently
 * failed stream degrades to today's behaviour instead of breaking the run.
 */

export type ScriptStreamField = "title" | "summary" | "fullStory"

export type AgentStreamItem = Record<string, unknown>

export type DirectorOperationStreamEvent =
  | { seq: number; event: "status"; data: { status: string; progress?: number; message?: string } }
  | { seq: number; event: "agent"; data: { id: string; status: string; message?: string } }
  | {
    seq: number
    event: "agent_delta"
    data: { agent: string; field: string; index: number | null; delta: string; reset: boolean }
  }
  | { seq: number; event: "agent_item"; data: { agent: string; field: string; index: number; item: AgentStreamItem } }
  | { seq: number; event: "done"; data: { status: string; result?: Record<string, unknown> } }
  | { seq: number; event: "cancelled"; data: { status: string; message?: string } }
  | { seq: number; event: "error"; data: { status: string; message?: string } }

const TERMINAL_EVENTS = new Set(["done", "cancelled", "error"])

export function isTerminalStreamEvent(event: DirectorOperationStreamEvent): boolean {
  return TERMINAL_EVENTS.has(event.event)
}

type StreamOptions = {
  since?: number
  signal?: AbortSignal
  /** Extra guard so stale panels stop reconnecting after unmount. */
  shouldContinue?: () => boolean
}

const MAX_ATTEMPTS = 4
const RETRY_DELAYS_MS = [800, 1600, 3200]

function parseFrame(raw: string): DirectorOperationStreamEvent | null {
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
    const data = JSON.parse(dataLines.join("\n")) as DirectorOperationStreamEvent["data"]
    return { seq, event: eventName, data } as DirectorOperationStreamEvent
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
  operationId: string,
  since: number,
  onEvent: (event: DirectorOperationStreamEvent) => void,
  signal: AbortSignal,
  resume: { lastSeq: number },
): Promise<{ terminal: boolean }> {
  const response = await fetch(
    `/api/director/operations/${encodeURIComponent(operationId)}/events${since > 0 ? `?since=${since}` : ""}`,
    { signal, headers: { Accept: "text/event-stream" } },
  )
  if (!response.ok || !response.body) {
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
    if (isTerminalStreamEvent(event)) terminal = true
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

export async function streamDirectorOperationEvents(
  operationId: string,
  onEvent: (event: DirectorOperationStreamEvent) => void,
  options: StreamOptions = {},
): Promise<"terminal" | "aborted" | "failed"> {
  const signal = options.signal ?? new AbortController().signal
  const resume = { lastSeq: Math.max(0, options.since ?? 0) }
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    if (signal.aborted) return "aborted"
    if (options.shouldContinue && !options.shouldContinue()) return "aborted"
    try {
      const { terminal } = await readStream(operationId, resume.lastSeq, onEvent, signal, resume)
      if (terminal) return "terminal"
      // Clean close without a terminal frame (server restart, proxy cut).
    } catch (error) {
      if (signal.aborted) return "aborted"
      if (options.shouldContinue && !options.shouldContinue()) return "aborted"
      if (error instanceof TypeError && attempt === 0) {
        // Network layer refused outright (backend down, ad-blocker): the
        // polling fallback already covers this; do not hammer retries.
        return "failed"
      }
    }
    if (attempt < RETRY_DELAYS_MS.length) {
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt]))
    }
  }
  return "failed"
}
