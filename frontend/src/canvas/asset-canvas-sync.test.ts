import { describe, expect, it } from "vitest"
import type { Director2Asset } from "../director2/api"
import { buildAssetCanvas, readAssetCanvasLayout } from "../director2/asset-canvas-model"
import {
  ASSET_CANVAS_SCHEMA_VERSION,
  isAssetCanvasDraftEmpty,
  mergeProjection,
  migrateLegacyLayout,
  parseAssetCanvasDraft,
  serializeAssetCanvasDraft,
  type AssetCanvasDraft,
} from "./asset-canvas-sync"

const asset = (id: string, kind: string, extra = {}): Director2Asset => ({ id, project_id: "p", kind, name: id, description: "制作描述", visual_prompt: "画面描述", role: null, image_url: null, voice_id: null, extra, created_at: "", updated_at: "" })

const draftNode = (over: Partial<AssetCanvasDraft["nodes"][number]>): AssetCanvasDraft["nodes"][number] => ({
  id: "x", kind: "asset", position: { x: 0, y: 0 }, data: { origin: "asset", assetId: "a", key: "group" }, ...over,
})

describe("asset canvas draft sync", () => {
  it("migrates legacy per-asset layout fragments into one initial draft", () => {
    const assets = [
      asset("a", "character", { identities: [{ id: "look-1" }], creation_canvas: { version: 1, positions: { group: { x: 120, y: 40 } } } }),
      asset("s", "scene", { creation_canvas: { version: 1, positions: { scene_master: { x: 900, y: 12 } }, links: [{ sourceAssetId: "a", sourceKey: "look:look-1", url: "https://cdn/a.png" }] } }),
    ]
    const graph = buildAssetCanvas(assets)
    const draft = migrateLegacyLayout(graph, assets.map(item => readAssetCanvasLayout(item)))
    const group = draft.nodes.find(node => node.id === "a::group")
    expect(group?.position).toEqual({ x: 120, y: 40 })
    expect(group?.data).toMatchObject({ origin: "asset", assetId: "a", key: "group" })
    expect(draft.nodes.find(node => node.id === "s::scene_master")?.position).toEqual({ x: 900, y: 12 })
    // 迁移只带位置，不复制媒体、不固化投影边。
    expect(draft.edges).toEqual([])
    expect(JSON.stringify(draft)).not.toContain("https://cdn/a.png")
    const merged = mergeProjection(graph, draft)
    expect(merged.nodes.filter(node => node.id.startsWith("a::")).every(node => Number.isFinite(node.position.x))).toBe(true)
  })

  it("falls back to an empty draft when no legacy fragments exist", () => {
    const graph = buildAssetCanvas([asset("a", "character")])
    const draft = migrateLegacyLayout(graph, [readAssetCanvasLayout(asset("a", "character"))])
    expect(isAssetCanvasDraftEmpty(draft)).toBe(true)
  })

  it("applies draft positions over projection defaults and keeps generator/video nodes", () => {
    const graph = buildAssetCanvas([asset("a", "character", { identities: [{ id: "look-1" }] })])
    const draft: AssetCanvasDraft = {
      schemaVersion: ASSET_CANVAS_SCHEMA_VERSION,
      nodes: [
        draftNode({ id: "a::group", position: { x: 777, y: 333 } }),
        draftNode({ id: "a::look:look-1", position: { x: 40, y: 60 }, data: { origin: "asset", assetId: "a", key: "look:look-1" } }),
        draftNode({ id: "gen_1", kind: "generator", position: { x: 1200, y: 500 }, data: { workflowId: "r2v", prompt: "运镜" } }),
        draftNode({ id: "vid_1", kind: "video", position: { x: 1700, y: 500 }, data: { url: "https://cdn/out.mp4", label: "成片" } }),
      ],
      edges: [{ id: "ae:a::look:look-1->gen_1", source: "a::look:look-1", target: "gen_1" }],
      viewport: { x: -10, y: -20, zoom: 0.8 },
    }
    const merged = mergeProjection(graph, draft)
    expect(merged.nodes.find(node => node.id === "a::group")?.position).toEqual({ x: 777, y: 333 })
    expect(merged.nodes.find(node => node.id === "a::look:look-1")?.position).toEqual({ x: 40, y: 60 })
    const generator = merged.nodes.find(node => node.id === "gen_1")!
    expect(generator.type).toBe("generator")
    expect(generator.data.origin).toBe("canvas")
    expect(generator.data.prompt).toBe("运镜")
    expect(merged.canvasNodeIds.sort()).toEqual(["gen_1", "vid_1"])
    expect(merged.edges.some(edge => edge.id === "ae:a::look:look-1->gen_1")).toBe(true)
    // 投影内部边保留。
    expect(merged.edges.some(edge => edge.source === "a::definition" && edge.target === "a::look:look-1")).toBe(true)
  })

  it("drops draft nodes for deleted assets or looks and prunes dangling user edges", () => {
    const graph = buildAssetCanvas([asset("a", "character")])
    const draft: AssetCanvasDraft = {
      schemaVersion: ASSET_CANVAS_SCHEMA_VERSION,
      nodes: [
        draftNode({ id: "a::group" }),
        draftNode({ id: "a::look:gone", data: { origin: "asset", assetId: "a", key: "look:gone" } }),
        draftNode({ id: "gone::group", data: { origin: "asset", assetId: "gone", key: "group" } }),
        draftNode({ id: "gen_1", kind: "generator", position: { x: 900, y: 100 }, data: {} }),
      ],
      edges: [
        { id: "ae:ok", source: "a::definition", target: "gen_1" },
        { id: "ae:dead", source: "a::look:gone", target: "gen_1" },
      ],
      viewport: null,
    }
    const merged = mergeProjection(graph, draft)
    expect(merged.nodes.map(node => node.id)).not.toContain("a::look:gone")
    expect(merged.nodes.map(node => node.id)).not.toContain("gone::group")
    expect(merged.nodes.map(node => node.id)).toContain("gen_1")
    expect(merged.edges.map(edge => edge.id)).toContain("ae:ok")
    expect(merged.edges.map(edge => edge.id)).not.toContain("ae:dead")
  })

  it("serializes only reference data for asset nodes and only user edges", () => {
    const source = { ...asset("s", "scene"), image_url: "https://cdn/master.png" }
    const target = asset("a", "character", { source_references: [{ id: "r", url: "https://cdn/master.png" }], creation_canvas: { version: 1, links: [{ sourceAssetId: "s", sourceKey: "scene_master", url: "https://cdn/master.png" }] } })
    const graph = buildAssetCanvas([source, target])
    const nodes = [...graph.nodes, {
      id: "gen_1", type: "generator", position: { x: 900, y: 200 },
      data: { origin: "canvas", canvasKind: "generator", workflowId: "r2v", optionValues: { duration: 5 } },
    } as never]
    const edges = [...graph.edges, { id: "ae:s>gen", source: "s::scene_master", target: "gen_1" }]
    const draft = serializeAssetCanvasDraft(nodes, edges, { x: 1, y: 2, zoom: 0.5 })
    const sceneNode = draft.nodes.find(node => node.id === "s::scene_master")
    expect(sceneNode?.data).toEqual({ origin: "asset", assetId: "s", key: "scene_master", target: { type: "scene_master" } })
    expect(JSON.stringify(draft)).not.toContain("master.png")
    expect(JSON.stringify(draft)).not.toContain("cdn")
    expect(draft.edges).toEqual([{ id: "ae:s>gen", source: "s::scene_master", target: "gen_1", sourceHandle: null, targetHandle: null }])
    expect(draft.viewport).toEqual({ x: 1, y: 2, zoom: 0.5 })
    const generator = draft.nodes.find(node => node.id === "gen_1")
    expect(generator?.kind).toBe("generator")
    expect(generator?.data).toEqual({ workflowId: "r2v", optionValues: { duration: 5 } })
  })

  it("round-trips through JSON without losing positions, canvas nodes, or viewport", () => {
    const graph = buildAssetCanvas([asset("a", "character")])
    const nodes = [...graph.nodes, { id: "vid_1", type: "video", position: { x: 40, y: 50 }, data: { origin: "canvas", canvasKind: "video", url: "/api/media/x.mp4" } } as never]
    const original = serializeAssetCanvasDraft(nodes, [{ id: "ae:g>v", source: "a::group", target: "vid_1" }], { x: 3, y: 4, zoom: 0.9 })
    const parsed = parseAssetCanvasDraft(JSON.stringify(original))
    expect(parsed).toEqual(original)
    const merged = mergeProjection({ nodes: graph.nodes, edges: graph.edges }, parsed)
    expect(merged.nodes.find(node => node.id === "vid_1")).toBeTruthy()
  })

  it("rejects malformed content and fields without throwing", () => {
    expect(isAssetCanvasDraftEmpty(parseAssetCanvasDraft("not json"))).toBe(true)
    expect(isAssetCanvasDraftEmpty(parseAssetCanvasDraft("[]"))).toBe(true)
    const draft = parseAssetCanvasDraft(JSON.stringify({
      nodes: [
        { id: "bad1", kind: "generator", position: { x: 1e9, y: 0 }, data: {} },
        { id: "bad2", kind: "asset", position: { x: 0, y: 0 }, data: { assetId: "" } },
        { id: "bad3", kind: "wat", position: { x: 0, y: 0 }, data: {} },
        draftNode({ id: "ok" }),
      ],
      edges: [{ id: "e", source: "ghost", target: "ok" }, { source: "x::group", target: "x" }],
      viewport: { x: 0, y: 0, zoom: 0 },
    }))
    expect(draft.nodes.map(node => node.id)).toEqual(["ok"])
    expect(draft.edges).toEqual([])
    expect(draft.viewport).toBeNull()
  })
})
