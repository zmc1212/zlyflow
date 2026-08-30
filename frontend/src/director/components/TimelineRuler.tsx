import { Slider } from "antd"
import { Eye, ZoomIn } from "lucide-react"
import React, { useRef } from "react"
import type { RecipeShot } from "../recipe-model"
import { recipeRulerSeekSec, recipeRulerShotEdges, recipeRulerTicks } from "../recipe-timeline"

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
  onSeek: (timeSec: number) => void
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
  onSeek,
  onUnitToggle,
  onZoomChange,
  onSnapChange,
}: TimelineRulerProps) {
  const rulerRef = useRef<HTMLDivElement>(null)
  const ticks = recipeRulerTicks(totalDurationSec)
  const shotEdges = recipeRulerShotEdges(shots).filter((second) => second > 0 && !ticks.includes(second))

  const handleRulerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!rulerRef.current) return
    const rect = rulerRef.current.getBoundingClientRect()
    const offsetX = Math.max(0, e.clientX - rect.left) + scrollLeft
    onSeek(recipeRulerSeekSec(offsetX, pixelsPerSecond, totalDurationSec, { snap: snapEnabled, shots }))
  }

  return (
    <div className="director-ruler">
      <div className="director-ruler-gutter" />
      <div ref={rulerRef} className="director-ruler-scale" onClick={handleRulerClick}>
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
        <div className="director-playhead" style={{ left: `${currentTimeSec * pixelsPerSecond - scrollLeft}px` }} />
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
