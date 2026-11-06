import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { KEYFRAME_WORKFLOW } from "../generation/keyframe"
import KeyframeNarrativeTool from "./KeyframeNarrativeTool"

function seedWorkflow(client: QueryClient) {
  client.setQueryData(["tool-workflow", KEYFRAME_WORKFLOW], {
    reference_labels: ["开场关键帧", "关键帧 2", "关键帧 3", "关键帧 4"],
    parameters: [{ name: "options", schema: { properties: {
      aspect_ratio: { label: "画面比例", type: "string", default: "16:9", ui_group: "primary", enum: ["16:9", "9:16", "1:1"] },
      duration: { label: "生成时长", type: "string", default: "5s", ui_group: "primary", enum: ["5s", "10s", "15s"] },
      anchor_seconds: { label: "锚点时间", type: "string", default: "", ui_group: "primary" },
      seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
      steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
    } } }],
  })
}

describe("keyframe narrative tool default creation form", () => {
  it("renders add card and anchor mode toggle, keeps advanced and internal parameters out", () => {
    const client = new QueryClient()
    seedWorkflow(client)
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <KeyframeNarrativeTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).toContain("关键帧叙事")
    expect(html).toContain("添加关键帧")
    expect(html).toContain("自定义锚点时间")
    expect(html).toContain("均匀分布")
    expect(html).toContain("第一张为")
    expect(html).toContain("开场画面")
    expect(html).toContain("开始生成")
    expect(html).toContain("（必填）")
    for (const label of ["随机种子", "采样步数"]) expect(html).not.toContain(label)
    client.clear()
  })

  it("does not render the anchor time input before any keyframe is uploaded", () => {
    const client = new QueryClient()
    seedWorkflow(client)
    const html = renderToStaticMarkup(<MemoryRouter><QueryClientProvider client={client}>
      <KeyframeNarrativeTool csrfToken="" />
    </QueryClientProvider></MemoryRouter>)
    expect(html).not.toContain("关键帧 2 锚点时间")
    expect(html).not.toContain("锚定到结尾")
    client.clear()
  })
})
