import { describe, expect, it } from "vitest"
import { canvasComposerOptionChoices, canvasComposerOptionLabel, canvasComposerParameterLayout, canvasMediaTime, canvasReferenceSlots, reorderCanvasReferenceEdges } from "./canvas-composer"
import { canvasJobLiveDetails, canvasJobResults, incomingGeneratorReferenceNodes, type CanvasJob, type CanvasWorkflowMode } from "./canvas-generation"
import { buildEdgeId, createGeneratorNode, createImageNode, createTextNode, createVideoNode, parseCanvasContent, type CanvasEdge } from "./canvas-model"

const mode: CanvasWorkflowMode = { id: "dynamic-video", name: "动态视频工作流", media_type: "video", reference_mode: "keyframes", min_references: 1, max_references: 2 }
const image = (id: string) => ({ ...createImageNode({ x: 0, y: 0 }, `/media/${id}.png`), id })
const edge = (source: string, target = "g", handle = "in"): CanvasEdge => ({ id: buildEdgeId(source, target, "out", handle), source, target, sourceHandle: "out", targetHandle: handle })

describe("registry-driven workflow settings", () => {
  const imageMode: CanvasWorkflowMode = {
    id: "custom-image-keys", name: "动态图片模型", media_type: "image",
    parameters: [{ name: "options", schema: { properties: {
      framing: { label: "画面比例", type: "string", default: "1:1", enum: ["auto", "1:1", "9:16"], ui_control: "visual-settings", ui_group: "primary", ui_companions: ["sizeChoice", "outputs", "widthPx", "engine", "missing"] },
      sizeChoice: { label: "分辨率", type: "string", default: "2K", enum: ["2K", "4K", "CUSTOM"], ui_group: "primary" },
      outputs: { label: "生成数量", type: "integer", default: 1, minimum: 1, maximum: 4, step: 1, unit: "张", ui_group: "primary" },
      widthPx: { label: "自定义宽度", type: "integer", default: 1024, minimum: 16, maximum: 3840, step: 16, unit: "px", ui_group: "advanced", ui_visible_when: { sizeChoice: "CUSTOM" } },
      seed: { label: "随机种子", type: "integer", default: 0, ui_group: "advanced" },
      engine: { label: "内部引擎", type: "string", default: "private", ui_group: "internal" },
    } } }],
  }

  it("groups renamed fields in registry order without duplicates or internal fields", () => {
    const layout = canvasComposerParameterLayout(imageMode, { sizeChoice: "2K" })
    expect(layout.visual.map(({ field, companions }) => [field[0], ...companions.map(([name]) => name)])).toEqual([["framing", "sizeChoice", "outputs"]])
    expect(layout.primary).toEqual([])
    expect(layout.advanced.map(([name]) => name)).toEqual(["seed"])
  })

  it("shows custom dimensions only under the registered visibility condition", () => {
    const layout = canvasComposerParameterLayout(imageMode, { sizeChoice: "CUSTOM" })
    expect(layout.visual[0].companions.map(([name]) => name)).toEqual(["sizeChoice", "outputs", "widthPx"])
    const dimensions = layout.visual[0].companions.find(([name]) => name === "widthPx")![1]
    expect(canvasComposerOptionChoices(dimensions)).toEqual([])
    const video = canvasComposerParameterLayout({ ...imageMode, media_type: "video" }, { sizeChoice: "CUSTOM" })
    expect(video.visual).toEqual(layout.visual)
    expect(video.primary).toEqual([])
    expect(video.advanced.map(([name]) => name)).toEqual(["seed"])
  })

  it("uses the actual output limit and numeric step instead of screenshot values", () => {
    const count = imageMode.parameters![0].schema!.properties!.outputs
    expect(canvasComposerOptionChoices(count).map(({ value }) => value)).toEqual([1, 2, 3, 4])
    expect(canvasComposerOptionChoices({ ...count, minimum: 2, maximum: 8, step: 2 }).map(({ value }) => value)).toEqual([2, 4, 6, 8])
    expect(canvasComposerOptionChoices({ ...count, step: 0 })).toEqual([])
    expect(canvasComposerOptionChoices({ ...count, maximum: 10000 })).toEqual([])
    expect(canvasComposerOptionLabel(count, 3)).toBe("3张")
  })

  it("preserves declared labels, selected values and automatic framing", () => {
    const definition = { label: "比例", type: "string", default: "auto", ui_control: "visual-settings", ui_options: [{ value: "auto", label: "自动" }, { value: "9:16", label: "9:16 竖屏" }] } as const
    const field = { ...definition, ui_options: [...definition.ui_options] }
    expect(canvasComposerOptionLabel(field, "auto")).toBe("自动")
    expect(canvasComposerOptionLabel(field, "9:16")).toBe("9:16")
    expect(canvasComposerOptionChoices(field)).toEqual(definition.ui_options)
    expect(canvasComposerOptionLabel({ label: "提示词扩写", type: "boolean", default: true }, undefined)).toBe("开启")
    expect(canvasComposerOptionLabel({ label: "提示词扩写", type: "boolean", default: true }, false)).toBe("关闭")
    const quality = { label: "输出清晰度", type: "string", default: "standard", ui_options: [{ value: "standard", label: "标准（约 400 万像素）", short_label: "标准", hint: "约 400 万像素" }] } as const
    const qualityField = { ...quality, ui_options: [...quality.ui_options] }
    expect(canvasComposerOptionLabel(qualityField, "standard")).toBe("标准")
    expect(canvasComposerOptionChoices(qualityField)[0]).toMatchObject({ value: "standard", label: "标准（约 400 万像素）", hint: "约 400 万像素" })
    const pricedResolution = { label: "分辨率", type: "string", default: "768P", ui_summary: "value", ui_options: [{ value: "768P", label: "768P · 高清 · 26-50 积分/秒" }] } as const
    const resolutionField = { ...pricedResolution, ui_options: [...pricedResolution.ui_options] }
    expect(canvasComposerOptionLabel(resolutionField, "768P")).toBe("768P")
    expect(canvasComposerOptionChoices(resolutionField)[0].label).toContain("26-50 积分/秒")
  })
})

describe("canvas reference composer contract", () => {
  it("uses workflow capabilities for required first-frame and optional end-frame slots", () => {
    expect(canvasReferenceSlots(mode, []).map(({ label, required }) => ({ label, required }))).toEqual([
      { label: "首帧", required: true }, { label: "尾帧", required: false },
    ])
    expect(canvasReferenceSlots({ ...mode, reference_labels: ["首帧", "尾帧（可选）"] }, [])[1].label).toBe("尾帧")
    expect(canvasReferenceSlots({ ...mode, reference_mode: "none", min_references: 0, max_references: 0 }, [])).toEqual([])
    const references = [image("a"), image("b")]
    expect(canvasReferenceSlots({ ...mode, reference_mode: "collection", max_references: 9 }, references)).toHaveLength(3)
    expect(canvasReferenceSlots({ ...mode, reference_mode: "fixed", max_references: 1, reference_labels: ["人物形象"] }, []).map((slot) => slot.label)).toEqual(["人物形象"])
  })

  it("keeps the required video at the end of a variable-length image and video layout", () => {
    const video = createVideoNode({ x: 0, y: 0 }, "/source.mp4")
    const modeWithVideo: CanvasWorkflowMode = {
      ...mode,
      reference_mode: "collection",
      min_references: 2,
      max_references: 4,
      reference_slots: ["image", "image", "image", "video"],
      reference_labels: ["角色图 1", "角色图 2", "角色图 3", "动作视频"],
    }
    const avatar = image("avatar")
    expect(canvasReferenceSlots(modeWithVideo, [video, avatar]).map(({ node, label, required }) => ({ node, label, required }))).toEqual([
      { node: avatar, label: "角色图 1", required: true },
      { node: null, label: "角色图 2", required: false },
      { node: video, label: "动作视频", required: true },
    ])
  })

  it("reorders Picture tokens without changing text inputs, unrelated edges or source nodes", () => {
    const a = image("a"), b = image("b"), c = image("c")
    const text = { ...createTextNode({ x: 0, y: 0 }), id: "text" }
    const nodes = [a, b, c, text]
    const edges = [edge("a"), edge("text", "g", "prompt"), edge("b"), edge("a", "other"), edge("c")]
    const moved = reorderCanvasReferenceEdges(edges, nodes, "g", "b", -1)
    expect(incomingGeneratorReferenceNodes(nodes, moved, "g").map((node) => node.id)).toEqual(["b", "a", "c"])
    expect(moved[1]).toBe(edges[1])
    expect(moved[3]).toBe(edges[3])
    expect(edges[0].source).toBe("a")
    expect(reorderCanvasReferenceEdges(edges, nodes, "g", "a", -1)).toBe(edges)
    expect(reorderCanvasReferenceEdges(edges, nodes, "g", "missing", 1)).toBe(edges)
  })

  it("keeps duplicate source edges together when reference order changes", () => {
    const nodes = [image("a"), image("b")]
    const edges = [edge("a"), edge("b"), { ...edge("a"), id: "legacy-a" }]
    const moved = reorderCanvasReferenceEdges(edges, nodes, "g", "b", -1)
    expect(incomingGeneratorReferenceNodes(nodes, moved, "g").map((node) => node.id)).toEqual(["b", "a"])
    expect(moved).toHaveLength(3)
  })

  it("creates compact new generators without altering an existing saved size", () => {
    const node = createGeneratorNode({ x: 0, y: 0 })
    expect(node.style).toMatchObject({ width: 400, height: 290 })
    const saved = { ...node, position: { x: 145, y: -55 }, style: { width: 356, height: 446 } }
    const restored = parseCanvasContent(JSON.stringify({ schemaVersion: 2, nodes: [saved], edges: [] })).nodes[0]
    expect(restored.position).toEqual(saved.position)
    expect(restored.style).toEqual(saved.style)
  })
})

describe("batch output and partial-result presentation", () => {
  const job: CanvasJob = { id: "job", media_type: "image", status: "partial", rounds: [{ generation_items: [
    { status: "succeeded", outputs: [{ kind: "image", cloud_url: "/one.png" }] },
    { status: "succeeded", outputs: [{ kind: "image", cloud_url: "/two.png" }] },
    { status: "failed" }, { status: "failed" },
  ] }] }

  it("retains all successful outputs and derives 2/4 from actual generation items", () => {
    expect(canvasJobResults(job).map((result) => result.url)).toEqual(["/one.png", "/two.png"])
    expect(canvasJobLiveDetails(job)).toMatchObject({ completedCount: 2, requestedCount: 4 })
  })

  it("does not invent a total for a partial job with no item count", () => {
    expect(canvasJobLiveDetails({ ...job, rounds: [], outputs: [{ kind: "image", cloud_url: "/one.png" }] }).requestedCount).toBeUndefined()
  })

  it("excludes expired outputs, deduplicates and prefers final outputs to previews", () => {
    expect(canvasJobResults({ id: "x", media_type: "video", status: "succeeded", outputs: [
      { kind: "video", download_url: "/preview.mp4", render_pass: "preview" },
      { kind: "video", download_url: "/expired.mp4", delivery_status: "expired" },
      { kind: "video", cloud_url: "/final.mp4", render_pass: "final" },
      { kind: "video", cloud_url: "/final.mp4", render_pass: "final" },
    ] }).map((result) => result.url)).toEqual(["/final.mp4"])
  })

  it("never fabricates video duration before metadata is available", () => {
    expect(canvasMediaTime(null)).toBeNull()
    expect(canvasMediaTime(Infinity)).toBeNull()
    expect(canvasMediaTime(65.8)).toBe("01:05")
  })
})
