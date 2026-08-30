/**
 * Source adaptation:
 * OpenCut classic apps/web/src/timeline/controllers/playhead-controller.ts
 * Upstream commit: cf5e79e919144200294fb9fed22a222592a0aeea
 */
import type { MouseEvent as ReactMouseEvent } from "react"
import type { RecipeShot } from "../recipe-model"
import {
  DIRECTOR_TIMELINE_FPS,
  directorTimelineFrameToPixel,
  directorTimelinePixelToFrame,
  directorTimelineSnapFrame,
  directorTimelineTotalFrames,
} from "../director-timeline-engine"

interface ScrubSession {
  kind: "scrubbing"
  didStartFromRuler: boolean
  hasMoved: boolean
  currentFrame: number | null
}

type Session = { kind: "idle" } | ScrubSession

export interface PlayheadConfig {
  shots: RecipeShot[]
  pixelsPerSecond: number
  snapEnabled: boolean
  getRulerEl: () => HTMLDivElement | null
  getRulerScrollLeft: () => number
  getPlayheadEl: () => HTMLDivElement | null
  getExtraSnapFrames: () => number[]
  isShiftHeld: () => boolean
  previewSeek: (frame: number) => void
  commitSeek: (frame: number) => void
  setScrubbing: (scrubbing: boolean) => void
}

export interface PlayheadConfigRef {
  readonly current: PlayheadConfig
}

function pixelToFrame({
  clientX,
  rulerEl,
  scrollLeft,
  pixelsPerSecond,
  totalFrames,
}: {
  clientX: number
  rulerEl: HTMLDivElement
  scrollLeft: number
  pixelsPerSecond: number
  totalFrames: number
}): number {
  const rect = rulerEl.getBoundingClientRect()
  return directorTimelinePixelToFrame(
    clientX - rect.left + scrollLeft,
    pixelsPerSecond,
    totalFrames,
  )
}

export class PlayheadController {
  private session: Session = { kind: "idle" }
  private readonly configRef: PlayheadConfigRef
  private lastMouseClientX = 0

  constructor(deps: { configRef: PlayheadConfigRef }) {
    this.configRef = deps.configRef
    this.onPlayheadMouseDown = this.onPlayheadMouseDown.bind(this)
    this.onRulerMouseDown = this.onRulerMouseDown.bind(this)
    this.handleMouseMove = this.handleMouseMove.bind(this)
    this.handleMouseUp = this.handleMouseUp.bind(this)
  }

  private get config(): PlayheadConfig {
    return this.configRef.current
  }

  get isActive(): boolean {
    return this.session.kind !== "idle"
  }

  getLastMouseClientX(): number {
    return this.lastMouseClientX
  }

  destroy(): void {
    this.deactivate()
    this.session = { kind: "idle" }
  }

  onPlayheadMouseDown(event: ReactMouseEvent): void {
    event.preventDefault()
    event.stopPropagation()
    this.beginSession(false)
    this.scrub({ event, edgeSnappingEnabled: true })
    this.activate()
  }

  onRulerMouseDown(event: ReactMouseEvent): void {
    if (event.button !== 0) return
    if (this.config.getPlayheadEl()?.contains(event.target as Node)) return
    event.preventDefault()
    this.beginSession(true)
    this.scrub({ event, edgeSnappingEnabled: false })
    this.activate()
  }

  updatePlayheadLeft(frame: number): void {
    const playhead = this.config.getPlayheadEl()
    if (!playhead) return
    const contentPixel = directorTimelineFrameToPixel(frame, this.config.pixelsPerSecond)
    playhead.style.transform = `translate3d(${contentPixel - this.config.getRulerScrollLeft()}px, 0, 0)`
  }

  private beginSession(didStartFromRuler: boolean): void {
    this.session = {
      kind: "scrubbing",
      didStartFromRuler,
      hasMoved: false,
      currentFrame: null,
    }
    this.config.setScrubbing(true)
  }

  private activate(): void {
    window.addEventListener("mousemove", this.handleMouseMove)
    window.addEventListener("mouseup", this.handleMouseUp)
  }

  private deactivate(): void {
    window.removeEventListener("mousemove", this.handleMouseMove)
    window.removeEventListener("mouseup", this.handleMouseUp)
  }

  private scrub({
    event,
    edgeSnappingEnabled,
  }: {
    event: MouseEvent | ReactMouseEvent
    edgeSnappingEnabled: boolean
  }): void {
    const ruler = this.config.getRulerEl()
    if (!ruler) return
    const totalFrames = directorTimelineTotalFrames(this.config.shots)
    const rawFrame = pixelToFrame({
      clientX: event.clientX,
      rulerEl: ruler,
      scrollLeft: this.config.getRulerScrollLeft(),
      pixelsPerSecond: this.config.pixelsPerSecond,
      totalFrames,
    })
    const frame = edgeSnappingEnabled && !this.config.isShiftHeld()
      ? directorTimelineSnapFrame(rawFrame, this.config.shots, this.config.pixelsPerSecond, {
        enabled: this.config.snapEnabled,
        extraFrames: this.config.getExtraSnapFrames(),
        fps: DIRECTOR_TIMELINE_FPS,
      }).frame
      : rawFrame
    if (this.session.kind === "scrubbing") this.session.currentFrame = frame
    this.config.previewSeek(frame)
    this.updatePlayheadLeft(frame)
    this.lastMouseClientX = event.clientX
  }

  private handleMouseMove(event: MouseEvent): void {
    if (this.session.kind !== "scrubbing") return
    this.scrub({ event, edgeSnappingEnabled: true })
    if (this.session.didStartFromRuler) this.session.hasMoved = true
  }

  private handleMouseUp(event: MouseEvent): void {
    if (this.session.kind !== "scrubbing") return
    const session = this.session
    if (session.didStartFromRuler && !session.hasMoved) {
      this.scrub({ event, edgeSnappingEnabled: false })
    }
    if (session.currentFrame !== null) this.config.commitSeek(session.currentFrame)
    this.config.setScrubbing(false)
    this.session = { kind: "idle" }
    this.deactivate()
  }
}
