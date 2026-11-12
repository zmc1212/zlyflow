import { describe, expect, it } from "vitest"
import type { Director2FeaturedSnapshot } from "./api"
import { normalizeRealCanvas, processThumbKind, synthesizeProcessGraph } from "./FeaturedProcessPage"

const baseSnapshot: Director2FeaturedSnapshot = {
  version: 2,
  project: { id: "proj-1", name: "测试精选", description: "", cover_url: "" },
  documents: [],
  episodes: [{
    id: "ep-1", number: 1, title: "第一集", status: "completed", script_text: "正文", summary: "",
    episode_video_url: "https://cdn.example.com/episode.mp4",
    beats: [{
      id: "b1", heading: "开场", speaker: "苏念", dialogue: "你来了", action: "推门",
      camera: "近景", scene: "老宅", time_of_day: "夜",
      image_url: "https://cdn.example.com/shot1.png", video_url: "https://cdn.example.com/shot1.mp4",
      duration: 4, prompt: "A lone scavenger walks the beach",
    }],
  }],
  assets: [
    { id: "ast-1", kind: "character", name: "苏念", role: "女主", description: "短发", visual_prompt: "短发少女", image_url: "https://cdn.example.com/sunian.png" },
    { kind: "scene", name: "老宅", role: "", description: "破旧老宅", image_url: "https://cdn.example.com/old.png" },
  ],
}

describe("normalizeRealCanvas", () => {
  it("资产画布草稿：资产投影解析图片、generator 转提示词节点、边保留", () => {
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      canvas: {
        nodes: [
          { id: "n1", kind: "asset", position: { x: 0, y: 0 }, data: { origin: "asset", assetId: "ast-1", key: "k" } },
          { id: "n2", kind: "generator", position: { x: 10, y: 0 }, data: { prompt: "雨夜街头", url: "https://cdn.example.com/r.mp4", resultKind: "video", workflowId: "minimax-h3-r2v", optionValues: { image_size: "9:16" } } },
          { id: "n3", kind: "text", position: { x: 20, y: 0 }, data: { text: "随手记" } },
        ],
        edges: [{ id: "e1", source: "n1", target: "n2" }, { id: "bad", source: "n1", target: "ghost" }],
        viewport: { x: 5, y: 6, zoom: 0.7 },
      },
    }
    const graph = normalizeRealCanvas(snapshot)
    expect(graph).not.toBeNull()
    expect(graph!.label).toBe("完整创作画布")
    const byId = new Map(graph!.nodes.map(node => [node.id, node]))
    expect(byId.get("n1")!.data.kind).toBe("asset")
    expect(byId.get("n1")!.data.mediaUrl).toBe("https://cdn.example.com/sunian.png")
    expect(byId.get("n1")!.data.label).toBe("苏念")
    expect(byId.get("n2")!.data.kind).toBe("prompt")
    expect(byId.get("n2")!.data.prompt).toBe("雨夜街头")
    expect(byId.get("n2")!.data.workflowId).toBe("minimax-h3-r2v")
    expect(byId.get("n2")!.data.mediaKind).toBe("video")
    expect(byId.get("n3")!.data.kind).toBe("text")
    expect(graph!.edges).toHaveLength(1)
    expect(graph!.edges[0].target).toBe("n2")
  })

  it("无限画布草稿（type 字段）也能归一，未知节点不丢失", () => {
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      canvas: {
        nodes: [
          { id: "w1", type: "video", position: { x: 0, y: 0 }, data: { url: "https://cdn.example.com/v.mp4", cover: "https://cdn.example.com/c.png", label: "镜头" }, style: { width: 320 } },
          { id: "w2", type: "mystery", position: { x: 400, y: 0 }, data: { label: "神秘节点" } },
        ],
        edges: [],
        viewport: null,
      },
    }
    const graph = normalizeRealCanvas(snapshot)
    expect(graph).not.toBeNull()
    const byId = new Map(graph!.nodes.map(node => [node.id, node]))
    expect(byId.get("w1")!.data.kind).toBe("video")
    expect(byId.get("w1")!.data.cover).toBe("https://cdn.example.com/c.png")
    expect(byId.get("w1")!.data.width).toBe(320)
    expect(byId.get("w2")!.data.kind).toBe("unknown")
  })

  it("分组画布：子节点坐标按父分组合成为绝对坐标", () => {
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      canvas: {
        nodes: [
          { id: "g1::group", kind: "asset", position: { x: 360, y: 100 }, data: { origin: "asset", assetId: "ast-1", key: "group" } },
          { id: "g1::definition", kind: "asset", position: { x: 30, y: 45 }, parentId: "g1::group", data: { origin: "asset", assetId: "ast-1", key: "definition" } },
          { id: "g1::references", kind: "asset", position: { x: 30, y: 405 }, parentId: "g1::group", data: { origin: "asset", assetId: "ast-1", key: "references" } },
        ],
        edges: [],
        viewport: null,
      },
    }
    const graph = normalizeRealCanvas(snapshot)
    expect(graph).not.toBeNull()
    const byId = new Map(graph!.nodes.map(node => [node.id, node]))
    expect(byId.get("g1::group")!.position).toEqual({ x: 360, y: 100 })
    expect(byId.get("g1::definition")!.position).toEqual({ x: 390, y: 145 })
    expect(byId.get("g1::references")!.position).toEqual({ x: 390, y: 505 })
    expect(graph!.reflowed).toBe(false)
  })

  it("一行排开的资产画布：分组重排成网格，组内相对位置不变", () => {
    const raw: NonNullable<Director2FeaturedSnapshot["canvas"]>["nodes"] = []
    for (let index = 0; index < 8; index += 1) {
      const groupId = `ast-${index}::group`
      const origin = { origin: "asset", assetId: "ast-1" }
      raw.push({ id: groupId, kind: "asset", position: { x: 360 + index * 1050, y: 100 }, data: { ...origin, key: "group" } })
      raw.push({ id: `ast-${index}::definition`, kind: "asset", position: { x: 30, y: 45 }, parentId: groupId, data: { ...origin, key: "definition" } })
      raw.push({ id: `ast-${index}::look`, kind: "asset", position: { x: 430, y: 100 }, parentId: groupId, data: { ...origin, key: "look" } })
    }
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      canvas: { nodes: raw, edges: [], viewport: { x: -38686, y: 115, zoom: 1.6 } },
    }
    const graph = normalizeRealCanvas(snapshot)
    expect(graph).not.toBeNull()
    expect(graph!.reflowed).toBe(true)
    const byId = new Map(graph!.nodes.map(node => [node.id, node]))
    const groupRowTops = new Set(Array.from({ length: 8 }, (_, index) => Math.round(byId.get(`ast-${index}::group`)!.position.y)))
    expect(groupRowTops.size).toBeGreaterThanOrEqual(3)
    const firstGroup = byId.get("ast-0::group")!.position
    const firstDefinition = byId.get("ast-0::definition")!.position
    const firstLook = byId.get("ast-0::look")!.position
    expect(firstDefinition).toEqual({ x: firstGroup.x + 30, y: firstGroup.y + 45 })
    expect(firstLook).toEqual({ x: firstGroup.x + 430, y: firstGroup.y + 100 })
    expect(firstGroup.x).toBe(0)
    // 同一行的分组按原顺序等距排列，不在同一位置重叠
    const rowXs = [0, 1, 2].map(index => byId.get(`ast-${index}::group`)!.position.x)
    expect(new Set(rowXs).size).toBe(3)
  })

  it("紧凑画布保持原始坐标，不做重排", () => {
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      canvas: {
        nodes: [
          { id: "c1", kind: "image", position: { x: 0, y: 0 }, data: { url: "https://cdn.example.com/a.png" } },
          { id: "c2", kind: "video", position: { x: 400, y: 0 }, data: { url: "https://cdn.example.com/a.mp4" } },
          { id: "c3", kind: "prompt", position: { x: 0, y: 460 }, data: { prompt: "镜头" } },
        ],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      },
    }
    const graph = normalizeRealCanvas(snapshot)
    expect(graph!.reflowed).toBe(false)
    const byId = new Map(graph!.nodes.map(node => [node.id, node]))
    expect(byId.get("c2")!.position).toEqual({ x: 400, y: 0 })
    expect(byId.get("c3")!.position).toEqual({ x: 0, y: 460 })
  })

  it("无画布或空画布返回 null", () => {
    expect(normalizeRealCanvas(baseSnapshot)).toBeNull()
    expect(normalizeRealCanvas({ ...baseSnapshot, canvas: { nodes: [], edges: [], viewport: null } })).toBeNull()
  })

  it("提示词缩略图优先用 resultKind，没有时按扩展名判断视频", () => {
    expect(processThumbKind({ kind: "prompt", mediaUrl: "/api/jobs/j/download", mediaKind: "video" })).toBe("video")
    expect(processThumbKind({ kind: "prompt", mediaUrl: "https://cdn.example.com/clip.mp4" })).toBe("video")
    expect(processThumbKind({ kind: "prompt", mediaUrl: "https://cdn.example.com/still.png" })).toBe("image")
    expect(processThumbKind({ kind: "prompt" })).toBe("image")
  })
})

describe("synthesizeProcessGraph", () => {
  it("资产行 + 每镜头提示词→图→视频链，视频用分镜图做封面", () => {
    const graph = synthesizeProcessGraph(baseSnapshot)
    const kinds = graph.nodes.map(node => [node.id, node.data.kind] as const)
    expect(kinds).toContainEqual(["syn-asset-0", "asset"])
    expect(kinds).toContainEqual(["syn-asset-1", "asset"])
    expect(kinds).toContainEqual(["syn-ep-0", "episode"])
    const byId = new Map(graph.nodes.map(node => [node.id, node]))
    expect(byId.get("syn-p-0-0")!.data.kind).toBe("prompt")
    expect(byId.get("syn-p-0-0")!.data.prompt).toBe("A lone scavenger walks the beach")
    expect(byId.get("syn-i-0-0")!.data.kind).toBe("image")
    expect(byId.get("syn-v-0-0")!.data.kind).toBe("video")
    expect(byId.get("syn-v-0-0")!.data.cover).toBe("https://cdn.example.com/shot1.png")
    // 链：提示词 → 图 → 视频
    const edgePairs = graph.edges.map(edge => [edge.source, edge.target] as const)
    expect(edgePairs).toContainEqual(["syn-p-0-0", "syn-i-0-0"])
    expect(edgePairs).toContainEqual(["syn-i-0-0", "syn-v-0-0"])
  })

  it("缺提示词的镜头用动作与对白兜底", () => {
    const snapshot: Director2FeaturedSnapshot = {
      ...baseSnapshot,
      episodes: [{
        ...baseSnapshot.episodes[0],
        beats: [{
          id: "b1", heading: "", speaker: "苏念", dialogue: "你来了", action: "推门",
          camera: "", scene: "", time_of_day: "", image_url: "", video_url: "", duration: 0,
        }],
      }],
    }
    const graph = synthesizeProcessGraph(snapshot)
    const promptNode = graph.nodes.find(node => node.data.kind === "prompt")
    expect(promptNode).toBeDefined()
    expect(promptNode!.data.prompt).toContain("推门")
    expect(promptNode!.data.prompt).toContain("苏念：你来了")
    // 没有媒体时不产生图/视频节点
    expect(graph.nodes.filter(node => node.data.kind === "image" || node.data.kind === "video")).toHaveLength(0)
  })
})
