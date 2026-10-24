import type { Edge, Node } from "@xyflow/react"
import { normalizeCanvasCover } from "./canvas-cover"

export const CANVAS_SCHEMA_VERSION = 2
export const LEGACY_CANVAS_SCHEMA_VERSION = 1
export const UNKNOWN_NODE_TYPE = "unknown"
export const CANVAS_NODE_TYPES = ["text", "image", "video", "artboard", "generator"] as const
export type CanvasNodeType = (typeof CANVAS_NODE_TYPES)[number]

const knownNodeTypes = new Set<string>(CANVAS_NODE_TYPES)

export type CanvasMediaKind = "image" | "video"

export type CanvasBranchDirection = "right" | "down"

export type CanvasResultVersion = {
  url: string
  path?: string | null
  kind: CanvasMediaKind
  label?: string
  jobId?: string | null
  createdAt?: number
}

export type CanvasRunSnapshot = {
  jobId: string
  workflowId: string
  workflowName: string
  prompt: string
  optionValues: Record<string, string | number | boolean>
  parameterSummary: string[]
  referenceCount: number
  mediaKind: CanvasMediaKind
  submittedAt: number
}

export type CanvasNodeData = {
  label?: string
  text?: string
  url?: string
  caption?: string
  mediaKind?: CanvasMediaKind
  /** 视频节点自动截取的首帧，压缩为 JPEG/WebP data URL。 */
  cover?: string
  /** 封面来源地址；与 url 不一致时视为旧封面。 */
  coverSource?: string
  /** 封面取帧位置（秒）。 */
  coverTime?: number
  assetPath?: string
  sourceJobId?: string | null
  workflowId?: string
  prompt?: string
  optionValues?: Record<string, string | number | boolean>
  jobId?: string | null
  jobStatus?: string | null
  jobError?: string | null
  resultUrl?: string | null
  resultKind?: CanvasMediaKind
  resultPath?: string | null
  resultHistory?: CanvasResultVersion[]
  resultIndex?: number
  branchDirection?: CanvasBranchDirection
  /** 最近一次提交的完整运行快照，编辑参数不会回写历史。 */
  lastRun?: CanvasRunSnapshot
  /** 按任务号保存的最近运行快照，用于切换历史结果版本时追溯。 */
  runHistory?: CanvasRunSnapshot[]
  /** 结果节点（图片/视频）对应的生成运行快照。 */
  sourceRun?: CanvasRunSnapshot
  /** 未注册节点类型在本地归一化前的原始 type，保存时还原。 */
  originalType?: string
}

export type CanvasCoverPatch = Pick<CanvasNodeData, "cover" | "coverSource" | "coverTime">

export type CanvasNode = Node<CanvasNodeData>
export type CanvasEdge = Edge
export type CanvasDraft = {
  schemaVersion: number
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  canvasSettings?: Record<string, unknown>
}

export type CanvasSerializeOptions = {
  canvasSettings?: Record<string, unknown>
  schemaVersion?: number
}

export type CanvasLibraryItem = {
  kind: string
  path: string
  label: string
  delivery_status: "pending" | "local" | "cloud" | "expired"
  download_url: string | null
  cloud_url: string | null
  delivered_at?: string | null
  job_id?: string | null
  generation_item_id?: string | null
  output_index?: number | null
  created_at?: string
  job_title?: string | null
}

export type CanvasPreviewItemType = CanvasNodeType | typeof UNKNOWN_NODE_TYPE

export type CanvasPreviewItem = {
  type: CanvasPreviewItemType
  x: number
  y: number
  width: number
  height: number
  url?: string
  cover?: string
}

export type CanvasPreview = {
  x: number
  y: number
  width: number
  height: number
  nodeCount: number
  items: CanvasPreviewItem[]
  links: [number, number][]
}

export type CanvasProject = {
  id: string
  title: string
  created_at: string
  updated_at: string
  tags?: string[]
  is_favorite?: boolean
  deleted_at?: string | null
  preview?: CanvasPreview | null
  draft_version?: number | null
  node_count?: number | null
  draft_updated_at?: string | null
}

export type CanvasProjectDetail = CanvasProject & {
  version: number
  checksum: string
  content: string
  node_count: number
}

export type CanvasVersion = {
  id: string
  version: number
  checksum: string
  node_count: number
  created_by: string
  created_at: string
}

export const EMPTY_CANVAS: CanvasDraft = {
  schemaVersion: CANVAS_SCHEMA_VERSION,
  nodes: [],
  edges: [],
}
export const CANVAS_HISTORY_LIMIT = 50
export const CANVAS_MIN_ZOOM = 0.1
export const CANVAS_MAX_ZOOM = 2

export type CanvasViewport = { x: number; y: number; zoom: number }

function readCanvasViewportValue(raw: unknown): CanvasViewport | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const { x, y, zoom } = raw as Record<string, unknown>
  if (typeof x !== "number" || !Number.isFinite(x)) return null
  if (typeof y !== "number" || !Number.isFinite(y)) return null
  if (typeof zoom !== "number" || !Number.isFinite(zoom)) return null
  if (zoom < CANVAS_MIN_ZOOM || zoom > CANVAS_MAX_ZOOM) return null
  return { x, y, zoom }
}

export function readCanvasViewport(settings?: Record<string, unknown> | null): CanvasViewport | null {
  return readCanvasViewportValue(settings?.viewport)
}

export const CANVAS_CONNECTION_MODES = ["off", "compact", "full"] as const
export type CanvasConnectionMode = (typeof CANVAS_CONNECTION_MODES)[number]
export const CANVAS_GENERATION_DISPLAY_MODES = ["aggregate", "independent"] as const
export type CanvasGenerationDisplayMode = (typeof CANVAS_GENERATION_DISPLAY_MODES)[number]
export const CANVAS_VIEWPOINT_COUNT = 10

export type CanvasSettings = {
  viewport: CanvasViewport | null
  connectionMode: CanvasConnectionMode
  generationDisplayMode: CanvasGenerationDisplayMode
  gridVisible: boolean
  minimapVisible: boolean
  guidesVisible: boolean
  globalPrompt: string
  viewpoints: (CanvasViewport | null)[]
}

export const DEFAULT_CANVAS_SETTINGS: CanvasSettings = {
  viewport: null,
  connectionMode: "full",
  generationDisplayMode: "aggregate",
  gridVisible: true,
  minimapVisible: true,
  guidesVisible: true,
  globalPrompt: "",
  viewpoints: Array.from({ length: CANVAS_VIEWPOINT_COUNT }, () => null),
}

export function readCanvasViewpoints(value: unknown): (CanvasViewport | null)[] {
  const entries = Array.isArray(value) ? value : []
  return Array.from({ length: CANVAS_VIEWPOINT_COUNT }, (_, index) => readCanvasViewportValue(entries[index]))
}

export function readCanvasSettings(settings?: Record<string, unknown> | null): CanvasSettings {
  const raw = settings && typeof settings === "object" ? settings : {}
  const connectionMode = CANVAS_CONNECTION_MODES.includes(raw.connectionMode as CanvasConnectionMode)
    ? raw.connectionMode as CanvasConnectionMode
    : DEFAULT_CANVAS_SETTINGS.connectionMode
  const generationDisplayMode = CANVAS_GENERATION_DISPLAY_MODES.includes(
    raw.generationDisplayMode as CanvasGenerationDisplayMode,
  )
    ? raw.generationDisplayMode as CanvasGenerationDisplayMode
    : DEFAULT_CANVAS_SETTINGS.generationDisplayMode
  return {
    viewport: readCanvasViewport(raw),
    connectionMode,
    generationDisplayMode,
    gridVisible: typeof raw.gridVisible === "boolean" ? raw.gridVisible : DEFAULT_CANVAS_SETTINGS.gridVisible,
    minimapVisible: typeof raw.minimapVisible === "boolean" ? raw.minimapVisible : DEFAULT_CANVAS_SETTINGS.minimapVisible,
    guidesVisible: typeof raw.guidesVisible === "boolean" ? raw.guidesVisible : DEFAULT_CANVAS_SETTINGS.guidesVisible,
    globalPrompt: typeof raw.globalPrompt === "string" ? raw.globalPrompt.slice(0, 2000) : DEFAULT_CANVAS_SETTINGS.globalPrompt,
    viewpoints: readCanvasViewpoints(raw.viewpoints),
  }
}

export function canvasViewportChanged(previous: CanvasViewport | null, next: CanvasViewport): boolean {
  if (!previous) return true
  return Math.abs(previous.x - next.x) > 0.5
    || Math.abs(previous.y - next.y) > 0.5
    || Math.abs(previous.zoom - next.zoom) > 0.001
}

export type CanvasHistory = {
  entries: string[]
  index: number
}

export function createCanvasHistory(initial: string): CanvasHistory {
  return { entries: [initial], index: 0 }
}

export function pushCanvasHistory(
  history: CanvasHistory,
  snapshot: string,
  limit = CANVAS_HISTORY_LIMIT,
): CanvasHistory {
  if (snapshot === history.entries[history.index]) return history
  if (canvasHistoryContent(snapshot) === canvasHistoryContent(history.entries[history.index])) return history
  const entries = history.entries.slice(0, history.index + 1)
  entries.push(snapshot)
  if (entries.length > limit) entries.splice(0, entries.length - limit)
  return { entries, index: entries.length - 1 }
}

function canvasHistoryContent(content: string): string {
  try {
    const draft = JSON.parse(content)
    if (draft?.canvasSettings && typeof draft.canvasSettings === "object") delete draft.canvasSettings.viewport
    if (Array.isArray(draft?.nodes)) {
      for (const node of draft.nodes) {
        if (!node?.data || typeof node.data !== "object") continue
        delete node.data.cover
        delete node.data.coverSource
        delete node.data.coverTime
      }
    }
    return canonicalCanvasJson(draft)
  } catch {
    return content
  }
}

export function undoCanvasHistory(history: CanvasHistory): CanvasHistory {
  return history.index > 0 ? { ...history, index: history.index - 1 } : history
}

export function redoCanvasHistory(history: CanvasHistory): CanvasHistory {
  return history.index < history.entries.length - 1 ? { ...history, index: history.index + 1 } : history
}

export function canvasHistoryState(history: CanvasHistory): { canUndo: boolean; canRedo: boolean } {
  return {
    canUndo: history.index > 0,
    canRedo: history.index < history.entries.length - 1,
  }
}

export function buildEdgeId(
  source: string,
  target: string,
  sourceHandle = "out",
  targetHandle = "in",
) {
  return `cc-edge__${source}|${sourceHandle || "out"}|${target}|${targetHandle || "in"}`
}

export function normalizeEdges(raw: CanvasEdge[]): CanvasEdge[] {
  const seen = new Set<string>()
  const result: CanvasEdge[] = []
  for (const edge of raw) {
    if (!edge || typeof edge.source !== "string" || typeof edge.target !== "string") continue
    const id = edge.id || buildEdgeId(edge.source, edge.target, edge.sourceHandle ?? undefined, edge.targetHandle ?? undefined)
    if (seen.has(id)) continue
    seen.add(id)
    result.push({
      id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
      type: edge.type ?? "smoothstep",
    })
  }
  return result
}

function emptyCanvasDraft(): CanvasDraft {
  return { ...EMPTY_CANVAS, nodes: [], edges: [] }
}

function readSchemaVersion(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : LEGACY_CANVAS_SCHEMA_VERSION
}

function normalizeCanvasNode(node: CanvasNode): CanvasNode {
  const rawType = typeof node.type === "string" && node.type.trim() ? node.type : "default"
  const rawData = node.data
  const data: CanvasNodeData = rawData && typeof rawData === "object" && !Array.isArray(rawData)
    ? { ...rawData }
    : {}
  for (const key of ["label", "text", "url", "caption", "prompt", "workflowId", "originalType"] as const) {
    if (data[key] !== undefined && typeof data[key] !== "string") delete data[key]
  }
  const position = node.position && typeof node.position === "object" ? node.position : { x: 0, y: 0 }
  const normalized: CanvasNode = {
    ...node,
    position: {
      x: typeof position.x === "number" && Number.isFinite(position.x) ? position.x : 0,
      y: typeof position.y === "number" && Number.isFinite(position.y) ? position.y : 0,
    },
    data,
  }
  if (knownNodeTypes.has(rawType)) {
    return { ...normalized, type: rawType }
  }
  return {
    ...normalized,
    type: UNKNOWN_NODE_TYPE,
    data: { ...data, originalType: data.originalType || rawType },
  }
}

export function parseCanvasContent(content: string): CanvasDraft {
  try {
    const payload = JSON.parse(content) as Partial<CanvasDraft> | null
    if (!payload || typeof payload !== "object") return emptyCanvasDraft()
    const nodes = Array.isArray(payload.nodes)
      ? payload.nodes
        .filter((node): node is CanvasNode => Boolean(node) && typeof node === "object" && typeof node.id === "string")
        .map(normalizeCanvasNode)
      : []
    const edges = Array.isArray(payload.edges) ? normalizeEdges(payload.edges) : []
    return {
      schemaVersion: readSchemaVersion(payload.schemaVersion),
      nodes,
      edges,
      canvasSettings: payload.canvasSettings && typeof payload.canvasSettings === "object" ? payload.canvasSettings : undefined,
    }
  } catch {
    return emptyCanvasDraft()
  }
}

export function serializeCanvasDraft(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  options: CanvasSerializeOptions = {},
): string {
  const serializedNodes = nodes.map((node) => {
    const data = node.data ?? {}
    const originalType = typeof data.originalType === "string" && data.originalType.trim()
      ? data.originalType
      : null
    const type = node.type === UNKNOWN_NODE_TYPE ? originalType ?? UNKNOWN_NODE_TYPE : node.type
    const dataWithoutOriginalType = { ...data }
    delete dataWithoutOriginalType.originalType
    return {
      id: node.id,
      type,
      position: { x: node.position.x, y: node.position.y },
      ...(typeof node.width === "number" ? { width: node.width } : {}),
      ...(typeof node.height === "number" ? { height: node.height } : {}),
      ...(node.parentId ? { parentId: node.parentId } : {}),
      ...(node.extent ? { extent: node.extent } : {}),
      ...(typeof node.expandParent === "boolean" ? { expandParent: node.expandParent } : {}),
      ...(typeof node.draggable === "boolean" ? { draggable: node.draggable } : {}),
      ...(typeof node.zIndex === "number" ? { zIndex: node.zIndex } : {}),
      ...(node.style ? { style: node.style } : {}),
      data: dataWithoutOriginalType,
    }
  })
  return JSON.stringify({
    schemaVersion: options.schemaVersion ?? CANVAS_SCHEMA_VERSION,
    ...(options.canvasSettings ? { canvasSettings: options.canvasSettings } : {}),
    nodes: serializedNodes,
    edges: normalizeEdges(edges),
  })
}

export type CanvasAlignMode = "left" | "centerX" | "right" | "top" | "centerY" | "bottom"
export type CanvasDistributeAxis = "horizontal" | "vertical"
export type CanvasPositionUpdates = Record<string, { x: number; y: number }>

function positiveNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null
}

function nodeDimension(node: CanvasNode, dimension: "width" | "height"): number {
  const style = node.style && typeof node.style === "object" ? node.style[dimension] : undefined
  const direct = dimension === "width" ? node.width : node.height
  return positiveNumber(node.measured?.[dimension]) ?? positiveNumber(style) ?? positiveNumber(direct) ?? 0
}

export const CANVAS_LIBRARY_NODE_SIZES: Record<CanvasMediaKind, { width: number; height: number }> = {
  image: { width: 320, height: 200 },
  video: { width: 360, height: 220 },
}

const CANVAS_FALLBACK_NODE_SIZES: Record<string, { width: number; height: number }> = {
  text: { width: 260, height: 120 },
  image: CANVAS_LIBRARY_NODE_SIZES.image,
  video: CANVAS_LIBRARY_NODE_SIZES.video,
  artboard: { width: 720, height: 480 },
  generator: { width: 356, height: 446 },
  unknown: { width: 260, height: 150 },
}

export function canvasNodeSize(node: CanvasNode): { width: number; height: number } {
  const fallback = CANVAS_FALLBACK_NODE_SIZES[node.type ?? "unknown"] ?? CANVAS_FALLBACK_NODE_SIZES.unknown
  return {
    width: nodeDimension(node, "width") || fallback.width,
    height: nodeDimension(node, "height") || fallback.height,
  }
}

export function canvasNodeTypeLabel(type: string | null | undefined): string {
  if (type === "text") return "文字"
  if (type === "image") return "图片"
  if (type === "video") return "视频"
  if (type === "artboard") return "画板"
  if (type === "generator") return "生成"
  return "未识别"
}

export function canvasBranchPosition(
  node: CanvasNode,
  direction: CanvasBranchDirection,
  index = 0,
  gap = 64,
): { x: number; y: number } {
  const { width, height } = canvasNodeSize(node)
  const slot = Math.max(0, Math.floor(index))
  if (direction === "down") {
    return {
      x: Math.round(node.position.x + slot * (width + 24)),
      y: Math.round(node.position.y + height + gap),
    }
  }
  return {
    x: Math.round(node.position.x + width + gap),
    y: Math.round(node.position.y + slot * (height + 24)),
  }
}

function canvasRectOverlaps(
  position: { x: number; y: number },
  size: { width: number; height: number },
  others: Array<{ x: number; y: number; width: number; height: number }>,
  margin: number,
): boolean {
  return others.some((other) => (
    position.x < other.x + other.width + margin
    && position.x + size.width + margin > other.x
    && position.y < other.y + other.height + margin
    && position.y + size.height + margin > other.y
  ))
}

export function nextCanvasBranchSlot(
  source: CanvasNode,
  direction: CanvasBranchDirection,
  nodes: CanvasNode[],
  margin = 24,
): { x: number; y: number } {
  const size = canvasNodeSize(source)
  const others = nodes
    .filter((node) => node.id !== source.id)
    .map((node) => ({ ...node.position, ...canvasNodeSize(node) }))
  for (let index = 0; index < 200; index += 1) {
    const position = canvasBranchPosition(source, direction, index)
    if (!canvasRectOverlaps(position, size, others, margin)) return position
  }
  return canvasBranchPosition(source, direction, nodes.length)
}

export function findCanvasFreePosition(
  desired: { x: number; y: number },
  size: { width: number; height: number },
  nodes: CanvasNode[],
  margin = 24,
): { x: number; y: number } {
  const others = nodes.map((node) => ({ ...node.position, ...canvasNodeSize(node) }))
  const stepX = Math.round(size.width + margin)
  const stepY = Math.round(size.height + margin)
  const offsets: Array<[number, number]> = [
    [0, 0],
    [1, 0], [0, 1], [-1, 0], [0, -1],
    [1, 1], [-1, 1], [1, -1], [-1, -1],
  ]
  for (let ring = 2; ring < 8; ring += 1) {
    for (let row = -ring; row <= ring; row += 1) {
      for (let col = -ring; col <= ring; col += 1) {
        if (Math.max(Math.abs(row), Math.abs(col)) === ring) offsets.push([col, row])
      }
    }
  }
  for (const [col, row] of offsets) {
    const candidate = {
      x: Math.round(desired.x + col * stepX),
      y: Math.round(desired.y + row * stepY),
    }
    if (!canvasRectOverlaps(candidate, size, others, margin)) return candidate
  }
  return { x: Math.round(desired.x), y: Math.round(desired.y) }
}

function nodeBox(node: CanvasNode) {
  return {
    id: node.id,
    x: node.position.x,
    y: node.position.y,
    width: nodeDimension(node, "width"),
    height: nodeDimension(node, "height"),
  }
}

export function alignCanvasNodes(nodes: CanvasNode[], mode: CanvasAlignMode): CanvasPositionUpdates {
  if (nodes.length < 2) return {}
  const boxes = nodes.map(nodeBox)
  const minX = Math.min(...boxes.map((box) => box.x))
  const maxX = Math.max(...boxes.map((box) => box.x + box.width))
  const minY = Math.min(...boxes.map((box) => box.y))
  const maxY = Math.max(...boxes.map((box) => box.y + box.height))
  const updates: CanvasPositionUpdates = {}
  for (const box of boxes) {
    let { x, y } = box
    if (mode === "left") x = minX
    if (mode === "right") x = maxX - box.width
    if (mode === "centerX") x = (minX + maxX - box.width) / 2
    if (mode === "top") y = minY
    if (mode === "bottom") y = maxY - box.height
    if (mode === "centerY") y = (minY + maxY - box.height) / 2
    updates[box.id] = { x, y }
  }
  return updates
}

export function distributeCanvasNodes(nodes: CanvasNode[], axis: CanvasDistributeAxis): CanvasPositionUpdates {
  if (nodes.length < 3) return {}
  const horizontal = axis === "horizontal"
  const sorted = [...nodes].sort((left, right) => horizontal
    ? (left.position.x - right.position.x) || (left.position.y - right.position.y)
    : (left.position.y - right.position.y) || (left.position.x - right.position.x))
  const boxes = sorted.map(nodeBox)
  const first = boxes[0]
  const last = boxes[boxes.length - 1]
  const start = horizontal ? first.x : first.y
  const end = horizontal ? last.x + last.width : last.y + last.height
  const totalSize = boxes.reduce((sum, box) => sum + (horizontal ? box.width : box.height), 0)
  const gap = (end - start - totalSize) / (boxes.length - 1)
  let cursor = start
  const updates: CanvasPositionUpdates = {}
  for (const box of boxes) {
    updates[box.id] = horizontal
      ? { x: cursor, y: box.y }
      : { x: box.x, y: cursor }
    cursor += (horizontal ? box.width : box.height) + gap
  }
  return updates
}

export function duplicateCanvasSelection(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  selectedNodeIds: Iterable<string>,
  offset = 32,
): { nodes: CanvasNode[]; edges: CanvasEdge[]; nodeIds: string[] } {
  const selected = new Set(selectedNodeIds)
  const originals = nodes.filter((node) => selected.has(node.id))
  if (!originals.length) return { nodes: [], edges: [], nodeIds: [] }
  const idMap = new Map<string, string>()
  const duplicatedNodes = originals.map((node) => {
    const id = nextNodeId(node.type ?? "node")
    idMap.set(node.id, id)
    return {
      ...node,
      id,
      position: { x: node.position.x + offset, y: node.position.y + offset },
      data: { ...node.data },
      selected: false,
    }
  })
  const duplicatedEdges = edges
    .filter((edge) => idMap.has(edge.source) && idMap.has(edge.target))
    .map((edge) => {
      const source = idMap.get(edge.source) as string
      const target = idMap.get(edge.target) as string
      return {
        ...edge,
        id: buildEdgeId(source, target, edge.sourceHandle ?? undefined, edge.targetHandle ?? undefined),
        source,
        target,
        selected: false,
      }
    })
  return { nodes: duplicatedNodes, edges: duplicatedEdges, nodeIds: duplicatedNodes.map((node) => node.id) }
}

export type CanvasClipboard = {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
}

export function copyCanvasClipboard(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  selectedNodeIds: Iterable<string>,
): CanvasClipboard | null {
  const selected = new Set(selectedNodeIds)
  const picked = nodes.filter((node) => selected.has(node.id))
  if (!picked.length) return null
  return {
    nodes: picked.map((node) => ({
      ...node,
      selected: false,
      data: { ...node.data },
    })),
    edges: edges
      .filter((edge) => selected.has(edge.source) && selected.has(edge.target))
      .map((edge) => ({ ...edge, selected: false })),
  }
}

export function pasteCanvasClipboard(clipboard: CanvasClipboard, offset = 32): {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  nodeIds: string[]
} {
  const idMap = new Map<string, string>()
  const nodes = clipboard.nodes.map((node) => {
    const id = nextNodeId(node.type ?? "node")
    idMap.set(node.id, id)
    return {
      ...node,
      id,
      position: { x: node.position.x + offset, y: node.position.y + offset },
      selected: false,
      data: { ...node.data },
    }
  })
  const edges = clipboard.edges
    .filter((edge) => idMap.has(edge.source) && idMap.has(edge.target))
    .map((edge) => {
      const source = idMap.get(edge.source) as string
      const target = idMap.get(edge.target) as string
      return {
        ...edge,
        id: buildEdgeId(source, target, edge.sourceHandle ?? undefined, edge.targetHandle ?? undefined),
        source,
        target,
        selected: false,
      }
    })
  return { nodes, edges, nodeIds: nodes.map((node) => node.id) }
}

export function nextNodeId(prefix = "node"): string {
  const random = Math.random().toString(36).slice(2, 8)
  return `${prefix}_${Date.now().toString(36)}_${random}`
}

export function createTextNode(position: { x: number; y: number }, text = "在这里输入文字"): CanvasNode {
  return {
    id: nextNodeId("text"),
    type: "text",
    position,
    data: { text },
    style: { width: 260 },
  }
}

export function createImageNode(position: { x: number; y: number }, url = "", label = ""): CanvasNode {
  const size = CANVAS_LIBRARY_NODE_SIZES.image
  return {
    id: nextNodeId("image"),
    type: "image",
    position,
    data: { url, label: label || (url ? "参考图" : "图片占位"), mediaKind: "image" },
    style: { ...size },
  }
}

export function createVideoNode(position: { x: number; y: number }, url = "", label = ""): CanvasNode {
  const size = CANVAS_LIBRARY_NODE_SIZES.video
  return {
    id: nextNodeId("video"),
    type: "video",
    position,
    data: { url, label: label || (url ? "参考视频" : "视频占位"), mediaKind: "video" },
    style: { ...size },
  }
}

export function isSafeMediaUrl(value: string, kind: CanvasMediaKind = "image"): boolean {
  const trimmed = value.trim()
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith("/")) return true
  return kind === "image" && /^data:image\//i.test(trimmed)
}

export function libraryItemUrl(item: CanvasLibraryItem): string {
  if (item.cloud_url) return item.cloud_url
  if (item.path) return `/api/media/${encodeURIComponent(item.path)}`
  return item.download_url ?? ""
}

export function isUsableLibraryItem(item: CanvasLibraryItem): boolean {
  if (item.kind !== "image" && item.kind !== "video") return false
  if (item.delivery_status === "local" || item.delivery_status === "expired") return false
  return Boolean(libraryItemUrl(item))
}

export const CANVAS_ASSET_DRAG_TYPE = "application/x-zly-canvas-asset"

type CanvasAssetDragPayload = {
  source: "zly-canvas-library"
  version: 1
  item: CanvasLibraryItem
}

export function encodeCanvasAssetDrag(item: CanvasLibraryItem): string {
  const payload: CanvasAssetDragPayload = { source: "zly-canvas-library", version: 1, item }
  return JSON.stringify(payload)
}

function readDragString(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

export function decodeCanvasAssetDrag(raw: string): CanvasLibraryItem | null {
  try {
    const payload = JSON.parse(raw) as Partial<CanvasAssetDragPayload> | null
    if (!payload || payload.source !== "zly-canvas-library" || payload.version !== 1) return null
    const item = payload.item as Partial<CanvasLibraryItem> | null
    if (!item || typeof item !== "object") return null
    const kind = readDragString(item.kind)
    const path = readDragString(item.path)
    const label = readDragString(item.label)
    const deliveryStatus = readDragString(item.delivery_status)
    if (!kind || path === null || label === null || !deliveryStatus) return null
    if (!(kind === "image" || kind === "video")) return null
    const normalized: CanvasLibraryItem = {
      kind,
      path,
      label,
      delivery_status: deliveryStatus as CanvasLibraryItem["delivery_status"],
      download_url: readDragString(item.download_url),
      cloud_url: readDragString(item.cloud_url),
      delivered_at: readDragString(item.delivered_at),
      job_id: readDragString(item.job_id),
      generation_item_id: readDragString(item.generation_item_id),
      output_index: typeof item.output_index === "number" ? item.output_index : null,
      created_at: readDragString(item.created_at) ?? undefined,
    }
    if (!isUsableLibraryItem(normalized)) return null
    return isSafeMediaUrl(libraryItemUrl(normalized), kind) ? normalized : null
  } catch {
    return null
  }
}

export function createLibraryNode(
  item: CanvasLibraryItem,
  position: { x: number; y: number },
  options: { center?: boolean } = {},
): CanvasNode | null {
  if (!isUsableLibraryItem(item)) return null
  const url = libraryItemUrl(item)
  const kind: CanvasMediaKind = item.kind === "video" ? "video" : "image"
  if (!isSafeMediaUrl(url, kind)) return null
  const size = CANVAS_LIBRARY_NODE_SIZES[kind]
  const topLeft = options.center
    ? { x: Math.round(position.x - size.width / 2), y: Math.round(position.y - size.height / 2) }
    : position
  const node = kind === "video"
    ? createVideoNode(topLeft, url, item.label)
    : createImageNode(topLeft, url, item.label)
  node.data = { ...node.data, assetPath: item.path, sourceJobId: item.job_id ?? null }
  return node
}

export function createArtboardNode(position: { x: number; y: number }): CanvasNode {
  return {
    id: nextNodeId("artboard"),
    type: "artboard",
    position,
    data: { label: "画板" },
    style: { width: 720, height: 480 },
    zIndex: 0,
  }
}

export function createGeneratorNode(
  position: { x: number; y: number },
  init: {
    prompt?: string
    workflowId?: string
    optionValues?: Record<string, string | number | boolean>
    mediaKind?: CanvasMediaKind
    branchDirection?: CanvasBranchDirection
  } = {},
): CanvasNode {
  return {
    id: nextNodeId("generator"),
    type: "generator",
    position,
    data: {
      label: "生成",
      prompt: init.prompt ?? "",
      optionValues: init.optionValues ?? {},
      ...(init.workflowId ? { workflowId: init.workflowId } : {}),
      ...(init.mediaKind ? { resultKind: init.mediaKind } : {}),
      ...(init.branchDirection ? { branchDirection: init.branchDirection } : {}),
    },
    style: { width: 356, height: 446 },
  }
}

function previewNumber(value: unknown, minimum: number, maximum: number): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null
  if (value < minimum || value > maximum) return null
  return value
}

function previewUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined
  const url = value.trim()
  if (!url || url.length > 768) return undefined
  return url.startsWith("/") || /^https?:\/\//i.test(url) ? url : undefined
}

export function readCanvasPreview(value: unknown): CanvasPreview | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const payload = value as Record<string, unknown>
  const x = previewNumber(payload.x, -1_000_000, 1_000_000)
  const y = previewNumber(payload.y, -1_000_000, 1_000_000)
  const width = previewNumber(payload.width, 0, 2_000_000)
  const height = previewNumber(payload.height, 0, 2_000_000)
  if (x === null || y === null || width === null || height === null) return null
  if (!Array.isArray(payload.items)) return null
  const items: CanvasPreviewItem[] = []
  for (const rawItem of payload.items.slice(0, 120)) {
    if (!rawItem || typeof rawItem !== "object" || Array.isArray(rawItem)) return null
    const item = rawItem as Record<string, unknown>
    const rawType = item.type
    if (typeof rawType !== "string") return null
    if (rawType !== UNKNOWN_NODE_TYPE && !knownNodeTypes.has(rawType)) return null
    const itemX = previewNumber(item.x, -1_000_000, 1_000_000)
    const itemY = previewNumber(item.y, -1_000_000, 1_000_000)
    const itemWidth = previewNumber(item.width, 1, 20_000)
    const itemHeight = previewNumber(item.height, 1, 20_000)
    if (itemX === null || itemY === null || itemWidth === null || itemHeight === null) return null
    const url = previewUrl(item.url)
    const cover = rawType === "video" ? normalizeCanvasCover(item.cover) : null
    items.push({
      type: rawType as CanvasPreviewItemType,
      x: itemX,
      y: itemY,
      width: itemWidth,
      height: itemHeight,
      ...(url ? { url } : {}),
      ...(cover ? { cover } : {}),
    })
  }
  const links: [number, number][] = []
  if (Array.isArray(payload.links)) {
    for (const rawLink of payload.links.slice(0, 80)) {
      if (!Array.isArray(rawLink) || rawLink.length !== 2) continue
      const [left, right] = rawLink
      if (
        typeof left !== "number" || typeof right !== "number"
        || !Number.isInteger(left) || !Number.isInteger(right)
        || left === right || left < 0 || right < 0
        || left >= items.length || right >= items.length
      ) continue
      links.push([left, right])
    }
  }
  const rawNodeCount = payload.nodeCount
  const nodeCount = typeof rawNodeCount === "number" && Number.isInteger(rawNodeCount) && rawNodeCount >= 0
    ? Math.min(rawNodeCount, 1_000_000)
    : items.length
  return { x, y, width, height, nodeCount, items, links }
}

/** 判断两次草稿之间是否只有自动封面字段变化，用于避免取帧写入撤销栈。 */
export function isCoverOnlyCanvasChange(previous: string, current: string): boolean {
  const left = coverlessCanvasContent(previous)
  const right = coverlessCanvasContent(current)
  return left !== null && right !== null && left === right
}

function coverlessCanvasContent(raw: string): string | null {
  try {
    const payload = JSON.parse(raw) as unknown
    if (!payload || typeof payload !== "object") return null
    const nodes = (payload as { nodes?: unknown }).nodes
    if (Array.isArray(nodes)) {
      for (const node of nodes) {
        if (!node || typeof node !== "object") continue
        const data = (node as { data?: unknown }).data
        if (!data || typeof data !== "object") continue
        for (const key of ["cover", "coverSource", "coverTime"]) {
          delete (data as Record<string, unknown>)[key]
        }
      }
    }
    return canonicalCanvasJson(payload)
  } catch {
    return null
  }
}

function canonicalCanvasJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null"
  if (Array.isArray(value)) return `[${value.map(canonicalCanvasJson).join(",")}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map((key) => (
    `${JSON.stringify(key)}:${canonicalCanvasJson(record[key])}`
  )).join(",")}}`
}

export function formatCanvasTime(value?: string | null): string {
  if (!value) return "尚未保存"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", { hour12: false })
}
