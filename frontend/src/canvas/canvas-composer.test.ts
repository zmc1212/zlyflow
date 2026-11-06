import { describe, expect, it } from "vitest"
import { canvasMediaTime, canvasReferenceSlots, reorderCanvasReferenceEdges } from "./canvas-composer"
import { canvasJobLiveDetails, canvasJobResults, incomingGeneratorReferenceNodes, type CanvasJob, type CanvasWorkflowMode } from "./canvas-generation"
import { buildEdgeId, createGeneratorNode, createImageNode, createTextNode, parseCanvasContent, type CanvasEdge } from "./canvas-model"

const mode: CanvasWorkflowMode = { id: "dynamic-video", name: "动态视频工作流", media_type: "video", reference_mode: "keyframes", min_references: 1, max_references: 2 }
const image = (id: string) => ({ ...createImageNode({ x: 0, y: 0 }, `/media/${id}.png`), id })
const edge = (source: string, target = "g", handle = "in"): CanvasEdge => ({ id: buildEdgeId(source, target, "out", handle), source, target, sourceHandle: "out", targetHandle: handle })

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
