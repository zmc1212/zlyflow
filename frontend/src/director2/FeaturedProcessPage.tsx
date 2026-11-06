// 精选作品「创作过程」只读画布：参考即梦的完整媒体发布画布。
// 优先渲染快照里冻结的真实画布草稿；没有画布时用剧本/分镜/资产合成创作流程视图。
// 整页只读：不可拖拽、不可连线、不可编辑，仅支持缩放平移与查看生成提示词；
// 「复制项目」把快照复制成自己的短剧后才能编辑。
import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Skeleton, message } from "antd"
import {
  Background,
  BackgroundVariant,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import {
  ArrowLeft,
  AudioLines,
  Clapperboard,
  Copy,
  FileText,
  Maximize,
  Play,
  Users,
  Wand2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react"
import {
  copyFeaturedWork,
  director2ErrorDetail,
  getFeaturedWork,
  type Director2FeaturedSnapshot,
} from "./api"
import { director2FeaturedPath, director2HomePath, director2ProjectPath } from "./paths"
import "./director-featured-process.css"

type ProcessNodeData = {
  kind: "prompt" | "image" | "video" | "text" | "asset" | "audio" | "episode" | "unknown"
  label?: string
  text?: string
  prompt?: string
  mediaUrl?: string
  cover?: string
  duration?: number
  camera?: string
  workflowId?: string
  optionValues?: Record<string, unknown>
  assetKind?: string
  width?: number
}

type ProcessNode = Node<ProcessNodeData>

const PROMPT_EXCERPT_CHARS = 120

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function finitePosition(value: unknown): { x: number; y: number } | null {
  const { x, y } = asRecord(value)
  if (typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y)) return { x, y }
  return null
}

/** 媒体结果类型推断：视频扩展名或 resultKind 标记按视频渲染，其余按图片。 */
function inferMediaKind(url: string | undefined, data: Record<string, unknown>): "image" | "video" {
  if (data.resultKind === "video" || data.resultKind === "editor") return "video"
  if (typeof url === "string" && /\.(mp4|webm|mov|m3u8)(\?|$)/i.test(url)) return "video"
  return "image"
}

/** 把快照冻结的真实画布草稿归一成只读展示图。 */
export function normalizeRealCanvas(snapshot: Director2FeaturedSnapshot): { nodes: ProcessNode[]; edges: Edge[]; label: string } | null {
  const canvas = snapshot.canvas
  if (!canvas?.nodes?.length) return null
  const assetById = new Map(snapshot.assets.filter(asset => asset.id).map(asset => [asset.id as string, asset]))
  const nodes: ProcessNode[] = []
  let fallbackX = 0
  for (const raw of canvas.nodes) {
    const data = asRecord(raw.data)
    const position = finitePosition(raw.position) ?? { x: fallbackX, y: 0 }
    fallbackX += 320
    const kind = String(raw.kind || raw.type || "unknown")
    const label = typeof data.label === "string" ? data.label : ""
    const url = typeof data.url === "string" && data.url ? data.url : typeof data.resultUrl === "string" ? data.resultUrl : undefined
    const width = typeof raw.style?.width === "number" && raw.style.width > 0 ? raw.style.width : undefined
    const base = { label, workflowId: typeof data.workflowId === "string" ? data.workflowId : undefined }

    let payload: ProcessNodeData
    if (kind === "asset") {
      const asset = typeof data.assetId === "string" ? assetById.get(data.assetId) : undefined
      payload = {
        kind: "asset",
        label: asset?.name || label || String(data.key || "资产"),
        assetKind: asset?.kind,
        mediaUrl: asset?.image_url || undefined,
        prompt: asset?.visual_prompt || asset?.description || "",
        width: 210,
      }
    } else if (kind === "generator" || kind === "editor") {
      payload = {
        ...base,
        kind: "prompt",
        prompt: typeof data.prompt === "string" ? data.prompt : "",
        mediaUrl: url,
        cover: typeof data.cover === "string" ? data.cover : undefined,
        optionValues: asRecord(data.optionValues),
        width: width ?? 340,
      }
    } else if (kind === "image") {
      payload = { ...base, kind: "image", mediaUrl: url, width: width ?? 280 }
    } else if (kind === "video") {
      payload = {
        ...base,
        kind: "video",
        mediaUrl: url,
        cover: typeof data.cover === "string" ? data.cover : undefined,
        duration: typeof data.duration === "number" ? data.duration : undefined,
        width: width ?? 300,
      }
    } else if (kind === "text") {
      payload = { ...base, kind: "text", text: typeof data.text === "string" ? data.text : typeof data.prompt === "string" ? data.prompt : undefined, width: width ?? 300 }
    } else if (kind === "audio") {
      payload = { ...base, kind: "audio", mediaUrl: url, width: width ?? 260 }
    } else if (kind === "artboard") {
      payload = { ...base, kind: "text", text: label, width: width ?? 420 }
    } else {
      payload = { ...base, kind: "unknown", text: typeof data.text === "string" ? data.text : undefined, width: width ?? 240 }
    }
    nodes.push({ id: raw.id, type: processNodeType(payload), position, data: payload })
  }

  const nodeIds = new Set(nodes.map(node => node.id))
  const edges: Edge[] = (canvas.edges || [])
    .filter(edge => edge && nodeIds.has(edge.source) && nodeIds.has(edge.target) && edge.source !== edge.target)
    .map((edge, index) => ({ id: edge.id || `pc-${index}`, source: edge.source, target: edge.target, type: "smoothstep" }))
  return { nodes, edges, label: "完整创作画布" }
}

/** 没有真实画布时，用快照里的资产与分镜合成创作流程视图（提示词 → 分镜图 → 成片镜头）。 */
export function synthesizeProcessGraph(snapshot: Director2FeaturedSnapshot): { nodes: ProcessNode[]; edges: Edge[]; label: string } {
  const nodes: ProcessNode[] = []
  const edges: Edge[] = []
  let edgeSeq = 0
  const link = (source: string, target: string) => { edges.push({ id: `syn-e-${edgeSeq++}`, source, target, type: "smoothstep" }) }

  const assets = snapshot.assets.filter(asset => asset.name)
  assets.forEach((asset, index) => {
    nodes.push({
      id: `syn-asset-${index}`,
      type: "process-asset",
      position: { x: index * 250, y: 0 },
      data: { kind: "asset", label: asset.name, assetKind: asset.kind, mediaUrl: asset.image_url || undefined, prompt: asset.visual_prompt || asset.description || "", width: 210 },
    })
  })

  const usedAssetIds = new Set<string>()
  let rowY = assets.length ? 300 : 60
  snapshot.episodes.forEach((episode, epIndex) => {
    nodes.push({
      id: `syn-ep-${epIndex}`,
      type: "process-episode",
      position: { x: -430, y: rowY + 120 },
      data: { kind: "episode", label: `第 ${episode.number} 集`, text: episode.title || "", mediaUrl: episode.episode_video_url || undefined, width: 200 },
    })
    let rowBottom = rowY
    episode.beats.forEach((beat, beatIndex) => {
      const x = beatIndex * 400
      const promptText = (beat.prompt || [beat.action, beat.dialogue ? `${beat.speaker || "对白"}：${beat.dialogue}` : ""].filter(Boolean).join("\n")).trim()
      const column: string[] = []
      let y = rowY
      if (promptText) {
        const id = `syn-p-${epIndex}-${beatIndex}`
        nodes.push({ id, type: "process-prompt", position: { x, y }, data: { kind: "prompt", prompt: promptText, label: beat.heading || `镜头 ${beatIndex + 1}`, camera: beat.camera, width: 340 } })
        column.push(id)
        y += 200
      }
      if (beat.image_url) {
        const id = `syn-i-${epIndex}-${beatIndex}`
        nodes.push({ id, type: "process-media", position: { x, y }, data: { kind: "image", mediaUrl: beat.image_url, label: beat.heading, width: 300 } })
        column.push(id)
        y += 240
      }
      if (beat.video_url) {
        const id = `syn-v-${epIndex}-${beatIndex}`
        nodes.push({ id, type: "process-media", position: { x, y }, data: { kind: "video", mediaUrl: beat.video_url, cover: beat.image_url || undefined, label: beat.heading || `镜头 ${beatIndex + 1}`, duration: beat.duration, width: 300 } })
        column.push(id)
        y += 240
      }
      for (let i = 1; i < column.length; i += 1) link(column[i - 1], column[i])
      rowBottom = Math.max(rowBottom, y)
    })
    rowY = (episode.beats.length ? rowBottom : rowY) + 120
  })
  return { nodes, edges, label: assets.length ? "资产与分镜创作流程" : "分镜创作流程" }
}

function processNodeType(data: ProcessNodeData): string {
  if (data.kind === "prompt") return "process-prompt"
  if (data.kind === "image" || data.kind === "video") return "process-media"
  if (data.kind === "asset") return "process-asset"
  if (data.kind === "episode") return "process-episode"
  if (data.kind === "audio") return "process-audio"
  return "process-text"
}

const NODE_TYPES: NodeTypes = {
  "process-media": ProcessMediaNode,
  "process-prompt": ProcessPromptNode,
  "process-text": ProcessTextNode,
  "process-asset": ProcessAssetNode,
  "process-episode": ProcessEpisodeNode,
  "process-audio": ProcessAudioNode,
}

/** 只读节点也需要 Handle 供连线渲染，但视觉隐藏且不可交互。 */
function InvisibleHandles() {
  return <>
    <Handle type="target" position={Position.Left} className="fpc-handle" isConnectable={false} />
    <Handle type="source" position={Position.Right} className="fpc-handle" isConnectable={false} />
  </>
}

function ProcessMediaNode({ data }: NodeProps<ProcessNode>) {
  const isVideo = data.kind === "video"
  return <div className="fpc-node fpc-media" style={{ width: data.width }}>
    <InvisibleHandles />
    <div className="fpc-media-frame">
      {isVideo
        ? data.cover
          ? <img src={data.cover} alt="" loading="lazy" />
          : <video src={data.mediaUrl} muted preload="metadata" />
        : data.mediaUrl ? <img src={data.mediaUrl} alt="" loading="lazy" /> : <Clapperboard size={22} />}
      {isVideo && <span className="fpc-media-play"><Play size={15} /></span>}
    </div>
    {(data.label || data.duration) ? <div className="fpc-media-caption"><span>{data.label}</span>{data.duration ? <em>{data.duration}s</em> : null}</div> : null}
  </div>
}

function ProcessPromptNode({ data }: NodeProps<ProcessNode>) {
  const prompt = data.prompt || ""
  const excerpt = prompt.length > PROMPT_EXCERPT_CHARS ? `${prompt.slice(0, PROMPT_EXCERPT_CHARS)}…` : prompt
  return <div className="fpc-node fpc-prompt" style={{ width: data.width }}>
    <InvisibleHandles />
    {data.mediaUrl ? <div className="fpc-prompt-thumb">{inferMediaKind(data.mediaUrl, {}) === "video" ? <video src={data.mediaUrl} muted preload="metadata" /> : <img src={data.mediaUrl} alt="" loading="lazy" />}</div> : null}
    <div className="fpc-prompt-body">
      <div className="fpc-prompt-tag"><Wand2 size={11} /> 提示词{data.label ? ` · ${data.label}` : ""}</div>
      {excerpt ? <p>{excerpt}</p> : <p className="is-empty">未记录提示词</p>}
      <div className="fpc-prompt-meta">
        {data.camera ? <em>{data.camera}</em> : null}
        <span>点击查看完整提示词</span>
      </div>
    </div>
  </div>
}

function ProcessTextNode({ data }: NodeProps<ProcessNode>) {
  return <div className="fpc-node fpc-text" style={{ width: data.width }}>
    <InvisibleHandles />
    <div className="fpc-text-tag"><FileText size={11} />{data.label || "文字"}</div>
    <p>{data.text || ""}</p>
  </div>
}

const ASSET_KIND_LABELS: Record<string, string> = { character: "角色", scene: "场景", prop: "道具" }

function ProcessAssetNode({ data }: NodeProps<ProcessNode>) {
  return <div className="fpc-node fpc-asset" style={{ width: data.width }}>
    <InvisibleHandles />
    <div className="fpc-asset-frame">{data.mediaUrl ? <img src={data.mediaUrl} alt="" loading="lazy" /> : <Users size={20} />}</div>
    <div className="fpc-asset-copy">
      <strong>{data.label}</strong>
      {data.assetKind ? <span>{ASSET_KIND_LABELS[data.assetKind] || data.assetKind}</span> : null}
    </div>
  </div>
}

function ProcessEpisodeNode({ data }: NodeProps<ProcessNode>) {
  return <div className="fpc-node fpc-episode" style={{ width: data.width }}>
    <InvisibleHandles />
    <div className="fpc-episode-tag"><Clapperboard size={12} /></div>
    <strong>{data.label}</strong>
    {data.text ? <p>{data.text}</p> : null}
    {data.mediaUrl ? <span className="fpc-episode-play"><Play size={12} /> 本集成片</span> : null}
  </div>
}

function ProcessAudioNode({ data }: NodeProps<ProcessNode>) {
  return <div className="fpc-node fpc-audio" style={{ width: data.width }}>
    <InvisibleHandles />
    <div className="fpc-audio-tag"><AudioLines size={12} />{data.label || "音频"}</div>
    {data.mediaUrl ? <audio src={data.mediaUrl} controls preload="metadata" /> : null}
  </div>
}

type PromptPanelState = { prompt: string; refs: string[]; params: string[]; title?: string }

function ZoomBar() {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  const { zoom } = useViewport()
  return <div className="fpc-zoombar">
    <button type="button" aria-label="缩小" onClick={() => void zoomOut()}><ZoomOut size={15} /></button>
    <span className="fpc-zoom-value">{Math.round(zoom * 100)}%</span>
    <button type="button" aria-label="放大" onClick={() => void zoomIn()}><ZoomIn size={15} /></button>
    <button type="button" aria-label="适应画布" onClick={() => void fitView({ padding: 0.15, duration: 300 })}><Maximize size={14} /></button>
  </div>
}

function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  return new Promise((resolve, reject) => {
    const area = document.createElement("textarea")
    area.value = text
    area.style.position = "fixed"
    area.style.opacity = "0"
    document.body.appendChild(area)
    area.select()
    try { document.execCommand("copy") ? resolve() : reject(new Error("copy failed")) }
    finally { area.remove() }
  })
}

export default function FeaturedProcessPage({ featuredId, csrfToken }: { featuredId: string; csrfToken: string }) {
  const navigate = useNavigate()
  const [panel, setPanel] = useState<PromptPanelState | null>(null)
  const [lightbox, setLightbox] = useState<{ url: string; kind: "image" | "video" } | null>(null)
  const [copying, setCopying] = useState(false)

  const query = useQuery({
    queryKey: ["director-featured-work", featuredId],
    queryFn: () => getFeaturedWork(featuredId),
    retry: false,
  })
  const work = query.data

  const graph = useMemo(() => {
    if (!work) return null
    return normalizeRealCanvas(work.snapshot) ?? synthesizeProcessGraph(work.snapshot)
  }, [work])

  const nodesById = useMemo(() => new Map((graph?.nodes ?? []).map(node => [node.id, node])), [graph])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      if (lightbox) { setLightbox(null); return }
      if (panel) setPanel(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [lightbox, panel])

  const handleNodeClick = useCallback((node: ProcessNode, edges: Edge[]) => {
    const data = node.data
    if (data.prompt) {
      const refs = edges
        .filter(edge => edge.target === node.id)
        .map(edge => nodesById.get(edge.source)?.data.mediaUrl)
        .filter((url): url is string => Boolean(url))
        .slice(0, 8)
      const params: string[] = []
      if (data.workflowId) params.push(`工作流 ${data.workflowId}`)
      for (const [key, value] of Object.entries(data.optionValues || {})) {
        if (value === "" || value == null) continue
        params.push(`${key}: ${String(value)}`)
      }
      if (data.camera) params.push(data.camera)
      setPanel({ prompt: data.prompt, refs, params, title: data.label })
      return
    }
    if (data.mediaUrl && (data.kind === "image" || data.kind === "video" || data.kind === "episode" || data.kind === "asset")) {
      setLightbox({ url: data.mediaUrl, kind: data.kind === "image" || data.kind === "asset" ? "image" : "video" })
    }
  }, [nodesById])

  async function handleCopy() {
    if (copying) return
    setCopying(true)
    try {
      const result = await copyFeaturedWork(csrfToken, featuredId)
      message.success(`已复制到我的短剧「${result.name}」，现在可以编辑了`)
      navigate(director2ProjectPath(result.project_id, "content"))
    } catch (error) {
      message.error(director2ErrorDetail(error, "复制项目失败，请重试"))
    } finally {
      setCopying(false)
    }
  }

  if (query.isLoading) {
    return <div className="fpc-page"><header className="fpc-topbar"><Skeleton active paragraph={false} title={{ width: 220 }} /></header>
      <div className="fpc-stage"><div className="fpc-loading"><Skeleton active paragraph={{ rows: 4 }} /></div></div></div>
  }
  if (query.isError || !work || !graph) {
    return <div className="fpc-page"><header className="fpc-topbar">
      <Button type="text" aria-label="返回" icon={<ArrowLeft size={16} />} onClick={() => navigate(director2FeaturedPath(featuredId))} />
      <h1>创作过程</h1>
    </header>
      <div className="fpc-stage"><div className="fpc-loading">
        <Alert type="error" showIcon title="创作过程加载失败" description="作品可能已下架，或当前登录状态已失效。" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />
      </div></div></div>
  }

  const edges = graph.edges
  return <div className="fpc-page">
    <header className="fpc-topbar">
      <div className="fpc-topbar-left">
        <Button type="text" className="fpc-back" aria-label="返回图文详情" icon={<ArrowLeft size={16} />} onClick={() => navigate(director2FeaturedPath(featuredId))} />
        <div className="fpc-title">
          <h1>{work.title}</h1>
          <span>创作过程 · {graph.label}</span>
        </div>
      </div>
      <div className="fpc-topbar-right">
        <span className="fpc-hint">当前为只读模式，如需创作请点击</span>
        <Button type="primary" className="fpc-copy" loading={copying} onClick={() => void handleCopy()}>复制项目</Button>
        <Button type="text" className="fpc-close" aria-label="关闭创作过程" icon={<X size={17} />} onClick={() => navigate(director2HomePath())} />
      </div>
    </header>
    <div className="fpc-stage">
      <ReactFlowProvider>
        <ReactFlow
          nodes={graph.nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          edgesFocusable={false}
          edgesReconnectable={false}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          minZoom={0.04}
          maxZoom={1.6}
          defaultViewport={work.snapshot.canvas?.viewport ?? undefined}
          fitView={!work.snapshot.canvas?.viewport}
          fitViewOptions={{ padding: 0.18, maxZoom: 0.85 }}
          onNodeClick={(_, node) => handleNodeClick(node as ProcessNode, edges)}
          panOnDrag
          zoomOnScroll
          preventScrolling
        >
          <Background variant={BackgroundVariant.Dots} gap={26} size={2} color="rgba(128,132,140,0.35)" />
        </ReactFlow>
        <ZoomBar />
      </ReactFlowProvider>

      {panel && <aside className="fpc-panel" role="dialog" aria-label="生成提示词">
        <header className="fpc-panel-head">
          <span><Wand2 size={14} /> 生成提示词{panel.title ? ` · ${panel.title}` : ""}</span>
          <button type="button" aria-label="关闭提示词面板" onClick={() => setPanel(null)}><X size={14} /></button>
        </header>
        {panel.refs.length ? <div className="fpc-panel-refs">{panel.refs.map((url, index) => <img key={`${url}-${index}`} src={url} alt="" loading="lazy" />)}</div> : null}
        <pre className="fpc-panel-text">{panel.prompt}</pre>
        <footer className="fpc-panel-foot">
          <span className="fpc-panel-params">{panel.params.join("  ·  ")}</span>
          <Button size="small" icon={<Copy size={12} />} onClick={() => void copyTextToClipboard(panel.prompt).then(() => void message.success("提示词已复制")).catch(() => message.error("复制失败，请手动选择文本复制"))}>复制提示词</Button>
        </footer>
      </aside>}

      {lightbox && <div className="fpc-lightbox" role="dialog" aria-label="媒体预览" onClick={() => setLightbox(null)}>
        <button type="button" className="fpc-lightbox-close" aria-label="关闭预览"><X size={18} /></button>
        {lightbox.kind === "video"
          ? <video src={lightbox.url} controls autoPlay onClick={event => event.stopPropagation()} />
          : <img src={lightbox.url} alt="" onClick={event => event.stopPropagation()} />}
      </div>}
    </div>
  </div>
}
