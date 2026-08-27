import { Slider } from "antd"
import { Eye, ZoomIn } from "lucide-react"
import React, { useRef } from "react"

interface TimelineRulerProps {
  totalDurationSec: number
  currentTimeSec: number
  pixelsPerSecond: number
  unit: "seconds" | "frames"
  fps?: number
  snapEnabled?: boolean
  onSeek: (timeSec: number) => void
  onUnitToggle: () => void
  onZoomChange: (pxPerSec: number) => void
  onSnapChange?: (enabled: boolean) => void
}

export default function TimelineRuler({
  totalDurationSec,
  currentTimeSec,
  pixelsPerSecond,
  unit,
  fps = 24,
  snapEnabled = true,
  onSeek,
  onUnitToggle,
  onZoomChange,
  onSnapChange,
}: TimelineRulerProps) {
  const rulerRef = useRef<HTMLDivElement>(null)
  const maxSec = Math.max(totalDurationSec, 15)
  const ticks: number[] = []
  for (let s = 0; s <= maxSec; s += 5) ticks.push(s)

  const handleRulerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!rulerRef.current) return
    const rect = rulerRef.current.getBoundingClientRect()
    const offsetX = Math.max(0, e.clientX - rect.left)
    const raw = offsetX / pixelsPerSecond
    const snapped = snapEnabled ? Math.round(raw) : raw
    onSeek(Math.min(maxSec, Math.max(0, snapped)))
  }

  return (
    <div className="director-ruler">
      <div className="director-ruler-gutter" />
      <div ref={rulerRef} className="director-ruler-scale" onClick={handleRulerClick}>
        {ticks.map((s) => (
          <div key={s} className="director-ruler-tick" style={{ left: `${s * pixelsPerSecond}px` }}>
            <i />
            <span>{unit === "seconds" ? `${s}s` : `${s * fps}f`}</span>
          </div>
        ))}
        <div className="director-playhead" style={{ left: `${currentTimeSec * pixelsPerSecond}px` }} />
      </div>
      <div className="director-ruler-tools">
        <button type="button" className="director-snap-chip" onClick={() => onSnapChange?.(!snapEnabled)}>
          <Eye size={12} />
          {snapEnabled ? "吸附开启" : "吸附关闭"}
        </button>
        <button type="button" className="director-snap-chip" onClick={onUnitToggle}>{unit === "seconds" ? "秒" : "帧"}</button>
        <ZoomIn size={14} className="text-[#98a2ad]" />
        <Slider min={24} max={120} value={pixelsPerSecond} onChange={onZoomChange} tooltip={{ open: false }} />
      </div>
    </div>
  )
}
