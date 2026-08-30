import { Slider } from "antd"
import { Eye, ZoomIn } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { RefObject } from "react"
import type { RecipeShot } from "../recipe-model"
import { DIRECTOR_TIMELINE_FPS, directorSecondsToFrames } from "../director-timeline-engine"
import { PlayheadController } from "../opencut-timeline/playhead-controller"
import { useCommittedRef } from "../opencut-timeline/use-committed-ref"
import { recipeRulerShotEdges, recipeRulerTicks } from "../recipe-timeline"

interface TimelineRulerProps {
  shots?: RecipeShot[]
  totalDurationSec: number
  currentTimeSec: number
  pixelsPerSecond: number
  unit: "seconds" | "frames"
  fps?: number
  snapEnabled?: boolean
  scrollLeft?: number
  minPixelsPerSecond?: number
  playheadElementRef?: RefObject<HTMLDivElement | null>
  onSeekPreview: (timeSec: number) => void
  onSeekCommit: (timeSec: number) => void
  onScrubbingChange?: (scrubbing: boolean) => void
  onUnitToggle: () => void
  onZoomChange: (pxPerSec: number) => void
  onSnapChange?: (enabled: boolean) => void
}

export default function TimelineRuler({
  shots = [],
  totalDurationSec,
  currentTimeSec,
  pixelsPerSecond,
  unit,
  fps = 24,
  snapEnabled = true,
  scrollLeft = 0,
  minPixelsPerSecond = 24,
  playheadElementRef,
  onSeekPreview,
  onSeekCommit,
  onScrubbingChange,
  onUnitToggle,
  onZoomChange,
  onSnapChange,
}: TimelineRulerProps) {
  const rulerRef = useRef<HTMLDivElement>(null)
  const localPlayheadRef = useRef<HTMLDivElement>(null)
  const playheadRef = playheadElementRef || localPlayheadRef
  const shiftHeldRef = useRef(false)
  const ticks = recipeRulerTicks(totalDurationSec)
  const shotEdges = recipeRulerShotEdges(shots).filter((second) => second > 0 && !ticks.includes(second))
  const configRef = useCommittedRef({
    shots,
    pixelsPerSecond,
    snapEnabled,
    getRulerEl: () => rulerRef.current,
    getRulerScrollLeft: () => scrollLeft,
    getPlayheadEl: () => playheadRef.current,
    getExtraSnapFrames: () => [directorSecondsToFrames(currentTimeSec)],
    isShiftHeld: () => shiftHeldRef.current,
    previewSeek: (frame: number) => onSeekPreview(frame / DIRECTOR_TIMELINE_FPS),
    commitSeek: (frame: number) => onSeekCommit(frame / DIRECTOR_TIMELINE_FPS),
    setScrubbing: (scrubbing: boolean) => onScrubbingChange?.(scrubbing),
  })
  const [controller] = useState(() => new PlayheadController({ configRef }))

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Shift") shiftHeldRef.current = true
    }
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === "Shift") shiftHeldRef.current = false
    }
    window.addEventListener("keydown", handleKeyDown)
    window.addEventListener("keyup", handleKeyUp)
    return () => {
      window.removeEventListener("keydown", handleKeyDown)
      window.removeEventListener("keyup", handleKeyUp)
      controller.destroy()
    }
  }, [controller])

  useEffect(() => {
    if (!controller.isActive) controller.updatePlayheadLeft(directorSecondsToFrames(currentTimeSec))
  }, [controller, currentTimeSec, pixelsPerSecond, scrollLeft])

  return (
    <div className="director-ruler">
      <div className="director-ruler-gutter" />
      <div ref={rulerRef} className="director-ruler-scale" onMouseDown={controller.onRulerMouseDown}>
        {shotEdges.map((second) => (
          <div
            key={`shot-${second}`}
            className="director-ruler-tick is-shot"
            style={{ left: `${second * pixelsPerSecond - scrollLeft}px` }}
          >
            <i />
          </div>
        ))}
        {ticks.map((second) => (
          <div key={second} className="director-ruler-tick" style={{ left: `${second * pixelsPerSecond - scrollLeft}px` }}>
            <i />
            <span>{unit === "seconds" ? `${second}s` : `${second * fps}f`}</span>
          </div>
        ))}
        <div
          ref={playheadRef}
          className="director-playhead director-playhead-interactive"
          role="slider"
          tabIndex={0}
          aria-label="播放头"
          aria-valuemin={0}
          aria-valuemax={Math.round(totalDurationSec * DIRECTOR_TIMELINE_FPS)}
          aria-valuenow={directorSecondsToFrames(currentTimeSec)}
          onMouseDown={controller.onPlayheadMouseDown}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return
            event.preventDefault()
            const delta = event.key === "ArrowLeft" ? -1 : 1
            onSeekCommit(Math.max(0, Math.min(totalDurationSec, currentTimeSec + delta / DIRECTOR_TIMELINE_FPS)))
          }}
        />
      </div>
      <div className="director-ruler-tools">
        <button type="button" className="director-snap-chip" onClick={() => onSnapChange?.(!snapEnabled)}>
          <Eye size={12} />
          {snapEnabled ? "吸附开启" : "吸附关闭"}
        </button>
        <button type="button" className="director-snap-chip" onClick={onUnitToggle}>{unit === "seconds" ? "秒" : "帧"}</button>
        <ZoomIn size={14} className="text-[#98a2ad]" />
        <Slider min={minPixelsPerSecond} max={120} value={pixelsPerSecond} onChange={onZoomChange} tooltip={{ open: false }} />
      </div>
    </div>
  )
}
