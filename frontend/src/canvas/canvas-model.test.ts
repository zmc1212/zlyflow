import { describe, expect, it } from "vitest"
import {
  CANVAS_ASSET_DRAG_TYPE,
  CANVAS_LIBRARY_NODE_SIZES,
  CANVAS_MAX_ZOOM,
  CANVAS_MIN_ZOOM,
  CANVAS_SCHEMA_VERSION,
  CANVAS_VIEWPOINT_COUNT,
  DEFAULT_CANVAS_SETTINGS,
  LEGACY_CANVAS_SCHEMA_VERSION,
  alignCanvasNodes,
  buildEdgeId,
  canvasBranchPosition,
  canvasHistoryState,
  canvasNodeSize,
  canvasNodeTypeLabel,
  canvasViewportChanged,
  copyCanvasClipboard,
  createArtboardNode,
  createCanvasHistory,
  createGeneratorNode,
  createImageNode,
  createLibraryNode,
  createTextNode,
  createVideoNode,
  decodeCanvasAssetDrag,
  distributeCanvasNodes,
  duplicateCanvasSelection,
  encodeCanvasAssetDrag,
  findCanvasFreePosition,
  isCoverOnlyCanvasChange,
  isSafeMediaUrl,
  isUsableLibraryItem,
  libraryItemUrl,
  nextCanvasBranchSlot,
  normalizeEdges,
  parseCanvasContent,
  pasteCanvasClipboard,
  pushCanvasHistory,
  readCanvasPreview,
  readCanvasSettings,
  readCanvasViewport,
  readCanvasViewpoints,
  redoCanvasHistory,
  serializeCanvasDraft,
  undoCanvasHistory,
  type CanvasLibraryItem,
  type CanvasNode,
} from "./canvas-model"

describe("canvas edit history", () => {
  it("does not create an undo step when flushing a draft with only a new video cover", () => {
    const node = createVideoNode({ x: 0, y: 0 }, "/video.mp4")
    const initial = serializeCanvasDraft([node], [])
    const history = createCanvasHistory(initial)
    const captured = serializeCanvasDraft([{ ...node, data: { ...node.data, cover: "data:image/jpeg;base64,AAAA", coverSource: "/video.mp4", coverTime: 0 } }], [])
    expect(pushCanvasHistory(history, captured)).toBe(history)
    expect(canvasHistoryState(history)).toEqual({ canUndo: false, canRedo: false })
  })
  it("can still open legacy malformed display data without rendering objects as React children", () => {
    const draft = parseCanvasContent(JSON.stringify({
      nodes: [{ id: "old", type: "text", position: { x: 0, y: 0 }, data: { label: {}, text: ["bad"], metadata: { keep: true } } }], edges: [],
    }))
    expect(draft.nodes[0].data.label).toBeUndefined()
    expect(draft.nodes[0].data.text).toBeUndefined()
    expect(draft.nodes[0].data).toHaveProperty("metadata", { keep: true })
  })
  it("preserves redo while selection or viewport-only changes are reported", () => {
    const nodes = [createTextNode({ x: 0, y: 0 }, "开场")]
    const original = serializeCanvasDraft(nodes, [], { canvasSettings: { gridVisible: true, viewport: { x: 0, y: 0, zoom: 1 } } })
    const changed = serializeCanvasDraft(nodes, [], { canvasSettings: { gridVisible: false, viewport: { x: 0, y: 0, zoom: 1 } } })
    const undone = undoCanvasHistory(pushCanvasHistory(createCanvasHistory(original), changed))
    const panned = serializeCanvasDraft(nodes, [], { canvasSettings: { gridVisible: true, viewport: { x: 100, y: 200, zoom: 0.5 } } })
    const history = pushCanvasHistory(undone, panned)
    expect(history).toBe(undone)
    expect(canvasHistoryState(history).canRedo).toBe(true)
    expect(redoCanvasHistory(history).entries[1]).toBe(changed)
  })
})

function layoutNode(id: string, x: number, y: number, width: number, height: number): CanvasNode {
  return {
    id,
    type: "image",
    position: { x, y },
    data: {},
    measured: { width, height },
  }
}

function libraryItem(overrides: Partial<CanvasLibraryItem> = {}): CanvasLibraryItem {
  return {
    kind: "image",
    path: "user/demo.png",
    label: "分镜 1",
    delivery_status: "cloud",
    download_url: "/api/jobs/j1/download",
    cloud_url: "https://cdn.example.com/demo.png",
    created_at: "2026-10-21T00:00:00Z",
    ...overrides,
  }
}

describe("canvas draft model", () => {
  it("round-trips nodes and edges without transient fields", () => {
    const node = { ...createTextNode({ x: 12, y: 24 }, "开场"), selected: true, dragging: false }
    const edge = { id: "e1", source: "a", target: "b", selected: true }
    const content = serializeCanvasDraft([node], [edge])
    const parsed = parseCanvasContent(content)
    expect(parsed.nodes).toHaveLength(1)
    expect(parsed.nodes[0]).toMatchObject({ id: node.id, type: "text", position: { x: 12, y: 24 } })
    expect(parsed.nodes[0].selected).toBeUndefined()
    expect(parsed.edges[0]).toMatchObject({ id: "e1", source: "a", target: "b", type: "smoothstep" })
  })

  it("deduplicates edges by id and builds stable canonical ids", () => {
    const canonical = buildEdgeId("n1", "n2")
    expect(canonical).toBe("cc-edge__n1|out|n2|in")
    const edges = normalizeEdges([
      { id: canonical, source: "n1", target: "n2" },
      { id: canonical, source: "n1", target: "n2" },
    ])
    expect(edges).toHaveLength(1)
    expect(edges[0].sourceHandle).toBeNull()
    expect(edges[0].targetHandle).toBeNull()
  })

  it("parses malformed content as an empty canvas", () => {
    expect(parseCanvasContent("not-json")).toEqual({
      schemaVersion: CANVAS_SCHEMA_VERSION,
      nodes: [],
      edges: [],
    })
    expect(parseCanvasContent("{}")).toEqual({
      schemaVersion: LEGACY_CANVAS_SCHEMA_VERSION,
      nodes: [],
      edges: [],
      canvasSettings: undefined,
    })
    expect(parseCanvasContent(JSON.stringify({ nodes: "bad", edges: [{ source: 1 }] }))).toEqual({
      schemaVersion: LEGACY_CANVAS_SCHEMA_VERSION,
      nodes: [],
      edges: [],
      canvasSettings: undefined,
    })
  })

  it("writes the current schema version and reads legacy drafts as v1", () => {
    const content = serializeCanvasDraft([], [])
    expect(JSON.parse(content).schemaVersion).toBe(CANVAS_SCHEMA_VERSION)
    expect(parseCanvasContent(content).schemaVersion).toBe(CANVAS_SCHEMA_VERSION)

    const legacy = JSON.stringify({
      nodes: [{ id: "t1", type: "text", position: { x: 1, y: 2 }, data: { text: "开场" } }],
      edges: [],
    })
    const parsed = parseCanvasContent(legacy)
    expect(parsed.schemaVersion).toBe(LEGACY_CANVAS_SCHEMA_VERSION)
    expect(parsed.nodes[0].data).toEqual({ text: "开场" })
  })

  it("preserves canvas settings and node zIndex across a round trip", () => {
    const content = serializeCanvasDraft([createArtboardNode({ x: 8, y: 16 })], [], {
      canvasSettings: { viewport: { x: 10, y: 20, zoom: 1.5 } },
    })
    const parsed = parseCanvasContent(content)
    expect(parsed.canvasSettings).toEqual({ viewport: { x: 10, y: 20, zoom: 1.5 } })
    expect(parsed.nodes[0].zIndex).toBe(0)
  })

  it("normalizes unknown node types and restores them on save", () => {
    const futureDraft = JSON.stringify({
      schemaVersion: 99,
      nodes: [{
        id: "story_1",
        type: "storyboard",
        position: { x: 10, y: 20 },
        data: { prompt: "雨夜街道", options: { ratio: "16:9" } },
        style: { width: 300 },
        zIndex: 4,
      }],
      edges: [],
    })
    const parsed = parseCanvasContent(futureDraft)
    expect(parsed.nodes[0].type).toBe("unknown")
    expect(parsed.nodes[0].data).toEqual({
      prompt: "雨夜街道",
      options: { ratio: "16:9" },
      originalType: "storyboard",
    })

    const saved = JSON.parse(serializeCanvasDraft(parsed.nodes, parsed.edges))
    expect(saved.schemaVersion).toBe(CANVAS_SCHEMA_VERSION)
    expect(saved.nodes[0].type).toBe("storyboard")
    expect(saved.nodes[0].data).toEqual({ prompt: "雨夜街道", options: { ratio: "16:9" } })
    expect(saved.nodes[0].zIndex).toBe(4)

    const reopened = parseCanvasContent(serializeCanvasDraft(parsed.nodes, parsed.edges))
    expect(reopened.nodes[0].type).toBe("unknown")
    expect(reopened.nodes[0].data.originalType).toBe("storyboard")
  })

  it("round-trips generator nodes with workflow, options, job result and run snapshot", () => {
    const runSnapshot = {
      jobId: "job_1",
      workflowId: "minimax-h3-lightx2v-i2v",
      workflowName: "MiniMax H3 首尾帧视频",
      prompt: "雨夜街道，霓虹倒影",
      optionValues: { aspect_ratio: "9:16", duration: 5 },
      parameterSummary: ["画面比例 竖屏", "时长 5"],
      referenceCount: 2,
      mediaKind: "video" as const,
      submittedAt: 1760000000000,
    }
    const node: CanvasNode = {
      ...createGeneratorNode({ x: 40, y: 80 }),
      data: {
        label: "生成",
        workflowId: "minimax-h3-lightx2v-i2v",
        prompt: "雨夜街道，霓虹倒影",
        optionValues: { aspect_ratio: "9:16", duration: 5 },
        jobId: "job_1",
        jobStatus: "succeeded",
        jobError: null,
        resultUrl: "/api/media/user%2Fout.mp4",
        resultKind: "video",
        resultPath: "user/out.mp4",
        lastRun: runSnapshot,
        runHistory: [runSnapshot],
      },
    }
    const parsed = parseCanvasContent(serializeCanvasDraft([node], []))
    expect(parsed.nodes[0].type).toBe("generator")
    expect(parsed.nodes[0].data).toMatchObject({
      workflowId: "minimax-h3-lightx2v-i2v",
      prompt: "雨夜街道，霓虹倒影",
      optionValues: { aspect_ratio: "9:16", duration: 5 },
      jobId: "job_1",
      jobStatus: "succeeded",
      resultUrl: "/api/media/user%2Fout.mp4",
      resultKind: "video",
      resultPath: "user/out.mp4",
      lastRun: runSnapshot,
      runHistory: [runSnapshot],
    })
  })

  it("keeps untyped nodes as unknown and does not drop their data", () => {
    const parsed = parseCanvasContent(JSON.stringify({
      nodes: [{ id: "n1", position: { x: 4, y: 6 }, data: { foo: "bar" } }],
      edges: [],
    }))
    expect(parsed.nodes[0].type).toBe("unknown")
    expect(parsed.nodes[0].data).toEqual({ foo: "bar", originalType: "default" })

    const saved = JSON.parse(serializeCanvasDraft(parsed.nodes, parsed.edges))
    expect(saved.nodes[0].type).toBe("default")
    expect(saved.nodes[0].data).toEqual({ foo: "bar" })
  })

  it("repairs invalid positions and data without dropping the node", () => {
    const parsed = parseCanvasContent(JSON.stringify({
      nodes: [{ id: "n1", type: "text", position: { x: "a", y: null }, data: null }],
      edges: [],
    }))
    expect(parsed.nodes).toHaveLength(1)
    expect(parsed.nodes[0].position).toEqual({ x: 0, y: 0 })
    expect(parsed.nodes[0].data).toEqual({})
  })

  it("creates the supported node kinds", () => {
    expect(createTextNode({ x: 0, y: 0 }).type).toBe("text")
    expect(createImageNode({ x: 0, y: 0 })).toMatchObject({ type: "image", data: { mediaKind: "image" } })
    expect(createVideoNode({ x: 0, y: 0 }, "/api/media/demo.mp4", "片段")).toMatchObject({
      type: "video",
      data: { url: "/api/media/demo.mp4", label: "片段", mediaKind: "video" },
    })
    expect(createArtboardNode({ x: 0, y: 0 })).toMatchObject({ type: "artboard", zIndex: 0 })
    expect(createGeneratorNode({ x: 0, y: 0 })).toMatchObject({
      type: "generator",
      data: { label: "生成", prompt: "", optionValues: {} },
      style: { width: 400 },
    })
  })
})

describe("canvas media urls", () => {
  it("accepts http, https and site paths for images and videos", () => {
    expect(isSafeMediaUrl("https://cdn.example.com/a.png", "image")).toBe(true)
    expect(isSafeMediaUrl(" http://example.com/v.mp4 ", "video")).toBe(true)
    expect(isSafeMediaUrl("/api/media/video.mp4", "video")).toBe(true)
    expect(isSafeMediaUrl("data:image/png;base64,AAAA", "image")).toBe(true)
  })

  it("rejects arbitrary protocols and data urls on video nodes", () => {
    expect(isSafeMediaUrl("javascript:alert(1)", "image")).toBe(false)
    expect(isSafeMediaUrl("file:///tmp/a.png", "image")).toBe(false)
    expect(isSafeMediaUrl("data:video/mp4;base64,AAAA", "video")).toBe(false)
    expect(isSafeMediaUrl("", "image")).toBe(false)
  })
})

describe("canvas library assets", () => {
  it("prefers stable cloud urls and falls back to same-origin media", () => {
    expect(libraryItemUrl(libraryItem())).toBe("https://cdn.example.com/demo.png")
    expect(libraryItemUrl(libraryItem({ cloud_url: null }))).toBe("/api/media/user%2Fdemo.png")
    expect(libraryItemUrl(libraryItem({ cloud_url: null, path: "" }))).toBe("/api/jobs/j1/download")
  })

  it("hides local, expired and non-media outputs", () => {
    expect(isUsableLibraryItem(libraryItem())).toBe(true)
    expect(isUsableLibraryItem(libraryItem({ kind: "video" }))).toBe(true)
    expect(isUsableLibraryItem(libraryItem({ delivery_status: "local" }))).toBe(false)
    expect(isUsableLibraryItem(libraryItem({ delivery_status: "expired" }))).toBe(false)
    expect(isUsableLibraryItem(libraryItem({ kind: "audio" }))).toBe(false)
    expect(isUsableLibraryItem(libraryItem({
      cloud_url: null, path: "", download_url: null,
    }))).toBe(false)
  })
})

describe("canvas library drag and drop", () => {
  it("round-trips usable assets through the drag payload", () => {
    const decoded = decodeCanvasAssetDrag(encodeCanvasAssetDrag(libraryItem({ job_id: "j1" })))
    expect(decoded).toMatchObject({
      kind: "image",
      path: "user/demo.png",
      label: "分镜 1",
      cloud_url: "https://cdn.example.com/demo.png",
      job_id: "j1",
    })
    expect(CANVAS_ASSET_DRAG_TYPE).toBe("application/x-zly-canvas-asset")
  })

  it("rejects foreign, malformed, expired and unsafe drag payloads", () => {
    expect(decodeCanvasAssetDrag("not-json")).toBeNull()
    expect(decodeCanvasAssetDrag(JSON.stringify({
      source: "other", version: 1, item: libraryItem(),
    }))).toBeNull()
    expect(decodeCanvasAssetDrag(JSON.stringify({
      source: "zly-canvas-library", version: 2, item: libraryItem(),
    }))).toBeNull()
    expect(decodeCanvasAssetDrag(encodeCanvasAssetDrag(libraryItem({ delivery_status: "expired" })))).toBeNull()
    expect(decodeCanvasAssetDrag(JSON.stringify({
      source: "zly-canvas-library", version: 1, item: { ...libraryItem(), kind: "audio" },
    }))).toBeNull()
    expect(decodeCanvasAssetDrag(JSON.stringify({
      source: "zly-canvas-library",
      version: 1,
      item: libraryItem({ cloud_url: "javascript:alert(1)", path: "", download_url: null }),
    }))).toBeNull()
  })

  it("centers dropped nodes on the cursor and keeps asset provenance", () => {
    const image = createLibraryNode(libraryItem({ job_id: "j1" }), { x: 500, y: 300 }, { center: true })
    expect(image).toMatchObject({
      type: "image",
      position: { x: 340, y: 200 },
      style: CANVAS_LIBRARY_NODE_SIZES.image,
      data: {
        mediaKind: "image",
        url: "https://cdn.example.com/demo.png",
        assetPath: "user/demo.png",
        sourceJobId: "j1",
      },
    })

    const video = createLibraryNode(
      libraryItem({ kind: "video", job_id: "j2" }),
      { x: 500, y: 300 },
      { center: true },
    )
    expect(video).toMatchObject({
      type: "video",
      position: { x: 320, y: 190 },
      style: CANVAS_LIBRARY_NODE_SIZES.video,
      data: { mediaKind: "video", sourceJobId: "j2" },
    })
  })

  it("keeps click insert coordinates unchanged and refuses unusable assets", () => {
    expect(createLibraryNode(libraryItem(), { x: 40, y: 60 })?.position).toEqual({ x: 40, y: 60 })
    expect(createLibraryNode(libraryItem({ delivery_status: "local" }), { x: 0, y: 0 })).toBeNull()
    expect(createLibraryNode(libraryItem({
      cloud_url: null, path: "", download_url: null,
    }), { x: 0, y: 0 })).toBeNull()
  })
})

describe("canvas viewport settings", () => {
  it("reads valid viewports and rejects malformed or out-of-range values", () => {
    expect(readCanvasViewport({ viewport: { x: 12, y: -8, zoom: 1.25 } })).toEqual({ x: 12, y: -8, zoom: 1.25 })
    expect(readCanvasViewport(undefined)).toBeNull()
    expect(readCanvasViewport({})).toBeNull()
    expect(readCanvasViewport({ viewport: null })).toBeNull()
    expect(readCanvasViewport({ viewport: { x: 0, y: 0, zoom: 0.01 } })).toBeNull()
    expect(readCanvasViewport({ viewport: { x: 0, y: 0, zoom: 3 } })).toBeNull()
    expect(readCanvasViewport({ viewport: { x: "0", y: 0, zoom: 1 } })).toBeNull()
    expect(readCanvasViewport({ viewport: { x: 0, y: Number.NaN, zoom: 1 } })).toBeNull()
    expect(readCanvasViewport({ viewport: { x: 0, y: 0, zoom: CANVAS_MIN_ZOOM } })).not.toBeNull()
    expect(readCanvasViewport({ viewport: { x: 0, y: 0, zoom: CANVAS_MAX_ZOOM } })).not.toBeNull()
  })

  it("ignores sub-pixel camera noise but detects real moves", () => {
    const base = { x: 100, y: 200, zoom: 1 }
    expect(canvasViewportChanged(null, base)).toBe(true)
    expect(canvasViewportChanged(base, { x: 100.4, y: 200.3, zoom: 1.0005 })).toBe(false)
    expect(canvasViewportChanged(base, { x: 101, y: 200, zoom: 1 })).toBe(true)
    expect(canvasViewportChanged(base, { x: 100, y: 200, zoom: 1.01 })).toBe(true)
  })

  it("fills defaults and sanitizes persisted canvas settings", () => {
    expect(readCanvasSettings(null)).toEqual(DEFAULT_CANVAS_SETTINGS)
    const sanitized = readCanvasSettings({
      viewport: { x: 10, y: 20, zoom: 1.5 },
      connectionMode: "invalid",
      generationDisplayMode: "invalid",
      gridVisible: false,
      minimapVisible: "yes",
      guidesVisible: false,
      globalPrompt: "x".repeat(2100),
    })
    expect(sanitized.viewport).toEqual({ x: 10, y: 20, zoom: 1.5 })
    expect(sanitized.connectionMode).toBe("full")
    expect(sanitized.generationDisplayMode).toBe("aggregate")
    expect(sanitized.gridVisible).toBe(false)
    expect(sanitized.minimapVisible).toBe(true)
    expect(sanitized.guidesVisible).toBe(false)
    expect(sanitized.globalPrompt).toHaveLength(2000)
    expect(sanitized.viewpoints).toHaveLength(CANVAS_VIEWPOINT_COUNT)
  })

  it("reads ten viewpoints and drops malformed slots", () => {
    const viewpoints = readCanvasViewpoints([
      { x: 1, y: 2, zoom: 1 },
      null,
      { x: 0, y: 0, zoom: 9 },
      { x: "0", y: 0, zoom: 1 },
    ])
    expect(viewpoints).toHaveLength(CANVAS_VIEWPOINT_COUNT)
    expect(viewpoints[0]).toEqual({ x: 1, y: 2, zoom: 1 })
    expect(viewpoints.slice(1).every((item) => item === null)).toBe(true)
    expect(readCanvasViewpoints("bad")).toHaveLength(CANVAS_VIEWPOINT_COUNT)
  })
})

describe("canvas node geometry and clipboard", () => {
  it("uses measured size and falls back by node type", () => {
    const measured = layoutNode("a", 0, 0, 200, 100)
    expect(canvasNodeSize(measured)).toEqual({ width: 200, height: 100 })
    expect(canvasNodeSize(createGeneratorNode({ x: 0, y: 0 }))).toEqual({ width: 400, height: 290 })
    expect(canvasNodeSize({ id: "u", type: "unknown", position: { x: 0, y: 0 }, data: {} }))
      .toEqual({ width: 260, height: 150 })
  })

  it("labels every supported node type", () => {
    expect(["text", "image", "video", "artboard", "generator", null].map(canvasNodeTypeLabel))
      .toEqual(["文字", "图片", "视频", "画板", "生成", "未识别"])
  })

  it("places branch nodes to the right or below without overlapping", () => {
    const source = layoutNode("a", 100, 50, 200, 100)
    expect(canvasBranchPosition(source, "right")).toEqual({ x: 364, y: 50 })
    expect(canvasBranchPosition(source, "right", 2)).toEqual({ x: 364, y: 298 })
    expect(canvasBranchPosition(source, "down")).toEqual({ x: 100, y: 214 })
    expect(canvasBranchPosition(source, "down", 1)).toEqual({ x: 324, y: 214 })
  })

  it("copies selected subgraphs and pastes them with fresh ids", () => {
    const nodes = [
      layoutNode("a", 0, 0, 100, 50),
      layoutNode("b", 100, 0, 100, 50),
      layoutNode("c", 200, 0, 100, 50),
    ]
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "b", target: "c" },
    ]
    const clipboard = copyCanvasClipboard(nodes, edges, ["a", "b"])
    expect(clipboard?.nodes.map((item) => item.id)).toEqual(["a", "b"])
    expect(clipboard?.nodes.every((item) => item.selected === false)).toBe(true)
    expect(clipboard?.edges).toHaveLength(1)

    const pasted = pasteCanvasClipboard(clipboard!, 40)
    expect(pasted.nodes.map((item) => item.position)).toEqual([
      { x: 40, y: 40 },
      { x: 140, y: 40 },
    ])
    expect(pasted.nodes[0].id).not.toBe("a")
    expect(pasted.edges).toHaveLength(1)
    expect(pasted.edges[0]).toMatchObject({
      source: pasted.nodes[0].id,
      target: pasted.nodes[1].id,
      selected: false,
    })
    expect(nodes[0].position).toEqual({ x: 0, y: 0 })
    expect(copyCanvasClipboard(nodes, edges, [])).toBeNull()
  })

  it("prefills generator nodes with workflow, prompt and branch direction", () => {
    const node = createGeneratorNode({ x: 0, y: 0 }, {
      prompt: "霓虹街道",
      workflowId: "wf-image",
      optionValues: { ratio: "16:9" },
      mediaKind: "image",
      branchDirection: "down",
    })
    expect(node.data).toMatchObject({
      prompt: "霓虹街道",
      workflowId: "wf-image",
      optionValues: { ratio: "16:9" },
      resultKind: "image",
      branchDirection: "down",
    })
  })
})

describe("canvas selection layout", () => {
  const first = layoutNode("a", 100, 40, 200, 100)
  const second = layoutNode("b", 0, 200, 100, 50)

  it("aligns selected nodes to each edge and center", () => {
    expect(alignCanvasNodes([first, second], "left")).toEqual({
      a: { x: 0, y: 40 },
      b: { x: 0, y: 200 },
    })
    expect(alignCanvasNodes([first, second], "right")).toEqual({
      a: { x: 100, y: 40 },
      b: { x: 200, y: 200 },
    })
    expect(alignCanvasNodes([first, second], "centerX")).toEqual({
      a: { x: 50, y: 40 },
      b: { x: 100, y: 200 },
    })
    expect(alignCanvasNodes([first, second], "top")).toEqual({
      a: { x: 100, y: 40 },
      b: { x: 0, y: 40 },
    })
    expect(alignCanvasNodes([first, second], "bottom")).toEqual({
      a: { x: 100, y: 150 },
      b: { x: 0, y: 200 },
    })
    expect(alignCanvasNodes([first, second], "centerY")).toEqual({
      a: { x: 100, y: 95 },
      b: { x: 0, y: 120 },
    })
    expect(alignCanvasNodes([first], "left")).toEqual({})
  })

  it("uses measured sizes before style and node width/height fallbacks", () => {
    const styled: CanvasNode = {
      id: "styled",
      type: "text",
      position: { x: 10, y: 0 },
      data: {},
      style: { width: 100, height: 40 },
    }
    const measured: CanvasNode = {
      id: "measured",
      type: "text",
      position: { x: 0, y: 100 },
      data: {},
      style: { width: 100, height: 40 },
      measured: { width: 60, height: 20 },
    }
    const direct: CanvasNode = {
      id: "direct",
      type: "text",
      position: { x: 0, y: 0 },
      data: {},
      width: 30,
      height: 10,
    }
    expect(alignCanvasNodes([styled, measured], "right")).toEqual({
      styled: { x: 10, y: 0 },
      measured: { x: 50, y: 100 },
    })
    expect(alignCanvasNodes([styled, direct], "bottom")).toEqual({
      styled: { x: 10, y: 0 },
      direct: { x: 0, y: 30 },
    })
  })

  it("distributes three or more nodes with equal gaps", () => {
    const nodes = [
      layoutNode("a", 0, 0, 100, 50),
      layoutNode("b", 150, 120, 50, 50),
      layoutNode("c", 400, 300, 100, 50),
    ]
    expect(distributeCanvasNodes(nodes, "horizontal")).toEqual({
      a: { x: 0, y: 0 },
      b: { x: 225, y: 120 },
      c: { x: 400, y: 300 },
    })
    expect(distributeCanvasNodes(nodes, "vertical")).toEqual({
      a: { x: 0, y: 0 },
      b: { x: 150, y: 150 },
      c: { x: 400, y: 300 },
    })
    expect(distributeCanvasNodes(nodes.slice(0, 2), "horizontal")).toEqual({})
  })

  it("duplicates selected nodes with an offset and only internal edges", () => {
    const nodes = [
      layoutNode("a", 0, 0, 100, 50),
      layoutNode("b", 100, 0, 100, 50),
      layoutNode("c", 200, 0, 100, 50),
    ]
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "b", target: "c" },
    ]
    const result = duplicateCanvasSelection(nodes, edges, ["a", "b"])
    expect(result.nodes).toHaveLength(2)
    expect(result.nodeIds).toEqual(result.nodes.map((node) => node.id))
    expect(result.nodes.map((node) => node.position)).toEqual([
      { x: 32, y: 32 },
      { x: 132, y: 32 },
    ])
    expect(result.nodes[0].id).not.toBe("a")
    expect(result.nodes[0].selected).toBe(false)
    expect(result.edges).toHaveLength(1)
    expect(result.edges[0]).toMatchObject({
      id: buildEdgeId(result.nodes[0].id, result.nodes[1].id),
      source: result.nodes[0].id,
      target: result.nodes[1].id,
      selected: false,
    })
    expect(nodes[0].position).toEqual({ x: 0, y: 0 })
    expect(duplicateCanvasSelection(nodes, edges, [])).toEqual({ nodes: [], edges: [], nodeIds: [] })
  })
})

describe("canvas branch slots", () => {
  it("skips slots that would overlap existing nodes", () => {
    const source = layoutNode("source", 0, 0, 260, 104)
    const tall = layoutNode("tall", 324, 0, 340, 218)
    expect(nextCanvasBranchSlot(source, "right", [source])).toEqual({ x: 324, y: 0 })
    expect(nextCanvasBranchSlot(source, "right", [source, tall])).toEqual({ x: 324, y: 256 })

    const below = layoutNode("below", 0, 168, 240, 160)
    expect(nextCanvasBranchSlot(source, "down", [source])).toEqual({ x: 0, y: 168 })
    expect(nextCanvasBranchSlot(source, "down", [source, below])).toEqual({ x: 284, y: 168 })
  })
})

describe("canvas free placement", () => {
  it("returns the desired position when it is free", () => {
    const occupied = layoutNode("occupied", 600, 0, 340, 218)
    expect(findCanvasFreePosition({ x: 0, y: 0 }, { width: 340, height: 218 }, [occupied]))
      .toEqual({ x: 0, y: 0 })
  })

  it("steps to a nearby slot when the desired position overlaps", () => {
    const occupied = layoutNode("occupied", 0, 0, 340, 218)
    expect(findCanvasFreePosition({ x: 0, y: 0 }, { width: 340, height: 218 }, [occupied]))
      .toEqual({ x: 364, y: 0 })
  })
})

describe("canvas preview", () => {
  it("reads bounded optional node annotations and remains compatible with old previews", () => {
    const preview = readCanvasPreview({
      x: 0, y: 0, width: 300, height: 200,
      items: [
        { type: "text", x: 0, y: 0, width: 120, height: 80, label: "  开场\n 提示  ", text: "雨".repeat(200) },
        { type: "image", x: 160, y: 0, width: 120, height: 80, label: {}, text: ["bad"] },
      ],
    })
    expect(preview?.items[0].label).toBe("开场 提示")
    expect(preview?.items[0].text).toHaveLength(160)
    expect(preview?.items[1].label).toBeUndefined()
    expect(preview?.items[1].text).toBeUndefined()
  })
  it("reads bounds, nodes, links and safe media urls", () => {
    const preview = readCanvasPreview({
      x: -10,
      y: -20,
      width: 200,
      height: 120,
      nodeCount: 2,
      items: [
        { type: "image", x: -10, y: -20, width: 80, height: 60, url: "/api/media/a.png" },
        { type: "text", x: 20, y: 10, width: 100, height: 60, url: "javascript:alert(1)" },
      ],
      links: [[0, 1], [1, 1], [0, 5], [0, "1"]],
    })
    expect(preview).toEqual({
      x: -10,
      y: -20,
      width: 200,
      height: 120,
      nodeCount: 2,
      items: [
        { type: "image", x: -10, y: -20, width: 80, height: 60, url: "/api/media/a.png" },
        { type: "text", x: 20, y: 10, width: 100, height: 60 },
      ],
      links: [[0, 1]],
    })
  })

  it("rejects malformed geometry and unknown node types", () => {
    expect(readCanvasPreview(null)).toBeNull()
    expect(readCanvasPreview({ items: [] })).toBeNull()
    expect(readCanvasPreview({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      items: [{ type: "image", x: 0, y: 0, width: 0, height: 10 }],
    })).toBeNull()
    expect(readCanvasPreview({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      items: [{ type: "future-node", x: 0, y: 0, width: 10, height: 10 }],
    })).toBeNull()
  })

  it("accepts covers for video items and rejects them elsewhere", () => {
    const cover = "data:image/jpeg;base64," + "A".repeat(120)
    const preview = readCanvasPreview({
      x: 0,
      y: 0,
      width: 400,
      height: 200,
      items: [
        { type: "video", x: 0, y: 0, width: 200, height: 120, cover },
        { type: "image", x: 200, y: 0, width: 200, height: 120, cover },
        { type: "video", x: 0, y: 120, width: 200, height: 80, cover: "data:image/svg+xml;base64,AAAA" },
      ],
    })
    expect(preview?.items[0]?.cover).toBe(cover)
    expect(preview?.items[1]?.cover).toBeUndefined()
    expect(preview?.items[2]?.cover).toBeUndefined()
  })

  it("keeps an offset node layout and fills a missing node count", () => {
    const preview = readCanvasPreview({
      x: 100,
      y: 200,
      width: 600,
      height: 400,
      items: [
        { type: "artboard", x: 100, y: 200, width: 500, height: 300 },
        { type: "generator", x: 650, y: 240, width: 340, height: 240, url: "https://cdn.example/r.png" },
      ],
    })
    expect(preview?.nodeCount).toBe(2)
    expect(preview?.items[1]?.url).toBe("https://cdn.example/r.png")
  })
})

describe("canvas cover-only history", () => {
  const base = JSON.stringify({
    nodes: [{ id: "v", type: "video", position: { x: 0, y: 0 }, data: { url: "/a.mp4", label: "A" } }],
    edges: [],
  })
  const withCover = JSON.stringify({
    nodes: [{
      id: "v",
      type: "video",
      position: { x: 0, y: 0 },
      data: {
        label: "A",
        url: "/a.mp4",
        cover: "data:image/jpeg;base64,AAAA",
        coverSource: "/a.mp4",
        coverTime: 1.2,
      },
    }],
    edges: [],
  })

  it("ignores cover fields in either direction", () => {
    expect(isCoverOnlyCanvasChange(base, withCover)).toBe(true)
    expect(isCoverOnlyCanvasChange(withCover, base)).toBe(true)
  })

  it("does not ignore layout or other data changes", () => {
    const moved = JSON.stringify({
      nodes: [{ id: "v", type: "video", position: { x: 40, y: 0 }, data: { url: "/a.mp4", label: "A" } }],
      edges: [],
    })
    const relabeled = JSON.stringify({
      nodes: [{ id: "v", type: "video", position: { x: 0, y: 0 }, data: { url: "/a.mp4", label: "B" } }],
      edges: [],
    })
    expect(isCoverOnlyCanvasChange(base, moved)).toBe(false)
    expect(isCoverOnlyCanvasChange(base, relabeled)).toBe(false)
    expect(isCoverOnlyCanvasChange(base, "not-json")).toBe(false)
  })
})

describe("canvas undo history", () => {
  it("pushes, undoes and redoes snapshots", () => {
    let history = createCanvasHistory("v1")
    history = pushCanvasHistory(history, "v2")
    history = pushCanvasHistory(history, "v3")
    expect(canvasHistoryState(history)).toEqual({ canUndo: true, canRedo: false })
    history = undoCanvasHistory(history)
    expect(history.entries[history.index]).toBe("v2")
    expect(canvasHistoryState(history)).toEqual({ canUndo: true, canRedo: true })
    history = redoCanvasHistory(history)
    expect(history.entries[history.index]).toBe("v3")
  })

  it("ignores duplicate snapshots and drops the redo branch on a new change", () => {
    let history = createCanvasHistory("v1")
    history = pushCanvasHistory(history, "v2")
    const unchanged = pushCanvasHistory(history, "v2")
    expect(unchanged).toBe(history)
    history = undoCanvasHistory(history)
    history = pushCanvasHistory(history, "v3")
    expect(history.entries).toEqual(["v1", "v3"])
    expect(canvasHistoryState(history).canRedo).toBe(false)
  })

  it("caps retained snapshots while keeping the newest entry current", () => {
    let history = createCanvasHistory("v0")
    for (let index = 1; index <= 5; index += 1) {
      history = pushCanvasHistory(history, `v${index}`, 3)
    }
    expect(history.entries).toEqual(["v3", "v4", "v5"])
    expect(history.index).toBe(2)
  })
})
