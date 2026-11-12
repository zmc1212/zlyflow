import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { IMAGE_ERASER_WORKFLOW, IMAGE_INPAINT_WORKFLOW, IMAGE_OUTPAINT_WORKFLOW, OUTPAINT_TARGET_ASPECTS } from "../generation/image-edit"
import ImageEraserTool, { IMAGE_ERASER_CONFIG } from "./ImageEraserTool"
import ImageInpaintTool, { IMAGE_INPAINT_CONFIG } from "./ImageInpaintTool"
import ImageOutpaintTool from "./ImageOutpaintTool"

function renderWithClient(element: React.ReactElement, workflow: string, data: unknown) {
  const client = new QueryClient()
  client.setQueryData(["tool-workflow", workflow], data)
  const html = renderToStaticMarkup(
    <MemoryRouter><QueryClientProvider client={client}>{element}</QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

function availableMode(id: string) {
  return { id, available: true, parameters: [] }
}

describe("masked image tools (inpaint / eraser)", () => {
  it("inpaint aligns jimeng editor copy with optional prompt", () => {
    // 即梦式编辑弹窗配置：提示词可不填（不填将基于原图生成），应用提交。
    expect(IMAGE_INPAINT_CONFIG.modalTitle).toBe("局部重绘")
    expect(IMAGE_INPAINT_CONFIG.promptRequired).toBe(false)
    expect(IMAGE_INPAINT_CONFIG.promptPlaceholder).toContain("不填将基于原图生成")
    expect(IMAGE_INPAINT_CONFIG.submitLabel).toBe("应用")
    expect(IMAGE_INPAINT_CONFIG.defaultTool).toBe("brush")
  })

  it("renders inpaint upload entry with result note", () => {
    const html = renderWithClient(<ImageInpaintTool csrfToken="" />, IMAGE_INPAINT_WORKFLOW, availableMode(IMAGE_INPAINT_WORKFLOW))
    expect(html).toContain("图片局部重绘")
    expect(html).toContain("上传原图")
    expect(html).toContain("点击选择或拖拽图片到此处")
    expect(html).toContain("只有标记的区域会被重绘")
    // 弹窗未打开前不渲染编辑器画布。
    expect(html).not.toContain("遮罩绘制画布")
  })

  it("eraser keeps optional hint and jimeng apply copy", () => {
    expect(IMAGE_ERASER_CONFIG.modalTitle).toBe("消除笔")
    expect(IMAGE_ERASER_CONFIG.promptRequired).toBe(false)
    expect(IMAGE_ERASER_CONFIG.submitLabel).toBe("应用")
    const html = renderWithClient(<ImageEraserTool csrfToken="" />, IMAGE_ERASER_WORKFLOW, availableMode(IMAGE_ERASER_WORKFLOW))
    expect(html).toContain("消除笔")
    expect(html).toContain("标记区域将被移除并用背景自然填补")
    expect(html).not.toContain("（必填）")
  })

  it("shows backend unavailable reason for masked tools", () => {
    const html = renderWithClient(<ImageInpaintTool csrfToken="" />, IMAGE_INPAINT_WORKFLOW, {
      id: IMAGE_INPAINT_WORKFLOW, available: false, unavailable_reason: "图片服务供应商尚未启用，请联系超级管理员。",
    })
    expect(html).toContain("图片服务供应商尚未启用，请联系超级管理员。")
  })
})

describe("image outpaint tool", () => {
  it("renders upload entry and defers the jimeng-style editor until a source is chosen", () => {
    const html = renderWithClient(<ImageOutpaintTool csrfToken="" />, IMAGE_OUTPAINT_WORKFLOW, availableMode(IMAGE_OUTPAINT_WORKFLOW))
    expect(html).toContain("图片扩图")
    expect(html).toContain("上传原图")
    expect(html).toContain("开始扩图")
    expect(html).toContain("原区域像素与原图完全一致")
    // 编辑器（扩图弹窗）在上传前不渲染。
    expect(html).not.toContain("描述想要扩图的内容")
    // 注册表画幅选项保持不变（生成页通用表单仍在使用）。
    expect(OUTPAINT_TARGET_ASPECTS).toEqual(["16:9", "9:16", "1:1", "4:3", "3:4"])
  })
})
