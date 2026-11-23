import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent
} from "react"
import { NodeResizer, type NodeProps } from "@xyflow/react"
import { Button, Slider, Tooltip, message } from "antd"
import {
  Clock,
  Download,
  Eye,
  Film,
  Maximize2,
  Pause,
  Play,
  Plus,
  Redo2,
  Scissors,
  Sparkles,
  Tag,
  Trash2,
  Type,
  Undo2,
  Volume2
} from "lucide-react"
import {
  endOf,
  frame,
  timecode,
  type EditAsset,
  type EditClip,
  type EditDocument,
  type EditTrack
} from "./model"
import {
  editorSessionKey,
  isEditSessionActive,
  subscribeEditSession,
  useEditingNodeContext
} from "./editing-shared"
import { assetFrames, imageFrames } from "./filmstrip"
import { useEditDocument } from "./use-edit-document"
import type { CanvasNode } from "../canvas/canvas-model"
import { NodeFloatingToolbar, NODE_RESIZE_HANDLE, NODE_RESIZE_LINE, CanvasPort } from "../canvas/node-primitives"
import "./editing.css"
import "./editing-overlays.css"

export type TimelineNodeVariant = "canvas" | "director"

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败"

type MiniLane = { key: EditTrack; clips: EditClip[]; icon: typeof Film; label: string }

function lanesOf(doc: EditDocument, variant: TimelineNodeVariant): MiniLane[] {
  const lanes: MiniLane[] = [
    { key: "video", clips: [], icon: variant === "director" ? Eye : Film, label: "画面" },
    { key: "audio", clips: [], icon: Volume2, label: "声音" },
    { key: "text", clips: [], icon: Type, label: "文字" }
  ]
  for (const clip of doc.clips) {
    const lane = lanes.find((item) => item.key === clip.track || (item.key === "audio" && clip.track === "music"))
    if (lane) lane.clips.push(clip)
  }
  const used = lanes.filter((lane) => lane.clips.length)
  return used.length ? used : lanes.slice(0, 1)
}

function activeClip(doc: EditDocument, track: EditTrack, time: number): EditClip | undefined {
  return doc.clips.find(
    (c) =>
      (c.track === track || (track === "audio" && c.track === "music")) &&
      time + 0.00001 >= c.start &&
      time < c.start + c.duration - 0.00001
  )
}

/** 播放时浮在节点上方的小预览窗：画面 + 声音与全屏编辑器同一套时间驱动。 */
function MiniStage({
  doc,
  time,
  volume,
  onProbe
}: {
  doc: EditDocument
  time: number
  volume: number
  onProbe: (id: string, duration: number) => void
}) {
  const picture = activeClip(doc, "video", time)
  const asset = doc.assets.find((a) => a.id === picture?.asset_id)
  const [w, h] = doc.settings.ratio === "9:16" ? [9, 16] : doc.settings.ratio === "1:1" ? [1, 1] : doc.settings.ratio === "4:3" ? [4, 3] : doc.settings.ratio === "3:4" ? [3, 4] : [16, 9]
  // 即梦式尺寸：高度约为节点高的 2 倍（即梦实测 ~2.06×），宽度由工程画幅 aspect-ratio 推出，
  // 超出节点宽度时按节点宽封顶（多出的部分只是黑边）；文字叠加按实测宽度换算字号。
  const stageRef = useRef<HTMLDivElement>(null)
  const [stageWidth, setStageWidth] = useState(480)
  useEffect(() => {
    const element = stageRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => setStageWidth(entries[0].contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const text = activeClip(doc, "text", time)
  return (
    <div ref={stageRef} className="se-node-stage" style={{ aspectRatio: `${w} / ${h}` }} aria-hidden="true">
      {asset ? (
        asset.kind === "image" ? (
          <img src={asset.url} alt="" style={{ opacity: picture?.opacity ?? 1 }} />
        ) : (
          <video
            src={asset.url}
            preload="auto"
            playsInline
            style={{ opacity: picture?.opacity ?? 1 }}
            onLoadedMetadata={(event) => {
              if (Number.isFinite(event.currentTarget.duration)) onProbe(asset.id, event.currentTarget.duration)
            }}
            ref={(element) => {
              if (!element || !picture) return
              const target = picture.in_point + Math.max(0, time - picture.start) * picture.speed
              if (Number.isFinite(target) && Math.abs(element.currentTime - target) > 0.18) element.currentTime = target
              element.playbackRate = picture.speed
              element.volume = Math.min(1, picture.volume * (picture.muted ? 0 : 1) * volume)
              void element.play().catch(() => undefined)
            }}
          />
        )
      ) : null}
      {text && (
        <div
          className="se-preview-text"
          style={{
            left: 0,
            top: `${50 + text.y}%`,
            color: text.color,
            fontSize: Math.max(11, (text.font_size * stageWidth) / 1920),
            opacity: text.opacity
          }}
        >
          {text.text}
        </div>
      )}
      {doc.clips
        .filter((c) => c.track === "audio" || c.track === "music")
        .filter((c) => time + 0.00001 >= c.start && time < c.start + c.duration - 0.00001)
        .map((clip) => {
          const sound = doc.assets.find((a) => a.id === clip.asset_id)
          if (!sound) return null
          return (
            <audio
              key={clip.id}
              ref={(element) => {
                if (!element) return
                const target = clip.in_point + Math.max(0, time - clip.start) * clip.speed
                if (Number.isFinite(target) && Math.abs(element.currentTime - target) > 0.18) element.currentTime = target
                element.volume = Math.min(1, clip.volume * (clip.muted ? 0 : 1) * volume)
                void element.play().catch(() => undefined)
              }}
              src={sound.url}
              preload="auto"
            />
          )
        })}
    </div>
  )
}

/**
 * 迷你时间线节点卡片（即梦式）。
 *
 * 两个宿主共用：
 * - variant="canvas"：无限画布「时间线」节点（图1：分列工具 + 时间码 + 全屏编辑）。
 * - variant="director"：导演台「多轨编辑器」节点（图3：撤销重做 + 智能字幕识别 + 音量）。
 * 完整剪辑（拖拽/裁切/属性/导出字幕）在全屏编辑器中完成。
 */
export function TimelineNodeCard({
  csrfToken,
  scopeProjectId,
  sequence,
  title,
  titleIcon,
  variant,
  openFullscreen
}: {
  csrfToken: string
  scopeProjectId: string
  sequence: string
  title: string
  titleIcon?: React.ReactNode
  variant: TimelineNodeVariant
  openFullscreen: () => void
}) {
  const director = variant === "director"
  const ctrl = useEditDocument({
    csrfToken,
    scopeProjectId,
    sequence,
    deferWhileBusySession: true
  })
  const { doc, loading, loadError, saveState, saveError, time, playing, seek, play, selected, select, undo, split, remove, probeAsset, job } = ctrl
  const [volume, setVolume] = useState(1)
  const [exportBusy, setExportBusy] = useState(false)
  const rulerRef = useRef<HTMLDivElement>(null)
  const scrubbing = useRef(false)
  const [rulerWidth, setRulerWidth] = useState(720)
  // 即梦式胶片带：时间线上出现的视频/图片素材按 url 抽帧缓存
  const [filmstrips, setFilmstrips] = useState<Record<string, string[]>>({})
  const stripRequested = useRef(new Set<string>())
  useEffect(() => {
    const usedUrls = new Set(
      doc.clips
        .map((clip) => doc.assets.find((asset) => asset.id === clip.asset_id))
        .filter((asset): asset is EditAsset => !!asset && (asset.kind === "video" || asset.kind === "image"))
        .map((asset) => asset.url)
    )
    for (const url of usedUrls) {
      if (stripRequested.current.has(url)) continue
      stripRequested.current.add(url)
      const asset = doc.assets.find((item) => item.url === url)!
      const job = asset.kind === "video" ? assetFrames(url) : Promise.resolve(imageFrames(asset))
      void job
        .then((result) => {
          if (result.frames.length) setFilmstrips((current) => ({ ...current, [url]: result.frames }))
        })
        .catch(() => undefined)
    }
  }, [doc])

  // 同一工程的全屏编辑器打开期间暂停自动保存；关闭后冲刷并重载最新文档。
  const sessionKey = editorSessionKey(scopeProjectId, sequence)
  const sessionOpen = useSyncExternalStore(subscribeEditSession, () => isEditSessionActive(sessionKey))
  const wasSessionOpen = useRef(false)
  useEffect(() => {
    if (wasSessionOpen.current && !sessionOpen) {
      void ctrl
        .saveLatest()
        .then(() => ctrl.reload())
        .catch(() => undefined)
    }
    wasSessionOpen.current = sessionOpen
    // ctrl.reload/saveLatest 由 useEditDocument 稳定提供
  }, [sessionOpen, ctrl.reload, ctrl.saveLatest])

  useEffect(() => {
    const element = rulerRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => setRulerWidth(entries[0].contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const end = endOf(doc)
  const length = Math.max(director ? 10 : 30, end + (director ? 1 : 5))
  const zoom = Math.max(4, rulerWidth / length)
  const tick = useMemo(() => {
    const candidates = director ? [0.5, 1, 2, 5, 10] : [1, 5, 10, 15, 30, 60]
    for (const candidate of candidates) {
      if (candidate * zoom >= 56) return candidate
    }
    return candidates[candidates.length - 1]
  }, [director, zoom])

  const seekFromEvent = useCallback(
    (event: { clientX: number }, bounds?: DOMRect) => {
      const rect = bounds || rulerRef.current?.getBoundingClientRect()
      if (!rect) return
      seek(frame(Math.max(0, (event.clientX - rect.left) / zoom), doc.settings.fps))
    },
    [doc.settings.fps, seek, zoom]
  )

  const lanes = lanesOf(doc, variant)
  const emptyDoc = !doc.clips.length

  async function download() {
    if (exportBusy) return
    setExportBusy(true)
    try {
      await ctrl.saveLatest()
      await ctrl.startExport(1080)
      message.info("成片导出中，完成后这里会出现下载链接")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setExportBusy(false)
    }
  }

  if (loading)
    return (
      <div className="se-node-card" role="status" aria-label="正在读取时间线">
        <div className="se-node-loading">正在读取时间线…</div>
      </div>
    )
  if (loadError)
    return (
      <div className="se-node-card is-error" aria-label="时间线读取失败">
        <div className="se-node-heading">
          <strong>{titleIcon}{title}</strong>
        </div>
        <div className="se-node-status is-error">时间线读取失败：{loadError}</div>
        <Button size="small" onClick={() => void ctrl.reload()}>重新加载</Button>
      </div>
    )

  const shortTime = (value: number) =>
    director ? timecode(value, doc.settings.fps) : timecode(value, doc.settings.fps).slice(0, 5)

  return (
    <>
    <div
      className={`se-node-card${playing ? " is-playing" : ""}`}
      tabIndex={0}
      aria-label={`${title}迷你时间线`}
      onKeyDown={(event) => {
        if ((event.target as HTMLElement).closest("input,textarea,[role='slider'],.ant-slider")) return
        if (event.code === "Space") {
          event.preventDefault()
          event.stopPropagation()
          play(!playing)
        } else if (event.key === "Delete" || event.key === "Backspace") {
          if (selected) {
            event.preventDefault()
            event.stopPropagation()
            remove()
          }
        }
      }}
    >
      <div className="se-node-heading">
        <strong>{titleIcon}{title}</strong>
        <Tag size={13} aria-hidden="true" />
      </div>
      <div className="se-node-toolbar">
        <Tooltip title="在播放头拆分"><Button type="text" size="small" className="nodrag nopan" aria-label="拆分片段" disabled={!selected} icon={<Scissors size={14} />} onClick={split} /></Tooltip>
        <Tooltip title="删除所选片段"><Button type="text" size="small" className="nodrag nopan" aria-label="删除片段" disabled={!selected} icon={<Trash2 size={14} />} onClick={remove} /></Tooltip>
        {director && (
          <>
            <span className="se-node-toolbar-divider" aria-hidden="true" />
            <Tooltip title="撤销 Ctrl+Z"><Button type="text" size="small" className="nodrag nopan" aria-label="撤销" disabled={!ctrl.canUndo} icon={<Undo2 size={14} />} onClick={() => undo()} /></Tooltip>
            <Tooltip title="重做 Ctrl+Shift+Z"><Button type="text" size="small" className="nodrag nopan" aria-label="重做" disabled={!ctrl.canRedo} icon={<Redo2 size={14} />} onClick={() => undo(true)} /></Tooltip>
            <Tooltip title="智能字幕识别（全屏编辑）">
              <Button type="text" size="small" className="nodrag nopan se-node-subtitle-tag" aria-label="智能字幕识别" icon={<Sparkles size={13} />} onClick={openFullscreen}>智能字幕识别</Button>
            </Tooltip>
          </>
        )}
        <span className="se-node-transport">
          <Tooltip title={playing ? "暂停" : "播放"}>
            <Button
              type="text"
              size="small"
              className="nodrag nopan"
              aria-label={playing ? "暂停" : "播放"}
              disabled={!doc.clips.length}
              icon={playing ? <Pause size={16} /> : <Play size={16} />}
              onClick={() => play(!playing)}
            />
          </Tooltip>
          <span><b>{shortTime(time)}</b> / {shortTime(end)}</span>
        </span>
        {director && (
          <span className="se-node-volume nodrag nopan">
            <Slider
              aria-label="预览音量"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={setVolume}
              tooltip={{ open: false }}
            />
            <Volume2 size={14} />
          </span>
        )}
        <span className="se-node-actions">
          <Tooltip title="导出成片 MP4">
            <Button type="text" size="small" className="nodrag nopan" aria-label="导出成片" disabled={!doc.clips.length} loading={exportBusy} icon={<Download size={14} />} onClick={() => void download()} />
          </Tooltip>
          <Button type="text" size="small" className="nodrag nopan se-node-fullscreen" aria-label="全屏编辑" icon={<Maximize2 size={14} />} onClick={openFullscreen}>全屏编辑</Button>
        </span>
      </div>
      <div
        ref={rulerRef}
        className="se-node-ruler nodrag nopan"
        role="slider"
        tabIndex={0}
        aria-label="播放位置"
        aria-valuemin={0}
        aria-valuemax={end}
        aria-valuenow={time}
        onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => {
          scrubbing.current = true
          event.currentTarget.setPointerCapture(event.pointerId)
          seekFromEvent(event)
        }}
        onPointerMove={(event: ReactPointerEvent<HTMLDivElement>) => {
          if (scrubbing.current) seekFromEvent(event)
        }}
        onPointerUp={(event: ReactPointerEvent<HTMLDivElement>) => {
          scrubbing.current = false
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
        }}
        onPointerCancel={() => {
          scrubbing.current = false
        }}
        onKeyDown={(event) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault()
            event.stopPropagation()
            seek(
              event.key === "Home" ? 0
                : event.key === "End" ? end
                  : Math.max(0, Math.min(end, time + (event.key === "ArrowLeft" ? -1 : 1) / doc.settings.fps))
            )
          }
        }}
      >
        {Array.from({ length: Math.floor(length / tick) + 1 }, (_, index) => (
          <span key={index} style={{ left: index * tick * zoom }}>
            {director
              ? (index * tick).toFixed(2)
              : timecode(index * tick, doc.settings.fps).slice(0, 5)}
          </span>
        ))}
        <span className="se-node-playhead" style={{ left: time * zoom }} />
      </div>
      <div className="se-node-lanes nodrag nopan">
        {lanes.map((lane) => (
          <div
            key={lane.key}
            className="se-node-lane"
            data-track={lane.key}
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) {
                select("")
                seekFromEvent(event, event.currentTarget.getBoundingClientRect())
              }
            }}
          >
            <span className="se-node-lane-icon"><lane.icon size={13} /></span>
            {lane.clips.map((clip) => {
              const asset = doc.assets.find((a) => a.id === clip.asset_id)
              const frames = asset && (asset.kind === "video" || asset.kind === "image")
                ? filmstrips[asset.url] || (asset.kind === "image" ? [asset.thumbnail || asset.url] : [])
                : []
              const clipWidth = Math.max(10, clip.duration * zoom)
              const frameCount = Math.max(1, Math.ceil(clipWidth / 30))
              return (
                <button
                  key={clip.id}
                  type="button"
                  className={`se-node-lane-clip${clip.track === "audio" || clip.track === "music" ? " is-audio" : clip.track === "text" ? " is-text" : ""}${selected === clip.id ? " is-selected" : ""}`}
                  style={{ left: clip.start * zoom, width: clipWidth }}
                  aria-pressed={selected === clip.id}
                  aria-label={`片段：${asset?.name || clip.text}`}
                  title={asset?.name || clip.text}
                  onClick={(event) => {
                    event.stopPropagation()
                    select(clip.id)
                    seek(clip.start)
                  }}
                  onDoubleClick={(event) => {
                    event.stopPropagation()
                    openFullscreen()
                  }}
                >
                  {frames.length ? (
                    <span className="se-node-filmstrip" aria-hidden="true">
                      {Array.from({ length: frameCount }, (_, i) => (
                        <img key={i} src={frames[i % frames.length]} alt="" draggable={false} loading="lazy" />
                      ))}
                    </span>
                  ) : null}
                  <span className="se-node-clip-name">
                    {clip.track === "text" ? clip.text : timecode(clip.duration, doc.settings.fps).slice(0, director ? 8 : 5)}
                  </span>
                </button>
              )
            })}
            {emptyDoc && (
              <span className="se-node-lane-empty is-clickable" onClick={openFullscreen} role="button" tabIndex={0} aria-label="添加素材到时间线">
                <Plus size={13} /> {variant === "canvas" ? "添加素材到时间线" : "添加素材"}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className={`se-node-status${saveError ? " is-error" : ""}`} role="status">
        <span>{saveError || saveState}</span>
        {job && ["queued", "running"].includes(job.status) && <span>导出中 {Math.round(job.progress)}%</span>}
        {job?.status === "completed" && job.result_url && (
          <Button type="link" size="small" className="nodrag nopan" href={job.result_url} target="_blank" rel="noopener noreferrer">打开成片</Button>
        )}
        {job?.status === "failed" && <span>导出失败：{job.error_message || "请重试"}</span>}
      </div>
    </div>
    {/* 播放预览渲染在卡片外：.se-node-card 的 overflow:hidden 会把浮在卡片上方的预览整个裁掉 */}
    {playing && doc.clips.length ? <MiniStage doc={doc} time={time} volume={volume} onProbe={probeAsset} /> : null}
    </>
  )
}

/** 无限画布「时间线」节点：通用节点注册表入口（node-registry → timeline）。 */
export function TimelineCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const context = useEditingNodeContext()
  const title = data.label || "时间线"
  if (!context)
    return (
      <div className="se-node-card" aria-label={title}>
        <div className="se-node-heading"><strong><Clock size={13} />{title}</strong></div>
        <div className="se-node-status">时间线宿主未就绪，请重新打开画布</div>
      </div>
    )
  return (
    <>
      <NodeResizer isVisible={selected} minWidth={520} minHeight={190} lineClassName={NODE_RESIZE_LINE} handleClassName={NODE_RESIZE_HANDLE} />
      <NodeFloatingToolbar id={id} type="timeline" data={data} selected={selected} />
      <div className={`se-node-host${selected ? " is-selected" : ""}`}>
        <TimelineNodeCard
          csrfToken={context.csrfToken}
          scopeProjectId={context.scopeProjectId(id)}
          sequence={context.sequenceFor(id)}
          title={title}
          titleIcon={<Clock size={13} />}
          variant="canvas"
          openFullscreen={() => context.openFullscreen(id)}
        />
        <CanvasPort type="target" id="in" aria-label="输入" />
        <CanvasPort type="source" id="out" aria-label="输出" />
      </div>
    </>
  )
}
