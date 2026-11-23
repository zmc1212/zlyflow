import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { CanvasResultComposer } from "./CanvasResultComposer"
import { CanvasNodeActionsContext } from "./node-primitives"
import { canvasModeAcceptsReferenceKind, type CanvasWorkflowMode } from "./canvas-generation"
import { createImageNode, createVideoNode, type CanvasNode, type CanvasRunSnapshot } from "./canvas-model"

vi.mock("../api", () => ({ requestJson: vi.fn(), notifyUnauthorized: vi.fn() }))
vi.mock("antd", async (importOriginal) => ({
  ...await importOriginal<typeof import("antd")>(),
  // Render portal content during SSR so the test can exercise the actual controls.
  Popover: ({ children, content }: { children: ReactNode; content: ReactNode }) => <section>{children}{content}</section>,
}))

function imageMode(overrides: Partial<CanvasWorkflowMode> = {}): CanvasWorkflowMode {
  return {
    id: "seedream-x",
    name: "测试生图",
    media_type: "image",
    reference_mode: "collection",
    min_references: 0,
    max_references: 9,
    ...overrides,
    parameters: [{
      name: "options",
      schema: { properties: {
        framing: { label: "画面比例", type: "string", default: "1:1", ui_group: "primary", ui_control: "visual-settings", ui_companions: ["clarity"], enum: ["1:1", "16:9", "9:16"] },
        clarity: { label: "输出清晰度", type: "string", default: "standard", ui_group: "primary", ui_options: [
          { value: "standard", label: "标准（约 400 万像素）", short_label: "标准", hint: "约 400 万像素" },
          { value: "high", label: "高清（约 900 万像素）", short_label: "高清", hint: "约 900 万像素" },
        ] },
        steps: { label: "内部采样步数", type: "integer", default: 20, ui_group: "internal" },
      } },
    }],
  }
}

function provenance(overrides: Partial<CanvasRunSnapshot> = {}): CanvasRunSnapshot {
  return {
    jobId: "job-1",
    workflowId: "seedream-x",
    workflowName: "测试生图",
    prompt: "雨夜街道霓虹",
    optionValues: { framing: "9:16", clarity: "high" },
    parameterSummary: ["画面比例 竖屏"],
    referenceCount: 0,
    mediaKind: "image",
    submittedAt: Date.parse("2026-11-19T10:20:00"),
    ...overrides,
  }
}

function renderComposer(node: CanvasNode, modes: CanvasWorkflowMode[], snapshot: CanvasRunSnapshot, onRun = vi.fn(), authenticated = true): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CanvasNodeActionsContext.Consumer>
        {(actions) => (
          <CanvasResultComposer node={node} provenance={snapshot} modes={modes} modesLoading={false} actions={actions} onRun={onRun} authenticated={authenticated} />
        )}
      </CanvasNodeActionsContext.Consumer>
    </QueryClientProvider>,
  )
}

describe("result composer echo", () => {
  it("echoes the previous prompt, workflow and visible options for an image result", () => {
    const mode = imageMode()
    const node = createImageNode({ x: 0, y: 0 }, "/api/media/a.png", "成品图")
    const html = renderComposer(node, [mode], provenance())
    expect(html).toContain("雨夜街道霓虹")
    expect(html).toContain("回显上次参数 · 测试生图")
    expect(html).toContain("9:16 · 高清")
    expect(html).toContain("约 900 万像素")
    expect(html).not.toContain("内部采样步数")
    expect(html).toContain("当前图片作为参考")
    expect(html).toContain("生成")
  })

  it("keeps the workflow selector echo but requires a choice when the workflow is gone", () => {
    const mode = imageMode()
    const node = createImageNode({ x: 0, y: 0 }, "/api/media/a.png", "成品图")
    const html = renderComposer(node, [mode], provenance({ workflowId: "removed-wf", workflowName: "已下线工作流" }))
    expect(html).toContain("已下线工作流")
    expect(html).toContain("请先选择生成工作流")
  })

  it("surfaces reference requirements and video nodes as self reference", () => {
    const mode = imageMode({ min_references: 2, max_references: 2 })
    const node = createImageNode({ x: 0, y: 0 }, "/api/media/a.png", "成品图")
    const html = renderComposer(node, [mode], provenance())
    expect(html).toContain("测试生图 需要 2 张参考图，当前 1 张")
    expect(html).toContain("添加参考图 2（必填）")

    const videoMode = imageMode({ id: "video-wf", name: "测试生视频", media_type: "video", reference_slots: ["image", "video"], reference_labels: ["首帧", "参考视频"] })
    const video = createVideoNode({ x: 0, y: 0 }, "/api/media/a.mp4", "成片")
    const videoHtml = renderComposer(video, [videoMode], provenance({
      workflowId: videoMode.id,
      workflowName: videoMode.name,
      mediaKind: "video",
      optionValues: {},
    }))
    expect(canvasModeAcceptsReferenceKind(videoMode, "video")).toBe(true)
    expect(videoHtml).toContain("当前视频作为参考")
    expect(videoHtml).toContain("参考视频")
  })

  it("shows the credit estimate beside the submit button only for billed workflows and signed-in users", () => {
    const node = createImageNode({ x: 0, y: 0 }, "/api/media/a.png", "成品图")
    const billed = imageMode({ billing: { enabled: true } })
    const billedHtml = renderComposer(node, [billed], provenance())
    expect(billedHtml).toContain("canvas-composer-cost")
    expect(billedHtml).toContain("本次预计消耗积分")

    const localHtml = renderComposer(node, [billed], provenance(), vi.fn(), false)
    expect(localHtml).not.toContain("canvas-composer-cost")

    const localMode = imageMode({ id: "local-x", name: "本地生图" })
    const localWorkflowHtml = renderComposer(node, [localMode], provenance({ workflowId: "local-x", workflowName: "本地生图" }))
    expect(localWorkflowHtml).not.toContain("canvas-composer-cost")
  })
})
