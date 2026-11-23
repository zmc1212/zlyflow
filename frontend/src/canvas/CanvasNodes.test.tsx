import type { NodeProps } from "@xyflow/react"
import type { ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { CanvasGeneratorComposer } from "./CanvasGeneratorComposer"
import { CanvasGeneratorContext, CanvasNodeActionsContext, GeneratorCanvasNode, TextCanvasNode, VideoCanvasNode, type CanvasGeneratorContextValue } from "./CanvasNodes"
import type { CanvasGeneratorLive, CanvasWorkflowMode } from "./canvas-generation"
import { createGeneratorNode, createTextNode, createVideoNode, type CanvasNode } from "./canvas-model"

vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  NodeResizer: () => null,
  NodeToolbar: ({ children, isVisible }: { children: ReactNode; isVisible?: boolean }) => isVisible === false ? null : <div>{children}</div>,
  Handle: ({ id }: { id: string }) => <span data-port={id} />,
  useStore: () => 1,
  useUpdateNodeInternals: () => vi.fn(),
  useReactFlow: () => ({ updateNodeData: vi.fn(), getNode: vi.fn(), setNodes: vi.fn(), getViewport: () => ({ x: 0, y: 0, zoom: 1 }), setViewport: vi.fn() }),
}))

const mode: CanvasWorkflowMode = {
  id: "registry-mode", name: "注册表视频工作流", media_type: "video", reference_mode: "keyframes", min_references: 1, max_references: 2,
  parameters: [{ name: "options", schema: { properties: {
    ratio: { label: "画面比例", type: "string", default: "16:9", enum: ["16:9", "9:16"], ui_group: "primary" },
    seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
    steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
  } } }],
}

function context(live: CanvasGeneratorLive | null = null): CanvasGeneratorContextValue {
  return {
    modes: [mode], modesLoading: false, modeFor: () => mode, workflowName: () => mode.name, liveFor: () => live,
    referenceCountFor: () => 0, referencesFor: () => [], chooseReference: vi.fn(), chooseReferenceSource: vi.fn(), moveReference: vi.fn(), removeReference: vi.fn(),
    promptInfoFor: () => ({ text: "保留这句提示词", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
    issueFor: () => null, disconnectInput: vi.fn(), submit: vi.fn(), cancel: vi.fn(), refine: vi.fn(), insertResult: vi.fn(), submitting: () => false,
  }
}

function generatorNode(live: CanvasGeneratorLive | null) {
  const node = createGeneratorNode({ x: 0, y: 0 }, { workflowId: mode.id, prompt: "保留这句提示词" })
  node.data.jobId = live?.jobId
  return node
}

function renderGenerator(selected: boolean, live: CanvasGeneratorLive | null = null) {
  const node = generatorNode(live)
  const props = { ...node, selected, isConnectable: true, positionAbsoluteX: node.position.x, positionAbsoluteY: node.position.y } as NodeProps<CanvasNode>
  return renderToStaticMarkup(<CanvasGeneratorContext.Provider value={context(live)}><GeneratorCanvasNode {...props} /></CanvasGeneratorContext.Provider>)
}

function renderComposer(live: CanvasGeneratorLive | null = null) {
  const { id, data } = generatorNode(live)
  return renderToStaticMarkup(<CanvasNodeActionsContext.Consumer>{(actions) => <CanvasGeneratorComposer id={id} data={data} generator={context(live)} actions={actions} />}</CanvasNodeActionsContext.Consumer>)
}

describe("canvas node creation surfaces", () => {
  it("mounts an input port for media linked to a text node", () => {
    const node = createTextNode({ x: 0, y: 0 }, "")
    const props = { ...node, selected: false, isConnectable: true, positionAbsoluteX: 0, positionAbsoluteY: 0 } as NodeProps<CanvasNode>
    expect(renderToStaticMarkup(<TextCanvasNode {...props} />).match(/data-port="[^"]+"/g)).toEqual(['data-port="in"', 'data-port="out"'])
  })

  it("renders one input and one output and keeps the composer out of the card", () => {
    for (const selected of [false, true]) {
      const html = renderGenerator(selected)
      expect(html.match(/data-port="[^"]+"/g)).toEqual(['data-port="in"', 'data-port="out"'])
      expect(html).not.toContain("textarea")
    }
  })

  it("renders first-frame requirements from the workflow without internal controls", () => {
    const html = renderComposer()
    expect(html).toContain("添加首帧（必填）")
    expect(html).toContain("添加尾帧（可选）")
    expect(html).not.toContain("添加参考图 3")
    expect(html).toContain("更多设置")
    expect(html).not.toContain("采样步数")
    expect(html).not.toContain("随机种子")
  })

  it("offers both refinement decisions instead of stopping an awaiting-preview task", () => {
    const html = renderComposer({ jobId: "preview", status: "awaiting_refine", result: { url: "/preview.mp4", kind: "video" }, updatedAt: 0 })
    expect(html).toContain("确认二采")
    expect(html).toContain("保留一采")
    expect(html).not.toContain("停止生成")
  })

  it("preserves prompt text for retry and does not fabricate progress", () => {
    const failed = renderComposer({ jobId: "failed", status: "failed", error: "服务暂不可用", updatedAt: 0 })
    expect(failed).toContain("保留这句提示词")
    expect(failed).toContain("重试")
    const pending = { jobId: "queued", status: "queued", updatedAt: 0 } as const
    expect(renderComposer(pending)).toContain("停止生成")
    expect(renderGenerator(true, pending)).not.toContain('aria-valuenow="0"')
  })

  it("shows the interruption reason on the video card", () => {
    const html = renderGenerator(false, { jobId: "interrupted", status: "interrupted", error: "视频服务当前不可用，任务尚未提交。", updatedAt: 0 })
    expect(html).toContain("已中断")
    expect(html).toContain("视频服务当前不可用，任务尚未提交。")
    expect(html).toContain("查看错误详情")
    expect(html).not.toContain("选中节点，开始创作")
  })

  it("represents exactly two successes and two failed items from a real partial snapshot", () => {
    const html = renderGenerator(false, { jobId: "partial", status: "partial", results: [{ url: "/a.png", kind: "image" }, { url: "/b.png", kind: "image" }], completedCount: 2, requestedCount: 4, updatedAt: 0 })
    expect(html).toContain("2/4")
    expect(html.match(/is-failed/g)).toHaveLength(2)
    expect(html.match(/aria-label="查看已完成结果/g)).toHaveLength(2)
  })

  it("does not give ordinary videos a generation action", () => {
    const node = createVideoNode({ x: 0, y: 0 }, "/clip.mp4")
    const html = renderToStaticMarkup(<VideoCanvasNode {...({ ...node, selected: true, isConnectable: true, positionAbsoluteX: node.position.x, positionAbsoluteY: node.position.y } as NodeProps<CanvasNode>)} />)
    expect(html).toContain("播放视频")
    expect(html).not.toContain("以此生成")
    expect(html).not.toContain("00:05")
    expect(html).not.toContain("已完成")
  })
})
