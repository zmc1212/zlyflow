import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Job } from "./api"
import { appendCanvasReference, assetCanvasJobNode, assetImageSlots, assetNodeId, assetSlotBlocker, assetSlotImage, buildAssetCanvas, canvasIdentities, patchAssetSlotPrompt, readAssetCanvasLayout } from "./asset-canvas-model"

const asset = (id: string, kind: string, extra = {}): Director2Asset => ({ id, project_id: "p", kind, name: id, description: "制作描述", visual_prompt: "画面描述", role: null, image_url: null, voice_id: null, extra, created_at: "", updated_at: "" })

describe("production asset canvas", () => {
  it("uses stable asset/look IDs and provides a single primary image for scenes and props", () => {
    const graph = buildAssetCanvas([asset("c", "character", { identities: [{ id: "look-a", name: "初始" }] }), asset("s", "scene"), asset("p", "prop")])
    expect(new Set(graph.nodes.map(node => node.id)).size).toBe(graph.nodes.length)
    expect(graph.nodes.find(node => node.id === "c::look:look-a")?.data.target?.identityId).toBe("look-a")
    expect(graph.nodes.filter(node => node.data.asset.id === "s" && node.data.role === "image").map(node => node.id)).toEqual(["s::scene_master"])
    expect(graph.nodes.filter(node => node.data.asset.id === "p" && node.data.role === "image").map(node => node.id)).toEqual(["p::prop_reference"])
    expect(graph.edges.some(edge => edge.source === "s::references" && edge.target === "s::scene_master")).toBe(true)
    expect(graph.nodes.find(node => node.id === "c::definition")?.parentId).toBe("c::group")
  })
  it("keeps stored media, text, and layout when the selected prompt changes", () => {
    const original = asset("c", "character", { identities: [{ id: "one", image_url: "one.png" }, { id: "two", description: "第二套", image_url: "two.png" }], voice: { preset_id: "v" }, creation_canvas: { version: 1, positions: { group: { x: 50, y: 80 } } } })
    const patch = patchAssetSlotPrompt(original, { type: "identity", identityId: "one" }, "新的服装描述")
    const saved = { ...original, extra: { ...original.extra, ...patch } }
    expect(saved.extra.identities[0]).toEqual({ id: "one", image_url: "one.png", description: "新的服装描述", appearance_details: "新的服装描述" })
    expect(saved.extra.identities[1].description).toBe("第二套")
    expect(saved.extra.voice.preset_id).toBe("v")
    expect(readAssetCanvasLayout(saved).positions.group).toEqual({ x: 50, y: 80 })
    expect(original.extra.identities[0]).not.toHaveProperty("description")
  })
  it("provides a deterministic first look for older characters without identities", () => {
    const old = { ...asset("old", "character"), image_url: "legacy.png" }
    const look = canvasIdentities(old)[0]
    expect(look.id).toBe("look-old-default")
    expect(assetSlotImage(old, { type: "identity", identityId: look.id })).toBe("legacy.png")
    expect(old.extra).not.toHaveProperty("identities")
  })
  it("blocks derived generation until its primary image is ready", () => {
    expect(assetSlotBlocker(asset("s", "scene"), { type: "scene_pano" })).toContain("主视角")
    expect(assetSlotBlocker(asset("s", "scene", { master_url: "master.png" }), { type: "scene_pano" })).toBe("")
    expect(assetSlotBlocker(asset("p", "prop"), { type: "prop_turnaround" })).toContain("参考图")
  })
  it("rejects malformed positions without losing valid placements or custom view names", () => {
    const scene = asset("s", "scene", { creation_canvas: { version: 1, positions: { group: { x: 10, y: 20 }, scene_master: { x: null, y: 2 }, bad: { x: 1e8, y: 1 } } }, canvas_node_names: { scene_master: "门口全景" } })
    expect(readAssetCanvasLayout(scene).positions).toEqual({ group: { x: 10, y: 20 } })
    expect(assetImageSlots(scene)).toEqual([{ target: { type: "scene_master" }, title: "门口全景" }])
    expect(buildAssetCanvas([scene]).nodes.find(node => node.id === assetNodeId("s", "group"))?.position).toEqual({ x: 10, y: 20 })
  })
  it("reuses reference snapshots, deduplicates URLs and enforces the nine-image limit", () => {
    const refs = Array.from({ length: 9 }, (_, i) => ({ id: `r${i}`, url: `https://cdn/${i}.png` }))
    const current = asset("c", "character", { source_references: refs })
    expect(appendCanvasReference(current, refs[0].url, "重复")).toHaveLength(9)
    expect(() => appendCanvasReference(current, "https://cdn/new.png", "新增")).toThrow("9")
    expect(() => appendCanvasReference(current, "javascript:alert(1)", "无效")).toThrow("无效")
  })
  it("shows a cross-asset reference edge only while the snapshot remains attached", () => {
    const source = { ...asset("s", "scene"), image_url: "https://cdn/master.png" }
    const target = asset("c", "character", { source_references: [{ id: "r", url: source.image_url }], creation_canvas: { version: 1, positions: {}, links: [{ sourceAssetId: "s", sourceKey: "scene_master", url: source.image_url }] } })
    expect(buildAssetCanvas([source, target]).edges.find(edge => edge.id.startsWith("ref:"))?.target).toBe("c::references")
    target.extra.source_references = []
    expect(buildAssetCanvas([source, target]).edges.some(edge => edge.id.startsWith("ref:"))).toBe(false)
  })
  it("recovers only asset image jobs and keeps distinct looks on their own nodes", () => {
    const job: Director2Job = { id: "job", project_id: "p", job_type: "image_generation", title: "造型", status: "running", progress: 25, result_url: null, error_message: null, created_at: "", updated_at: "", payload: { asset_id: "c", target_type: "identity", identity_id: "look-b" } }
    expect(assetCanvasJobNode(job)).toBe("c::look:look-b")
    expect(assetCanvasJobNode({ ...job, payload: { asset_id: "s", target_type: "scene_reverse" } })).toBe("s::scene_reverse")
    expect(assetCanvasJobNode({ ...job, job_type: "video_generation" })).toBeNull()
    expect(assetCanvasJobNode({ ...job, payload: { asset_id: "c", target_type: "identity" } })).toBeNull()
    expect(assetCanvasJobNode({ ...job, payload: { asset_id: "c", target_type: "triptych" } })).toBeNull()
  })
  it("keeps default placements stable when the server returns recently edited assets first", () => {
    const first = asset("a", "character"), second = asset("b", "character")
    const placements = (items: Director2Asset[]) => Object.fromEntries(buildAssetCanvas(items).nodes.map(node => [node.id, node.position]))
    expect(placements([second, first])).toEqual(placements([first, second]))
  })
})
