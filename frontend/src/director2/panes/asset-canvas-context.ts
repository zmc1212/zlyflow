import { createContext } from "react"
import type { Node, XYPosition } from "@xyflow/react"
import type { CanvasOptionValue, CanvasWorkflowMode } from "../../canvas/canvas-generation"
import type { AssetCanvasTarget } from "../asset-canvas-model"
import type { AssetCreativeSettings } from "../asset-canvas-creative"
import type { EditAsset } from "../../editing/model"

export type AssetCanvasActions = {
  select: (id: string) => void
  showList: () => void | Promise<void>
  create: (kind: string, position?: XYPosition) => void
  addLook: (id: string) => void
  saveDefinition: (id: string, name: string, role: string, description: string) => Promise<void>
  saveMetadata: (id: string, target: AssetCanvasTarget, name: string) => Promise<void>
  configure: (id: string, target: AssetCanvasTarget, settings: AssetCreativeSettings) => Promise<void>
  prompt: (id: string, target: AssetCanvasTarget, prompt: string) => void
  generate: (id: string, target: AssetCanvasTarget, context?: { prompt?: string; images?: string[] }) => Promise<void>
  upload: (id: string, target: AssetCanvasTarget | null, files: File[]) => Promise<void>
  removeReference: (id: string, refId: string) => Promise<void>
  connect: (sourceId: string, targetId: string) => void
  voice: (id: string) => void
  save: () => Promise<void>
  continue?: () => void | Promise<void>
}

export type CanvasNodeData = Record<string, unknown> & {
  origin?: string; canvasKind?: string; label?: string; prompt?: string; workflowId?: string
  optionValues?: Record<string, CanvasOptionValue>; jobId?: string | null; jobStatus?: string | null
  jobError?: string | null; resultUrl?: string | null; resultPath?: string | null; videoNodeId?: string | null
  url?: string | null; assetPath?: string | null; mediaKind?: string; sourceLabel?: string; pendingGeneratorId?: string
  style?: AssetCreativeSettings["style"]; design?: AssetCreativeSettings["design"]
  resultHistory?: { url: string; path?: string; jobId?: string; kind: string }[]; resultIndex?: number
}

export type AssetCanvasContextValue = {
  actions: AssetCanvasActions; working: string | null; choose: (id: string, edit?: boolean) => void
  editDefinition: (id: string) => void; editMetadata: (id: string) => void; editDesign: (id: string) => void
  chooseFile: (id: string, library: boolean) => void; preview: (url: string, title: string) => void
  modes: CanvasWorkflowMode[]; patchCanvasNode: (id: string, patch: Partial<CanvasNodeData>) => void
  removeCanvasNode: (id: string) => void; submitGenerator: (id: string) => Promise<void>
  createVideoFrom: (id: string) => void; referenceCountOf: (id: string) => number; canvasReady: boolean
  portMenu: (id: string, direction: "in" | "out", anchor: HTMLElement) => void
  inputsOf: (id: string) => Node[]; openSmartEdit: (id: string) => Promise<void>
  duplicate: (id: string) => void; openTool: (id: string, tool: string) => void
  /** 多轨编辑器节点宿主信息：剪辑工程挂在导演项目 scope 下（序列 canvas-<节点id>）。 */
  csrfToken: string; projectId: string
  /** 打开多轨编辑器全屏态（即梦式），不再整页跳转智能剪辑。 */
  openEditorFullscreen: (id: string) => void
  /** 导演项目资产池（资产库 + 画布媒体节点），自动并入多轨编辑器资产列表。 */
  projectAssets: () => EditAsset[]
}

export const AssetCanvasContext = createContext<AssetCanvasContextValue | null>(null)
