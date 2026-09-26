import type { WorkshopPromptStreamEvent } from "./workshop-prompt-stream"

const TERMINAL = new Set(["completed", "succeeded", "failed", "cancelled", "interrupted"])

/** Transport events wake the reader; only the persisted job decides completion. */
export async function waitForPersistedPromptJob<T extends { status: string }>(options: {
  getJob: () => Promise<T>
  stream: (onEvent: (event: WorkshopPromptStreamEvent) => void, signal: AbortSignal) => Promise<unknown>
  onEvent: (event: WorkshopPromptStreamEvent) => void
  onReconnecting: () => void
  signal: AbortSignal
  pollMs?: number
  reconnectMs?: number
}): Promise<T> {
  const controller = new AbortController()
  const delay = (ms: number) => new Promise<void>(resolve => {
    if (controller.signal.aborted) return resolve()
    const finish = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", finish); resolve() }
    const timer = setTimeout(finish, ms)
    controller.signal.addEventListener("abort", finish, { once: true })
  })
  let settled = false
  let reading = false
  let resolveJob!: (job: T) => void
  let rejectJob!: (error: unknown) => void
  const result = new Promise<T>((resolve, reject) => { resolveJob = resolve; rejectJob = reject })
  const abort = () => { settled = true; controller.abort(); rejectJob(new DOMException("Preview listener disposed", "AbortError")) }
  const read = async () => {
    if (reading || settled) return
    reading = true
    try {
      const job = await options.getJob()
      if (!settled && TERMINAL.has(job.status)) { settled = true; resolveJob(job); controller.abort() }
    } catch {
      if (!settled) options.onReconnecting()
    } finally { reading = false }
  }
  options.signal.addEventListener("abort", abort, { once: true })
  if (options.signal.aborted) abort()
  void (async () => {
    while (!settled) { await read(); if (!settled) await delay(options.pollMs ?? 15_000) }
  })()
  void (async () => {
    while (!settled) {
      try {
        await options.stream(event => {
          if (settled) return
          options.onEvent(event)
          if (event.event === "done" || event.event === "error") void read()
        }, controller.signal)
      } catch { /* A transport failure is not a job failure. */ }
      if (!settled) {
        options.onReconnecting()
        await delay(options.reconnectMs ?? 5_000)
      }
    }
  })()
  try { return await result } finally {
    settled = true
    controller.abort()
    options.signal.removeEventListener("abort", abort)
  }
}
