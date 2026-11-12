import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { Button, Empty, Slider, Tooltip } from "antd"
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Film,
  Magnet,
  Music2,
  Redo2,
  Scissors,
  Trash2,
  Type,
  Undo2,
  ZoomIn,
  ZoomOut,
  ListStart
} from "lucide-react"
import {
  TRANSITIONS,
  endOf,
  frame,
  laneClips,
  timecode,
  type EditClip,
  type EditDocument,
  type EditTrack
} from "./model"

type Drag = {
  id: string
  kind: "move" | "left" | "right"
  origin: number
  delta: number
  clip: EditClip
}
export default function Timeline({
  doc,
  thumbnails,
  time,
  selected,
  canUndo,
  canRedo,
  onSelect,
  onTime,
  onUndo,
  onRedo,
  onSplit,
  onDelete,
  onCopy,
  onReorder,
  onPack,
  onDrag,
  onDropAsset
}: {
  doc: EditDocument
  thumbnails: Record<string, string>
  time: number
  selected: string
  canUndo: boolean
  canRedo: boolean
  onSelect: (id: string) => void
  onTime: (time: number) => void
  onUndo: () => void
  onRedo: () => void
  onSplit: () => void
  onDelete: () => void
  onCopy: () => void
  onReorder: (direction: -1 | 1) => void
  onPack: () => void
  onDrag: (id: string, kind: Drag["kind"], delta: number, snap: boolean) => void
  onDropAsset: (id: string, time: number, track?: EditTrack) => void
}) {
  const [zoom, setZoom] = useState(39),
    [snap, setSnap] = useState(true),
    [drag, setDrag] = useState<Drag | null>(null)
  const canvas = useRef<HTMLDivElement>(null),
    dragRef = useRef<Drag | null>(null)
  const scrubbing = useRef(false)
  const length = Math.max(20, endOf(doc) + 5),
    width = Math.max(720, length * zoom)
  const tick = zoom < 25 ? 10 : zoom < 60 ? 5 : 1
  function seek(event: ReactPointerEvent) {
    if (!canvas.current) return
    const bounds = canvas.current.getBoundingClientRect()
    onTime(
      Math.min(
        endOf(doc),
        frame((event.clientX - bounds.left) / zoom, doc.settings.fps)
      )
    )
  }
  function begin(
    event: ReactPointerEvent<HTMLDivElement>,
    clip: EditClip,
    kind: Drag["kind"]
  ) {
    event.preventDefault()
    event.stopPropagation()
    onSelect(clip.id)
    ;(event.currentTarget.closest(".se-clip") as HTMLElement | null)?.focus()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      id: clip.id,
      kind,
      origin: event.clientX,
      delta: 0,
      clip
    }
    setDrag(dragRef.current)
  }
  function move(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return
    dragRef.current = {
      ...dragRef.current,
      delta: (event.clientX - dragRef.current.origin) / zoom
    }
    setDrag(dragRef.current)
  }
  function finish(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return
    const current = dragRef.current
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    dragRef.current = null
    setDrag(null)
    if (Math.abs(current.delta) > 0.5 / zoom)
      onDrag(current.id, current.kind, current.delta, snap)
  }
  const tools = [
    { name: "撤销 (Ctrl+Z)", icon: Undo2, action: onUndo, disabled: !canUndo },
    {
      name: "重做 (Ctrl+Shift+Z)",
      icon: Redo2,
      action: onRedo,
      disabled: !canRedo
    },
    {
      name: "在播放头拆分 (S)",
      icon: Scissors,
      action: onSplit,
      disabled: !selected
    },
    { name: "复制片段", icon: Copy, action: onCopy, disabled: !selected },
    {
      name: "删除片段 (Delete)",
      icon: Trash2,
      action: onDelete,
      disabled: !selected
    },
    {
      name: "向前排序",
      icon: ArrowLeft,
      action: () => onReorder(-1),
      disabled: !selected
    },
    {
      name: "向后排序",
      icon: ArrowRight,
      action: () => onReorder(1),
      disabled: !selected
    },
    {
      name: "移除画面轨空隙",
      icon: ListStart,
      action: onPack,
      disabled: !doc.clips.some((c) => c.track === "video")
    }
  ]
  return (
    <section className="se-timeline" aria-label="剪辑时间线">
      <div className="se-timeline-toolbar">
        <div className="se-timeline-edit-tools">
          <div className="se-timeline-title"><strong>时间线</strong><span>{doc.clips.length} 个片段</span></div>
          {tools.map(({ name, icon: Icon, action, disabled }, index) => (
            <Tooltip key={name} title={name}>
              <Button
                type="text"
                aria-label={name}
                className={index === 2 || index === 5 || index === 7 ? "se-tool-group-start" : undefined}
                icon={<Icon size={15} />}
                disabled={disabled}
                onClick={action}
              />
            </Tooltip>
          ))}
        </div>
        <div className="se-timeline-zoom">
          <Tooltip title="拖动时吸附片段边缘">
            <Button
              type={snap ? "primary" : "text"}
              aria-label="时间线磁吸"
              aria-pressed={snap}
              icon={<Magnet size={15} />}
              onClick={() => setSnap(!snap)}
            />
          </Tooltip>
          <ZoomOut size={14} />
          <Slider
            aria-label="时间线缩放"
            min={12}
            max={160}
            value={zoom}
            onChange={setZoom}
          />
          <ZoomIn size={14} />
        </div>
      </div>
      <div className="se-timeline-body">
        <div className="se-track-labels">
          <div className="se-ruler-label">时间线</div>
          {(
            [
              { key: "text", name: "文字", Icon: Type },
              { key: "video", name: "画面", Icon: Film },
              { key: "audio", name: "配音", Icon: Music2 },
              { key: "music", name: "音乐", Icon: Music2 }
            ] as const
          ).map(({ key, name, Icon }) => (
            <div key={key} className={`se-track-label se-track-${key}`}>
              <Icon size={15} />
              <span>{name}</span>
              <i className={`se-track-indicator is-${key}`} aria-hidden="true" />
            </div>
          ))}
        </div>
        <div className="se-timeline-scroll">
          <div
            ref={canvas}
            className="se-timeline-canvas"
            style={{ width, "--se-tick-step": `${zoom}px` } as React.CSSProperties}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault()
              const id = event.dataTransfer.getData("application/x-zly-asset")
              const lane = (event.target as Element)
                .closest(".se-track")
                ?.getAttribute("data-track") as EditTrack | undefined
              if (id && canvas.current)
                onDropAsset(
                  id,
                  frame(
                    (event.clientX -
                      canvas.current.getBoundingClientRect().left) /
                      zoom,
                    doc.settings.fps
                  ),
                  lane
                )
            }}
          >
            <div
              className="se-ruler"
              onPointerDown={(event) => {
                scrubbing.current = true
                event.currentTarget.setPointerCapture(event.pointerId)
                seek(event)
              }}
              onPointerMove={(event) => {
                if (scrubbing.current) seek(event)
              }}
              onPointerUp={(event) => {
                scrubbing.current = false
                event.currentTarget.releasePointerCapture(event.pointerId)
              }}
              onPointerCancel={() => {
                scrubbing.current = false
              }}
              role="slider"
              tabIndex={0}
              aria-label="播放位置"
              aria-valuemin={0}
              aria-valuemax={endOf(doc)}
              aria-valuenow={time}
              onKeyDown={(event) => {
                if (
                  ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
                ) {
                  event.preventDefault()
                  onTime(
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? endOf(doc)
                        : Math.max(
                            0,
                            Math.min(
                              endOf(doc),
                              time +
                                (event.key === "ArrowLeft" ? -1 : 1) /
                                  doc.settings.fps
                            )
                          )
                  )
                }
              }}
            >
              {Array.from({ length: Math.floor(length / tick) + 1 }, (_, i) => (
                <span key={i} style={{ left: i * tick * zoom }}>
                  {timecode(i * tick, doc.settings.fps).slice(0, 5)}
                </span>
              ))}
            </div>
            {(["text", "video", "audio", "music"] as EditTrack[]).map((track) => (
              <div
                key={track}
                className={`se-track se-track-${track}`}
                data-track={track}
                onPointerDown={seek}
              >
                {laneClips(doc, track).map((clip) => {
                  const asset = doc.assets.find((a) => a.id === clip.asset_id),
                    live = drag?.id === clip.id ? drag : null
                  const x =
                    (clip.start +
                      (live?.kind === "move" || live?.kind === "left"
                        ? live.delta
                        : 0)) *
                    zoom
                  const cw = Math.max(
                    5,
                    (clip.duration +
                      (live?.kind === "right"
                        ? live.delta
                        : live?.kind === "left"
                          ? -live.delta
                          : 0)) *
                      zoom
                  )
                  const thumb =
                    asset?.thumbnail ||
                    (asset && thumbnails[asset.id]) ||
                    (asset?.kind === "image" ? asset.url : null)
                  return (
                    <div
                      key={clip.id}
                      role="button"
                      aria-label={`${track === "text" ? "文字" : "片段"}：${asset?.name || clip.text}`}
                      aria-pressed={selected === clip.id}
                      tabIndex={0}
                      className={`se-clip se-clip-${track}${selected === clip.id ? " is-selected" : ""}${live ? " is-dragging" : ""}`}
                      style={{ left: x, width: cw }}
                      onPointerDown={(event) => begin(event, clip, "move")}
                      onPointerMove={move}
                      onPointerUp={finish}
                      onPointerCancel={() => {
                        dragRef.current = null
                        setDrag(null)
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          onSelect(clip.id)
                          onTime(clip.start)
                        }
                      }}
                      onDoubleClick={() => onTime(clip.start)}
                    >
                      {thumb && (
                        <div
                          className="se-clip-filmstrip"
                          style={{
                            backgroundImage: `url(${JSON.stringify(thumb)})`
                          }}
                        />
                      )}
                      <div className="se-clip-caption">
                        <span>
                          {clip.track === "text" ? (
                            <Type size={11} />
                          ) : clip.track === "audio" ? (
                            <Music2 size={11} />
                          ) : (
                            <Film size={11} />
                          )}
                          {asset?.name || clip.text}
                        </span>
                        <span>
                          {clip.speed !== 1 ? `${clip.speed}× · ` : ""}
                          {timecode(clip.duration, doc.settings.fps).slice(0, 5)}
                          {clip.muted ? " · 静音" : ""}
                        </span>
                      </div>
                      {clip.track === "video" &&
                        clip.transition &&
                        clip.transition !== "none" && (
                          <span
                            className="se-clip-transition"
                            title={`转场：${
                              TRANSITIONS.find(
                                (t) => t.id === clip.transition
                              )?.name || ""
                            } ${clip.transition_duration ?? 0.5} 秒`}
                          >
                            {
                              TRANSITIONS.find(
                                (t) => t.id === clip.transition
                              )?.name
                            }
                          </span>
                        )}
                      <div
                        role="separator"
                        aria-label="裁切片段起点"
                        className="se-trim-handle is-left"
                        onPointerDown={(event) => begin(event, clip, "left")}
                        onPointerMove={move}
                        onPointerUp={finish}
                      />
                      <div
                        role="separator"
                        aria-label="裁切片段终点"
                        className="se-trim-handle is-right"
                        onPointerDown={(event) => begin(event, clip, "right")}
                        onPointerMove={move}
                        onPointerUp={finish}
                      />
                    </div>
                  )
                })}
              </div>
            ))}
            <div className="se-playhead" style={{ left: time * zoom }}>
              <span />
              <i />
            </div>
            {!doc.clips.length && (
              <div className="se-timeline-empty">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="双击素材或拖入这里，开始剪辑"
                />
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="se-timeline-footer">
        <span>
          {doc.clips.length} 个片段 <span className="se-dot">·</span>{" "}
          {endOf(doc).toFixed(2)} 秒
        </span>
        <span>
          空格 播放 / 暂停 <span className="se-dot">·</span> S 拆分{" "}
          <span className="se-dot">·</span> 拖动片段两端裁切
        </span>
      </div>
    </section>
  )
}
