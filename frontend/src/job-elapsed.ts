import { useEffect, useState } from "react"

const LIVE_STATUSES = new Set(["queued", "running", "interrupted"])

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
  return `${minutes}:${String(seconds).padStart(2, "0")}`
}

function parseTimestamp(value?: string | null): number | null {
  if (!value) return null
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? ms : null
}

export function isLiveStatus(status?: string | null): boolean {
  return Boolean(status && LIVE_STATUSES.has(status))
}

export function jobElapsedMs(options: {
  createdAt?: string | null
  finishedAt?: string | null
  elapsedMs?: number | null
  now: number
  live: boolean
}): number | null {
  if (!options.live && typeof options.elapsedMs === "number" && Number.isFinite(options.elapsedMs)) {
    return Math.max(0, Math.round(options.elapsedMs))
  }
  const start = parseTimestamp(options.createdAt)
  if (start == null) return null
  if (options.live) return Math.max(0, options.now - start)
  const end = parseTimestamp(options.finishedAt)
  if (end == null) return null
  return Math.max(0, end - start)
}

export function elapsedCaption(ms: number | null, live: boolean): string {
  if (ms == null) return ""
  const clock = formatElapsed(ms)
  return live ? `已等待 ${clock}` : `用时 ${clock}`
}

export function executionCaption(executionElapsedMs?: number | null): string {
  if (typeof executionElapsedMs !== "number" || !Number.isFinite(executionElapsedMs) || executionElapsedMs < 0) {
    return ""
  }
  return `ComfyUI 推理 ${formatElapsed(executionElapsedMs)}`
}

export function useNow(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) {
      setNow(Date.now())
      return
    }
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [active, intervalMs])
  return now
}
