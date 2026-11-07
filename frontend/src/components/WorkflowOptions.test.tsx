import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { CanvasWorkflowMode } from "../canvas/canvas-generation"
import { groupedWorkflowOptions, WorkflowOptionRow } from "./WorkflowOptions"

describe("shared workflow option rendering", () => {
  it("groups canvas modes by catalog group and flags defaults with credit cost", () => {
    const modes: CanvasWorkflowMode[] = [
      { id: "grs-gpt-image-2.5", name: "GPT Image 2.5", description: "精准生成与编辑", media_type: "image", catalog_group: "image", catalog_group_label: "图片生成", catalog_group_order: 0, is_default: true, credit_cost: 600 },
      { id: "grs-nano-banana", name: "Nano Banana", media_type: "image", catalog_group: "image", catalog_group_label: "图片生成", catalog_group_order: 0, credit_cost: null },
      { id: "h3-t2v", name: "H3 文生视频", media_type: "video" },
    ]
    const options = groupedWorkflowOptions(modes)
    expect(options).toEqual([
      { label: "图片生成", options: [expect.objectContaining({ value: "grs-gpt-image-2.5", isDefault: true, creditCost: 600 }), expect.objectContaining({ value: "grs-nano-banana" })] },
      expect.objectContaining({ value: "h3-t2v", isDefault: false, creditCost: null }),
    ])
  })

  it("renders the option row with description, default flag and cost", () => {
    const html = renderToStaticMarkup(<WorkflowOptionRow item={{ value: "m", label: "智能图片", description: "高质量出图", isDefault: true, creditCost: 42 }} />)
    expect(html).toContain("智能图片")
    expect(html).toContain("高质量出图")
    expect(html).toContain("默认")
    expect(html).toContain("42 积分/张")
  })
})
