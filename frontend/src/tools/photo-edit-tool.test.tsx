import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import PhotoEditTool from "./PhotoEditTool"

function renderPhotoEdit(modes: unknown) {
  const client = new QueryClient()
  client.setQueryData(["tool-workflows", "photo-edit"], modes)
  const html = renderToStaticMarkup(
    <MemoryRouter><QueryClientProvider client={client}><PhotoEditTool csrfToken="" /></QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

describe("photo edit tool", () => {
  it("renders the marking editor with stage, toolbar and prompt bar", () => {
    // AntD Select 的选项标签不在静态标记中渲染；模型过滤逻辑由 image-edit.test.ts 覆盖。
    const html = renderPhotoEdit({
      modes: [
        {
          id: "grs-gpt-image-2", name: "GPT Image 2", media_type: "image", available: true,
          parameters: [{
            name: "options",
            schema: {
              properties: {
                resolution: { label: "分辨率", default: "1K", enum: ["1K", "2K"] },
                count: { label: "生成数量", default: 1, minimum: 1, maximum: 4 },
              },
            },
          }],
        },
        { id: "grs-nano-banana-2", name: "Nano Banana 2", media_type: "image", available: true },
        { id: "minimax-h3-t2v", name: "官方 H3 文生视频", media_type: "video", available: true },
      ],
    })
    expect(html).toContain("图片编辑")
    // 舞台空态：引导上传原图。
    expect(html).toContain("上传要编辑的原图")
    // 工具栏：标记 + 撤销/重做 + 缩放。
    expect(html).toContain("标记")
    expect(html).toContain('aria-label="撤销上一处标记"')
    expect(html).toContain('aria-label="重做标记"')
    expect(html).toContain('aria-label="舞台缩放"')
    expect(html).toContain("100%")
    // 指令条：区域芯片容器 + 指令输入 + 模型/分辨率/数量 + 圆形提交按钮。
    expect(html).toContain('aria-label="已标记区域与参考图"')
    expect(html).toContain('aria-label="编辑指令"')
    expect(html).toContain('aria-label="编辑模型"')
    expect(html).toContain('aria-label="输出分辨率"')
    expect(html).toContain('aria-label="生成数量"')
    expect(html).toContain('aria-label="开始编辑"')
    // 未上传原图、未填写指令时提交按钮禁用，指令条呈弱化态。
    expect(html).toMatch(/<button[^>]*disabled=""/)
    expect(html).toContain("studio-photo-promptbar is-disabled")
  })

  it("hides resolution and count controls when the registry manages single output", () => {
    // schema 缺省（如未登录 payload 或单档模型）时收起分辨率与数量，仅保留模型选择。
    const html = renderPhotoEdit({
      modes: [
        {
          id: "grs-gpt-image-2", name: "GPT Image 2", media_type: "image", available: true,
          parameters: [{ name: "options", schema: { properties: { resolution: { enum: ["1K"], default: "1K" } } } }],
        },
      ],
    })
    expect(html).not.toContain('aria-label="输出分辨率"')
    expect(html).not.toContain('aria-label="生成数量"')
    expect(html).toContain('aria-label="编辑模型"')
  })

  it("shows the empty-state notice when no GRS image model is available", () => {
    // 不可用的模型会被 photoEditWorkflowChoices 过滤，选项为空时给出明确提示。
    const html = renderPhotoEdit({
      modes: [{ id: "grs-gpt-image-2", name: "GPT Image 2", media_type: "image", available: false }],
    })
    expect(html).toContain("暂无可用的图片编辑模型，请稍后重试")
    expect(html).toMatch(/ant-select-disabled/)
    expect(html).toContain("编辑指令")
  })
})
