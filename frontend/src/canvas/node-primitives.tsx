import {
  Handle, NodeToolbar, Position, useNodeConnections, useReactFlow,
} from "@xyflow/react"
import { Button, Dropdown, Tooltip } from "antd"
import { Copy, Download, Plus, Settings, Sparkles, Trash2 } from "lucide-react"
import { createContext, useContext, type ComponentProps } from "react"
import type { CanvasBranchDirection, CanvasCoverPatch, CanvasNode } from "./canvas-model"
import {
  generatorResultFromNodeData,
  type CanvasGeneratorLive,
  type CanvasGeneratorPromptState,
  type CanvasWorkflowMode,
} from "./canvas-generation"

/**
 * 画布节点共享原语（单一来源）。
 *
 * 这里放的是「通用节点」在两个画布入口都要用、且彼此无差别的部分：
 * - 三个节点上下文（动作 / 生成器 / 媒体预览）与它们的类型
 * - `ConnectedHandle`：按上游节点类型着色的端口
 * - `NodeFloatingToolbar`：选中后的节点悬浮工具条
 * - 节点缩放手柄的类名常量
 *
 * 无限画布 `CanvasNodes.tsx` 与导演台资产画布后续都从本文件取用，
 * 避免同一套交互在两处各写一份。
 */

/** 按上游节点类型给端口着色的 Handle。 */
export function ConnectedHandle(props: ComponentProps<typeof Handle>) {
  const connections = useNodeConnections({ handleType: props.type, handleId: props.id ?? undefined })
  const { getNode } = useReactFlow<CanvasNode>()
  const sourceType = props.type === "target" && connections[0] ? getNode(connections[0].source)?.type : null
  const color = sourceType === "generator" ? "var(--studio-primary)" : sourceType === "text" ? "var(--canvas-text-tone)" : sourceType === "video" ? "var(--canvas-video-tone)" : sourceType === "image" ? "var(--canvas-image-tone)" : undefined
  return <Handle {...props} style={{ ...props.style, ...(color ? { color } : {}) }} className={`${props.className ?? ""}${connections.length ? " is-connected" : ""}`} />
}

export type CanvasMediaPreview = {
  url: string
  label?: string
  kind: "image" | "video"
  poster?: string
}

export const CanvasMediaPreviewContext = createContext<(preview: CanvasMediaPreview) => void>(() => undefined)

export type CanvasGeneratorContextValue = {
  modes: CanvasWorkflowMode[]
  modesLoading: boolean
  disconnectInput: (nodeId: string, kind: "text" | "image") => void
  workflowName: (workflowId?: string) => string
  modeFor: (workflowId?: string) => CanvasWorkflowMode | null
  liveFor: (jobId?: string | null) => CanvasGeneratorLive | null
  referenceCountFor: (nodeId: string) => number
  referencesFor: (nodeId: string) => CanvasNode[]
  chooseReference: (nodeId: string, sourceId?: string) => void
  removeReference: (nodeId: string, sourceId: string) => void
  moveReference: (nodeId: string, sourceId: string, direction: -1 | 1) => void
  promptInfoFor: (nodeId: string) => CanvasGeneratorPromptState
  issueFor: (nodeId: string) => string | null
  submit: (nodeId: string) => void
  cancel: (nodeId: string) => void
  refine: (nodeId: string, action: "confirm" | "skip") => void
  insertResult: (nodeId: string, direction: CanvasBranchDirection) => void
  submitting: (nodeId: string) => boolean
}

export const CanvasGeneratorContext = createContext<CanvasGeneratorContextValue>({
  modes: [],
  modesLoading: false,
  disconnectInput: () => undefined,
  workflowName: () => "未选择工作流",
  modeFor: () => null,
  liveFor: () => null,
  referenceCountFor: () => 0,
  referencesFor: () => [],
  chooseReference: () => undefined,
  removeReference: () => undefined,
  moveReference: () => undefined,
  promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
  issueFor: () => null,
  submit: () => undefined,
  cancel: () => undefined,
  refine: () => undefined,
  insertResult: () => undefined,
  submitting: () => false,
})

export type CanvasNodeActions = {
  openProperties: (nodeId: string) => void
  branchGenerate: (nodeId: string, direction: CanvasBranchDirection) => void
  duplicateNode: (nodeId: string) => void
  deleteNode: (nodeId: string) => void
  downloadNode: (nodeId: string) => void
  updateCover: (nodeId: string, patch: CanvasCoverPatch) => void
  chooseMedia: (nodeId: string, kind: "image" | "video") => void
  saveCanvas: () => void
}

export const CanvasNodeActionsContext = createContext<CanvasNodeActions>({
  openProperties: () => undefined,
  branchGenerate: () => undefined,
  duplicateNode: () => undefined,
  deleteNode: () => undefined,
  downloadNode: () => undefined,
  updateCover: () => undefined,
  chooseMedia: () => undefined,
  saveCanvas: () => undefined,
})

export function canvasBranchMenu(onPick: (direction: CanvasBranchDirection) => void) {
  return {
    items: [
      { key: "right", label: "向右生成" },
      { key: "down", label: "向下生成" },
    ],
    onClick: ({ key }: { key: string }) => onPick(key === "down" ? "down" : "right"),
  }
}

/** 选中节点时浮在节点上方的工具条。 */
export function NodeFloatingToolbar({ id, type, data, selected }: {
  id: string
  type: string
  data: CanvasNode["data"]
  selected: boolean
}) {
  const actions = useContext(CanvasNodeActionsContext)
  const generator = useContext(CanvasGeneratorContext)
  const result = generatorResultFromNodeData(data)
  const mediaUrl = type === "image" || type === "video" ? data.url : result?.url
  const canBranch = type === "text" || type === "image" || type === "generator"

  return (
    <NodeToolbar
      isVisible={selected}
      position={Position.Top}
      offset={8}
      className={`canvas-node-toolbar nodrag nopan${type === "generator" ? " is-generator" : ""}`}
    >
      {canBranch ? (
        <Dropdown classNames={{ root: "canvas-popup canvas-branch-menu" }} trigger={["click"]} menu={canvasBranchMenu((direction) => actions.branchGenerate(id, direction))}>
          <Button size="small" type="text" className="canvas-toolbar-branch" icon={<Sparkles size={15} />}>以此生成</Button>
        </Dropdown>
      ) : null}
      {canBranch ? <span className="canvas-toolbar-divider" /> : null}

      {result ? (
        <Tooltip title="把结果插入到右侧">
          <Button
            size="small"
            type="text"
            icon={<Plus size={14} />}
            aria-label="插入生成结果"
            onClick={() => generator.insertResult(id, "right")}
          />
        </Tooltip>
      ) : null}

      <Tooltip title="节点属性">
        <Button
          size="small"
          type="text"
          icon={<Settings size={16} />}
          aria-label="节点属性"
          onClick={() => actions.openProperties(id)}
        />
      </Tooltip>
      <Tooltip title="复制节点 (Ctrl/⌘ D)">
        <Button
          size="small"
          type="text"
          icon={<Copy size={16} />}
          aria-label="复制节点"
          onClick={() => actions.duplicateNode(id)}
        />
      </Tooltip>
      {mediaUrl || type === "generator" ? (
        <Tooltip title={mediaUrl ? "下载素材" : "生成结果后可下载"}>
          <Button
            size="small"
            type="text"
            icon={<Download size={14} />}
            aria-label="下载素材"
            disabled={!mediaUrl}
            onClick={() => actions.downloadNode(id)}
          />
        </Tooltip>
      ) : null}
      <Tooltip title="删除节点 (Delete)">
        <Button
          size="small"
          type="text"
          danger
          icon={<Trash2 size={14} />}
          aria-label="删除节点"
          onClick={() => actions.deleteNode(id)}
        />
      </Tooltip>
    </NodeToolbar>
  )
}

export const NODE_RESIZE_LINE = "canvas-resize-line"
export const NODE_RESIZE_HANDLE = "canvas-resize-handle"
