import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import FaceSwapTool, { FACE_SWAP_WORKFLOW } from "./FaceSwapTool"

const option = (label: string, definition: Record<string, unknown>) => ({ label, ...definition })

const WORKFLOW = {
  id: FACE_SWAP_WORKFLOW,
  name: "H3 角色替换（换头修脸）",
  description: "把原片视频里主要人物的脸替换成角色形象图的身份。",
  reference_labels: ["角色形象图", "原片视频"],
  accepts_video_reference: true,
  parameters: [{ name: "options", schema: { properties: {
    duration: option("替换时长", { type: "string", default: "5s", ui_group: "primary", enum: ["5s", "10s", "15s"] }),
    crop_factor: option("脸部取景范围", { type: "number", default: 1.8, ui_group: "advanced", minimum: 1.2, maximum: 3.0, step: 0.1 }),
    frame_load_cap: option("处理帧上限", { type: "integer", default: 240, ui_group: "internal" }),
    confidence: option("人脸检测置信度", { type: "number", default: 0.35, ui_group: "internal" }),
  } } }],
}

function render(path = "/tools/face-swap") {
  const client = new QueryClient()
  client.setQueryData(["face-swap-workflow"], WORKFLOW)
  const html = renderToStaticMarkup(
    <MemoryRouter initialEntries={[path]}><QueryClientProvider client={client}>
      <FaceSwapTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

describe("face swap tool", () => {
  it("renders the two image+video reference slots from the registry labels", () => {
    const html = render()
    expect(html).toContain("角色替换")
    expect(html).toContain("角色形象图")
    expect(html).toContain("原片视频")
    expect(html).toContain('aria-label="提示词（可选）"')
    expect(html).toContain("开始替换")
  })

  it("shows only primary controls by default and hides internal params", () => {
    const html = render()
    expect(html).toContain('aria-label="替换时长"')
    // advanced 需渐进展示，internal 永不暴露。
    expect(html).not.toContain('aria-label="脸部取景范围"')
    expect(html).not.toContain("处理帧上限")
    expect(html).not.toContain("人脸检测置信度")
    expect(html).toContain("更多设置")
    expect(html).toContain('aria-expanded="false"')
  })

  it("greys the start button until both materials are ready", () => {
    const html = render()
    expect(html).toMatch(/ant-btn-primary[^>]*disabled/)
  })
})
