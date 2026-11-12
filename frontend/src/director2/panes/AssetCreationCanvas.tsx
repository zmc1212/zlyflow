import { useEffect, useMemo, useRef, useState } from "react"
import { Background, BackgroundVariant, MiniMap, ReactFlow, ReactFlowProvider, applyEdgeChanges, applyNodeChanges, getBezierPath, Position, useReactFlow, type ConnectionLineComponentProps, type Connection, type Edge, type Node, type XYPosition } from "@xyflow/react"
import { useNavigate } from "react-router-dom"
import ThemeToggle from "../../components/ThemeToggle"
import { GeneratorOptionField } from "../../canvas/CanvasGeneratorInspector"
import CreativeStylePicker from "../CreativeStylePicker"
import CharacterDesignModal from "./assets/CharacterDesignModal"
import { assetCanvasPollingKey, moveAssetCanvasReference, canvasEditingCloudUrl, canvasWorkflowReferenceKind, assetCanvasConnectionIssue, assetCanvasNodeKind, assetCanvasOutputKinds, assetCanvasMedia, assetCreativeSettings, compileAssetCreativePrompt, normalizeSlotAspect, slotAspectRatioOptions, EMPTY_CREATIVE_STYLE, isUniversalAssetNodeKind, type AssetCreativeSettings, type CharacterDesign } from "../asset-canvas-creative"
import { groupedWorkflowOptions, WorkflowOptionRow, type WorkflowSelectOption } from "../../components/WorkflowOptions"
import { filterGroupedOptions } from "../../search-match"
import { AssetGroupNode, AssetCreationNode, UniversalAssetNode } from "./AssetCanvasNodes"
import { AssetCanvasContext as Context, type AssetCanvasActions, type CanvasNodeData, type AssetCanvasContextValue as CanvasContext } from "./asset-canvas-context"
import { readEdit, saveEdit, uploadMedia } from "../smart-edit/api"
import { makeClip, blankDocument, type EditAsset } from "../smart-edit/model"
import { director2ProjectPath } from "../paths"
import { ArrowUp, Undo2, Redo2, Link2, Layers, Hand, MousePointer2, Keyboard, ChevronsLeft, ChevronRight, Scissors, Copy, Volume2 } from "lucide-react"
import { Alert, Button, ConfigProvider, Dropdown, Empty, Form, Input, Modal, Segmented, Select, Spin, Tag, Tooltip, message, Tabs, Popover, type MenuProps } from "antd"
import { ArrowRight, Boxes, Check, ChevronDown, FileText, Image as ImageIcon, Images, LayoutGrid, Map as MapIcon, Maximize2, Mic, MoreHorizontal, Plus, RefreshCw, Search, Sparkles, Trash2, Video, Workflow, X, ZoomIn, ZoomOut } from "lucide-react"
import type { Director2Asset } from "../api"
import { assetDefinitionText, assetNodeId, assetSlotBlocker, assetSlotPrompt, buildAssetCanvas, readAssetCanvasLayout, type AssetCanvasNode, type AssetCanvasTarget } from "../asset-canvas-model"
import { sourceReferencesOf } from "../asset-source-references"
import { useMediaPreview } from "../media-preview"
import { assetReadiness } from "../project-flow"
import { getAssetDisplayAvatar, getKindIcon, kindLabel } from "./assets/shared"
import AssetPickerModal from "../../tools/AssetPickerModal"
import { ensureLinkedCanvas, getCanvasProject, saveCanvasDraft } from "../../canvas/canvas-api"
import { buildEdgeId, nextNodeId, type CanvasNode } from "../../canvas/canvas-model"
import { buildNodeTypes } from "../../canvas/node-registry"
import {
  cancelCanvasJob,
  refineCanvasJob,
  canvasJobOutputs,
  canvasJobResults,
  canvasImageNodeFile,
  defaultGeneratorOptionValues,
  fetchCanvasJob,
  fetchCanvasModes,
  generatorParameterFields,
  isCanvasJobActive,
  serializeGeneratorOptionValues,
  submitCanvasJob,
  type CanvasJob,
  type CanvasOptionValue,
  type CanvasWorkflowMode,
} from "../../canvas/canvas-generation"
import { canvasByteSize, canvasConflictVersion, canvasContentSizeLevel, createCanvasSaveQueue, formatCanvasBytes, saveStateAfterCanvasEdit, saveStateAfterCanvasSave, type CanvasSaveState } from "../../canvas/canvas-save"
import {
  mergeProjection,
  migrateLegacyLayout,
  parseAssetCanvasDraft,
  serializeAssetCanvasDraft,
  assetCanvasDraftContent,
  isAssetCanvasDraftEmpty,
  type AssetCanvasDraft,
} from "../../canvas/asset-canvas-sync"
import "@xyflow/react/dist/style.css"
import "./asset-creation-canvas.css"
import "./asset-canvas-generator.css"
import "./asset-canvas-workspace.css"
// 共享顶栏样式层：改一次两个画布同时生效
import "../../canvas/canvas-chrome-shared.css"

export type { AssetCanvasActions } from "./asset-canvas-context"

type Props = {
  projectId: string
  projectTitle?: string
  csrfToken: string
  assets: Director2Asset[]
  selectedId?: string
  selectedNode?: string | null
  saveStatus: string
  saveError: boolean
  loading: boolean
  working: string | null
  errors?: Record<string, string>
  actions: AssetCanvasActions
}

const DRAFT_SAVE_DEBOUNCE_MS = 1500
const JOB_POLL_INTERVAL_MS = 2500
const errorText = (error: unknown, fallback = "操作失败") => error instanceof Error && error.message ? error.message : fallback
const isActiveJobStatus = (status: unknown) => typeof status === "string" && (isCanvasJobActive(status) || status === "canceling")

function AssetConnectionLine({ fromX, fromY, toX, toY, fromPosition, toPosition }: ConnectionLineComponentProps) {
  const [path] = getBezierPath({ sourceX: fromX, sourceY: fromY, targetX: toX, targetY: toY, sourcePosition: fromPosition, targetPosition: toPosition })
  return <g><path d={path} fill="none" stroke="var(--ac-link-active)" strokeWidth={1.5}/><path d={path} className="ac-connection-highlight" fill="none" stroke="var(--studio-text)" strokeWidth={2} pathLength={100}/></g>
}

function isAssetDerived(data: Record<string, unknown> | undefined): boolean {
  return !!data && data.origin !== "canvas" && !!data.asset && typeof (data.asset as { id?: unknown }).id === "string"
}

function canvasDataOf(node: { data?: unknown }): CanvasNodeData | null {
  const data = node.data as CanvasNodeData | undefined
  return data && data.origin === "canvas" ? data : null
}

/** 资产图片投影节点 → 通用画布图片节点形状，供 canvas-generation 参考图链路复用。 */
function asCanvasImageNode(node: { id: string; data?: Record<string, unknown> }): CanvasNode | null {
  const image = String(node.data?.image || ((node.data?.canvasKind === "image" || node.data?.resultKind === "image") ? node.data?.url || node.data?.resultUrl || "" : ""))
  if (!image) return null
  return { id: node.id, type: "image", position: { x: 0, y: 0 }, data: { url: image, label: String(node.data?.title ?? "") } }
}

/** 渲染层结构相等判定：投影重建只在节点真正变化时才替换对象，避免 xyflow measured 被无意义重置。 */
function isSameRenderedNode(a: Node, b: Node): boolean {
  if (a.id !== b.id || a.type !== b.type || a.parentId !== b.parentId || !!a.selected !== !!b.selected) return false
  if (a.position.x !== b.position.x || a.position.y !== b.position.y || a.style?.width !== b.style?.width) return false
  const da = (a.data ?? {}) as Record<string, unknown>
  const db = (b.data ?? {}) as Record<string, unknown>
  if (da.asset !== db.asset || da.key !== db.key || da.role !== db.role || da.title !== db.title || da.image !== db.image) return false
  if (da.origin === "canvas" || db.origin === "canvas") return JSON.stringify(da) === JSON.stringify(db)
  return JSON.stringify(da.target ?? null) === JSON.stringify(db.target ?? null)
}

// 通用节点来自共享注册表（单一来源）；资产域专属节点在此叠加。
const nodeTypes = buildNodeTypes({ assetGroup: AssetGroupNode, assetCreation: AssetCreationNode, generator: UniversalAssetNode, video: UniversalAssetNode, image: UniversalAssetNode, text: UniversalAssetNode, audio: UniversalAssetNode, editor: UniversalAssetNode })

const styleNumber = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null
function nodeWidth(node: Node | { width?: unknown; style?: Record<string, unknown>; measured?: { width?: number } } | undefined): number | null {
  if (!node) return null
  const anyNode = node as { width?: unknown; style?: Record<string, unknown>; measured?: { width?: number } }
  return styleNumber(anyNode.measured?.width) ?? styleNumber(anyNode.width) ?? styleNumber(anyNode.style?.width) ?? null
}
function nodeHeight(node: Node | { height?: unknown; style?: Record<string, unknown>; measured?: { height?: number } } | undefined): number | null {
  if (!node) return null
  const anyNode = node as { height?: unknown; style?: Record<string, unknown>; measured?: { height?: number } }
  return styleNumber(anyNode.measured?.height) ?? styleNumber(anyNode.height) ?? styleNumber(anyNode.style?.height) ?? null
}
// 组框位于顶层，其 position 即绝对坐标；子节点 position 相对父级。
function absoluteOf(list: Node[], id: string): XYPosition {
  const node = list.find(item => item.id === id)
  if (!node) return { x: 0, y: 0 }
  if (!node.parentId) return node.position
  const parent = list.find(item => item.id === node.parentId)
  return { x: node.position.x + (parent?.position.x ?? 0), y: node.position.y + (parent?.position.y ?? 0) }
}

export default function AssetCreationCanvas(props: Props) {
  return <ConfigProvider button={{ autoInsertSpace: false }}><ReactFlowProvider><AssetCreationCanvasInner {...props}/></ReactFlowProvider></ConfigProvider>
}

function AssetCreationCanvasInner(props: Props) {
  const { assets, actions, selectedId, selectedNode, working, csrfToken, projectId } = props
  const navigate = useNavigate()
  const { openMediaPreview } = useMediaPreview()
  const flow = useReactFlow<Node, Edge>()
  const graph = useMemo(() => buildAssetCanvas(assets), [assets])
  const [nodes, setNodes] = useState<Node[]>(() => graph.nodes.map(node => ({ ...node })))
  const [edges, setEdges] = useState<Edge[]>(graph.edges)
  const [currentNode, setCurrentNode] = useState<string | null>(selectedNode || null)
  const [composerOpen, setComposerOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(true)
  const [libraryKind, setLibraryKind] = useState("all")
  const [search, setSearch] = useState("")
  // 工作流/图片模型下拉的搜索词：受控过滤后才能按相关度排序（filterOption 只能过滤不能排序）。
  const [workflowQuery, setWorkflowQuery] = useState("")
  const [slotModelQuery, setSlotModelQuery] = useState("")
  const [miniMap, setMiniMap] = useState(true)
  const [contextMenuOpen, setContextMenuOpen] = useState(false)
  const contextOrigin = useRef<XYPosition | null>(null)
  const [zoom, setZoom] = useState(1)
  const [editNode, setEditNode] = useState<string | null>(null)
  const [editKind, setEditKind] = useState<"definition" | "metadata">("definition")
  const [editName, setEditName] = useState("")
  const [editRole, setEditRole] = useState("")
  const [editText, setEditText] = useState("")
  const [editing, setEditing] = useState(false)
  const [fileTarget, setFileTarget] = useState<string | null>(null)
  const [mediaPicker, setMediaPicker] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const focusedAsset = useRef<string | null>(null)
  const composerWasOpen = useRef(false)
  const [libraryTab, setLibraryTab] = useState("materials")
  const [panMode, setPanMode] = useState(false)
  const [linksVisible, setLinksVisible] = useState(true)
  const [showGrid, setShowGrid] = useState(true)
  const [designNode, setDesignNode] = useState<string | null>(null)
  const [uploadBusy, setUploadBusy] = useState<string | null>(null)
  const [referenceOpen, setReferenceOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [contextNodeId, setContextNodeId] = useState<string | null>(null)
  const [moving, setMoving] = useState(false)
  const [portRequest, setPortRequest] = useState<{ id: string; direction: "in" | "out"; x: number; y: number; position: XYPosition } | null>(null)
  const connectionStart = useRef<{ id: string; direction: "in" | "out" } | null>(null)
  const pendingAssetConnection = useRef<{ ids: string[]; source: string; direction: "in" | "out" } | null>(null)
  const history = useRef<{ nodes: Node[]; edges: Edge[] }[]>([])
  const future = useRef<{ nodes: Node[]; edges: Edge[] }[]>([])
  const [, setHistoryRevision] = useState(0)
  const lastHistoryEdit = useRef({ id: "", at: 0 })
  const submitting = useRef(new Set<string>())
  const polling = useRef(false)

  // —— linked 画布 + 草稿持久化 ——
  const [canvasReady, setCanvasReady] = useState(false)
  const [draftSaveState, setDraftSaveState] = useState<CanvasSaveState>("saved")
  const [modes, setModes] = useState<CanvasWorkflowMode[]>([])
  const [canvasError, setCanvasError] = useState("")
  const [modesError, setModesError] = useState("")
  const canvasProjectRef = useRef<{ id: string; version: number } | null>(null)
  const draftRef = useRef<AssetCanvasDraft>({ schemaVersion: 1, nodes: [], edges: [], viewport: null })
  const nodesRef = useRef<Node[]>(nodes)
  const edgesRef = useRef<Edge[]>(edges)
  nodesRef.current = nodes
  edgesRef.current = edges
  const draftSaveTimer = useRef<number | null>(null)
  const savingRef = useRef(false)
  const mountedRef = useRef(true)
  mountedRef.current = true

  const markDraftDirty = () => setDraftSaveState(state => saveStateAfterCanvasEdit(state))

  const flushDraftSave = useMemo(() => createCanvasSaveQueue(async (notify) => {
    const canvasProject = canvasProjectRef.current
    if (!canvasProject || !canvasReadyRef.current) return "failed"
    if (savingRef.current) return "dirty"
    const draft = serializeAssetCanvasDraft(nodesRef.current, edgesRef.current, draftRef.current.viewport)
    draftRef.current = draft
    const content = assetCanvasDraftContent(draft)
    if (content === lastSavedContentRef.current) {
      if (mountedRef.current) setDraftSaveState("saved")
      return "saved"
    }
    if (canvasContentSizeLevel(canvasByteSize(content)) === "over") {
      if (mountedRef.current) { setDraftSaveState("error"); message.error(`画布内容约 ${formatCanvasBytes(canvasByteSize(content))}，超过 8 MB 上限`) }
      return "failed"
    }
    savingRef.current = true
    if (mountedRef.current) setDraftSaveState("saving")
    try {
      const result = await saveCanvasDraft(csrfToken, canvasProject.id, canvasProject.version, content, null)
      canvasProjectRef.current = { id: canvasProject.id, version: result.version }
      lastSavedContentRef.current = content
      const outcome = saveStateAfterCanvasSave(assetCanvasDraftContent(serializeAssetCanvasDraft(nodesRef.current, edgesRef.current, draftRef.current.viewport)) === content)
      if (mountedRef.current) setDraftSaveState(outcome === "saved" ? "saved" : "dirty")
      if (notify && outcome === "saved") message.success("资产画布已保存")
      return outcome === "saved" ? "saved" : "dirty"
    } catch (error) {
      const currentVersion = canvasConflictVersion(error)
      if (currentVersion !== null) {
        // 本地真相优先：刷新版本号后由队列重试（节点 ID 稳定寻址，不存在并发多编辑者）。
        try {
          const latest = await getCanvasProject(canvasProject.id)
          canvasProjectRef.current = { id: canvasProject.id, version: latest.version }
          if (mountedRef.current) setDraftSaveState("retrying")
          return "dirty"
        } catch { /* 读取失败则保留冲突版本继续重试 */ }
        canvasProjectRef.current = { id: canvasProject.id, version: currentVersion }
        if (mountedRef.current) setDraftSaveState("retrying")
        return "dirty"
      }
      if (mountedRef.current) { setDraftSaveState("error"); if (notify) message.error(errorText(error, "资产画布保存失败")) }
      return "failed"
    } finally {
      savingRef.current = false
    }
  }), [csrfToken])
  const canvasReadyRef = useRef(false)
  const lastSavedContentRef = useRef("")

  const scheduleDraftSave = () => {
    markDraftDirty()
    if (draftSaveTimer.current !== null) window.clearTimeout(draftSaveTimer.current)
    draftSaveTimer.current = window.setTimeout(() => {
      draftSaveTimer.current = null
      void flushDraftSave()
    }, DRAFT_SAVE_DEBOUNCE_MS)
  }

  const remember = (id = "") => {
    if (id && lastHistoryEdit.current.id === id && Date.now() - lastHistoryEdit.current.at < 700) return
    lastHistoryEdit.current = { id, at: Date.now() }
    history.current = [...history.current.slice(-39), { nodes: nodesRef.current, edges: edgesRef.current }]
    future.current = []
    setHistoryRevision(value => value + 1)
  }
  const commitGraph = (nextNodes: Node[], nextEdges: Edge[] = edgesRef.current) => {
    nodesRef.current = nextNodes; edgesRef.current = nextEdges
    setNodes(nextNodes); setEdges(nextEdges)
    draftRef.current = serializeAssetCanvasDraft(nextNodes, nextEdges, draftRef.current.viewport)
    scheduleDraftSave()
  }
  const travelHistory = (redo: boolean) => {
    const source = redo ? future : history, destination = redo ? history : future
    const snapshot = source.current.pop()
    if (!snapshot) return
    destination.current.push({ nodes: nodesRef.current, edges: edgesRef.current })
    // 媒体真相仍由资产表提供，撤销只恢复画布布局、文本和用户连线。
    const latestAssets = new Map(graph.nodes.map(node => [node.id, node.data]))
    commitGraph(snapshot.nodes.map(node => latestAssets.has(node.id) ? { ...node, data: latestAssets.get(node.id)! } : node), snapshot.edges)
    setHistoryRevision(value => value + 1)
    setCurrentNode(null); setComposerOpen(false)
  }

  useEffect(() => {
    let stopped = false
    void (async () => {
      try {
        const project = await ensureLinkedCanvas(csrfToken, projectId, props.projectTitle ? `资产画布 · ${props.projectTitle}` : "")
        if (stopped) return
        canvasProjectRef.current = { id: project.id, version: project.version }
        setCanvasError("")
        let draft = parseAssetCanvasDraft(project.content || "")
        if (isAssetCanvasDraftEmpty(draft)) {
          const migrated = migrateLegacyLayout(graph, assets.map(asset => readAssetCanvasLayout(asset)))
          if (!isAssetCanvasDraftEmpty(migrated)) {
            draft = migrated
            if (canvasProjectRef.current) {
              try {
                const saved = await saveCanvasDraft(csrfToken, canvasProjectRef.current.id, canvasProjectRef.current.version, assetCanvasDraftContent(draft), null)
                canvasProjectRef.current = { id: saved.id, version: saved.version }
                lastSavedContentRef.current = assetCanvasDraftContent(draft)
              } catch { /* 首迁失败则保持内存草稿，后续编辑仍会保存 */ }
            }
          }
        }
        if (stopped) return
        draftRef.current = draft
        const merged = mergeProjection(graph, draft)
        setNodes(merged.nodes as Node[])
        setEdges(merged.edges)
        canvasReadyRef.current = true
        setCanvasReady(true)
        if (draft.viewport) void flow.setViewport(draft.viewport)
        else void flow.fitView({ padding: .2, maxZoom: .8 })
      } catch (error) {
        if (stopped) return
        setCanvasError(errorText(error, "画布草稿读取失败，请重试")); setDraftSaveState("error")
        // linked 画布不可用（登录过期/后端异常）：本轮沿用投影布局，不做草稿持久化。
        canvasReadyRef.current = true
        setCanvasReady(true)
      }
    })()
    return () => { stopped = true }
    // 仅挂载（或项目切换）时读取一次草稿
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [csrfToken, projectId])

  useEffect(() => {
    void (async () => {
      try {
        const payload = await fetchCanvasModes()
        setModes(payload.modes.filter(mode => mode.available !== false))
      } catch (error) { setModesError(errorText(error, "工作流列表读取失败，请刷新重试")) }
    })()
  }, [])

  // 资产更新只同步节点 data 与增删节点，位置以草稿（draftRef）为唯一真相，绝不回落到投影默认（根除回弹与硬刷新丢失布局）。
  // 硬刷新深链进画布时，挂载读草稿的那一刻 assets 尚未到达、graph 为空，mergeProjection 会丢弃全部资产坐标；
  // 待资产到位 graph 变化后，这里必须重新套用草稿坐标，否则节点会退回投影默认并被反向覆盖写回服务端。
  // 重建必须幂等：父组件任意 re-render 都会生成新的 graph 引用，若每次都用全新节点对象覆盖，
  // xyflow 的 measured 会被反复重置（节点 visibility:hidden、边不渲染），因此结构未变时保持原数组。
  useEffect(() => {
    if (!canvasReadyRef.current) return
    // 以 mergeProjection（与挂载同一函数、已单测）为唯一权威重建：资产节点取草稿坐标、canvas 节点取草稿、
    // 投影边 + 连到 canvas 节点的用户连线一并保留。避免手写边剔除误伤图片→生成、生成→视频连线。
    const merged = mergeProjection(graph, draftRef.current)
    setNodes(previous => {
      const selectedIds = new Set(previous.filter(node => node.selected).map(node => node.id))
      const next = merged.nodes.map(node => (selectedIds.has(node.id) ? { ...node, selected: true } : node)) as Node[]
      if (previous.length !== next.length) return next
      const byId = new Map(previous.map(node => [node.id, node]))
      for (const node of next) {
        const old = byId.get(node.id)
        if (!old || !isSameRenderedNode(old, node)) return next
      }
      return previous
    })
    setEdges(previous => {
      if (previous.length !== merged.edges.length) return merged.edges
      const byId = new Map(previous.map(edge => [edge.id, edge]))
      for (const edge of merged.edges) {
        const old = byId.get(edge.id)
        if (!old || old.source !== edge.source || old.target !== edge.target) return merged.edges
      }
      return previous
    })
  }, [graph, canvasReady])

  useEffect(() => {
    setNodes(previous => {
      const changed = previous.some(node => !!node.selected !== (node.id === currentNode))
      return changed ? previous.map(node => ({ ...node, selected: node.id === currentNode })) : previous
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentNode])

  useEffect(() => {
    if (!selectedId || !nodes.length || focusedAsset.current === selectedId) return
    focusedAsset.current = selectedId
    const key = selectedNode || nodes.find(node => (node.data as Record<string, unknown> | undefined)?.asset && (node.data as { asset?: { id?: string } }).asset?.id === selectedId && (node.data as { role?: string }).role === "image")?.id || assetNodeId(selectedId, "definition")
    setCurrentNode(key)
    requestAnimationFrame(() => { void flow.fitView({ nodes: [{ id: assetNodeId(selectedId, "group") }], padding: .16, maxZoom: .95, duration: 250 }) })
  }, [selectedId, selectedNode, nodes, flow])

  const chosen = nodes.find(node => node.id === currentNode)
  const chosenAsset = (chosen?.data as AssetCanvasNode["data"] | undefined)?.asset as Director2Asset | undefined
  const imageNode = chosen?.type === "assetCreation" ? chosen as unknown as AssetCanvasNode : undefined
  const blocker = imageNode?.data.target ? assetSlotBlocker(imageNode.data.asset, imageNode.data.target) : ""

  useEffect(() => {
    const wasOpen = composerWasOpen.current
    composerWasOpen.current = composerOpen
    if (!composerOpen) {
      if (wasOpen && chosenAsset) void flow.fitView({ nodes: [{ id: assetNodeId(chosenAsset.id, "group") }], padding: .16, maxZoom: .95, duration: 220 })
      return
    }
    if (!chosen || !stageRef.current) return
    const frame = requestAnimationFrame(() => {
      const stage = stageRef.current
      if (!stage) return
      const internal = nodesRef.current.find(node => node.id === chosen.id)
      const abs = absoluteOf(nodesRef.current, chosen.id)
      const width = nodeWidth(internal) || 392, height = nodeHeight(internal) || 460
      const availableHeight = Math.max(220, stage.clientHeight - 360)
      const nextZoom = Math.min(.85, Math.max(.3, availableHeight / height))
      const libraryWidth = drawerOpen ? 294 : 0
      void flow.setViewport({ x: libraryWidth + (stage.clientWidth - libraryWidth) / 2 - (abs.x + width / 2) * nextZoom, y: 90 + availableHeight / 2 - (abs.y + height / 2) * nextZoom, zoom: nextZoom }, { duration: 220 })
    })
    return () => cancelAnimationFrame(frame)
    // Keep typing and generation updates from moving the selected node again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerOpen, currentNode])

  useEffect(() => () => {
    if (draftSaveTimer.current !== null) window.clearTimeout(draftSaveTimer.current)
    void flushDraftSave()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const syncDraftNow = () => {
    const draft = serializeAssetCanvasDraft(nodesRef.current, edgesRef.current, draftRef.current.viewport)
    draftRef.current = draft
    return draft
  }

  const choose = (id: string, edit = true) => {
    const node = nodesRef.current.find(item => item.id === id)
    if (!node) return
    setCurrentNode(id)
    setComposerOpen(edit && (node.data.role === "image" || ["image", "video", "generator"].includes(String(node.data.canvasKind))))
    if (isAssetDerived(node.data)) actions.select((node.data as AssetCanvasNode["data"]).asset.id)
    if (node.data.origin === "canvas" && ["image", "video", "generator"].includes(String(node.data.canvasKind)) && !node.data.workflowId) {
      const media = node.data.canvasKind === "image" ? "image" : "video"
      const refs = referenceNodesFor(id).length
      const mode = modes.find(item => item.media_type === media && refs >= (item.min_references || 0) && refs <= (item.max_references || 0))
      if (mode) patchCanvasNode(id, { workflowId: mode.id, optionValues: defaultGeneratorOptionValues(mode) })
    }
  }
  const openEditor = (id: string, kind: "definition" | "metadata") => {
    const node = nodes.find(item => item.id === id) as AssetCanvasNode | undefined
    if (!node || !isAssetDerived(node.data as Record<string, unknown>)) return
    choose(id, false); setEditKind(kind); setEditNode(id)
    setEditName(kind === "definition" ? node.data.asset.name : node.data.title)
    setEditRole(node.data.asset.role || "")
    setEditText(assetDefinitionText(node.data.asset))
  }
  const saveEditor = async () => {
    const node = nodes.find(item => item.id === editNode) as AssetCanvasNode | undefined
    if (!node || !editName.trim()) { message.warning("名称不能为空"); return }
    setEditing(true)
    try {
      if (editKind === "definition") await actions.saveDefinition(node.data.asset.id, editName.trim(), editRole.trim(), editText)
      else if (node.data.target) await actions.saveMetadata(node.data.asset.id, node.data.target, editName.trim())
      setEditNode(null)
    } catch (err) { message.error(err instanceof Error ? err.message : "保存失败，修改已保留") }
    finally { setEditing(false) }
  }
  const chooseFile = (id: string, library: boolean) => {
    choose(id, false); setFileTarget(id)
    if (library) setMediaPicker(true)
    else requestAnimationFrame(() => uploadRef.current?.click())
  }
  const uploadFiles = async (files: File[]) => {
    const node = nodesRef.current.find(item => item.id === fileTarget)
    if (!node || !files.length || uploadBusy) return
    if (isAssetDerived(node.data)) { const data = node.data as AssetCanvasNode["data"]; await actions.upload(data.asset.id, data.target || null, files); return }
    const file = files[0]
    if (file.size > 512 * 1024 * 1024) { message.warning("单个素材不能超过 512 MB"); return }
    setUploadBusy(node.id)
    try {
      const result = await uploadMedia(csrfToken, projectId, `canvas-${node.id}`, file)
      if (result.kind !== node.data.canvasKind) throw new Error("请选择与当前节点类型一致的媒体")
      patchCanvasNode(node.id, { url: result.url, label: file.name, duration: result.duration, mediaAsset: result, jobError: null })
      setMediaPicker(false)
    } catch (error) { message.error(errorText(error, "媒体上传失败")) }
    finally { setUploadBusy(null) }
  }

  // —— generator / 视频节点：创建、提交、轮询 ——
  const referenceNodesFor = (generatorId: string): CanvasNode[] => {
    const byId = new Map(nodesRef.current.map((node): [string, Node] => [node.id, node]))
    const seen = new Set<string>()
    const references: CanvasNode[] = []
    for (const edge of edgesRef.current) {
      if (edge.target !== generatorId || seen.has(edge.source)) continue
      const source = byId.get(edge.source)
      if (!source) continue
      const image = asCanvasImageNode(source)
      if (!image) continue
      seen.add(edge.source)
      references.push(image)
    }
    return references
  }

  const addConnection = (source: string, target: string, quiet = false) => {
    const issue = assetCanvasConnectionIssue(nodesRef.current, edgesRef.current, source, target)
    if (issue) { if (!quiet) message.info(issue); return }
    remember()
    commitGraph(nodesRef.current, [...edgesRef.current, { id: buildEdgeId(source, target), source, target, type: "default" }])
  }
  const createNode = (kind: string, position?: XYPosition, from?: string, direction: "in" | "out" = "out") => {
    setPortRequest(null); setContextMenuOpen(false)
    const point = position || contextOrigin.current || flow.screenToFlowPosition({ x: (stageRef.current?.getBoundingClientRect().left || 0) + (stageRef.current?.clientWidth || 1000) / 2, y: (stageRef.current?.getBoundingClientRect().top || 0) + 180 })
    if (["character", "scene", "prop"].includes(kind)) {
      if (from) pendingAssetConnection.current = { ids: assets.map(asset => asset.id), source: from, direction }
      actions.create(kind, point); return
    }
    if (!isUniversalAssetNodeKind(kind)) return
    if (!canvasProjectRef.current) { message.warning("画布尚未连接，请重试读取草稿后再新建节点"); return }
    remember()
    const labels: Record<string, string> = { text: "创作文本", image: "图片", video: "视频", audio: "音频", editor: "剪辑工程", generator: "视频" }
    const node: Node = { id: nextNodeId(`ac-${kind}`), type: kind, position: point, style: { width: kind === "image" ? 360 : kind === "text" ? 320 : 380 }, data: { origin: "canvas", canvasKind: kind, label: labels[kind], prompt: "", text: "", optionValues: {} } }
    const next = [...nodesRef.current, node]
    const connected = from ? { id: buildEdgeId(direction === "out" ? from : node.id, direction === "out" ? node.id : from), source: direction === "out" ? from : node.id, target: direction === "out" ? node.id : from, type: "default" } : null
    commitGraph(next, connected ? [...edgesRef.current, connected] : edgesRef.current)
    setCurrentNode(node.id); setComposerOpen(["image", "video", "generator"].includes(kind))
    const media = kind === "image" ? "image" : "video"
    const refs = from && asCanvasImageNode(nodesRef.current.find(item => item.id === from)!) ? 1 : 0
    const mode = modes.find(item => item.media_type === media && refs >= (item.min_references || 0) && refs <= (item.max_references || 0))
    if (mode && ["image", "video", "generator"].includes(kind)) patchCanvasNode(node.id, { workflowId: mode.id, optionValues: defaultGeneratorOptionValues(mode) })
  }
  const createGeneratorFrom = (id: string) => {
    const point = absoluteOf(nodesRef.current, id)
    createNode("video", { x: point.x + (nodeWidth(nodesRef.current.find(node => node.id === id)) || 392) + 180, y: point.y }, id)
  }

  const patchCanvasNode = (id: string, patch: Partial<CanvasNodeData>) => {
    remember(id)
    commitGraph(nodesRef.current.map(node => node.id === id ? { ...node, data: { ...node.data, ...patch } } : node))
  }
  const removeCanvasNode = (id: string) => {
    const node = nodesRef.current.find(item => item.id === id)
    if (node?.data.origin !== "canvas") { message.info("导演资产保留在资产库，可从素材库继续编辑"); return }
    if (isActiveJobStatus(node.data.jobStatus)) { message.info("请先停止此节点的生成任务"); return }
    remember()
    commitGraph(nodesRef.current.filter(item => item.id !== id), edgesRef.current.filter(edge => edge.source !== id && edge.target !== id))
    if (currentNode === id) { setCurrentNode(null); setComposerOpen(false) }
  }

  const fillVideoResult = (generatorNode: Node, job: CanvasJob, jobId: string) => {
    const results = canvasJobResults(job), first = results[0]
    if (!first) { patchCanvasNode(generatorNode.id, { jobStatus: "failed", jobError: "任务已结束，但没有可用媒体结果" }); return }
    const current = canvasDataOf(generatorNode)!
    const old = current.resultHistory?.length ? current.resultHistory : current.url || current.resultUrl ? [{ url: String(current.url || current.resultUrl), kind: String(current.resultKind || (current.canvasKind === "image" ? "image" : "video")) }] : []
    const resultHistory = [...old, ...results.filter(result => !old.some(item => item.url === result.url)).map(result => ({ ...result, jobId }))].slice(-30)
    const resultIndex = resultHistory.findIndex(item => item.url === first.url)
    const patch = { jobStatus: job.status, jobProgress: job.progress, jobError: null, url: first.url, resultUrl: first.url, resultKind: first.kind, resultPath: first.path || null, resultHistory, resultIndex }
    commitGraph(nodesRef.current.map(node => node.id === generatorNode.id || node.id === current.videoNodeId ? { ...node, data: { ...node.data, ...patch } } : node))
  }

  const applyJobToNodes = (job: CanvasJob) => {
    const generator = nodesRef.current.find(node => {
      const canvas = canvasDataOf(node)
      return !!canvas && canvas.jobId === job.id
    })
    if (!generator) return
    if (job.status === "succeeded" || job.status === "partial") {
      fillVideoResult(generator, job, job.id)
      return
    }
    const patch: Partial<CanvasNodeData> = { jobStatus: job.status, jobProgress: job.progress, jobError: job.status === "failed" || job.status === "cancelled" ? job.error || "任务未完成" : null }
    commitGraph(nodesRef.current.map(node => node.id === generator.id ? { ...node, data: { ...node.data, ...patch } } : node))
  }

  const pollTick = async () => {
    if (polling.current) return
    polling.current = true
    try {
      const active = nodesRef.current.filter(node => {
        const canvas = canvasDataOf(node)
        return !!canvas && typeof canvas.jobId === "string" && canvas.jobId && isActiveJobStatus(canvas.jobStatus)
      })
      for (const node of active) {
        const canvas = canvasDataOf(node)!
        const job = await fetchCanvasJob(String(canvas.jobId))
        applyJobToNodes(job)
      }
    } catch { /* 下一轮再试，保留节点状态 */ }
    finally { polling.current = false }
  }

  const pollingKey = assetCanvasPollingKey(nodes)
  useEffect(() => {
    if (!pollingKey) return
    let stopped = false
    const tick = async () => {
      if (stopped) return
      await pollTick()
    }
    void tick()
    const timer = window.setInterval(() => void tick(), JOB_POLL_INTERVAL_MS)
    return () => { stopped = true; window.clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasReady, pollingKey])

  const inputsOf = (id: string) => edgesRef.current.filter(edge => edge.target === id).map(edge => nodesRef.current.find(node => node.id === edge.source)).filter((node): node is Node => !!node)
  const submitGenerator = async (id: string) => {
    const generator = nodesRef.current.find(node => node.id === id)
    const canvas = generator ? canvasDataOf(generator) : null
    if (!generator || !canvas || submitting.current.has(id) || isActiveJobStatus(canvas.jobStatus)) return
    if (!canvasProjectRef.current) { message.warning("画布草稿尚未就绪，请先重试读取"); return }
    const mode = modes.find(item => item.id === canvas.workflowId) ?? null
    const upstream = inputsOf(id)
    const inputMedia = upstream.filter(node => assetCanvasNodeKind(node) !== "text").map(node => ({ node, media: assetCanvasMedia(node) }))
    if (inputMedia.some(item => !item.media)) { message.warning("请先补齐上游媒体，或移除空引用"); return }
    const contextText = upstream.filter(node => assetCanvasNodeKind(node) === "text").map(node => node.data.asset ? assetDefinitionText(node.data.asset as Director2Asset) : String(node.data.text || "")).filter(Boolean)
    const prompt = compileAssetCreativePrompt([...contextText, String(canvas.prompt || mode?.default_prompt || "")].join("\n\n"), { style: canvas.style, design: canvas.design })
    if (!mode) { message.warning("请先选择生成工作流"); return }
    if (!prompt.trim()) { message.warning("请填写创作提示词"); return }
    if (inputMedia.length < (mode.min_references || 0) || inputMedia.length > (mode.max_references || 0)) { message.warning(`${mode.name} 需要 ${mode.min_references || 0}–${mode.max_references || 0} 份参考素材，当前 ${inputMedia.length} 份`); return }
    const incorrect = inputMedia.findIndex((item, i) => item.media!.kind !== canvasWorkflowReferenceKind(mode, i + 1, inputMedia.length))
    if (incorrect >= 0) { const kind = canvasWorkflowReferenceKind(mode, incorrect + 1, inputMedia.length); message.warning(`参考 ${incorrect + 1} 需要${kind === "video" ? "视频" : kind === "audio" ? "音频" : "图片"}，请调整引用或更换工作流`); return }
    submitting.current.add(id)
    patchCanvasNode(id, { jobStatus: "queued", jobError: null, jobId: null })
    try {
      const files = []
      for (const [index, item] of inputMedia.entries()) {
        const ref: CanvasNode = { id: item.node.id, type: "image", position: { x: 0, y: 0 }, data: { url: item.media!.url, label: item.media!.name } }
        files.push(await canvasImageNodeFile(ref, index + 1, item.media!.kind))
      }
      const job = await submitCanvasJob(csrfToken, { mode: mode!.id, prompt, options: serializeGeneratorOptionValues(mode, canvas.optionValues), references: files, title: String(canvas.label || "画布创作") })
      patchCanvasNode(id, { jobId: job.id, jobStatus: job.status, jobError: null })
      if (["succeeded", "partial"].includes(job.status)) applyJobToNodes(job)
    } catch (error) { patchCanvasNode(id, { jobStatus: "failed", jobError: errorText(error, "任务提交失败") }) }
    finally { submitting.current.delete(id) }
  }

  const portMenu = (id: string, direction: "in" | "out", anchor: HTMLElement) => {
    const stage = stageRef.current?.getBoundingClientRect(), bounds = anchor.getBoundingClientRect()
    if (!stage) return
    const x = Math.min(stage.width - 248, Math.max(12, bounds.right - stage.left + 16)), y = Math.min(stage.height - 360, Math.max(12, bounds.top - stage.top))
    setPortRequest({ id, direction, x, y, position: flow.screenToFlowPosition({ x: bounds.right + 150, y: bounds.top }) })
  }
  const duplicate = (id: string) => {
    const source = nodesRef.current.find(node => node.id === id)
    if (!source) return
    const asset = source.data.asset as Director2Asset | undefined
    const data = canvasDataOf(source)
    remember()
    const node: Node = { id: nextNodeId("ac-copy"), type: data ? source.type : source.data.role === "definition" ? "text" : "image", position: { x: absoluteOf(nodesRef.current, id).x + 80, y: absoluteOf(nodesRef.current, id).y + 80 }, style: { width: nodeWidth(source) || 360 }, data: data ? { ...data, label: `${data.label || "节点"} 副本`, jobId: null, jobStatus: null, videoNodeId: null } : { origin: "canvas", canvasKind: source.data.role === "definition" ? "text" : "image", label: `${asset?.name || "图片"} 副本`, url: source.data.image || "", text: asset ? assetDefinitionText(asset) : "" } }
    commitGraph([...nodesRef.current, node]); setCurrentNode(node.id)
  }
  const openSmartEdit = async (id: string) => {
    if (uploadBusy) return
    setUploadBusy(id)
    try {
      const sequence = `canvas-${id}`
      const snapshot = await readEdit(projectId, sequence)
      const document = snapshot.document || blankDocument()
      const references = inputsOf(id).map(node => ({ node, media: assetCanvasMedia(node) })).filter(item => !!item.media)
      for (const { node, media } of references) {
        let url = media!.url
        if (!/^https?:\/\//i.test(url) && !url.startsWith("/api/local-media/")) {
          const history = (node.data.resultHistory || []) as { jobId?: string }[]
          const selectedJob = history[Number(node.data.resultIndex)]?.jobId
          const jobId = String(selectedJob || node.data.sourceJobId || node.data.jobId || "")
          if (jobId) {
            const job = await fetchCanvasJob(jobId)
            const outputs = canvasJobOutputs(job)
            const cloud = canvasEditingCloudUrl(url, node.data, media!.kind, outputs)
            if (cloud) url = cloud
          }
          if (!/^https?:\/\//i.test(url)) {
            const ref: CanvasNode = { id: node.id, type: "image", position: { x: 0, y: 0 }, data: { url: media!.url } }
            const file = await canvasImageNodeFile(ref, 1, media!.kind)
            url = (await uploadMedia(csrfToken, projectId, sequence, file)).url
          }
        }
        if (document.assets.some(asset => asset.url === url)) continue
        const asset: EditAsset = { id: `canvas-${node.id}-${document.assets.length}`, name: media!.name, kind: media!.kind, url, duration: media!.duration, ...(media!.kind === "image" ? { thumbnail: url } : {}) }
        document.assets.push(asset)
        document.clips.push(makeClip(document, asset, 0))
      }
      document.name = String(nodesRef.current.find(node => node.id === id)?.data.label || "画布剪辑")
      await saveEdit(csrfToken, projectId, sequence, snapshot.revision, document)
      syncDraftNow(); await flushDraftSave()
      navigate(director2ProjectPath(projectId, "edit", sequence))
    } catch (error) { message.error(errorText(error, "打开智能剪辑失败")) }
    finally { setUploadBusy(null) }
  }
  const openTool = (_id: string, tool: string) => { void flushDraftSave(); navigate(`/tools/${tool}`) }

  const context: CanvasContext = {
    actions, working: uploadBusy || working, choose,
    editDesign: id => { choose(id, false); setDesignNode(id) },
    portMenu, inputsOf, openSmartEdit, duplicate, openTool,
    editDefinition: id => openEditor(id, "definition"),
    editMetadata: id => openEditor(id, "metadata"),
    chooseFile,
    preview: (url, title) => openMediaPreview({ src: url, title }),
    modes,
    patchCanvasNode,
    removeCanvasNode,
    submitGenerator,
    createVideoFrom: createGeneratorFrom,
    referenceCountOf: id => referenceNodesFor(id).length,
    canvasReady: canvasReady && !!canvasProjectRef.current,
  }
  const filtered = assets.filter(asset => (libraryKind === "all" || asset.kind === libraryKind) && (!search.trim() || `${asset.name} ${asset.description || ""}`.toLowerCase().includes(search.trim().toLowerCase())))
  const draftStateLabel: Record<CanvasSaveState, string> = { saved: "画布已保存", dirty: "画布未保存", saving: "画布保存中", retrying: "画布重试中", error: "画布保存失败", conflict: "画布冲突" }

  useEffect(() => {
    const pending = pendingAssetConnection.current
    if (!pending) return
    const newAsset = assets.find(asset => !pending.ids.includes(asset.id))
    const target = newAsset && nodes.find(node => (node.data.asset as Director2Asset | undefined)?.id === newAsset.id && node.data.role === "image")
    if (!target) return
    pendingAssetConnection.current = null
    addConnection(pending.direction === "out" ? pending.source : target.id, pending.direction === "out" ? target.id : pending.source, true)
  }, [nodes, assets])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setPortRequest(null); setContextMenuOpen(false); setReferenceOpen(false); return }
      const target = event.target as HTMLElement
      if (target.closest("input,textarea,[contenteditable='true'],.ant-modal,.ant-select,.ant-dropdown")) return
      const mod = event.ctrlKey || event.metaKey
      if (mod && event.key.toLowerCase() === "s") { event.preventDefault(); syncDraftNow(); void flushDraftSave(true); return }
      if (mod && event.key.toLowerCase() === "z") { event.preventDefault(); travelHistory(event.shiftKey); return }
      if (mod && event.key.toLowerCase() === "y") { event.preventDefault(); travelHistory(true); return }
      if (mod && event.key === "0") { event.preventDefault(); void flow.fitView({ padding: .18, maxZoom: .85 }); return }
      if (mod && event.key === "Enter" && currentNode) { event.preventDefault(); if (!working && !blocker) runChosen(); return }
      if (event.key.toLowerCase() === "h") setPanMode(true)
      if (event.key.toLowerCase() === "v") setPanMode(false)
      if (event.key === "Tab") { event.preventDefault(); setPortRequest(null); setContextNodeId(null); setContextMenuOpen(value => !value) }
      if ((event.key === "Delete" || event.key === "Backspace") && currentNode) { event.preventDefault(); removeCanvasNode(currentNode) }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  })

  const kinds = ["character", "scene", "prop", "text", "image", "video", "audio", "editor"]
  const nodeLabel = (node: Node) => String(node.data.label || (node.data.role === "image" ? (node.data.asset as Director2Asset | undefined)?.name : node.data.title) || "节点")
  const kindName = (kind: string) => ({ generator: "视频", text: "文本", image: "图片", video: "视频", audio: "音频", editor: "剪辑工程" }[kind] || kindLabel(kind))
  const kindIcon = (kind: string) => { const Icon = kind === "text" ? FileText : kind === "image" ? ImageIcon : kind === "video" ? Video : kind === "audio" ? Volume2 : kind === "editor" ? Scissors : getKindIcon(kind); return <Icon size={16}/> }
  const addMenuItems: MenuProps["items"] = kinds.map(kind => ({ key: kind, label: kindName(kind), icon: kindIcon(kind), onClick: () => createNode(kind, contextOrigin.current || undefined) }))
  const selectedCanvas = chosen ? canvasDataOf(chosen) : null
  const selectedMedia = chosen ? assetCanvasMedia(chosen) : null
  const selectedInputs = currentNode ? inputsOf(currentNode) : []
  const mode = modes.find(item => item.id === selectedCanvas?.workflowId) || null
  const parameterFields = generatorParameterFields(mode, selectedCanvas?.optionValues || {})
  const selectedSettings = imageNode?.data.target ? assetCreativeSettings(imageNode.data.asset, imageNode.data.target) : { style: selectedCanvas?.style, design: selectedCanvas?.design }
  // 槽位图片模型/比例：与生成页同源（/api/modes 的 GRS 生图模型），按槽位记忆在 canvas_settings。
  const imageModeOptions = useMemo(() => groupedWorkflowOptions(modes.filter(item => item.media_type === "image")), [modes])
  const imageModePickerOptions = useMemo(() => filterGroupedOptions(imageModeOptions, slotModelQuery), [imageModeOptions, slotModelQuery])
  const canvasWorkflowOptions = useMemo(
    () => groupedWorkflowOptions(modes.filter(item => item.media_type === (chosen?.data.canvasKind === "image" ? "image" : "video"))),
    [modes, chosen?.data.canvasKind],
  )
  const canvasWorkflowPickerOptions = useMemo(
    () => filterGroupedOptions(canvasWorkflowOptions, workflowQuery),
    [canvasWorkflowOptions, workflowQuery],
  )
  const defaultImageMode = modes.find(item => item.media_type === "image" && item.is_default) || null
  const slotSettings = imageNode?.data.target ? selectedSettings as AssetCreativeSettings : null
  const slotMode = slotSettings?.model ? modes.find(item => item.id === slotSettings.model) || null : null
  const slotAspectOptions = slotAspectRatioOptions(slotMode)
  const designTarget = nodes.find(node => node.id === designNode)
  const designAsset = designTarget?.data.asset as Director2Asset | undefined
  const designTargetSlot = designTarget?.data.target as AssetCanvasTarget | undefined
  const designValue: CharacterDesign = designAsset && designTargetSlot ? assetCreativeSettings(designAsset, designTargetSlot).design || {} : (designTarget?.data.design as CharacterDesign) || {}
  const changeStyle = (style: typeof EMPTY_CREATIVE_STYLE) => {
    if (imageNode?.data.target) void actions.configure(imageNode.data.asset.id, imageNode.data.target, { style }).catch(error => message.error(errorText(error)))
    else if (currentNode) patchCanvasNode(currentNode, { style })
  }
  const setOption = (name: string, value: CanvasOptionValue) => { if (currentNode) patchCanvasNode(currentNode, { optionValues: { ...selectedCanvas?.optionValues, [name]: value } }) }
  const portSource = portRequest ? nodes.find(node => node.id === portRequest.id) : undefined
  const portKinds = portRequest?.direction === "out" ? assetCanvasOutputKinds(portSource) : kinds.filter(kind => kind !== "editor")
  const portItems: MenuProps["items"] = [{ key: "title", label: portRequest?.direction === "out" ? "引用该节点生成" : "添加上下文", disabled: true }, ...portKinds.map(kind => ({ key: kind, label: kindName(kind), icon: kindIcon(kind), onClick: () => { if (portRequest) createNode(kind, portRequest.position, portRequest.id, portRequest.direction) } })), { type: "divider" }, { key: "existing", label: "连接已有节点", icon: <Link2 size={15}/>, children: nodes.filter(node => node.type !== "assetGroup" && node.data.role !== "references" && node.id !== portRequest?.id && (portRequest?.direction !== "in" || assetCanvasNodeKind(portSource) !== "editor" || !!assetCanvasMedia(node))).map(node => ({ key: node.id, label: <span className="ac-existing-node-label">{nodeLabel(node)}{node.data.role && node.data.role !== "image" ? ` · ${(node.data.asset as Director2Asset | undefined)?.name || ""}` : ""}</span>, onClick: () => { if (portRequest) addConnection(portRequest.direction === "out" ? portRequest.id : node.id, portRequest.direction === "out" ? node.id : portRequest.id); setPortRequest(null) } })) }]
  // @ 素材引用：即梦式级联菜单 —— 一级分类（空分类隐藏），二级为可连接节点（缩略图 + 名称），选中即建立引用连线
  const referenceCandidates = chosen ? nodes.filter(node => node.id !== chosen.id && node.type !== "assetGroup" && ["text", "image", "character", "scene", "prop", "video", "audio"].includes(assetCanvasNodeKind(node))) : []
  const referenceBuckets = new Map<string, Node[]>()
  for (const node of referenceCandidates) {
    const asset = node.data.asset as Director2Asset | undefined
    const slot = node.data.target as AssetCanvasTarget | undefined
    const key = asset && node.data.role ? (slot?.type === "scene_pano" ? "pano" : String(asset.kind || "image")) : String(node.data.canvasKind || assetCanvasNodeKind(node))
    const bucket = referenceBuckets.get(key)
    if (bucket) bucket.push(node); else referenceBuckets.set(key, [node])
  }
  const referenceCategoryIcon = (key: string) => {
    if (key === "image") return <ImageIcon size={16}/>
    if (key === "pano") return <Images size={15}/>
    if (key === "video") return <Video size={16}/>
    if (key === "audio") return <Volume2 size={16}/>
    if (key === "text") return <FileText size={16}/>
    const Icon = getKindIcon(key)
    return <Icon size={16}/>
  }
  const referenceNodeLabel = (node: Node) => {
    const asset = node.data.asset as Director2Asset | undefined
    return asset && (node.data.role === "definition" || node.data.role === "references") ? `${asset.name} · ${nodeLabel(node)}` : nodeLabel(node)
  }
  const referenceNodeItem = (node: Node) => {
    const media = assetCanvasMedia(node)
    const thumb = media && media.kind === "image" ? media.url : (node.data.asset ? getAssetDisplayAvatar(node.data.asset as Director2Asset) : "")
    return <span className="ac-reference-node-item">{thumb ? <img src={thumb} alt=""/> : <span className="ac-reference-node-icon">{kindIcon(assetCanvasNodeKind(node))}</span>}<span className="ac-reference-node-name">{referenceNodeLabel(node)}</span></span>
  }
  const referenceCategories: { key: string; label: string }[] = [
    { key: "image", label: "图片" },
    { key: "character", label: "角色" },
    { key: "scene", label: "场景" },
    { key: "pano", label: "全景图" },
    { key: "prop", label: "道具" },
    { key: "video", label: "视频" },
    { key: "audio", label: "音频" },
    { key: "text", label: "文本" },
  ]
  const referenceMenuItems: MenuProps["items"] = [
    { key: "reference-title", label: "素材引用", disabled: true },
    ...referenceCategories.filter(category => referenceBuckets.has(category.key)).map(category => ({
      key: category.key,
      label: category.label,
      icon: referenceCategoryIcon(category.key),
      children: (referenceBuckets.get(category.key) || []).map(node => ({ key: node.id, disabled: selectedInputs.some(item => item.id === node.id), label: referenceNodeItem(node) })),
    })),
    ...(referenceCandidates.length ? [] : [{ key: "reference-empty", label: "画布上暂无可引用的素材", disabled: true }]),
  ]
  const relatedEdges: Edge[] = edges.map(edge => ({ ...edge, hidden: !linksVisible, type: "default", className: edge.source === currentNode || edge.target === currentNode ? "ac-edge-active" : "ac-edge-idle", style: { stroke: edge.source === currentNode || edge.target === currentNode ? "var(--ac-link-active)" : "var(--ac-link-idle)", strokeWidth: 1.4 }, label: undefined }))
  const sidebarNodes = nodes.filter(node => node.data.origin === "canvas" && (!search || String(node.data.label || node.data.text || "").toLowerCase().includes(search.toLowerCase())) && (libraryKind === "all" || node.data.canvasKind === libraryKind))
  const focusNode = (id: string) => { choose(id, false); void flow.fitView({ nodes: [{ id }], padding: .5, maxZoom: .85, duration: 220 }) }
  const viewport = flow.getViewport()
  const selectedPoint = chosen ? absoluteOf(nodes, chosen.id) : null
  const toolbarX = selectedPoint ? selectedPoint.x * viewport.zoom + viewport.x + (nodeWidth(chosen) || 392) * viewport.zoom / 2 : 500
  const toolbarY = selectedPoint ? selectedPoint.y * viewport.zoom + viewport.y - 84 : 24
  let pendingPath = ""
  if (portRequest && portSource && stageRef.current) {
    const from = absoluteOf(nodes, portSource.id), stage = stageRef.current.getBoundingClientRect()
    const source = flow.flowToScreenPosition({ x: from.x + (portRequest.direction === "out" ? (nodeWidth(portSource) || 392) + 17 : -17), y: from.y + (nodeHeight(portSource) || 460) / 2 })
    const destination = flow.flowToScreenPosition(portRequest.position)
    pendingPath = getBezierPath({ sourceX: source.x - stage.left, sourceY: source.y - stage.top, targetX: destination.x - stage.left, targetY: destination.y - stage.top, sourcePosition: portRequest.direction === "out" ? Position.Right : Position.Left, targetPosition: Position.Left })[0]
  }
  const runChosen = () => {
    if (!imageNode?.data.target) { if (currentNode) void submitGenerator(currentNode); return }
    const custom = selectedInputs.filter(node => !graph.edges.some(edge => edge.source === node.id && edge.target === imageNode.id))
    const text = custom.filter(node => assetCanvasNodeKind(node) === "text").map(node => node.data.asset ? assetDefinitionText(node.data.asset as Director2Asset) : String(node.data.text || ""))
    const images = custom.filter(node => assetCanvasNodeKind(node) !== "text").map(node => asCanvasImageNode(node))
    if (images.some(node => !node)) { message.warning("请先补齐上游图片；音频和视频请连接剪辑工程"); return }
    if (images.length + sourceReferencesOf(imageNode.data.asset).length > 9) { message.warning("最多使用 9 张参考图，请移除多余引用"); return }
    void actions.generate(imageNode.data.asset.id, imageNode.data.target, { prompt: [...text, assetSlotPrompt(imageNode.data.asset, imageNode.data.target)].filter(Boolean).join("\n\n"), images: images.map(node => String(node!.data.url)) })
  }

  return <div className={`asset-creation-canvas${drawerOpen ? " has-library" : ""}${panMode ? " is-pan-mode" : ""}`}>
    <header className="ac-header canvas-chrome-bar"><div className="ac-header-start"><strong className="ac-project-title" title={props.projectTitle}>{props.projectTitle || "创作项目"}</strong><span className="ac-header-divider"/><strong>创作画布</strong><Segmented aria-label="资产视图" value="canvas" options={[{ value: "list", label: "列表", icon: <LayoutGrid size={13}/> }, { value: "canvas", label: "画布", icon: <Workflow size={13}/> }]} onChange={value => { if (value === "list") { syncDraftNow(); void flushDraftSave(); void actions.showList() } }}/><span className="ac-node-count">节点 {nodes.filter(node => node.type !== "assetGroup").length}</span></div><div className="ac-header-end"><Tooltip title={props.saveError ? "资产保存失败，点击重试" : draftStateLabel[draftSaveState]}><Button type="text" size="small" icon={draftSaveState === "error" || props.saveError ? <RefreshCw size={14}/> : <Check size={14}/>} danger={draftSaveState === "error" || props.saveError} onClick={() => { syncDraftNow(); void flushDraftSave(true); void actions.save().catch(error => message.error(errorText(error))) }}>{props.saveError ? "保存失败" : draftSaveState === "saved" ? "已保存" : draftStateLabel[draftSaveState]}</Button></Tooltip><span className="ac-header-divider"/><ThemeToggle/><Dropdown trigger={["click"]} menu={{ items: addMenuItems }}><Button className="ac-header-add" type="text" icon={<Plus size={16}/>} aria-label="新增节点"/></Dropdown></div></header>
    <div className="ac-stage" ref={stageRef}>
      <Context.Provider value={context}>
        <Dropdown trigger={["contextMenu"]} open={contextMenuOpen} onOpenChange={setContextMenuOpen} autoFocus destroyOnHidden disabled={props.loading} classNames={{ root: "ac-context-menu" }} menu={{ "aria-label": "画布右键菜单", items: contextNodeId ? [{ key: "copy", label: "创建副本", icon: <Copy size={15}/>, onClick: () => { duplicate(contextNodeId); setContextMenuOpen(false) } }, { key: "upstream", label: "查看上游引用", onClick: () => { setLibraryTab("layers"); setDrawerOpen(true); setContextMenuOpen(false) } }, { key: "delete", label: "删除节点", icon: <Trash2 size={15}/>, danger: true, disabled: nodes.find(node => node.id === contextNodeId)?.data.origin !== "canvas", onClick: () => { removeCanvasNode(contextNodeId); setContextMenuOpen(false) } }] : [{ key: "add", label: "新建节点", icon: <Plus size={15}/>, children: addMenuItems }, { type: "divider" }, { key: "assets", label: "素材库", icon: <Boxes size={15}/>, onClick: () => { setDrawerOpen(true); setContextMenuOpen(false) } }, { key: "undo", label: "撤销", icon: <Undo2 size={15}/>, disabled: !history.current.length, onClick: () => { travelHistory(false); setContextMenuOpen(false) } }, { key: "redo", label: "重做", icon: <Redo2 size={15}/>, disabled: !future.current.length, onClick: () => { travelHistory(true); setContextMenuOpen(false) } }, { key: "fit", label: "适应画布", icon: <Maximize2 size={15}/>, onClick: () => { void flow.fitView({ padding: .18, maxZoom: .85 }); setContextMenuOpen(false) } }] }}>
          <div className="ac-flow-surface" onContextMenuCapture={event => {
            if (event.target instanceof Element && event.target.closest("button,a,input,textarea,[contenteditable='true'],.react-flow__panel")) { event.stopPropagation(); return }
            const target = event.target instanceof Element ? event.target.closest(".react-flow__node") : null
            setContextNodeId(target?.getAttribute("data-id") || null)
            contextOrigin.current = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })
          }}>
            <ReactFlow connectionLineComponent={AssetConnectionLine} nodes={nodes} edges={relatedEdges} nodeTypes={nodeTypes} deleteKeyCode={null} minZoom={.15} maxZoom={1.6} nodeDragThreshold={4} nodesConnectable selectionOnDrag={!panMode} panOnDrag={panMode ? true : [1, 2]} panActivationKeyCode="Space" multiSelectionKeyCode={["Control", "Meta", "Shift"]} onNodeDragStart={() => remember()} onConnectStart={(_event, params) => { if (params.nodeId) { setPortRequest(null); connectionStart.current = { id: params.nodeId, direction: params.handleType === "source" ? "out" : "in" } } }} onConnectEnd={(event, state) => {
              const start = connectionStart.current; connectionStart.current = null
              if (!start || state.isValid || !(event instanceof MouseEvent || event instanceof TouchEvent)) return
              const point = "changedTouches" in event ? event.changedTouches[0] : event
              const stage = stageRef.current?.getBoundingClientRect()
              if (!stage || !point) return
              setPortRequest({ ...start, x: Math.max(12, Math.min(stage.width - 248, point.clientX - stage.left)), y: Math.max(12, Math.min(stage.height - 360, point.clientY - stage.top)), position: flow.screenToFlowPosition({ x: point.clientX, y: point.clientY }) })
            }} onConnect={(connection: Connection) => { if (connection.source && connection.target) addConnection(connection.source, connection.target); setPortRequest(null) }} onNodesChange={changes => {
              const next = applyNodeChanges(changes, nodesRef.current)
              nodesRef.current = next; setNodes(next)
              if (changes.some(change => change.type === "position" && !change.dragging)) { draftRef.current = serializeAssetCanvasDraft(next, edgesRef.current, draftRef.current.viewport); scheduleDraftSave() }
            }} onEdgesChange={changes => {
              const allowed = changes.filter(change => change.type !== "remove" || !graph.edges.some(edge => edge.id === change.id))
              const next = applyEdgeChanges(allowed, edgesRef.current)
              edgesRef.current = next; setEdges(next)
              if (allowed.some(change => change.type === "remove")) { syncDraftNow(); scheduleDraftSave() }
            }} onNodeClick={(event, node) => { setPortRequest(null); setContextMenuOpen(false); if (!event.ctrlKey && !event.metaKey && !event.shiftKey) choose(node.id) }} onNodeDoubleClick={(_event, node) => { if (node.data.role === "definition") openEditor(node.id, "definition"); else choose(node.id) }} onPaneClick={() => { setContextMenuOpen(false); setPortRequest(null); setComposerOpen(false); setCurrentNode(null) }} onMoveStart={() => { setMoving(true); setContextMenuOpen(false); setPortRequest(null) }} onMoveEnd={(_event, viewport) => {
              setMoving(false); setZoom(viewport.zoom)
              if (canvasReadyRef.current && Number.isFinite(viewport.x) && Number.isFinite(viewport.y) && Number.isFinite(viewport.zoom)) {
                if (draftRef.current.viewport && Math.abs(draftRef.current.viewport.x - viewport.x) < 1 && Math.abs(draftRef.current.viewport.y - viewport.y) < 1 && Math.abs(draftRef.current.viewport.zoom - viewport.zoom) < .005) return
                draftRef.current.viewport = { ...viewport }; scheduleDraftSave()
              }
            }} onInit={instance => { if (!canvasReadyRef.current) void instance.fitView({ padding: .2, maxZoom: .8 }) }}>
              {showGrid && <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="var(--ac-grid)"/>}
              {miniMap && <MiniMap position="bottom-right" pannable zoomable nodeColor="var(--studio-surface-raised)" maskColor="var(--ac-map-mask)"/>}
            </ReactFlow>
          </div>
        </Dropdown>
        {portRequest && <Dropdown open trigger={["click"]} placement="bottomLeft" onOpenChange={open => { if (!open) setPortRequest(null) }} classNames={{ root: "ac-port-menu" }} menu={{ triggerSubMenuAction: "click", "aria-label": portRequest.direction === "out" ? "引用该节点生成" : "添加上下文", items: portItems }}><span className="ac-menu-anchor" style={{ left: portRequest.x, top: portRequest.y }}/></Dropdown>}
      </Context.Provider>
      {pendingPath && <svg className="ac-pending-connection" aria-hidden="true"><path d={pendingPath} fill="none" stroke="var(--ac-link-active)" strokeWidth={1.5}/><path className="ac-connection-highlight" d={pendingPath} fill="none" stroke="var(--studio-text)" strokeWidth={2} pathLength={100}/></svg>}
      {drawerOpen ? <aside className="ac-library-panel" aria-label="素材库"><header><strong>素材库</strong><Tooltip title="收起素材库"><Button type="text" aria-label="收起素材库" icon={<ChevronsLeft size={15}/>} onClick={() => setDrawerOpen(false)}/></Tooltip></header><Tabs activeKey={libraryTab} onChange={setLibraryTab} items={[{ key: "materials", label: "素材" }, { key: "layers", label: "图层" }, { key: "history", label: "历史" }]}/><Input aria-label="搜索素材与节点" placeholder="搜索素材与节点" prefix={<Search size={14}/>} value={search} onChange={event => setSearch(event.target.value)} allowClear variant="filled"/>{libraryTab === "materials" && <Segmented size="small" aria-label="画布素材分类" value={libraryKind} onChange={value => setLibraryKind(String(value))} options={[{ value: "all", label: "全部" }, { value: "character", label: "角色" }, { value: "scene", label: "场景" }, { value: "image", label: "图片" }, { value: "video", label: "视频" }]}/>}
        <div className="ac-library-scroll">
          {libraryTab === "materials" ? <><h3>项目资产 <ChevronDown size={12}/></h3><div className="ac-library-items">{filtered.map(asset => { const image = getAssetDisplayAvatar(asset); const Icon = getKindIcon(asset.kind); return <Button type="text" key={asset.id} className={asset.id === chosenAsset?.id ? "is-selected" : ""} onClick={() => { const node = nodes.find(item => (item.data.asset as Director2Asset | undefined)?.id === asset.id && item.data.role === "image"); if (node) focusNode(node.id) }}>{image ? <img src={image} alt=""/> : <span className="ac-library-icon"><Icon size={21}/></span>}<span><strong>{asset.name}</strong><small>{kindLabel(asset.kind)}资产 · {assetReadiness(asset).label}</small></span><ChevronRight size={13}/></Button> })}</div><h3 className="ac-library-separator">画布素材</h3><div className="ac-library-items">{sidebarNodes.map(node => <Button type="text" key={node.id} className={currentNode === node.id ? "is-selected" : ""} onClick={() => focusNode(node.id)}>{assetCanvasMedia(node)?.kind === "image" ? <img src={assetCanvasMedia(node)!.url} alt=""/> : <span className="ac-library-icon">{kindIcon(String(node.data.canvasKind))}</span>}<span><strong>{String(node.data.label || "未命名节点")}</strong><small>{kindName(String(node.data.canvasKind))} · {node.data.jobError ? "生成失败" : assetCanvasMedia(node) ? "已完成" : "草稿"}</small></span><ChevronRight size={13}/></Button>)}</div>{!filtered.length && !sidebarNodes.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到相关素材"/>}</> : libraryTab === "layers" ? <div className="ac-library-layers">{nodes.filter(node => !search || String((node.data.asset as Director2Asset | undefined)?.name || node.data.label || node.data.title || "").includes(search)).map(node => <Button type="text" key={node.id} className={currentNode === node.id ? "is-selected" : ""} style={{ paddingLeft: node.parentId ? 24 : 8 }} onClick={() => focusNode(node.id)}>{node.type === "assetGroup" ? <Layers size={14}/> : kindIcon(assetCanvasNodeKind(node))}<span>{String(node.data.title || node.data.label || "节点")}</span><small>{edges.filter(edge => edge.target === node.id).length || ""}</small></Button>)}</div> : <div className="ac-library-history">{nodes.filter(node => node.data.jobId || (node.data.resultHistory as unknown[])?.length).map(node => <Button type="text" key={node.id} onClick={() => focusNode(node.id)}>{kindIcon(assetCanvasNodeKind(node))}<span><strong>{String(node.data.label || "创作记录")}</strong><small>{isActiveJobStatus(node.data.jobStatus) ? "生成中" : node.data.jobError ? "失败 · 点击重试" : "已完成"} · {(node.data.resultHistory as unknown[])?.length || 0} 个版本</small></span></Button>)}{!nodes.some(node => node.data.jobId) && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成记录会显示在这里"/>}</div>}
        </div><Dropdown trigger={["click"]} placement="topLeft" menu={{ items: addMenuItems }}><Button className="ac-library-add" type="text" icon={<Plus size={16}/>}>新建节点</Button></Dropdown></aside> : <Button className="ac-library-collapsed" icon={<Boxes size={16}/>} onClick={() => setDrawerOpen(true)}>素材库</Button>}
      {chosen && chosen.type !== "assetGroup" && !moving && <section className="ac-context-toolbar" style={{ left: Math.max(drawerOpen ? 560 : 280, Math.min((stageRef.current?.clientWidth || 1920) - 300, toolbarX)), top: Math.max(18, toolbarY) }} aria-label="选中节点工具栏">
        {chosenAsset?.kind === "character" && imageNode?.data.role === "image" ? <><Button type="text" icon={<ImageIcon size={14}/>} onClick={() => setDesignNode(chosen.id)}>角色设计</Button><Button type="text" icon={<Sparkles size={14}/>} onClick={() => { setDesignNode(chosen.id) }}>表情与面部</Button><Button type="text" icon={<Mic size={14}/>} onClick={() => actions.voice(chosenAsset.id)}>音色</Button></> : assetCanvasNodeKind(chosen) === "text" ? <><Button type="text" onClick={() => { if (selectedCanvas) patchCanvasNode(chosen.id, { fontSize: 22 }) }}>H1</Button><Button type="text" onClick={() => { if (selectedCanvas) patchCanvasNode(chosen.id, { fontSize: 18 }) }}>H2</Button><Button type="text" onClick={() => { if (selectedCanvas) patchCanvasNode(chosen.id, { fontSize: 14 }) }}>正文</Button></> : <><Button type="text" icon={<ImageIcon size={14}/>} disabled={!selectedMedia} onClick={() => { if (selectedMedia) openMediaPreview({ src: selectedMedia.url, title: selectedMedia.name }) }}>预览</Button>{["image", "character", "scene", "prop"].includes(assetCanvasNodeKind(chosen)) && <Button type="text" icon={<Video size={14}/>} onClick={() => createGeneratorFrom(chosen.id)}>生成视频</Button>}{assetCanvasNodeKind(chosen) === "video" && <Button type="text" icon={<Scissors size={14}/>} onClick={() => createNode("editor", { x: absoluteOf(nodes, chosen.id).x + 500, y: absoluteOf(nodes, chosen.id).y }, chosen.id)}>剪辑</Button>}</>}
        <Button type="text" icon={<Link2 size={14}/>} onClick={event => portMenu(chosen.id, "out", event.currentTarget)}>继续创作</Button><Dropdown trigger={["click"]} menu={{ items: [{ key: "copy", label: "创建副本", onClick: () => duplicate(chosen.id) }, ...(selectedMedia ? [{ key: "preview", label: "全屏预览", onClick: () => openMediaPreview({ src: selectedMedia.url, title: selectedMedia.name }) }] : [])] }}><Button type="text" aria-label="更多节点工具" icon={<MoreHorizontal size={15}/>} /></Dropdown>
      </section>}
      {(canvasError || modesError) && <Alert className="ac-service-error" type="error" showIcon title={canvasError || modesError} action={<Button size="small" onClick={() => window.location.reload()}>重试</Button>}/>}
      {props.loading && <div className="ac-loading"><Spin/><span>正在读取项目资产</span></div>}
      {!props.loading && !nodes.length && <div className="ac-empty-canvas"><Empty description="把故事、素材和创作放在同一张画布"/><Dropdown trigger={["click"]} menu={{ items: addMenuItems }}><Button className="ac-monochrome" icon={<Plus size={15}/>}>新建节点</Button></Dropdown></div>}
      {composerOpen && chosen && (imageNode?.data.target || selectedCanvas) && <section className="ac-composer" aria-label={`${chosenAsset?.name || selectedCanvas?.label || "节点"}创作面板`}>
        <header><span>{chosenAsset ? `${chosenAsset.name} · ${imageNode?.data.title}` : `${selectedCanvas?.label || "创作"} · ${assetCanvasNodeKind(chosen) === "image" ? "图片" : "视频"}`}</span><Button type="text" aria-label="收起创作面板" icon={<X size={15}/>} onClick={() => setComposerOpen(false)}/></header>
        {(selectedInputs.length > 0 || (imageNode && sourceReferencesOf(imageNode.data.asset).length > 0)) && <div className="ac-composer-references">{selectedInputs.filter(node => node.type !== "assetGroup").map((node, i) => <Dropdown key={node.id} trigger={["contextMenu"]} disabled={isActiveJobStatus(selectedCanvas?.jobStatus) || graph.edges.some(edge => edge.source === node.id && edge.target === chosen.id)} menu={{ items: [{ key: "up", label: "向前移动", disabled: i === 0, onClick: () => { remember(); commitGraph(nodesRef.current, moveAssetCanvasReference(edgesRef.current, chosen.id, node.id, -1)) } }, { key: "down", label: "向后移动", disabled: i === selectedInputs.length - 1, onClick: () => { remember(); commitGraph(nodesRef.current, moveAssetCanvasReference(edgesRef.current, chosen.id, node.id, 1)) } }] }}><Tag title="右键调整引用顺序" closable={!graph.edges.some(edge => edge.source === node.id && edge.target === chosen.id)} onClose={() => { remember(); commitGraph(nodesRef.current, edgesRef.current.filter(edge => !(edge.source === node.id && edge.target === chosen.id))) }} icon={kindIcon(assetCanvasNodeKind(node))}><Button type="text" onClick={() => { if (selectedCanvas && asCanvasImageNode(node) && mode?.reference_mode === "collection") patchCanvasNode(chosen.id, { prompt: `${selectedCanvas.prompt || ""}<Picture ${referenceNodesFor(chosen.id).findIndex(ref => ref.id === node.id) + 1}>` }); else focusNode(node.id) }}>{asCanvasImageNode(node) ? `图${selectedInputs.slice(0, i + 1).filter(item => asCanvasImageNode(item)).length} ` : ""}{nodeLabel(node)}</Button></Tag></Dropdown>)}{imageNode && sourceReferencesOf(imageNode.data.asset).map(ref => <Tag key={ref.id} icon={<ImageIcon size={12}/>}>{ref.filename || "参考图"}</Tag>)}</div>}
        <Input.TextArea disabled={!!working || isActiveJobStatus(selectedCanvas?.jobStatus)} aria-label={imageNode ? "节点创作提示词" : "画布创作提示词"} value={imageNode?.data.target ? assetSlotPrompt(imageNode.data.asset, imageNode.data.target) : selectedCanvas?.prompt || ""} onChange={event => { if (imageNode?.data.target) actions.prompt(imageNode.data.asset.id, imageNode.data.target, event.target.value); else patchCanvasNode(chosen.id, { prompt: event.target.value }) }} placeholder="描述你想要的画面、动作与氛围…" autoSize={{ minRows: 2, maxRows: 5 }} variant="borderless" onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); if (!working && !blocker) runChosen() } }}/>
        {(props.errors?.[chosen.id] || selectedCanvas?.jobError) && <Alert type="error" title={props.errors?.[chosen.id] || selectedCanvas?.jobError} showIcon/>}{blocker && <p className="ac-composer-hint">{blocker}</p>}
        {selectedCanvas?.jobStatus === "awaiting_refine" && <Alert type="info" title="一采已完成，是否继续精修？" action={<><Button size="small" onClick={async () => { try { applyJobToNodes(await refineCanvasJob(csrfToken, String(selectedCanvas.jobId), "skip")) } catch (error) { message.error(errorText(error)) } }}>使用一采</Button><Button size="small" onClick={async () => { try { applyJobToNodes(await refineCanvasJob(csrfToken, String(selectedCanvas.jobId), "confirm")) } catch (error) { message.error(errorText(error)) } }}>继续精修</Button></>}/>}
        <footer><div className="ac-composer-controls"><Button type="text" aria-label="添加节点引用" icon={<Plus size={17}/>} onClick={() => setReferenceOpen(true)}/><Dropdown open={referenceOpen} onOpenChange={setReferenceOpen} trigger={["click"]} placement="topLeft" classNames={{ root: "ac-reference-menu" }} menu={{ selectable: false, items: referenceMenuItems, onClick: ({ key }) => { addConnection(String(key), chosen.id); setReferenceOpen(false) } }}><Button type="text" aria-label="引用画布节点">@</Button></Dropdown><CreativeStylePicker value={selectedSettings.style || EMPTY_CREATIVE_STYLE} onChange={changeStyle} placement="topLeft" compact disabled={!!working || isActiveJobStatus(selectedCanvas?.jobStatus)}/>
          {selectedCanvas ? <><Select size="small" variant="filled" aria-label="创作工作流" value={selectedCanvas.workflowId || undefined} placeholder="选择模型" disabled={isActiveJobStatus(selectedCanvas.jobStatus)} showSearch filterOption={false} onSearch={setWorkflowQuery} onOpenChange={open => { if (!open) setWorkflowQuery("") }} onChange={id => { const next = modes.find(item => item.id === id) || null; patchCanvasNode(chosen.id, { workflowId: id, optionValues: defaultGeneratorOptionValues(next) }) }} options={canvasWorkflowPickerOptions} optionRender={option => <WorkflowOptionRow item={option.data as WorkflowSelectOption} />} popupMatchSelectWidth={360}/>{parameterFields.primary.map(([name, definition]) => <Tooltip key={name} title={definition.label}><span><GeneratorOptionField disabled={isActiveJobStatus(selectedCanvas?.jobStatus)} name={name} definition={definition} value={selectedCanvas.optionValues?.[name] ?? definition.default} onChange={setOption}/></span></Tooltip>)}{parameterFields.advanced.length > 0 && <Popover trigger="click" placement="topLeft" arrow={false} content={<div className="ac-advanced-options">{parameterFields.advanced.map(([name, definition]) => <div key={name}><GeneratorOptionField disabled={isActiveJobStatus(selectedCanvas?.jobStatus)} name={name} definition={definition} value={selectedCanvas.optionValues?.[name] ?? definition.default} onChange={setOption}/></div>)}</div>}><Button type="text">更多设置<ChevronDown size={12}/></Button></Popover>}</> : <><Select size="small" variant="filled" allowClear aria-label="资产图片模型" placeholder={defaultImageMode?.name || "默认图片模型"} value={(selectedSettings as { model?: string }).model || undefined} disabled={!!working} popupMatchSelectWidth={360} showSearch filterOption={false} onSearch={setSlotModelQuery} onOpenChange={open => { if (!open) setSlotModelQuery("") }} options={imageModePickerOptions} optionRender={option => <WorkflowOptionRow item={option.data as WorkflowSelectOption} />} onChange={id => { if (!imageNode?.data.target) return; const next = id ? modes.find(item => item.id === id) || null : null; void actions.configure(imageNode.data.asset.id, imageNode.data.target, { model: id || undefined, ...(id ? { aspectRatio: normalizeSlotAspect(next, slotSettings?.aspectRatio) } : {}) }).catch(error => message.error(errorText(error))) }}/><Tooltip title={imageNode?.data.target?.type === "identity" ? "设定板比例" : undefined}><Select size="small" variant="filled" aria-label={imageNode?.data.target?.type === "identity" ? "设定板比例" : "资产图片比例"} value={(selectedSettings as { aspectRatio?: string }).aspectRatio || "16:9"} disabled={!!working} options={slotAspectOptions} onChange={value => { if (imageNode?.data.target) void actions.configure(imageNode.data.asset.id, imageNode.data.target, { aspectRatio: value }) }}/></Tooltip></>}
        </div><div className="ac-send-controls"><small>Ctrl + Enter</small>{selectedCanvas && isActiveJobStatus(selectedCanvas.jobStatus) ? <Tooltip title="停止生成"><Button shape="circle" aria-label="停止生成" loading={selectedCanvas.jobStatus === "canceling"} icon={<X size={16}/>} onClick={async () => { if (!selectedCanvas.jobId) return; try { applyJobToNodes(await cancelCanvasJob(csrfToken, selectedCanvas.jobId)) } catch (error) { message.error(errorText(error)) } }}/></Tooltip> : <Tooltip title={`${imageNode || chosen.data.canvasKind === "image" ? "生成图片" : "生成视频"} · Ctrl + Enter`}><Button className="ac-send ac-monochrome" shape="circle" aria-label={imageNode || chosen.data.canvasKind === "image" ? "生成图片" : "生成视频"} icon={<ArrowUp size={20}/>} loading={working === chosen.id} disabled={props.loading || !!working || !!blocker || (!imageNode && (!mode || !canvasProjectRef.current)) || (imageNode ? !assetSlotPrompt(imageNode.data.asset, imageNode.data.target!).trim() && !sourceReferencesOf(imageNode.data.asset).length : !selectedCanvas?.prompt?.trim() && !selectedInputs.some(node => assetCanvasNodeKind(node) === "text"))} onClick={runChosen}/></Tooltip>}</div></footer>
      </section>}
      <div className="ac-viewport-tools"><Tooltip title="撤销 Ctrl+Z"><Button type="text" aria-label="撤销画布操作" disabled={!history.current.length} icon={<Undo2 size={15}/>} onClick={() => travelHistory(false)}/></Tooltip><Tooltip title="重做 Ctrl+Y"><Button type="text" aria-label="重做画布操作" disabled={!future.current.length} icon={<Redo2 size={15}/>} onClick={() => travelHistory(true)}/></Tooltip><Dropdown trigger={["click"]} menu={{ items: [{ key: "links", label: linksVisible ? "隐藏连线" : "显示连线", onClick: () => setLinksVisible(!linksVisible) }, { key: "grid", label: showGrid ? "隐藏网格" : "显示网格", onClick: () => setShowGrid(!showGrid) }] }}><Button type="text" aria-label="画布显示设置" icon={<Link2 size={16}/>} /></Dropdown><Tooltip title="整理节点"><Button type="text" aria-label="整理画布节点" icon={<LayoutGrid size={16}/>} onClick={() => { remember(); let x = 360; commitGraph(nodes.map(node => { if (node.parentId) return node; const next = { ...node, position: { x, y: 100 } }; x += (nodeWidth(node) || 400) + 130; return next })); void flow.fitView({ padding: .2, maxZoom: .7 }) }}/></Tooltip><Tooltip title="适应画布 Ctrl+0"><Button type="text" aria-label="适应全部节点" icon={<Maximize2 size={15}/>} onClick={() => void flow.fitView({ padding: .18, maxZoom: .85 })}/></Tooltip><Button type="text" aria-label="缩小画布" icon={<ZoomOut size={15}/>} onClick={() => void flow.zoomOut()}/><Button type="text" aria-label="放大画布" icon={<ZoomIn size={15}/>} onClick={() => void flow.zoomIn()}/><Dropdown trigger={["click"]} menu={{ items: [.25, .5, .75, 1, 1.25, 1.5].map(value => ({ key: String(value), label: `${value * 100}%`, onClick: () => void flow.zoomTo(value) })) }}><Button type="text" className="ac-zoom-value" aria-label="设置画布缩放">{Math.round(zoom * 100)}%<ChevronDown size={12}/></Button></Dropdown></div>
      <div className="ac-bottom-tools"><Dropdown trigger={["click"]} placement="topLeft" menu={{ items: addMenuItems }}><Button className="ac-add-button ac-monochrome" aria-label="新建画布节点" icon={<Plus size={20}/>} /></Dropdown><Tooltip title="图层"><Button type="text" aria-label="查看画布图层" icon={<Layers size={19}/>} onClick={() => { setDrawerOpen(true); setLibraryTab("layers") }}/></Tooltip><Tooltip title="小地图"><Button type="text" aria-label="画布小地图" aria-pressed={miniMap} icon={<MapIcon size={19}/>} onClick={() => setMiniMap(!miniMap)}/></Tooltip><Tooltip title="快捷键"><Button type="text" aria-label="画布快捷键" icon={<Keyboard size={19}/>} onClick={() => setShortcutsOpen(true)}/></Tooltip><Tooltip title="选择 V"><Button type="text" aria-label="画布选择工具" aria-pressed={!panMode} icon={<MousePointer2 size={19}/>} onClick={() => setPanMode(false)}/></Tooltip><Tooltip title="抓手 H / 空格拖动"><Button type="text" aria-label="画布抓手工具" aria-pressed={panMode} icon={<Hand size={19}/>} onClick={() => setPanMode(true)}/></Tooltip></div>
      {actions.continue && <Button className="ac-next-step ac-monochrome" icon={<ArrowRight size={15}/>} iconPlacement="end" onClick={() => { syncDraftNow(); void flushDraftSave(); void actions.continue?.() }}>进入分镜</Button>}
    </div>
    <Modal title={editKind === "definition" ? `${chosenAsset ? kindLabel(chosenAsset.kind) : "资产"}信息` : `${chosenAsset?.kind === "scene" ? "场景" : chosenAsset?.kind === "prop" ? "道具" : "角色与形象"}信息`} open={!!editNode} onCancel={() => setEditNode(null)} onOk={() => void saveEditor()} confirmLoading={editing} okText="保存" cancelText="取消" width={760} className="ac-information-modal" destroyOnHidden>
      <div className="ac-information-grid"><Form layout="vertical"><Form.Item label={editKind === "definition" ? "名称" : chosenAsset?.kind === "scene" ? "视角名称" : "形象名称"} required><Input aria-label="画布节点名称" value={editName} onChange={event => setEditName(event.target.value)} maxLength={120}/></Form.Item>{editKind === "definition" ? <><Form.Item label="定位"><Input value={editRole} onChange={event => setEditRole(event.target.value)}/></Form.Item><Form.Item label="创作设定"><Input.TextArea aria-label="画布资产设定" value={editText} onChange={event => setEditText(event.target.value)} autoSize={{ minRows: 7, maxRows: 12 }}/></Form.Item></> : <><Form.Item label={chosenAsset?.kind === "scene" ? "所属场景" : "所属角色"}><Input value={chosenAsset?.name} readOnly/></Form.Item><Form.Item label="出现集数"><Input readOnly value={String(chosenAsset?.extra?.episodes || chosenAsset?.extra?.episode_numbers || "全剧复用")}/></Form.Item><Form.Item label="设定描述"><Input.TextArea value={chosenAsset ? assetDefinitionText(chosenAsset) : ""} readOnly autoSize={{ minRows: 4, maxRows: 8 }}/></Form.Item></>}</Form>{chosenAsset?.kind === "character" && <aside><h3>形象与音色</h3>{imageNode?.data.image ? <img src={imageNode.data.image} alt="角色形象"/> : <div className="ac-information-empty"><ImageIcon size={32}/><span>暂无形象图</span></div>}<Button icon={<Mic size={14}/>} onClick={() => { setEditNode(null); actions.voice(chosenAsset.id) }}>设置角色音色</Button><Button type="text" icon={<Plus size={14}/>} onClick={() => { setEditNode(null); actions.addLook(chosenAsset.id) }}>新增形象</Button></aside>}</div>
    </Modal>
    <CharacterDesignModal open={!!designNode} value={designValue} onCancel={() => setDesignNode(null)} onSave={async design => { try { if (designAsset && designTargetSlot) await actions.configure(designAsset.id, designTargetSlot, { design }); else if (designNode) patchCanvasNode(designNode, { design }); setDesignNode(null) } catch (error) { message.error(errorText(error, "角色设计保存失败")) } }}/>
    <Modal title="画布快捷键" open={shortcutsOpen} onCancel={() => setShortcutsOpen(false)} footer={<Button onClick={() => setShortcutsOpen(false)}>知道了</Button>} width={420}><div className="ac-shortcuts">{[["新建节点", "Tab"], ["选择 / 抓手", "V / H"], ["临时平移", "Space + 拖动"], ["撤销 / 重做", "Ctrl + Z / Y"], ["保存画布", "Ctrl + S"], ["适应全部", "Ctrl + 0"], ["生成", "Ctrl + Enter"], ["取消连线 / 菜单", "Esc"]].map(([label, key]) => <div key={label}><span>{label}</span><kbd>{key}</kbd></div>)}</div></Modal>
    <input className="ac-file-input" type="file" accept={fileTarget && nodes.find(node => node.id === fileTarget)?.data.canvasKind === "audio" ? "audio/*" : fileTarget && nodes.find(node => node.id === fileTarget)?.data.canvasKind === "video" ? "video/*" : "image/jpeg,image/png,image/webp,image/gif"} multiple={nodes.find(node => node.id === fileTarget)?.data.role === "references"} ref={uploadRef} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ""; void uploadFiles(files) }}/>
    <AssetPickerModal open={mediaPicker} onClose={() => setMediaPicker(false)} onPick={file => void uploadFiles([file])}/>
  </div>
}

export function AssetCanvasCreateModal({ open, kind, busy, onCancel, onSubmit }: { open: boolean; kind: string; busy: boolean; onCancel: () => void; onSubmit: (name: string, description: string) => void }) {
  const [name, setName] = useState(""), [description, setDescription] = useState("")
  useEffect(() => { if (open) { setName(""); setDescription("") } }, [open])
  return <Modal title={`新增${kindLabel(kind)}节点`} open={open} onCancel={onCancel} okText="创建并进入画布" cancelText="取消" confirmLoading={busy} onOk={() => { if (!name.trim()) message.warning("请输入名称"); else onSubmit(name.trim(), description) }} destroyOnHidden width={480}><Form layout="vertical"><Form.Item label={`${kindLabel(kind)}名称`} required><Input aria-label="新资产名称" value={name} onChange={event => setName(event.target.value)} maxLength={120}/></Form.Item><Form.Item label="初始设定（选填）"><Input.TextArea aria-label="新资产设定" value={description} onChange={event => setDescription(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="可以先创建节点，再在画布上完善"/></Form.Item></Form></Modal>
}
