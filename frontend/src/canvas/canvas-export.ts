import { readCanvasCover } from "./canvas-cover"
import { canvasJobStatusLabel, generatorResultFromNodeData } from "./canvas-generation"
import {
  canvasNodeSize,
  isSafeMediaUrl,
  type CanvasEdge,
  type CanvasNode,
  type CanvasNodeType,
  type CanvasMediaKind,
} from "./canvas-model"

export type CanvasExportBackground = "light" | "dark" | "transparent"
export type CanvasExportScope = "all" | "selection"

export type CanvasExportOptions = {
  scope?: CanvasExportScope
  selectedNodeIds?: Iterable<string>
  background?: CanvasExportBackground
  /** 透明背景下的卡片配色，默认跟随背景。 */
  theme?: "light" | "dark"
  scale?: number
  padding?: number
}

export type CanvasExportNode = {
  id: string
  type: CanvasNodeType | "unknown"
  originalType?: string
  x: number
  y: number
  width: number
  height: number
  label: string
  text?: string
  prompt?: string
  caption?: string
  status?: string
  mediaKind?: CanvasMediaKind
  imageCandidates: string[]
}

export type CanvasExportLink = {
  id: string
  source: string
  target: string
}

export type CanvasExportBounds = {
  x: number
  y: number
  width: number
  height: number
}

export type CanvasExportScene = {
  bounds: CanvasExportBounds
  background: string | null
  backgroundMode: CanvasExportBackground
  paletteMode: "light" | "dark"
  /** 实际生效倍率，可能因画布过大被下调。 */
  scale: number
  requestedScale: number
  width: number
  height: number
  nodes: CanvasExportNode[]
  links: CanvasExportLink[]
  nodeCount: number
  edgeCount: number
}

export type CanvasExportPalette = {
  background: string
  surface: string
  raised: string
  border: string
  text: string
  secondary: string
  muted: string
  primary: string
  edge: string
  textTone: string
  imageTone: string
  videoTone: string
  generatorTone: string
  unknownTone: string
  videoSurface: string
}

export const CANVAS_EXPORT_PADDING = 48
export const CANVAS_EXPORT_MAX_EDGE = 8192
export const CANVAS_EXPORT_MAX_PIXELS = 24_000_000
export const CANVAS_EXPORT_MAX_SCALE = 3
export const CANVAS_EXPORT_MIN_SCALE = 0.01
export const CANVAS_EXPORT_PREVIEW_WIDTH = 760
export const CANVAS_EXPORT_PREVIEW_HEIGHT = 520

export const CANVAS_EXPORT_PALETTES: Record<"light" | "dark", CanvasExportPalette> = {
  light: {
    background: "#f8f9fa",
    surface: "#ffffff",
    raised: "#f4f6f8",
    border: "rgba(15, 23, 42, 0.10)",
    text: "#171a1f",
    secondary: "#4b5563",
    muted: "#6b7280",
    primary: "#4554ff",
    edge: "rgba(15, 23, 42, 0.30)",
    textTone: "#7551bd",
    imageTone: "#ad6613",
    videoTone: "#3c70bc",
    generatorTone: "#4554ff",
    unknownTone: "#6b7280",
    videoSurface: "#0b0d10",
  },
  dark: {
    background: "#0f1115",
    surface: "#171a20",
    raised: "#1e2229",
    border: "rgba(255, 255, 255, 0.10)",
    text: "#f3f5f7",
    secondary: "#c0c7d0",
    muted: "#9ba5b1",
    primary: "#6977f5",
    edge: "rgba(255, 255, 255, 0.24)",
    textTone: "#c5a9fa",
    imageTone: "#f4bd72",
    videoTone: "#8db8f7",
    generatorTone: "#6977f5",
    unknownTone: "#9ba5b1",
    videoSurface: "#0b0d10",
  },
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function mediaPathUrl(path: unknown): string {
  const trimmed = textValue(path)
  if (!trimmed) return ""
  return `/api/media/${encodeURIComponent(trimmed)}`
}

function pushSafeCandidate(target: string[], value: unknown) {
  const trimmed = textValue(value)
  if (!trimmed || !isSafeMediaUrl(trimmed, "image") || target.includes(trimmed)) return
  target.push(trimmed)
}

/**
 * 导出优先使用同源 `/api/media/{path}`，避免云端跨域图片污染 canvas；
 * 同源地址失败时渲染器会再尝试原始地址。
 */
function imageCandidatesForNode(node: CanvasNode): string[] {
  const data = node.data ?? {}
  const candidates: string[] = []
  if (node.type === "image") {
    pushSafeCandidate(candidates, mediaPathUrl(data.assetPath))
    pushSafeCandidate(candidates, data.url)
    return candidates
  }
  if (node.type === "generator") {
    const result = generatorResultFromNodeData(data)
    if (!result || result.kind !== "image") return candidates
    pushSafeCandidate(candidates, mediaPathUrl(result.path))
    pushSafeCandidate(candidates, result.url)
  }
  if (node.type === "video") {
    pushSafeCandidate(candidates, readCanvasCover(data))
  }
  return candidates
}

function exportNodeLabel(node: CanvasNode): string {
  const label = textValue(node.data?.label)
  if (label) return label
  if (node.type === "text") return "文字"
  if (node.type === "image") return "图片"
  if (node.type === "video") return "视频"
  if (node.type === "artboard") return "画板"
  if (node.type === "generator") return "画面生成"
  return "未识别节点"
}

/** 与 canvas-generation 的提示词语义一致：按连线顺序合并非空文字节点。 */
function connectedTextPrompt(node: CanvasNode, nodesById: Map<string, CanvasNode>, edges: CanvasEdge[]): string {
  const seen = new Set<string>()
  const parts: string[] = []
  for (const edge of edges) {
    if (edge.target !== node.id) continue
    const source = nodesById.get(edge.source)
    if (!source || source.type !== "text" || seen.has(source.id)) continue
    seen.add(source.id)
    const text = textValue(source.data?.text)
    if (text) parts.push(text)
  }
  return parts.join("\n\n")
}

function generatorPrompt(node: CanvasNode, nodesById: Map<string, CanvasNode>, edges: CanvasEdge[]): string {
  return connectedTextPrompt(node, nodesById, edges) || textValue(node.data?.prompt)
}

function exportNodeOrder(left: CanvasNode, right: CanvasNode, order: Map<string, number>): number {
  const artboardDelta = Number(right.type === "artboard") - Number(left.type === "artboard")
  if (artboardDelta) return artboardDelta
  const zDelta = finiteNumber(left.zIndex) - finiteNumber(right.zIndex)
  if (zDelta) return zDelta
  return (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0)
}

export function canvasExportBackgroundColor(mode: CanvasExportBackground = "light"): string | null {
  if (mode === "transparent") return null
  return CANVAS_EXPORT_PALETTES[mode].background
}

export function canvasExportPalette(mode: CanvasExportBackground = "light"): CanvasExportPalette {
  return mode === "dark" ? CANVAS_EXPORT_PALETTES.dark : CANVAS_EXPORT_PALETTES.light
}

export function fitCanvasExportScale(width: number, height: number, requestedScale = 2): number {
  const safeWidth = Math.max(1, width)
  const safeHeight = Math.max(1, height)
  const requested = clampNumber(requestedScale, CANVAS_EXPORT_MIN_SCALE, CANVAS_EXPORT_MAX_SCALE)
  const edgeScale = CANVAS_EXPORT_MAX_EDGE / Math.max(safeWidth, safeHeight)
  const pixelScale = Math.sqrt(CANVAS_EXPORT_MAX_PIXELS / (safeWidth * safeHeight))
  const fitted = Math.min(requested, edgeScale, pixelScale)
  return Math.max(CANVAS_EXPORT_MIN_SCALE, Math.floor(fitted * 100) / 100)
}

export function canvasExportPreviewScale(bounds: CanvasExportBounds): number {
  const width = Math.max(1, bounds.width)
  const height = Math.max(1, bounds.height)
  return Math.max(
    CANVAS_EXPORT_MIN_SCALE,
    Math.min(1, CANVAS_EXPORT_PREVIEW_WIDTH / width, CANVAS_EXPORT_PREVIEW_HEIGHT / height),
  )
}

export function buildCanvasExportScene(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  options: CanvasExportOptions = {},
): CanvasExportScene | null {
  const selected = options.scope === "selection" ? new Set(options.selectedNodeIds ?? []) : null
  const included = nodes.filter((node) => node.hidden !== true && (!selected || selected.has(node.id)))
  if (!included.length) return null

  const nodesById = new Map(nodes.map((node) => [node.id, node]))
  const padding = Math.max(0, finiteNumber(options.padding ?? CANVAS_EXPORT_PADDING))
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const node of included) {
    const size = canvasNodeSize(node)
    minX = Math.min(minX, node.position.x)
    minY = Math.min(minY, node.position.y)
    maxX = Math.max(maxX, node.position.x + size.width)
    maxY = Math.max(maxY, node.position.y + size.height)
  }

  const bounds: CanvasExportBounds = {
    x: Math.round((minX - padding) * 100) / 100,
    y: Math.round((minY - padding) * 100) / 100,
    width: Math.max(1, Math.round((maxX - minX + padding * 2) * 100) / 100),
    height: Math.max(1, Math.round((maxY - minY + padding * 2) * 100) / 100),
  }

  const order = new Map(included.map((node, index) => [node.id, index]))
  const ordered = [...included].sort((left, right) => exportNodeOrder(left, right, order))
  const exportedNodes: CanvasExportNode[] = ordered.map((node) => {
    const size = canvasNodeSize(node)
    const data = node.data ?? {}
    const exported: CanvasExportNode = {
      id: node.id,
      type: (node.type ?? "unknown") as CanvasNodeType | "unknown",
      x: node.position.x,
      y: node.position.y,
      width: size.width,
      height: size.height,
      label: exportNodeLabel(node),
      imageCandidates: imageCandidatesForNode(node),
    }
    const originalType = textValue(data.originalType)
    if (originalType) exported.originalType = originalType
    if (node.type === "text") {
      const text = typeof data.text === "string" ? data.text : ""
      if (text.trim()) exported.text = text
    }
    if (node.type === "generator") {
      const prompt = generatorPrompt(node, nodesById, edges)
      if (prompt) exported.prompt = prompt
      exported.status = canvasJobStatusLabel(data.jobStatus)
      const result = generatorResultFromNodeData(data)
      if (result) exported.mediaKind = result.kind
    }
    if (node.type === "image" || node.type === "video") {
      exported.mediaKind = node.type === "video" ? "video" : "image"
      const caption = textValue(data.caption)
      if (caption) exported.caption = caption
    }
    if (node.type === "artboard") {
      const caption = textValue(data.caption)
      if (caption) exported.caption = caption
    }
    return exported
  })

  const exportedIds = new Set(exportedNodes.map((node) => node.id))
  const links: CanvasExportLink[] = edges
    .filter((edge) => (
      edge.hidden !== true
      && edge.source !== edge.target
      && exportedIds.has(edge.source)
      && exportedIds.has(edge.target)
    ))
    .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }))

  const backgroundMode = options.background ?? "light"
  const paletteMode = options.theme ?? (backgroundMode === "dark" ? "dark" : "light")
  const requestedScale = clampNumber(finiteNumber(options.scale) || 2, CANVAS_EXPORT_MIN_SCALE, CANVAS_EXPORT_MAX_SCALE)
  const scale = fitCanvasExportScale(bounds.width, bounds.height, requestedScale)
  return {
    bounds,
    background: canvasExportBackgroundColor(backgroundMode),
    backgroundMode,
    paletteMode,
    scale,
    requestedScale,
    width: Math.max(1, Math.round(bounds.width * scale)),
    height: Math.max(1, Math.round(bounds.height * scale)),
    nodes: exportedNodes,
    links,
    nodeCount: exportedNodes.length,
    edgeCount: links.length,
  }
}

export function canvasPngFileName(title: string, date = new Date()): string {
  const safeTitle = title.trim().replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 60) || "canvas"
  const pad = (value: number) => String(value).padStart(2, "0")
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`
  return `${safeTitle}-${stamp}.png`
}
