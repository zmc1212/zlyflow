/**
 * Source adaptation:
 * OpenCut classic apps/web/src/timeline/controllers/resize-controller.ts
 * Upstream commit: cf5e79e919144200294fb9fed22a222592a0aeea
 */
import type { MouseEvent as ReactMouseEvent } from "react"
import type { RecipeShot } from "../recipe-model"
import {
  DIRECTOR_TIMELINE_FPS,
  directorSecondsToFrames,
  directorTimelineCommitDuration,
  directorTimelineFrameLayout,
  directorTimelineResizeDraftFrames,
  directorTimelineSnapFrame,
} from "../director-timeline-engine"

interface ResizeSession {
  kind: "active"
  shot: RecipeShot
  startX: number
  draftFrames: number
  snapFrame: number | null
  currentMouseX: number
}

type Session = { kind: "idle" } | ResizeSession

export interface ResizeView {
  kind: "idle" | "resizing"
  shotId?: string
  draftFrames?: number
  snapFrame?: number | null
  currentMouseX?: number
}

export interface ResizeConfig {
  pixelsPerSecond: number
  snappingEnabled: boolean
  shots: RecipeShot[]
  getCurrentPlayheadFrame: () => number
  isShiftHeld: () => boolean
  commitDuration: (shotId: string, durationSec: number) => void
}

export interface ResizeConfigRef {
  readonly current: ResizeConfig
}

export class ResizeController {
  private session: Session = { kind: "idle" }
  private readonly subscribers = new Set<() => void>()
  private readonly configRef: ResizeConfigRef

  constructor(deps: { configRef: ResizeConfigRef }) {
    this.configRef = deps.configRef
    this.onResizeStart = this.onResizeStart.bind(this)
    this.handleMouseMove = this.handleMouseMove.bind(this)
    this.handleMouseUp = this.handleMouseUp.bind(this)
  }

  private get config(): ResizeConfig {
    return this.configRef.current
  }

  get view(): ResizeView {
    if (this.session.kind === "idle") return { kind: "idle" }
    return {
      kind: "resizing",
      shotId: this.session.shot.id,
      draftFrames: this.session.draftFrames,
      snapFrame: this.session.snapFrame,
      currentMouseX: this.session.currentMouseX,
    }
  }

  get isResizing(): boolean {
    return this.session.kind === "active"
  }

  subscribe(fn: () => void): () => void {
    this.subscribers.add(fn)
    return () => this.subscribers.delete(fn)
  }

  destroy(): void {
    this.deactivate()
    this.subscribers.clear()
  }

  cancel(): void {
    this.finishSession()
  }

  onResizeStart({ event, shot }: { event: ReactMouseEvent; shot: RecipeShot }): void {
    event.preventDefault()
    event.stopPropagation()
    if (this.session.kind === "active") this.cancel()
    this.session = {
      kind: "active",
      shot,
      startX: event.clientX,
      draftFrames: directorSecondsToFrames(shot.durationSec),
      snapFrame: null,
      currentMouseX: event.clientX,
    }
    this.activate()
    this.notify()
  }

  private activate(): void {
    window.addEventListener("mousemove", this.handleMouseMove)
    window.addEventListener("mouseup", this.handleMouseUp)
  }

  private deactivate(): void {
    window.removeEventListener("mousemove", this.handleMouseMove)
    window.removeEventListener("mouseup", this.handleMouseUp)
  }

  private handleMouseMove(event: MouseEvent): void {
    const session = this.session
    if (session.kind !== "active") return
    const clip = directorTimelineFrameLayout(this.config.shots)
      .find((item) => item.shot.id === session.shot.id)
    if (!clip) return
    const rawDraft = directorTimelineResizeDraftFrames(
      session.shot,
      event.clientX - session.startX,
      this.config.pixelsPerSecond,
    )
    const rawEndFrame = clip.startFrame + rawDraft
    const snap = directorTimelineSnapFrame(rawEndFrame, this.config.shots, this.config.pixelsPerSecond, {
      enabled: this.config.snappingEnabled && !this.config.isShiftHeld(),
      excludedShotId: session.shot.id,
      extraFrames: [this.config.getCurrentPlayheadFrame()],
    })
    const snappedDuration = Math.max(
      directorSecondsToFrames(2),
      Math.min(directorSecondsToFrames(15), snap.frame - clip.startFrame),
    )
    session.draftFrames = snap.snapped ? snappedDuration : rawDraft
    session.snapFrame = snap.snapped ? snap.snapFrame : null
    session.currentMouseX = event.clientX
    this.notify()
  }

  private handleMouseUp(): void {
    if (this.session.kind !== "active") return
    const { shot, draftFrames } = this.session
    const originalFrames = directorSecondsToFrames(shot.durationSec, DIRECTOR_TIMELINE_FPS)
    if (draftFrames !== originalFrames) {
      this.config.commitDuration(shot.id, directorTimelineCommitDuration(draftFrames))
    }
    this.finishSession()
  }

  private finishSession(): void {
    this.session = { kind: "idle" }
    this.deactivate()
    this.notify()
  }

  private notify(): void {
    for (const fn of this.subscribers) fn()
  }
}
