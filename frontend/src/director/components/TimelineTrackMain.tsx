import { Dropdown } from "antd"
import { Copy, Plus, Trash2 } from "lucide-react"
import React from "react"
import { DirectorShot, SubjectSlot } from "../types"

interface TimelineTrackMainProps {
  shots: DirectorShot[]
  subjectSlots?: SubjectSlot[]
  selectedShotId?: string
  pixelsPerSecond: number
  currentTimeSec: number
  onSelectShot: (shot: DirectorShot) => void
  onAddShot: () => void
  onDeleteShot: (shotId: string) => void
  onDuplicateShot: (shot: DirectorShot) => void
  onRenderShot: (shot: DirectorShot) => void
  onUpdateShotDuration: (shotId: string, durationSec: number) => void
  onOpenFrameScrubber?: (shot: DirectorShot) => void
}

function statusCopy(shot: DirectorShot) {
  if (shot.status === "succeeded") return "已完成 100%"
  if (shot.status === "running") return `生成中 ${shot.progress || 0}%`
  if (shot.status === "queued") return "排队中"
  if (shot.status === "failed") return "需要处理"
  if (shot.status === "interrupted") return "已中断"
  if (shot.status === "cancelled") return "已停止"
  return "待生成"
}

export default function TimelineTrackMain({
  shots,
  subjectSlots = [],
  selectedShotId,
  pixelsPerSecond,
  currentTimeSec,
  onSelectShot,
  onAddShot,
  onDeleteShot,
  onDuplicateShot,
}: TimelineTrackMainProps) {
  let accumulatedTime = 0
  const layout = shots.map((shot) => {
    const start = accumulatedTime
    accumulatedTime += shot.durationSec
    return { shot, start, width: Math.max(72, shot.durationSec * pixelsPerSecond) }
  })
  const canvasWidth = Math.max(accumulatedTime * pixelsPerSecond + 88, 640)

  return (
    <div className="director-tracks">
      <div className="director-track-labels">
        <span>视频镜头</span>
        <span>主体参考</span>
        <span>首尾帧</span>
        <span>生成状态</span>
      </div>
      <div className="director-track-canvas">
        <div className="director-track-rows" style={{ width: `${canvasWidth}px` }}>
          <div className="director-playhead" style={{ left: `${currentTimeSec * pixelsPerSecond}px` }} />
          <div className="director-track-row director-track-row-video">
            {layout.map(({ shot, start, width }) => {
              const selected = selectedShotId === shot.id
              const tone = selected || shot.status === "running" || shot.status === "queued"
                ? "director-clip-selected"
                : shot.status === "succeeded"
                  ? "director-clip-success"
                  : "director-clip-idle"
              return (
                <Dropdown
                  key={shot.id}
                  trigger={["contextMenu"]}
                  menu={{
                    items: [
                      { key: "dup", label: "复制分镜", icon: <Copy size={13} />, onClick: () => onDuplicateShot(shot) },
                      { key: "del", label: "删除分镜", icon: <Trash2 size={13} />, danger: true, disabled: shots.length <= 1, onClick: () => onDeleteShot(shot.id) },
                    ],
                  }}
                >
                  <button
                    type="button"
                    className={`director-clip ${tone}`}
                    style={{ left: `${start * pixelsPerSecond}px`, width: `${width - 4}px` }}
                    onClick={() => onSelectShot(shot)}
                  >
                    镜头 {String(shot.shotNumber).padStart(2, "0")} · {shot.title}
                  </button>
                </Dropdown>
              )
            })}
            <button type="button" className="director-add-next" style={{ left: `${accumulatedTime * pixelsPerSecond + 8}px`, width: 72 }} onClick={onAddShot}>
              <Plus size={12} />
            </button>
          </div>
          <div className="director-track-row director-track-row-subjects">
            {layout.map(({ shot, start, width }) => {
              const refs = shot.referencedSubjectIds.map((id) => {
                const slot = subjectSlots.find((item) => item.id === id)
                return slot?.name && !slot.name.startsWith("主体") ? `${id} ${slot.name}` : id
              })
              if (!refs.length) return null
              return (
                <div key={shot.id} className="director-subject-span" style={{ left: `${start * pixelsPerSecond + 16}px`, width: `${Math.max(48, width - 36)}px` }}>
                  {refs.join(" + ")}
                </div>
              )
            })}
          </div>
          <div className="director-track-row director-track-row-frames">
            {layout.map(({ shot, start, width }) => (
              <div key={shot.id} className="director-frame-marks" style={{ left: `${start * pixelsPerSecond}px`, width: `${width}px` }}>
                <span className={`director-diamond ${shot.firstFrameUrl ? "is-set" : ""}`} />
                <span className={`director-diamond ${shot.endFrameUrl ? "is-set" : ""}`} />
              </div>
            ))}
          </div>
          <div className="director-track-row director-track-row-status">
            {layout.map(({ shot, start, width }) => {
              const running = shot.status === "running" || shot.status === "queued"
              const done = shot.status === "succeeded"
              return (
                <div
                  key={shot.id}
                  className={`director-status-bar ${running ? "is-running" : ""} ${done ? "is-success" : ""}`}
                  style={{ left: `${start * pixelsPerSecond}px`, width: `${width - 4}px` }}
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
