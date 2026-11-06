import { describe, expect, it } from "vitest"
import type { Node, Edge } from "@xyflow/react"
import { assetCanvasConnectionIssue, assetCanvasMedia, assetCanvasOutputKinds, assetCanvasPollingKey, canvasEditingCloudUrl, canvasWorkflowReferenceKind, compileAssetCreativePrompt, moveAssetCanvasReference } from "./asset-canvas-creative"
import { mergeProjection, parseAssetCanvasDraft, serializeAssetCanvasDraft } from "../canvas/asset-canvas-sync"
import { buildAssetCanvas } from "./asset-canvas-model"
import type { Director2Asset } from "./api"
import { director2MenuEpisodeId } from "./paths"
import type { CanvasWorkflowMode } from "../canvas/canvas-generation"

const node = (id: string, kind: string, data = {}): Node => ({ id, type: kind, position: { x: 70, y: 20 }, data: { origin: "canvas", canvasKind: kind, ...data } })

describe("universal director asset canvas", () => {
  it("round trips every new node and its creative draft through persistence", () => {
    const nodes = [node("text", "text", { text: "镜头缓慢推进" }), node("image", "image", { url: "/img.png", style: { presetId: "custom", custom: "水墨" }, design: { 发型: "短发" } }), node("audio", "audio", { url: "/voice.wav", duration: 8 }), node("edit", "editor"), node("video", "video", { resultHistory: [{ url: "/v.mp4", jobId: "j", kind: "video" }] })]
    const edges: Edge[] = [{ id: "text-image", source: "text", target: "image" }, { id: "audio-edit", source: "audio", target: "edit" }]
    const draft = serializeAssetCanvasDraft(nodes, edges, { x: 3, y: -2, zoom: .75 })
    const parsed = parseAssetCanvasDraft(JSON.stringify(draft))
    expect(parsed).toEqual(draft)
    const restored = mergeProjection({ nodes: [], edges: [] }, parsed)
    expect(restored.canvasNodeIds).toHaveLength(5)
    expect(restored.nodes.find(node => node.id === "image")?.data.design).toEqual({ 发型: "短发" })
    expect(restored.nodes.find(node => node.id === "image")?.style?.width).toBe(360)
    expect(restored.nodes.find(node => node.id === "text")?.style?.width).toBe(320)
    expect(restored.nodes.find(node => node.id === "video")?.style?.width).toBe(380)
    expect(restored.edges.map(edge => edge.id)).toEqual(["text-image", "audio-edit"])
  })
  it("reads v1 generator/video drafts and preserves asset references without copying media", () => {
    const asset = { id: "a", project_id: "p", kind: "scene", name: "夜市", image_url: "https://cdn/scene.png", extra: {} } as Director2Asset
    const draft = parseAssetCanvasDraft(JSON.stringify({ schemaVersion: 1, nodes: [{ id: "a::scene_master", kind: "asset", position: { x: 400, y: 90 }, data: { assetId: "a", key: "scene_master" } }, { id: "g", kind: "generator", position: { x: 950, y: 90 }, data: { jobId: "job", workflowId: "h3" } }], edges: [{ id: "ref", source: "a::scene_master", target: "g" }] }))
    const merged = mergeProjection(buildAssetCanvas([asset]), draft)
    expect(merged.nodes.find(node => node.id === "a::scene_master")?.position.x).toBe(400)
    expect(merged.nodes.find(node => node.id === "g")?.data.jobId).toBe("job")
    const next = serializeAssetCanvasDraft(merged.nodes, merged.edges, null)
    expect(JSON.stringify(next)).not.toContain("cdn/scene.png")
  })
  it("rejects duplicate, self and cyclic references, including indirect cycles", () => {
    const nodes = [node("a", "text"), node("b", "image"), node("c", "video")]
    const edges: Edge[] = [{ id: "ab", source: "a", target: "b" }, { id: "bc", source: "b", target: "c" }]
    expect(assetCanvasConnectionIssue(nodes, edges, "c", "a")).toContain("循环")
    expect(assetCanvasConnectionIssue(nodes, edges, "a", "b")).toContain("已经连接")
    expect(assetCanvasConnectionIssue(nodes, edges, "a", "a")).toContain("自身")
    expect(assetCanvasConnectionIssue(nodes, edges, "a", "c")).toBe("")
  })
  it("uses different downstream menus for characters and scenes, even before they have images", () => {
    const assetNode = (kind: string): Node => ({ ...node("a", "assetCreation"), data: { role: "image", asset: { kind } } })
    expect(assetCanvasOutputKinds(assetNode("character"))).toEqual(["image", "video", "audio", "character", "text"])
    expect(assetCanvasOutputKinds(assetNode("scene"))).toEqual(["image", "video", "scene", "text"])
  })
  it("compiles saved design and style into generation without modifying the original prompt", () => {
    const settings = { style: { presetId: "custom", custom: "手绘水彩" }, design: { 发型: "短发", 摄影方案: "正面半身", 肤色: "" } }
    expect(compileAssetCreativePrompt("夜市中走来", settings)).toBe("夜市中走来\n\n角色设计：发型：短发；摄影方案：正面半身\n\n视觉风格：手绘水彩")
    expect(settings.design.肤色).toBe("")
    expect(compileAssetCreativePrompt("原文")).toBe("原文")
    expect(assetCanvasMedia(node("empty", "image"))).toBeNull()
    expect(assetCanvasMedia(node("voice", "audio", { url: "/v.wav", duration: 4 }))?.kind).toBe("audio")
  })
  it("persists user asset-to-asset edges while recomputing projection edges", () => {
    const assets = ["a", "b"].map(id => ({ id, kind: "scene", name: id, extra: {} } as Director2Asset))
    const graph = buildAssetCanvas(assets)
    const edge = { id: "custom", source: "a::scene_master", target: "b::scene_master" }
    const saved = serializeAssetCanvasDraft(graph.nodes, [...graph.edges, edge], null)
    expect(saved.edges.map(item => item.id)).toEqual(["custom"])
    expect(mergeProjection(graph, parseAssetCanvasDraft(JSON.stringify(saved))).edges.some(item => item.id === "custom")).toBe(true)
  })
  it("derives video/audio slots and variable image collections from registry metadata", () => {
    const mode = { reference_slots: ["video", "audio"] } as CanvasWorkflowMode
    expect(canvasWorkflowReferenceKind(mode, 1, 2)).toBe("video")
    expect(canvasWorkflowReferenceKind(mode, 2, 2)).toBe("audio")
    const multi = { reference_slots: ["image", "image", "image", "video"] } as CanvasWorkflowMode
    expect(canvasWorkflowReferenceKind(multi, 1, 2)).toBe("image")
    expect(canvasWorkflowReferenceKind(multi, 2, 2)).toBe("video")
    expect(canvasWorkflowReferenceKind({ accepts_audio_reference: true } as CanvasWorkflowMode, 2, 2)).toBe("audio")
  })
  it("returns to storyboard without treating a canvas edit sequence as an episode", () => {
    expect(director2MenuEpisodeId({ targetMenu: "workshop", currentMenu: "edit", currentEpisodeId: "canvas-editor-1" })).toBeNull()
    expect(director2MenuEpisodeId({ targetMenu: "workshop", currentMenu: "edit", currentEpisodeId: "episode-1" })).toBe("episode-1")
  })
  it("hands off the selected output rather than the first output when paths are absent", () => {
    const outputs = [
      { kind: "video", download_url: "/api/media/first", cloud_url: "https://cdn/first.mp4" },
      { kind: "video", download_url: "/api/media/second", cloud_url: "https://cdn/second.mp4" },
    ]
    expect(canvasEditingCloudUrl("/api/media/second", {}, "video", outputs)).toBe("https://cdn/second.mp4")
    expect(canvasEditingCloudUrl("/api/media/missing", {}, "audio", outputs)).toBeNull()
  })
  it("reorders reference inputs without moving other graph edges and retains the order after saving", () => {
    const edges = [{ id: "other", source: "a", target: "x" }, { id: "one", source: "a", target: "v" }, { id: "two", source: "b", target: "v" }]
    const next = moveAssetCanvasReference(edges, "v", "b", -1)
    expect(next.map(edge => edge.id)).toEqual(["other", "two", "one"])
    const saved = serializeAssetCanvasDraft([node("a", "image"), node("b", "image"), node("v", "video"), node("x", "video")], next, null)
    expect(parseAssetCanvasDraft(JSON.stringify(saved)).edges.filter(edge => edge.target === "v").map(edge => edge.source)).toEqual(["b", "a"])
    expect(edges.map(edge => edge.id)).toEqual(["other", "one", "two"])
  })
  it("keeps one polling lifecycle while editing and progressing, then stops at completion", () => {
    const running = node("v", "video", { jobId: "job", jobStatus: "running", jobProgress: 10 })
    const key = assetCanvasPollingKey([running])
    expect(assetCanvasPollingKey([{ ...running, position: { x: 900, y: 400 }, data: { ...running.data, jobProgress: 90, prompt: "编辑中" } }])).toBe(key)
    expect(assetCanvasPollingKey([{ ...running, data: { ...running.data, jobStatus: "awaiting_refine" } }])).toBe(key)
    expect(assetCanvasPollingKey([{ ...running, data: { ...running.data, jobStatus: "succeeded" } }])).toBe("")
    expect(assetCanvasPollingKey([{ ...running, data: { ...running.data, jobId: "next-job" } }])).not.toBe(key)
  })
})
