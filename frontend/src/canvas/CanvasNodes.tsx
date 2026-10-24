import {
  Handle, NodeResizer, NodeToolbar, Position, useNodeConnections, useReactFlow, type NodeProps,
} from "@xyflow/react"
import { Button, Dropdown, Input, Select, Tag, Tooltip } from "antd"
import {
  ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Copy, Download, Image as ImageIcon,
  LoaderCircle, MoreHorizontal, Play, Plus, Settings, Sparkles, Square, Trash2, TriangleAlert, Type, Video,
} from "lucide-react"
import { createContext, useContext, useEffect, useState, type ComponentProps } from "react"
import type { CanvasBranchDirection, CanvasCoverPatch, CanvasNode } from "./canvas-model"
import { readCanvasCover, requestCanvasCoverCapture } from "./canvas-cover"
import {
  canvasWorkflowChangePatch,
  canvasJobStatusLabel,
  canvasJobStatusTone,
  canvasPictureToken,
  canvasResultHistory,
  canvasResultVersionIndex,
  generatorOptionValues,
  generatorParameterSummary,
  generatorResultFromNodeData,
  displayedGeneratorResult,
  isCanvasJobActive,
  selectCanvasResultVersion,
  type CanvasGeneratorLive,
  type CanvasGeneratorPromptState,
  type CanvasWorkflowMode,
} from "./canvas-generation"

function ConnectedHandle(props: ComponentProps<typeof Handle>) {
  const connections = useNodeConnections({ handleType: props.type, handleId: props.id ?? undefined })
  const { getNode } = useReactFlow<CanvasNode>()
  const sourceType = props.type === "target" && connections[0] ? getNode(connections[0].source)?.type : null
  const color = sourceType === "generator" ? "var(--studio-primary)" : sourceType === "text" ? "var(--canvas-text-tone)" : sourceType === "video" ? "var(--canvas-video-tone)" : sourceType === "image" ? "var(--canvas-image-tone)" : undefined
  return <Handle {...props} style={{ ...props.style, ...(color ? { color } : {}) }} className={`${props.className ?? ""}${connections.length ? " is-connected" : ""}`} />
}

export type CanvasMediaPreview = {
  url: string
  label?: string
  kind: "image" | "video"
  poster?: string
}

export const CanvasMediaPreviewContext = createContext<(preview: CanvasMediaPreview) => void>(() => undefined)

export type CanvasGeneratorContextValue = {
  modes: CanvasWorkflowMode[]
  modesLoading: boolean
  disconnectInput: (nodeId: string, kind: "text" | "image") => void
  workflowName: (workflowId?: string) => string
  modeFor: (workflowId?: string) => CanvasWorkflowMode | null
  liveFor: (jobId?: string | null) => CanvasGeneratorLive | null
  referenceCountFor: (nodeId: string) => number
  promptInfoFor: (nodeId: string) => CanvasGeneratorPromptState
  issueFor: (nodeId: string) => string | null
  submit: (nodeId: string) => void
  cancel: (nodeId: string) => void
  refine: (nodeId: string, action: "confirm" | "skip") => void
  insertResult: (nodeId: string, direction: CanvasBranchDirection) => void
  submitting: (nodeId: string) => boolean
}

export const CanvasGeneratorContext = createContext<CanvasGeneratorContextValue>({
  modes: [],
  modesLoading: false,
  disconnectInput: () => undefined,
  workflowName: () => "未选择工作流",
  modeFor: () => null,
  liveFor: () => null,
  referenceCountFor: () => 0,
  promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
  issueFor: () => null,
  submit: () => undefined,
  cancel: () => undefined,
  refine: () => undefined,
  insertResult: () => undefined,
  submitting: () => false,
})

export type CanvasNodeActions = {
  openProperties: (nodeId: string) => void
  branchGenerate: (nodeId: string, direction: CanvasBranchDirection) => void
  duplicateNode: (nodeId: string) => void
  deleteNode: (nodeId: string) => void
  downloadNode: (nodeId: string) => void
  updateCover: (nodeId: string, patch: CanvasCoverPatch) => void
}

export const CanvasNodeActionsContext = createContext<CanvasNodeActions>({
  openProperties: () => undefined,
  branchGenerate: () => undefined,
  duplicateNode: () => undefined,
  deleteNode: () => undefined,
  downloadNode: () => undefined,
  updateCover: () => undefined,
})

const branchMenu = (onPick: (direction: CanvasBranchDirection) => void) => ({
  items: [
    { key: "right", label: "向右生成" },
    { key: "down", label: "向下生成" },
  ],
  onClick: ({ key }: { key: string }) => onPick(key === "down" ? "down" : "right"),
})

function NodeFloatingToolbar({ id, type, data, selected }: {
  id: string
  type: string
  data: CanvasNode["data"]
  selected: boolean
}) {
  const actions = useContext(CanvasNodeActionsContext)
  const generator = useContext(CanvasGeneratorContext)
  const result = generatorResultFromNodeData(data)
  const mediaUrl = type === "image" || type === "video" ? data.url : result?.url
  const canBranch = type === "text" || type === "image" || type === "generator"

  return (
    <NodeToolbar
      isVisible={selected}
      position={Position.Top}
      offset={8}
      className={`canvas-node-toolbar nodrag nopan${type === "generator" ? " is-generator" : ""}`}
    >
      {canBranch ? (
        <Dropdown classNames={{ root: "canvas-popup canvas-branch-menu" }} trigger={["click"]} menu={branchMenu((direction) => actions.branchGenerate(id, direction))}>
          <Button size="small" type="text" className="canvas-toolbar-branch" icon={<Sparkles size={15} />}>以此生成</Button>
        </Dropdown>
      ) : null}
      <span className="canvas-toolbar-divider" />

      {result ? (
        <Tooltip title="把结果插入到右侧">
          <Button
            size="small"
            type="text"
            icon={<Plus size={14} />}
            aria-label="插入生成结果"
            onClick={() => generator.insertResult(id, "right")}
          />
        </Tooltip>
      ) : null}

      <Tooltip title="节点属性">
        <Button
          size="small"
          type="text"
          icon={<Settings size={16} />}
          aria-label="节点属性"
          onClick={() => actions.openProperties(id)}
        />
      </Tooltip>
      <Tooltip title="复制节点 (Ctrl/⌘ D)">
        <Button
          size="small"
          type="text"
          icon={<Copy size={16} />}
          aria-label="复制节点"
          onClick={() => actions.duplicateNode(id)}
        />
      </Tooltip>
      {mediaUrl || type === "generator" ? (
        <Tooltip title={mediaUrl ? "下载素材" : "生成结果后可下载"}>
          <Button
            size="small"
            type="text"
            icon={<Download size={14} />}
            aria-label="下载素材"
            disabled={!mediaUrl}
            onClick={() => actions.downloadNode(id)}
          />
        </Tooltip>
      ) : null}
      <Tooltip title="删除节点 (Delete)">
        <Button
          size="small"
          type="text"
          danger
          icon={<Trash2 size={14} />}
          aria-label="删除节点"
          onClick={() => actions.deleteNode(id)}
        />
      </Tooltip>
    </NodeToolbar>
  )
}

const resizeLine = "canvas-resize-line"
const resizeHandle = "canvas-resize-handle"

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
            {loadFailed ? <TriangleAlert size={28} /> : <ImageIcon size={28} />}
            <span>{loadFailed ? "素材无法加载" : data.label || "图片占位"}</span>
            {loadFailed ? <small>地址可能已过期</small> : null}
          </div>
        )}
        </div>
        {data.caption ? <div className="canvas-media-caption" title={data.caption}>{data.caption}</div> : null}
        <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle canvas-handle-image" />
        <ConnectedHandle type="source" position={Position.Right} id="out" className="canvas-handle canvas-handle-image" />
      </div>
    </>
  )
}

export function VideoCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const openPreview = useContext(CanvasMediaPreviewContext)
  const { updateCover } = useContext(CanvasNodeActionsContext)
  const url = data.url ?? ""
  const cover = readCanvasCover(data)
  const [loadFailed, setLoadFailed] = useState(false)
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
          />
        ) : (
          <div className="canvas-image-placeholder">
            {loadFailed ? <TriangleAlert size={28} /> : <Video size={28} />}
            <span>{loadFailed ? "素材无法加载" : data.label || "视频占位"}</span>
            {loadFailed ? <small>地址可能已过期</small> : null}
          </div>
        )}
        </div>
        {data.caption ? <div className="canvas-media-caption" title={data.caption}>{data.caption}</div> : null}
        {playable ? (
          <button
            type="button"
            className="canvas-video-play nodrag"
            aria-label="播放视频"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              openVideo()
            }}
          >
            <Play size={12} />播放
          </button>
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
        <div className="canvas-artboard-title nodrag nopan">
          <Input
            variant="borderless"
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
  const {
    modes, modesLoading, disconnectInput, modeFor, liveFor, referenceCountFor, promptInfoFor, issueFor, submit, cancel, insertResult,
    submitting, refine,
  } = useContext(CanvasGeneratorContext)
  const actions = useContext(CanvasNodeActionsContext)
  const openPreview = useContext(CanvasMediaPreviewContext)
  const live = liveFor(data.jobId)
  const status = live?.status ?? data.jobStatus ?? null
  const result = displayedGeneratorResult(data, live)
  const active = isCanvasJobActive(status)
  const progress = typeof live?.progress === "number" ? Math.max(0, Math.min(100, live.progress)) : null
  const referenceCount = referenceCountFor(id)
  const promptInfo = promptInfoFor(id)
  const issue = issueFor(id)
  const tone = canvasJobStatusTone(status)
  const prompt = promptInfo.text
  const mode = modeFor(data.workflowId)
  const summary = generatorParameterSummary(mode, generatorOptionValues(mode, data.optionValues))
  const history = canvasResultHistory(data)
  const versionIndex = canvasResultVersionIndex(data)
  const resultUrl = result?.url ?? ""
  const [resultFailed, setResultFailed] = useState(false)
  useEffect(() => { setResultFailed(false) }, [resultUrl])

  const selectVersion = (nextIndex: number) => {
    const patch = selectCanvasResultVersion(data, nextIndex)
    if (patch) updateNodeData(id, patch)
  }

  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={280}
        minHeight={200}
        lineClassName={resizeLine}
        handleClassName={resizeHandle}
      />
      <NodeFloatingToolbar id={id} type="generator" data={data} selected={selected} />
      <div
        className={`canvas-node canvas-node-generator ${selected ? "is-selected" : ""}`}
        title={result && !resultFailed ? "双击预览生成结果" : undefined}
        onDoubleClick={result && !resultFailed ? (event) => {
          event.stopPropagation()
          openPreview({ url: result.url, label: result.label || data.label, kind: result.kind })
        } : undefined}
      >
        <div className="canvas-node-title"><span className="canvas-node-type-icon is-generator"><Sparkles size={20} /></span><strong title={data.label}>{!data.label || data.label === "生成" ? "画面生成" : data.label}</strong>
          <span className={`canvas-generator-status is-${tone}`}>
            {active ? <LoaderCircle size={14} className="animate-spin" /> : <span className="canvas-status-dot" />}
            {canvasJobStatusLabel(status)}
          </span>
        </div>

        <div className="canvas-generator-body nowheel">
        <div className="canvas-node-workflow-field nodrag nopan">
          <label htmlFor={`canvas-node-workflow-${id}`}>{mode?.media_type === "video" ? "视频工作流" : "图像工作流"}</label>
          <Select
            id={`canvas-node-workflow-${id}`}
            aria-label="节点生成工作流"
            classNames={{ popup: { root: "canvas-select-popup" } }}
            value={mode?.id}
            placeholder="选择工作流"
            loading={modesLoading}
            disabled={active || submitting(id)}
            options={modes.map((item) => ({ value: item.id, label: item.name }))}
            onChange={(value) => updateNodeData(id, canvasWorkflowChangePatch(value, modes.find((item) => item.id === value) ?? null))}
          />
        </div>
        {result ? (
          <div className="canvas-generator-result">
            {resultFailed ? (
              <div className="canvas-generator-media-error">
                <TriangleAlert size={20} />
                <span>结果素材无法加载</span>
                <small>可能已过期，可在属性面板核对来源任务</small>
              </div>
            ) : result.kind === "video" ? (
              <video
                src={result.url}
                muted
                loop
                playsInline
                preload="metadata"
                draggable={false}
                onError={() => setResultFailed(true)}
              />
            ) : (
              <img
                src={result.url}
                alt={result.label || "生成结果"}
                draggable={false}
                onError={() => setResultFailed(true)}
              />
            )}
            {!resultFailed ? (
              <span className="canvas-generator-result-hint">
                {result.kind === "video" ? <Video size={11} /> : <ImageIcon size={11} />}
                双击预览
              </span>
            ) : null}
            {history.length > 1 ? (
              <div className="canvas-result-version-switch nodrag nopan" onPointerDown={(event) => event.stopPropagation()}>
                <Button
                  size="small"
                  type="text"
                  className="canvas-result-version-button"
                  icon={<ChevronLeft size={12} />}
                  aria-label="上一个生成版本"
                  disabled={versionIndex <= 0}
                  onClick={(event) => {
                    event.stopPropagation()
                    selectVersion(versionIndex - 1)
                  }}
                />
                <span>{versionIndex + 1}/{history.length}</span>
                <Button
                  size="small"
                  type="text"
                  className="canvas-result-version-button"
                  icon={<ChevronRight size={12} />}
                  aria-label="下一个生成版本"
                  disabled={versionIndex >= history.length - 1}
                  onClick={(event) => {
                    event.stopPropagation()
                    selectVersion(versionIndex + 1)
                  }}
                />
              </div>
            ) : null}
          </div>
        ) : (
          <div className="canvas-node-prompt-field nodrag nopan nowheel">
            <label htmlFor={`canvas-generator-prompt-${id}`}>提示词</label>
            <Input.TextArea
              className="canvas-generator-prompt-input"
              id={`canvas-generator-prompt-${id}`}
              aria-label={promptInfo.fromTextNodes ? "来自文字节点的提示词" : "生成提示词"}
              value={promptInfo.fromTextNodes ? prompt : data.prompt ?? ""}
              readOnly={promptInfo.fromTextNodes}
              disabled={active}
              rows={4}
              maxLength={4000}
              showCount
              placeholder="描述画面、镜头与动作…"
              onChange={(event) => updateNodeData(id, { prompt: event.target.value })}
              onPointerDown={(event) => event.stopPropagation()}
            />
          </div>
        )}

        {result && prompt ? <p className="canvas-generator-prompt-caption">{prompt}</p> : null}

        <div className="canvas-generator-meta nodrag nopan" title={summary.join(" · ")}>
          {referenceCount ? <Tag closable={!active && !submitting(id)} icon={<ImageIcon size={18} />} onClose={(event) => { event.preventDefault(); disconnectInput(id, "image") }} title={`按连线顺序对应 ${canvasPictureToken(1)} 至 ${canvasPictureToken(referenceCount)}`}>{referenceCount} 张参考</Tag> : <Tag icon={<ImageIcon size={18} />}>连接参考图</Tag>}
          {promptInfo.fromTextNodes ? <Tag closable={!active && !submitting(id)} icon={<Type size={18} />} onClose={(event) => { event.preventDefault(); disconnectInput(id, "text") }}>文字已连接</Tag> : null}
        </div>

        {!active && issue ? (
          <span className="canvas-generator-warning" title={issue}>
            <TriangleAlert size={11} />{issue}
          </span>
        ) : null}

        {active ? (
          <div
            className="canvas-generator-progress"
            role="progressbar"
            aria-label="生成进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress ?? 0}
          >
            <span
              className={progress === null ? "is-indeterminate" : undefined}
              style={{ width: `${progress === null ? 8 : Math.max(4, progress)}%` }}
            />
          </div>
        ) : null}

        {!active && data.jobError ? (
          <span className="canvas-generator-error" title={data.jobError}>{data.jobError}</span>
        ) : null}

        </div>
        <div className="canvas-generator-actions nodrag nopan">
          <Tooltip title="生成设置"><Button className="canvas-generator-settings" aria-label="生成设置" icon={<Settings size={22} />} onClick={() => actions.openProperties(id)} /></Tooltip>

          {active ? (
            <Button
              size="small"
              danger
              loading={submitting(id)}
              icon={<Square size={12} />}
              onClick={() => cancel(id)}
            >
              停止
            </Button>
          ) : (
            <Button
              size="small"
              type="primary"
              icon={<Sparkles size={22} />}
              loading={submitting(id)}
              disabled={Boolean(issue)}
              title={issue ?? undefined}
              onClick={() => submit(id)}
            >
              {result ? "重新生成" : "生成"}
            </Button>
          )}
          {status === "awaiting_refine" ? (
            <Dropdown trigger={["click"]} disabled={submitting(id)} menu={{ items: [
              { key: "confirm", label: "确认二采" }, { key: "skip", label: "保留一采" },
            ], onClick: ({ key }) => refine(id, key === "confirm" ? "confirm" : "skip") }}>
              <Button size="small" type="primary" loading={submitting(id)}>确认预览<ChevronDown size={12} /></Button>
            </Dropdown>
          ) : null}
          {result ? (
            <Button
              size="small"
              type="text"
              icon={<Plus size={13} />}
              onClick={() => insertResult(id, "right")}
            >
              插入
            </Button>
          ) : null}
        </div>

        <ConnectedHandle type="target" position={Position.Left} id="prompt" className="canvas-handle canvas-handle-text canvas-prompt-handle" />
        <ConnectedHandle type="target" position={Position.Left} id="in" className="canvas-handle canvas-handle-image canvas-reference-handle" />
        <ConnectedHandle
          type="source"
          position={Position.Right}
          id="out"
          className={`canvas-handle canvas-handle-${data.resultKind === "video" ? "video" : "generator"}`}
        />
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
