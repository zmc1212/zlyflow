import {
  bindCanvasReferenceSlots, CANVAS_REFERENCE_LABELS, canvasReferenceKind, canvasWorkflowReferenceKinds,
  generatorParameterFields, incomingGeneratorReferenceNodes, type CanvasOptionDefinition, type CanvasOptionValue, type CanvasWorkflowMode,
} from "./canvas-generation"
import type { CanvasEdge, CanvasNode } from "./canvas-model"

type ComposerOptionField = [string, CanvasOptionDefinition]

/** Honor the registry's visual groups, visibility and parameter tiers without assuming field names. */
export function canvasComposerParameterLayout(mode: CanvasWorkflowMode | null, values: Record<string, CanvasOptionValue>) {
  const fields = generatorParameterFields(mode, values)
  const visual: { field: ComposerOptionField; companions: ComposerOptionField[] }[] = []
  const available = new Map([...fields.primary, ...fields.advanced])
  const grouped = new Set<string>()
  for (const field of fields.primary) {
    const [name, definition] = field
    if (grouped.has(name) || definition.ui_control !== "visual-settings" || !canvasComposerOptionChoices(definition).length) continue
    grouped.add(name)
    const companions = (definition.ui_companions ?? (definition.ui_companion ? [definition.ui_companion] : [])).flatMap((key): ComposerOptionField[] => {
      const companion = available.get(key)
      if (!companion || grouped.has(key)) return []
      grouped.add(key)
      return [[key, companion]]
    })
    visual.push({ field, companions })
  }
  return {
    primary: fields.primary.filter(([name]) => !grouped.has(name)),
    advanced: fields.advanced.filter(([name]) => !grouped.has(name)),
    visual,
  }
}

/** Small bounded ranges become real choices; unbounded values retain their numeric input. */
export function canvasComposerOptionChoices(definition: CanvasOptionDefinition): { value: string | number; label: string; short_label?: string; hint?: string }[] {
  if (definition.ui_options?.length) return definition.ui_options
  if (definition.enum?.length) return definition.enum.map((value) => ({ value, label: String(value) }))
  const { minimum, maximum } = definition
  const step = definition.step ?? 1
  if ((definition.type !== "integer" && definition.type !== "number")
    || minimum === undefined || maximum === undefined || !Number.isFinite(minimum) || !Number.isFinite(maximum)
    || !Number.isFinite(step) || step <= 0) return []
  const count = Math.floor((maximum - minimum) / step) + 1
  if (count < 1 || count > 12) return []
  return Array.from({ length: count }, (_, index) => {
    const value = Number((minimum + index * step).toPrecision(12))
    return { value, label: String(value) }
  })
}

export function canvasComposerOptionLabel(definition: CanvasOptionDefinition, value: CanvasOptionValue | undefined): string {
  const actual = value ?? definition.default
  if (definition.ui_summary === "value") return `${actual}${definition.unit ?? ""}`
  const choice = canvasComposerOptionChoices(definition).find((item) => String(item.value) === String(actual))
  const label = (choice?.short_label || choice?.label)
    ?? (typeof actual === "boolean" ? actual ? "开启" : "关闭" : String(actual))
  if (definition.ui_control === "visual-settings") return String(actual).match(/\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?/)?.[0] ?? label
  return definition.unit && !label.endsWith(definition.unit) ? `${label}${definition.unit}` : label
}

/** Slot shape comes from the selected workflow, not a model-name allowlist. */
export function canvasReferenceSlots(mode: CanvasWorkflowMode | null, references: CanvasNode[]) {
  const minimum = mode?.min_references ?? 0
  const maximum = Math.max(0, mode?.max_references ?? 0)
  const fixed = mode?.reference_mode === "keyframes" || mode?.reference_mode === "fixed"
  const count = fixed ? maximum : Math.min(maximum, Math.max(minimum, references.length + 1))
  const { slots, unmatched } = mode ? bindCanvasReferenceSlots(mode, references, count) : { slots: [], unmatched: references }
  const requiredKinds = mode ? canvasWorkflowReferenceKinds(mode, minimum) : []
  const declaredCount = mode?.reference_slots?.length ?? 0
  const items = slots.map(({ kind, node }, index) => {
    const requiredIndex = requiredKinds.indexOf(kind)
    const labelIndex = declaredCount > count && index === count - 1 ? declaredCount - 1 : index
    const label = mode?.reference_labels?.[labelIndex]?.replace(/[（(]\s*(?:可选|必填)\s*[）)]\s*$/, "").trim()
      || (mode?.reference_mode === "keyframes" ? index === 0 ? "首帧" : "尾帧" : `${CANVAS_REFERENCE_LABELS[kind]} ${index + 1}`)
    if (requiredIndex >= 0) requiredKinds.splice(requiredIndex, 1)
    return { index, node, kind, required: requiredIndex >= 0, label, unmatched: false }
  })
  for (const node of unmatched) {
    const index = items.length
    const kind = canvasReferenceKind(node) ?? "image"
    items.push({ index, node, kind, required: false, label: CANVAS_REFERENCE_LABELS[kind], unmatched: true })
  }
  return items
}

/** Preserve the order of each media kind when the workflow assigns its slots. */
export function reorderCanvasReferenceEdges(
  edges: CanvasEdge[], nodes: CanvasNode[], targetId: string, sourceId: string, direction: -1 | 1,
): CanvasEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const source = nodeById.get(sourceId)
  const kind = source && canvasReferenceKind(source)
  if (!kind) return edges
  const references = incomingGeneratorReferenceNodes(nodes, edges, targetId).filter((node) => canvasReferenceKind(node) === kind)
  const index = references.findIndex((node) => node.id === sourceId)
  const next = index + direction
  if (index < 0 || next < 0 || next >= references.length) return edges
  const ordered = references.map((node) => node.id)
  ;[ordered[index], ordered[next]] = [ordered[next], ordered[index]]
  const rank = new Map(ordered.map((id, position) => [id, position]))
  const positions: number[] = []
  const matched = edges.filter((edge, position) => {
    const source = nodeById.get(edge.source)
    if (edge.target !== targetId || !source || canvasReferenceKind(source) !== kind) return false
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
