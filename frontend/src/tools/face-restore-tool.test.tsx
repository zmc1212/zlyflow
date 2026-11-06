import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { FACE_RESTORE_WORKFLOW } from "../generation/face-restore"
import FaceRestoreTool from "./FaceRestoreTool"

describe("face repair default form", () => {
  it("shows registry creative controls and requires a selected face before submission", () => {
    const client = new QueryClient()
    client.setQueryData(["workflow", FACE_RESTORE_WORKFLOW], { parameters: [{ name: "options", schema: { properties: {
      duration: { label: "处理范围", type: "string", default: "full", ui_group: "primary", enum: ["full", "5s"], ui_options: [{ value: "full", label: "完整视频" }, { value: "5s", label: "前 5 秒试片" }] },
      preserve_audio: { label: "保留原声", type: "boolean", default: true, ui_group: "primary" },
      model_name: { label: "修复模型", type: "string", default: "KEEP", ui_group: "internal" },
      chunk_length: { label: "时序窗口", type: "integer", default: 12, ui_group: "internal" },
      target_point: { label: "人脸标记", type: "string", default: "", ui_group: "internal" },
    } } }] })
    client.setQueryData(["face-restore-capabilities"], { available: true, reason: "" })
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}><FaceRestoreTool csrfToken="" /></QueryClientProvider></MemoryRouter>)
    expect(html).toContain("人脸高清修复")
    expect(html).toContain("高清前原片（可选）")
    expect(html).toContain('aria-label="处理范围"')
    expect(html).toContain('aria-label="保留原声"')
    expect(html).toMatch(/<button[^>]+disabled=""[^>]*>[\s\S]*?开始修复/)
    for (const label of ["修复模型", "时序窗口", "人脸标记"]) expect(html).not.toContain(label)
    client.clear()
  })
})
