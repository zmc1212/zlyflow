import { describe, expect, it } from "vitest"
import {
  createImageNode,
  createTextNode,
  serializeCanvasDraft,
  type CanvasLibraryItem,
  type CanvasProject,
} from "./canvas-model"
import {
  CANVAS_IMPORT_MAX_BYTES,
  CANVAS_IMPORT_MAX_EDGES,
  CANVAS_IMPORT_MAX_NODES,
  CANVAS_LIBRARY_PAGE_SIZE,
  canvasAssetInsertSearch,
  canvasCopyTitle,
  canvasExportFileName,
  canvasLibraryItemKey,
  canvasLibraryQueryString,
  collectCanvasTags,
  filterCanvasProjects,
  findCanvasInsertLibraryItem,
  mergeCanvasLibraryItems,
  normalizeCanvasTags,
  parseCanvasImportContent,
  readCanvasAssetInsert,
} from "./canvas-manage"

function project(overrides: Partial<CanvasProject>): CanvasProject {
  return {
    id: "canvas_1",
    title: "分镜草稿",
    created_at: "2026-10-20T08:00:00Z",
    updated_at: "2026-10-20T08:00:00Z",
    ...overrides,
  }
}

function libraryItem(overrides: Partial<CanvasLibraryItem> = {}): CanvasLibraryItem {
  return {
    kind: "image",
    path: "user/demo.png",
    label: "分镜 1",
    delivery_status: "cloud",
    download_url: "/api/jobs/j1/outputs/0/download",
    cloud_url: "https://cdn.example.com/demo.png",
    job_id: "job_1",
    output_index: 0,
    created_at: "2026-10-21T00:00:00Z",
    ...overrides,
  }
}

function params(entries: Record<string, string>): URLSearchParams {
  return new URLSearchParams(entries)
}

describe("canvas management", () => {
  it("filters canvas projects by title and sorts by update time", () => {
    const projects = [
      project({ id: "a", title: "雨夜追车", draft_updated_at: "2026-10-21T10:00:00Z" }),
      project({ id: "b", title: "室内对话", draft_updated_at: "2026-10-22T10:00:00Z" }),
      project({ id: "c", title: "雨夜霓虹", updated_at: "2026-10-20T10:00:00Z" }),
    ]
    expect(filterCanvasProjects(projects, "", "updated_desc").map((item) => item.id)).toEqual(["b", "a", "c"])
    expect(filterCanvasProjects(projects, "雨夜", "updated_desc").map((item) => item.id)).toEqual(["a", "c"])
    expect(filterCanvasProjects(projects, " 雨夜 ", "updated_desc")).toHaveLength(2)
    expect(filterCanvasProjects(projects, "不存在", "updated_desc")).toEqual([])
  })

  it("sorts by creation time or title and keeps the input array intact", () => {
    const projects = [
      project({ id: "a", title: "B 画布", created_at: "2026-10-22T00:00:00Z" }),
      project({ id: "b", title: "A 画布", created_at: "2026-10-20T00:00:00Z" }),
    ]
    const original = projects.map((item) => item.id)
    expect(filterCanvasProjects(projects, "", "created_desc").map((item) => item.id)).toEqual(["a", "b"])
    expect(filterCanvasProjects(projects, "", "title_asc").map((item) => item.title)).toEqual(["A 画布", "B 画布"])
    expect(projects.map((item) => item.id)).toEqual(original)
  })

  it("filters by tags, searches tags and pins favorites first", () => {
    const projects = [
      project({ id: "a", title: "雨夜追车", tags: ["分镜", "雨夜"], draft_updated_at: "2026-10-21T10:00:00Z" }),
      project({ id: "b", title: "室内对话", tags: ["对话"], is_favorite: true, draft_updated_at: "2026-10-20T10:00:00Z" }),
      project({ id: "c", title: "雨夜霓虹", tags: ["分镜"], draft_updated_at: "2026-10-22T10:00:00Z" }),
    ]
    expect(filterCanvasProjects(projects, "", "updated_desc").map((item) => item.id)).toEqual(["b", "c", "a"])
    expect(filterCanvasProjects(projects, "", "updated_desc", { tag: "分镜" }).map((item) => item.id)).toEqual(["c", "a"])
    expect(filterCanvasProjects(projects, "", "updated_desc", { favoriteOnly: true }).map((item) => item.id)).toEqual(["b"])
    expect(filterCanvasProjects(projects, "对话", "updated_desc").map((item) => item.id)).toEqual(["b"])
    const tags = collectCanvasTags(projects)
    expect(tags).toHaveLength(3)
    expect(tags).toEqual(expect.arrayContaining(["分镜", "雨夜", "对话"]))
  })

  it("normalizes and bounds canvas tags", () => {
    expect(normalizeCanvasTags([" 分镜 ", "雨夜", "分镜", "  "])).toEqual({ tags: ["分镜", "雨夜"], error: null })
    expect(normalizeCanvasTags(["长".repeat(25)]).error).toContain("24")
    const tooMany = normalizeCanvasTags(Array.from({ length: 9 }, (_, index) => `标签${index}`))
    expect(tooMany.tags).toHaveLength(8)
    expect(tooMany.error).toContain("8")
  })

  it("builds a bounded copy title", () => {
    expect(canvasCopyTitle("第一集分镜")).toBe("第一集分镜 副本")
    expect(canvasCopyTitle("   ")).toBe("未命名画布 副本")
    const long = canvasCopyTitle("长".repeat(200))
    expect(long.endsWith(" 副本")).toBe(true)
    expect(long.length).toBe(120)
  })

  it("reads valid asset insert parameters and rejects malformed values", () => {
    expect(readCanvasAssetInsert(params({ addJob: "job_1", addOutput: "2" }))).toEqual({
      jobId: "job_1",
      generationItemId: null,
      outputIndex: 2,
      key: "job_1::2",
    })
    expect(readCanvasAssetInsert(params({ addJob: "job_1", addItem: "item_1", addOutput: "2" }))).toEqual({
      jobId: "job_1",
      generationItemId: "item_1",
      outputIndex: 2,
      key: "job_1:item_1:2",
    })
    expect(readCanvasAssetInsert(params({ addJob: "job_1" }))).toBeNull()
    expect(readCanvasAssetInsert(params({ addJob: "", addOutput: "0" }))).toBeNull()
    expect(readCanvasAssetInsert(params({ addJob: "job_1", addOutput: "-1" }))).toBeNull()
    expect(readCanvasAssetInsert(params({ addJob: "job_1", addOutput: "1.5" }))).toBeNull()
    expect(readCanvasAssetInsert(params({ addJob: "job_1", addOutput: "9999" }))).toBeNull()
  })

  it("builds insert query strings that round-trip through the reader", () => {
    const query = canvasAssetInsertSearch({ jobId: "job_1", generationItemId: "item_1", outputIndex: 3 })
    expect(readCanvasAssetInsert(new URLSearchParams(query))).toEqual({
      jobId: "job_1",
      generationItemId: "item_1",
      outputIndex: 3,
      key: "job_1:item_1:3",
    })
  })

  it("matches a usable library item for insertion and rejects unsafe entries", () => {
    const request = readCanvasAssetInsert(params({ addJob: "job_1", addOutput: "0" }))
    expect(request).not.toBeNull()
    expect(findCanvasInsertLibraryItem([libraryItem()], request!)).toMatchObject({ job_id: "job_1", output_index: 0 })
    expect(findCanvasInsertLibraryItem([libraryItem({ output_index: 1 })], request!)).toBeNull()
    expect(findCanvasInsertLibraryItem([libraryItem({ delivery_status: "expired" })], request!)).toBeNull()
    expect(findCanvasInsertLibraryItem([libraryItem({ delivery_status: "local" })], request!)).toBeNull()
    expect(findCanvasInsertLibraryItem([libraryItem({ cloud_url: "javascript:alert(1)", download_url: null })], request!)).toBeNull()

    const itemRequest = readCanvasAssetInsert(params({ addJob: "job_1", addItem: "item_1", addOutput: "0" }))
    expect(findCanvasInsertLibraryItem([libraryItem()], itemRequest!)).toBeNull()
    expect(findCanvasInsertLibraryItem([libraryItem({ generation_item_id: "item_1" })], itemRequest!)).not.toBeNull()
  })

  it("imports a serialized canvas with settings, edges and unknown nodes", () => {
    const nodes = [createTextNode({ x: 10, y: 20 }, "开场"), createImageNode({ x: 300, y: 20 }, "https://cdn.example.com/a.png")]
    nodes.push({
      id: "future_1",
      type: "future-node",
      position: { x: 0, y: 0 },
      data: { originalType: "future-node" },
    })
    const edges = [{ id: "e1", source: nodes[0].id, target: nodes[1].id }]
    const content = serializeCanvasDraft(nodes, edges, {
      canvasSettings: { globalPrompt: "雨夜", connectionMode: "compact" },
    })
    const result = parseCanvasImportContent(content)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.nodeCount).toBe(3)
    expect(result.edgeCount).toBe(1)
    expect(result.draft.nodes.find((node) => node.type === "unknown")?.data.originalType).toBe("future-node")
    expect(result.draft.canvasSettings?.globalPrompt).toBe("雨夜")
  })

  it("rejects malformed or unsafe import content before applying it", () => {
    const empty = { nodes: [], edges: [] }
    expect(parseCanvasImportContent("")).toMatchObject({ ok: false })
    expect(parseCanvasImportContent("not-json")).toMatchObject({ ok: false, error: "文件不是合法的 JSON" })
    expect(parseCanvasImportContent(JSON.stringify({ nodes: [] }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({ ...empty, schemaVersion: 0 }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({ ...empty, nodes: [{ id: "a", type: "text", position: { x: null, y: 0 } }] })))
      .toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      ...empty,
      nodes: [
        { id: "a", type: "text", position: { x: 0, y: 0 } },
        { id: "a", type: "text", position: { x: 10, y: 0 } },
      ],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      ...empty,
      nodes: [{ id: "a", type: "video", position: { x: 0, y: 0 }, data: { url: "data:video/mp4;base64,AAAA" } }],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      ...empty,
      nodes: [{ id: "a", type: "image", position: { x: 0, y: 0 }, data: { url: "javascript:alert(1)" } }],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      ...empty,
      nodes: [{ id: "a", type: "generator", position: { x: 0, y: 0 }, data: { resultHistory: [{ url: "file:///tmp/a.png" }] } }],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      ...empty,
      edges: [{ source: "a", target: "b" }],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [],
      edges: [],
      canvasSettings: "bad",
    }))).toMatchObject({ ok: false })
  })

  it("enforces the import limits for size and counts", () => {
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [],
      edges: [],
      padding: "x".repeat(CANVAS_IMPORT_MAX_BYTES),
    }))).toMatchObject({ ok: false, error: "画布 JSON 超过 8 MB 上限，无法导入" })
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: Array.from({ length: CANVAS_IMPORT_MAX_NODES + 1 }, () => ({})),
      edges: [],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [],
      edges: Array.from({ length: CANVAS_IMPORT_MAX_EDGES + 1 }, () => ({})),
    }))).toMatchObject({ ok: false })
  })

  it("accepts image data URLs and rejects a self-loop edge", () => {
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [{ id: "a", type: "image", position: { x: 0, y: 0 }, data: { url: "data:image/png;base64,AAAA" } }],
      edges: [],
    }))).toMatchObject({ ok: true })
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [{ id: "a", type: "text", position: { x: 0, y: 0 } }],
      edges: [{ source: "a", target: "a" }],
    }))).toMatchObject({ ok: false })
    expect(parseCanvasImportContent(JSON.stringify({
      nodes: [{ id: "v1", type: "video", position: { x: 0, y: 0 }, data: { url: "/api/media/demo.mp4" } }],
      edges: [],
    }))).toMatchObject({ ok: true })
  })

  it("creates a safe export filename", () => {
    expect(canvasExportFileName("第一集 / 分镜:\"草稿\"", new Date(2026, 9, 22, 9, 5)))
      .toBe("第一集_分镜_草稿_-20261022-0905.canvas.json")
    expect(canvasExportFileName("   ", new Date(2026, 0, 2, 3, 4))).toBe("canvas-20260102-0304.canvas.json")
  })

  it("imports a blank canvas", () => {
    expect(parseCanvasImportContent(JSON.stringify({ nodes: [], edges: [] }))).toMatchObject({
      ok: true,
      nodeCount: 0,
      edgeCount: 0,
    })
  })

  it("rejects structured display fields instead of accepting a canvas that crashes on render", () => {
    for (const data of [{ label: { bad: true } }, { text: ["bad"] }, { url: 42 }, { prompt: {} }]) {
      const content = JSON.stringify({ nodes: [{ id: "a", type: "text", position: { x: 0, y: 0 }, data }], edges: [] })
      expect(parseCanvasImportContent(content)).toMatchObject({ ok: false })
    }
  })

  it("builds bounded library query strings", () => {
    const defaults = new URLSearchParams(canvasLibraryQueryString())
    expect(defaults.get("limit")).toBe(String(CANVAS_LIBRARY_PAGE_SIZE))
    expect(defaults.get("offset")).toBe("0")
    expect(defaults.has("q")).toBe(false)
    expect(defaults.has("kind")).toBe(false)

    const query = new URLSearchParams(canvasLibraryQueryString({
      q: "  雨夜 霓虹  ",
      kind: "video",
      limit: 999,
      offset: -4,
      jobId: " job_1 ",
      generationItemId: "item_1",
      outputIndex: 0,
    }))
    expect(query.get("q")).toBe("雨夜 霓虹")
    expect(query.get("kind")).toBe("video")
    expect(query.get("limit")).toBe("100")
    expect(query.get("offset")).toBe("0")
    expect(query.get("job_id")).toBe("job_1")
    expect(query.get("generation_item_id")).toBe("item_1")
    expect(query.get("output_index")).toBe("0")

    const longSearch = new URLSearchParams(canvasLibraryQueryString({ q: "长".repeat(160) }))
    expect(longSearch.get("q")).toHaveLength(100)
    const invalidIndex = new URLSearchParams(canvasLibraryQueryString({ outputIndex: -1 }))
    expect(invalidIndex.has("output_index")).toBe(false)
    const fractionalIndex = new URLSearchParams(canvasLibraryQueryString({ outputIndex: 1.5 }))
    expect(fractionalIndex.has("output_index")).toBe(false)
  })

  it("merges paged library items without duplicates", () => {
    const first = libraryItem()
    const second = libraryItem({ path: "user/second.png", output_index: 1 })
    const duplicate = libraryItem({ cloud_url: "https://cdn.example.com/other.png" })
    const third = libraryItem({ job_id: "job_2", path: "user/third.png" })

    expect(canvasLibraryItemKey(first)).toBe("job_1:item:0:user/demo.png")
    expect(mergeCanvasLibraryItems([], [first, second])).toEqual([first, second])
    expect(mergeCanvasLibraryItems([first, second], [duplicate, third])).toEqual([first, second, third])
    expect(mergeCanvasLibraryItems([first], [first, first])).toEqual([first])
  })
})
