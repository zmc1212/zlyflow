/**
 * Source adaptation:
 * OpenCut classic apps/web/src/timeline/controllers/zoom-controller.ts
 * Upstream commit: cf5e79e919144200294fb9fed22a222592a0aeea
 */
import type { WheelEvent as ReactWheelEvent } from "react"

type ZoomUpdater = number | ((previous: number) => number)

export interface ZoomConfig {
  minZoom: number
  maxZoom: number
  getTracksScrollEl: () => HTMLDivElement | null
  getCurrentPlayheadSec: () => number
  setZoomLevel: (zoomLevel: number) => void
  setScrollLeft: (scrollLeft: number) => void
}

export interface ZoomConfigRef {
  readonly current: ZoomConfig
}

export class ZoomController {
  private readonly configRef: ZoomConfigRef
  private zoomLevelValue: number
  private previousZoom: number
  private preZoomScrollLeft = 0

  constructor(deps: { configRef: ZoomConfigRef; initialZoom: number }) {
    this.configRef = deps.configRef
    this.zoomLevelValue = deps.initialZoom
    this.previousZoom = deps.initialZoom
    this.setZoomLevel = this.setZoomLevel.bind(this)
    this.handleWheel = this.handleWheel.bind(this)
  }

  private get config(): ZoomConfig {
    return this.configRef.current
  }

  setZoomLevel(zoomLevelOrUpdater: ZoomUpdater): void {
    const scrollElement = this.config.getTracksScrollEl()
    if (scrollElement) this.preZoomScrollLeft = scrollElement.scrollLeft
    const raw = typeof zoomLevelOrUpdater === "function"
      ? zoomLevelOrUpdater(this.zoomLevelValue)
      : zoomLevelOrUpdater
    const next = Math.max(this.config.minZoom, Math.min(this.config.maxZoom, raw))
    if (next === this.zoomLevelValue) return
    this.zoomLevelValue = next
    this.config.setZoomLevel(next)
  }

  handleWheel(event: ReactWheelEvent): void {
    const isZoomGesture = event.ctrlKey || event.metaKey
    const isHorizontalScrollGesture = event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)
    if (isHorizontalScrollGesture || !isZoomGesture) return
    const normalizedDelta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY
    const cappedDelta = Math.sign(normalizedDelta) * Math.min(Math.abs(normalizedDelta), 30)
    this.setZoomLevel((previous) => previous * Math.exp(-cappedDelta / 300))
  }

  reconcileExternalZoom(zoomLevel: number): void {
    if (zoomLevel === this.zoomLevelValue) return
    this.preZoomScrollLeft = this.config.getTracksScrollEl()?.scrollLeft || 0
    this.zoomLevelValue = zoomLevel
  }

  applyZoomLayout(zoomLevel: number): void {
    const previousZoom = this.previousZoom
    if (previousZoom === zoomLevel) return
    const scrollElement = this.config.getTracksScrollEl()
    if (!scrollElement) {
      this.previousZoom = zoomLevel
      return
    }
    const playheadSec = this.config.getCurrentPlayheadSec()
    const viewportOffset = playheadSec * previousZoom - this.preZoomScrollLeft
    const unclamped = playheadSec * zoomLevel - viewportOffset
    const maxScrollLeft = Math.max(0, scrollElement.scrollWidth - scrollElement.clientWidth)
    const nextScrollLeft = Math.max(0, Math.min(maxScrollLeft, unclamped))
    scrollElement.scrollLeft = nextScrollLeft
    this.config.setScrollLeft(nextScrollLeft)
    this.previousZoom = zoomLevel
  }

  bindPreventBrowserZoom(): () => void {
    const preventZoom = (event: WheelEvent) => {
      const isZoomKeyPressed = event.ctrlKey || event.metaKey
      const container = this.config.getTracksScrollEl()
      if (isZoomKeyPressed && container?.contains(event.target as Node)) event.preventDefault()
    }
    document.addEventListener("wheel", preventZoom, { passive: false, capture: true })
    return () => document.removeEventListener("wheel", preventZoom, { capture: true })
  }
}
