import type { Edge } from "@xyflow/react"
import type { CanvasConnectionMode, CanvasGenerationDisplayMode } from "./canvas-model"

export type CanvasViewModeOption<T extends string> = {
  value: T
  label: string
  description: string
}

export const CANVAS_CONNECTION_MODE_OPTIONS: CanvasViewModeOption<CanvasConnectionMode>[] = [
  {
    value: "off",
    label: "关闭",
    description: "隐藏全部连线与端口，画布最干净，适合专注节点内容；连线数据仍在，切回其他档位即恢复显示。",
  },
  {
    value: "compact",
    label: "精简",
    description: "只显示与当前选中、悬停节点相关的连线，跟随焦点溯源上下游，适合节点较多时理清局部关系。",
  },
  {
    value: "full",
    label: "完全",
    description: "显示画布上的全部连线，完整呈现节点之间的依赖与数据流向，适合总览整个工作流。",
  },
]

export const CANVAS_GENERATION_MODE_OPTIONS: CanvasViewModeOption<CanvasGenerationDisplayMode>[] = [
  {
    value: "independent",
    label: "独立",
    description: "生成后自动插入首个结果为独立素材节点；其它结果可切换版本后插入，便于并排比较与组合。重新生成会另建节点。",
  },
  {
    value: "aggregate",
    label: "聚合",
    description: "多次生成与重新生成都落在同一个节点内，结果以「版本」形式并存，在节点内切换并选定最终版；适合保持画布结构稳定。",
  },
]

export function canvasConnectionModeLabel(mode: CanvasConnectionMode): string {
  return CANVAS_CONNECTION_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode
}

export function canvasGenerationModeLabel(mode: CanvasGenerationDisplayMode): string {
  return CANVAS_GENERATION_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode
}

export type CanvasEdgeFocus = {
  selectedNodeIds: Iterable<string>
  selectedEdgeIds: Iterable<string>
  recentEdgeId?: string | null
  hoveredNodeId?: string | null
}

/** 精简模式保留焦点节点/连线所在的上下游连通链，焦点包括选中、最近创建与悬停。 */
export function compactCanvasEdgeIds(edges: Edge[], focus: CanvasEdgeFocus): Set<string> {
  const keep = new Set(focus.selectedEdgeIds)
  const nodeKeep = new Set(focus.selectedNodeIds)
  if (focus.recentEdgeId) keep.add(focus.recentEdgeId)
  if (focus.hoveredNodeId) nodeKeep.add(focus.hoveredNodeId)
  let changed = true
  while (changed) {
    changed = false
    for (const edge of edges) {
      if (keep.has(edge.id)) {
        if (!nodeKeep.has(edge.source)) {
          nodeKeep.add(edge.source)
          changed = true
        }
        if (!nodeKeep.has(edge.target)) {
          nodeKeep.add(edge.target)
          changed = true
        }
        continue
      }
      if (nodeKeep.has(edge.source)) {
        keep.add(edge.id)
        nodeKeep.add(edge.target)
        changed = true
      }
      if (nodeKeep.has(edge.target)) {
        keep.add(edge.id)
        nodeKeep.add(edge.source)
        changed = true
      }
    }
  }
  return keep
}
