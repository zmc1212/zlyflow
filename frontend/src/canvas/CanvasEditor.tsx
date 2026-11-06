import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import {
  Background,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  ViewportPortal,
  getBezierPath,
  useEdgesState,
  useNodesState,
  useOnSelectionChange,
  useReactFlow,
  useViewport,
  type Connection,
  type EdgeTypes,
  type FinalConnectionState,
  type MiniMapNodeProps,
  type NodeTypes,
  type NodeChange,
  type OnConnectStartParams,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import {
  Alert, Button, Drawer, Dropdown, Empty, Input, Menu, Modal, Popover, Segmented, Space, Spin, Tag, Tooltip,
  message, type MenuProps,
} from "antd"
import {
  AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignHorizontalSpaceAround,
  AlignHorizontalSpaceBetween, AlignStartHorizontal, AlignStartVertical, AlignVerticalSpaceBetween,
  Check, ChevronDown, ChevronLeft, CircleOff, ClipboardPaste, CopyPlus, Download, Frame, GitBranch, Hand, History, Image as ImageIcon, ImagePlus, Images, Keyboard,
  Focus, Link2, LoaderCircle, Map as MapIcon, Minus, MoreHorizontal, MousePointer2, MoveDown, MoveRight, Pencil, Plus, Redo2, RefreshCw,
  PanelRight, Search, Settings, SlidersHorizontal, Sparkles, Square, Trash2, Type, Undo2, Upload, Video, Waypoints,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState,
  type ChangeEvent,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react"
import { useSearchParams } from "react-router-dom"
import { generateJobPath } from "../paths"
import { ApiRequestError } from "../api"
import { useStudioTheme } from "../ThemeProvider"
import CanvasExportDialog from "./CanvasExportDialog"
import CanvasFlowEdge from "./CanvasFlowEdge"
import { reorderCanvasReferenceEdges } from "./canvas-composer"
import { canvasConnectEdge, canvasConnectMenuPosition, canvasConnectTargets } from "./canvas-connections"
import { claimCanvasRecovery, clearCanvasRecovery, normalizedCanvasContent, readCanvasRecovery, resolveCanvasRecovery, writeCanvasRecovery } from "./canvas-recovery"
import {
  getCanvasProject,
  listCanvasVersions,
  queryCanvasLibraryItems,
  renameCanvasProject,
  restoreCanvasVersion,
  saveCanvasDraft,
} from "./canvas-api"
import {
  alignCanvasNodes,
  buildEdgeId,
  CANVAS_ASSET_DRAG_TYPE,
  CANVAS_LIBRARY_NODE_SIZES,
  CANVAS_MAX_ZOOM,
  CANVAS_MIN_ZOOM,
  canvasHistoryState,
  canvasNodeSize,
  canvasViewportChanged,
  copyCanvasClipboard,
  createArtboardNode,
  createCanvasHistory,
  createGeneratorNode,
  createImageNode,
  createLibraryNode,
  createTextNode,
  createVideoNode,
  decodeCanvasAssetDrag,
  distributeCanvasNodes,
  duplicateCanvasSelection,
  encodeCanvasAssetDrag,
  formatCanvasTime,
  isSafeMediaUrl,
  isUsableLibraryItem,
  isCoverOnlyCanvasChange,
  libraryItemUrl,
  findCanvasFreePosition,
  nextCanvasBranchSlot,
  parseCanvasContent,
  pasteCanvasClipboard,
  pushCanvasHistory,
  readCanvasSettings,
  redoCanvasHistory,
  serializeCanvasDraft,
  undoCanvasHistory,
  type CanvasAlignMode,
  type CanvasBranchDirection,
  type CanvasClipboard,
  type CanvasCoverPatch,
  type CanvasDistributeAxis,
  type CanvasEdge,
  type CanvasHistory,
  type CanvasLibraryItem,
  type CanvasMediaKind,
  type CanvasNode,
  type CanvasNodeData,
  type CanvasProjectDetail,
  type CanvasSettings,
  type CanvasVersion,
  type CanvasViewport,
} from "./canvas-model"
import {
  CANVAS_CONNECTION_MODE_OPTIONS,
  CANVAS_GENERATION_MODE_OPTIONS,
  compactCanvasEdgeIds,
} from "./canvas-view-modes"
import {
  CANVAS_IMPORT_MAX_BYTES,
  CANVAS_INSERT_ITEM_PARAM,
  CANVAS_INSERT_JOB_PARAM,
  CANVAS_INSERT_OUTPUT_PARAM,
  CANVAS_LIBRARY_PAGE_SIZE,
  canvasExportFileName,
  canvasLibraryItemKey,
  findCanvasInsertLibraryItem,
  mergeCanvasLibraryItems,
  parseCanvasImportContent,
  readCanvasAssetInsert,
} from "./canvas-manage"
import {
  appendCanvasRunSnapshot,
  buildCanvasRunSnapshot,
  cancelCanvasJob,
  canvasImageNodeFile,
  canvasJobResult,
  canvasJobResults,
  canvasJobLiveDetails,
  canvasPendingResultFill,
  canvasPromptEligible,
  canvasReferenceEligible,
  canvasResultHistory,
  canvasResultVersionIndex,
  canvasResultVersionPatch,
  selectCanvasResultVersion,
  canvasRunSnapshotForJob,
  canvasWorkflowList,
  defaultGeneratorOptionValues,
  fetchCanvasJob,
  fetchCanvasModes,
  generatorPromptInfo,
  generatorReferenceIssue,
  generatorResultFromNodeData,
  incomingGeneratorPromptNodes,
  incomingGeneratorReferenceNodes,
  isCanvasJobActive,
  pickCanvasGenerationMode,
  resolveGeneratorPrompt,
  refineCanvasJob,
  serializeGeneratorOptionValues,
  submitCanvasJob,
  validateGeneratorInput,
  type CanvasGeneratorLive,
  type CanvasGeneratorPromptState,
  type CanvasJob,
  type CanvasJobResult,
} from "./canvas-generation"
import {
  canvasByteSize,
  canvasConflictVersion,
  canvasContentSizeLevel,
  createCanvasSaveQueue,
  formatCanvasBytes,
  isCanvasSaveRetryable,
  nextCanvasSaveRetryDelay,
  saveStateAfterCanvasEdit,
  saveStateAfterCanvasSave,
  shouldVirtualizeCanvasNodes,
  type CanvasSaveState,
  type CanvasSaveOutcome,
} from "./canvas-save"
import { CanvasSidePanel, type CanvasPanelTab } from "./CanvasSidePanel"
import {
  ArtboardCanvasNode,
  CanvasGeneratorContext,
  CanvasMediaPreviewContext,
  CanvasNodeActionsContext,
  GeneratorCanvasNode,
  ImageCanvasNode,
  TextCanvasNode,
  UnknownCanvasNode,
  VideoCanvasNode,
  type CanvasMediaPreview,
  type CanvasNodeActions,
} from "./CanvasNodes"
import { baseNodeTypes } from "./node-registry"

const edgeTypes: EdgeTypes = {
  canvasFlow: CanvasFlowEdge,
}

function edgeStroke(node: CanvasNode | undefined): string {
  if (node?.type === "text") return "var(--canvas-text-tone)"
  if (node?.type === "video") return "var(--canvas-video-tone)"
  if (node?.type === "generator") {
    return node.data.resultKind === "video" ? "var(--canvas-video-tone)" : "var(--studio-primary)"
  }
  return "var(--canvas-image-tone)"
}

const saveStateLabels: Record<CanvasSaveState, string> = {
  saved: "已保存",
  dirty: "待保存",
  saving: "保存中",
  retrying: "重试中",
  error: "保存失败",
  conflict: "版本冲突",
}

type CanvasTool = "select" | "pan"

type CanvasGuideLines = {
  vertical: number[]
  horizontal: number[]
}

type CanvasContextMenuState =
  | { kind: "pane"; x: number; y: number; flow: { x: number; y: number } }
  | { kind: "node"; x: number; y: number; nodeId: string }
  | { kind: "selection"; x: number; y: number }

type CanvasConnectMenuState = {
  x: number
  y: number
  from: { x: number; y: number }
  flow: { x: number; y: number }
  sourceId: string
  sourceHandle: string
}

type CanvasConnectStartState = OnConnectStartParams & {
  screen: { x: number; y: number }
}

const EMPTY_GUIDES: CanvasGuideLines = { vertical: [], horizontal: [] }

function sameGuides(left: CanvasGuideLines, right: CanvasGuideLines): boolean {
  return left.vertical.length === right.vertical.length
    && left.horizontal.length === right.horizontal.length
    && left.vertical.every((value, index) => value === right.vertical[index])
    && left.horizontal.every((value, index) => value === right.horizontal[index])
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败"
}

function settingsRecord(settings: CanvasSettings): Record<string, unknown> {
  return { ...settings }
}

function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && Boolean(target.closest("input, textarea, select, [contenteditable='true']"))
}

function eventClientPoint(event: MouseEvent | TouchEvent): { x: number; y: number } {
  if ("clientX" in event) return { x: event.clientX, y: event.clientY }
  const touch = event.changedTouches[0] ?? event.touches[0]
  return touch ? { x: touch.clientX, y: touch.clientY } : { x: 0, y: 0 }
}

function computeSnapGuides(
  moving: CanvasNode[],
  others: CanvasNode[],
  threshold: number,
): { dx: number; dy: number; guides: CanvasGuideLines } {
  if (!moving.length || !others.length) return { dx: 0, dy: 0, guides: EMPTY_GUIDES }
  const boxes = moving.map((node) => {
    const size = canvasNodeSize(node)
    return {
      x: node.position.x,
      y: node.position.y,
      width: size.width,
      height: size.height,
    }
  })
  const left = Math.min(...boxes.map((box) => box.x))
  const right = Math.max(...boxes.map((box) => box.x + box.width))
  const top = Math.min(...boxes.map((box) => box.y))
  const bottom = Math.max(...boxes.map((box) => box.y + box.height))
  const movingX = [left, (left + right) / 2, right]
  const movingY = [top, (top + bottom) / 2, bottom]
  let bestX: { delta: number; line: number } | null = null
  let bestY: { delta: number; line: number } | null = null

  for (const other of others) {
    const size = canvasNodeSize(other)
    const otherX = [other.position.x, other.position.x + size.width / 2, other.position.x + size.width]
    const otherY = [other.position.y, other.position.y + size.height / 2, other.position.y + size.height]
    for (const line of otherX) {
      for (const anchor of movingX) {
        const delta = line - anchor
        if (Math.abs(delta) <= threshold && (!bestX || Math.abs(delta) < Math.abs(bestX.delta))) {
          bestX = { delta, line }
        }
      }
    }
    for (const line of otherY) {
      for (const anchor of movingY) {
        const delta = line - anchor
        if (Math.abs(delta) <= threshold && (!bestY || Math.abs(delta) < Math.abs(bestY.delta))) {
          bestY = { delta, line }
        }
      }
    }
  }

  return {
    dx: bestX?.delta ?? 0,
    dy: bestY?.delta ?? 0,
    guides: {
      vertical: bestX ? [bestX.line] : [],
      horizontal: bestY ? [bestY.line] : [],
    },
  }
}

function canvasNodeMediaUrl(node: CanvasNode): string | null {
  if (node.type === "image" || node.type === "video") {
    const url = typeof node.data.url === "string" ? node.data.url.trim() : ""
    return url || null
  }
  if (node.type === "generator") return generatorResultFromNodeData(node.data)?.url ?? null
  return null
}

const connectionModeGlyphs = {
  off: <CircleOff size={16} />,
  compact: <GitBranch size={16} />,
  full: <Link2 size={16} />,
} as const

const generationModeGlyphs = {
  independent: <CopyPlus size={16} />,
  aggregate: <Images size={16} />,
} as const

function CanvasViewModeMenu({ settings, onChange }: {
  settings: CanvasSettings
  onChange: (patch: Partial<CanvasSettings>) => void
}) {
  return (
    <div className="canvas-viewmode-menu">
      <section className="canvas-viewmode-group" aria-label="连线">
        <span className="canvas-viewmode-group-title">连线</span>
        {CANVAS_CONNECTION_MODE_OPTIONS.map((option) => {
          const active = settings.connectionMode === option.value
          return (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={active}
              className={`canvas-viewmode-option${active ? " is-active" : ""}`}
              onClick={() => onChange({ connectionMode: option.value })}
            >
              <span className="canvas-viewmode-glyph">{connectionModeGlyphs[option.value]}</span>
              <span className="canvas-viewmode-copy"><strong>{option.label}</strong><small>{option.description}</small></span>
              {active ? <Check size={15} className="canvas-viewmode-check" /> : null}
            </button>
          )
        })}
      </section>
      <section className="canvas-viewmode-group" aria-label="生成节点展示方式">
        <span className="canvas-viewmode-group-title">生成节点展示方式</span>
        {CANVAS_GENERATION_MODE_OPTIONS.map((option) => {
          const active = settings.generationDisplayMode === option.value
          return (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={active}
              className={`canvas-viewmode-option${active ? " is-active" : ""}`}
              onClick={() => onChange({ generationDisplayMode: option.value })}
            >
              <span className="canvas-viewmode-glyph">{generationModeGlyphs[option.value]}</span>
              <span className="canvas-viewmode-copy"><strong>{option.label}</strong><small>{option.description}</small></span>
              {active ? <Check size={15} className="canvas-viewmode-check" /> : null}
            </button>
          )
        })}
      </section>
    </div>
  )
}

export default function CanvasEditor(props: {
  project: CanvasProjectDetail
  csrfToken: string
  onBack: () => void
}) {
  return (
    <ReactFlowProvider>
      <CanvasEditorInner {...props} />
    </ReactFlowProvider>
  )
}

function CanvasEditorInner({ project, csrfToken, onBack }: {
  project: CanvasProjectDetail
  csrfToken: string
  onBack: () => void
}) {
  const { mode: themeMode } = useStudioTheme()
  const {
    screenToFlowPosition, setViewport, updateNodeData, getViewport, fitView, zoomIn, zoomOut, zoomTo, setCenter,
  } = useReactFlow<CanvasNode, CanvasEdge>()
  const { zoom } = useViewport()
  const [recoveryOwner] = useState(() => Symbol(project.id))
  const recovery = useMemo(() => resolveCanvasRecovery(project.content, project.version, readCanvasRecovery(project.id)), [project.id, project.content, project.version])
  const initial = useMemo(() => parseCanvasContent(recovery.content), [recovery.content])
  const initialSettings = useMemo(() => readCanvasSettings(initial.canvasSettings), [initial.canvasSettings])
  const initialSnapshot = useMemo(
    () => serializeCanvasDraft(initial.nodes, initial.edges, { canvasSettings: settingsRecord(initialSettings) }),
    [initial, initialSettings],
  )
  const settingsRef = useRef<CanvasSettings>(initialSettings)
  const viewportRef = useRef<CanvasViewport | null>(initialSettings.viewport)
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(initial.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>(initial.edges)
  const handleNodesChange = useCallback((changes: NodeChange<CanvasNode>[]) => {
    const removed = new Set(changes.filter((change) => change.type === "remove").map((change) => change.id))
    if (removed.size) setEdges((current) => current.filter((edge) => !removed.has(edge.source) && !removed.has(edge.target)))
    onNodesChange(changes)
  }, [onNodesChange, setEdges])
  const [settings, setSettings] = useState<CanvasSettings>(initialSettings)
  const [title, setTitle] = useState(project.title)
  const titleRef = useRef(title)
  titleRef.current = title
  const savedTitleRef = useRef(project.title)
  const titleSaveRef = useRef<Promise<boolean>>(Promise.resolve(true))
  const [leaving, setLeaving] = useState(false)
  const [saveState, setSaveState] = useState<CanvasSaveState>(recovery.conflict ? "conflict" : recovery.restored ? "dirty" : "saved")
  const [retryAttempt, setRetryAttempt] = useState(0)
  const [retryDelayMs, setRetryDelayMs] = useState(0)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [contentBytes, setContentBytes] = useState(() => canvasByteSize(initialSnapshot))
  const [savedAt, setSavedAt] = useState(project.draft_updated_at ?? project.updated_at)
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([])
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<string[]>([])
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [tool, setTool] = useState<CanvasTool>("select")
  const [panelOpen, setPanelOpen] = useState(false)
  const [panelTab, setPanelTab] = useState<CanvasPanelTab>("properties")
  const [contextMenu, setContextMenu] = useState<CanvasContextMenuState | null>(null)
  const [connectMenu, setConnectMenu] = useState<CanvasConnectMenuState | null>(null)
  const connectStartRef = useRef<CanvasConnectStartState | null>(null)
  const [guides, setGuides] = useState<CanvasGuideLines>(EMPTY_GUIDES)
  const [clipboardCount, setClipboardCount] = useState(0)
  const [recentEdgeId, setRecentEdgeId] = useState<string | null>(null)
  const [addImageOpen, setAddImageOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [imageUrl, setImageUrl] = useState("")
  const [versions, setVersions] = useState<CanvasVersion[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [conflictVersionNumber, setConflictVersionNumber] = useState<number | null>(recovery.conflict ? project.version : null)
  const [reloading, setReloading] = useState(false)
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false })
  const [canvasSettingsPinned, setCanvasSettingsPinned] = useState(false)
  const [assetOpen, setAssetOpen] = useState(false)
  const [assetKind, setAssetKind] = useState<CanvasMediaKind>("image")
  const [assetTargetNodeId, setAssetTargetNodeId] = useState<string | null>(null)
  const [assetGeneratorId, setAssetGeneratorId] = useState<string | null>(null)
  const [assetReferenceSourceId, setAssetReferenceSourceId] = useState<string | null>(null)
  const [assetSearch, setAssetSearch] = useState("")
  const [librarySearch, setLibrarySearch] = useState("")
  const [pendingImport, setPendingImport] = useState<{
    nodeCount: number
    edgeCount: number
    replace: () => void
  } | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const insertRequest = readCanvasAssetInsert(searchParams)
  const [preview, setPreview] = useState<CanvasMediaPreview | null>(null)
  const [previewZoom, setPreviewZoom] = useState(1)
  useEffect(() => { setPreviewZoom(1) }, [preview?.url])
  const [draggingAsset, setDraggingAsset] = useState<CanvasLibraryItem | null>(null)
  const [dropPoint, setDropPoint] = useState<{ x: number; y: number } | null>(null)
  const [liveJobs, setLiveJobs] = useState<Record<string, CanvasGeneratorLive>>({})
  const [submittingGeneratorIds, setSubmittingGeneratorIds] = useState<Set<string>>(new Set())
  const pendingGeneratorIdsRef = useRef(new Set<string>())

  const beginGeneratorAction = useCallback((nodeId: string) => {
    if (pendingGeneratorIdsRef.current.has(nodeId)) return false
    pendingGeneratorIdsRef.current.add(nodeId)
    setSubmittingGeneratorIds(new Set(pendingGeneratorIdsRef.current))
    return true
  }, [])
  const endGeneratorAction = useCallback((nodeId: string) => {
    pendingGeneratorIdsRef.current.delete(nodeId)
    if (mountedRef.current) setSubmittingGeneratorIds(new Set(pendingGeneratorIdsRef.current))
  }, [])

  const stageRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const dragDepthRef = useRef(0)
  const clipboardRef = useRef<CanvasClipboard | null>(null)
  const pasteCountRef = useRef(0)
  const pendingAddPointRef = useRef<{ x: number; y: number } | null>(null)
  const autoInsertedJobsRef = useRef<Set<string>>(new Set())
  const consumedInsertAssetRef = useRef<string | null>(null)
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes
  const edgesRef = useRef(edges)
  edgesRef.current = edges
  const liveJobsRef = useRef(liveJobs)
  liveJobsRef.current = liveJobs
  const nodeDataSnapshotRef = useRef(new Map<string, { type?: string; data: CanvasNode["data"] }>())
  const [nodeDataRevision, setNodeDataRevision] = useState(0)
  useEffect(() => {
    const previous = nodeDataSnapshotRef.current
    let changed = previous.size !== nodes.length
    if (!changed) {
      for (const node of nodes) {
        const before = previous.get(node.id)
        if (!before || before.type !== node.type || before.data !== node.data) {
          changed = true
          break
        }
      }
    }
    if (!changed) return
    const next = new Map<string, { type?: string; data: CanvasNode["data"] }>()
    for (const node of nodes) next.set(node.id, { type: node.type, data: node.data })
    nodeDataSnapshotRef.current = next
    setNodeDataRevision((revision) => revision + 1)
  }, [nodes])
  const serializeCurrent = useCallback(
    () => serializeCanvasDraft(nodesRef.current, edgesRef.current, {
      canvasSettings: settingsRecord({ ...settingsRef.current, viewport: viewportRef.current }),
    }),
    [],
  )
  const versionRef = useRef(recovery.baseVersion)
  const lastSavedRef = useRef(recovery.savedContent)
  const historyRef = useRef(createCanvasHistory(initialSnapshot))
  const historyTimerRef = useRef<number | null>(null)
  const suppressHistoryRef = useRef(false)
  const coverOnlyChangeRef = useRef(false)
  const savingRef = useRef(false)
  const conflictRef = useRef(recovery.conflict)
  const retryTimerRef = useRef<number | null>(null)
  const retryCountRef = useRef(0)
  const saveDraftRef = useRef<(notify: boolean) => Promise<CanvasSaveOutcome>>(async () => "saved")
  const saveDraft = useMemo(() => createCanvasSaveQueue((notify) => saveDraftRef.current(notify)), [])
  const initialEffectRef = useRef(true)
  const mountedRef = useRef(true)
  const recoveryNoticeRef = useRef(false)
  const backupCurrent = useCallback(() => {
    const content = serializeCurrent()
    if (content === lastSavedRef.current) clearCanvasRecovery(project.id, content)
    else writeCanvasRecovery(project.id, { baseVersion: versionRef.current, content }, undefined, recoveryOwner)
  }, [project.id, recoveryOwner, serializeCurrent])

  const [dragSettledRevision, setDragSettledRevision] = useState(0)
  const panelNodesRef = useRef(nodes)
  const panelNodesRevisionRef = useRef(-1)
  const panelNodes = useMemo(() => {
    if (panelNodesRevisionRef.current !== dragSettledRevision) {
      panelNodesRevisionRef.current = dragSettledRevision
      panelNodesRef.current = nodes
      return nodes
    }
    const previous = panelNodesRef.current
    const unchanged = previous.length === nodes.length && nodes.every((node, index) => {
      const before = previous[index]
      if (before === node) return true
      return before.id === node.id
        && before.type === node.type
        && before.data === node.data
        && before.selected === node.selected
        && before.dragging === node.dragging
        && before.width === node.width
        && before.height === node.height
        && before.measured === node.measured
        && before.style === node.style
        && (node.dragging === true
          || (before.position.x === node.position.x && before.position.y === node.position.y))
    })
    if (unchanged) return previous
    panelNodesRef.current = nodes
    return nodes
  }, [nodes, dragSettledRevision])
  const selectedNodeIdSet = useMemo(() => new Set(selectedNodeIds), [selectedNodeIds])
  const selectedNodes = useMemo(
    () => panelNodes.filter((node) => selectedNodeIdSet.has(node.id)),
    [panelNodes, selectedNodeIdSet],
  )
  const selectedNode = selectedNodes.length === 1 ? selectedNodes[0] : null
  const selectedNodeId = selectedNode?.id ?? null
  const selectionCount = selectedNodeIds.length + selectedEdgeIds.length
  const assetTargetNode = useMemo(
    () => assetTargetNodeId ? nodes.find((node) => node.id === assetTargetNodeId) ?? null : null,
    [assetTargetNodeId, nodes],
  )

  const modesQuery = useQuery({
    queryKey: ["canvas-modes"],
    queryFn: fetchCanvasModes,
    staleTime: 5 * 60_000,
    retry: 1,
  })
  const generationModes = useMemo(
    () => canvasWorkflowList(modesQuery.data?.modes ?? []),
    [modesQuery.data],
  )
  const selectedGeneratorReferences = useMemo(
    () => selectedNode?.type === "generator"
      ? incomingGeneratorReferenceNodes(nodesRef.current, edges, selectedNode.id)
      : [],
    [edges, nodeDataRevision, selectedNode],
  )
  const selectedGeneratorPromptNodes = useMemo(
    () => selectedNode?.type === "generator"
      ? incomingGeneratorPromptNodes(nodesRef.current, edges, selectedNode.id)
      : [],
    [edges, nodeDataRevision, selectedNode],
  )

  const libraryQuery = useInfiniteQuery({
    queryKey: ["canvas-library", assetKind, librarySearch],
    queryFn: ({ pageParam }) => queryCanvasLibraryItems({
      kind: assetKind,
      q: librarySearch,
      limit: CANVAS_LIBRARY_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => (
      lastPage.has_more ? lastPage.offset + lastPage.items.length : undefined
    ),
    enabled: assetOpen,
    staleTime: 30_000,
    retry: false,
  })
  const insertAssetQuery = useQuery({
    queryKey: ["canvas-library-insert", insertRequest?.key ?? ""],
    queryFn: () => queryCanvasLibraryItems({
      jobId: insertRequest?.jobId,
      generationItemId: insertRequest?.generationItemId,
      outputIndex: insertRequest?.outputIndex,
      limit: 1,
      offset: 0,
    }),
    enabled: Boolean(insertRequest),
    staleTime: 30_000,
    retry: false,
  })
  const libraryItems = useMemo(() => {
    const pages = libraryQuery.data?.pages ?? []
    return mergeCanvasLibraryItems([], pages.flatMap((page) => page.items)).filter(isUsableLibraryItem)
  }, [libraryQuery.data])
  const libraryTotal = libraryQuery.data?.pages[0]?.total ?? 0
  const libraryCounts = libraryQuery.data?.pages[0]?.counts ?? { image: 0, video: 0 }

  const needsGeneratorKind = useMemo(
    () => nodes.some((node) => node.type === "generator" && !node.data.resultKind && node.data.workflowId),
    [nodes],
  )

  useEffect(() => {
    if (!generationModes.length || !needsGeneratorKind) return
    const modeById = new Map(generationModes.map((mode) => [mode.id, mode]))
    setNodes((current) => {
      let changed = false
      const next = current.map((node) => {
        if (node.type !== "generator" || node.data.resultKind) return node
        const mode = modeById.get(String(node.data.workflowId ?? ""))
        if (!mode) return node
        changed = true
        return { ...node, data: { ...node.data, resultKind: mode.media_type } }
      })
      return changed ? next : current
    })
    if (nodesRef.current.some((node) => (
      node.type === "generator"
      && !node.data.resultKind
      && modeById.has(String(node.data.workflowId ?? ""))
    ))) {
      setNodeDataRevision((revision) => revision + 1)
    }
  }, [generationModes, needsGeneratorKind, setNodes])

  useEffect(() => {
    const trimmed = assetSearch.trim()
    if (!trimmed) {
      setLibrarySearch("")
      return
    }
    const timer = window.setTimeout(() => setLibrarySearch(trimmed), 300)
    return () => window.clearTimeout(timer)
  }, [assetSearch])

  const syncHistoryState = useCallback((history: CanvasHistory) => {
    setHistoryState(canvasHistoryState(history))
  }, [])

  const openMediaPreview = useCallback((next: CanvasMediaPreview) => {
    setPreview(next)
  }, [])

  const clearSaveRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    claimCanvasRecovery(project.id, recoveryOwner)
    if (!recoveryNoticeRef.current) {
      recoveryNoticeRef.current = true
      if (recovery.restored) message.info(recovery.conflict ? "已找回本页草稿，服务器版本已变化，请先处理版本冲突" : "已恢复本页尚未保存的画布草稿")
      else clearCanvasRecovery(project.id)
    }
    return () => {
      mountedRef.current = false
      clearSaveRetry()
      backupCurrent()
      void saveDraft()
    }
  }, [backupCurrent, clearSaveRetry, project.id, recovery.conflict, recovery.restored, recoveryOwner, saveDraft])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (serializeCurrent() === lastSavedRef.current && titleRef.current.trim() === savedTitleRef.current) return
      event.preventDefault()
      event.returnValue = ""
      backupCurrent()
      void saveDraft()
    }
    window.addEventListener("beforeunload", beforeUnload)
    return () => window.removeEventListener("beforeunload", beforeUnload)
  }, [backupCurrent, saveDraft, serializeCurrent])

  useOnSelectionChange({
    onChange: useCallback(({ nodes: selectedNodesChange, edges: selectedEdgesChange }) => {
      setSelectedNodeIds(selectedNodesChange.map((node) => node.id))
      setSelectedEdgeIds(selectedEdgesChange.map((edge) => edge.id))
    }, []),
  })

  useEffect(() => {
    if (suppressHistoryRef.current) {
      suppressHistoryRef.current = false
      return
    }
    const coverOnlyChange = coverOnlyChangeRef.current
    coverOnlyChangeRef.current = false
    if (historyTimerRef.current !== null) window.clearTimeout(historyTimerRef.current)
    historyTimerRef.current = window.setTimeout(() => {
      historyTimerRef.current = null
      const snapshot = serializeCurrent()
      const previous = historyRef.current.entries[historyRef.current.index]
      if (coverOnlyChange && previous && isCoverOnlyCanvasChange(previous, snapshot)) return
      const next = pushCanvasHistory(historyRef.current, snapshot)
      if (next !== historyRef.current) {
        historyRef.current = next
        syncHistoryState(next)
      }
    }, 350)
    return () => {
      if (historyTimerRef.current !== null) {
        window.clearTimeout(historyTimerRef.current)
        historyTimerRef.current = null
      }
    }
  }, [nodes, edges, settings, serializeCurrent, syncHistoryState])

  const flushHistory = useCallback(() => {
    if (historyTimerRef.current !== null) {
      window.clearTimeout(historyTimerRef.current)
      historyTimerRef.current = null
    }
    const snapshot = serializeCurrent()
    const next = pushCanvasHistory(historyRef.current, snapshot)
    if (next !== historyRef.current) {
      historyRef.current = next
      syncHistoryState(next)
    }
    return next
  }, [serializeCurrent, syncHistoryState])

  const applyHistory = useCallback((history: CanvasHistory) => {
    historyRef.current = history
    const draft = parseCanvasContent(history.entries[history.index])
    const restoredSettings = { ...readCanvasSettings(draft.canvasSettings), viewport: viewportRef.current }
    settingsRef.current = restoredSettings
    setSettings(restoredSettings)
    suppressHistoryRef.current = true
    setNodes(draft.nodes)
    setEdges(draft.edges)
    setSelectedNodeIds([])
    setSelectedEdgeIds([])
    setContextMenu(null)
    setGuides(EMPTY_GUIDES)
    setHistoryState(canvasHistoryState(history))
  }, [setEdges, setNodes])

  const undo = useCallback(() => {
    const current = flushHistory()
    const next = undoCanvasHistory(current)
    if (next !== current) applyHistory(next)
  }, [applyHistory, flushHistory])

  const redo = useCallback(() => {
    const current = flushHistory()
    const next = redoCanvasHistory(current)
    if (next !== current) applyHistory(next)
  }, [applyHistory, flushHistory])

  const acceptSavedContent = useCallback((content: string, version: number, updatedAt: string): CanvasSaveOutcome => {
    versionRef.current = version
    lastSavedRef.current = content
    const current = serializeCurrent()
    const stillCurrent = current === content
    clearCanvasRecovery(project.id, content)
    if (!stillCurrent) writeCanvasRecovery(project.id, { baseVersion: version, content: current }, undefined, recoveryOwner)
    if (mountedRef.current) {
      retryCountRef.current = 0
      setRetryAttempt(0)
      setSaveError(null)
      setSavedAt(updatedAt)
      setSaveState(saveStateAfterCanvasSave(stillCurrent))
    }
    return stillCurrent ? "saved" : "dirty"
  }, [project.id, recoveryOwner, serializeCurrent])

  const performSave = useCallback(async (notify = false): Promise<CanvasSaveOutcome> => {
    if (savingRef.current || conflictRef.current) return "failed"
    clearSaveRetry()
    const content = serializeCurrent()
    if (content === lastSavedRef.current) {
      clearCanvasRecovery(project.id, content)
      retryCountRef.current = 0
      setRetryAttempt(0)
      setSaveError(null)
      setSaveState("saved")
      return "saved"
    }
    const bytes = canvasByteSize(content)
    setContentBytes(bytes)
    if (canvasContentSizeLevel(bytes) === "over") {
      retryCountRef.current = 0
      setRetryAttempt(0)
      setSaveError(`画布内容约 ${formatCanvasBytes(bytes)}，超过 8 MB 上限，无法保存`)
      setSaveState("error")
      if (notify) message.error("画布内容超过 8 MB，请删除大型内嵌图片或改用素材地址")
      return "failed"
    }
    savingRef.current = true
    setSaveState("saving")
    writeCanvasRecovery(project.id, { baseVersion: versionRef.current, content }, undefined, recoveryOwner)
    try {
      const result = await saveCanvasDraft(
        csrfToken, project.id, versionRef.current, content, null,
      )
      const outcome = acceptSavedContent(content, result.version, result.updated_at)
      if (notify && mountedRef.current && outcome === "saved") message.success("画布已保存")
      return outcome
    } catch (error) {
      backupCurrent()
      const currentVersion = canvasConflictVersion(error)
      if (currentVersion !== null) {
        try {
          const latest = await getCanvasProject(project.id)
          if (normalizedCanvasContent(latest.content) === normalizedCanvasContent(content)) {
            return acceptSavedContent(content, latest.version, latest.draft_updated_at ?? latest.updated_at)
          }
        } catch { /* Keep the original conflict when the latest version cannot be read. */ }
        conflictRef.current = true
        if (!mountedRef.current) return "failed"
        retryCountRef.current = 0
        setRetryAttempt(0)
        setSaveError(null)
        setConflictVersionNumber(currentVersion)
        setSaveState("conflict")
        return "failed"
      }
      if (!mountedRef.current) return "failed"
      const retryDelay = isCanvasSaveRetryable(error)
        ? nextCanvasSaveRetryDelay(retryCountRef.current)
        : null
      if (retryDelay !== null) {
        retryCountRef.current += 1
        setRetryAttempt(retryCountRef.current)
        setRetryDelayMs(retryDelay)
        setSaveError(errorText(error))
        setSaveState("retrying")
        if (notify) message.error(`${errorText(error)}，稍后自动重试`)
        retryTimerRef.current = window.setTimeout(() => {
          retryTimerRef.current = null
          void saveDraft()
        }, retryDelay)
      } else {
        retryCountRef.current = 0
        setRetryAttempt(0)
        setSaveError(errorText(error))
        setSaveState("error")
        if (notify) message.error(errorText(error))
      }
      return "failed"
    } finally {
      savingRef.current = false
    }
  }, [acceptSavedContent, backupCurrent, clearSaveRetry, csrfToken, project.id, recoveryOwner, saveDraft, serializeCurrent])
  saveDraftRef.current = performSave

  const patchSettings = useCallback((patch: Partial<CanvasSettings>) => {
    const next = { ...settingsRef.current, ...patch }
    settingsRef.current = next
    setSettings(next)
    setSaveState((state) => saveStateAfterCanvasEdit(state))
  }, [])

  const exportJson = useCallback(() => {
    const blob = new Blob([serializeCurrent()], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = canvasExportFileName(title)
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    message.success("画布 JSON 已导出")
  }, [serializeCurrent, title])

  const handleImportFile = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return
    if (file.size > CANVAS_IMPORT_MAX_BYTES) {
      message.error("画布 JSON 超过 8 MB 上限，无法导入")
      return
    }
    let raw = ""
    try {
      raw = await file.text()
    } catch {
      message.error("读取文件失败，请重试")
      return
    }
    const result = parseCanvasImportContent(raw)
    if (!result.ok) {
      message.error(result.error)
      return
    }
    const replace = () => {
      flushHistory()
      const importedSettings = readCanvasSettings(result.draft.canvasSettings)
      const nextSettings = result.draft.canvasSettings
        ? { ...importedSettings, viewport: viewportRef.current ?? importedSettings.viewport }
        : settingsRef.current
      settingsRef.current = nextSettings
      setSettings(nextSettings)
      setNodes(result.draft.nodes)
      setEdges(result.draft.edges)
      setSelectedNodeIds([])
      setSelectedEdgeIds([])
      setContextMenu(null)
      setGuides(EMPTY_GUIDES)
      setSaveState((state) => saveStateAfterCanvasEdit(state))
      message.success(`已导入 ${result.nodeCount} 个节点、${result.edgeCount} 条连线`)
    }
    if (nodesRef.current.length === 0 && edgesRef.current.length === 0) {
      replace()
      return
    }
    setPendingImport({ nodeCount: result.nodeCount, edgeCount: result.edgeCount, replace })
  }, [flushHistory, setEdges, setNodes])

  const handleViewportChange = useCallback((_event: unknown, next: CanvasViewport) => {
    if (!canvasViewportChanged(viewportRef.current, next)) return
    const normalized = {
      x: Math.round(next.x * 1000) / 1000,
      y: Math.round(next.y * 1000) / 1000,
      zoom: Math.round(next.zoom * 1000) / 1000,
    }
    viewportRef.current = normalized
    settingsRef.current = { ...settingsRef.current, viewport: normalized }
    setSaveState((state) => {
      if (state === "conflict" || state === "retrying" || state === "saving") return state
      return "dirty"
    })
  }, [])

  useEffect(() => {
    if (initialEffectRef.current) {
      initialEffectRef.current = false
      return
    }
    setSaveState((state) => saveStateAfterCanvasEdit(state))
  }, [nodes, edges])

  useEffect(() => {
    if (saveState !== "dirty" || conflictVersionNumber !== null) return
    const timer = window.setTimeout(() => { void saveDraft() }, 1200)
    return () => window.clearTimeout(timer)
  }, [saveState, nodes, edges, settings, saveDraft, conflictVersionNumber])

  const reloadFromServer = useCallback(async () => {
    setReloading(true)
    try {
      const next = await getCanvasProject(project.id)
      if (historyTimerRef.current !== null) {
        window.clearTimeout(historyTimerRef.current)
        historyTimerRef.current = null
      }
      clearSaveRetry()
      const draft = parseCanvasContent(next.content)
      const nextSettings = readCanvasSettings(draft.canvasSettings)
      if (!nextSettings.viewport && viewportRef.current) nextSettings.viewport = viewportRef.current
      const snapshot = serializeCanvasDraft(draft.nodes, draft.edges, {
        canvasSettings: settingsRecord(nextSettings),
      })
      settingsRef.current = nextSettings
      setSettings(nextSettings)
      viewportRef.current = nextSettings.viewport
      versionRef.current = next.version
      lastSavedRef.current = snapshot
      clearCanvasRecovery(project.id)
      historyRef.current = createCanvasHistory(snapshot)
      setHistoryState(canvasHistoryState(historyRef.current))
      autoInsertedJobsRef.current.clear()
      conflictRef.current = false
      retryCountRef.current = 0
      setRetryAttempt(0)
      setRetryDelayMs(0)
      setSaveError(null)
      setContentBytes(canvasByteSize(snapshot))
      setConflictVersionNumber(null)
      suppressHistoryRef.current = true
      setNodes(draft.nodes)
      setEdges(draft.edges)
      if (nextSettings.viewport) setViewport(nextSettings.viewport)
      setSelectedNodeIds([])
      setSelectedEdgeIds([])
      setContextMenu(null)
      setTitle(next.title)
      savedTitleRef.current = next.title
      setSavedAt(next.draft_updated_at ?? next.updated_at)
      setSaveState("saved")
      message.success("已加载服务器上的最新画布")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setReloading(false)
    }
  }, [clearSaveRetry, project.id, setEdges, setNodes, setViewport])

  const appendResultNode = useCallback((
    generatorNode: CanvasNode,
    result: CanvasJobResult,
    jobId: string | null,
    direction: CanvasBranchDirection,
    options: { auto?: boolean } = {},
  ) => {
    const position = nextCanvasBranchSlot(generatorNode, direction, nodesRef.current)
    const label = result.label
      || String(generatorNode.data.prompt ?? "").trim().slice(0, 24)
      || (result.kind === "video" ? "生成视频" : "生成图片")
    const created = result.kind === "video"
      ? createVideoNode(position, result.url, label)
      : createImageNode(position, result.url, label)
    const sourceRun = jobId ? canvasRunSnapshotForJob(generatorNode.data, jobId) : null
    created.data = {
      ...created.data,
      assetPath: result.path || undefined,
      sourceJobId: jobId,
      mediaKind: result.kind,
      ...(sourceRun ? { sourceRun } : {}),
    }
    const edge: CanvasEdge = {
      id: buildEdgeId(generatorNode.id, created.id),
      source: generatorNode.id,
      target: created.id,
      sourceHandle: "out",
      targetHandle: "in",
      type: "smoothstep",
    }
    setNodes((current) => [
      ...(options.auto ? current : current.map((node) => ({ ...node, selected: false }))),
      { ...created, selected: !options.auto },
    ])
    setEdges((current) => (current.some((item) => item.id === edge.id) ? current : [...current, edge]))
    if (!options.auto) {
      setSelectedNodeIds([created.id])
      setSelectedEdgeIds([])
      message.success(result.kind === "video" ? "视频结果已插入画布" : "图片结果已插入画布")
    }
    return created
  }, [setEdges, setNodes])

  const fillPendingResultNodes = useCallback((
    generatorNode: CanvasNode,
    result: CanvasJobResult,
    jobId: string | null,
  ): number => {
    const sourceRun = jobId ? canvasRunSnapshotForJob(generatorNode.data, jobId) : null
    let filled = 0
    for (const pending of nodesRef.current) {
      if (pending.data.pendingGeneratorId !== generatorNode.id) continue
      const patch = canvasPendingResultFill(pending, result, jobId)
      if (!patch) continue
      updateNodeData(pending.id, { ...patch, ...(sourceRun ? { sourceRun } : {}) })
      filled += 1
    }
    return filled
  }, [updateNodeData])

  const applyGeneratorJobSnapshot = useCallback((jobId: string, job: CanvasJob) => {
    if (isCanvasJobActive(job.status) && job.status !== "awaiting_refine") return
    const matchingNodes = nodesRef.current.filter((item) => item.type === "generator" && item.data.jobId === jobId)
    const results = job.status === "succeeded" || job.status === "partial" ? canvasJobResults(job) : []
    const result = results[0] ?? null
    for (const node of matchingNodes) {
      const history = canvasResultHistory(node.data)
      const newResults = results.filter((candidate) => !history.some((entry) => entry.url === candidate.url && (entry.path ?? "") === (candidate.path ?? "")))
      const resultChanged = newResults.length > 0
      const statusChanged = node.data.jobStatus !== job.status
        || (node.data.jobError ?? null) !== (job.error ?? null)
      if (statusChanged || resultChanged) {
        const patch: Partial<CanvasNodeData> = {
          jobStatus: job.status,
          jobError: job.error ?? null,
        }
        if (resultChanged) {
          let versionData = node.data
          for (const candidate of newResults) versionData = { ...versionData, ...canvasResultVersionPatch(versionData, candidate, jobId) }
          Object.assign(patch, { resultHistory: versionData.resultHistory })
          const first = canvasResultHistory(versionData).findIndex((entry) => entry.url === result?.url)
          Object.assign(patch, selectCanvasResultVersion(versionData, first) ?? canvasResultVersionPatch(versionData, newResults[0], jobId))
        }
        updateNodeData(node.id, patch)
      }
      if (result) {
        const filled = fillPendingResultNodes(node, result, jobId)
        if (filled && jobId) autoInsertedJobsRef.current.add(jobId)
      }
      if (result && settingsRef.current.generationDisplayMode === "independent" && jobId) {
        const alreadyInserted = autoInsertedJobsRef.current.has(jobId)
          || nodesRef.current.some((item) => (
            (item.type === "image" || item.type === "video") && item.data.sourceJobId === jobId
          ))
        if (!alreadyInserted) {
          autoInsertedJobsRef.current.add(jobId)
          appendResultNode(
            node,
            result,
            jobId,
            node.data.branchDirection === "down" ? "down" : "right",
            { auto: true },
          )
        }
      }
    }
  }, [appendResultNode, fillPendingResultNodes, updateNodeData])

  useEffect(() => {
    for (const live of Object.values(liveJobs)) {
      if (!isCanvasJobActive(live.status) || live.status === "awaiting_refine") {
        applyGeneratorJobSnapshot(live.jobId, {
          id: live.jobId, media_type: live.result?.kind ?? "video", status: live.status,
          error: live.error, outputs: live.results?.length ? live.results.map((item) => ({ kind: item.kind, download_url: item.url, path: item.path, label: item.label })) : live.result ? [{ kind: live.result.kind, download_url: live.result.url, path: live.result.path, label: live.result.label }] : [],
        })
      }
    }
  }, [applyGeneratorJobSnapshot, liveJobs, nodes])

  const insertGeneratorResult = useCallback((nodeId: string, direction: CanvasBranchDirection) => {
    const node = nodesRef.current.find((item) => item.id === nodeId && item.type === "generator")
    if (!node) return
    const version = canvasResultHistory(node.data)[canvasResultVersionIndex(node.data)]
    const jobId = version?.jobId ?? node.data.jobId ?? null
    const result = generatorResultFromNodeData(node.data)
      ?? (jobId ? liveJobsRef.current[jobId]?.result : null)
    if (!result) {
      message.warning("生成结果还未就绪")
      return
    }
    appendResultNode(node, result, jobId, direction)
  }, [appendResultNode])

  const generatorJobPollKey = useMemo(() => {
    const jobIds = new Set<string>()
    for (const node of nodesRef.current) {
      if (node.type !== "generator" || !node.data.jobId) continue
      const status = liveJobs[node.data.jobId]?.status ?? node.data.jobStatus
      // Hydrate finished jobs once after opening a draft, including partial counts.
      if (!liveJobs[node.data.jobId] || isCanvasJobActive(status)) jobIds.add(node.data.jobId)
    }
    return [...jobIds].sort().join("|")
  }, [liveJobs, nodeDataRevision])

  useEffect(() => {
    if (!generatorJobPollKey) return
    const jobIds = generatorJobPollKey.split("|")
    let cancelled = false
    const poll = async () => {
      const snapshots = await Promise.all(jobIds.map(async (jobId) => {
        try {
          return [jobId, await fetchCanvasJob(jobId)] as const
        } catch (error) {
          if (error instanceof ApiRequestError && error.status === 404) {
            return [jobId, { id: jobId, media_type: "video", status: "failed", error: "任务已删除或当前账号无法访问，请重新生成" } satisfies CanvasJob] as const
          }
          return null
        }
      }))
      if (cancelled) return
      const found = snapshots.filter((item): item is readonly [string, CanvasJob] => item !== null)
      if (!found.length) return
      setLiveJobs((previous) => {
        const next = { ...previous }
        for (const [jobId, job] of found) {
          const result = canvasJobResult(job)
          const details = canvasJobLiveDetails(job)
          const previousLive = previous[jobId]
          if (previousLive
            && previousLive.status === job.status
            && previousLive.stage === job.stage
            && previousLive.progress === job.progress
            && (previousLive.error ?? null) === (job.error ?? null)
            && (previousLive.result?.url ?? null) === (result?.url ?? null)
            && previousLive.completedCount === details.completedCount
            && previousLive.requestedCount === details.requestedCount
            && JSON.stringify(previousLive.results) === JSON.stringify(details.results)) continue
          next[jobId] = {
            jobId,
            status: job.status,
            stage: job.stage,
            progress: job.progress,
            error: job.error ?? null,
            result,
            ...details,
            updatedAt: Date.now(),
          }
        }
        return next
      })
      for (const [jobId, job] of found) applyGeneratorJobSnapshot(jobId, job)
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [applyGeneratorJobSnapshot, generatorJobPollKey])

  const submitGenerator = useCallback(async (nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId && item.type === "generator")
    if (!node) return
    const currentStatus = (node.data.jobId ? liveJobsRef.current[node.data.jobId]?.status : null)
      ?? node.data.jobStatus
      ?? null
    if (isCanvasJobActive(currentStatus)) {
      message.info("当前生成任务还未结束")
      return
    }
    const mode = generationModes.find((item) => item.id === node.data.workflowId) ?? null
    if (!mode) {
      message.warning("请先选择生成工作流")
      return
    }
    const references = incomingGeneratorReferenceNodes(nodesRef.current, edgesRef.current, nodeId)
    const promptSource = resolveGeneratorPrompt(
      incomingGeneratorPromptNodes(nodesRef.current, edgesRef.current, nodeId),
      node.data.prompt ?? "",
    )
    const validation = validateGeneratorInput(
      mode,
      promptSource.text,
      references,
      generatorPromptInfo(promptSource),
    )
    if (validation) {
      message.warning(validation)
      return
    }
    if (!beginGeneratorAction(nodeId)) return
    try {
      const files: File[] = []
      for (const [index, reference] of references.entries()) {
        files.push(await canvasImageNodeFile(reference, index + 1))
      }
      const prompt = promptSource.text
      const options = serializeGeneratorOptionValues(mode, node.data.optionValues)
      const job = await submitCanvasJob(csrfToken, {
        mode: mode.id,
        prompt,
        options,
        references: files,
        title: prompt.slice(0, 60),
      })
      if (!mountedRef.current) return
      const result = canvasJobResult(job)
      setLiveJobs((previous) => ({
        ...previous,
        [job.id]: {
          jobId: job.id,
          status: job.status,
          stage: job.stage,
          progress: job.progress,
          error: job.error ?? null,
          result,
          ...canvasJobLiveDetails(job),
          updatedAt: Date.now(),
        },
      }))
      const snapshot = buildCanvasRunSnapshot({
        jobId: job.id,
        mode,
        prompt,
        optionValues: options,
        referenceCount: references.length,
      })
      const latest = nodesRef.current.find((item) => item.id === nodeId)
      updateNodeData(nodeId, {
        jobId: job.id,
        jobStatus: job.status,
        jobError: null,
        ...appendCanvasRunSnapshot(latest?.data ?? node.data, snapshot),
      })
      message.success("已提交生成任务")
    } catch (error) {
      if (mountedRef.current) message.error(errorText(error))
    } finally {
      endGeneratorAction(nodeId)
    }
  }, [beginGeneratorAction, csrfToken, endGeneratorAction, generationModes, updateNodeData])

  const cancelGenerator = useCallback(async (nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId && item.type === "generator")
    const jobId = node?.data.jobId
    if (!node || !jobId) return
    if (!beginGeneratorAction(nodeId)) return
    try {
      const job = await cancelCanvasJob(csrfToken, jobId)
      if (!mountedRef.current) return
      const result = canvasJobResult(job)
      setLiveJobs((previous) => ({
        ...previous,
        [jobId]: {
          jobId,
          status: job.status,
          stage: job.stage,
          progress: job.progress,
          error: job.error ?? null,
          result,
          ...canvasJobLiveDetails(job),
          updatedAt: Date.now(),
        },
      }))
      applyGeneratorJobSnapshot(jobId, job)
      message.success(isCanvasJobActive(job.status) ? "已请求停止生成任务" : "已停止生成任务")
    } catch (error) {
      if (mountedRef.current) message.error(errorText(error))
    } finally {
      endGeneratorAction(nodeId)
    }
  }, [applyGeneratorJobSnapshot, beginGeneratorAction, csrfToken, endGeneratorAction])

  const refineGenerator = useCallback(async (nodeId: string, action: "confirm" | "skip") => {
    const node = nodesRef.current.find((item) => item.id === nodeId && item.type === "generator")
    const jobId = node?.data.jobId
    if (!jobId || !beginGeneratorAction(nodeId)) return
    try {
      const job = await refineCanvasJob(csrfToken, jobId, action)
      if (!mountedRef.current) return
      setLiveJobs((previous) => ({ ...previous, [jobId]: {
        jobId, status: job.status, stage: job.stage, progress: job.progress,
        error: job.error ?? null, result: canvasJobResult(job), ...canvasJobLiveDetails(job), updatedAt: Date.now(),
      } }))
      applyGeneratorJobSnapshot(jobId, job)
      message.success(action === "confirm" ? "已确认二采精修" : "已保留一采预览")
    } catch (error) {
      if (mountedRef.current) message.error(errorText(error))
    } finally {
      endGeneratorAction(nodeId)
    }
  }, [applyGeneratorJobSnapshot, beginGeneratorAction, csrfToken, endGeneratorAction])

  const openGeneratorJob = useCallback((jobId: string, kind?: CanvasMediaKind) => {
    let resolved = kind
    if (!resolved) {
      const node = nodesRef.current.find((item) => (
        (item.type === "generator" && item.data.jobId === jobId)
        || item.data.sourceJobId === jobId
      ))
      if (node?.type === "video") resolved = "video"
      else if (node?.type === "image") resolved = "image"
      else if (node?.type === "generator") {
        const mode = generationModes.find((item) => item.id === node.data.workflowId)
        resolved = generatorResultFromNodeData(node.data)?.kind ?? mode?.media_type ?? "video"
      }
    }
    window.open(generateJobPath(resolved ?? "video", jobId), "_blank", "noopener,noreferrer")
  }, [generationModes])

  const selectOnlyNode = useCallback((nodeId: string) => {
    setNodes((current) => current.map((node) => ({ ...node, selected: node.id === nodeId })))
    setEdges((current) => current.map((edge) => ({ ...edge, selected: false })))
    setSelectedNodeIds([nodeId])
    setSelectedEdgeIds([])
  }, [setEdges, setNodes])

  const openProperties = useCallback((nodeId: string) => {
    selectOnlyNode(nodeId)
    setPanelOpen(true)
    setPanelTab("properties")
  }, [selectOnlyNode])

  const focusNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId)
    if (!node) return
    const size = canvasNodeSize(node)
    void setCenter(
      node.position.x + size.width / 2,
      node.position.y + size.height / 2,
      { zoom: Math.min(CANVAS_MAX_ZOOM, Math.max(zoom, 0.6)), duration: 300 },
    )
  }, [setCenter, zoom])

  const appendNodes = useCallback((created: CanvasNode[]) => {
    if (!created.length) return
    const ids = new Set(created.map((node) => node.id))
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...created.map((node) => ({ ...node, selected: ids.has(node.id) })),
    ])
    setSelectedNodeIds(created.map((node) => node.id))
    setSelectedEdgeIds([])
  }, [setNodes])

  const stageVisibleBounds = useCallback(() => {
    const stage = stageRef.current
    return {
      left: 96,
      top: 56,
      right: Math.max(200, (stage?.clientWidth ?? window.innerWidth) - 24),
      bottom: Math.max(200, (stage?.clientHeight ?? window.innerHeight) - (settingsRef.current.minimapVisible ? 144 : 88)),
    }
  }, [])

  const stageCenter = useCallback(() => {
    const rect = stageRef.current?.getBoundingClientRect()
    const bounds = stageVisibleBounds()
    return screenToFlowPosition({
      x: (rect?.left ?? 0) + (bounds.left + bounds.right) / 2,
      y: (rect?.top ?? 0) + (bounds.top + bounds.bottom) / 2,
    })
  }, [screenToFlowPosition, stageVisibleBounds])

  const revealAddedNode = useCallback((node: CanvasNode) => {
    const stage = stageRef.current
    if (!stage) return
    const viewport = getViewport()
    const size = canvasNodeSize(node)
    const left = node.position.x * viewport.zoom + viewport.x
    const top = node.position.y * viewport.zoom + viewport.y
    const bounds = stageVisibleBounds()
    if (
      left >= bounds.left
      && top >= bounds.top
      && left + size.width * viewport.zoom <= bounds.right
      && top + size.height * viewport.zoom <= bounds.bottom
    ) return
    const nextZoom = Math.max(CANVAS_MIN_ZOOM, Math.min(viewport.zoom,
      (bounds.right - bounds.left) / size.width, (bounds.bottom - bounds.top) / size.height))
    void setViewport({
      x: (bounds.left + bounds.right) / 2 - (node.position.x + size.width / 2) * nextZoom,
      y: (bounds.top + bounds.bottom) / 2 - (node.position.y + size.height / 2) * nextZoom,
      zoom: nextZoom,
    }, { duration: 300 })
  }, [getViewport, setViewport, stageVisibleBounds])

  const addCanvasNode = useCallback((
    kind: "text" | "image" | "generator" | "artboard",
    point?: { x: number; y: number },
  ) => {
    const center = stageCenter()
    const fallbackSize = kind === "generator"
      ? { width: 400, height: 290 }
      : kind === "text"
        ? { width: 260, height: 120 }
        : kind === "artboard"
          ? { width: 720, height: 480 }
          : CANVAS_LIBRARY_NODE_SIZES.image
    const offset = (nodesRef.current.length % 5) * 24
    const position = point ?? {
      x: Math.round(center.x - fallbackSize.width / 2 + offset),
      y: Math.round(center.y - fallbackSize.height / 2 + offset),
    }
    const mode = kind === "generator" ? pickCanvasGenerationMode(generationModes, 0) : null
    const node = kind === "text"
      ? createTextNode(position)
      : kind === "image"
        ? createImageNode(position)
        : kind === "generator"
          ? createGeneratorNode(position, {
            prompt: settingsRef.current.globalPrompt,
            workflowId: mode?.id,
            optionValues: defaultGeneratorOptionValues(mode),
            mediaKind: mode?.media_type,
          })
          : createArtboardNode(position)
    if (!point) node.position = findCanvasFreePosition(position, canvasNodeSize(node), nodesRef.current)
    appendNodes([node])
    revealAddedNode(node)
  }, [appendNodes, generationModes, revealAddedNode, stageCenter])

  const branchGenerate = useCallback((nodeId: string, direction: CanvasBranchDirection) => {
    const source = nodesRef.current.find((node) => node.id === nodeId)
    if (!source) return
    let prompt = ""
    let workflowId: string | undefined
    let optionValues: Record<string, string | number | boolean> = {}
    if (source.type === "generator") {
      prompt = String(source.data.prompt ?? "")
      workflowId = source.data.workflowId
      optionValues = { ...(source.data.optionValues ?? {}) }
    } else if (source.type === "text") {
      prompt = String(source.data.text ?? "").trim() || String(source.data.label ?? "").trim()
    } else if (source.type === "image") {
      prompt = String(source.data.caption ?? "").trim() || String(source.data.label ?? "").trim()
    }
    if (!prompt) prompt = settingsRef.current.globalPrompt
    const referenceCount = canvasReferenceEligible(source) ? 1 : 0
    const sourceMode = generationModes.find((mode) => mode.id === workflowId) ?? null
    const sourceModeUsable = sourceMode !== null
      && referenceCount >= (sourceMode.min_references ?? 0)
      && referenceCount <= (sourceMode.max_references ?? 0)
    if (!workflowId || !sourceModeUsable) {
      const mode = pickCanvasGenerationMode(generationModes, referenceCount) ?? sourceMode
      workflowId = mode?.id
      optionValues = defaultGeneratorOptionValues(mode)
    }
    const created = createGeneratorNode(nextCanvasBranchSlot(source, direction, nodesRef.current), {
      prompt,
      workflowId,
      optionValues,
      branchDirection: direction,
      mediaKind: generationModes.find((mode) => mode.id === workflowId)?.media_type,
    })
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), { ...created, selected: true }])
    if (referenceCount > 0 || source.type === "text") {
      const edge: CanvasEdge = {
        id: buildEdgeId(source.id, created.id),
        source: source.id,
        target: created.id,
        sourceHandle: "out",
        targetHandle: "in",
        type: "smoothstep",
      }
      setEdges((current) => (current.some((item) => item.id === edge.id) ? current : [...current, edge]))
    }
    setSelectedNodeIds([created.id])
    setSelectedEdgeIds([])
    const sourceSize = canvasNodeSize(source)
    const createdSize = canvasNodeSize(created)
    const rect = stageRef.current?.getBoundingClientRect()
    const margin = 64 / zoom
    const bounds = {
      left: Math.min(source.position.x, created.position.x),
      top: Math.min(source.position.y, created.position.y),
      right: Math.max(source.position.x + sourceSize.width, created.position.x + createdSize.width),
      bottom: Math.max(source.position.y + sourceSize.height, created.position.y + createdSize.height),
    }
    const fitsBoth = rect
      ? bounds.right - bounds.left + margin * 2 <= rect.width / zoom
        && bounds.bottom - bounds.top + margin * 2 <= rect.height / zoom
      : false
    void setCenter(
      fitsBoth ? (bounds.left + bounds.right) / 2 : created.position.x + createdSize.width / 2,
      fitsBoth ? (bounds.top + bounds.bottom) / 2 : created.position.y + createdSize.height / 2,
      { zoom, duration: 300 },
    )
  }, [generationModes, setCenter, setEdges, setNodes, zoom])

  const applyConnectTarget = useCallback((key: string) => {
    const pending = connectMenu
    setConnectMenu(null)
    if (!pending) return
    const source = nodesRef.current.find((node) => node.id === pending.sourceId)
    const target = canvasConnectTargets(source).find((item) => item.key === key)
    if (!source || !target) return

    let created: CanvasNode | null = null
    let notice = ""
    if (target.kind === "generator") {
      const referenceCount = target.targetHandle === "in" ? 1 : 0
      const rawPrompt = source.type === "text"
        ? source.data.text
        : source.type === "image"
          ? source.data.caption || source.data.label
          : source.type === "generator"
            ? source.data.prompt
            : ""
      const prompt = String(rawPrompt ?? "").trim().slice(0, 4000) || settingsRef.current.globalPrompt
      const sourceMode = source.type === "generator"
        ? generationModes.find((mode) => mode.id === source.data.workflowId) ?? null
        : null
      const modeUsable = sourceMode !== null
        && referenceCount >= (sourceMode.min_references ?? 0)
        && referenceCount <= (sourceMode.max_references ?? 0)
      const mode = modeUsable ? sourceMode : pickCanvasGenerationMode(generationModes, referenceCount)
      created = createGeneratorNode(pending.flow, {
        prompt,
        workflowId: mode?.id,
        optionValues: modeUsable && sourceMode
          ? { ...(source.data.optionValues ?? {}) }
          : defaultGeneratorOptionValues(mode),
        mediaKind: mode?.media_type,
      })
      notice = "已创建生成节点并连线"
    } else {
      const version = canvasResultHistory(source.data)[canvasResultVersionIndex(source.data)]
      const jobId = version?.jobId ?? source.data.jobId ?? null
      const result = generatorResultFromNodeData(source.data)
        ?? (jobId ? liveJobsRef.current[jobId]?.result : null)
      if (result && result.kind === target.kind) {
        const label = result.label
          || String(source.data.prompt ?? "").trim().slice(0, 24)
          || (result.kind === "video" ? "生成视频" : "生成图片")
        created = result.kind === "video"
          ? createVideoNode(pending.flow, result.url, label)
          : createImageNode(pending.flow, result.url, label)
        const sourceRun = jobId ? canvasRunSnapshotForJob(source.data, jobId) : null
        created.data = {
          ...created.data,
          assetPath: result.path || undefined,
          sourceJobId: jobId,
          mediaKind: result.kind,
          ...(sourceRun ? { sourceRun } : {}),
        }
        notice = result.kind === "video" ? "视频结果已加入画布" : "图片结果已加入画布"
      } else {
        created = target.kind === "video"
          ? createVideoNode(pending.flow, "", "等待生成")
          : createImageNode(pending.flow, "", "等待生成")
        created.data = { ...created.data, pendingGeneratorId: source.id }
        notice = target.kind === "video"
          ? "已预建视频节点，生成完成后自动填入"
          : "已预建图片节点，生成完成后自动填入"
      }
    }

    created.position = findCanvasFreePosition(pending.flow, canvasNodeSize(created), nodesRef.current)
    appendNodes([created])
    const edge = canvasConnectEdge(source.id, created.id, target.targetHandle, pending.sourceHandle)
    setEdges((current) => (current.some((item) => item.id === edge.id) ? current : [...current, edge]))
    setRecentEdgeId(edge.id)
    revealAddedNode(created)
    message.success(notice)
    if (source.type === "text" && !String(source.data.text ?? "").trim()) {
      message.warning("文字节点内容为空，补充文字后才能用于生成")
    }
  }, [appendNodes, connectMenu, generationModes, revealAddedNode, setEdges])

  const duplicateNode = useCallback((nodeId: string) => {
    const duplicated = duplicateCanvasSelection(nodesRef.current, edgesRef.current, [nodeId])
    if (!duplicated.nodes.length) return
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...duplicated.nodes.map((node) => ({ ...node, selected: true })),
    ])
    setEdges((current) => [
      ...current.map((edge) => ({ ...edge, selected: false })),
      ...duplicated.edges,
    ])
    setSelectedNodeIds(duplicated.nodeIds)
    setSelectedEdgeIds([])
  }, [setEdges, setNodes])

  const deleteNode = useCallback((nodeId: string) => {
    setNodes((current) => current.filter((node) => node.id !== nodeId))
    setEdges((current) => current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId))
    setSelectedNodeIds((current) => current.filter((id) => id !== nodeId))
    setSelectedEdgeIds([])
  }, [setEdges, setNodes])

  const downloadNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId)
    if (!node) return
    const url = canvasNodeMediaUrl(node)
    if (!url) return
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.target = "_blank"
    anchor.rel = "noopener noreferrer"
    anchor.download = ""
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }, [])

  const updateNodeCover = useCallback((nodeId: string, patch: CanvasCoverPatch) => {
    coverOnlyChangeRef.current = true
    updateNodeData(nodeId, patch)
  }, [updateNodeData])

  const deleteSelected = useCallback(() => {
    if (!selectedNodeIds.length && !selectedEdgeIds.length) return
    const nodeIds = new Set(selectedNodeIds)
    const edgeIds = new Set(selectedEdgeIds)
    setNodes((current) => current.filter((node) => !nodeIds.has(node.id)))
    setEdges((current) => current.filter((edge) => (
      !edgeIds.has(edge.id) && !nodeIds.has(edge.source) && !nodeIds.has(edge.target)
    )))
    setSelectedNodeIds([])
    setSelectedEdgeIds([])
  }, [selectedEdgeIds, selectedNodeIds, setEdges, setNodes])

  const arrangeSelected = useCallback((action: CanvasAlignMode | `distribute-${CanvasDistributeAxis}`) => {
    const selected = nodesRef.current.filter((node) => selectedNodeIdSet.has(node.id))
    if (selected.length < 2) return
    const updates = action === "distribute-horizontal"
      ? distributeCanvasNodes(selected, "horizontal")
      : action === "distribute-vertical"
        ? distributeCanvasNodes(selected, "vertical")
        : alignCanvasNodes(selected, action)
    if (!Object.keys(updates).length) return
    flushHistory()
    setNodes((current) => current.map((node) => {
      const position = updates[node.id]
      return position ? { ...node, position } : node
    }))
  }, [flushHistory, selectedNodeIdSet, setNodes])

  const copySelected = useCallback(() => {
    const clipboard = copyCanvasClipboard(nodesRef.current, edgesRef.current, selectedNodeIds)
    if (!clipboard) return
    clipboardRef.current = clipboard
    pasteCountRef.current = 0
    setClipboardCount(clipboard.nodes.length)
  }, [selectedNodeIds])

  const pasteClipboard = useCallback(() => {
    const clipboard = clipboardRef.current
    if (!clipboard) return
    pasteCountRef.current += 1
    const pasted = pasteCanvasClipboard(clipboard, 32 * pasteCountRef.current)
    if (!pasted.nodes.length) return
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...pasted.nodes.map((node) => ({ ...node, selected: true })),
    ])
    setEdges((current) => [
      ...current.map((edge) => ({ ...edge, selected: false })),
      ...pasted.edges,
    ])
    setSelectedNodeIds(pasted.nodeIds)
    setSelectedEdgeIds([])
  }, [setEdges, setNodes])

  const selectAllNodes = useCallback(() => {
    setNodes((current) => current.map((node) => ({ ...node, selected: true })))
    setEdges((current) => current.map((edge) => ({ ...edge, selected: false })))
    setSelectedNodeIds(nodesRef.current.map((node) => node.id))
    setSelectedEdgeIds([])
  }, [setEdges, setNodes])

  const saveViewpoint = useCallback((index: number) => {
    const current = getViewport()
    const stored = {
      x: Math.round(current.x * 1000) / 1000,
      y: Math.round(current.y * 1000) / 1000,
      zoom: Math.round(current.zoom * 1000) / 1000,
    }
    const viewpoints = [...settingsRef.current.viewpoints]
    viewpoints[index] = stored
    patchSettings({ viewpoints })
    message.success(`已保存视角 ${index === 9 ? 0 : index + 1}`)
  }, [getViewport, patchSettings])

  const jumpViewpoint = useCallback((index: number) => {
    const viewpoint = settingsRef.current.viewpoints[index]
    if (!viewpoint) return
    void setViewport(viewpoint, { duration: 300 })
  }, [setViewport])

  const clearViewpoint = useCallback((index: number) => {
    const viewpoints = [...settingsRef.current.viewpoints]
    if (!viewpoints[index]) return
    viewpoints[index] = null
    patchSettings({ viewpoints })
    message.success(`已清除视角 ${index === 9 ? 0 : index + 1}`)
  }, [patchSettings])

  const closeAssetLibrary = useCallback(() => {
    setAssetOpen(false)
    setAssetTargetNodeId(null)
    setAssetGeneratorId(null)
    setAssetReferenceSourceId(null)
    setAssetSearch("")
    setLibrarySearch("")
  }, [])

  const clearInsertParams = useCallback(() => {
    setSearchParams((current) => {
      if (!current.has(CANVAS_INSERT_JOB_PARAM) && !current.has(CANVAS_INSERT_ITEM_PARAM) && !current.has(CANVAS_INSERT_OUTPUT_PARAM)) {
        return current
      }
      const next = new URLSearchParams(current)
      next.delete(CANVAS_INSERT_JOB_PARAM)
      next.delete(CANVAS_INSERT_ITEM_PARAM)
      next.delete(CANVAS_INSERT_OUTPUT_PARAM)
      return next
    }, { replace: true })
  }, [setSearchParams])

  const openAssetLibrary = useCallback((kind: CanvasMediaKind = "image", targetNodeId: string | null = null) => {
    setAssetKind(kind)
    setAssetTargetNodeId(targetNodeId)
    setAssetGeneratorId(null)
    setAssetReferenceSourceId(null)
    setAssetOpen(true)
  }, [])

  const insertLibraryItem = useCallback((
    item: CanvasLibraryItem,
    dropAt: { x: number; y: number } | null = null,
    options: { replace?: boolean } = {},
  ) => {
    if (assetGeneratorId && options.replace !== false) {
      const target = nodesRef.current.find((node) => node.id === assetGeneratorId && node.type === "generator")
      const workflow = generationModes.find((mode) => mode.id === target?.data.workflowId)
      if (!target || !workflow || item.kind === "video") return
      if (isCanvasJobActive(target.data.jobId ? liveJobsRef.current[target.data.jobId]?.status ?? target.data.jobStatus : target.data.jobStatus) || submittingGeneratorIds.has(target.id)) return
      const references = incomingGeneratorReferenceNodes(nodesRef.current, edgesRef.current, target.id)
      if (!assetReferenceSourceId && references.length >= (workflow.max_references ?? 0)) {
        message.warning("已达到当前工作流的参考图上限")
        return
      }
      const reference = createLibraryNode(item, { x: target.position.x - 420, y: target.position.y + references.length * 48 })
      if (!reference) { message.warning("该素材暂不可用"); return }
      reference.position = findCanvasFreePosition(reference.position, canvasNodeSize(reference), nodesRef.current.filter((node) => node.type !== "artboard"))
      const edge = canvasConnectEdge(reference.id, target.id, "in")
      setNodes((current) => [...current.map((node) => ({ ...node, selected: node.id === target.id })), { ...reference, selected: false }])
      setEdges((current) => assetReferenceSourceId
        ? current.map((old) => old.target === target.id && old.source === assetReferenceSourceId ? { ...edge, targetHandle: old.targetHandle || "in", id: buildEdgeId(reference.id, target.id, "out", old.targetHandle || "in") } : old)
        : [...current, edge])
      closeAssetLibrary()
      message.success("参考图已连接")
      return
    }
    const replaceTargetId = options.replace === false ? null : assetTargetNodeId
    if (replaceTargetId) {
      const url = libraryItemUrl(item)
      if (!url) return
      const target = nodesRef.current.find((node) => node.id === replaceTargetId)
      if (!target) {
        closeAssetLibrary()
        return
      }
      updateNodeData(replaceTargetId, {
        url,
        label: target.data.label || item.label,
        assetPath: item.path,
        sourceJobId: item.job_id ?? null,
        mediaKind: item.kind === "video" ? "video" : "image",
        ...(item.kind === "video" ? { cover: undefined, coverSource: undefined, coverTime: undefined } : {}),
      })
      closeAssetLibrary()
      message.success(item.kind === "video" ? "视频素材已替换" : "图片素材已替换")
      return
    }
    const center = stageCenter()
    const offset = (nodesRef.current.length % 5) * 24
    const position = dropAt ?? {
      x: Math.round(center.x - 160 + offset),
      y: Math.round(center.y - 110 + offset),
    }
    const node = createLibraryNode(item, position, { center: Boolean(dropAt) })
    if (!node) {
      message.warning("该素材暂不可用，请选择已交付且地址有效的素材")
      return
    }
    if (!dropAt) node.position = findCanvasFreePosition(position, canvasNodeSize(node), nodesRef.current)
    appendNodes([node])
    revealAddedNode(node)
    message.success(item.kind === "video" ? "视频已插入画布" : "图片已插入画布")
  }, [appendNodes, assetGeneratorId, assetReferenceSourceId, assetTargetNodeId, closeAssetLibrary, generationModes, revealAddedNode, setEdges, setNodes, stageCenter, submittingGeneratorIds, updateNodeData])

  useEffect(() => {
    if (!insertRequest) return
    if (consumedInsertAssetRef.current === insertRequest.key) return
    if (insertAssetQuery.isLoading) return
    consumedInsertAssetRef.current = insertRequest.key
    if (insertAssetQuery.isError) {
      message.error("作品库加载失败，无法加入这份素材")
      clearInsertParams()
      return
    }
    const item = findCanvasInsertLibraryItem(insertAssetQuery.data?.items ?? [], insertRequest)
    if (!item) {
      message.warning("该素材不在当前账号的作品库中，无法加入画布")
      clearInsertParams()
      return
    }
    insertLibraryItem(item, null, { replace: false })
    clearInsertParams()
  }, [
    clearInsertParams,
    insertAssetQuery.data,
    insertAssetQuery.isError,
    insertAssetQuery.isLoading,
    insertLibraryItem,
    insertRequest,
  ])

  const isCanvasAssetDrag = (event: ReactDragEvent) => (
    Array.from(event.dataTransfer?.types ?? []).includes(CANVAS_ASSET_DRAG_TYPE)
  )

  const stageDropPoint = (event: ReactDragEvent) => {
    const rect = stageRef.current?.getBoundingClientRect()
    return rect ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : null
  }

  const startAssetDrag = useCallback((item: CanvasLibraryItem, event: ReactDragEvent<HTMLElement>) => {
    if (assetTargetNodeId) {
      event.preventDefault()
      return
    }
    event.dataTransfer.effectAllowed = "copy"
    event.dataTransfer.setData(CANVAS_ASSET_DRAG_TYPE, encodeCanvasAssetDrag(item))
    setDraggingAsset(item)
  }, [assetTargetNodeId])

  const endAssetDrag = useCallback(() => {
    dragDepthRef.current = 0
    setDropPoint(null)
    setDraggingAsset(null)
  }, [])

  const handleStageDragEnter = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
    if (!isCanvasAssetDrag(event)) return
    event.preventDefault()
    dragDepthRef.current += 1
    const point = stageDropPoint(event)
    if (point) setDropPoint(point)
  }, [])

  const handleStageDragOver = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
    if (!isCanvasAssetDrag(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"
    const point = stageDropPoint(event)
    if (point) setDropPoint(point)
  }, [])

  const handleStageDragLeave = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
    if (!isCanvasAssetDrag(event)) return
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDropPoint(null)
  }, [])

  const handleStageDrop = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
    if (!isCanvasAssetDrag(event)) return
    event.preventDefault()
    const item = decodeCanvasAssetDrag(event.dataTransfer.getData(CANVAS_ASSET_DRAG_TYPE))
    endAssetDrag()
    if (!item) {
      message.warning("未能识别拖入的素材，请从作品库重新拖拽")
      return
    }
    insertLibraryItem(item, screenToFlowPosition({ x: event.clientX, y: event.clientY }))
  }, [endAssetDrag, insertLibraryItem, screenToFlowPosition])

  const openAddImageDialog = useCallback((point?: { x: number; y: number }) => {
    pendingAddPointRef.current = point ?? null
    setImageUrl("")
    setAddImageOpen(true)
  }, [])

  const applyImage = useCallback(() => {
    const url = imageUrl.trim()
    if (url && !isSafeMediaUrl(url, "image")) {
      message.warning("请填写 http(s)、站内路径或 data:image 图片地址")
      return
    }
    const point = pendingAddPointRef.current
    const center = stageCenter()
    const offset = (nodesRef.current.length % 5) * 24
    const position = point ?? {
      x: Math.round(center.x - 160 + offset),
      y: Math.round(center.y - 100 + offset),
    }
    const node = createImageNode(position, url)
    if (!point) node.position = findCanvasFreePosition(position, canvasNodeSize(node), nodesRef.current)
    appendNodes([node])
    revealAddedNode(node)
    pendingAddPointRef.current = null
    setAddImageOpen(false)
  }, [appendNodes, imageUrl, revealAddedNode, stageCenter])

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return
    const edgeId = buildEdgeId(
      connection.source,
      connection.target,
      connection.sourceHandle ?? undefined,
      connection.targetHandle ?? undefined,
    )
    const currentEdges = edgesRef.current
    if (currentEdges.some((edge) => edge.source === connection.source && edge.target === connection.target)) return
    const nextEdges = [...currentEdges, {
      ...connection,
      id: edgeId,
      type: "smoothstep",
    } as CanvasEdge]
    setEdges(nextEdges)
    setRecentEdgeId(edgeId)

    const sourceNode = nodesRef.current.find((node) => node.id === connection.source)
    const targetNode = nodesRef.current.find((node) => node.id === connection.target)
    if (sourceNode?.type === "text" && !String(sourceNode.data.text ?? "").trim()) {
      message.warning("文字节点内容为空，补充文字后才能用于生成")
      return
    }
    if (!sourceNode || targetNode?.type !== "generator" || !canvasReferenceEligible(sourceNode)) return
    const mode = generationModes.find((item) => item.id === targetNode.data.workflowId) ?? null
    const countIssue = generatorReferenceIssue(
      mode,
      incomingGeneratorReferenceNodes(nodesRef.current, nextEdges, targetNode.id),
    )
    if (countIssue) message.warning(`连线已添加：${countIssue}`)
  }, [generationModes, setEdges])

  const isValidConnection = useCallback((connection: Connection | CanvasEdge) => {
    const { source, target } = connection
    if (!source || !target || source === target) return false
    const sourceNode = nodesRef.current.find((node) => node.id === source)
    const targetNode = nodesRef.current.find((node) => node.id === target)
    if (!sourceNode || !targetNode) return false
    if (targetNode.type === "generator") {
      return canvasReferenceEligible(sourceNode) || canvasPromptEligible(sourceNode)
    }
    if (targetNode.type === "image" || targetNode.type === "video") return sourceNode.type === "generator"
    return false
  }, [])

  const handleConnectStart = useCallback((event: MouseEvent | TouchEvent, params: OnConnectStartParams) => {
    connectStartRef.current = { ...params, screen: eventClientPoint(event) }
    setContextMenu(null)
    setConnectMenu(null)
  }, [])

  const handleConnectEnd = useCallback((event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
    const start = connectStartRef.current
    connectStartRef.current = null
    if (!start || !start.nodeId || start.handleType !== "source") return
    const screen = eventClientPoint(event)
    if (Math.abs(screen.x - start.screen.x) + Math.abs(screen.y - start.screen.y) < 10) return
    if (state.toHandle) return
    const source = nodesRef.current.find((node) => node.id === start.nodeId)
    const targets = canvasConnectTargets(source)
    if (!source || !targets.length) return
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    const size = canvasNodeSize(source)
    const fallbackFrom = { x: source.position.x + size.width, y: source.position.y + size.height / 2 }
    const menu = canvasConnectMenuPosition(
      { x: screen.x - rect.left, y: screen.y - rect.top },
      { width: rect.width, height: rect.height },
      { width: 252, height: 44 + targets.length * 52 },
    )
    setConnectMenu({
      ...menu,
      from: state.from ?? fallbackFrom,
      flow: screenToFlowPosition(screen),
      sourceId: source.id,
      sourceHandle: start.handleId ?? "out",
    })
  }, [screenToFlowPosition])

  const handleSnapDrag = useCallback((draggedNodes: CanvasNode[]) => {
    if (!settingsRef.current.guidesVisible || !draggedNodes.length) {
      setGuides((current) => (current.vertical.length || current.horizontal.length ? EMPTY_GUIDES : current))
      return
    }
    const movingIds = new Set(draggedNodes.map((node) => node.id))
    const others = nodesRef.current.filter((node) => !movingIds.has(node.id))
    const snap = computeSnapGuides(draggedNodes, others, 6 / getViewport().zoom)
    setGuides((current) => (sameGuides(current, snap.guides) ? current : snap.guides))
    if (snap.dx || snap.dy) {
      setNodes((current) => current.map((node) => (
        movingIds.has(node.id)
          ? { ...node, position: { x: node.position.x + snap.dx, y: node.position.y + snap.dy } }
          : node
      )))
    }
  }, [getViewport, setNodes])

  const compactEdgeIds = useMemo(() => {
    if (settings.connectionMode !== "compact") return null
    return compactCanvasEdgeIds(edges, {
      selectedNodeIds,
      selectedEdgeIds,
      recentEdgeId,
      hoveredNodeId,
    })
  }, [edges, hoveredNodeId, recentEdgeId, selectedEdgeIds, selectedNodeIds, settings.connectionMode])

  const nodeById = useMemo(() => {
    const map = new Map<string, CanvasNode>()
    for (const node of nodesRef.current) map.set(node.id, node)
    return map
  }, [nodeDataRevision])

  const visibleEdges = useMemo(() => {
    if (settings.connectionMode === "off") return []
    const visible = compactEdgeIds ? edges.filter((edge) => compactEdgeIds.has(edge.id)) : edges
    return visible.map((edge) => ({
      ...edge,
      type: "canvasFlow",
      style: { ...edge.style, stroke: edgeStroke(nodeById.get(edge.source)) },
    }))
  }, [compactEdgeIds, edges, nodeById, settings.connectionMode])

  const connectMenuTargets = useMemo(
    () => (connectMenu ? canvasConnectTargets(nodeById.get(connectMenu.sourceId)) : []),
    [connectMenu, nodeById],
  )

  const pendingConnectPath = useMemo(() => {
    if (!connectMenu) return null
    const [path] = getBezierPath({
      sourceX: connectMenu.from.x,
      sourceY: connectMenu.from.y,
      sourcePosition: Position.Right,
      targetX: connectMenu.flow.x,
      targetY: connectMenu.flow.y,
      targetPosition: Position.Left,
    })
    return path
  }, [connectMenu])

  useEffect(() => {
    if (!recentEdgeId) return
    const timer = window.setTimeout(() => setRecentEdgeId(null), 4000)
    return () => window.clearTimeout(timer)
  }, [recentEdgeId])

  useEffect(() => {
    setContextMenu(null)
    setConnectMenu(null)
  }, [tool])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (connectMenu) {
          setConnectMenu(null)
          event.preventDefault()
          return
        }
        if (contextMenu) {
          setContextMenu(null)
          event.preventDefault()
        }
        return
      }
      if (event.defaultPrevented || isTypingTarget(event.target)) return
      if (addImageOpen || exportOpen || assetOpen || preview || pendingImport || connectMenu || contextMenu) return
      const modifier = event.ctrlKey || event.metaKey
      const key = event.key.toLowerCase()

      if (modifier) {
        if (key === "z") {
          event.preventDefault()
          if (event.shiftKey) redo()
          else undo()
          return
        }
        if (key === "y") {
          event.preventDefault()
          redo()
          return
        }
        if (key === "d") {
          event.preventDefault()
          if (selectedNodeIds.length) {
            const duplicated = duplicateCanvasSelection(nodesRef.current, edgesRef.current, selectedNodeIds)
            if (duplicated.nodes.length) {
              setNodes((current) => [
                ...current.map((node) => ({ ...node, selected: false })),
                ...duplicated.nodes.map((node) => ({ ...node, selected: true })),
              ])
              setEdges((current) => [
                ...current.map((edge) => ({ ...edge, selected: false })),
                ...duplicated.edges,
              ])
              setSelectedNodeIds(duplicated.nodeIds)
              setSelectedEdgeIds([])
            }
          }
          return
        }
        if (key === "c") {
          event.preventDefault()
          copySelected()
          return
        }
        if (key === "v") {
          event.preventDefault()
          pasteClipboard()
          return
        }
        if (key === "a") {
          event.preventDefault()
          selectAllNodes()
          return
        }
        if (key === "s") {
          event.preventDefault()
          void saveDraft(true)
        }
        return
      }

      if (event.altKey) return
      if (key === "v") setTool("select")
      else if (key === "h") setTool("pan")
      else if (key === "t") addCanvasNode("text")
      else if (key === "a") addCanvasNode("image")
      else if (key === "g") addCanvasNode("generator")
      else if (key === "f") addCanvasNode("artboard")
      else if (key === "m") patchSettings({ minimapVisible: !settingsRef.current.minimapVisible })
      else if (/^[0-9]$/.test(event.key) || /^Digit[0-9]$/.test(event.code)) {
        const digit = /^Digit[0-9]$/.test(event.code) ? event.code.slice(-1) : event.key
        const index = digit === "0" ? 9 : Number(digit) - 1
        if (event.shiftKey) saveViewpoint(index)
        else jumpViewpoint(index)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [
    addCanvasNode, addImageOpen, assetOpen, connectMenu, contextMenu, copySelected, exportOpen, jumpViewpoint, pasteClipboard, patchSettings, pendingImport, preview, redo,
    saveDraft, saveViewpoint, selectAllNodes, selectedNodeIds, setEdges, setNodes, undo,
  ])

  const commitTitle = useCallback(() => {
    const nextTitle = title.trim()
    if (!nextTitle) {
      setTitle(savedTitleRef.current)
      return titleSaveRef.current
    }
    const pending = titleSaveRef.current.then(async () => {
      if (nextTitle === savedTitleRef.current) return true
      try {
        const updated = await renameCanvasProject(csrfToken, project.id, nextTitle)
        savedTitleRef.current = updated.title
        if (mountedRef.current && titleRef.current.trim() === nextTitle) setTitle(updated.title)
        if (mountedRef.current) message.success("标题已更新")
        return true
      } catch (error) {
        if (mountedRef.current) {
          if (titleRef.current.trim() === nextTitle) setTitle(savedTitleRef.current)
          message.error(errorText(error))
        }
        return false
      }
    })
    titleSaveRef.current = pending
    return pending
  }, [csrfToken, project.id, title])

  const leaveCanvas = useCallback(async () => {
    if (leaving) return
    setLeaving(true)
    try {
      const titleSaved = await commitTitle()
      const draftSaved = await saveDraft()
      if (titleSaved && draftSaved) onBack()
      else message.warning("画布尚未保存，请处理保存提示后再返回列表")
    } finally {
      if (mountedRef.current) setLeaving(false)
    }
  }, [commitTitle, leaving, onBack, saveDraft])

  const refreshVersions = useCallback(async () => {
    setVersionsLoading(true)
    try {
      setVersions(await listCanvasVersions(project.id))
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setVersionsLoading(false)
    }
  }, [project.id])

  const changePanelTab = useCallback((tab: CanvasPanelTab) => {
    setPanelTab(tab)
    if (tab === "history") void refreshVersions()
  }, [refreshVersions])

  const openHistoryPanel = useCallback(() => {
    setPanelOpen(true)
    changePanelTab("history")
  }, [changePanelTab])

  const openCanvasSettings = useCallback(() => {
    setCanvasSettingsPinned(true)
    setPanelOpen(true)
    changePanelTab("properties")
  }, [changePanelTab])

  const restoreVersion = useCallback(async (version: number) => {
    try {
      if (!await saveDraft()) {
        message.warning("请先处理当前画布的保存问题，再恢复历史版本")
        return
      }
      await restoreCanvasVersion(csrfToken, project.id, version)
      await reloadFromServer()
      await refreshVersions()
    } catch (error) {
      message.error(errorText(error))
    }
  }, [csrfToken, project.id, refreshVersions, reloadFromServer, saveDraft])

  const closePanel = useCallback(() => setPanelOpen(false), [])
  const openAssetLibraryFromPanel = useCallback(() => openAssetLibrary("image"), [openAssetLibrary])
  const replaceAssetFromPanel = useCallback(
    (nodeId: string, kind: CanvasMediaKind) => openAssetLibrary(kind, nodeId),
    [openAssetLibrary],
  )
  const nodeActions = useMemo<CanvasNodeActions>(() => ({
    openProperties,
    branchGenerate,
    duplicateNode,
    deleteNode,
    downloadNode,
    updateCover: updateNodeCover,
    chooseMedia: (nodeId, kind) => openAssetLibrary(kind, nodeId),
    saveCanvas: () => { void saveDraft(true) },
  }), [branchGenerate, deleteNode, downloadNode, duplicateNode, openProperties, openAssetLibrary, saveDraft, updateNodeCover])

  const reloadModesFromPanel = useCallback(() => {
    void modesQuery.refetch()
  }, [modesQuery.refetch])
  const submitFromPanel = useCallback((nodeId: string) => { void submitGenerator(nodeId) }, [submitGenerator])
  const cancelFromPanel = useCallback((nodeId: string) => { void cancelGenerator(nodeId) }, [cancelGenerator])
  const refineFromPanel = useCallback(
    (nodeId: string, action: "confirm" | "skip") => { void refineGenerator(nodeId, action) },
    [refineGenerator],
  )
  const refreshVersionsFromPanel = useCallback(() => { void refreshVersions() }, [refreshVersions])
  const restoreVersionFromPanel = useCallback((version: number) => { void restoreVersion(version) }, [restoreVersion])

  const openPaneContextMenu = useCallback((event: MouseEvent | ReactMouseEvent) => {
    event.preventDefault()
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    setContextMenu({
      kind: "pane",
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 236)),
      y: Math.max(8, Math.min(event.clientY - rect.top, rect.height - 440)),
      flow: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
    })
  }, [screenToFlowPosition])

  const openNodeContextMenu = useCallback((event: ReactMouseEvent, node: CanvasNode) => {
    event.preventDefault()
    if (!selectedNodeIdSet.has(node.id)) selectOnlyNode(node.id)
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    setContextMenu({
      kind: "node",
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 236)),
      y: Math.max(8, Math.min(event.clientY - rect.top, rect.height - 380)),
      nodeId: node.id,
    })
  }, [selectOnlyNode, selectedNodeIdSet])

  const openSelectionContextMenu = useCallback((event: ReactMouseEvent) => {
    event.preventDefault()
    if (!selectedNodeIds.length && !selectedEdgeIds.length) return
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    setContextMenu({
      kind: "selection",
      x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 236)),
      y: Math.max(8, Math.min(event.clientY - rect.top, rect.height - 320)),
    })
  }, [selectedEdgeIds.length, selectedNodeIds.length])

  const contextNode = contextMenu?.kind === "node"
    ? nodes.find((node) => node.id === contextMenu.nodeId) ?? null
    : null
  const contextNodeStatus = contextNode
    ? (contextNode.data.jobId ? liveJobs[contextNode.data.jobId]?.status : null)
      ?? contextNode.data.jobStatus
      ?? null
    : null
  const contextNodeResult = contextNode ? generatorResultFromNodeData(contextNode.data) : null
  const canAlign = selectedNodes.length >= 2
  const canDistribute = selectedNodes.length >= 3
  const arrangeItems: MenuProps["items"] = [
    { key: "left", icon: <AlignStartVertical size={15} />, label: "左对齐" },
    { key: "centerX", icon: <AlignCenterVertical size={15} />, label: "水平居中" },
    { key: "right", icon: <AlignEndVertical size={15} />, label: "右对齐" },
    { key: "top", icon: <AlignStartHorizontal size={15} />, label: "顶部对齐" },
    { key: "centerY", icon: <AlignCenterHorizontal size={15} />, label: "垂直居中" },
    { key: "bottom", icon: <AlignEndHorizontal size={15} />, label: "底部对齐" },
    { type: "divider" },
    {
      key: "distribute-horizontal",
      icon: <AlignHorizontalSpaceBetween size={15} />,
      label: "水平等距",
      disabled: !canDistribute,
    },
    {
      key: "distribute-vertical",
      icon: <AlignVerticalSpaceBetween size={15} />,
      label: "垂直等距",
      disabled: !canDistribute,
    },
  ]

  const addMenuItems: MenuProps["items"] = [
    { type: "group", label: "添加到画布", children: [
      { key: "generator", icon: <span className="canvas-menu-glyph is-generator"><Sparkles size={21} /></span>, label: <span className="canvas-menu-label"><strong>生成节点</strong><small>AI 生成图像或视频</small></span>, extra: <kbd>G</kbd> },
      { key: "text", icon: <span className="canvas-menu-glyph is-text"><Type size={21} /></span>, label: <span className="canvas-menu-label"><strong>文字</strong><small>添加提示词或文案</small></span>, extra: <kbd>T</kbd> },
      { key: "image", icon: <span className="canvas-menu-glyph is-image"><ImagePlus size={21} /></span>, label: <span className="canvas-menu-label"><strong>图片</strong><small>引用图片或创建占位</small></span>, extra: <kbd>A</kbd> },
      { key: "artboard", icon: <span className="canvas-menu-glyph is-artboard"><Square size={21} /></span>, label: <span className="canvas-menu-label"><strong>画板</strong><small>组织多节点的区域</small></span>, extra: <kbd>F</kbd> },
    ] },
    { type: "divider" },
    { key: "library-image", icon: <span className="canvas-menu-glyph is-artboard"><Images size={21} /></span>, label: <span className="canvas-menu-label"><strong>从作品库插入</strong><small>从已生成的内容中选择</small></span> },
  ]

  const handleAddMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "generator") addCanvasNode("generator")
    else if (key === "text") addCanvasNode("text")
    else if (key === "image") openAddImageDialog()
    else if (key === "artboard") addCanvasNode("artboard")
    else if (key === "library-image") openAssetLibrary("image")
    else if (key === "library-video") openAssetLibrary("video")
    else if (key === "image-url") openAddImageDialog()
  }

  const paneMenuItems: MenuProps["items"] = [
    ...(addMenuItems ?? []),
    { type: "divider" },
    {
      key: "paste",
      icon: <ClipboardPaste size={15} />,
      label: "粘贴",
      extra: "Ctrl V",
      disabled: !clipboardCount,
    },
    {
      key: "select-all",
      icon: <MousePointer2 size={15} />,
      label: "全选",
      extra: "Ctrl A",
      disabled: !nodes.length,
    },
  ]

  const handlePaneMenuClick: MenuProps["onClick"] = ({ key }) => {
    const point = contextMenu?.kind === "pane" ? contextMenu.flow : undefined
    setContextMenu(null)
    if (key === "paste") {
      pasteClipboard()
      return
    }
    if (key === "select-all") {
      selectAllNodes()
      return
    }
    if (key === "image") { openAddImageDialog(point); return }
    if (key === "generator" || key === "text" || key === "artboard") {
      addCanvasNode(key, point)
      return
    }
    if (key === "library-image") openAssetLibrary("image")
    else if (key === "library-video") openAssetLibrary("video")
    else if (key === "image-url") openAddImageDialog(point)
  }

  const nodeMenuItems: MenuProps["items"] = (() => {
    if (!contextNode) return []
    const items: NonNullable<MenuProps["items"]> = [
      { key: "properties", icon: <SlidersHorizontal size={15} />, label: "节点属性" },
    ]
    if (contextNode.type === "generator") {
      items.push(
        isCanvasJobActive(contextNodeStatus)
          ? { key: "cancel", icon: <Square size={14} />, label: "停止生成", danger: true }
          : {
            key: "submit",
            icon: <Sparkles size={15} />,
            label: contextNodeResult ? "重新生成" : "生成",
          },
      )
      items.push({ type: "divider" })
    }
    if (contextNode.type === "text" || contextNode.type === "image" || contextNode.type === "generator") {
      items.push(
        { key: "branch-right", icon: <MoveRight size={15} />, label: "向右生成" },
        { key: "branch-down", icon: <MoveDown size={15} />, label: "向下生成" },
        { type: "divider" },
      )
    }
    items.push({ key: "duplicate", icon: <CopyPlus size={15} />, label: "复制节点" })
    if (canvasNodeMediaUrl(contextNode)) {
      items.push({ key: "download", icon: <Download size={15} />, label: "下载素材" })
    }
    items.push(
      { type: "divider" },
      { key: "delete", icon: <Trash2 size={15} />, label: "删除节点", danger: true },
    )
    return items
  })()

  const handleNodeMenuClick: MenuProps["onClick"] = ({ key }) => {
    const node = contextNode
    setContextMenu(null)
    if (!node) return
    if (key === "properties") openProperties(node.id)
    else if (key === "submit") void submitGenerator(node.id)
    else if (key === "cancel") void cancelGenerator(node.id)
    else if (key === "branch-right") branchGenerate(node.id, "right")
    else if (key === "branch-down") branchGenerate(node.id, "down")
    else if (key === "duplicate") duplicateNode(node.id)
    else if (key === "download") downloadNode(node.id)
    else if (key === "delete") deleteNode(node.id)
  }

  const selectionMenuItems: MenuProps["items"] = [
    {
      key: "duplicate",
      icon: <CopyPlus size={15} />,
      label: `复制 ${selectedNodeIds.length} 个节点`,
      disabled: !selectedNodeIds.length,
    },
    {
      key: "arrange",
      icon: <AlignHorizontalSpaceAround size={15} />,
      label: "对齐与分布",
      disabled: !canAlign,
      children: arrangeItems,
    },
    { type: "divider" },
    {
      key: "delete",
      icon: <Trash2 size={15} />,
      label: "删除选中",
      danger: true,
    },
  ]

  const handleSelectionMenuClick: MenuProps["onClick"] = ({ key }) => {
    setContextMenu(null)
    if (key === "duplicate") duplicateSelected()
    else if (key === "delete") deleteSelected()
    else arrangeSelected(key as CanvasAlignMode | `distribute-${CanvasDistributeAxis}`)
  }

  const duplicateSelected = useCallback(() => {
    if (!selectedNodeIds.length) return
    const duplicated = duplicateCanvasSelection(nodesRef.current, edgesRef.current, selectedNodeIds)
    if (!duplicated.nodes.length) return
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...duplicated.nodes.map((node) => ({ ...node, selected: true })),
    ])
    setEdges((current) => [
      ...current.map((edge) => ({ ...edge, selected: false })),
      ...duplicated.edges,
    ])
    setSelectedNodeIds(duplicated.nodeIds)
    setSelectedEdgeIds([])
  }, [selectedNodeIds, setEdges, setNodes])

  const handleNodeDrag = useCallback((_event: unknown, _node: CanvasNode, draggedNodes: CanvasNode[]) => {
    handleSnapDrag(draggedNodes)
  }, [handleSnapDrag])

  const handleNodeDragStart = useCallback(() => {
    setContextMenu(null)
  }, [])

  const onNodeDragEnd = useCallback(() => {
    setGuides((current) => (current.vertical.length || current.horizontal.length ? EMPTY_GUIDES : current))
    setDragSettledRevision((revision) => revision + 1)
  }, [])

  const minimapNodeColor = useCallback((node: CanvasNode) => {
    if (node.type === "artboard") return "var(--studio-border-strong)"
    if (node.type === "video") return "var(--canvas-video-tone)"
    if (node.type === "image") return "var(--canvas-image-tone)"
    if (node.type === "text") return "var(--canvas-text-tone)"
    return "var(--studio-primary)"
  }, [])

  const minimapShapeToken = useMemo(() => {
    if (nodes.some((node) => node.dragging)) return "dragging"
    return nodes.map((node) => {
      const size = canvasNodeSize(node)
      return `${node.id}:${node.position.x}:${node.position.y}:${size.width}:${size.height}`
    }).join("|")
  }, [nodes])

  const MinimapNodeShape = useCallback((props: MiniMapNodeProps) => {
    const { id, x, y, width, height, color, onClick } = props
    const nodesNow = nodesRef.current
    const edgesNow = edgesRef.current
    return (
      <g>
        {edgesNow.filter((edge) => edge.source === id).map((edge) => {
          const target = nodesNow.find((node) => node.id === edge.target)
          if (!target) return null
          const targetSize = canvasNodeSize(target)
          const sx = x + width
          const sy = y + height / 2
          const tx = target.position.x
          const ty = target.position.y + targetSize.height / 2
          const bend = Math.max(24, Math.abs(tx - sx) / 2)
          return <path key={edge.id} d={`M${sx},${sy} C${sx + bend},${sy} ${tx - bend},${ty} ${tx},${ty}`} fill="none" stroke={color} strokeWidth={0.8} vectorEffect="non-scaling-stroke" pointerEvents="none" />
        })}
        <rect className="react-flow__minimap-node" x={x} y={y} width={width} height={height} rx={6} style={{ fill: `color-mix(in srgb, ${color} 12%, var(--studio-surface))`, stroke: color, strokeWidth: 0.8 }} vectorEffect="non-scaling-stroke" onClick={onClick ? (event) => onClick(event, id) : undefined} />
      </g>
    )
  }, [edges, minimapShapeToken])

  const generatorContextValue = useMemo(() => {
    const promptStateFor = (nodeId: string): CanvasGeneratorPromptState => {
      const currentNodes = nodesRef.current
      const node = currentNodes.find((item) => item.id === nodeId && item.type === "generator")
      if (!node) return { text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }
      const source = resolveGeneratorPrompt(
        incomingGeneratorPromptNodes(currentNodes, edgesRef.current, nodeId),
        node.data.prompt ?? "",
      )
      return {
        text: source.text,
        connectedTextNodes: source.nodes.length,
        emptyTextNodes: source.emptyCount,
        fromTextNodes: source.fromTextNodes,
      }
    }
    return {
      modes: generationModes,
      modesLoading: modesQuery.isLoading,
      disconnectInput: (nodeId: string, kind: "text" | "image") => {
        setEdges((current) => current.filter((edge) => {
          if (edge.target !== nodeId) return true
          const source = nodesRef.current.find((item) => item.id === edge.source)
          return kind === "text" ? source?.type !== "text" : !source || !canvasReferenceEligible(source)
        }))
      },
      workflowName: (workflowId?: string) => {
        if (!workflowId) return "未选择工作流"
        return generationModes.find((mode) => mode.id === workflowId)?.name ?? workflowId
      },
      modeFor: (workflowId?: string) => generationModes.find((mode) => mode.id === workflowId) ?? null,
      liveFor: (jobId?: string | null) => (jobId ? liveJobs[jobId] ?? null : null),
      referenceCountFor: (nodeId: string) => incomingGeneratorReferenceNodes(nodesRef.current, edgesRef.current, nodeId).length,
      referencesFor: (nodeId: string) => incomingGeneratorReferenceNodes(nodesRef.current, edgesRef.current, nodeId),
      chooseReference: (nodeId: string, sourceId?: string) => {
        setAssetKind("image")
        setAssetTargetNodeId(null)
        setAssetGeneratorId(nodeId)
        setAssetReferenceSourceId(sourceId ?? null)
        setAssetOpen(true)
      },
      removeReference: (nodeId: string, sourceId: string) => setEdges((current) => current.filter((edge) => !(edge.target === nodeId && edge.source === sourceId))),
      moveReference: (nodeId: string, sourceId: string, direction: -1 | 1) => setEdges((current) => reorderCanvasReferenceEdges(current, nodesRef.current, nodeId, sourceId, direction)),
      promptInfoFor: promptStateFor,
      issueFor: (nodeId: string) => {
        const currentNodes = nodesRef.current
        const node = currentNodes.find((item) => item.id === nodeId && item.type === "generator")
        if (!node) return null
        const prompt = promptStateFor(nodeId)
        const mode = generationModes.find((item) => item.id === node.data.workflowId) ?? null
        return validateGeneratorInput(
          mode,
          prompt.text,
          incomingGeneratorReferenceNodes(currentNodes, edgesRef.current, nodeId),
          { connectedTextNodes: prompt.connectedTextNodes, emptyTextNodes: prompt.emptyTextNodes },
        )
      },
      submit: (nodeId: string) => { void submitGenerator(nodeId) },
      cancel: (nodeId: string) => { void cancelGenerator(nodeId) },
      refine: (nodeId: string, action: "confirm" | "skip") => { void refineGenerator(nodeId, action) },
      insertResult: (nodeId: string, direction: CanvasBranchDirection) => insertGeneratorResult(nodeId, direction),
      submitting: (nodeId: string) => submittingGeneratorIds.has(nodeId),
    }
  }, [
    cancelGenerator, edges, generationModes, insertGeneratorResult, liveJobs, modesQuery.isLoading, nodeDataRevision,
    submitGenerator, refineGenerator, submittingGeneratorIds,
  ])


  const contentSizeLevel = canvasContentSizeLevel(contentBytes)
  const saveNotice: {
    type: "warning" | "error"
    message: string
    description?: string
    action?: ReactNode
  } | null = (() => {
    if (conflictVersionNumber !== null) return null
    if (contentSizeLevel === "over") {
      return {
        type: "error",
        message: `画布体积约 ${formatCanvasBytes(contentBytes)}，超过 8 MB 上限`,
        description: "请删除大型内嵌图片或改用素材地址后再保存。",
      }
    }
    if (saveState === "retrying") {
      return {
        type: "warning",
        message: `保存失败，${Math.round(retryDelayMs / 1000)} 秒后自动重试（${retryAttempt}/3）`,
        description: saveError ? `${saveError}。网络恢复后会自动保存。` : undefined,
        action: <Button size="small" onClick={() => { void saveDraft() }}>立即重试</Button>,
      }
    }
    if (saveState === "error") {
      return {
        type: "error",
        message: "保存失败",
        description: saveError ? `${saveError}。可点击“立即重试”。` : "可点击“立即重试”。",
        action: <Button size="small" onClick={() => { void saveDraft() }}>立即重试</Button>,
      }
    }
    if (contentSizeLevel === "warning") {
      return {
        type: "warning",
        message: `画布体积约 ${formatCanvasBytes(contentBytes)}，接近 8 MB 上限`,
        description: "建议改用素材地址或删除大型内嵌图片，避免保存失败。",
      }
    }
    return null
  })()
  const shortcutContent = (
    <div className="canvas-shortcut-list">
      <div><span>选择 / 移动工具</span><span><kbd>V</kbd> / <kbd>H</kbd></span></div>
      <div><span>生成节点 / 文本 / 图片 / 画板</span><span><kbd>G</kbd> <kbd>T</kbd> <kbd>A</kbd> <kbd>F</kbd></span></div>
      <div><span>切换小地图</span><kbd>M</kbd></div>
      <div><span>撤销 / 重做</span><span><kbd>Ctrl/⌘ Z</kbd> / <kbd>Ctrl/⌘ Shift Z</kbd></span></div>
      <div><span>复制节点 / 复制 / 粘贴</span><span><kbd>Ctrl/⌘ D</kbd> <kbd>C</kbd> <kbd>V</kbd></span></div>
      <div><span>全选 / 保存</span><span><kbd>Ctrl/⌘ A</kbd> / <kbd>S</kbd></span></div>
      <div><span>跳转视角 / 保存视角</span><span><kbd>1–0</kbd> / <kbd>Shift</kbd> + <kbd>1–0</kbd></span></div>
      <div><span>多选 / 框选</span><span><kbd>Ctrl/⌘</kbd> 点击 / <kbd>Shift</kbd> 拖拽</span></div>
      <div><span>平移 / 缩放</span><span><kbd>Space</kbd> 拖拽 / 滚轮</span></div>
      <div><span>右键画布或节点</span><span>打开快捷菜单</span></div>
    </div>
  )

  const imageUrlInvalid = Boolean(imageUrl.trim()) && !isSafeMediaUrl(imageUrl.trim(), "image")

  return (
    <div className="canvas-workspace canvas-editor-workspace">
      <header className="canvas-editor-header canvas-chrome-bar">
        <div className="canvas-editor-project">
        <Tooltip title="返回画布列表"><Button type="text" loading={leaving} icon={<ChevronLeft size={20} />} aria-label="返回画布列表" onClick={() => { void leaveCanvas() }} /></Tooltip>
        <span className="canvas-editor-breadcrumb">无限画布 <span>/</span></span>
        <Input
          id="canvas-title"
          name="canvas-title"
          className="canvas-title-input"
          style={{ width: `${Math.min(330, Math.max(176, title.length * 13 + 8))}px` }}
          value={title}
          maxLength={120}
          aria-label="画布标题"
          onChange={(event) => setTitle(event.target.value)}
          onBlur={() => { void commitTitle() }}
          onPressEnter={(event) => { (event.target as HTMLInputElement).blur() }}
        />
        <Button type="text" className="canvas-title-edit" icon={<Pencil size={17} />} aria-label="编辑画布标题" onClick={() => document.getElementById("canvas-title")?.focus()} />
        <Tooltip title={`最近保存：${formatCanvasTime(savedAt)} · 改动会自动保存`}>
          <span className={`canvas-save-tag canvas-save-${saveState}`} role="status">
            {saveState === "saving" || saveState === "retrying" ? <LoaderCircle size={13} className="animate-spin" /> : saveState === "saved" ? <Check size={13} /> : <span className="canvas-save-dot" />}
            {saveStateLabels[saveState]}
          </span>
        </Tooltip>
        </div>
        <div className="canvas-editor-controls">
        <Button className="canvas-header-history" type="text" icon={<History size={22} />} onClick={openHistoryPanel}>历史</Button>
        <Tooltip title="图层"><Button type="text" icon={<PanelRight size={16} />} aria-label="图层" onClick={() => { setPanelOpen(true); changePanelTab("layers") }} /></Tooltip>
        <Button className="canvas-header-settings" type="text" icon={<Settings size={22} />} onClick={openCanvasSettings}>设置</Button>
        <Tooltip title={panelOpen ? "收起属性面板" : "展开属性面板"}>
          <Button className={panelOpen ? "canvas-panel-toggle is-active" : "canvas-panel-toggle"} type="text" icon={<ImageIcon size={22} />} aria-pressed={panelOpen} onClick={() => setPanelOpen((open) => !open)}>属性</Button>
        </Tooltip>
        <Dropdown
          trigger={["click"]}
          classNames={{ root: "canvas-popup canvas-file-menu" }}
          menu={{
            items: [
              { key: "save", icon: <Check size={15} />, label: "立即保存" },
              { key: "export-png", icon: <ImageIcon size={15} />, label: "导出 PNG" },
              { type: "divider" },
              { key: "export", icon: <Download size={15} />, label: "导出 JSON" },
              { key: "import", icon: <Upload size={15} />, label: "导入 JSON" },
            ],
            onClick: ({ key }) => {
              if (key === "save") void saveDraft(true)
              if (key === "export-png") setExportOpen(true)
              if (key === "export") exportJson()
              if (key === "import") fileInputRef.current?.click()
            },
          }}
        >
          <Button type="text" icon={<MoreHorizontal size={18} />} aria-label="更多画布操作" />
        </Dropdown>
        <Button className="canvas-header-export" icon={<Download size={15} />} onClick={() => setExportOpen(true)}>导出</Button>
        </div>
      </header>
      <input
        ref={fileInputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => { void handleImportFile(event) }}
      />

      {conflictVersionNumber !== null ? (
        <Alert
          className="canvas-conflict-alert"
          type="warning"
          showIcon
          title="画布已在其他窗口更新"
          description={`服务器当前版本为 v${conflictVersionNumber || "未知"}，本页改动尚未保存。加载最新版本会替换本页内容，可先导出草稿备份。`}
          action={<Space wrap><Button size="small" onClick={exportJson}>导出本页草稿</Button><Button size="small" loading={reloading} onClick={() => { void reloadFromServer() }}>加载最新版本</Button></Space>}
        />
      ) : null}
      {saveNotice ? (
        <Alert
          className="canvas-save-alert"
          type={saveNotice.type}
          showIcon
          title={saveNotice.message}
          description={saveNotice.description}
          action={saveNotice.action}
        />
      ) : null}

      <div className="canvas-editor-body">
        <div
          className={`canvas-stage canvas-flow canvas-tool-${tool} canvas-connections-${settings.connectionMode}`}
          ref={stageRef}
          onDragEnter={handleStageDragEnter}
          onDragOver={handleStageDragOver}
          onDragLeave={handleStageDragLeave}
          onDrop={handleStageDrop}
        >
          <div className="canvas-rail" role="toolbar" aria-label="画布工具">
            <Tooltip title="选择 (V)" placement="right">
              <Button
                type="text"
                className={tool === "select" ? "is-active" : undefined}
                icon={<MousePointer2 size={17} />}
                onClick={() => setTool("select")}
                aria-label="选择工具"
                aria-pressed={tool === "select"}
              />
            </Tooltip>
            <Tooltip title="移动画布 (H)" placement="right">
              <Button
                type="text"
                className={tool === "pan" ? "is-active" : undefined}
                icon={<Hand size={17} />}
                onClick={() => setTool("pan")}
                aria-label="移动工具"
                aria-pressed={tool === "pan"}
              />
            </Tooltip>
            <span className="canvas-rail-divider" />
            <Dropdown trigger={["click"]} placement="rightTop" classNames={{ root: "canvas-popup canvas-add-menu" }} align={{ offset: [8, -2] }} menu={{ items: addMenuItems, onClick: handleAddMenuClick }}>
              <Button className="canvas-rail-add" type="primary" icon={<Plus size={18} />} aria-label="添加节点" />
            </Dropdown>
            <Tooltip title="添加文字 (T)" placement="right">
              <Button type="text" icon={<Type size={18} />} onClick={() => addCanvasNode("text")} aria-label="添加文字" />
            </Tooltip>
            <Tooltip title="添加图片 (A)" placement="right"><Button type="text" icon={<ImageIcon size={22} />} onClick={() => openAddImageDialog()} aria-label="添加图片" /></Tooltip>
            <Tooltip title="添加生成节点 (G)" placement="right"><Button type="text" icon={<Sparkles size={22} />} onClick={() => addCanvasNode("generator")} aria-label="添加生成节点" /></Tooltip>
            <Tooltip title="新建画板 (F)" placement="right"><Button type="text" icon={<Square size={22} />} onClick={() => addCanvasNode("artboard")} aria-label="新建画板" /></Tooltip>
            <span className="canvas-rail-divider" />
            <Tooltip title={historyState.canUndo ? "撤销 (Ctrl/⌘ Z)" : "没有可撤销的操作"} placement="right">
              <Button icon={<Undo2 size={17} />} disabled={!historyState.canUndo} onClick={undo} aria-label="撤销" />
            </Tooltip>
            <Tooltip title={historyState.canRedo ? "重做 (Ctrl/⌘ Shift Z)" : "没有可重做的操作"} placement="right">
              <Button icon={<Redo2 size={17} />} disabled={!historyState.canRedo} onClick={redo} aria-label="重做" />
            </Tooltip>
            <Popover classNames={{ root: "canvas-popover canvas-shortcuts-popover" }} content={shortcutContent} title={<span className="canvas-popover-heading"><Keyboard size={15} />快捷键</span>} trigger="click" placement="rightBottom">
              <Button icon={<Keyboard size={17} />} aria-label="快捷键说明" />
            </Popover>
          </div>

          <CanvasNodeActionsContext.Provider value={nodeActions}>
          <CanvasGeneratorContext.Provider value={generatorContextValue}>
          <CanvasMediaPreviewContext.Provider value={openMediaPreview}>
            <ReactFlow
              nodes={nodes}
              edges={visibleEdges}
              nodeTypes={baseNodeTypes}
              edgeTypes={edgeTypes}
              onNodesChange={handleNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={handleConnectStart}
              onConnectEnd={handleConnectEnd}
              isValidConnection={isValidConnection}
              onMoveEnd={handleViewportChange}
              onMoveStart={() => {
                setContextMenu(null)
                setConnectMenu(null)
              }}
              onPaneClick={() => {
                setContextMenu(null)
                setConnectMenu(null)
              }}
              onPaneContextMenu={openPaneContextMenu}
              onNodeContextMenu={openNodeContextMenu}
              onNodeClick={() => setCanvasSettingsPinned(false)}
              onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
              onNodeMouseLeave={() => setHoveredNodeId(null)}
              onSelectionContextMenu={openSelectionContextMenu}
              onNodeDrag={handleNodeDrag}
              onNodeDragStart={handleNodeDragStart}
              onNodeDragStop={onNodeDragEnd}
              defaultViewport={initialSettings.viewport ?? undefined}
              fitView={!initialSettings.viewport}
              fitViewOptions={{ padding: 0.28, maxZoom: 1 }}
              minZoom={CANVAS_MIN_ZOOM}
              maxZoom={CANVAS_MAX_ZOOM}
              onlyRenderVisibleElements={shouldVirtualizeCanvasNodes(nodes.length)}
              deleteKeyCode={["Backspace", "Delete"]}
              defaultEdgeOptions={{ type: "smoothstep" }}
              colorMode={themeMode}
              proOptions={{ hideAttribution: false }}
              panOnDrag={tool === "pan" ? true : [1]}
              selectionOnDrag={tool === "select"}
              selectionMode={SelectionMode.Partial}
              selectionKeyCode="Shift"
              multiSelectionKeyCode={["Meta", "Control"]}
              panActivationKeyCode="Space"
              nodesDraggable={tool === "select"}
              nodesConnectable={settings.connectionMode !== "off"}
              connectionRadius={26}
              zoomOnDoubleClick={false}
              elementsSelectable
            >
              {settings.gridVisible ? <Background gap={22} size={1} color="var(--canvas-grid-dot)" /> : null}
              <ViewportPortal>
                {guides.vertical.map((x, index) => (
                  <div
                    key={`v-${index}-${x}`}
                    className="canvas-guide is-vertical"
                    style={{ top: -100000, height: 200000, transform: `translateX(${x}px)` }}
                  />
                ))}
                {guides.horizontal.map((y, index) => (
                  <div
                    key={`h-${index}-${y}`}
                    className="canvas-guide is-horizontal"
                    style={{ left: -100000, width: 200000, transform: `translateY(${y}px)` }}
                  />
                ))}
                {connectMenu && pendingConnectPath ? (
                  <svg className="canvas-pending-connection" width="1" height="1" aria-hidden="true">
                    <path d={pendingConnectPath} className="canvas-pending-path" />
                    <circle cx={connectMenu.flow.x} cy={connectMenu.flow.y} r={4.5} className="canvas-pending-dot" />
                  </svg>
                ) : null}
              </ViewportPortal>
              {settings.minimapVisible ? (
                <MiniMap
                  pannable
                  zoomable
                  position="bottom-left"
                  className="canvas-minimap"
                  nodeComponent={MinimapNodeShape}
                  nodeStrokeColor={minimapNodeColor}
                  nodeStrokeWidth={1.5}
                  nodeColor={minimapNodeColor}
                  maskColor={themeMode === "dark" ? "rgba(9, 12, 17, 0.72)" : "rgba(245, 247, 250, 0.72)"}
                  style={{
                    margin: "0 0 77px 13px",
                    width: 148,
                    height: 86,
                    background: "var(--studio-surface)",
                    border: "1px solid var(--studio-border)",
                  }}
                />
              ) : null}
            </ReactFlow>
          </CanvasMediaPreviewContext.Provider>
          </CanvasGeneratorContext.Provider>
          </CanvasNodeActionsContext.Provider>

          <div className="canvas-bottombar" role="toolbar" aria-label="画布视图">
            <Tooltip title={settings.minimapVisible ? "隐藏小地图 (M)" : "显示小地图 (M)"}>
              <Button
                type="text"
                className={settings.minimapVisible ? "is-active" : undefined}
                icon={<MapIcon size={15} />}
                onClick={() => patchSettings({ minimapVisible: !settings.minimapVisible })}
                aria-label="切换小地图"
              />
            </Tooltip>
            <span className="canvas-bottombar-divider" />
            <Tooltip title="缩小">
              <Button type="text" icon={<Minus size={15} />} onClick={() => { void zoomOut({ duration: 160 }) }} aria-label="缩小" />
            </Tooltip>
            <Dropdown trigger={["click"]} placement="top" classNames={{ root: "canvas-popup canvas-zoom-menu" }} menu={{
              selectable: true,
              selectedKeys: [String(Math.round(zoom * 100))],
              items: [25, 50, 75, 100, 150, 200].map((value) => ({ key: String(value), label: `${value}%`, extra: value === 100 ? "原始大小" : undefined })),
              onClick: ({ key }) => { void zoomTo(Number(key) / 100, { duration: 200 }) },
            }}>
              <Button type="text" className="canvas-zoom-value" aria-label="选择缩放比例">{Math.round(zoom * 100)}% <ChevronDown size={12} /></Button>
            </Dropdown>
            <Tooltip title="放大">
              <Button type="text" icon={<Plus size={15} />} onClick={() => { void zoomIn({ duration: 160 }) }} aria-label="放大" />
            </Tooltip>
            <Tooltip title="适应画布">
              <Button type="text" icon={<Focus size={15} />} onClick={() => { void fitView({ padding: 0.2, duration: 300 }) }} aria-label="适应画布" />
            </Tooltip>
            <span className="canvas-bottombar-divider" />
            <Popover
              trigger="click"
              placement="topRight"
              classNames={{ root: "canvas-popover canvas-viewmode-popover" }}
              title={<span className="canvas-popover-heading"><Waypoints size={15} />连线与生成模式</span>}
              content={<CanvasViewModeMenu settings={settings} onChange={patchSettings} />}
            >
              <Tooltip title="连线与生成模式">
                <Button type="text" className="canvas-viewmode-trigger" icon={<Waypoints size={15} />} aria-label="连线与生成模式" />
              </Tooltip>
            </Popover>
            <Popover trigger="click" placement="topRight" classNames={{ root: "canvas-popover canvas-viewpoints-popover" }} title="保存的视角" content={(
              <div className="canvas-viewpoints-content">
              <p>点击空位保存当前视角，点击已存视角跳转。</p>
              <div className="canvas-viewpoints" aria-label="保存的视角">
              {settings.viewpoints.map((viewpoint, index) => (
                <Tooltip
                  key={index}
                  title={viewpoint
                    ? "点击跳转 · Shift + 数字覆盖 · 右键清除"
                    : "点击保存当前视角"}
                >
                  <button
                    type="button"
                    className={`canvas-viewpoint${viewpoint ? " is-saved" : ""}`}
                    aria-label={`视角 ${index === 9 ? 0 : index + 1}${viewpoint ? "，已保存" : "，点击保存"}`}
                    onClick={() => viewpoint ? jumpViewpoint(index) : saveViewpoint(index)}
                    onContextMenu={(event) => {
                      event.preventDefault()
                      clearViewpoint(index)
                    }}
                  >
                    {index === 9 ? 0 : index + 1}
                  </button>
                </Tooltip>
              ))}
              </div>
              <small><kbd>Shift</kbd> + <kbd>数字</kbd> 保存或覆盖 · 右键清除</small>
              </div>
            )}>
              <Button type="text" className="canvas-viewpoints-trigger">视角 <ChevronDown size={12} /></Button>
            </Popover>
          </div>

          {nodes.length ? <div className="canvas-stage-hint"><span><kbd>空格</kbd>拖拽平移</span><span>·</span>滚轮缩放</div> : null}

          {!nodes.length ? (
            <div className="canvas-empty-hint">
              <span className="canvas-empty-symbol"><Sparkles size={25} /></span>
              <strong>把灵感连成作品</strong>
              <span>从一段文字、一张参考图，或一个生成节点开始。</span>
              <div className="canvas-empty-hint-actions"><Button type="primary" icon={<Plus size={15} />} onClick={() => addCanvasNode("generator")}>添加生成节点</Button><Button icon={<Images size={15} />} onClick={() => openAssetLibrary("image")}>从作品库插入</Button></div>
              <small>也可以右键画布添加 · T 文字 · G 生成 · F 画板</small>
            </div>
          ) : null}

          {draggingAsset && dropPoint ? (
            <div className="canvas-drop-feedback" aria-hidden="true">
              <span className="canvas-drop-hint">
                {draggingAsset.kind === "video" ? <Video size={13} /> : <ImageIcon size={13} />}
                松开鼠标插入{draggingAsset.kind === "video" ? "视频" : "图片"}
              </span>
              <span
                className="canvas-drop-ghost"
                style={{
                  left: dropPoint.x,
                  top: dropPoint.y,
                  width: Math.max(96, CANVAS_LIBRARY_NODE_SIZES[draggingAsset.kind === "video" ? "video" : "image"].width * zoom),
                  height: Math.max(54, CANVAS_LIBRARY_NODE_SIZES[draggingAsset.kind === "video" ? "video" : "image"].height * zoom),
                }}
              >
                {draggingAsset.kind === "video" ? <Video size={15} /> : <ImageIcon size={15} />}
                {draggingAsset.label || (draggingAsset.kind === "video" ? "视频素材" : "图片素材")}
              </span>
            </div>
          ) : null}

          {contextMenu ? (
            <>
              <div
                className="canvas-context-backdrop"
                onPointerDown={() => setContextMenu(null)}
                onContextMenu={(event) => {
                  event.preventDefault()
                  setContextMenu(null)
                }}
              />
              <div
                className="canvas-context-menu"
                style={{ left: contextMenu.x, top: contextMenu.y, maxHeight: `calc(100% - ${contextMenu.y + 8}px)` }}
              >
                <Menu
                  selectable={false}
                  items={contextMenu.kind === "node"
                    ? nodeMenuItems
                    : contextMenu.kind === "selection"
                      ? selectionMenuItems
                      : paneMenuItems}
                  onClick={contextMenu.kind === "node"
                    ? handleNodeMenuClick
                    : contextMenu.kind === "selection"
                      ? handleSelectionMenuClick
                      : handlePaneMenuClick}
                />
              </div>
            </>
          ) : null}

          {connectMenu && connectMenuTargets.length ? (
            <>
              <div
                className="canvas-context-backdrop"
                onPointerDown={() => setConnectMenu(null)}
                onContextMenu={(event) => {
                  event.preventDefault()
                  setConnectMenu(null)
                }}
              />
              <div
                className="canvas-connect-menu"
                style={{ left: connectMenu.x, top: connectMenu.y }}
              >
                <div className="canvas-connect-heading">
                  <span>添加节点</span>
                  <small>选择后自动连线</small>
                </div>
                <Menu
                  selectable={false}
                  items={connectMenuTargets.map((target) => ({
                    key: target.key,
                    icon: target.kind === "generator"
                      ? <Sparkles size={16} />
                      : target.kind === "video"
                        ? <Video size={16} />
                        : <ImageIcon size={16} />,
                    label: (
                      <span className="canvas-connect-item">
                        <strong>{target.label}</strong>
                        <small>{target.description}</small>
                      </span>
                    ),
                  }))}
                  onClick={({ key }) => applyConnectTarget(key)}
                />
              </div>
            </>
          ) : null}
        </div>

        {panelOpen ? (
          <CanvasSidePanel
            tab={panelTab}
            onTabChange={changePanelTab}
            onClose={closePanel}
            nodes={panelNodes}
            edgeCount={edges.length}
            selectedNode={canvasSettingsPinned && panelTab === "properties" ? null : selectedNode}
            settings={settings}
            onSettingsChange={patchSettings}
            onSelectNode={selectOnlyNode}
            onFocusNode={focusNode}
            onDeleteNode={deleteNode}
            onDuplicateNode={duplicateNode}
            onOpenAssetLibrary={openAssetLibraryFromPanel}
            onPreview={openMediaPreview}
            onReplaceAsset={replaceAssetFromPanel}
            onUpdateCover={updateNodeCover}
            modes={generationModes}
            modesLoading={modesQuery.isLoading}
            modesError={modesQuery.isError ? errorText(modesQuery.error) : null}
            onReloadModes={reloadModesFromPanel}
            references={selectedGeneratorReferences}
            promptNodes={selectedGeneratorPromptNodes}
            live={selectedNodeId && selectedNode?.data.jobId
              ? liveJobs[selectedNode.data.jobId] ?? null
              : null}
            submitting={selectedNodeId !== null && submittingGeneratorIds.has(selectedNodeId)}
            onSubmit={submitFromPanel}
            onCancel={cancelFromPanel}
            onRefine={refineFromPanel}
            onInsertResult={insertGeneratorResult}
            onOpenJob={openGeneratorJob}
            historyState={historyState}
            onUndo={undo}
            onRedo={redo}
            versions={versions}
            versionsLoading={versionsLoading}
            onRefreshVersions={refreshVersionsFromPanel}
            onRestoreVersion={restoreVersionFromPanel}
            projectTitle={title}
            contentBytes={contentBytes}
            savedAt={savedAt}
          />
        ) : null}
      </div>

      <Modal
        className="canvas-dialog"
        width={480}
        title="通过图片地址添加"
        open={addImageOpen}
        okText={imageUrl.trim() ? "添加图片" : "创建占位节点"}
        okButtonProps={{ disabled: imageUrlInvalid }}
        cancelText="取消"
        onOk={applyImage}
        onCancel={() => {
          setAddImageOpen(false)
          pendingAddPointRef.current = null
        }}
        destroyOnHidden
      >
        <Space orientation="vertical" className="w-full" size={8}>
          <div className="canvas-dialog-intro"><span className="canvas-dialog-symbol is-image"><ImagePlus size={22} /></span><p>引用已有图片，或先创建占位节点，稍后从作品库替换素材。</p></div>
          <label className="canvas-inspector-field-label" htmlFor="canvas-image-url">图片地址 <span className="canvas-field-optional">选填</span></label>
          <Input
            autoFocus
            id="canvas-image-url"
            name="canvas-image-url"
            status={imageUrlInvalid ? "error" : undefined}
            aria-invalid={imageUrlInvalid}
            aria-describedby="canvas-image-url-hint"
            value={imageUrl}
            placeholder="粘贴图片地址，例如 https://… 或 /api/…"
            onChange={(event) => setImageUrl(event.target.value)}
            onPressEnter={applyImage}
          />
          <p id="canvas-image-url-hint" className={`canvas-dialog-hint${imageUrlInvalid ? " is-error" : ""}`}>{imageUrlInvalid ? "地址格式不正确，请使用 http(s)、站内路径或 data:image 图片地址。" : "支持 http(s)、站内路径和 data:image 地址。"}</p>
        </Space>
      </Modal>

      <Drawer
        className="canvas-asset-panel"
        rootClassName="canvas-asset-drawer"
        title={assetGeneratorId ? "选择生成参考图" : assetTargetNodeId ? `替换${assetKind === "video" ? "视频" : "图片"}素材` : "从作品库插入素材"}
        placement="right"
        size={560}
        mask={false}
        open={assetOpen}
        onClose={closeAssetLibrary}
        footer={<Button type="primary" onClick={closeAssetLibrary}>完成</Button>}
        destroyOnHidden
        styles={{ root: { top: 76 }, body: { padding: "16px 20px 24px" }, footer: { padding: "12px 20px" } }}
      >
        <div className="canvas-asset-toolbar">
          <div className="canvas-asset-toolbar-row">
            {assetGeneratorId ? <Tag>按选择顺序添加参考图</Tag> : assetTargetNodeId ? (
              <Tag className="canvas-asset-target">
                替换：{assetTargetNode?.data.label || "选中节点"}
              </Tag>
            ) : (
              <Segmented
                value={assetKind}
                onChange={(value) => setAssetKind(value as CanvasMediaKind)}
                options={[
                  { label: `图片 ${libraryCounts.image}`, value: "image" },
                  { label: `视频 ${libraryCounts.video}`, value: "video" },
                ]}
              />
            )}
            <Input
              allowClear
              className="canvas-asset-search"
              value={assetSearch}
              onChange={(event) => setAssetSearch(event.target.value)}
              maxLength={100}
              placeholder="搜索任务标题、提示词或素材名"
              prefix={<Search size={15} />}
              aria-label="搜索作品库"
            />
          </div>
          <span className="canvas-asset-hint">
            {assetGeneratorId ? "选择图片将创建素材节点，并连接为当前生成节点的参考图；替换不会修改原素材。" : assetTargetNodeId
              ? "点击素材会替换当前节点的地址与来源，保留已有标签。"
              : "点击素材插入画布中心，或直接拖到画布上的目标位置；已交付到本机或已过期的资源不可用。"}
          </span>
        </div>
        {libraryQuery.isLoading ? (
          <div className="canvas-asset-loading"><Spin /><span>正在加载作品库…</span></div>
        ) : libraryQuery.isError && !libraryItems.length ? (
          <Empty description={errorText(libraryQuery.error)}>
            <Button
              icon={<RefreshCw size={15} />}
              onClick={() => { libraryQuery.refetch().catch(() => undefined) }}
            >
              重试
            </Button>
          </Empty>
        ) : !libraryItems.length ? (
          <Empty description={librarySearch
            ? `没有找到与「${librarySearch}」匹配的${assetKind === "image" ? "图片" : "视频"}`
            : `作品库里还没有可用${assetKind === "image" ? "图片" : "视频"}`}
          >
            {librarySearch ? (
              <Button onClick={() => { setAssetSearch(""); setLibrarySearch("") }}>清除搜索</Button>
            ) : null}
          </Empty>
        ) : (
          <>
            <div className="canvas-asset-grid">
              {libraryItems.map((item) => {
                const url = libraryItemUrl(item)
                const title = item.job_title || item.label || item.path
                return (
                  <button
                    type="button"
                    key={canvasLibraryItemKey(item)}
                    className="canvas-asset-card"
                    draggable={!assetTargetNodeId && !assetGeneratorId && Boolean(url)}
                    title={assetGeneratorId ? "选择为生成参考图" : assetTargetNodeId ? "点击替换当前节点素材" : "点击插入画布中心，或拖拽到画布目标位置"}
                    onClick={() => insertLibraryItem(item)}
                    onDragStart={(event) => startAssetDrag(item, event)}
                    onDragEnd={endAssetDrag}
                  >
                    <span className="canvas-asset-thumb">
                      {item.kind === "video" ? (
                        <video src={url} muted playsInline preload="metadata" aria-hidden="true" draggable={false} />
                      ) : (
                        <img src={url} alt={item.label || "作品库图片"} loading="lazy" draggable={false} />
                      )}
                      <Tag variant="filled">{item.kind === "video" ? "视频" : "图片"}</Tag>
                    </span>
                    <strong title={title}>{title}</strong>
                    {item.created_at ? (
                      <small>{item.job_title && item.label ? `${item.label} · ` : ""}{formatCanvasTime(item.created_at)}</small>
                    ) : null}
                  </button>
                )
              })}
            </div>
            <div className="canvas-asset-pager">
              <span>已加载 {libraryItems.length} / {libraryTotal}</span>
              {libraryQuery.hasNextPage ? (
                <Button
                  size="small"
                  loading={libraryQuery.isFetchingNextPage}
                  onClick={() => { libraryQuery.fetchNextPage().catch(() => undefined) }}
                >
                  加载更多
                </Button>
              ) : null}
            </div>
            {libraryQuery.isError ? (
              <p className="canvas-dialog-hint is-error">加载更多素材失败，请稍后重试。</p>
            ) : null}
          </>
        )}
      </Drawer>

      <Modal
        className="canvas-dialog canvas-media-dialog"
        title={preview?.label || (preview?.kind === "video" ? "视频预览" : "图片预览")}
        open={Boolean(preview)}
        footer={preview ? <Space size={6}>
          {preview.kind === "image" ? <>
            <Button aria-label="缩小预览" icon={<Minus size={15} />} disabled={previewZoom <= 0.25} onClick={() => setPreviewZoom((value) => Math.max(0.25, value - 0.25))} />
            <Button aria-label="适配图片" onClick={() => setPreviewZoom(1)}>{Math.round(previewZoom * 100)}%</Button>
            <Button aria-label="放大预览图片" icon={<Plus size={15} />} disabled={previewZoom >= 3} onClick={() => setPreviewZoom((value) => Math.min(3, value + 0.25))} />
          </> : null}
          <Button icon={<Download size={14} />} href={preview.url} target="_blank" rel="noopener noreferrer">下载素材</Button>
        </Space> : null}
        width={preview?.kind === "video" ? 960 : 920}
        onCancel={() => setPreview(null)}
        destroyOnHidden
      >
        {preview ? (
          preview.kind === "video" ? (
            <video className="canvas-preview-media" src={preview.url} poster={preview.poster} controls autoPlay playsInline />
          ) : (
            <div className="canvas-image-preview-viewport"><img className="canvas-preview-media" src={preview.url} alt={preview.label || "画布图片预览"} style={{ zoom: previewZoom }} /></div>
          )
        ) : null}
      </Modal>

      <Modal
        className="canvas-dialog"
        width={480}
        title="导入并替换当前画布？"
        open={Boolean(pendingImport)}
        okText="导入并替换"
        cancelText="取消"
        onOk={() => {
          const current = pendingImport
          setPendingImport(null)
          current?.replace()
        }}
        onCancel={() => setPendingImport(null)}
        destroyOnHidden
      >
        {pendingImport
          ? `将用 ${pendingImport.nodeCount} 个节点、${pendingImport.edgeCount} 条连线替换当前画布内容，导入后仍可撤销。`
          : null}
      </Modal>

      <CanvasExportDialog
        open={exportOpen}
        title={title}
        nodes={nodes}
        edges={edges}
        selectedNodeIds={selectedNodeIds}
        onClose={() => setExportOpen(false)}
      />
    </div>
  )
}
