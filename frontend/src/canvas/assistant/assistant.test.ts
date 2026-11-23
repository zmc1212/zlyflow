import { describe, expect, it, vi } from "vitest"
import { CANVAS_NODE_LAYOUT_GAP, canvasNodeSize, type CanvasEdge, type CanvasNode } from "../canvas-model"
import type { CanvasWorkflowMode } from "../canvas-generation"
import { applyAssistantProposalOps, type CanvasAssistantEditorContext } from "./assistant-bridge"
import { describeOp, isExistingRef, mergeAssistantEvent, type AssistantDetail, type CanvasAssistantOp, type MessagePart } from "./api"

function makeDetail(): AssistantDetail {
  return {
    session: { id: "s1", status: "ready", version: 1, created_at: "", updated_at: "", title: "t", canvas_id: "c1", selections: { model_id: "m", web_search: false, image_workflow_id: "", video_workflow_id: "", skill_id: "" }, active_run_id: null, pending_question: null },
    messages: [{ id: "m1", kind: "message", status: "streaming", version: 1, created_at: "", updated_at: "", role: "assistant", run_id: "r1", selections: { model_id: "m", web_search: false, image_workflow_id: "", video_workflow_id: "", skill_id: "" }, parts: [{ type: "markdown", text: "" }] }],
    proposals: [],
    run: null,
  } as unknown as AssistantDetail
}

describe("mergeAssistantEvent", () => {
  it("按 index 流式更新 markdown part", () => {
    const detail = makeDetail()
    const next = mergeAssistantEvent(detail, { index: 0, text: "半截回复" }, "m1")
    expect(next.messages[0].parts[0]).toEqual({ type: "markdown", text: "半截回复" })
  })

  it("snapshot 事件整体替换 parts", () => {
    const detail = makeDetail()
    const parts: MessagePart[] = [{ type: "markdown", text: "完整" }, { type: "tool", name: "canvas_read", label: "读取画布快照", status: "succeeded" }]
    const next = mergeAssistantEvent(detail, { parts }, "m1")
    expect(next.messages[0].parts).toHaveLength(2)
    expect(next.messages[0].parts[1]).toMatchObject({ type: "tool", name: "canvas_read" })
  })

  it("其他消息不受影响", () => {
    const detail = makeDetail()
    detail.messages.push({ ...detail.messages[0], id: "m2", parts: [] })
    const next = mergeAssistantEvent(detail, { index: 0, text: "x" }, "m1")
    expect(next.messages[1].parts).toHaveLength(0)
  })
})

describe("describeOp / isExistingRef", () => {
  const modes = [{ id: "wf-image", name: "图片工作流" }]
  it("生成器操作带工作流名与提示词", () => {
    const text = describeOp({ op: "create_generator", ref: "n1", workflow_id: "wf-image", prompt: "一张图" }, modes)
    expect(text).toContain("图片工作流")
    expect(text).toContain("一张图")
  })
  it("生成器操作展示关键参数与连入节点数", () => {
    const text = describeOp({
      op: "create_generator", ref: "n2", workflow_id: "wf-image", prompt: "p",
      option_values: { aspect_ratio: "9:16", duration: 5, unknown_key: "x" },
      connect_from: ["n1", "g9"],
    }, modes)
    expect(text).toContain("画幅 9:16")
    expect(text).toContain("时长 5")
    expect(text).toContain("unknown_key x")
    expect(text).toContain("连入 2 个节点")
  })
  it("空提示词时按连入关系区分提示词来源文案", () => {
    const withRefs = describeOp({ op: "create_generator", ref: "n1", workflow_id: "wf-image", prompt: "", connect_from: ["n2"] }, modes)
    expect(withRefs).toContain("提示词/参考来自连入节点")
    const withoutRefs = describeOp({ op: "create_generator", ref: "n1", workflow_id: "wf-image", prompt: "" }, modes)
    expect(withoutRefs).toContain("使用画布全局提示词")
  })
  it("connect 用 describeNode 转成可读描述，无解析器时回退原始 ref", () => {
    const describeNode = (ref: string) => ref === "g1" ? "雪地柴犬（生成器）" : ref
    expect(describeOp({ op: "connect", ref: "c1", source_ref: "g1", target_ref: "n2" }, modes, describeNode))
      .toBe("雪地柴犬（生成器） → n2")
    expect(describeOp({ op: "connect", ref: "c1", source_ref: "g1", target_ref: "n2" }, modes))
      .toBe("g1 → n2")
  })
  it("delete_node 描述带可读节点名", () => {
    const describeNode = (ref: string) => ref === "g1" ? "海报（生成器）" : ref
    expect(describeOp({ op: "delete_node", ref: "g1" }, modes, describeNode)).toContain("删除 海报（生成器）")
  })
  it("submit 与素材插入描述", () => {
    expect(describeOp({ op: "submit", ref: "n2" }, modes)).toContain("提交")
    expect(describeOp({ op: "insert_library_item", ref: "n3", item: { kind: "image", label: "封面图" }, as_reference_of: "n1" }, modes)).toContain("封面图")
  })
  it("ref 规则：n 数字为提案内编号，其余为画布已有节点", () => {
    expect(isExistingRef("n1")).toBe(false)
    expect(isExistingRef("N12")).toBe(false)
    expect(isExistingRef("canvas-abc")).toBe(true)
    expect(isExistingRef(null)).toBe(false)
  })
})

function makeContext(initialNodes: CanvasNode[] = [], modes: CanvasWorkflowMode[] = []) {
  const nodesRef = { current: [...initialNodes] }
  const edgesRef = { current: [] as CanvasEdge[] }
  const submitGenerator = vi.fn(async () => true as boolean)
  const saveNow = vi.fn()
  const ctx: CanvasAssistantEditorContext = {
    nodesRef,
    edgesRef,
    setNodes: (updater) => { nodesRef.current = typeof updater === "function" ? (updater as (current: CanvasNode[]) => CanvasNode[])(nodesRef.current) : updater },
    setEdges: (updater) => { edgesRef.current = typeof updater === "function" ? (updater as (current: CanvasEdge[]) => CanvasEdge[])(edgesRef.current) : updater },
    stageCenter: () => ({ x: 0, y: 0 }),
    generationModes: modes,
    globalPrompt: () => "",
    submitGenerator,
    saveNow,
  }
  return { ctx, nodesRef, edgesRef, submitGenerator, saveNow }
}

describe("applyAssistantProposalOps", () => {
  it("创建文字+生成器并连线", async () => {
    const { ctx, nodesRef, edgesRef } = makeContext([], [{ id: "wf-x", name: "测试工作流", media_type: "image" } as unknown as CanvasWorkflowMode])
    const ops: CanvasAssistantOp[] = [
      { op: "create_text", ref: "n1", text: "提示词内容", label: "提示词", op_index: 1 },
      { op: "create_generator", ref: "n2", workflow_id: "wf-x", prompt: "p", connect_from: ["n1"], op_index: 2 },
    ]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.applied).toBe(2)
    expect(result.failed).toHaveLength(0)
    expect(nodesRef.current).toHaveLength(2)
    expect(nodesRef.current[0].type).toBe("text")
    expect(nodesRef.current[1].type).toBe("generator")
    expect(edgesRef.current).toHaveLength(1)
    expect(edgesRef.current[0].source).toBe(nodesRef.current[0].id)
    expect(edgesRef.current[0].target).toBe(nodesRef.current[1].id)
  })

  it("同一提案给长正文和不同比例的视频框预留互不重叠的位置", async () => {
    const mode: CanvasWorkflowMode = {
      id: "video", name: "视频工作流", media_type: "video",
      parameters: [{ name: "options", schema: { properties: {
        aspect_ratio: { label: "画面比例", type: "string", default: "16:9", enum: ["16:9", "9:16"], ui_group: "primary" },
      } } }],
    }
    const { ctx, nodesRef, edgesRef, saveNow } = makeContext([], [mode])
    const text = "雨夜的巷口，电动车碾过水面溅起一片水花。\n".repeat(18)
    const result = await applyAssistantProposalOps([
      { op: "create_text", ref: "n1", text },
      { op: "create_text", ref: "n2", text, position: "below:n1" },
      { op: "create_text", ref: "n3", text, position: "below:n2" },
      { op: "create_generator", ref: "n4", workflow_id: mode.id, position: "right_of:n1", connect_from: ["n1"] },
      { op: "create_generator", ref: "n5", workflow_id: mode.id, position: "right_of:n1", connect_from: ["n1"], option_values: { aspect_ratio: "9:16" } },
      { op: "create_generator", ref: "n6", workflow_id: mode.id, position: "right_of:n2", connect_from: ["n2"] },
    ], ctx)

    expect(result.applied).toBe(6)
    expect(result.failed).toHaveLength(0)
    expect(result.created_node_ids).toHaveLength(6)
    const boxes = nodesRef.current.map(node => ({ ...node.position, ...canvasNodeSize(node) }))
    expect(boxes[0].height).toBeGreaterThan(500)
    expect(boxes[4].height).toBeGreaterThan(boxes[4].width)
    expect(boxes[1].x).toBe(boxes[0].x)
    expect(boxes[3].y).toBe(boxes[0].y)
    for (const [index, box] of boxes.entries()) {
      for (const other of boxes.slice(index + 1)) {
        expect(
          box.x + box.width + CANVAS_NODE_LAYOUT_GAP <= other.x
          || other.x + other.width + CANVAS_NODE_LAYOUT_GAP <= box.x
          || box.y + box.height + CANVAS_NODE_LAYOUT_GAP <= other.y
          || other.y + other.height + CANVAS_NODE_LAYOUT_GAP <= box.y,
        ).toBe(true)
      }
    }
    expect(edgesRef.current.map(edge => edge.source)).toEqual([nodesRef.current[0].id, nodesRef.current[0].id, nodesRef.current[1].id])
    expect(saveNow).toHaveBeenCalledOnce()
  })

  it("submit 引用未创建的 ref 记为失败", async () => {
    const { ctx, submitGenerator } = makeContext()
    const ops: CanvasAssistantOp[] = [{ op: "submit", ref: "n9", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.applied).toBe(0)
    expect(result.failed).toHaveLength(1)
    // 错误文案不暴露内部节点编号（D5），新手可读
    expect(result.failed[0].error).toContain("不是画布上的生成器节点")
    expect(result.failed[0].error).not.toContain("n9")
    expect(submitGenerator).not.toHaveBeenCalled()
  })

  it("submit 画布已有生成器但缺工作流时失败", async () => {
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "p" } } as CanvasNode
    const { ctx, submitGenerator } = makeContext([existing])
    const ops: CanvasAssistantOp[] = [{ op: "submit", ref: "gen-1", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.failed).toHaveLength(1)
    expect(result.failed[0].error).toContain("工作流")
    expect(submitGenerator).not.toHaveBeenCalled()
  })

  it("submit 校验通过时调用提交并立即保存", async () => {
    const mode = { id: "wf-x", name: "测试工作流", media_type: "image", min_references: 0, max_references: 0, accepts_negative_prompt: false, default_prompt: null } as unknown as CanvasWorkflowMode
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "一张图", workflowId: "wf-x" } } as CanvasNode
    const { ctx, submitGenerator, saveNow } = makeContext([existing], [mode])
    const ops: CanvasAssistantOp[] = [{ op: "submit", ref: "gen-1", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.applied).toBe(1)
    expect(result.failed).toHaveLength(0)
    expect(submitGenerator).toHaveBeenCalledWith("gen-1")
    expect(saveNow).toHaveBeenCalled()
  })

  it("submitGenerator 返回 false 时记为失败项", async () => {
    const mode = { id: "wf-x", name: "测试工作流", media_type: "image", min_references: 0, max_references: 0, accepts_negative_prompt: false, default_prompt: null } as unknown as CanvasWorkflowMode
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "一张图", workflowId: "wf-x" } } as CanvasNode
    const { ctx } = makeContext([existing], [mode])
    ctx.submitGenerator = vi.fn(async () => false as boolean)
    const ops: CanvasAssistantOp[] = [{ op: "submit", ref: "gen-1", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.applied).toBe(0)
    expect(result.failed).toHaveLength(1)
    expect(result.failed[0].error).toContain("未提交成功")
  })

  it("引用的画布节点不存在时给出重读提示", async () => {
    const { ctx } = makeContext()
    const ops: CanvasAssistantOp[] = [{ op: "update_generator", ref: "ghost-node", prompt: "x", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.failed).toHaveLength(1)
    expect(result.failed[0].error).toContain("重新读取画布")
  })

  it("delete_node 移除节点与相邻连线，提案内新建与不存在节点报错", async () => {
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "p" } } as CanvasNode
    const textNode: CanvasNode = { id: "t1", type: "text", position: { x: 10, y: 0 }, data: { text: "备注" } } as CanvasNode
    const { ctx, nodesRef, edgesRef } = makeContext([existing, textNode])
    edgesRef.current = [{ id: "e1", source: "t1", target: "gen-1" } as CanvasEdge]
    const result = await applyAssistantProposalOps([{ op: "delete_node", ref: "gen-1", op_index: 1 }], ctx)
    expect(result.applied).toBe(1)
    expect(result.failed).toHaveLength(0)
    expect(nodesRef.current.some(n => n.id === "gen-1")).toBe(false)
    expect(nodesRef.current.some(n => n.id === "t1")).toBe(true)
    expect(edgesRef.current.some(e => e.id === "e1")).toBe(false)
    // 提案内新建 ref（n 编号）不能删
    const rejected = await applyAssistantProposalOps([{ op: "delete_node", ref: "n1", op_index: 1 }], makeContext().ctx)
    expect(rejected.failed).toHaveLength(1)
    expect(rejected.failed[0].error).toContain("提案内节点编号")
    // 不存在的节点
    const missing = await applyAssistantProposalOps([{ op: "delete_node", ref: "ghost", op_index: 1 }], makeContext().ctx)
    expect(missing.failed).toHaveLength(1)
    expect(missing.failed[0].error).toContain("重新读取画布")
  })

  it("update_text 修改文字节点内容，非 text 节点与提案内新建报错", async () => {
    const textNode: CanvasNode = { id: "t1", type: "text", position: { x: 0, y: 0 }, data: { text: "旧内容", label: "备注" } } as CanvasNode
    const genNode: CanvasNode = { id: "gen-1", type: "generator", position: { x: 10, y: 0 }, data: { prompt: "p" } } as CanvasNode
    const { ctx, nodesRef } = makeContext([textNode, genNode])
    const result = await applyAssistantProposalOps([{ op: "update_text", ref: "t1", text: "新内容 v2", op_index: 1 }], ctx)
    expect(result.applied).toBe(1)
    expect(result.failed).toHaveLength(0)
    expect(nodesRef.current.find(n => n.id === "t1")?.data.text).toBe("新内容 v2")
    expect(nodesRef.current.find(n => n.id === "t1")?.data.label).toBe("备注")
    // 非 text 节点
    const wrongKind = await applyAssistantProposalOps([{ op: "update_text", ref: "gen-1", text: "x", op_index: 1 }], makeContext([genNode]).ctx)
    expect(wrongKind.failed).toHaveLength(1)
    expect(wrongKind.failed[0].error).toContain("不是画布上的文字节点")
    // 提案内新建 ref
    const created = await applyAssistantProposalOps([{ op: "update_text", ref: "n1", text: "x", op_index: 1 }], makeContext().ctx)
    expect(created.failed).toHaveLength(1)
    expect(created.failed[0].error).toContain("提案内节点编号")
  })

  it("update_generator 合并已有 optionValues", async () => {
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "old", optionValues: { aspect_ratio: "1:1" }, workflowId: "wf-x" } } as CanvasNode
    const { ctx, nodesRef } = makeContext([existing])
    const ops: CanvasAssistantOp[] = [{ op: "update_generator", ref: "gen-1", option_values: { aspect_ratio: "16:9" }, prompt: "new", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.applied).toBe(1)
    expect(nodesRef.current[0].data.optionValues).toEqual({ aspect_ratio: "16:9" })
    expect(nodesRef.current[0].data.prompt).toBe("new")
  })

  it("不存在的目标节点报错", async () => {
    const { ctx } = makeContext()
    const ops: CanvasAssistantOp[] = [{ op: "update_generator", ref: "ghost", prompt: "x", op_index: 1 }]
    const result = await applyAssistantProposalOps(ops, ctx)
    expect(result.failed).toHaveLength(1)
    // 错误文案不暴露内部节点 ID（D5），给出重读画布指引
    expect(result.failed[0].error).toContain("重新读取画布")
    expect(result.failed[0].error).not.toContain("ghost")
  })

  it("应用结果返回本次新建的节点 ID（撤销检测依据）", async () => {
    const { ctx, nodesRef } = makeContext([], [{ id: "wf-x", name: "测试工作流", media_type: "image" } as unknown as CanvasWorkflowMode])
    const result = await applyAssistantProposalOps([
      { op: "create_text", ref: "n1", text: "提示词" },
      { op: "create_generator", ref: "n2", workflow_id: "wf-x", prompt: "p" },
    ], ctx)
    expect(result.created_node_ids).toHaveLength(2)
    for (const id of result.created_node_ids) {
      expect(nodesRef.current.some(node => node.id === id)).toBe(true)
    }
    // 失败的提案没有新建节点
    const failed = await applyAssistantProposalOps([{ op: "update_generator", ref: "ghost", prompt: "x" }], makeContext().ctx)
    expect(failed.created_node_ids).toHaveLength(0)
  })

  it("删除提案记录被移除的节点 ID（撤销后重现检测依据）", async () => {
    const existing: CanvasNode = { id: "gen-1", type: "generator", position: { x: 0, y: 0 }, data: { prompt: "p" } } as CanvasNode
    const textNode: CanvasNode = { id: "t1", type: "text", position: { x: 10, y: 0 }, data: { text: "备注" } } as CanvasNode
    const { ctx } = makeContext([existing, textNode])
    const result = await applyAssistantProposalOps([{ op: "delete_node", ref: "gen-1" }, { op: "delete_node", ref: "t1" }], ctx)
    expect(result.applied).toBe(2)
    expect(result.removed_node_ids.sort()).toEqual(["gen-1", "t1"])
    expect(result.created_node_ids).toHaveLength(0)
    // 删除失败的提案不记录
    const partial = await applyAssistantProposalOps([{ op: "delete_node", ref: "ghost" }], makeContext().ctx)
    expect(partial.removed_node_ids).toHaveLength(0)
  })
})
