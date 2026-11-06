import { isUniversalAssetNodeKind, type UniversalAssetNodeKind } from "../director2/asset-canvas-creative"
import type { Edge, XYPosition } from "@xyflow/react"
import type { CanvasViewport } from "./canvas-model"
import type { AssetCanvasNode, AssetCanvasLayout } from "../director2/asset-canvas-model"

/** 资产画布草稿 content 的 schema 版本（与无限画布 CanvasDraft 分开演进）。 */
export const ASSET_CANVAS_SCHEMA_VERSION = 2

const MAX_POSITION = 100_000
const MAX_DRAFT_NODES = 3_000
const MAX_DRAFT_EDGES = 6_000

export type AssetCanvasDraftNode = {
  id: string
  kind: "asset" | UniversalAssetNodeKind
  position: XYPosition
  parentId?: string | null
  /** 资产投影节点只存 {assetId,key} 引用，不复制媒体；canvas 侧节点存小体量 data。 */
  data: Record<string, unknown>
}

export type AssetCanvasDraftEdge = {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

export type AssetCanvasDraft = {
  schemaVersion: number
  nodes: AssetCanvasDraftNode[]
  edges: AssetCanvasDraftEdge[]
  viewport: CanvasViewport | null
}

export type AssetCanvasGraph = { nodes: AssetCanvasNode[]; edges: Edge[] }

/** 合并后参与渲染的画布侧节点（generator/视频），保留稳定 id 寻址与自由 data。 */
export type MergedCanvasNode = {
  id: string
  type: string
  position: XYPosition
  data: Record<string, unknown>
  parentId?: string | null
  selected?: boolean
  style?: { width: number }
}

export type MergedNode = AssetCanvasNode | MergedCanvasNode

export const isFinitePosition = (value: unknown): value is XYPosition => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const { x, y } = value as XYPosition
  return Number.isFinite(x) && Number.isFinite(y) && Math.abs(x) <= MAX_POSITION && Math.abs(y) <= MAX_POSITION
}

export const isFiniteViewport = (value: unknown): value is CanvasViewport => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const { x, y, zoom } = value as CanvasViewport
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(zoom) && zoom > 0
}

function emptyDraft(): AssetCanvasDraft {
  return { schemaVersion: ASSET_CANVAS_SCHEMA_VERSION, nodes: [], edges: [], viewport: null }
}

function readPosition(value: unknown): XYPosition | null {
  if (!isFinitePosition(value)) return null
  const { x, y } = value as XYPosition
  return { x, y }
}

/**
 * 把旧版散落在 asset.extra.creation_canvas 的布局碎片合成为初始草稿（一次性迁移）。
 * 以投影图的节点集合为准（positions 已经 buildAssetCanvas 读过旧布局），草稿为空时才有意义。
 */
export function migrateLegacyLayout(graph: AssetCanvasGraph, legacyLayouts: AssetCanvasLayout[] = []): AssetCanvasDraft {
  const hasLegacy = legacyLayouts.some(layout => Object.keys(layout.positions || {}).length || layout.links?.length)
  if (!hasLegacy) return emptyDraft()
  const nodes: AssetCanvasDraftNode[] = graph.nodes.map(node => ({
    id: node.id,
    kind: "asset" as const,
    position: { ...node.position },
    ...(node.parentId ? { parentId: node.parentId } : {}),
    data: {
      origin: "asset",
      assetId: node.data.asset?.id ?? "",
      key: node.data.key,
      ...(node.data.target ? { target: node.data.target } : {}),
    },
  })).filter(node => node.data.assetId)
  return { schemaVersion: ASSET_CANVAS_SCHEMA_VERSION, nodes, edges: [], viewport: null }
}

/** 解析服务端草稿 content；任何异常都退化为空草稿，绝不抛错阻塞画布。 */
export function parseAssetCanvasDraft(content: string): AssetCanvasDraft {
  if (!content) return emptyDraft()
  try {
    const payload = JSON.parse(content) as Partial<AssetCanvasDraft> | null
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return emptyDraft()
    const rawNodes = Array.isArray(payload.nodes) ? payload.nodes : []
    const nodes: AssetCanvasDraftNode[] = []
    const seen = new Set<string>()
    for (const raw of rawNodes) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue
      const node = raw as Partial<AssetCanvasDraftNode>
      if (typeof node.id !== "string" || !node.id || seen.has(node.id)) continue
      const kind = isUniversalAssetNodeKind(node.kind) ? node.kind : node.kind === "asset" ? "asset" : null
      if (!kind) continue
      const position = readPosition(node.position)
      if (!position) continue
      const data = node.data && typeof node.data === "object" && !Array.isArray(node.data) ? node.data as Record<string, unknown> : {}
      if (kind === "asset" && (typeof data.assetId !== "string" || !data.assetId || typeof data.key !== "string" || !data.key)) continue
      seen.add(node.id)
      nodes.push({
        id: node.id,
        kind,
        position,
        ...(typeof node.parentId === "string" && node.parentId ? { parentId: node.parentId } : {}),
        data,
      })
      if (nodes.length >= MAX_DRAFT_NODES) break
    }
    const nodeIds = new Set(nodes.map(node => node.id))
    const rawEdges = Array.isArray(payload.edges) ? payload.edges : []
    const edges: AssetCanvasDraftEdge[] = []
    const edgeSeen = new Set<string>()
    for (const raw of rawEdges) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue
      const edge = raw as Partial<AssetCanvasDraftEdge>
      if (typeof edge.source !== "string" || typeof edge.target !== "string") continue
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target) || edge.source === edge.target) continue
      const id = typeof edge.id === "string" && edge.id ? edge.id : `ae:${edge.source}->${edge.target}`
      if (edgeSeen.has(id)) continue
      edgeSeen.add(id)
      edges.push({ id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle ?? null, targetHandle: edge.targetHandle ?? null })
      if (edges.length >= MAX_DRAFT_EDGES) break
    }
    return {
      schemaVersion: typeof payload.schemaVersion === "number" ? payload.schemaVersion : ASSET_CANVAS_SCHEMA_VERSION,
      nodes,
      edges,
      viewport: isFiniteViewport(payload.viewport) ? payload.viewport : null,
    }
  } catch {
    return emptyDraft()
  }
}

/**
 * 投影图与草稿合并：
 * - 资产投影节点：data 恒取投影真相（媒体在资产表），位置优先级 草稿 > 旧 extra（已含在投影里）> 默认；
 * - 草稿里已消失的资产节点（造型/资产删除）自动剔除；
 * - generator/视频结果节点只存在于草稿侧，原样带入渲染；
 * - 悬空的用户边剪除。
 */
export function mergeProjection(graph: AssetCanvasGraph, draft: AssetCanvasDraft): {
  nodes: MergedNode[]
  edges: Edge[]
  canvasNodeIds: string[]
} {
  const draftById = new Map(draft.nodes.map(node => [node.id, node]))
  const graphIds = new Set(graph.nodes.map(node => node.id))
  const nodes: MergedNode[] = graph.nodes.map(node => {
    const stored = draftById.get(node.id)
    if (!stored || stored.kind !== "asset") return node
    return { ...node, ...(stored.parentId ? { parentId: stored.parentId } : {}), position: stored.position }
  })
  for (const stored of draft.nodes) {
    if (stored.kind === "asset" || graphIds.has(stored.id)) continue
    nodes.push({
      id: stored.id,
      type: stored.kind,
      position: stored.position,
      ...(stored.parentId ? { parentId: stored.parentId } : {}),
      data: { ...stored.data, origin: "canvas", canvasKind: stored.kind },
      style: { width: stored.kind === "text" ? 320 : stored.kind === "image" ? 360 : 380 },
    })
  }
  const finalIds = new Set(nodes.map((node: MergedNode) => node.id))
  const edges: Edge[] = [...graph.edges]
  const edgeIds = new Set(edges.map(edge => edge.id))
  for (const edge of draft.edges) {
    if (!finalIds.has(edge.source) || !finalIds.has(edge.target) || edgeIds.has(edge.id)) continue
    edgeIds.add(edge.id)
    edges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? undefined,
      targetHandle: edge.targetHandle ?? undefined,
      type: "smoothstep",
    })
  }
  const canvasNodeIds = nodes
    .filter((node: MergedNode) => (node.data as { origin?: string } | undefined)?.origin === "canvas")
    .map((node: MergedNode) => node.id)
  return { nodes, edges, canvasNodeIds }
}

/**
 * 序列化为待保存 content：投影内部边（每次由 buildAssetCanvas 重算的）不落盘，
 * 只保留用户连线（涉及 canvas 侧节点的边）；资产节点 data 收缩为引用。
 */
export function serializeAssetCanvasDraft(
  nodes: Array<{ id: string; type?: string | null; position: XYPosition; parentId?: string | null; data?: Record<string, unknown> }>,
  edges: Edge[],
  viewport: CanvasViewport | null,
): AssetCanvasDraft {
  const draftNodes: AssetCanvasDraftNode[] = []
  for (const node of nodes) {
    const data = (node.data || {}) as Record<string, unknown>
    if (data.origin === "canvas") {
      const kind = isUniversalAssetNodeKind(data.canvasKind) ? data.canvasKind : null
      if (!kind) continue
      const rest: Record<string, unknown> = { ...data }
      delete rest.origin
      delete rest.canvasKind
      draftNodes.push({
        id: node.id,
        kind,
        position: { ...node.position },
        ...(node.parentId ? { parentId: node.parentId } : {}),
        data: rest,
      })
      continue
    }
    const assetData = data as { asset?: { id?: string }; key?: string; target?: unknown }
    const assetId = typeof assetData.asset?.id === "string" ? assetData.asset.id : ""
    if (!assetId || typeof assetData.key !== "string") continue
    draftNodes.push({
      id: node.id,
      kind: "asset",
      position: { ...node.position },
      ...(node.parentId ? { parentId: node.parentId } : {}),
      data: {
        origin: "asset",
        assetId,
        key: assetData.key,
        ...(assetData.target ? { target: assetData.target } : {}),
      },
    })
  }
  const nodeIds = new Set(draftNodes.map(node => node.id))
  const canvasIds = new Set(draftNodes.filter(node => node.kind !== "asset").map(node => node.id))
  const draftEdges: AssetCanvasDraftEdge[] = edges
    .filter(edge => (
      nodeIds.has(edge.source) && nodeIds.has(edge.target)
      // 投影边标记 deletable=false 并重算；其余创作引用（含资产到资产）统一持久化。
      && (canvasIds.has(edge.source) || canvasIds.has(edge.target) || edge.deletable !== false)
    ))
    .map(edge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    }))
  return {
    schemaVersion: ASSET_CANVAS_SCHEMA_VERSION,
    nodes: draftNodes.slice(0, MAX_DRAFT_NODES),
    edges: draftEdges.slice(0, MAX_DRAFT_EDGES),
    viewport: isFiniteViewport(viewport) ? viewport : null,
  }
}

export function assetCanvasDraftContent(draft: AssetCanvasDraft): string {
  return JSON.stringify(draft)
}

export function isAssetCanvasDraftEmpty(draft: AssetCanvasDraft): boolean {
  return draft.nodes.length === 0 && draft.edges.length === 0
}
