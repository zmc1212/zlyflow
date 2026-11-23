import {
  canvasPromptEligible, canvasReferenceKind, canvasReferenceUrl, canvasWorkflowReferenceKinds, pickCanvasGenerationMode,
  type CanvasReferenceKind, type CanvasWorkflowMode,
} from "./canvas-generation"
import { buildEdgeId, type CanvasEdge, type CanvasNode } from "./canvas-model"

type CanvasConnectKind = CanvasReferenceKind | "text"

export const CANVAS_CONNECT_LABELS: Record<CanvasConnectKind, string> = {
  text: "文字",
  image: "图片",
  video: "视频",
  audio: "音频",
}

export type CanvasConnectTarget = { kind: CanvasConnectKind; mode?: CanvasWorkflowMode }

const canvasNodeInputs: Record<"text" | "audio", readonly CanvasConnectKind[]> = {
  text: ["text", "video", "audio"],
  audio: ["text", "audio"],
}

function canvasOutputKind(node: CanvasNode): CanvasConnectKind | null {
  return canvasPromptEligible(node) ? "text" : canvasReferenceKind(node)
}

export function canvasAcceptsNodeInput(source: CanvasNode, targetKind: keyof typeof canvasNodeInputs): boolean {
  const kind = canvasOutputKind(source)
  return kind !== null && canvasNodeInputs[targetKind].includes(kind)
}

export function canvasConnectTargets(source: CanvasNode | undefined, modes: CanvasWorkflowMode[]): CanvasConnectTarget[] {
  if (!source) return []
  const outputKind = canvasOutputKind(source)
  if (!outputKind) return []
  const kind = outputKind === "text" ? null : outputKind
  if (source.type === "image" && !source.data.pendingGeneratorId && !canvasReferenceUrl(source)) return []
  const compatible = modes.filter((mode) => {
    if (mode.available === false) return false
    const minimum = mode.min_references ?? 0
    if (!kind) return minimum === 0
    if (!canvasWorkflowReferenceKinds(mode).includes(kind)) return false
    return kind !== "image" || canvasWorkflowReferenceKinds(mode, Math.max(1, minimum)).every((slot) => slot === "image")
  })
  const referenceCount = kind ? 1 : 0
  const targets: CanvasConnectTarget[] = (["image", "video"] as const).flatMap((targetKind) => {
    const candidates = compatible.filter((mode) => mode.media_type === targetKind)
    const sourceMode = candidates.find((mode) => mode.id === source.data.workflowId
      && (mode.min_references ?? 0) <= referenceCount
      && (!kind || canvasWorkflowReferenceKinds(mode, referenceCount).includes(kind)))
    const matching = kind
      ? candidates.filter((mode) => canvasWorkflowReferenceKinds(mode, referenceCount).includes(kind))
      : candidates
    const mode = sourceMode ?? pickCanvasGenerationMode(matching.length ? matching : candidates, referenceCount)
    return mode ? [{ kind: targetKind, mode }] : []
  })
  if (canvasNodeInputs.text.includes(outputKind)) targets.unshift({ kind: "text" })
  if (outputKind === "audio") targets.push({ kind: "audio" })
  return targets
}

export function canvasCanAddReference(mode: CanvasWorkflowMode, kind: CanvasReferenceKind, references: CanvasNode[]): boolean {
  const slots = canvasWorkflowReferenceKinds(mode)
  if (references.length >= slots.length) return false
  return references.filter((node) => canvasReferenceKind(node) === kind).length < slots.filter((slot) => slot === kind).length
}

export function canvasConnectInputs(
  target: CanvasNode | undefined,
  modes: CanvasWorkflowMode[],
  references: CanvasNode[],
): CanvasConnectTarget[] {
  if (target?.type === "text" || target?.type === "audio") {
    return canvasNodeInputs[target.type].map((kind) => ({ kind }))
  }
  if (target?.type !== "generator") return []
  const mode = modes.find((item) => item.id === target.data.workflowId && item.available !== false)
  const targets: CanvasConnectTarget[] = [{ kind: "text" }]
  for (const kind of ["image", "video", "audio"] as const) {
    if (mode && canvasCanAddReference(mode, kind, references)) targets.push({ kind })
  }
  return targets
}

export function canvasConnectEdge(sourceId: string, targetId: string, sourceHandle = "out", targetHandle = "in"): CanvasEdge {
  return {
    id: buildEdgeId(sourceId, targetId, sourceHandle, targetHandle),
    source: sourceId,
    target: targetId,
    sourceHandle,
    targetHandle,
    type: "smoothstep",
  }
}

// Old drafts retain their edge IDs and serialized handle names. Only React Flow needs the visible handle.
export function canvasVisibleTargetHandle(edge: CanvasEdge): CanvasEdge["targetHandle"] {
  return edge.targetHandle === "prompt" ? "in" : edge.targetHandle
}

export function canvasConnectMenuPosition(
  point: { x: number; y: number },
  stage: { width: number; height: number },
  targetCount: number,
): { x: number; y: number } {
  const maxX = Math.max(8, stage.width - 232 - 8)
  const maxY = Math.max(8, stage.height - (48 + targetCount * 42) - 8)
  return {
    x: Math.round(Math.max(8, Math.min(point.x, maxX))),
    y: Math.round(Math.max(8, Math.min(point.y, maxY))),
  }
}
