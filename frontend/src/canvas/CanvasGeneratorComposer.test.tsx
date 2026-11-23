import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { CanvasGeneratorComposer } from "./CanvasGeneratorComposer"
import { CanvasNodeActionsContext, type CanvasGeneratorContextValue } from "./node-primitives"
import { type CanvasWorkflowMode } from "./canvas-generation"
import { createGeneratorNode, createImageNode, type CanvasNode } from "./canvas-model"

vi.mock("../api", () => ({ requestJson: vi.fn(), notifyUnauthorized: vi.fn() }))

vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  NodeResizer: () => null,
  NodeToolbar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Handle: () => null,
  useStore: () => 1,
  useUpdateNodeInternals: () => vi.fn(),
  useReactFlow: () => ({ updateNodeData: vi.fn() }),
}))

vi.mock("antd", async (importOriginal) => ({
  ...await importOriginal<typeof import("antd")>(),
  // Render portal content during SSR so the test can exercise the actual controls.
  Popover: ({ children, content }: { children: ReactNode; content: ReactNode }) => <section>{children}{content}</section>,
  Tooltip: ({ title, children }: { title: ReactNode; children: ReactNode }) => <span data-tooltip={typeof title === "string" ? title : ""}>{children}</span>,
}))

describe("shared workflow parameter controls", () => {
  it.each(["image", "video"] as const)("renders the same visual choices for %s workflows", (media_type) => {
    const mode: CanvasWorkflowMode = {
      id: `custom-${media_type}`, name: "测试工作流", media_type,
      parameters: [{ name: "options", schema: { properties: {
        framing: { label: "画面比例", type: "string", default: "1:1", ui_group: "primary", ui_control: "visual-settings", ui_companions: ["clarity"], enum: ["1:1", "16:9", "9:16"] },
        clarity: { label: "输出清晰度", type: "string", default: "standard", ui_group: "primary", ui_options: [
          { value: "standard", label: "标准（约 400 万像素）", short_label: "标准", hint: "约 400 万像素" },
          { value: "high", label: "高清（约 900 万像素）", short_label: "高清", hint: "约 900 万像素" },
        ] },
        expand: { label: "提示词扩写", type: "boolean", default: true, ui_group: "primary" },
        private_steps: { label: "内部采样步数", type: "integer", default: 20, ui_group: "internal" },
      } } }],
    }
    const node = createGeneratorNode({ x: 0, y: 0 }, { workflowId: mode.id })
    const generator: CanvasGeneratorContextValue = {
      modes: [mode], modesLoading: false, modeFor: () => mode, workflowName: () => mode.name,
      liveFor: () => null, referenceCountFor: () => 0, referencesFor: () => [],
      chooseReference: vi.fn(), chooseReferenceSource: vi.fn(), removeReference: vi.fn(), moveReference: vi.fn(),
      promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
      issueFor: () => null, disconnectInput: vi.fn(), submit: vi.fn(), cancel: vi.fn(), refine: vi.fn(), insertResult: vi.fn(), submitting: () => false,
    }
    const html = renderToStaticMarkup(<CanvasNodeActionsContext.Consumer>{(actions) => <CanvasGeneratorComposer id={node.id} data={node.data} generator={generator} actions={actions} />}</CanvasNodeActionsContext.Consumer>)
    expect(html.match(/type="radio"/g)).toHaveLength(5)
    expect(html).toContain('role="switch"')
    expect(html).toContain("1:1 · 标准")
    expect(html).toContain("约 400 万像素")
    expect(html).toContain("约 900 万像素")
    expect(html).not.toContain("内部采样步数")
  })
})

describe("composer reference slots", () => {
  const referenceMode: CanvasWorkflowMode = {
    id: "ref-workflow", name: "参考图工作流", media_type: "image",
    min_references: 0, max_references: 1,
    parameters: [{ name: "options", schema: { properties: {} } }],
  }
  const generatorFor = (reference: CanvasNode): CanvasGeneratorContextValue => ({
    modes: [referenceMode], modesLoading: false, modeFor: () => referenceMode, workflowName: () => referenceMode.name,
    liveFor: () => null, referenceCountFor: () => 1, referencesFor: () => [reference],
    chooseReference: vi.fn(), chooseReferenceSource: vi.fn(), removeReference: vi.fn(), moveReference: vi.fn(),
    promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
    issueFor: () => null, disconnectInput: vi.fn(), submit: vi.fn(), cancel: vi.fn(), refine: vi.fn(), insertResult: vi.fn(), submitting: () => false,
  })
  const renderComposer = (generator: CanvasGeneratorContextValue) => {
    const node = createGeneratorNode({ x: 0, y: 0 }, { workflowId: referenceMode.id })
    return renderToStaticMarkup(<CanvasNodeActionsContext.Consumer>{(actions) => <CanvasGeneratorComposer id={node.id} data={node.data} generator={generator} actions={actions} />}</CanvasNodeActionsContext.Consumer>)
  }
  const chipTag = (html: string, ariaLabel: string) => html.match(new RegExp(`<button[^>]*aria-label="${ariaLabel}"[^>]*>`))?.[0] ?? ""

  it("keeps an upstream node without content visible but disabled, hinting 节点内容为空", () => {
    const html = renderComposer(generatorFor(createImageNode({ x: 0, y: 0 })))
    expect(html).toContain("节点内容为空")
    expect(chipTag(html, "参考图 1（节点内容为空）")).toContain('disabled=""')
    expect(html).toContain("canvas-composer-reference is-filled is-empty")
    expect(html).not.toContain("素材待就绪")
  })

  it("keeps a ready upstream reference clickable with its hover preview", () => {
    const ready = createImageNode({ x: 0, y: 0 }, "https://cdn.example.com/a.png", "图片 2")
    const html = renderComposer(generatorFor(ready))
    const chip = chipTag(html, "替换参考图 1")
    expect(chip).toBeTruthy()
    expect(chip).not.toContain('disabled=""')
    // 即梦式预览：卡片只有图片，替换入口叠在图片右下角，不再回显提示词或说明文字。
    expect(html).toContain('class="canvas-reference-preview-card"')
    expect(html).toMatch(/canvas-reference-preview-actions"><button[^>]*aria-label="替换参考图 1"/)
    expect(html).not.toContain("canvas-reference-preview-bar")
    expect(html).not.toContain("参考图 1 · 图片 2")
    expect(html).not.toContain("节点内容为空")
  })

  it("hides an unusable incoming reference and offers the upgrade add tile on zero-reference workflows", () => {
    const zeroRefMode: CanvasWorkflowMode = {
      id: "minimax-h3-image-t2i", name: "H3 图像 文生图", media_type: "image",
      min_references: 0, max_references: 0, reference_mode: "none",
      parameters: [{ name: "options", schema: { properties: {} } }],
    }
    const editMode: CanvasWorkflowMode = {
      id: "minimax-h3-image-edit", name: "H3 图像 多参考编辑", media_type: "image",
      min_references: 1, max_references: 16, reference_mode: "collection",
      parameters: [{ name: "options", schema: { properties: {} } }],
    }
    const upstream = createGeneratorNode({ x: 0, y: 0 }, { workflowId: zeroRefMode.id, mediaKind: "image" })
    const html = renderToStaticMarkup(
      <CanvasNodeActionsContext.Consumer>{(actions) => {
        const target = createGeneratorNode({ x: 0, y: 0 }, { workflowId: zeroRefMode.id })
        const generator: CanvasGeneratorContextValue = {
          modes: [zeroRefMode, editMode], modesLoading: false, modeFor: () => zeroRefMode, workflowName: () => zeroRefMode.name,
          liveFor: () => null, referenceCountFor: () => 1, referencesFor: () => [upstream],
          chooseReference: vi.fn(), chooseReferenceSource: vi.fn(), removeReference: vi.fn(), moveReference: vi.fn(),
          promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
          issueFor: () => null, disconnectInput: vi.fn(), submit: vi.fn(), cancel: vi.fn(), refine: vi.fn(), insertResult: vi.fn(), submitting: () => false,
        }
        return <CanvasGeneratorComposer id={target.id} data={target.data} generator={generator} actions={actions} />
      }}</CanvasNodeActionsContext.Consumer>,
    )
    // 即梦式：连入但用不上的素材不占参考位，也不出现「自身当参考」的占位
    expect(html).not.toContain("类型不匹配")
    expect(html).not.toContain("来自连入节点")
    // 0 参考位工作流仍显示加号，提示会切换到同系可接参考的工作流
    expect(html).toContain('aria-label="添加参考图"')
    expect(html).toContain("当前工作流不使用参考图")
    expect(html).toContain("H3 图像 多参考编辑")
  })
})

describe("composer credit estimate", () => {
  const billedMode: CanvasWorkflowMode = {
    id: "grs-billed", name: "云端生图", media_type: "image", billing: { enabled: true },
    parameters: [{ name: "options", schema: { properties: {} } }],
  }
  const generatorFor = (mode: CanvasWorkflowMode): CanvasGeneratorContextValue => ({
    modes: [mode], modesLoading: false, modeFor: () => mode, workflowName: () => mode.name,
    liveFor: () => null, referenceCountFor: () => 0, referencesFor: () => [],
    chooseReference: vi.fn(), chooseReferenceSource: vi.fn(), removeReference: vi.fn(), moveReference: vi.fn(),
    promptInfoFor: () => ({ text: "", connectedTextNodes: 0, emptyTextNodes: 0, fromTextNodes: false }),
    issueFor: () => null, disconnectInput: vi.fn(), submit: vi.fn(), cancel: vi.fn(), refine: vi.fn(), insertResult: vi.fn(), submitting: () => false,
  })
  const renderWithEstimate = (mode: CanvasWorkflowMode, authenticated = true) => {
    const node = createGeneratorNode({ x: 0, y: 0 }, { workflowId: mode.id })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <CanvasNodeActionsContext.Consumer>
          {(actions) => <CanvasGeneratorComposer id={node.id} data={node.data} generator={generatorFor(mode)} actions={actions} authenticated={authenticated} />}
        </CanvasNodeActionsContext.Consumer>
      </QueryClientProvider>,
    )
  }

  it("renders the estimate beside the submit button only for billed workflows and signed-in users", () => {
    const billedHtml = renderWithEstimate(billedMode)
    expect(billedHtml).toContain("canvas-composer-cost")
    expect(billedHtml).toContain("本次预计消耗积分")
    expect(renderWithEstimate(billedMode, false)).not.toContain("canvas-composer-cost")
    expect(renderWithEstimate({ ...billedMode, billing: null })).not.toContain("canvas-composer-cost")
  })
})
