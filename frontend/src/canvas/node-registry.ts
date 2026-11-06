import type { NodeTypes } from "@xyflow/react"
import {
  ArtboardCanvasNode,
  GeneratorCanvasNode,
  ImageCanvasNode,
  TextCanvasNode,
  UnknownCanvasNode,
  VideoCanvasNode,
} from "./CanvasNodes"

/**
 * 画布通用节点注册表（单一来源）。
 *
 * 无限画布（`canvas/CanvasEditor.tsx`）与导演台资产画布
 * （`director2/panes/AssetCreationCanvas.tsx`）都从这里取通用节点，
 * 新增通用节点类型时只在此登记一处，两个入口同时获得。
 */
export const baseNodeTypes: NodeTypes = {
  text: TextCanvasNode,
  image: ImageCanvasNode,
  video: VideoCanvasNode,
  artboard: ArtboardCanvasNode,
  generator: GeneratorCanvasNode,
  unknown: UnknownCanvasNode,
}

/**
 * 组装某个宿主的节点注册表：以通用节点为底，叠加宿主域专属节点。
 * 同名节点以 `domain` 覆盖，便于宿主替换某个通用节点的实现。
 */
export function buildNodeTypes(domain: NodeTypes = {}): NodeTypes {
  return { ...baseNodeTypes, ...domain }
}
