const H3_MIN_DURATION_SEC = 2
const H3_MAX_DURATION_SEC = 15
const DEFAULT_BEAT_DURATION_SEC = 8

export function beatDurationSec(
  raw: string | number | null | undefined,
  fallback: number = DEFAULT_BEAT_DURATION_SEC,
): number {
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) return fallback
  return Math.max(H3_MIN_DURATION_SEC, Math.min(H3_MAX_DURATION_SEC, Math.round(value)))
}

export function formatBeatDurationLabel(
  raw: string | number | null | undefined,
  fallback: number = DEFAULT_BEAT_DURATION_SEC,
): string {
  return `${beatDurationSec(raw, fallback)}s`
}

export function formatBeatDurationZh(
  raw: string | number | null | undefined,
  fallback: number = DEFAULT_BEAT_DURATION_SEC,
): string {
  return `${beatDurationSec(raw, fallback)}秒`
}

export function sumBeatDurationSec(
  beats: Array<{ video_duration?: string | number | null }>,
  fallback: number = DEFAULT_BEAT_DURATION_SEC,
): number {
  return beats.reduce((total, beat) => total + beatDurationSec(beat.video_duration, fallback), 0)
}
