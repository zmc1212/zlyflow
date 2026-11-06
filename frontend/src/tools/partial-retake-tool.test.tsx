import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { INPAINT_WORKFLOW } from "../generation/inpaint"
import PartialRetakeTool from "./PartialRetakeTool"

describe("partial retake tool default creation form", () => {
  it("uses registry fields and keeps advanced and internal parameters out of the default form", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", INPAINT_WORKFLOW], {
      reference_labels: ["重绘遮罩图(白色=重绘区)", "原片视频"],
      parameters: [{ name: "options", schema: { properties: {
        inpaint_strength: { label: "重绘强度", type: "number", default: 1, ui_group: "primary", minimum: 0.1, maximum: 1, step: 0.05 },
        composition: { label: "注册表创作选项", type: "string", default: "wide", ui_group: "primary", enum: ["wide", "square"] },
        render_quality: { label: "生成质量", type: "string", default: "standard", ui_group: "advanced", enum: ["standard"] },
        seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
        steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
      } } }],
    })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <PartialRetakeTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain('aria-label="重绘强度"')
    expect(html).toContain('aria-label="注册表创作选项"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("更多设置")
    for (const label of ["生成质量", "随机种子", "采样步数"]) expect(html).not.toContain(label)
    expect(html).toContain("视频局部重拍")
    expect(html).toContain("开始生成")
    client.clear()
  })

  it("marks the prompt as required for inpaint", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", INPAINT_WORKFLOW], {
      reference_labels: ["重绘遮罩图(白色=重绘区)", "原片视频"],
      parameters: [{ name: "options", schema: { properties: {
        inpaint_strength: { label: "重绘强度", type: "number", default: 1, ui_group: "primary", minimum: 0.1, maximum: 1, step: 0.05 },
      } } }],
    })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <PartialRetakeTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain("提示词")
    expect(html).toContain("（必填）")
    expect(html).toContain("开始生成")
    client.clear()
  })
})
