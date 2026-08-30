import type { RecipeShot } from "./recipe-model"

/**
 * Headless timeline math inspired by OpenCut's engine/UI split.
 *
 * The director timeline is deliberately smaller than a general NLE: shots are
 * contiguous, live on one main track, and H3 accepts integer durations from
 * 2–15 seconds. Interaction previews still use frame precision so dragging is
 * continuous; the product constraint is applied only when a gesture commits.
 */
export const DIRECTOR_TIMELINE_FPS = 24
export const DIRECTOR_TIMELINE_DRAG_THRESHOLD_PX = 5
export const DIRECTOR_TIMELINE_SNAP_THRESHOLD_PX = 8
export const DIRECTOR_TIMELINE_MIN_DURATION_SEC = 2
export const DIRECTOR_TIMELINE_MAX_DURATION_SEC = 15

export interface DirectorTimelineFrameClip {
  shot: RecipeShot
  index: number
  startFrame: number
  durationFrames: number
  endFrame: number
}

export interface DirectorTimelineSnapResult {
  frame: number
  snapped: boolean
  snapFrame: number | null
}

export function directorSecondsToFrames(seconds: number, fps: number = DIRECTOR_TIMELINE_FPS): number {
  const safeFps = Math.max(1, Math.round(Number(fps) || DIRECTOR_TIMELINE_FPS))
  return Math.max(0, Math.round((Number(seconds) || 0) * safeFps))
}

export function directorFramesToSeconds(frames: number, fps: number = DIRECTOR_TIMELINE_FPS): number {
  const safeFps = Math.max(1, Math.round(Number(fps) || DIRECTOR_TIMELINE_FPS))
  return Math.max(0, Number(frames) || 0) / safeFps
}

export function directorTimelineFrameLayout(
  shots: RecipeShot[],
  durationDraftFrames: ReadonlyMap<string, number> = new Map(),
  fps: number = DIRECTOR_TIMELINE_FPS,
): DirectorTimelineFrameClip[] {
  let startFrame = 0
  return shots.map((shot, index) => {
    const durationFrames = Math.max(
      1,
      Math.round(durationDraftFrames.get(shot.id) ?? directorSecondsToFrames(shot.durationSec, fps)),
    )
    const item = {
      shot,
      index,
      startFrame,
      durationFrames,
      endFrame: startFrame + durationFrames,
    }
    startFrame = item.endFrame
    return item
  })
}

export function directorTimelineTotalFrames(
  shots: RecipeShot[],
  durationDraftFrames?: ReadonlyMap<string, number>,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  const layout = directorTimelineFrameLayout(shots, durationDraftFrames, fps)
  return layout[layout.length - 1]?.endFrame || 0
}

export function directorTimelinePixelToFrame(
  contentPixel: number,
  pixelsPerSecond: number,
  totalFrames: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  const pps = Math.max(1, Number(pixelsPerSecond) || 0)
  const frame = Math.round((Math.max(0, contentPixel) / pps) * fps)
  return Math.min(Math.max(0, totalFrames), frame)
}

export function directorTimelineFrameToPixel(
  frame: number,
  pixelsPerSecond: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  return directorFramesToSeconds(frame, fps) * Math.max(1, Number(pixelsPerSecond) || 0)
}

export function directorTimelineSnapFrame(
  targetFrame: number,
  shots: RecipeShot[],
  pixelsPerSecond: number,
  options?: {
    enabled?: boolean
    excludedShotId?: string
    extraFrames?: number[]
    fps?: number
  },
): DirectorTimelineSnapResult {
  const fps = options?.fps || DIRECTOR_TIMELINE_FPS
  const frame = Math.max(0, Math.round(targetFrame))
  if (options?.enabled === false) return { frame, snapped: false, snapFrame: null }

  const thresholdFrames = Math.max(
    1,
    Math.round((DIRECTOR_TIMELINE_SNAP_THRESHOLD_PX / Math.max(1, pixelsPerSecond)) * fps),
  )
  const snapFrames = new Set<number>([0, ...(options?.extraFrames || [])])
  for (const clip of directorTimelineFrameLayout(shots, new Map(), fps)) {
    if (clip.shot.id === options?.excludedShotId) continue
    snapFrames.add(clip.startFrame)
    snapFrames.add(clip.endFrame)
  }

  let nearest: number | null = null
  let nearestDistance = Number.POSITIVE_INFINITY
  for (const snapFrame of snapFrames) {
    const distance = Math.abs(frame - snapFrame)
    if (distance < nearestDistance) {
      nearest = snapFrame
      nearestDistance = distance
    }
  }
  return nearest !== null && nearestDistance <= thresholdFrames
    ? { frame: nearest, snapped: true, snapFrame: nearest }
    : { frame, snapped: false, snapFrame: null }
}

export function directorTimelineResizeDraftFrames(
  shot: RecipeShot,
  deltaPixels: number,
  pixelsPerSecond: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  const startFrames = directorSecondsToFrames(shot.durationSec, fps)
  const deltaFrames = Math.round((deltaPixels / Math.max(1, pixelsPerSecond)) * fps)
  return Math.min(
    directorSecondsToFrames(DIRECTOR_TIMELINE_MAX_DURATION_SEC, fps),
    Math.max(directorSecondsToFrames(DIRECTOR_TIMELINE_MIN_DURATION_SEC, fps), startFrames + deltaFrames),
  )
}

export function directorTimelineCommitDuration(
  draftFrames: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  return Math.min(
    DIRECTOR_TIMELINE_MAX_DURATION_SEC,
    Math.max(DIRECTOR_TIMELINE_MIN_DURATION_SEC, Math.round(directorFramesToSeconds(draftFrames, fps))),
  )
}

export function directorTimelineReorderShots(shots: RecipeShot[], shotId: string, targetIndex: number): RecipeShot[] {
  const sourceIndex = shots.findIndex((shot) => shot.id === shotId)
  if (sourceIndex < 0) return shots
  const next = [...shots]
  const [moving] = next.splice(sourceIndex, 1)
  const insertionIndex = Math.min(next.length, Math.max(0, Math.round(targetIndex)))
  next.splice(insertionIndex, 0, moving)
  return next
}

export function directorTimelineMoveTargetIndex(
  shots: RecipeShot[],
  shotId: string,
  pointerFrame: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): number {
  const remaining = shots.filter((shot) => shot.id !== shotId)
  const layout = directorTimelineFrameLayout(remaining, new Map(), fps)
  const target = layout.findIndex((clip) => pointerFrame < clip.startFrame + clip.durationFrames / 2)
  return target < 0 ? remaining.length : target
}

export function directorTimelineClipIdsInFrameRange(
  shots: RecipeShot[],
  startFrame: number,
  endFrame: number,
  fps: number = DIRECTOR_TIMELINE_FPS,
): string[] {
  const low = Math.min(startFrame, endFrame)
  const high = Math.max(startFrame, endFrame)
  return directorTimelineFrameLayout(shots, new Map(), fps)
    .filter((clip) => clip.endFrame > low && clip.startFrame < high)
    .map((clip) => clip.shot.id)
}
