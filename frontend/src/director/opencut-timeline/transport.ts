/**
 * Adapted from S07K/OpenCut's frame-based playback transport.
 * Upstream: packages/timeline-engine/src/time.ts and
 * apps/web/src/features/editor/PreviewPanel.tsx at e9c6cc06.
 */

export function clampTransportFrame(frame: number, durationFrames: number): number {
  return Math.min(Math.max(0, Math.round(frame)), Math.max(0, Math.round(durationFrames)))
}

export function stepTransportFrame(currentFrame: number, deltaFrames: number, durationFrames: number): number {
  return clampTransportFrame(currentFrame + Math.round(deltaFrames), durationFrames)
}

/** Pressing play at the finished timeline replays it from the beginning. */
export function playbackStartFrame(currentFrame: number, durationFrames: number): number {
  const duration = Math.max(0, Math.round(durationFrames))
  const current = clampTransportFrame(currentFrame, duration)
  return current >= Math.max(0, duration - 1) ? 0 : current
}

/** Formats an integer frame as the OpenCut-compatible `HH:MM:SS:FF` timecode. */
export function formatTransportTimecode(frame: number, fps: number): string {
  const safeFps = Math.max(1, Math.round(fps) || 1)
  const safeFrame = Math.max(0, Math.floor(frame))
  const totalSeconds = Math.floor(safeFrame / safeFps)
  const frames = safeFrame % safeFps
  const seconds = totalSeconds % 60
  const minutes = Math.floor(totalSeconds / 60) % 60
  const hours = Math.floor(totalSeconds / 3600)
  const pad = (value: number) => value.toString().padStart(2, "0")
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}:${pad(frames)}`
}
