import { Dropdown } from "antd"
import { Copy, Plus, Trash2 } from "lucide-react"
import { PointerEvent, UIEvent, useRef, useState } from "react"
import { snapH3DurationSec } from "../prompt-compiler"
import { directorStatusLabel } from "../status-labels"
import {
  RecipeShot,
  recipeShotHasEndFrame,
  recipeShotHasFirstFrame,
  recipeShotSubjectLabels,
  recipeTrackCanvasWidth,
  recipeTrackClipIdsInRange,
  recipeTrackLayout,
} from "../types"

interface TimelineTrackMainProps {
  shots: RecipeShot[]
  selectedShotId?: string
  checkedShotIds?: string[]
  pixelsPerSecond: number
  currentTimeSec: number
  onSelectShot: (shot: RecipeShot, additive?: boolean) => void
  onSetCheckedShotIds?: (ids: string[]) => void
  onAddShot: () => void
  onDeleteShot: (shotId: string) => void
  onDuplicateShot: (shot: RecipeShot) => void
  onSeek?: (timeSec: number) => void
  onUpdateShotDuration?: (shotId: string, durationSec: number) => void
  onCanvasScroll?: (scrollLeft: number) => void
}

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
  onSelectShot,
  onSetCheckedShotIds,
  onAddShot,
  onDeleteShot,
  onDuplicateShot,
  onSeek,
  onUpdateShotDuration,
  onCanvasScroll,
}: TimelineTrackMainProps) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)
  const marqueeOriginRef = useRef(0)
  const [marquee, setMarquee] = useState<{ left: number; width: number } | null>(null)
  const layout = recipeTrackLayout(shots, pixelsPerSecond)
  const totalSec = layout.length ? layout[layout.length - 1].endSec : 0
  const canvasWidth = recipeTrackCanvasWidth(shots, pixelsPerSecond)

  function timeFromClientX(clientX: number) {
    const canvas = canvasRef.current
    if (!canvas) return 0
    const rect = canvas.getBoundingClientRect()
    return Math.max(0, (clientX - rect.left + canvas.scrollLeft) / Math.max(1, pixelsPerSecond))
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    if ((event.target as HTMLElement).closest("button, .director-clip-resize")) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const origin = event.clientX - rect.left + canvas.scrollLeft
    draggingRef.current = true
    marqueeOriginRef.current = origin
    canvas.setPointerCapture(event.pointerId)
    setMarquee({ left: origin, width: 0 })
    onSeek?.(timeFromClientX(event.clientX))
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!draggingRef.current || !canvasRef.current) return
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    const current = event.clientX - rect.left + canvas.scrollLeft
    const originX = marqueeOriginRef.current
    setMarquee({ left: Math.min(originX, current), width: Math.abs(current - originX) })
    onSeek?.(timeFromClientX(event.clientX))
  }

  function handlePointerUp() {
    if (marquee && marquee.width >= 6) {
      onSetCheckedShotIds?.(recipeTrackClipIdsInRange(layout, marquee.left, marquee.left + marquee.width))
    }
    draggingRef.current = false
    setMarquee(null)
  }

  function handleResize(event: PointerEvent<HTMLSpanElement>, shot: RecipeShot) {
    event.preventDefault()
    event.stopPropagation()
    if (!onUpdateShotDuration) return
    const startX = event.clientX
    const startDuration = shot.durationSec
    const handle = event.currentTarget
    handle.setPointerCapture(event.pointerId)
    const onMove = (move: globalThis.PointerEvent) => {
      onUpdateShotDuration(shot.id, snapH3DurationSec(startDuration + (move.clientX - startX) / pixelsPerSecond))
    }
    const onUp = () => {
      handle.releasePointerCapture(event.pointerId)
      handle.removeEventListener("pointermove", onMove)
      handle.removeEventListener("pointerup", onUp)
    }
    handle.addEventListener("pointermove", onMove)
    handle.addEventListener("pointerup", onUp)
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
        className="director-track-canvas"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onScroll={(event: UIEvent<HTMLDivElement>) => onCanvasScroll?.(event.currentTarget.scrollLeft)}
      >
        <div className="director-track-rows" style={{ width: `${canvasWidth}px` }}>
          <div className="director-playhead" style={{ left: `${currentTimeSec * pixelsPerSecond}px` }} />
          {marquee ? (
            <div className="director-track-marquee" style={{ left: `${marquee.left}px`, width: `${marquee.width}px` }} />
          ) : null}
          <div className="director-track-row director-track-row-video">
            {layout.map(({ shot, left, width }) => {
              const selected = selectedShotId === shot.id
              const checked = checkedShotIds.includes(shot.id)
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
                  <button
                    type="button"
                    className={`director-clip ${clipTone(shot, selected, checked)}`}
                    style={{ left: `${left}px`, width: `${width - 4}px` }}
                    onClick={(event) => onSelectShot(shot, event.shiftKey)}
                  >
                    镜头 {String(shot.shotNumber).padStart(2, "0")} · {shot.title}
                    {onUpdateShotDuration ? (
                      <span
                        className="director-clip-resize"
                        onPointerDown={(event) => handleResize(event, shot)}
                        aria-label="拖动调整时长"
                      />
                    ) : null}
                  </button>
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
              return (
                <div key={shot.id} className="director-subject-span" style={{ left: `${left + 16}px`, width: `${Math.max(48, width - 36)}px` }}>
                  {refs.join(" + ")}
                </div>
              )
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
                <div
                  key={shot.id}
                  className={`director-status-bar ${running ? "is-running" : ""} ${done ? "is-success" : ""}`}
                  style={{ left: `${left}px`, width: `${width - 4}px` }}
                >
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
