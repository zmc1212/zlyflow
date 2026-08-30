import { Dropdown } from "antd"
import { Copy, Plus, Trash2 } from "lucide-react"
import {
  PointerEvent,
  UIEvent,
  WheelEvent,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react"
import type { RefObject } from "react"
import { directorStatusLabel } from "../status-labels"
import type { RecipeShot } from "../recipe-model"
import {
  directorFramesToSeconds,
  directorSecondsToFrames,
  directorTimelineClipIdsInFrameRange,
  directorTimelineFrameLayout,
  directorTimelineFrameToPixel,
  directorTimelinePixelToFrame,
  directorTimelineTotalFrames,
} from "../director-timeline-engine"
import { ElementInteractionController } from "../opencut-timeline/element-interaction-controller"
import { ResizeController } from "../opencut-timeline/resize-controller"
import { useCommittedRef } from "../opencut-timeline/use-committed-ref"
import { useEdgeAutoScroll } from "../opencut-timeline/use-edge-auto-scroll"
import { ZoomController } from "../opencut-timeline/zoom-controller"
import {
  recipeShotHasEndFrame,
  recipeShotHasFirstFrame,
  recipeShotSubjectLabels,
  recipeTrackCanvasWidth,
  recipeTrackLayout,
} from "../recipe-timeline"

interface TimelineTrackMainProps {
  shots: RecipeShot[]
  selectedShotId?: string
  checkedShotIds?: string[]
  pixelsPerSecond: number
  currentTimeSec: number
  snapEnabled?: boolean
  minPixelsPerSecond?: number
  playheadElementRef?: RefObject<HTMLDivElement | null>
  onSelectShot: (shot: RecipeShot, additive?: boolean) => void
  onSetCheckedShotIds?: (ids: string[]) => void
  onAddShot: () => void
  onDeleteShot: (shotId: string) => void
  onDuplicateShot: (shot: RecipeShot) => void
  onSeek?: (timeSec: number) => void
  onUpdateShotDuration?: (shotId: string, durationSec: number) => void
  onMoveShot?: (shotId: string, targetIndex: number) => void
  onZoomChange?: (pixelsPerSecond: number) => void
  onCanvasScroll?: (scrollLeft: number) => void
}

type BlankGesture =
  | { kind: "idle" }
  | { kind: "scrubbing"; pointerId: number }
  | { kind: "marquee"; pointerId: number; originFrame: number; currentFrame: number }
  | { kind: "panning"; pointerId: number; originClientX: number; originScrollLeft: number }

function statusCopy(shot: RecipeShot) {
  if (shot.status === "running") return `生成中 ${shot.progress || 0}%`
  return directorStatusLabel(shot.status)
}

function clipTone(shot: RecipeShot, selected: boolean, checked: boolean) {
  if (selected) return "director-clip-selected"
  if (shot.status === "running" || shot.status === "queued") return "director-clip-running"
  if (shot.status === "succeeded") return "director-clip-success"
  if (checked) return "director-clip-checked"
  return "director-clip-idle"
}

export default function TimelineTrackMain({
  shots,
  selectedShotId,
  checkedShotIds = [],
  pixelsPerSecond,
  currentTimeSec,
  snapEnabled = true,
  minPixelsPerSecond = 24,
  playheadElementRef,
  onSelectShot,
  onSetCheckedShotIds,
  onAddShot,
  onDeleteShot,
  onDuplicateShot,
  onSeek,
  onUpdateShotDuration,
  onMoveShot,
  onZoomChange,
  onCanvasScroll,
}: TimelineTrackMainProps) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const shiftHeldRef = useRef(false)
  const spaceHeldRef = useRef(false)
  const blankGestureRef = useRef<BlankGesture>({ kind: "idle" })
  const pendingScrubSecRef = useRef<number | null>(null)
  const scrubRafRef = useRef<number | null>(null)
  const [marquee, setMarquee] = useState<{ left: number; width: number } | null>(null)
  const [, rerenderControllers] = useReducer((count: number) => count + 1, 0)

  const elementConfigRef = useCommittedRef({
    shots,
    pixelsPerSecond,
    snappingEnabled: snapEnabled,
    getTracksScrollEl: () => canvasRef.current,
    getCurrentPlayheadFrame: () => directorSecondsToFrames(currentTimeSec),
    isShiftHeld: () => shiftHeldRef.current,
    selectShot: (shotId: string, additive: boolean) => {
      const shot = shots.find((item) => item.id === shotId)
      if (shot) onSelectShot(shot, additive)
    },
    commitMove: (shotId: string, targetIndex: number) => onMoveShot?.(shotId, targetIndex),
  })
  const resizeConfigRef = useCommittedRef({
    shots,
    pixelsPerSecond,
    snappingEnabled: snapEnabled,
    getCurrentPlayheadFrame: () => directorSecondsToFrames(currentTimeSec),
    isShiftHeld: () => shiftHeldRef.current,
    commitDuration: (shotId: string, durationSec: number) => onUpdateShotDuration?.(shotId, durationSec),
  })
  const zoomConfigRef = useCommittedRef({
    minZoom: minPixelsPerSecond,
    maxZoom: 120,
    getTracksScrollEl: () => canvasRef.current,
    getCurrentPlayheadSec: () => currentTimeSec,
    setZoomLevel: (zoomLevel: number) => onZoomChange?.(zoomLevel),
    setScrollLeft: (nextScrollLeft: number) => onCanvasScroll?.(nextScrollLeft),
  })
  const [elementController] = useState(() => new ElementInteractionController({ configRef: elementConfigRef }))
  const [resizeController] = useState(() => new ResizeController({ configRef: resizeConfigRef }))
  const [zoomController] = useState(() => new ZoomController({ configRef: zoomConfigRef, initialZoom: pixelsPerSecond }))

  useEffect(() => {
    const unsubscribeElement = elementController.subscribe(rerenderControllers)
    const unsubscribeResize = resizeController.subscribe(rerenderControllers)
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Shift") shiftHeldRef.current = true
      if (event.code === "Space" && !(event.target as HTMLElement)?.closest("input, textarea, [contenteditable=true]")) {
        spaceHeldRef.current = true
      }
    }
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === "Shift") shiftHeldRef.current = false
      if (event.code === "Space") spaceHeldRef.current = false
    }
    window.addEventListener("keydown", handleKeyDown)
    window.addEventListener("keyup", handleKeyUp)
    return () => {
      unsubscribeElement()
      unsubscribeResize()
      elementController.destroy()
      resizeController.destroy()
      if (scrubRafRef.current !== null) cancelAnimationFrame(scrubRafRef.current)
      window.removeEventListener("keydown", handleKeyDown)
      window.removeEventListener("keyup", handleKeyUp)
    }
  }, [elementController, resizeController])

  useEffect(() => {
    zoomController.reconcileExternalZoom(pixelsPerSecond)
    zoomController.applyZoomLayout(pixelsPerSecond)
  }, [pixelsPerSecond, zoomController])

  useEffect(() => zoomController.bindPreventBrowserZoom(), [zoomController])

  const dragView = elementController.view
  const resizeView = resizeController.view
  const durationDraftFrames = useMemo(() => {
    const map = new Map<string, number>()
    if (resizeView.kind === "resizing" && resizeView.shotId && resizeView.draftFrames) {
      map.set(resizeView.shotId, resizeView.draftFrames)
    }
    return map
  }, [resizeView.draftFrames, resizeView.kind, resizeView.shotId])
  const displayShots = useMemo(() => shots.map((shot) => {
    const draftFrames = durationDraftFrames.get(shot.id)
    return draftFrames ? { ...shot, durationSec: directorFramesToSeconds(draftFrames) } : shot
  }), [durationDraftFrames, shots])
  const layout = recipeTrackLayout(displayShots, pixelsPerSecond)
  const totalSec = layout.length ? layout[layout.length - 1].endSec : 0
  const canvasWidth = recipeTrackCanvasWidth(displayShots, pixelsPerSecond)

  const getGestureMouseClientX = useCallback(() => {
    if (dragView.kind === "dragging") return dragView.currentMouseX
    if (resizeView.kind === "resizing") return resizeView.currentMouseX || 0
    return 0
  }, [dragView, resizeView])
  useEdgeAutoScroll({
    isActive: dragView.kind === "dragging" || resizeView.kind === "resizing",
    getMouseClientX: getGestureMouseClientX,
    tracksScrollRef: canvasRef,
    contentWidth: canvasWidth,
  })

  const dropFrame = useMemo(() => {
    if (dragView.kind !== "dragging") return null
    const remaining = shots.filter((shot) => shot.id !== dragView.shotId)
    const remainingLayout = directorTimelineFrameLayout(remaining)
    return remainingLayout[dragView.targetIndex]?.startFrame
      ?? remainingLayout[remainingLayout.length - 1]?.endFrame
      ?? 0
  }, [dragView, shots])
  const snapFrame = resizeView.kind === "resizing"
    ? resizeView.snapFrame
    : dragView.kind === "dragging"
      ? dragView.snapFrame
      : null

  function frameFromClientX(clientX: number): number {
    const canvas = canvasRef.current
    if (!canvas) return 0
    const rect = canvas.getBoundingClientRect()
    return directorTimelinePixelToFrame(
      clientX - rect.left + canvas.scrollLeft,
      pixelsPerSecond,
      directorTimelineTotalFrames(displayShots),
    )
  }

  function queueScrub(frame: number) {
    pendingScrubSecRef.current = directorFramesToSeconds(frame)
    if (scrubRafRef.current !== null) return
    scrubRafRef.current = requestAnimationFrame(() => {
      scrubRafRef.current = null
      if (pendingScrubSecRef.current !== null) onSeek?.(pendingScrubSecRef.current)
    })
  }

  function handleBlankPointerDown(event: PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest(".director-clip, button, .director-clip-resize")) return
    const canvas = canvasRef.current
    if (!canvas) return
    if (event.button === 1 || (event.button === 0 && spaceHeldRef.current)) {
      event.preventDefault()
      blankGestureRef.current = {
        kind: "panning",
        pointerId: event.pointerId,
        originClientX: event.clientX,
        originScrollLeft: canvas.scrollLeft,
      }
    } else if (event.button === 0 && event.shiftKey) {
      const frame = frameFromClientX(event.clientX)
      blankGestureRef.current = { kind: "marquee", pointerId: event.pointerId, originFrame: frame, currentFrame: frame }
      const left = directorTimelineFrameToPixel(frame, pixelsPerSecond)
      setMarquee({ left, width: 0 })
    } else if (event.button === 0) {
      const frame = frameFromClientX(event.clientX)
      blankGestureRef.current = { kind: "scrubbing", pointerId: event.pointerId }
      queueScrub(frame)
    } else {
      return
    }
    canvas.setPointerCapture(event.pointerId)
  }

  function handleBlankPointerMove(event: PointerEvent<HTMLDivElement>) {
    const canvas = canvasRef.current
    const gesture = blankGestureRef.current
    if (!canvas || gesture.kind === "idle" || gesture.pointerId !== event.pointerId) return
    if (gesture.kind === "panning") {
      canvas.scrollLeft = Math.max(0, gesture.originScrollLeft - (event.clientX - gesture.originClientX))
      return
    }
    const frame = frameFromClientX(event.clientX)
    if (gesture.kind === "scrubbing") {
      queueScrub(frame)
      return
    }
    gesture.currentFrame = frame
    const originPx = directorTimelineFrameToPixel(gesture.originFrame, pixelsPerSecond)
    const currentPx = directorTimelineFrameToPixel(frame, pixelsPerSecond)
    setMarquee({ left: Math.min(originPx, currentPx), width: Math.abs(currentPx - originPx) })
  }

  function handleBlankPointerUp(event: PointerEvent<HTMLDivElement>) {
    const canvas = canvasRef.current
    const gesture = blankGestureRef.current
    if (gesture.kind === "idle" || gesture.pointerId !== event.pointerId) return
    if (gesture.kind === "marquee" && Math.abs(gesture.currentFrame - gesture.originFrame) >= 1) {
      onSetCheckedShotIds?.(directorTimelineClipIdsInFrameRange(
        displayShots,
        gesture.originFrame,
        gesture.currentFrame,
      ))
    }
    if (canvas?.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    blankGestureRef.current = { kind: "idle" }
    setMarquee(null)
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    const canvas = canvasRef.current
    if (!canvas) return
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault()
      zoomController.handleWheel(event)
      return
    }
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      event.preventDefault()
      canvas.scrollLeft += event.deltaX || event.deltaY
    }
  }

  return (
    <div className="director-tracks">
      <div className="director-track-labels">
        <span>视频镜头</span>
        <span>角色 / 场景</span>
        <span>首尾帧</span>
        <span>生成状态</span>
      </div>
      <div
        ref={canvasRef}
        className={`director-track-canvas${blankGestureRef.current.kind === "panning" ? " is-panning" : ""}`}
        tabIndex={0}
        aria-label="导演剪辑时间轴"
        onPointerDown={handleBlankPointerDown}
        onPointerMove={handleBlankPointerMove}
        onPointerUp={handleBlankPointerUp}
        onPointerCancel={handleBlankPointerUp}
        onWheel={handleWheel}
        onScroll={(event: UIEvent<HTMLDivElement>) => onCanvasScroll?.(event.currentTarget.scrollLeft)}
      >
        <div className="director-track-rows" style={{ width: `${canvasWidth}px` }}>
          <div ref={playheadElementRef} className="director-playhead director-track-playhead" style={{ transform: `translate3d(${currentTimeSec * pixelsPerSecond}px, 0, 0)` }} />
          {marquee ? <div className="director-track-marquee" style={{ left: `${marquee.left}px`, width: `${marquee.width}px` }} /> : null}
          {dropFrame !== null ? (
            <div className="director-drop-indicator" style={{ transform: `translate3d(${directorTimelineFrameToPixel(dropFrame, pixelsPerSecond)}px, 0, 0)` }} />
          ) : null}
          {snapFrame !== null && snapFrame !== undefined ? (
            <div className="director-snap-indicator" style={{ transform: `translate3d(${directorTimelineFrameToPixel(snapFrame, pixelsPerSecond)}px, 0, 0)` }} />
          ) : null}
          <div className="director-track-row director-track-row-video">
            {layout.map(({ shot, left, width }) => {
              const selected = selectedShotId === shot.id
              const checked = checkedShotIds.includes(shot.id)
              const dragging = dragView.kind === "dragging" && dragView.shotId === shot.id
              const dragDelta = dragging ? dragView.currentMouseX - dragView.startMouseX : 0
              const resizing = resizeView.kind === "resizing" && resizeView.shotId === shot.id
              return (
                <Dropdown
                  key={shot.id}
                  trigger={["contextMenu"]}
                  menu={{
                    items: [
                      { key: "dup", label: "复制镜头", icon: <Copy size={13} />, onClick: () => onDuplicateShot(shot) },
                      { key: "del", label: "删除镜头", icon: <Trash2 size={13} />, danger: true, disabled: shots.length <= 1, onClick: () => onDeleteShot(shot.id) },
                    ],
                  }}
                >
                  <div
                    className={`director-clip ${clipTone(shot, selected, checked)}${dragging ? " is-dragging" : ""}${resizing ? " is-resizing" : ""}`}
                    style={{ left: `${left}px`, width: `${width}px`, transform: dragging ? `translate3d(${dragDelta}px, 0, 0)` : undefined }}
                  >
                    <button
                      type="button"
                      className="director-clip-body"
                      onMouseDown={(event) => elementController.onElementMouseDown({ event, shot })}
                      onClick={(event) => elementController.onElementClick({ event, shot })}
                    >
                      镜头 {String(shot.shotNumber).padStart(2, "0")} · {shot.title}
                    </button>
                    {onUpdateShotDuration ? (
                      <button
                        type="button"
                        className="director-clip-resize"
                        onMouseDown={(event) => resizeController.onResizeStart({ event, shot })}
                        onClick={(event) => event.stopPropagation()}
                        aria-label={`调整镜头 ${shot.shotNumber} 时长`}
                      />
                    ) : null}
                    {resizing && resizeView.draftFrames ? (
                      <span className="director-resize-readout">{directorFramesToSeconds(resizeView.draftFrames).toFixed(2)}s</span>
                    ) : null}
                  </div>
                </Dropdown>
              )
            })}
            <button type="button" className="director-add-next" style={{ left: `${totalSec * pixelsPerSecond + 8}px`, width: 72 }} onClick={onAddShot}>
              <Plus size={12} />
            </button>
          </div>
          <div className="director-track-row director-track-row-subjects">
            {layout.map(({ shot, left, width }) => {
              const refs = recipeShotSubjectLabels(shot)
              if (!refs.length) return null
              return <div key={shot.id} className="director-subject-span" style={{ left: `${left + 16}px`, width: `${Math.max(48, width - 36)}px` }}>{refs.join(" + ")}</div>
            })}
          </div>
          <div className="director-track-row director-track-row-frames">
            {layout.map(({ shot, left, width }) => (
              <div key={shot.id} className="director-frame-marks" style={{ left: `${left}px`, width: `${width}px` }}>
                <span className={`director-diamond ${recipeShotHasFirstFrame(shot) ? "is-set" : ""}`} />
                <span className={`director-diamond ${recipeShotHasEndFrame(shot) ? "is-set" : ""}`} />
              </div>
            ))}
          </div>
          <div className="director-track-row director-track-row-status">
            {layout.map(({ shot, left, width }) => {
              const running = shot.status === "running" || shot.status === "queued"
              const done = shot.status === "succeeded"
              return (
                <div key={shot.id} className={`director-status-bar ${running ? "is-running" : ""} ${done ? "is-success" : ""}`} style={{ left: `${left}px`, width: `${width}px` }}>
                  {running ? <i style={{ width: `${Math.max(8, shot.progress || 8)}%` }} /> : null}
                  <b>{statusCopy(shot)}</b>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
