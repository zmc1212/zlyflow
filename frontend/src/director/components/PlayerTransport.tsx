import { Button, Tooltip } from "antd"
import { ChevronsLeft, ChevronsRight, Pause, Play, SkipBack, SkipForward } from "lucide-react"
import type { RefObject } from "react"
import { directorSecondsToFrames } from "../director-timeline-engine"
import { formatTransportTimecode } from "../opencut-timeline/transport"

export default function PlayerTransport({
  currentTimeSec,
  fps,
  playing,
  canPlay,
  safeGuides,
  timecodeRef,
  onGoToStart,
  onPreviousFrame,
  onTogglePlayback,
  onNextFrame,
  onGoToEnd,
  onToggleSafeGuides,
}: {
  currentTimeSec: number
  fps: number
  playing: boolean
  canPlay: boolean
  safeGuides: boolean
  timecodeRef: RefObject<HTMLSpanElement | null>
  onGoToStart: () => void
  onPreviousFrame: () => void
  onTogglePlayback: () => void
  onNextFrame: () => void
  onGoToEnd: () => void
  onToggleSafeGuides: () => void
}) {
  const controls = [
    { label: "跳到开头（Home）", icon: <SkipBack size={15} />, onClick: onGoToStart, primary: false, disabled: false },
    { label: "后退一帧（←）", icon: <ChevronsLeft size={15} />, onClick: onPreviousFrame, primary: false, disabled: false },
    {
      label: playing ? "暂停（Space）" : "播放（Space）",
      icon: playing ? <Pause size={15} /> : <Play size={15} />,
      onClick: onTogglePlayback,
      primary: true,
      disabled: !canPlay,
    },
    { label: "前进一帧（→）", icon: <ChevronsRight size={15} />, onClick: onNextFrame, primary: false, disabled: false },
    { label: "跳到结尾（End）", icon: <SkipForward size={15} />, onClick: onGoToEnd, primary: false, disabled: false },
  ]

  return (
    <div className="director-player-transport">
      <span ref={timecodeRef} className="director-player-timecode" aria-label="当前时间码">
        {formatTransportTimecode(directorSecondsToFrames(currentTimeSec, fps), fps)}
      </span>

      <div className="director-player-controls" role="group" aria-label="播放器控制">
        {controls.map((control) => (
          <Tooltip key={control.label} title={control.label} mouseEnterDelay={0.45}>
            <Button
              type="text"
              className={`director-player-control${control.primary ? " is-primary" : ""}`}
              icon={control.icon}
              aria-label={control.label}
              disabled={control.disabled}
              onClick={control.onClick}
            />
          </Tooltip>
        ))}
      </div>

      <Tooltip title={safeGuides ? "隐藏安全框" : "显示安全框"} mouseEnterDelay={0.45}>
        <Button
          type="text"
          className={`director-player-safe${safeGuides ? " is-active" : ""}`}
          aria-label={safeGuides ? "隐藏安全框" : "显示安全框"}
          aria-pressed={safeGuides}
          onClick={onToggleSafeGuides}
        >
          SAFE
        </Button>
      </Tooltip>
    </div>
  )
}
