import type { Dispatch, MutableRefObject, SetStateAction } from "react"
import { flushSync } from "react-dom"
import { canvasConnectEdge } from "../canvas-connections"
import { CANVAS_GENERATOR_CHROME_HEIGHT, canvasFrameSize, generatorFrameRatio } from "../canvas-frame"
import {
  CANVAS_NODE_LAYOUT_GAP,
  canvasNodeSize,
  createAudioNode,
  createGeneratorNode,
  createLibraryNode,
  createTextNode,
  findCanvasFreePosition,
  libraryItemUrl,
  nextCanvasBranchSlot,
  type CanvasEdge,
  type CanvasNode,
} from "../canvas-model"
import {
  generatorOptionValues,
  generatorPromptInfo,
  incomingGeneratorPromptNodes,
  incomingGeneratorReferenceNodes,
  resolveGeneratorPrompt,
  validateGeneratorInput,
  type CanvasWorkflowMode,
} from "../canvas-generation"
import type { CanvasAssistantOp } from "./api"
import { isExistingRef } from "./api"

export type ProposalApplyResult = {
  applied: number
  failed: { op_index?: number; error: string }[]
  /** 本次应用在画布上新建的节点 ID：撤销后这些节点消失（仅前端使用）。 */
  created_node_ids: string[]
  /** 本次应用删除的画布节点 ID：撤销后这些节点重新出现（仅前端使用）。 */
  removed_node_ids: string[]
}

export type CanvasAssistantEditorContext = {
  nodesRef: MutableRefObject<CanvasNode[]>
  edgesRef: MutableRefObject<CanvasEdge[]>
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>
  setEdges: Dispatch<SetStateAction<CanvasEdge[]>>
  stageCenter: () => { x: number; y: number }
  generationModes: CanvasWorkflowMode[]
  globalPrompt: () => string
  submitGenerator: (nodeId: string) => Promise<boolean> | boolean
  saveNow?: () => unknown
}

export type CanvasAssistantBridge = {
  applyProposal(ops: CanvasAssistantOp[]): Promise<ProposalApplyResult>
  getSelectionIds(): string[]
  getViewportNodeIds(): string[]
  clearSelection?(): void
  /** 把节点 ref 转成用户可读描述（方案卡连线展示用）；节点不存在时原样返回。 */
  describeNode?(ref: string): string
  /** 返回这些节点 ID 中已不在当前画布上的部分（撤销/删除后检测方案卡一致性）。 */
  filterMissingNodeIds?(nodeIds: string[]): string[]
}

type NodeInfo = { kind: string; media_kind: string | null; workflow_id: string | null }

function opError(op: CanvasAssistantOp, error: unknown): { op_index?: number; error: string } {
  return { op_index: op.op_index, error: error instanceof Error ? error.message : String(error) }
}

function missingNodeError(): Error {
  // 面向新手兜底：不暴露内部节点 ID，只描述现象与下一步动作。
  return new Error("提案引用的节点已不在当前画布上（可能已被撤销、删除或由其他窗口修改），请让助手重新读取画布后重试")
}

function sizeGeneratorFrame(node: CanvasNode, mode: CanvasWorkflowMode | undefined): CanvasNode {
  const ratio = generatorFrameRatio(mode, generatorOptionValues(mode, node.data.optionValues))
  if (!ratio || (typeof node.data.frameRatio === "number" && Math.abs(node.data.frameRatio - ratio) <= 0.005)) return node
  const size = canvasFrameSize({ ratio, width: canvasNodeSize(node).width, chromeHeight: CANVAS_GENERATOR_CHROME_HEIGHT })
  return { ...node, measured: undefined, style: { ...node.style, ...size }, data: { ...node.data, frameRatio: ratio } }
}

function resolveAnchorPosition(
  position: string | null | undefined,
  nodes: CanvasNode[],
  nodeForRef: (ref: string) => CanvasNode | undefined,
  stageCenter: CanvasAssistantEditorContext["stageCenter"],
  size: { width: number; height: number },
): { x: number; y: number } {
  const [relation, ref] = (position ?? "").split(":")
  if (ref && (relation === "right_of" || relation === "below")) {
    const anchor = nodeForRef(ref)
    if (anchor) return nextCanvasBranchSlot(anchor, relation === "right_of" ? "right" : "down", nodes, CANVAS_NODE_LAYOUT_GAP, size)
  }
  const center = stageCenter()
  const offset = (nodes.length % 5) * 24
  return findCanvasFreePosition(
    { x: Math.round(center.x - size.width / 2 + offset), y: Math.round(center.y - size.height / 2 + offset) },
    size,
    nodes,
    CANVAS_NODE_LAYOUT_GAP,
  )
}

function generatorInfo(node: CanvasNode): NodeInfo {
  return { kind: "generator", media_kind: String(node.data.mediaKind || node.data.resultKind || ""), workflow_id: node.data.workflowId ?? null }
}

function nodeInfo(node: CanvasNode): NodeInfo {
  if (node.type === "generator") return generatorInfo(node)
  return { kind: node.type || "unknown", media_kind: node.type === "image" || node.type === "video" || node.type === "audio" ? node.type : null, workflow_id: null }
}

function connectFailure(source: NodeInfo, target: NodeInfo): string | null {
  const sourceKind = source.kind === "text" ? "text" : source.kind === "generator" ? (source.media_kind || "image") : source.kind
  const accepted: Record<string, string[]> = {
    text: ["text", "video", "audio"],
    audio: ["text", "audio"],
    generator: ["text", "image", "video", "audio"],
    image: ["generator"],
    video: ["generator"],
  }
  const allowed = accepted[target.kind]
  if (!allowed) return `「${target.kind}」节点不接受连线输入`
  if (sourceKind && !allowed.includes(sourceKind)) return `「${sourceKind}」不能连到「${target.kind}」节点`
  return null
}

/**
 * 逐条应用提案操作（阶段一：建节点/连线/改参数；阶段二：等 nodesRef 刷新后提交任务）。
 * 与画布人工操作同一条校验链：连线规则、参考槽位、提示词校验都复用既有函数。
 */
export async function applyAssistantProposalOps(ops: CanvasAssistantOp[], ctx: CanvasAssistantEditorContext): Promise<ProposalApplyResult> {
  const result: ProposalApplyResult = { applied: 0, failed: [], created_node_ids: [], removed_node_ids: [] }
  const created = new Map<string, string>()
  const nodeUpdates: Array<(nodes: CanvasNode[]) => CanvasNode[]> = []
  const addedEdges = new Map<string, CanvasEdge>()
  const edgeUpdates: Array<(edges: CanvasEdge[]) => CanvasEdge[]> = []
  const removedIds = new Set<string>()
  const submitTargets: CanvasAssistantOp[] = []
  // React 会批处理状态更新，提案内部的排版和引用依赖当前批次的草稿。
  let nodes = ctx.nodesRef.current
  const idForRef = (ref: string | null | undefined) => ref ? created.get(ref) ?? (isExistingRef(ref) ? ref : null) : null
  const nodeForRef = (ref: string | null | undefined) => {
    const id = idForRef(ref)
    return nodes.find((node) => node.id === id)
  }
  const updateNodes = (update: (nodes: CanvasNode[]) => CanvasNode[]) => {
    nodes = update(nodes)
    nodeUpdates.push(update)
  }
  const appendNode = (op: CanvasAssistantOp, node: CanvasNode) => {
    node.position = resolveAnchorPosition(op.position, nodes, nodeForRef, ctx.stageCenter, canvasNodeSize(node))
    created.set(op.ref, node.id)
    updateNodes((current) => [...current, node])
  }
  const addEdge = (sourceId: string, targetId: string) => {
    const edge = canvasConnectEdge(sourceId, targetId)
    addedEdges.set(edge.id, edge)
  }

  for (const op of ops) {
    try {
      if (op.op === "create_text") {
        const node = createTextNode({ x: 0, y: 0 }, op.text || "")
        if (op.label) node.data = { ...node.data, label: op.label }
        appendNode(op, node)
        result.applied++
      } else if (op.op === "create_generator") {
        const mode = ctx.generationModes.find(item => item.id === op.workflow_id)
        if (!mode) throw new Error("提案指定的生成工作流在当前画布不可用，请让助手重新读取工作流目录后再试")
        const node = sizeGeneratorFrame(createGeneratorNode({ x: 0, y: 0 }, {
          prompt: op.prompt || "",
          workflowId: mode.id,
          optionValues: op.option_values || {},
          mediaKind: mode.media_type,
        }), mode)
        if (op.label) node.data = { ...node.data, label: op.label }
        const sourceIds = (op.connect_from ?? []).map((ref) => {
          const sourceNode = nodeForRef(ref)
          if (!sourceNode) throw new Error("提案引用的参考来源节点不存在，请让助手重新读取画布后重试")
          const failure = connectFailure(nodeInfo(sourceNode), generatorInfo(node))
          if (failure) throw new Error(failure)
          return sourceNode.id
        })
        appendNode(op, node)
        for (const sourceId of sourceIds) addEdge(sourceId, node.id)
        result.applied++
      } else if (op.op === "connect") {
        const sourceNode = nodeForRef(op.source_ref)
        const targetNode = nodeForRef(op.target_ref)
        if (!sourceNode || !targetNode) throw missingNodeError()
        const failure = connectFailure(nodeInfo(sourceNode), nodeInfo(targetNode))
        if (failure) throw new Error(failure)
        addEdge(sourceNode.id, targetNode.id)
        result.applied++
      } else if (op.op === "update_generator") {
        const target = nodeForRef(op.ref)
        if (!target) throw missingNodeError()
        if (target.type !== "generator") throw new Error("提案要更新的节点不是画布上的生成器节点")
        const patch: Partial<CanvasNode["data"]> = {}
        if (op.workflow_id) patch.workflowId = op.workflow_id
        if (op.prompt) patch.prompt = op.prompt
        if (op.option_values && Object.keys(op.option_values).length) {
          patch.optionValues = { ...(target.data.optionValues ?? {}), ...op.option_values }
        }
        if (Object.keys(patch).length) {
          const mode = ctx.generationModes.find(item => item.id === (patch.workflowId ?? target.data.workflowId))
          updateNodes(current => current.map(item => item.id === target.id
            ? sizeGeneratorFrame({ ...item, data: { ...item.data, ...patch } }, mode)
            : item))
        }
        result.applied++
      } else if (op.op === "insert_library_item") {
        const item = (op.item || {}) as Parameters<typeof createLibraryNode>[0]
        const kind = String(item.kind || "")
        const node = kind === "audio"
          ? (() => {
            const audio = createAudioNode({ x: 0, y: 0 }, { prompt: String(item.label || "") })
            audio.data = { ...audio.data, url: libraryItemUrl(item), label: String(item.label || "音频素材"), assetPath: (item.path as string) ?? null, sourceJobId: (item.job_id as string) ?? null }
            return audio
          })()
          : createLibraryNode(item, { x: 0, y: 0 })
        if (!node) throw new Error("该素材暂不可插入（未交付或地址无效），请选择已交付的素材")
        const target = nodeForRef(op.as_reference_of)
        if (op.as_reference_of && !target) throw missingNodeError()
        if (target) {
          const failure = connectFailure(nodeInfo(node), nodeInfo(target))
          if (failure) throw new Error(failure)
          addEdge(node.id, target.id)
        }
        appendNode(op, node)
        result.applied++
      } else if (op.op === "update_text") {
        // 修改画布已有文字节点：同提案新建又更新是冗余操作（后端同样拒绝），此处再兜底。
        if (created.has(op.ref)) throw new Error("提案对新建节点又执行了更新，请让助手直接在 create_text 中写最终内容")
        if (!isExistingRef(op.ref)) throw new Error("该引用是提案内节点编号（n1/n2），update_text 只能修改画布已有文字节点（真实节点 ID）")
        const target = nodeForRef(op.ref)
        if (!target) throw missingNodeError()
        if (target.type !== "text") throw new Error("提案要更新的节点不是画布上的文字节点")
        updateNodes(current => current.map(item => item.id === target.id
          ? { ...item, data: { ...item.data, text: op.text ?? item.data.text, ...(op.label ? { label: op.label } : {}) } }
          : item))
        result.applied++
      } else if (op.op === "delete_node") {
        // 只能删除画布已有节点：同提案新建又删除是矛盾操作（后端同样拒绝），此处再兜底。
        if (created.has(op.ref)) throw new Error("提案对新建节点又执行了删除，请让助手把删除项从提案中去掉")
        if (!isExistingRef(op.ref)) throw new Error("该引用是提案内节点编号（n1/n2），delete_node 只能删除画布已有节点（真实节点 ID）")
        const target = nodeForRef(op.ref)
        if (!target) throw missingNodeError()
        updateNodes(current => current.filter(item => item.id !== target.id))
        removedIds.add(target.id)
        for (const [edgeId, edge] of [...addedEdges]) {
          if (edge.source === target.id || edge.target === target.id) addedEdges.delete(edgeId)
        }
        edgeUpdates.push(current => current.filter(item => item.source !== target.id && item.target !== target.id))
        created.delete(op.ref)
        result.applied++
      } else if (op.op === "submit") {
        submitTargets.push(op)
      }
    } catch (error) {
      result.failed.push(opError(op, error))
    }
  }
  if (nodeUpdates.length || addedEdges.size || edgeUpdates.length) {
    // 提交和立即保存都会读取编辑器 refs，先让 React 同步提交这一批改动。
    flushSync(() => {
      if (nodeUpdates.length) ctx.setNodes(current => nodeUpdates.reduce((draft, update) => update(draft), current))
      if (edgeUpdates.length || addedEdges.size) ctx.setEdges(current => {
        const afterRemovals = edgeUpdates.reduce((draft, update) => update(draft), current)
        const existing = new Set(afterRemovals.map(edge => edge.id))
        return [...afterRemovals, ...[...addedEdges.values()].filter(edge => !existing.has(edge.id))]
      })
    })
  }
  if (submitTargets.length) {
    for (const op of submitTargets) {
      try {
        const targetId = idForRef(op.ref)
        const node = targetId ? ctx.nodesRef.current.find(item => item.id === targetId && item.type === "generator") : null
        if (targetId && !node) throw missingNodeError()
        if (!targetId || !node) throw new Error("提案要提交的节点不是画布上的生成器节点")
        const mode = ctx.generationModes.find(item => item.id === node.data.workflowId) ?? null
        if (!mode) throw new Error("请先为该节点选择生成工作流")
        const references = incomingGeneratorReferenceNodes(ctx.nodesRef.current, ctx.edgesRef.current, targetId)
        const promptSource = resolveGeneratorPrompt(
          incomingGeneratorPromptNodes(ctx.nodesRef.current, ctx.edgesRef.current, targetId),
          node.data.prompt ?? "",
        )
        const validation = validateGeneratorInput(mode, promptSource.text, references, generatorPromptInfo(promptSource))
        if (validation) throw new Error(validation)
        const submitted = await ctx.submitGenerator(targetId)
        if (submitted === false) throw new Error("生成任务未提交成功：可能缺少提示词或参考图、工作流暂不可用，或积分余额不足（详见画布提示）")
        result.applied++
      } catch (error) {
        result.failed.push(opError(op, error))
      }
    }
  }
  // 记录本次应用对画布的实际改动：新建的节点（撤销后消失）与删除的节点（撤销后重现），
  // 方案卡据此检测「已应用」状态与画布是否一致。
  result.created_node_ids = [...new Set(created.values())]
  result.removed_node_ids = [...removedIds]
  // 应用完成后立即落盘：自动保存有 1.2s 防抖窗口，应用后立刻刷新可能丢节点。
  try { await ctx.saveNow?.() } catch { /* 保存失败交回自动保存重试链路 */ }
  return result
}
