/**
 * Source adaptation:
 * OpenCut classic apps/web/src/timeline/controllers/element-interaction-controller.ts
 * Upstream commit: cf5e79e919144200294fb9fed22a222592a0aeea
 *
 * OpenCut supports groups and arbitrary tracks. Director Recipe has one
 * contiguous main track, so the upstream session/threshold/commit controller
 * is retained while its drop resolver maps to a RecipeShot insertion index.
 */
import type { MouseEvent as ReactMouseEvent } from "react"
import type { RecipeShot } from "../recipe-model"
import {
  DIRECTOR_TIMELINE_DRAG_THRESHOLD_PX,
  directorTimelineFrameLayout,
  directorTimelineFrameToPixel,
  directorTimelineMoveTargetIndex,
  directorTimelinePixelToFrame,
  directorTimelineSnapFrame,
  directorTimelineTotalFrames,
} from "../director-timeline-engine"

const MOUSE_BUTTON_RIGHT = 2

export interface ElementInteractionConfig {
  shots: RecipeShot[]
  pixelsPerSecond: number
  snappingEnabled: boolean
  getTracksScrollEl: () => HTMLDivElement | null
  getCurrentPlayheadFrame: () => number
  isShiftHeld: () => boolean
  selectShot: (shotId: string, additive: boolean) => void
  commitMove: (shotId: string, targetIndex: number) => void
}

export interface ElementInteractionConfigRef {
  readonly current: ElementInteractionConfig
}

interface MousedownSnapshot {
  originX: number
  originY: number
  shotId: string
  sourceIndex: number
  clickOffsetPx: number
}

interface DragProgress {
  currentMouseX: number
  currentMouseY: number
  targetIndex: number
  snapFrame: number | null
}

type Session =
  | { kind: "idle" }
  | { kind: "pending"; mousedown: MousedownSnapshot }
  | { kind: "dragging"; mousedown: MousedownSnapshot; drag: DragProgress }

export type ElementDragView =
  | { kind: "idle" }
  | {
    kind: "dragging"
    shotId: string
    sourceIndex: number
    targetIndex: number
    startMouseX: number
    currentMouseX: number
    currentMouseY: number
    snapFrame: number | null
  }

function movedPastDragThreshold(currentX: number, currentY: number, originX: number, originY: number): boolean {
  return Math.abs(currentX - originX) > DIRECTOR_TIMELINE_DRAG_THRESHOLD_PX
    || Math.abs(currentY - originY) > DIRECTOR_TIMELINE_DRAG_THRESHOLD_PX
}

export class ElementInteractionController {
  private session: Session = { kind: "idle" }
  private lastGestureWasDrag = false
  private readonly subscribers = new Set<() => void>()
  private readonly configRef: ElementInteractionConfigRef

  constructor(args: { configRef: ElementInteractionConfigRef }) {
    this.configRef = args.configRef
  }

  private get config(): ElementInteractionConfig {
    return this.configRef.current
  }

  get view(): ElementDragView {
    if (this.session.kind !== "dragging") return { kind: "idle" }
    return {
      kind: "dragging",
      shotId: this.session.mousedown.shotId,
      sourceIndex: this.session.mousedown.sourceIndex,
      targetIndex: this.session.drag.targetIndex,
      startMouseX: this.session.mousedown.originX,
      currentMouseX: this.session.drag.currentMouseX,
      currentMouseY: this.session.drag.currentMouseY,
      snapFrame: this.session.drag.snapFrame,
    }
  }

  get isActive(): boolean {
    return this.session.kind !== "idle"
  }

  subscribe(fn: () => void): () => void {
    this.subscribers.add(fn)
    return () => this.subscribers.delete(fn)
  }

  cancel = (): void => {
    this.lastGestureWasDrag = false
    this.finishSession()
  }

  destroy(): void {
    this.cancel()
    this.subscribers.clear()
  }

  onElementMouseDown = ({
    event,
    shot,
  }: {
    event: ReactMouseEvent
    shot: RecipeShot
  }): void => {
    if (event.button === MOUSE_BUTTON_RIGHT) return
    event.stopPropagation()
    this.lastGestureWasDrag = false
    const sourceIndex = this.config.shots.findIndex((item) => item.id === shot.id)
    if (sourceIndex < 0) return
    const rect = event.currentTarget.getBoundingClientRect()
    if (event.metaKey || event.ctrlKey || event.shiftKey) {
      this.config.selectShot(shot.id, true)
    }
    this.session = {
      kind: "pending",
      mousedown: {
        originX: event.clientX,
        originY: event.clientY,
        shotId: shot.id,
        sourceIndex,
        clickOffsetPx: event.clientX - rect.left,
      },
    }
    this.activate()
    this.notify()
  }

  onElementClick = ({ event, shot }: { event: ReactMouseEvent; shot: RecipeShot }): void => {
    event.stopPropagation()
    if (this.lastGestureWasDrag) {
      this.lastGestureWasDrag = false
      return
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey) return
    this.config.selectShot(shot.id, false)
  }

  private activate(): void {
    document.addEventListener("mousemove", this.handleMouseMove)
    document.addEventListener("mouseup", this.handleMouseUp)
  }

  private deactivate(): void {
    document.removeEventListener("mousemove", this.handleMouseMove)
    document.removeEventListener("mouseup", this.handleMouseUp)
  }

  private handleMouseMove = ({ clientX, clientY }: MouseEvent): void => {
    const scrollContainer = this.config.getTracksScrollEl()
    if (!scrollContainer) return
    if (this.session.kind === "pending") {
      if (!movedPastDragThreshold(
        clientX,
        clientY,
        this.session.mousedown.originX,
        this.session.mousedown.originY,
      )) return
      this.beginDragFromPending(clientX, clientY, scrollContainer)
      return
    }
    if (this.session.kind === "dragging") this.updateActiveDrag(clientX, clientY, scrollContainer)
  }

  private frameFromMouse(
    clientX: number,
    scrollContainer: HTMLDivElement,
    mousedown: MousedownSnapshot,
  ): { frame: number; snapFrame: number | null } {
    const rect = scrollContainer.getBoundingClientRect()
    const contentPixel = clientX - rect.left + scrollContainer.scrollLeft - mousedown.clickOffsetPx
    const totalFrames = directorTimelineTotalFrames(this.config.shots)
    const rawFrame = directorTimelinePixelToFrame(
      contentPixel,
      this.config.pixelsPerSecond,
      totalFrames,
    )
    const snap = directorTimelineSnapFrame(rawFrame, this.config.shots, this.config.pixelsPerSecond, {
      enabled: this.config.snappingEnabled && !this.config.isShiftHeld(),
      excludedShotId: mousedown.shotId,
      extraFrames: [this.config.getCurrentPlayheadFrame()],
    })
    return { frame: snap.frame, snapFrame: snap.snapFrame }
  }

  private beginDragFromPending(clientX: number, clientY: number, scrollContainer: HTMLDivElement): void {
    if (this.session.kind !== "pending") return
    const mousedown = this.session.mousedown
    const { frame, snapFrame } = this.frameFromMouse(clientX, scrollContainer, mousedown)
    this.session = {
      kind: "dragging",
      mousedown,
      drag: {
        currentMouseX: clientX,
        currentMouseY: clientY,
        targetIndex: directorTimelineMoveTargetIndex(this.config.shots, mousedown.shotId, frame),
        snapFrame,
      },
    }
    this.lastGestureWasDrag = true
    this.config.selectShot(mousedown.shotId, false)
    this.notify()
  }

  private updateActiveDrag(clientX: number, clientY: number, scrollContainer: HTMLDivElement): void {
    if (this.session.kind !== "dragging") return
    const { frame, snapFrame } = this.frameFromMouse(clientX, scrollContainer, this.session.mousedown)
    this.session.drag.currentMouseX = clientX
    this.session.drag.currentMouseY = clientY
    this.session.drag.targetIndex = directorTimelineMoveTargetIndex(
      this.config.shots,
      this.session.mousedown.shotId,
      frame,
    )
    this.session.drag.snapFrame = snapFrame
    this.notify()
  }

  private handleMouseUp = ({ clientX, clientY }: MouseEvent): void => {
    if (this.session.kind === "pending") {
      this.finishSession()
      return
    }
    if (this.session.kind !== "dragging") return
    const { mousedown, drag } = this.session
    if (!movedPastDragThreshold(clientX, clientY, mousedown.originX, mousedown.originY)) {
      this.lastGestureWasDrag = false
      this.finishSession()
      return
    }
    if (drag.targetIndex !== mousedown.sourceIndex) {
      this.config.commitMove(mousedown.shotId, drag.targetIndex)
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

export function elementDragPreviewLeftPx(
  view: ElementDragView,
  shots: RecipeShot[],
  pixelsPerSecond: number,
): number | null {
  if (view.kind !== "dragging") return null
  const preview = directorTimelineFrameLayout(shots)
    .find((clip) => clip.shot.id === view.shotId)
  return preview ? directorTimelineFrameToPixel(preview.startFrame, pixelsPerSecond) : null
}
