import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { IMAGE_BACKGROUND_REMOVE_WORKFLOW, IMAGE_LAYER_SPLIT_WORKFLOW } from "../generation/image-edit"
import ImageBgRemoveTool from "./ImageBgRemoveTool"
import ImageLayerSplitTool from "./ImageLayerSplitTool"

function renderWithClient(element: React.ReactElement, workflow: string, data: unknown) {
  const client = new QueryClient()
  client.setQueryData(["tool-workflow", workflow], data)
  const html = renderToStaticMarkup(
    <MemoryRouter><QueryClientProvider client={client}>{element}</QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

describe("single source image tools", () => {
  it("renders the background removal landing without exposing any technical options", () => {
    const html = renderWithClient(<ImageBgRemoveTool csrfToken="" />, IMAGE_BACKGROUND_REMOVE_WORKFLOW, {
      id: IMAGE_BACKGROUND_REMOVE_WORKFLOW,
      available: true,
      parameters: [{ name: "options", schema: { properties: { rem_mode: { label: "去背景引擎", ui_group: "internal" } } } }],
    })
    expect(html).toContain("图片去背景")
    expect(html).toContain("将文件拖至此处添加")
    expect(html).toContain("从本地上传")
    expect(html).toContain("从资产选取")
    expect(html).not.toContain("去背景引擎")
    expect(html).not.toContain("开始生成")
  })

  it("renders the layer split editor with the three jimeng-style split modes", () => {
    const html = renderWithClient(<ImageLayerSplitTool csrfToken="" />, IMAGE_LAYER_SPLIT_WORKFLOW, {
      id: IMAGE_LAYER_SPLIT_WORKFLOW,
      available: true,
      parameters: [],
    })
    expect(html).toContain("图片图层分离")
    expect(html).toContain("智能拆分")
    expect(html).toContain("框选拆分")
    expect(html).toContain("按描述拆分")
    expect(html).toContain("确认拆分")
    expect(html).toContain("上传要拆分的原图")
    // 智能拆分是默认激活的方式。
    expect(html).toContain("data-active")
  })

  it("keeps the split confirm disabled before an image is uploaded", () => {
    const html = renderWithClient(<ImageLayerSplitTool csrfToken="" />, IMAGE_LAYER_SPLIT_WORKFLOW, {
      id: IMAGE_LAYER_SPLIT_WORKFLOW,
      available: true,
      parameters: [],
    })
    expect(html).toContain("studio-ls-confirm")
    expect(html).toContain("disabled")
    expect(html).toContain("上传要拆分的原图")
  })

  it("shows the backend unavailable reason when the ComfyUI image tool is offline", () => {
    const html = renderWithClient(<ImageBgRemoveTool csrfToken="" />, IMAGE_BACKGROUND_REMOVE_WORKFLOW, {
      id: IMAGE_BACKGROUND_REMOVE_WORKFLOW,
      available: false,
      unavailable_reason: "ComfyUI 或 FRP 当前不可用，任务尚未提交。",
    })
    expect(html).toContain("ComfyUI 或 FRP 当前不可用，任务尚未提交。")
  })
})
