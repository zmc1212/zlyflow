import { ApiRequestError } from "../api"

export type CanvasSaveState = "saved" | "dirty" | "saving" | "retrying" | "error" | "conflict"

export type CanvasSaveOutcome = "saved" | "dirty" | "failed"

/** Serialize requests and keep saving edits made while an earlier request was in flight. */
export function createCanvasSaveQueue(save: (notify: boolean) => Promise<CanvasSaveOutcome>) {
  let pending: Promise<boolean> | null = null
  return function flush(notify = false): Promise<boolean> {
    if (pending) return pending
    pending = (async () => {
      let outcome: CanvasSaveOutcome
      do {
        outcome = await save(notify)
      } while (outcome === "dirty")
      return outcome === "saved"
    })().finally(() => { pending = null })
    return pending
  }
}

export const CANVAS_CONTENT_LIMIT_BYTES = 8 * 1024 * 1024
export const CANVAS_CONTENT_WARN_BYTES = 6 * 1024 * 1024
export const CANVAS_SAVE_RETRY_DELAYS_MS = [2000, 5000, 10000] as const
export const CANVAS_VIRTUALIZE_NODE_LIMIT = 300

export type CanvasContentSizeLevel = "ok" | "warning" | "over"

export function canvasByteSize(content: string): number {
  return new TextEncoder().encode(content).length
}

export function canvasContentSizeLevel(bytes: number): CanvasContentSizeLevel {
  if (bytes > CANVAS_CONTENT_LIMIT_BYTES) return "over"
  return bytes >= CANVAS_CONTENT_WARN_BYTES ? "warning" : "ok"
}

export function formatCanvasBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export function nextCanvasSaveRetryDelay(retryCount: number): number | null {
  if (!Number.isInteger(retryCount) || retryCount < 0) return null
  return CANVAS_SAVE_RETRY_DELAYS_MS[retryCount] ?? null
}

export function isCanvasSaveRetryable(error: unknown): boolean {
  if (!(error instanceof ApiRequestError)) return true
  return error.status >= 500 || error.status === 408 || error.status === 429
}

export function canvasConflictVersion(error: unknown): number | null {
  if (!(error instanceof ApiRequestError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { current_version?: unknown } } | null)?.detail
  return typeof detail?.current_version === "number" ? detail.current_version : 0
}

export function saveStateAfterCanvasEdit(state: CanvasSaveState): CanvasSaveState {
  return state === "conflict" || state === "retrying" || state === "saving" ? state : "dirty"
}

export function saveStateAfterCanvasSave(stillCurrent: boolean): CanvasSaveState {
  return stillCurrent ? "saved" : "dirty"
}

export function shouldVirtualizeCanvasNodes(nodeCount: number): boolean {
  return nodeCount > CANVAS_VIRTUALIZE_NODE_LIMIT
}
