import { canvasReferenceEligible, incomingGeneratorReferenceNodes, type CanvasWorkflowMode } from "./canvas-generation"
import type { CanvasEdge, CanvasNode } from "./canvas-model"

/** Slot shape comes from the selected workflow, not a model-name allowlist. */
export function canvasReferenceSlots(mode: CanvasWorkflowMode | null, references: CanvasNode[]) {
  const maximum = Math.max(0, mode?.max_references ?? 0)
  const fixed = mode?.reference_mode === "keyframes" || mode?.reference_mode === "fixed"
  const count = Math.max(references.length, fixed ? maximum : Math.min(maximum, references.length + 1))
  return Array.from({ length: count }, (_, index) => ({
    index,
    node: references[index] ?? null,
    required: index < (mode?.min_references ?? 0),
    label: mode?.reference_labels?.[index]?.replace(/[（(]\s*(?:可选|必填)\s*[）)]\s*$/, "").trim()
      || (mode?.reference_mode === "keyframes" ? index === 0 ? "首帧" : "尾帧" : `参考图 ${index + 1}`),
  }))
}

/** Reorder the existing edges: their order is the <Picture n> protocol. */
export function reorderCanvasReferenceEdges(
  edges: CanvasEdge[], nodes: CanvasNode[], targetId: string, sourceId: string, direction: -1 | 1,
): CanvasEdge[] {
  const references = incomingGeneratorReferenceNodes(nodes, edges, targetId)
  const index = references.findIndex((node) => node.id === sourceId)
  const next = index + direction
  if (index < 0 || next < 0 || next >= references.length) return edges
  const ordered = references.map((node) => node.id)
  ;[ordered[index], ordered[next]] = [ordered[next], ordered[index]]
  const rank = new Map(ordered.map((id, position) => [id, position]))
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const positions: number[] = []
  const matched = edges.filter((edge, position) => {
    const source = nodeById.get(edge.source)
    if (edge.target !== targetId || !source || !canvasReferenceEligible(source)) return false
    positions.push(position)
    return true
  }).sort((a, b) => (rank.get(a.source) ?? 0) - (rank.get(b.source) ?? 0))
  const result = [...edges]
  positions.forEach((position, index) => { result[position] = matched[index] })
  return result
}

export function canvasMediaTime(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null
  const total = Math.floor(seconds)
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`
}
