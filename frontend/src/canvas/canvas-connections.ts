import { generatorResultFromNodeData } from "./canvas-generation"
import { buildEdgeId, type CanvasEdge, type CanvasNode } from "./canvas-model"

export type CanvasConnectTargetKind = "generator" | "image" | "video"

export type CanvasConnectTarget = {
  key: string
  kind: CanvasConnectTargetKind
  label: string
  description: string
  targetHandle: "prompt" | "in"
}

export function canvasGeneratorOutputKind(source: CanvasNode): "image" | "video" | null {
  return generatorResultFromNodeData(source.data)?.kind ?? source.data.resultKind ?? null
}

export function canvasConnectTargets(source: CanvasNode | null | undefined): CanvasConnectTarget[] {
  if (!source) return []
  if (source.type === "text") {
    return [{
      key: "generator",
      kind: "generator",
      label: "生成节点",
      description: "以这段文字作为提示词",
      targetHandle: "prompt",
    }]
  }
  if (source.type === "image") {
    return [{
      key: "generator",
      kind: "generator",
      label: "生成节点",
      description: "以这张图片作为参考图",
      targetHandle: "in",
    }]
  }
  if (source.type !== "generator") return []
  const result = generatorResultFromNodeData(source.data)
  const outputKind = canvasGeneratorOutputKind(source)
  if (!outputKind) return []
  if (outputKind === "video") {
    return [{
      key: "video",
      kind: "video",
      label: "视频节点",
      description: result ? "把当前视频结果加入画布" : "创建后自动接收生成结果",
      targetHandle: "in",
    }]
  }
  return [
    {
      key: "generator",
      kind: "generator",
      label: "生成节点",
      description: result ? "继承提示词并引用当前结果" : "继承提示词，生成后自动引用结果",
      targetHandle: "in",
    },
    {
      key: "image",
      kind: "image",
      label: "图片节点",
      description: result ? "把当前图片结果加入画布" : "创建后自动接收生成结果",
      targetHandle: "in",
    },
  ]
}

export function canvasConnectEdge(
  sourceId: string,
  targetId: string,
  targetHandle: CanvasConnectTarget["targetHandle"],
  sourceHandle = "out",
): CanvasEdge {
  return {
    id: buildEdgeId(sourceId, targetId, sourceHandle, targetHandle),
    source: sourceId,
    target: targetId,
    sourceHandle,
    targetHandle,
    type: "smoothstep",
  }
}

export function canvasConnectMenuPosition(
  point: { x: number; y: number },
  stage: { width: number; height: number },
  menu: { width: number; height: number } = { width: 252, height: 196 },
): { x: number; y: number } {
  const maxX = Math.max(8, stage.width - menu.width - 8)
  const maxY = Math.max(8, stage.height - menu.height - 8)
  return {
    x: Math.round(Math.max(8, Math.min(point.x, maxX))),
    y: Math.round(Math.max(8, Math.min(point.y, maxY))),
  }
}
