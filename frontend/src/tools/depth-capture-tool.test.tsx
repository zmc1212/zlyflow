import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { DEPTH_WORKFLOW } from "../generation/depth"
import DepthCaptureTool from "./DepthCaptureTool"

describe("depth capture tool default creation form", () => {
  it("supports the independent native video editing mode with original-BGM switch", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", "minimax-h3-video-edit"], {
      reference_labels: ["原片视频"],
      parameters: [{ name: "options", schema: { properties: {
        duration: { label: "生成时长", type: "string", default: "5s", ui_group: "primary", enum: ["5s", "10s", "15s"] },
        preserve_audio: { label: "保留原片声音 / BGM", type: "boolean", default: true, ui_group: "primary" },
        seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
        steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
      } } }],
    })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <DepthCaptureTool csrfToken="" workflowId="minimax-h3-video-edit" copy={{ title: "H3 视频编辑（试用）" }} />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain("H3 视频编辑（试用）")
    expect(html).toContain('role="switch"')
    expect(html).toContain("保留原片声音 / BGM")
    expect(html).not.toContain("随机种子")
    expect(html).not.toContain("采样步数")
    client.clear()
  })
  it("uses registry fields and keeps advanced and internal parameters out of the default form", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", DEPTH_WORKFLOW], {
      reference_labels: ["原片视频"],
      parameters: [{ name: "options", schema: { properties: {
        control_strength: { label: "结构跟随强度", type: "number", default: 1, ui_group: "primary", minimum: 0.1, maximum: 1, step: 0.05 },
        composition: { label: "注册表创作选项", type: "string", default: "wide", ui_group: "primary", enum: ["wide", "square"] },
        render_quality: { label: "生成质量", type: "string", default: "standard", ui_group: "advanced", enum: ["standard"] },
        seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
        steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
        da3_resolution: { label: "深度推理分辨率", type: "integer", default: 504, ui_group: "internal" },
      } } }],
    })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <DepthCaptureTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain('aria-label="结构跟随强度"')
    expect(html).toContain('aria-label="注册表创作选项"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("更多设置")
    for (const label of ["生成质量", "随机种子", "采样步数", "深度推理分辨率"]) expect(html).not.toContain(label)
    expect(html).toContain("深度捕捉")
    expect(html).toContain("开始生成")
    client.clear()
  })

  it("marks the prompt as required for depth capture", () => {
    const client = new QueryClient()
    client.setQueryData(["tool-workflow", DEPTH_WORKFLOW], {
      reference_labels: ["原片视频"],
      parameters: [{ name: "options", schema: { properties: {
        control_strength: { label: "结构跟随强度", type: "number", default: 1, ui_group: "primary", minimum: 0.1, maximum: 1, step: 0.05 },
      } } }],
    })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <DepthCaptureTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain("提示词")
    expect(html).toContain("（必填）")
    expect(html).toContain("开始生成")
    client.clear()
  })
})
