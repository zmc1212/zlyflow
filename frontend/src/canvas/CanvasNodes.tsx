import {
  NodeResizer, useReactFlow, useUpdateNodeInternals, type NodeProps,
} from "@xyflow/react"
import { Button, Input, Popover, Tooltip } from "antd"
import {
  AudioLines, ChevronLeft, ChevronRight, CircleHelp, Download, Image as ImageIcon,
  LoaderCircle, MoreHorizontal, Music, Play, Plus, TriangleAlert, Type, Video,
} from "lucide-react"
import { useContext, useEffect, useRef, useState, type SyntheticEvent } from "react"
import { CANVAS_TEXT_MAX_ROWS, canvasNodeSize, type CanvasNode } from "./canvas-model"
import { readCanvasCover, requestCanvasCoverCapture } from "./canvas-cover"
import {
  CANVAS_GENERATOR_CHROME_HEIGHT,
  CANVAS_IMAGE_CHROME_HEIGHT,
  canvasFrameSize,
  generatorFrameRatio,
} from "./canvas-frame"
import { canvasMediaTime } from "./canvas-composer"
import {
  canvasAudioTitle,
  type CanvasAudioMode,
} from "./canvas-audio"
import {
  canvasJobStatusLabel,
  canvasJobStatusTone,
  canvasResultHistory,
  canvasResultVersionIndex,
  generatorOptionValues,
  generatorParameterSummary,
  displayedGeneratorResult,
  isCanvasJobActive,
  selectCanvasResultVersion,
} from "./canvas-generation"
import {
  CanvasGeneratorContext,
  CanvasMediaPreviewContext,
  CanvasNodeActionsContext,
  CanvasPort,
  NodeFloatingToolbar,
  NODE_RESIZE_HANDLE,
  NODE_RESIZE_LINE,
} from "./node-primitives"

// 上下文与原语已迁至 ./node-primitives（单一来源）；此处回传以保持既有 import 路径不变。
export {
  CanvasGeneratorContext,
  CanvasMediaPreviewContext,
  CanvasNodeActionsContext,
} from "./node-primitives"
export type {
  CanvasGeneratorContextValue,
  CanvasMediaPreview,
  CanvasNodeActions,
} from "./node-primitives"

const resizeLine = NODE_RESIZE_LINE
const resizeHandle = NODE_RESIZE_HANDLE

function CanvasMenuPort({ nodeId, direction = "out", opensMenu = true }: {
  nodeId: string
  direction?: "in" | "out"
  opensMenu?: boolean
}) {
  const { openConnectMenu } = useContext(CanvasNodeActionsContext)
  const type = direction === "out" ? "source" : "target"
  return opensMenu ? (
    <CanvasPort type={type} id={direction} role="button" tabIndex={0} aria-label={direction === "out" ? "添加下游节点" : "添加上游节点"} aria-haspopup="menu"
      onClick={(event) => { event.stopPropagation(); openConnectMenu(nodeId, event.currentTarget, direction) }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return
        event.preventDefault()
        event.stopPropagation()
        openConnectMenu(nodeId, event.currentTarget, direction)
      }} />
  ) : <CanvasPort type={type} id={direction} aria-label={direction === "out" ? "输出" : "输入"} />
}

export function TextCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const { getNode, updateNodeData } = useReactFlow()
  const actions = useContext(CanvasNodeActionsContext)
  // 手动 resize 过的节点保留固定高度（内容溢出时底部渐隐提示）；
  // 未设高度的节点让内容自适应撑开，避免长文本（如剧本节点）被无提示地硬裁。
  const node = getNode(id)
  const fixedHeight = Boolean(node?.height || node?.style?.height)
  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={180}
        minHeight={90}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <NodeFloatingToolbar id={id} type="text" data={data} selected={selected} />
      <div className={`canvas-node canvas-card canvas-node-text ${selected ? "is-selected" : ""}${fixedHeight ? " is-fixed-height" : ""}`}>
        <div className="canvas-card-heading"><span className="canvas-card-label"><Type size={14} /><strong>{data.label || "文字"}</strong></span><Button type="text" className="canvas-node-more nodrag nopan" size="small" icon={<MoreHorizontal size={15} />} aria-label="文字节点设置" onClick={() => actions.openProperties(id)} /></div>
        <Input.TextArea
          className="canvas-text-input nodrag nopan nowheel"
          id={`canvas-text-${id}`}
          name={`canvas-text-${id}`}
          aria-label={data.label || "文字内容"}
          value={data.text ?? ""}
          placeholder="输入文字…"
          autoSize={fixedHeight ? false : { minRows: 2, maxRows: CANVAS_TEXT_MAX_ROWS }}
          onChange={(event) => updateNodeData(id, { text: event.target.value })}
          onPointerDown={(event) => event.stopPropagation()}
        />
        <CanvasMenuPort nodeId={id} direction="in" />
        <CanvasMenuPort nodeId={id} />
      </div>
    </>
  )
}

export function ImageCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const { getNode, setNodes } = useReactFlow<CanvasNode>()
  const updateNodeInternals = useUpdateNodeInternals()
  const openPreview = useContext(CanvasMediaPreviewContext)
  const url = data.url ?? ""
  const [loadFailed, setLoadFailed] = useState(false)
  useEffect(() => { setLoadFailed(false) }, [url])
  const actions = useContext(CanvasNodeActionsContext)
  const previewable = Boolean(url) && !loadFailed
  const [hoverPreviewOpen, setHoverPreviewOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  // 图片节点跟随素材自身比例：插入 9:16 的成片时不应被塞进 16:10 的默认框里裁掉。
  const fitFrameToImage = (event: SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget
    const naturalRatio = image.naturalWidth / image.naturalHeight
    if (!Number.isFinite(naturalRatio) || naturalRatio <= 0) return
    const applied = typeof data.frameRatio === "number" && Number.isFinite(data.frameRatio) ? data.frameRatio : null
    if (applied !== null && Math.abs(applied - naturalRatio) <= 0.005) return
    const root = rootRef.current
    const body = bodyRef.current
    const chrome = root && body && root.offsetHeight > body.offsetHeight
      ? root.offsetHeight - body.offsetHeight
      : CANVAS_IMAGE_CHROME_HEIGHT
    const node = getNode(id)
    const size = canvasFrameSize({
      ratio: naturalRatio,
      width: node ? canvasNodeSize(node).width : 320,
      chromeHeight: chrome,
      minWidth: 160,
    })
    setNodes((nodes) => nodes.map((item) => (item.id === id
      ? { ...item, style: { ...item.style, width: size.width, height: size.height }, data: { ...item.data, frameRatio: naturalRatio } }
      : item)))
    updateNodeInternals(id)
  }

  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={120}
        minHeight={80}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <NodeFloatingToolbar id={id} type="image" data={data} selected={selected} />
      <div
        ref={rootRef}
        className={`canvas-node canvas-card canvas-node-image ${selected ? "is-selected" : ""}`}
        title={previewable ? "双击预览图片" : undefined}
        onDoubleClick={previewable ? (event) => {
          event.stopPropagation()
          openPreview({ url, label: data.label, kind: "image" })
        } : undefined}
      >
        <div className="canvas-card-heading"><span className="canvas-card-label"><ImageIcon size={14} /><strong title={data.label}>{data.label || "图片"}</strong></span><Button type="text" className="canvas-node-more nodrag nopan" size="small" icon={<MoreHorizontal size={15} />} aria-label="图片节点设置" onClick={() => actions.openProperties(id)} /></div>
        <div className="canvas-media-body canvas-media-frame" ref={bodyRef}>
          {previewable ? (
            <Popover trigger="hover" placement="right" arrow={false} mouseEnterDelay={0.35} mouseLeaveDelay={0.08}
              open={hoverPreviewOpen && previewable && !selected}
              onOpenChange={setHoverPreviewOpen}
              classNames={{ root: "canvas-popover canvas-image-hover" }}
              content={<figure className="canvas-image-hover-card">
                <img src={url} alt={data.label || "画布图片"} draggable={false} />
                <figcaption>{data.label || "图片"}</figcaption>
              </figure>}>
              <img src={url} alt={data.label || "画布图片"} draggable={false} onLoad={fitFrameToImage} onError={() => setLoadFailed(true)} />
            </Popover>
          ) : (
            <div className="canvas-image-placeholder">
              {loadFailed ? <TriangleAlert size={28} /> : data.pendingGeneratorId ? <LoaderCircle size={24} className="animate-spin" /> : <ImageIcon size={28} />}
              <span>{loadFailed ? "素材无法加载" : data.pendingGeneratorId ? "等待生成" : "尚未选择图片"}</span>
              {loadFailed ? <small>地址可能已过期</small> : data.pendingGeneratorId ? <small>等待上游生成完成，自动填入</small> : null}
            </div>
          )}
        </div>
        {previewable ? <Button type="default" size="small" className="canvas-media-preview-button nodrag nopan" icon={<ImageIcon size={13} />} onClick={() => openPreview({ url, label: data.label, kind: "image" })}>放大预览</Button> : null}
        {!previewable && !data.pendingGeneratorId ? <div className="canvas-media-empty-actions nodrag nopan">
          {!loadFailed ? <Button size="small" onClick={() => actions.chooseMedia(id, "image")}>从作品库选择</Button> : null}
          <Button size="small" onClick={() => actions.openProperties(id)}>{loadFailed ? "查看节点属性" : "填写图片地址"}</Button>
        </div> : <div className="canvas-media-caption" title={data.caption}>{data.caption || "图片"}</div>}
        <CanvasPort type="target" id="in" aria-label="输入" />
        <CanvasMenuPort nodeId={id} opensMenu={Boolean(url || data.assetPath || data.pendingGeneratorId)} />
      </div>
    </>
  )
}

export function VideoCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const openPreview = useContext(CanvasMediaPreviewContext)
  const actions = useContext(CanvasNodeActionsContext)
  const { updateCover } = actions
  const url = data.url ?? ""
  const cover = readCanvasCover(data)
  const [loadFailed, setLoadFailed] = useState(false)
  const [duration, setDuration] = useState<number | null>(null)
  useEffect(() => { setLoadFailed(false) }, [url])
  useEffect(() => {
    if (!url || cover) return
    let cancelled = false
    requestCanvasCoverCapture(url).then((capture) => {
      if (cancelled || !capture) return
      updateCover(id, { cover: capture.cover, coverSource: url, coverTime: Math.round(capture.time * 100) / 100 })
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [cover, id, updateCover, url])
  const playable = Boolean(url) && !loadFailed
  const openVideo = () => {
    if (playable) openPreview({ url, label: data.label, kind: "video", poster: cover ?? undefined })
  }
  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={140}
        minHeight={90}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <NodeFloatingToolbar id={id} type="video" data={data} selected={selected} />
      <div
        className={`canvas-node canvas-card canvas-node-video ${selected ? "is-selected" : ""}`}
        onDoubleClick={playable ? (event) => {
          event.stopPropagation()
          openVideo()
        } : undefined}
      >
        <div className="canvas-card-heading"><span className="canvas-card-label"><Video size={14} /><strong title={data.label}>{data.label || "视频"}</strong></span></div>
        <div className="canvas-media-body canvas-media-frame">
        {playable ? (
          <video
            src={url}
            poster={cover ?? undefined}
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={data.label || "画布视频"}
            draggable={false}
            onError={() => setLoadFailed(true)}
            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
          />
        ) : (
          <div className="canvas-image-placeholder">
            {loadFailed ? <TriangleAlert size={28} /> : data.pendingGeneratorId ? <LoaderCircle size={24} className="animate-spin" /> : <Video size={28} />}
            <span>{loadFailed ? "素材无法加载" : data.pendingGeneratorId ? "等待生成" : "尚未选择视频"}</span>
            {loadFailed ? <small>地址可能已过期</small> : data.pendingGeneratorId ? <small>等待上游生成完成，自动填入</small> : null}
          </div>
        )}
        </div>
        {!playable && !data.pendingGeneratorId ? <div className="canvas-media-empty-actions nodrag nopan">
          {!loadFailed ? <Button size="small" onClick={() => actions.chooseMedia(id, "video")}>从作品库选择</Button> : null}
          <Button size="small" onClick={() => actions.openProperties(id)}>{loadFailed ? "查看节点属性" : "填写视频地址"}</Button>
        </div> : <div className="canvas-media-caption" title={data.caption}>{data.caption || "视频"}{playable && canvasMediaTime(duration) ? ` · ${canvasMediaTime(duration)}` : ""}</div>}
        {playable ? (
          <Button
            type="text"
            className="canvas-video-play nodrag"
            aria-label="播放视频"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              openVideo()
            }}
          >
            <Play size={22} fill="currentColor" />
          </Button>
        ) : null}
        <CanvasPort type="target" id="in" aria-label="输入" />
        <CanvasMenuPort nodeId={id} />
      </div>
    </>
  )
}

export function AudioCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const actions = useContext(CanvasNodeActionsContext)
  const mode: CanvasAudioMode = data.audioMode === "music" ? "music" : "tts"
  const status = String(data.jobStatus ?? "")
  const active = isCanvasJobActive(status)
  const resultUrl = data.resultUrl ?? ""
  const error = String(data.jobError ?? "")

  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={200}
        minHeight={200}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <div className={`canvas-node canvas-card canvas-node-audio ${selected ? "is-selected" : ""}`}>
        <div className="canvas-card-heading">
          <span className="canvas-card-label">{mode === "music" ? <Music size={14} /> : <AudioLines size={14} />}<strong>{canvasAudioTitle(data.label, mode)}</strong></span>
          <Button
            type="text"
            className="canvas-node-more nodrag nopan"
            size="small"
            icon={<MoreHorizontal size={15} />}
            aria-label="音频节点设置"
            onClick={() => actions.openProperties(id)}
          />
        </div>
        <div className={`canvas-media-frame canvas-audio-preview${active ? " is-generating" : ""}`} aria-label={resultUrl ? "音频预览" : active ? "正在生成音频" : "等待生成音频"}>
          <div className="canvas-audio-symbol" aria-hidden="true">{error && !active ? <TriangleAlert size={22} /> : mode === "music" ? <Music size={22} /> : <AudioLines size={22} />}</div>
          {active ? (
            <div className="canvas-audio-status" role="status">
              <LoaderCircle className="canvas-spin" size={13} />
              <span>{status === "queued" ? "排队中" : canvasJobStatusLabel(status)}</span>
              {typeof data.jobProgress === "number" && Number.isFinite(data.jobProgress) ? <span>{Math.round(data.jobProgress)}%</span> : null}
            </div>
          ) : null}
          {resultUrl ? (
            <audio className="canvas-audio-player nodrag nopan nowheel" src={resultUrl} controls preload="metadata" />
          ) : null}
          {error && !active ? <div className="canvas-audio-error" title={error} role="status">生成失败，选中节点后重试</div> : null}
        </div>
        <CanvasMenuPort nodeId={id} direction="in" />
        <CanvasMenuPort nodeId={id} />
      </div>
    </>
  )
}

export function ArtboardCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const { updateNodeData } = useReactFlow()
  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={240}
        minHeight={160}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <NodeFloatingToolbar id={id} type="artboard" data={data} selected={selected} />
      <div className={`canvas-node canvas-node-artboard ${selected ? "is-selected" : ""}`}>
        <div className="canvas-artboard-title">
          <Input
            variant="borderless"
            className="nodrag nopan"
            value={data.label ?? "画板"}
            id={`canvas-artboard-${id}`}
            name={`canvas-artboard-${id}`}
            aria-label="画板名称"
            onChange={(event) => updateNodeData(id, { label: event.target.value })}
            onPointerDown={(event) => event.stopPropagation()}
          />
        </div>
      </div>
    </>
  )
}

export function GeneratorCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const { updateNodeData, getNode, setNodes } = useReactFlow<CanvasNode>()
  const updateNodeInternals = useUpdateNodeInternals()
  const generator = useContext(CanvasGeneratorContext)
  const actions = useContext(CanvasNodeActionsContext)
  const openPreview = useContext(CanvasMediaPreviewContext)
  const live = generator.liveFor(data.jobId)
  const status = live?.status ?? data.jobStatus ?? null
  const result = displayedGeneratorResult(data, live)
  const active = isCanvasJobActive(status)
  const progress = typeof live?.progress === "number" ? Math.max(0, Math.min(100, live.progress)) : null
  const mode = generator.modeFor(data.workflowId)
  const kind = mode?.media_type ?? data.resultKind ?? "image"
  const values = generatorOptionValues(mode, data.optionValues)
  const summary = generatorParameterSummary(mode, values)
  const frameRatio = generatorFrameRatio(mode, values)
  const appliedFrameRatio = typeof data.frameRatio === "number" && Number.isFinite(data.frameRatio) ? data.frameRatio : null
  const shellRef = useRef<HTMLDivElement>(null)
  const mediaRef = useRef<HTMLDivElement>(null)

  // 画幅框跟随参数：改 9:16 的同一帧内把节点变成竖框，而不是等生成返回。
  // frameRatio 记录「当前框体现的比例」，因此用户手动拉过尺寸的节点在重载后不会被强行纠正。
  useEffect(() => {
    if (!frameRatio) return
    if (appliedFrameRatio !== null && Math.abs(appliedFrameRatio - frameRatio) <= 0.005) return
    const shell = shellRef.current
    const media = mediaRef.current
    const chrome = shell && media && shell.offsetHeight > media.offsetHeight
      ? shell.offsetHeight - media.offsetHeight
      : CANVAS_GENERATOR_CHROME_HEIGHT
    const node = getNode(id)
    const size = canvasFrameSize({
      ratio: frameRatio,
      width: node ? canvasNodeSize(node).width : 400,
      chromeHeight: chrome,
    })
    setNodes((nodes) => nodes.map((item) => (item.id === id
      ? { ...item, style: { ...item.style, width: size.width, height: size.height }, data: { ...item.data, frameRatio } }
      : item)))
    updateNodeInternals(id)
  }, [appliedFrameRatio, frameRatio, getNode, id, setNodes, updateNodeInternals])
  const history = canvasResultHistory(data)
  const versionIndex = canvasResultVersionIndex(data)
  const resultUrl = result?.url ?? ""
  const [resultFailed, setResultFailed] = useState(false)
  const [duration, setDuration] = useState<number | null>(null)
  useEffect(() => { setResultFailed(false); setDuration(null) }, [resultUrl])
  const error = live?.error || data.jobError
  const unsuccessful = status === "failed" || status === "interrupted"
  const partialResults = status === "partial" ? live?.results : null
  const label = !data.label || data.label === "生成" || data.label === "画面生成"
    ? kind === "video" ? "视频生成" : "图片生成" : data.label
  const preview = () => {
    if (result && !resultFailed) openPreview({ url: result.url, label: result.label || label, kind: result.kind })
  }
  const selectVersion = (index: number) => {
    const patch = selectCanvasResultVersion(data, index)
    if (patch) updateNodeData(id, patch)
  }
  return (
    <>
      <NodeResizer isVisible={selected} minWidth={280} minHeight={200} lineClassName={resizeLine} handleClassName={resizeHandle} />
      <NodeFloatingToolbar id={id} type="generator" data={data} selected={selected} />
      <div className="canvas-generator-shell" ref={shellRef}>
        <div className={`canvas-node canvas-card canvas-node-generator ${selected ? "is-selected" : ""}`} title={result && !resultFailed ? "双击预览生成结果" : undefined}
          onDoubleClick={(event) => { event.stopPropagation(); preview() }}>
          <div className="canvas-card-heading">
            <span className="canvas-card-label">{kind === "video" ? <Video size={14} /> : <ImageIcon size={14} />}<strong title={label}>{label}</strong></span>
            <span className={`canvas-generator-status is-${status === "partial" ? "warning" : canvasJobStatusTone(status)}`}>
              {active && status !== "awaiting_refine" ? <LoaderCircle size={12} className="animate-spin" /> : <span className="canvas-status-dot" />}
              {canvasJobStatusLabel(status)}{status === "partial" && live?.requestedCount ? ` ${live.completedCount}/${live.requestedCount}` : ""}
            </span>
          </div>
          <div className="canvas-generator-media canvas-media-frame" ref={mediaRef}>
            {partialResults?.length ? <div className="canvas-partial-results" aria-label="部分完成的生成结果">
              {Array.from({ length: Math.min(4, live?.requestedCount || partialResults.length) }, (_, index) => {
                const entry = partialResults[index]
                return entry ? <Button type="text" key={index} className={`canvas-partial-result${result?.url === entry.url ? " is-selected" : ""}`} aria-label={`查看已完成结果 ${index + 1}`}
                  onClick={() => selectVersion(history.findIndex((version) => version.url === entry.url))}
                  onDoubleClick={(event) => { event.stopPropagation(); openPreview({ url: entry.url, kind: entry.kind, label: entry.label }) }}>
                  {entry.kind === "video" ? <video src={entry.url} muted preload="metadata" /> : <img src={entry.url} alt={`已完成结果 ${index + 1}`} />}
                  <span className="canvas-partial-result-status">已完成</span>
                </Button> : <div key={index} className="canvas-partial-result is-failed"><ImageIcon size={22} /><span>生成失败</span></div>
              })}
            </div> : result ? resultFailed ? (
              <div className="canvas-generator-empty is-error"><TriangleAlert size={26} /><strong>结果素材无法加载</strong><small>可能已过期，可在属性中核对来源任务</small></div>
            ) : result.kind === "video" ? (
              <video src={result.url} muted playsInline preload="metadata" draggable={false} onError={() => setResultFailed(true)} onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)} />
            ) : <img src={result.url} alt={result.label || "生成结果"} draggable={false} onError={() => setResultFailed(true)} /> : (
              <div className={`canvas-generator-empty${unsuccessful ? " is-error" : ""}`}>
                {unsuccessful ? <TriangleAlert size={28} /> : active ? <LoaderCircle size={27} className="animate-spin" /> : kind === "video" ? <Video size={30} /> : <ImageIcon size={30} />}
                <strong>{status === "queued" ? "正在等待处理" : status === "running" ? "正在生成" : status === "awaiting_refine" ? "等待一采预览" : status === "failed" ? "生成未完成，请重试" : status === "cancelled" || status === "interrupted" ? canvasJobStatusLabel(status) : "待生成"}</strong>
                {unsuccessful && error ? (
                  <small className="canvas-generator-empty-error" title={error}>{error}</small>
                ) : status === null ? <small>{selected ? "在下方填写提示词并生成" : "选中节点，开始创作"}</small> : null}
              </div>
            )}
            {result && result.kind === "video" && !resultFailed ? <Button type="text" className="canvas-generator-play nodrag nopan" aria-label="播放生成视频" icon={<Play size={22} fill="currentColor" />} onClick={preview} /> : null}
            {result && canvasMediaTime(duration) ? <span className="canvas-media-time">{canvasMediaTime(duration)}</span> : null}
            {active && status !== "awaiting_refine" ? <div className="canvas-media-progress">
              <span>{status === "queued" ? "排队中" : `生成中${progress === null ? "" : ` ${Math.round(progress)}%`}`}{result ? " · 当前显示历史结果" : ""}</span>
              <div className="canvas-generator-progress" role="progressbar" aria-label="生成进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined}>
                <span className={progress === null ? "is-indeterminate" : undefined} style={{ width: `${progress === null ? 12 : progress}%` }} />
              </div>
            </div> : null}
          </div>
          <div className="canvas-generator-footer nodrag nopan" onPointerDown={(event) => event.stopPropagation()}>
            {history.length > 1 ? <div className="canvas-generator-versions" aria-label="生成结果版本">
              <Button type="text" size="small" icon={<ChevronLeft size={12} />} aria-label="上一个生成版本" disabled={versionIndex <= 0} onClick={() => selectVersion(versionIndex - 1)} />
              <span>{versionIndex + 1} / {history.length}</span>
              <div className="canvas-generator-version-thumbnails">
                {history.map((entry, index) => <Button type="text" key={`${entry.url}-${index}`} className={index === versionIndex ? "is-active" : ""} aria-label={`查看生成版本 ${index + 1}`} aria-pressed={index === versionIndex} onClick={() => selectVersion(index)}>
                  {entry.kind === "image" ? <img src={entry.url} alt={`版本 ${index + 1}`} loading="lazy" draggable={false} /> : <Video size={14} />}
                </Button>)}
              </div>
              <Button type="text" size="small" icon={<ChevronRight size={12} />} aria-label="下一个生成版本" disabled={versionIndex >= history.length - 1} onClick={() => selectVersion(versionIndex + 1)} />
            </div> : <span className="canvas-generator-summary" title={summary.join(" · ")}>{mode?.name || "选择工作流"}{summary.length ? ` · ${summary.join(" · ")}` : ""}</span>}
            {result ? <div className="canvas-generator-result-actions">
              <Tooltip title="插入结果"><Button type="text" size="small" icon={<Plus size={14} />} aria-label="插入生成结果" onClick={() => generator.insertResult(id, "right")} /></Tooltip>
              <Tooltip title="下载素材"><Button type="text" size="small" icon={<Download size={14} />} aria-label="下载生成结果" onClick={() => actions.downloadNode(id)} /></Tooltip>
            </div> : null}
            {error && !active ? <Tooltip title={error}><Button type="text" size="small" className="canvas-generator-error-link" onClick={() => actions.openProperties(id)}>查看错误详情</Button></Tooltip> : null}
          </div>
          {status === "awaiting_refine" && !selected ? <div className="canvas-generator-refine-actions nodrag nopan">
            <Button type="primary" size="small" loading={generator.submitting(id)} onClick={() => generator.refine(id, "confirm")}>确认二采</Button>
            <Button size="small" disabled={generator.submitting(id)} onClick={() => generator.refine(id, "skip")}>保留一采</Button>
          </div> : null}
          <CanvasMenuPort nodeId={id} direction="in" />
          <CanvasMenuPort nodeId={id} />
        </div>
      </div>
    </>
  )
}

export function UnknownCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const originalType = data.originalType || "unknown"
  return (
    <>
      <NodeFloatingToolbar id={id} type="unknown" data={data} selected={selected} />
      <div className={`canvas-node canvas-card canvas-node-unknown ${selected ? "is-selected" : ""}`}>
        <div className="canvas-node-badge"><CircleHelp size={12} />未识别节点</div>
        <div className="canvas-unknown-body">
          <TriangleAlert size={22} />
          <strong>{data.label || originalType}</strong>
          <span>类型「{originalType}」由更新版本创建</span>
          <small>节点内容已保留，升级工作台后可继续编辑。</small>
        </div>
        <CanvasPort type="target" id="in" aria-label="输入" />
        <CanvasPort type="source" id="out" aria-label="输出" />
      </div>
    </>
  )
}
