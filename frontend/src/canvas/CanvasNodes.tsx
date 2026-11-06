import {
  Handle, NodeResizer, NodeToolbar, Position, useReactFlow, type NodeProps,
} from "@xyflow/react"
import { Button, Input, Tooltip } from "antd"
import {
  ChevronLeft, ChevronRight, CircleHelp, Download, Image as ImageIcon,
  LoaderCircle, MoreHorizontal, Play, Plus, TriangleAlert, Type, Video,
} from "lucide-react"
import { useContext, useEffect, useState } from "react"
import type { CanvasNode } from "./canvas-model"
import { readCanvasCover, requestCanvasCoverCapture } from "./canvas-cover"
import { CanvasGeneratorComposer } from "./CanvasGeneratorComposer"
import { canvasMediaTime } from "./canvas-composer"
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
  ConnectedHandle,
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

export function TextCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const { updateNodeData } = useReactFlow()
  const actions = useContext(CanvasNodeActionsContext)
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
      <div className={`canvas-node canvas-node-text ${selected ? "is-selected" : ""}`}>
        <div className="canvas-node-title"><span className="canvas-node-type-icon is-text"><Type size={14} /></span><strong>{data.label || "文字"}</strong><Button type="text" className="canvas-node-more nodrag nopan" size="small" icon={<MoreHorizontal size={20} />} aria-label="文字节点设置" onClick={() => actions.openProperties(id)} /></div>
        <Input.TextArea
          className="canvas-text-input nodrag nopan nowheel"
          id={`canvas-text-${id}`}
          name={`canvas-text-${id}`}
          aria-label={data.label || "文字内容"}
          value={data.text ?? ""}
          placeholder="输入文字…"
          onChange={(event) => updateNodeData(id, { text: event.target.value })}
          onPointerDown={(event) => event.stopPropagation()}
        />
        <ConnectedHandle type="source" position={Position.Right} id="out" className="canvas-handle canvas-handle-text" />
      </div>
    </>
  )
}

export function ImageCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const openPreview = useContext(CanvasMediaPreviewContext)
  const url = data.url ?? ""
  const [loadFailed, setLoadFailed] = useState(false)
  useEffect(() => { setLoadFailed(false) }, [url])
  const actions = useContext(CanvasNodeActionsContext)
  const previewable = Boolean(url) && !loadFailed
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
        className={`canvas-node canvas-node-image ${selected ? "is-selected" : ""}`}
        title={previewable ? "双击预览图片" : undefined}
        onDoubleClick={previewable ? (event) => {
          event.stopPropagation()
          openPreview({ url, label: data.label, kind: "image" })
        } : undefined}
      >
        <div className="canvas-node-title"><span className="canvas-node-type-icon is-image"><ImageIcon size={14} /></span><strong title={data.label}>{data.label || "图片"}</strong><Button type="text" className="canvas-node-more nodrag nopan" size="small" icon={<MoreHorizontal size={20} />} aria-label="图片节点设置" onClick={() => actions.openProperties(id)} /></div>
        <div className="canvas-media-body">
        {previewable ? (
          <img src={url} alt={data.label || "画布图片"} draggable={false} onError={() => setLoadFailed(true)} />
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
        <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle canvas-handle-image" />
        <ConnectedHandle type="source" position={Position.Right} id="out" className="canvas-handle canvas-handle-image" />
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
        className={`canvas-node canvas-node-video ${selected ? "is-selected" : ""}`}
        onDoubleClick={playable ? (event) => {
          event.stopPropagation()
          openVideo()
        } : undefined}
      >
        <div className="canvas-node-title"><span className="canvas-node-type-icon is-video"><Video size={14} /></span><strong title={data.label}>{data.label || "视频"}</strong><span className="canvas-node-type-name">视频</span></div>
        <div className="canvas-media-body">
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
        <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle canvas-handle-video" />
        <ConnectedHandle type="source" position={Position.Right} id="out" className="canvas-handle canvas-handle-video" />
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
  const { updateNodeData } = useReactFlow()
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
  const summary = generatorParameterSummary(mode, generatorOptionValues(mode, data.optionValues))
  const history = canvasResultHistory(data)
  const versionIndex = canvasResultVersionIndex(data)
  const resultUrl = result?.url ?? ""
  const [resultFailed, setResultFailed] = useState(false)
  const [duration, setDuration] = useState<number | null>(null)
  useEffect(() => { setResultFailed(false); setDuration(null) }, [resultUrl])
  const error = live?.error || data.jobError
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
      <div className="canvas-generator-shell">
        <div className={`canvas-node canvas-node-generator ${selected ? "is-selected" : ""}`} title={result && !resultFailed ? "双击预览生成结果" : undefined}
          onDoubleClick={(event) => { event.stopPropagation(); preview() }}>
          <div className="canvas-node-title">
            <span className="canvas-node-type-icon is-generator">{kind === "video" ? <Video size={15} /> : <ImageIcon size={15} />}</span>
            <strong title={label}>{label}</strong>
            <span className={`canvas-generator-status is-${status === "partial" ? "warning" : canvasJobStatusTone(status)}`}>
              {active && status !== "awaiting_refine" ? <LoaderCircle size={12} className="animate-spin" /> : <span className="canvas-status-dot" />}
              {canvasJobStatusLabel(status)}{status === "partial" && live?.requestedCount ? ` ${live.completedCount}/${live.requestedCount}` : ""}
            </span>
          </div>
          <div className="canvas-generator-media">
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
              <div className={`canvas-generator-empty${status === "failed" ? " is-error" : ""}`}>
                {status === "failed" ? <TriangleAlert size={28} /> : active ? <LoaderCircle size={27} className="animate-spin" /> : kind === "video" ? <Video size={30} /> : <ImageIcon size={30} />}
                <strong>{status === "queued" ? "正在等待处理" : status === "running" ? "正在生成" : status === "awaiting_refine" ? "等待一采预览" : status === "failed" ? "生成未完成，请重试" : status === "cancelled" || status === "interrupted" ? canvasJobStatusLabel(status) : "待生成"}</strong>
                {!active && status !== "failed" ? <small>{selected ? "在下方填写提示词并生成" : "选中节点，开始创作"}</small> : null}
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
          <ConnectedHandle type="target" position={Position.Left} id="prompt" className="canvas-handle canvas-handle-text canvas-prompt-handle" title="提示词输入" />
          <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle canvas-handle-image canvas-reference-handle" title="参考图输入" />
          <ConnectedHandle type="source" position={Position.Right} id="out" className={`canvas-handle canvas-handle-${kind === "video" ? "video" : "generator"}`} />
        </div>
        {selected ? <NodeToolbar position={Position.Bottom} offset={12} isVisible className="canvas-composer-anchor">
          <CanvasGeneratorComposer id={id} data={data} generator={generator} actions={actions} />
        </NodeToolbar> : null}
      </div>
    </>
  )
}

export function UnknownCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const originalType = data.originalType || "unknown"
  return (
    <>
      <NodeFloatingToolbar id={id} type="unknown" data={data} selected={selected} />
      <div className={`canvas-node canvas-node-unknown ${selected ? "is-selected" : ""}`}>
        <div className="canvas-node-badge"><CircleHelp size={12} />未识别节点</div>
        <div className="canvas-unknown-body">
          <TriangleAlert size={22} />
          <strong>{data.label || originalType}</strong>
          <span>类型「{originalType}」由更新版本创建</span>
          <small>节点内容已保留，升级工作台后可继续编辑。</small>
        </div>
        <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle" />
        <ConnectedHandle type="source" position={Position.Right} id="out" className="canvas-handle" />
      </div>
    </>
  )
}
