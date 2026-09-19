export const VOICE_EXTRACT_MIN_SEC = 1
export const VOICE_EXTRACT_MAX_SEC = 15
export const VOICE_EXTRACT_HINT = "请框选该角色单独说话的片段"

function round3(value: number): number {
  return Math.round(value * 1000) / 1000
}

export function clampVoiceExtractWindow(
  start: number,
  end: number,
  durationSec: number,
): [number, number] {
  const duration = Math.max(0, Number.isFinite(durationSec) ? durationSec : 0)
  let left = Number.isFinite(start) ? start : 0
  let right = Number.isFinite(end) ? end : 0
  if (right < left) {
    const swap = left
    left = right
    right = swap
  }
  left = Math.min(Math.max(0, left), duration)
  right = Math.min(Math.max(0, right), duration)
  if (right - left > VOICE_EXTRACT_MAX_SEC) {
    right = left + VOICE_EXTRACT_MAX_SEC
    if (right > duration) {
      right = duration
      left = Math.max(0, right - VOICE_EXTRACT_MAX_SEC)
    }
  }
  if (duration >= VOICE_EXTRACT_MIN_SEC && right - left < VOICE_EXTRACT_MIN_SEC) {
    right = Math.min(duration, left + VOICE_EXTRACT_MIN_SEC)
    if (right - left < VOICE_EXTRACT_MIN_SEC) {
      left = Math.max(0, right - VOICE_EXTRACT_MIN_SEC)
    }
  }
  return [round3(left), round3(right)]
}

export function isVoiceExtractWindowValid(
  start: number,
  end: number,
  durationSec: number,
): boolean {
  if (!Number.isFinite(start) || !Number.isFinite(end) || !(start < end)) return false
  if (start < -0.05) return false
  const duration = Number.isFinite(durationSec) ? durationSec : 0
  if (duration > 0 && end > duration + 0.05) return false
  const span = end - start
  if (span < VOICE_EXTRACT_MIN_SEC - 1e-6) return false
  if (span > VOICE_EXTRACT_MAX_SEC + 1e-6) return false
  return true
}

export function formatVoiceExtractTime(sec: number): string {
  const value = Math.max(0, Number.isFinite(sec) ? sec : 0)
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`
}

export function voiceExtractSourceLabel(source: {
  episode_num: number
  seq: string
  line_preview: string
}): string {
  const preview = source.line_preview?.trim() || "开口对白"
  return `第${source.episode_num}集 · 镜${source.seq} · ${preview}`
}
