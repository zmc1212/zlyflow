import {
  isSafeMediaUrl,
  isUsableLibraryItem,
  libraryItemUrl,
  parseCanvasContent,
  type CanvasDraft,
  type CanvasLibraryItem,
  type CanvasMediaKind,
  type CanvasNode,
  type CanvasProject,
} from "./canvas-model"

export const CANVAS_IMPORT_MAX_BYTES = 8 * 1024 * 1024
export const CANVAS_IMPORT_MAX_NODES = 3000
export const CANVAS_IMPORT_MAX_EDGES = 6000
export const CANVAS_INSERT_JOB_PARAM = "addJob"
export const CANVAS_INSERT_ITEM_PARAM = "addItem"
export const CANVAS_INSERT_OUTPUT_PARAM = "addOutput"

export type CanvasProjectSort = "updated_desc" | "created_desc" | "title_asc"

export type CanvasProjectFilter = {
  favoriteOnly?: boolean
  tag?: string | null
}

export const CANVAS_MAX_TAGS = 8
export const CANVAS_MAX_TAG_LENGTH = 24

export function collectCanvasTags(projects: CanvasProject[]): string[] {
  const tags = new Set<string>()
  for (const project of projects) {
    for (const tag of project.tags ?? []) tags.add(tag)
  }
  return [...tags].sort((left, right) => left.localeCompare(right, "zh-CN"))
}

export function normalizeCanvasTags(tags: string[]): { tags: string[]; error: string | null } {
  const normalized: string[] = []
  for (const raw of tags) {
    const tag = raw.trim()
    if (!tag) continue
    if (tag.length > CANVAS_MAX_TAG_LENGTH) {
      return { tags: normalized, error: `单个标签不能超过 ${CANVAS_MAX_TAG_LENGTH} 个字符` }
    }
    if (!normalized.includes(tag)) normalized.push(tag)
  }
  if (normalized.length > CANVAS_MAX_TAGS) {
    return { tags: normalized.slice(0, CANVAS_MAX_TAGS), error: `标签不能超过 ${CANVAS_MAX_TAGS} 个` }
  }
  return { tags: normalized, error: null }
}

function projectTimestamp(value?: string | null): number {
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function projectUpdatedAt(project: CanvasProject): number {
  return projectTimestamp(project.draft_updated_at) || projectTimestamp(project.updated_at)
}

export function filterCanvasProjects(
  projects: CanvasProject[],
  query: string,
  sort: CanvasProjectSort,
  filter: CanvasProjectFilter = {},
): CanvasProject[] {
  const keyword = query.trim().toLocaleLowerCase()
  const tag = filter.tag?.trim() ?? ""
  const filtered = projects.filter((project) => {
    const tags = project.tags ?? []
    if (filter.favoriteOnly && !project.is_favorite) return false
    if (tag && !tags.includes(tag)) return false
    if (!keyword) return true
    return project.title.toLocaleLowerCase().includes(keyword)
      || tags.some((item) => item.toLocaleLowerCase().includes(keyword))
  })
  return filtered.sort((left, right) => {
    const favoriteDiff = Number(Boolean(right.is_favorite)) - Number(Boolean(left.is_favorite))
    if (favoriteDiff !== 0) return favoriteDiff
    if (sort === "title_asc") {
      return left.title.localeCompare(right.title, "zh-CN")
    }
    if (sort === "created_desc") {
      return projectTimestamp(right.created_at) - projectTimestamp(left.created_at)
    }
    return projectUpdatedAt(right) - projectUpdatedAt(left)
  })
}

export function canvasCopyTitle(title: string): string {
  const base = title.trim() || "未命名画布"
  const suffix = " 副本"
  return `${base.slice(0, Math.max(1, 120 - suffix.length))}${suffix}`
}

export type CanvasAssetInsertRequest = {
  jobId: string
  generationItemId: string | null
  outputIndex: number
  key: string
}

export function canvasAssetInsertSearch(request: {
  jobId: string
  generationItemId?: string | null
  outputIndex: number
}): string {
  const params = new URLSearchParams()
  params.set(CANVAS_INSERT_JOB_PARAM, request.jobId)
  if (request.generationItemId) params.set(CANVAS_INSERT_ITEM_PARAM, request.generationItemId)
  params.set(CANVAS_INSERT_OUTPUT_PARAM, String(request.outputIndex))
  return params.toString()
}

export function readCanvasAssetInsert(params: Pick<URLSearchParams, "get">): CanvasAssetInsertRequest | null {
  const jobId = params.get(CANVAS_INSERT_JOB_PARAM)?.trim()
  const rawIndex = params.get(CANVAS_INSERT_OUTPUT_PARAM)?.trim()
  if (!jobId || !rawIndex || !/^\d+$/.test(rawIndex)) return null
  const outputIndex = Number(rawIndex)
  if (!Number.isSafeInteger(outputIndex) || outputIndex < 0 || outputIndex > 999) return null
  const generationItemId = params.get(CANVAS_INSERT_ITEM_PARAM)?.trim() || null
  return {
    jobId,
    generationItemId,
    outputIndex,
    key: `${jobId}:${generationItemId ?? ""}:${outputIndex}`,
  }
}

export function findCanvasInsertLibraryItem(
  items: CanvasLibraryItem[],
  request: CanvasAssetInsertRequest,
): CanvasLibraryItem | null {
  const item = items.find((entry) => (
    entry.job_id === request.jobId
    && entry.output_index === request.outputIndex
    && (!request.generationItemId || entry.generation_item_id === request.generationItemId)
  ))
  if (!item || !isUsableLibraryItem(item)) return null
  const kind = item.kind === "video" ? "video" : "image"
  return isSafeMediaUrl(libraryItemUrl(item), kind) ? item : null
}

export const CANVAS_LIBRARY_PAGE_SIZE = 40
export const CANVAS_LIBRARY_MAX_SEARCH = 100

export type CanvasLibraryQuery = {
  q?: string
  kind?: CanvasMediaKind
  limit?: number
  offset?: number
  jobId?: string | null
  generationItemId?: string | null
  outputIndex?: number | null
}

export function canvasLibraryQueryString(query: CanvasLibraryQuery = {}): string {
  const params = new URLSearchParams()
  const q = (query.q ?? "").trim().slice(0, CANVAS_LIBRARY_MAX_SEARCH)
  if (q) params.set("q", q)
  if (query.kind === "image" || query.kind === "video") params.set("kind", query.kind)
  const limit = Math.max(1, Math.min(100, Math.trunc(query.limit ?? CANVAS_LIBRARY_PAGE_SIZE)))
  const offset = Math.max(0, Math.trunc(query.offset ?? 0))
  params.set("limit", String(limit))
  params.set("offset", String(offset))
  const jobId = (query.jobId ?? "").trim()
  if (jobId) params.set("job_id", jobId)
  const generationItemId = (query.generationItemId ?? "").trim()
  if (generationItemId) params.set("generation_item_id", generationItemId)
  if (
    typeof query.outputIndex === "number"
    && Number.isSafeInteger(query.outputIndex)
    && query.outputIndex >= 0
  ) {
    params.set("output_index", String(query.outputIndex))
  }
  return params.toString()
}

export function canvasLibraryItemKey(item: CanvasLibraryItem): string {
  return `${item.job_id ?? "file"}:${item.generation_item_id ?? "item"}:${item.output_index ?? 0}:${item.path}`
}

export function mergeCanvasLibraryItems(
  current: CanvasLibraryItem[],
  incoming: CanvasLibraryItem[],
): CanvasLibraryItem[] {
  const seen = new Set(current.map(canvasLibraryItemKey))
  const merged = [...current]
  for (const item of incoming) {
    const key = canvasLibraryItemKey(item)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

export type CanvasImportResult =
  | { ok: true; draft: CanvasDraft; nodeCount: number; edgeCount: number; bytes: number }
  | { ok: false; error: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function invalidMediaUrl(node: CanvasNode, index: number): string | null {
  const data = isRecord(node.data) ? node.data : {}
  if (node.type === "image" || node.type === "video") {
    const url = data.url
    if (typeof url === "string" && url.trim() && !isSafeMediaUrl(url, node.type)) {
      return `第 ${index + 1} 个${node.type === "video" ? "视频" : "图片"}节点的地址协议不受支持`
    }
  }
  if (node.type === "generator") {
    const resultKind = data.resultKind === "video" ? "video" : "image"
    const resultUrl = data.resultUrl
    if (typeof resultUrl === "string" && resultUrl.trim() && !isSafeMediaUrl(resultUrl, resultKind)) {
      return `第 ${index + 1} 个生成节点的结果地址协议不受支持`
    }
    const history = data.resultHistory
    if (Array.isArray(history)) {
      for (const entry of history) {
        if (!isRecord(entry)) continue
        const url = entry.url
        if (typeof url === "string" && url.trim() && !isSafeMediaUrl(url, entry.kind === "video" ? "video" : "image")) {
          return `第 ${index + 1} 个生成节点的结果版本地址协议不受支持`
        }
      }
    }
  }
  return null
}

export function parseCanvasImportContent(raw: string): CanvasImportResult {
  const content = raw.replace(/^\uFEFF/, "")
  if (!content.trim()) return { ok: false, error: "文件内容为空，无法导入" }
  const bytes = new TextEncoder().encode(content).length
  if (bytes > CANVAS_IMPORT_MAX_BYTES) {
    return { ok: false, error: "画布 JSON 超过 8 MB 上限，无法导入" }
  }
  let payload: unknown
  try {
    payload = JSON.parse(content)
  } catch {
    return { ok: false, error: "文件不是合法的 JSON" }
  }
  if (!isRecord(payload)) return { ok: false, error: "画布 JSON 必须是对象" }
  if ("schemaVersion" in payload && (!Number.isInteger(payload.schemaVersion) || Number(payload.schemaVersion) < 1)) {
    return { ok: false, error: "画布 schemaVersion 无效" }
  }
  if ("canvasSettings" in payload && payload.canvasSettings != null && !isRecord(payload.canvasSettings)) {
    return { ok: false, error: "画布设置格式无效" }
  }
  if (!Array.isArray(payload.nodes) || !Array.isArray(payload.edges)) {
    return { ok: false, error: "画布 JSON 缺少 nodes 或 edges 数组" }
  }
  if (payload.nodes.length > CANVAS_IMPORT_MAX_NODES) {
    return { ok: false, error: `节点数量超过 ${CANVAS_IMPORT_MAX_NODES} 个上限` }
  }
  if (payload.edges.length > CANVAS_IMPORT_MAX_EDGES) {
    return { ok: false, error: `连线数量超过 ${CANVAS_IMPORT_MAX_EDGES} 条上限` }
  }

  const nodeIds = new Set<string>()
  for (let index = 0; index < payload.nodes.length; index += 1) {
    const node = payload.nodes[index]
    if (!isRecord(node)) return { ok: false, error: `第 ${index + 1} 个节点格式无效` }
    if (typeof node.id !== "string" || !node.id.trim()) {
      return { ok: false, error: `第 ${index + 1} 个节点缺少有效 id` }
    }
    if (nodeIds.has(node.id)) return { ok: false, error: `节点 id 重复：${node.id}` }
    nodeIds.add(node.id)
    if (typeof node.type !== "string" || !node.type.trim()) {
      return { ok: false, error: `第 ${index + 1} 个节点缺少 type` }
    }
    if (!isRecord(node.position)
      || typeof node.position.x !== "number" || !Number.isFinite(node.position.x)
      || typeof node.position.y !== "number" || !Number.isFinite(node.position.y)) {
      return { ok: false, error: `第 ${index + 1} 个节点的坐标无效` }
    }
    if ("data" in node && node.data != null && !isRecord(node.data)) {
      return { ok: false, error: `第 ${index + 1} 个节点的 data 格式无效` }
    }
    if (isRecord(node.data)) {
      for (const key of ["label", "text", "url", "caption", "prompt", "workflowId", "originalType"]) {
        if (key in node.data && node.data[key] !== undefined && typeof node.data[key] !== "string") {
          return { ok: false, error: `第 ${index + 1} 个节点的 ${key} 必须是文本` }
        }
      }
    }
    const urlError = invalidMediaUrl(node as unknown as CanvasNode, index)
    if (urlError) return { ok: false, error: urlError }
  }

  for (let index = 0; index < payload.edges.length; index += 1) {
    const edge = payload.edges[index]
    if (!isRecord(edge)) return { ok: false, error: `第 ${index + 1} 条连线格式无效` }
    if (typeof edge.source !== "string" || typeof edge.target !== "string") {
      return { ok: false, error: `第 ${index + 1} 条连线缺少 source 或 target` }
    }
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      return { ok: false, error: `第 ${index + 1} 条连线指向不存在的节点` }
    }
    if (edge.source === edge.target) {
      return { ok: false, error: `第 ${index + 1} 条连线的两端相同` }
    }
  }

  const draft = parseCanvasContent(content)
  return { ok: true, draft, nodeCount: draft.nodes.length, edgeCount: draft.edges.length, bytes }
}

export function canvasExportFileName(title: string, date = new Date()): string {
  const safeTitle = title.trim().replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 60) || "canvas"
  const pad = (value: number) => String(value).padStart(2, "0")
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`
  return `${safeTitle}-${stamp}.canvas.json`
}
