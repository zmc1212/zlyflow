import { notifyUnauthorized, requestJson } from "../api"
import { fileFromReferenceBlob } from "../reference-assets"
import type { CanvasEdge, CanvasNode, CanvasResultVersion, CanvasRunSnapshot } from "./canvas-model"

export type CanvasOptionVisibility = "primary" | "advanced" | "internal"

export type CanvasOptionDefinition = {
  label: string
  type: "string" | "number" | "integer" | "boolean"
  default: string | number | boolean
  enum?: (string | number)[]
  minimum?: number
  maximum?: number
  step?: number
  pattern?: string
  description?: string
  unit?: string
  ui_group?: CanvasOptionVisibility
  ui_control?: string
  ui_options?: { value: string | number; label: string; hint?: string }[]
  ui_visible_when?: Record<string, string | number | boolean>
}

export type CanvasOptionValue = string | number | boolean

/** The card selector and inspector must reset the same workflow-dependent state. */
export function canvasWorkflowChangePatch(workflowId: string, mode: CanvasWorkflowMode | null): Partial<CanvasNode["data"]> {
  return {
    workflowId,
    optionValues: defaultGeneratorOptionValues(mode),
    jobId: null,
    jobStatus: null,
    jobError: null,
    resultUrl: null,
    resultKind: mode?.media_type,
    resultPath: null,
    resultHistory: [],
    resultIndex: -1,
  }
}

export type CanvasWorkflowParameter = {
  name: string
  schema?: { properties?: Record<string, CanvasOptionDefinition> } | null
}

export type CanvasWorkflowMode = {
  id: string
  name: string
  description?: string
  media_type: "image" | "video"
  executor?: string
  reference_mode?: "none" | "keyframes" | "collection" | "fixed"
  min_references?: number
  max_references?: number
  reference_labels?: string[]
  reference_slots?: ("image" | "video" | "audio")[]
  accepts_video_reference?: boolean
  accepts_audio_reference?: boolean
  default_prompt?: string | null
  accepts_negative_prompt?: boolean
  accepts_image_size?: boolean
  available?: boolean
  unavailable_reason?: string | null
  catalog_group?: string
  catalog_group_label?: string
  catalog_group_order?: number
  is_default?: boolean
  credit_cost?: number | null
  parameters?: CanvasWorkflowParameter[]
}

export type CanvasModesPayload = { modes: CanvasWorkflowMode[] }

export type CanvasJobOutput = {
  render_pass?: "preview" | "final"
  path?: string
  kind?: string
  label?: string
  delivery_status?: string
  download_url?: string | null
  cloud_url?: string | null
}

export type CanvasJobItem = {
  id?: string
  status?: string
  stage?: string
  progress?: number
  outputs?: CanvasJobOutput[]
  error?: string | null
}

export type CanvasJobRound = {
  generation_items?: CanvasJobItem[]
}

export type CanvasJob = {
  id: string
  media_type: "image" | "video"
  status: string
  stage?: string
  progress?: number
  error?: string | null
  outputs?: CanvasJobOutput[]
  rounds?: CanvasJobRound[]
}

export type CanvasGeneratorLive = {
  jobId: string
  status: string
  stage?: string
  progress?: number
  error?: string | null
  result?: CanvasJobResult | null
  results?: CanvasJobResult[]
  completedCount?: number
  requestedCount?: number
  updatedAt: number
}

export type CanvasJobResult = {
  url: string
  kind: "image" | "video"
  path?: string
  label?: string
}

export function canvasWorkflowList(modes: CanvasWorkflowMode[]): CanvasWorkflowMode[] {
  return modes
    .filter((mode) => mode.available !== false && (mode.media_type === "image" || mode.media_type === "video"))
    .sort((left, right) => (
      (left.catalog_group_order ?? 100) - (right.catalog_group_order ?? 100)
      || left.name.localeCompare(right.name, "zh-CN")
    ))
}

export function pickCanvasGenerationMode(
  modes: CanvasWorkflowMode[],
  referenceCount: number,
): CanvasWorkflowMode | null {
  const available = canvasWorkflowList(modes)
  if (!available.length) return null
  const usable = available.filter((mode) => (
    referenceCount >= (mode.min_references ?? 0) && referenceCount <= (mode.max_references ?? 0)
  ))
  if (!usable.length) return available[0]
  if (referenceCount === 0) return usable.find((mode) => mode.reference_mode === "none") ?? usable[0]
  if (referenceCount <= 2) {
    return usable.find((mode) => mode.reference_mode === "keyframes")
      ?? usable.find((mode) => mode.reference_mode === "collection")
      ?? usable[0]
  }
  return usable.find((mode) => mode.reference_mode === "collection") ?? usable[0]
}

export function canvasModeOptionDefinitions(
  mode: CanvasWorkflowMode | null | undefined,
): Record<string, CanvasOptionDefinition> {
  const parameter = mode?.parameters?.find((item) => item.name === "options")
  return parameter?.schema?.properties ?? {}
}

export function canvasOptionVisible(
  definition: CanvasOptionDefinition,
  values: Record<string, CanvasOptionValue>,
): boolean {
  const condition = definition.ui_visible_when
  if (!condition) return true
  return Object.entries(condition).every(([name, expected]) => String(values[name]) === String(expected))
}

export function defaultGeneratorOptionValues(
  mode: CanvasWorkflowMode | null | undefined,
): Record<string, CanvasOptionValue> {
  const values: Record<string, CanvasOptionValue> = {}
  for (const [name, definition] of Object.entries(canvasModeOptionDefinitions(mode))) {
    if ((definition.ui_group ?? "internal") === "internal") continue
    if (definition.default !== undefined) values[name] = definition.default
  }
  return values
}

export function generatorOptionValues(
  mode: CanvasWorkflowMode | null | undefined,
  stored: Record<string, CanvasOptionValue> | null | undefined,
): Record<string, CanvasOptionValue> {
  const definitions = canvasModeOptionDefinitions(mode)
  const values = defaultGeneratorOptionValues(mode)
  for (const [name, value] of Object.entries(stored ?? {})) {
    if (definitions[name] && (definitions[name].ui_group ?? "internal") !== "internal") values[name] = value
  }
  return values
}

export function generatorParameterFields(
  mode: CanvasWorkflowMode | null | undefined,
  values: Record<string, CanvasOptionValue>,
): {
  primary: Array<[string, CanvasOptionDefinition]>
  advanced: Array<[string, CanvasOptionDefinition]>
} {
  const primary: Array<[string, CanvasOptionDefinition]> = []
  const advanced: Array<[string, CanvasOptionDefinition]> = []
  for (const [name, definition] of Object.entries(canvasModeOptionDefinitions(mode))) {
    const group = definition.ui_group ?? "internal"
    if (group === "internal" || !canvasOptionVisible(definition, values)) continue
    if (group === "advanced") advanced.push([name, definition])
    else primary.push([name, definition])
  }
  return { primary, advanced }
}

export function serializeGeneratorOptionValues(
  mode: CanvasWorkflowMode | null | undefined,
  stored: Record<string, CanvasOptionValue> | null | undefined,
): Record<string, CanvasOptionValue> {
  const definitions = canvasModeOptionDefinitions(mode)
  const values = generatorOptionValues(mode, stored)
  const serialized: Record<string, CanvasOptionValue> = {}
  for (const [name, definition] of Object.entries(definitions)) {
    if ((definition.ui_group ?? "internal") === "internal") continue
    if (!canvasOptionVisible(definition, values)) continue
    const value = values[name]
    if (value === undefined) continue
    serialized[name] = definition.type === "number" || definition.type === "integer"
      ? Number(value)
      : value
  }
  return serialized
}

export function canvasReferenceEligible(node: CanvasNode): boolean {
  if (node.type === "image") return Boolean(canvasImageReferenceUrl(node.data))
  if (node.type === "generator") {
    const kind = generatorResultFromNodeData(node.data)?.kind ?? node.data.resultKind ?? null
    return kind === "image"
  }
  return false
}

/** 预留给生成结果、尚未填入地址的图片/视频节点。 */
export function canvasPendingResultFill(
  node: CanvasNode,
  result: CanvasJobResult,
  jobId: string | null,
): Partial<CanvasNode["data"]> | null {
  if (node.type !== "image" && node.type !== "video") return null
  if (!node.data.pendingGeneratorId) return null
  if (String(node.data.url ?? "").trim()) return null
  if (node.data.mediaKind !== result.kind) return null
  return {
    url: result.url,
    label: result.label || (result.kind === "video" ? "生成视频" : "生成图片"),
    assetPath: result.path || undefined,
    sourceJobId: jobId,
    mediaKind: result.kind,
    pendingGeneratorId: undefined,
  }
}

export function canvasPromptEligible(node: CanvasNode): boolean {
  return node.type === "text"
}

export type CanvasGeneratorPromptSource = {
  nodes: CanvasNode[]
  text: string
  emptyCount: number
  fromTextNodes: boolean
}

export type CanvasGeneratorPromptInfo = {
  connectedTextNodes: number
  emptyTextNodes: number
}

export type CanvasGeneratorPromptState = CanvasGeneratorPromptInfo & {
  text: string
  fromTextNodes: boolean
}

export function canvasPictureToken(index: number): string {
  return `<Picture ${index}>`
}

export function incomingGeneratorPromptNodes(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  generatorNodeId: string,
): CanvasNode[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const seen = new Set<string>()
  const sources: CanvasNode[] = []
  for (const edge of edges) {
    if (edge.target !== generatorNodeId || seen.has(edge.source)) continue
    const node = nodeById.get(edge.source)
    if (!node || !canvasPromptEligible(node)) continue
    seen.add(edge.source)
    sources.push(node)
  }
  return sources
}

export function resolveGeneratorPrompt(
  promptNodes: CanvasNode[],
  manualPrompt: string,
): CanvasGeneratorPromptSource {
  if (!promptNodes.length) {
    return { nodes: [], text: manualPrompt.trim(), emptyCount: 0, fromTextNodes: false }
  }
  const parts = promptNodes.map((node) => String(node.data.text ?? "").trim())
  const kept = parts.filter(Boolean)
  return {
    nodes: promptNodes,
    text: kept.join("\n\n"),
    emptyCount: parts.length - kept.length,
    fromTextNodes: true,
  }
}

export function generatorPromptInfo(source: CanvasGeneratorPromptSource): CanvasGeneratorPromptInfo {
  return {
    connectedTextNodes: source.nodes.length,
    emptyTextNodes: source.emptyCount,
  }
}

export function incomingGeneratorReferenceNodes(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  generatorNodeId: string,
): CanvasNode[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const seen = new Set<string>()
  const references: CanvasNode[] = []
  for (const edge of edges) {
    if (edge.target !== generatorNodeId || seen.has(edge.source)) continue
    const node = nodeById.get(edge.source)
    if (!node || !canvasReferenceEligible(node)) continue
    seen.add(edge.source)
    references.push(node)
  }
  return references
}

function safeReferenceUrl(raw: string, allowDataImage = true): string | null {
  const url = raw.trim()
  if (!url) return null
  if (allowDataImage && /^data:image\//i.test(url)) return url
  if (url.startsWith("/")) return url
  if (/^https?:\/\//i.test(url)) return url
  return null
}

export function canvasImageReferenceUrl(data: CanvasNode["data"]): string | null {
  const assetPath = typeof data.assetPath === "string" ? data.assetPath.trim() : ""
  if (assetPath) return `/api/media/${encodeURIComponent(assetPath)}`
  const url = typeof data.url === "string" ? data.url.trim() : ""
  if (url) return safeReferenceUrl(url)
  const resultPath = typeof data.resultPath === "string" ? data.resultPath.trim() : ""
  if (resultPath) return `/api/media/${encodeURIComponent(resultPath)}`
  const resultUrl = typeof data.resultUrl === "string" ? data.resultUrl.trim() : ""
  if (resultUrl) return safeReferenceUrl(resultUrl)
  return null
}

export function canvasReferenceLabel(node: CanvasNode, index: number): string {
  return String(node.data.label ?? "").trim() || `参考图 ${index}`
}

export async function canvasImageNodeFile(node: CanvasNode, index: number, expectedKind: "image" | "video" | "audio" = "image"): Promise<File> {
  const url = canvasImageReferenceUrl(node.data)
  if (!url) throw new Error(`参考图 ${index}「${canvasReferenceLabel(node, index)}」没有可用地址`)
  let response: Response
  try {
    // 跨源 CDN（如七牛图片域名）不返回带凭据的 CORS 头，credentials:"include" 会被直接拦截；
    // 公开图片无凭据读取即可，同源 /api/ 仍带 cookie。
    const crossOrigin = /^https?:\/\//i.test(url) && new URL(url).origin !== location.origin
    response = await fetch(url, { credentials: crossOrigin ? "omit" : "include" })
  } catch {
    throw new Error(`参考图 ${index} 无法读取，可能受跨域限制；请从作品库重新插入该图片`)
  }
  if (response.status === 401) {
    notifyUnauthorized()
    throw new Error("登录已过期，请重新登录")
  }
  if (!response.ok) {
    throw new Error(`参考图 ${index} 读取失败（HTTP ${response.status}）`)
  }
  const blob = await response.blob()
  return fileFromReferenceBlob(blob, index, blob.type || response.headers.get("content-type") || "", expectedKind)
}

export function generatorPromptIssue(
  prompt: string,
  info?: CanvasGeneratorPromptInfo | null,
): string | null {
  if (info?.connectedTextNodes && info.emptyTextNodes > 0) {
    return info.emptyTextNodes >= info.connectedTextNodes
      ? "已连接的文字节点内容为空，请补充文字或断开连线"
      : "连接的文字节点内容为空，请补充文字"
  }
  if (prompt.trim()) return null
  return "请填写创作提示词"
}

export function generatorReferenceIssue(
  mode: CanvasWorkflowMode | null | undefined,
  references: CanvasNode[],
): string | null {
  if (!mode) return null
  const minimum = mode.min_references ?? 0
  const maximum = mode.max_references ?? 0
  if (references.length < minimum || references.length > maximum) {
    if (minimum === maximum) return `${mode.name} 需要 ${minimum} 张参考图，当前 ${references.length} 张`
    return `${mode.name} 支持 ${minimum}-${maximum} 张参考图，当前 ${references.length} 张`
  }
  for (const [index, node] of references.entries()) {
    if (!canvasImageReferenceUrl(node.data)) {
      return `参考图 ${index + 1}「${canvasReferenceLabel(node, index + 1)}」没有可用地址`
    }
  }
  return null
}

export function validateGeneratorInput(
  mode: CanvasWorkflowMode | null | undefined,
  prompt: string,
  references: CanvasNode[],
  promptInfo?: CanvasGeneratorPromptInfo | null,
): string | null {
  if (!mode) return "请先选择生成工作流"
  return generatorPromptIssue(prompt, promptInfo) ?? generatorReferenceIssue(mode, references)
}

export type CanvasJobDraft = {
  mode: string
  prompt: string
  negativePrompt?: string
  imageSize?: string
  options?: Record<string, CanvasOptionValue>
  references: File[]
  title?: string
}

export function buildCanvasJobForm(draft: CanvasJobDraft): FormData {
  const form = new FormData()
  form.set("mode", draft.mode)
  form.set("prompt", draft.prompt)
  if (draft.negativePrompt) form.set("negative_prompt", draft.negativePrompt)
  if (draft.imageSize) form.set("image_size", draft.imageSize)
  if (draft.options && Object.keys(draft.options).length) {
    form.set("options", JSON.stringify(draft.options))
  }
  for (const file of draft.references) form.append("references", file)
  if (draft.title) form.set("title", draft.title)
  return form
}

export function submitCanvasJob(csrfToken: string, draft: CanvasJobDraft): Promise<CanvasJob> {
  return requestJson<CanvasJob>("/api/jobs", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: buildCanvasJobForm(draft),
  })
}

export function fetchCanvasModes(): Promise<CanvasModesPayload> {
  return requestJson<CanvasModesPayload>("/api/modes")
}

export function fetchCanvasJob(jobId: string): Promise<CanvasJob> {
  return requestJson<CanvasJob>(`/api/jobs/${encodeURIComponent(jobId)}`)
}

export function cancelCanvasJob(csrfToken: string, jobId: string): Promise<CanvasJob> {
  return requestJson<CanvasJob>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  })
}

export function refineCanvasJob(csrfToken: string, jobId: string, action: "confirm" | "skip"): Promise<CanvasJob> {
  return requestJson<CanvasJob>(`/api/jobs/${encodeURIComponent(jobId)}/refine/${action}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  })
}

export function canvasJobOutputs(job: CanvasJob): CanvasJobOutput[] {
  const roundOutputs = (job.rounds ?? [])
    .flatMap((round) => round.generation_items ?? [])
    .flatMap((item) => item.outputs ?? [])
  return roundOutputs.length ? roundOutputs : job.outputs ?? []
}

export function canvasJobResult(job: CanvasJob): CanvasJobResult | null {
  return canvasJobResults(job)[0] ?? null
}

export function canvasJobResults(job: CanvasJob): CanvasJobResult[] {
  const outputs = canvasJobOutputs(job)
  const ordered = [...outputs.filter((output) => output.render_pass !== "preview"), ...outputs.filter((output) => output.render_pass === "preview")]
  const results: CanvasJobResult[] = []
  const seen = new Set<string>()
  for (const output of ordered) {
    if (output.delivery_status === "expired") continue
    const kind = output.kind === "video" || output.kind === "image" ? output.kind : job.media_type
    const url = output.download_url
      || output.cloud_url
      || (output.path ? `/api/media/${encodeURIComponent(output.path)}` : "")
    if (!url) continue
    if (results.length && output.render_pass === "preview") continue
    if (seen.has(url)) continue
    seen.add(url)
    results.push({ url, kind, path: output.path, label: output.label })
  }
  return results
}

export function canvasJobLiveDetails(job: CanvasJob) {
  const results = canvasJobResults(job)
  const items = (job.rounds ?? []).at(-1)?.generation_items ?? []
  return {
    results,
    completedCount: results.length,
    requestedCount: items.length > results.length ? items.length : job.status === "partial" ? undefined : results.length,
  }
}

export function isCanvasJobActive(status: string | null | undefined): boolean {
  return status === "queued" || status === "running" || status === "awaiting_refine"
}

export function canvasJobOutputsExpired(job: CanvasJob): boolean {
  if (job.status !== "succeeded" && job.status !== "partial") return false
  const outputs = canvasJobOutputs(job)
  if (!outputs.length) return true
  return outputs.every((output) => (
    output.delivery_status === "expired"
    || (!output.download_url && !output.cloud_url && !output.path)
  ))
}

function readResultVersion(raw: unknown): CanvasResultVersion | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const entry = raw as Record<string, unknown>
  const url = typeof entry.url === "string" ? entry.url.trim() : ""
  if (!url) return null
  return {
    url,
    path: typeof entry.path === "string" ? entry.path : null,
    kind: entry.kind === "video" ? "video" : "image",
    label: typeof entry.label === "string" ? entry.label : undefined,
    jobId: typeof entry.jobId === "string" ? entry.jobId : null,
    createdAt: typeof entry.createdAt === "number" && Number.isFinite(entry.createdAt) ? entry.createdAt : undefined,
  }
}

export function canvasResultHistory(data: CanvasNode["data"]): CanvasResultVersion[] {
  const stored = Array.isArray(data.resultHistory)
    ? data.resultHistory.map(readResultVersion).filter((entry): entry is CanvasResultVersion => entry !== null)
    : []
  if (stored.length) return stored
  const url = typeof data.resultUrl === "string" ? data.resultUrl.trim() : ""
  if (!url) return []
  return [{
    url,
    path: data.resultPath ?? null,
    kind: data.resultKind === "video" ? "video" : "image",
    label: data.label,
    jobId: data.jobId ?? null,
  }]
}

export function canvasResultVersionIndex(data: CanvasNode["data"]): number {
  const history = canvasResultHistory(data)
  if (!history.length) return -1
  const requested = typeof data.resultIndex === "number" && Number.isInteger(data.resultIndex)
    ? data.resultIndex
    : history.length - 1
  return Math.min(Math.max(0, requested), history.length - 1)
}

export function displayedGeneratorResult(data: CanvasNode["data"], live?: CanvasGeneratorLive | null): CanvasJobResult | null {
  if (live && isCanvasJobActive(live.status) && live.result) return live.result
  return generatorResultFromNodeData(data) ?? live?.result ?? null
}

export function generatorResultFromNodeData(data: CanvasNode["data"]): CanvasJobResult | null {
  const history = canvasResultHistory(data)
  if (history.length) {
    const index = canvasResultVersionIndex(data)
    const entry = history[index]
    if (entry) {
      return {
        url: entry.url,
        kind: entry.kind,
        path: entry.path ?? undefined,
        label: entry.label || data.label,
      }
    }
  }
  const url = typeof data.resultUrl === "string" ? data.resultUrl.trim() : ""
  if (!url) return null
  return {
    url,
    kind: data.resultKind === "video" ? "video" : "image",
    path: data.resultPath ?? undefined,
    label: data.label,
  }
}

export function canvasResultVersionPatch(
  data: CanvasNode["data"],
  result: CanvasJobResult,
  jobId: string | null,
  now = Date.now(),
): Pick<CanvasNode["data"], "resultUrl" | "resultPath" | "resultKind" | "resultHistory" | "resultIndex"> {
  const history = [...canvasResultHistory(data)]
  let index = history.findIndex((entry) => (
    entry.url === result.url && (entry.path ?? "") === (result.path ?? "")
  ))
  if (index < 0) {
    history.push({
      url: result.url,
      path: result.path ?? null,
      kind: result.kind,
      label: result.label,
      jobId,
      createdAt: now,
    })
    index = history.length - 1
  }
  const capped = history.slice(-12)
  const resultIndex = Math.max(0, index - (history.length - capped.length))
  const selected = capped[resultIndex]
  return {
    resultUrl: selected.url,
    resultPath: selected.path ?? null,
    resultKind: selected.kind,
    resultHistory: capped,
    resultIndex,
  }
}

export function selectCanvasResultVersion(
  data: CanvasNode["data"],
  index: number,
): Pick<CanvasNode["data"], "resultUrl" | "resultPath" | "resultKind" | "resultIndex"> | null {
  const history = canvasResultHistory(data)
  const entry = history[index]
  if (!entry) return null
  return {
    resultUrl: entry.url,
    resultPath: entry.path ?? null,
    resultKind: entry.kind,
    resultIndex: index,
  }
}

export function generatorParameterSummary(
  mode: CanvasWorkflowMode | null | undefined,
  values: Record<string, CanvasOptionValue>,
): string[] {
  if (!mode) return []
  return generatorParameterFields(mode, values).primary.slice(0, 3).map(([name, definition]) => {
    const value = values[name] ?? definition.default
    const option = definition.ui_options?.find((item) => String(item.value) === String(value))
    const text = option?.label ?? (typeof value === "boolean" ? value ? "开启" : "关闭" : String(value))
    return `${definition.label} ${text}${definition.unit && !option ? definition.unit : ""}`
  })
}

export const CANVAS_RUN_HISTORY_LIMIT = 12
export const CANVAS_RUN_PROMPT_LIMIT = 4000
const CANVAS_RUN_OPTION_LIMIT = 40
const CANVAS_RUN_OPTION_TEXT_LIMIT = 200
const CANVAS_RUN_SUMMARY_LIMIT = 6
const CANVAS_RUN_SUMMARY_TEXT_LIMIT = 120

export function buildCanvasRunSnapshot(input: {
  jobId: string
  mode: CanvasWorkflowMode
  prompt: string
  optionValues: Record<string, CanvasOptionValue>
  referenceCount: number
  submittedAt?: number
}): CanvasRunSnapshot {
  const optionValues = serializeGeneratorOptionValues(input.mode, input.optionValues)
  return {
    jobId: input.jobId,
    workflowId: input.mode.id,
    workflowName: input.mode.name,
    prompt: input.prompt.slice(0, CANVAS_RUN_PROMPT_LIMIT),
    optionValues,
    parameterSummary: generatorParameterSummary(input.mode, optionValues),
    referenceCount: Math.max(0, Math.min(99, Math.trunc(input.referenceCount))),
    mediaKind: input.mode.media_type,
    submittedAt: input.submittedAt ?? Date.now(),
  }
}

function readRunOptionValues(raw: unknown): Record<string, CanvasOptionValue> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {}
  const values: Record<string, CanvasOptionValue> = {}
  for (const [name, value] of Object.entries(raw).slice(0, CANVAS_RUN_OPTION_LIMIT)) {
    if (typeof value === "string") values[name] = value.slice(0, CANVAS_RUN_OPTION_TEXT_LIMIT)
    else if (typeof value === "number" && Number.isFinite(value)) values[name] = value
    else if (typeof value === "boolean") values[name] = value
  }
  return values
}

export function readCanvasRunSnapshot(raw: unknown): CanvasRunSnapshot | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const entry = raw as Record<string, unknown>
  const jobId = typeof entry.jobId === "string" ? entry.jobId.trim() : ""
  const workflowId = typeof entry.workflowId === "string" ? entry.workflowId.trim() : ""
  if (!jobId || !workflowId) return null
  const workflowName = typeof entry.workflowName === "string" && entry.workflowName.trim()
    ? entry.workflowName.trim().slice(0, 120)
    : workflowId
  const parameterSummary = Array.isArray(entry.parameterSummary)
    ? entry.parameterSummary
      .filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
      .slice(0, CANVAS_RUN_SUMMARY_LIMIT)
      .map((item) => item.slice(0, CANVAS_RUN_SUMMARY_TEXT_LIMIT))
    : []
  const submittedAt = typeof entry.submittedAt === "number" && Number.isFinite(entry.submittedAt) && entry.submittedAt > 0
    ? entry.submittedAt
    : 0
  const referenceCount = typeof entry.referenceCount === "number" && Number.isFinite(entry.referenceCount)
    ? Math.max(0, Math.min(99, Math.trunc(entry.referenceCount)))
    : 0
  return {
    jobId,
    workflowId,
    workflowName,
    prompt: typeof entry.prompt === "string" ? entry.prompt.slice(0, CANVAS_RUN_PROMPT_LIMIT) : "",
    optionValues: readRunOptionValues(entry.optionValues),
    parameterSummary,
    referenceCount,
    mediaKind: entry.mediaKind === "video" ? "video" : "image",
    submittedAt,
  }
}

export function canvasRunHistory(data: CanvasNode["data"]): CanvasRunSnapshot[] {
  if (!Array.isArray(data.runHistory)) return []
  const snapshots: CanvasRunSnapshot[] = []
  for (const raw of data.runHistory.slice(-CANVAS_RUN_HISTORY_LIMIT * 2)) {
    const snapshot = readCanvasRunSnapshot(raw)
    if (!snapshot) continue
    const existing = snapshots.findIndex((item) => item.jobId === snapshot.jobId)
    if (existing >= 0) snapshots[existing] = snapshot
    else snapshots.push(snapshot)
  }
  return snapshots.slice(-CANVAS_RUN_HISTORY_LIMIT)
}

export function canvasRunSnapshotForJob(
  data: CanvasNode["data"],
  jobId: string | null | undefined,
): CanvasRunSnapshot | null {
  const target = typeof jobId === "string" ? jobId.trim() : ""
  if (!target) return null
  const fromHistory = canvasRunHistory(data).find((item) => item.jobId === target)
  if (fromHistory) return fromHistory
  const lastRun = readCanvasRunSnapshot(data.lastRun)
  return lastRun?.jobId === target ? lastRun : null
}

export function appendCanvasRunSnapshot(
  data: CanvasNode["data"],
  snapshot: CanvasRunSnapshot,
): Pick<CanvasNode["data"], "lastRun" | "runHistory"> {
  const history = canvasRunHistory(data).filter((item) => item.jobId !== snapshot.jobId)
  history.push(snapshot)
  return {
    lastRun: snapshot,
    runHistory: history.slice(-CANVAS_RUN_HISTORY_LIMIT),
  }
}

export type CanvasJobStatusTone = "idle" | "active" | "success" | "warning" | "error"

export function canvasJobStatusTone(status: string | null | undefined): CanvasJobStatusTone {
  if (isCanvasJobActive(status)) return "active"
  if (status === "succeeded" || status === "partial") return "success"
  if (status === "failed") return "error"
  if (status === "cancelled" || status === "interrupted") return "warning"
  return "idle"
}

const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "生成中",
  awaiting_refine: "一采预览待确认",
  succeeded: "已完成",
  failed: "生成失败",
  interrupted: "已中断",
  cancelled: "已停止",
  partial: "部分完成",
}

export function canvasJobStatusLabel(status: string | null | undefined): string {
  if (!status) return "待提交"
  return JOB_STATUS_LABELS[status] ?? status
}

export function canvasJobStatusColor(status: string | null | undefined): string {
  if (status === "succeeded" || status === "partial") return "success"
  if (status === "failed") return "error"
  if (status === "cancelled" || status === "interrupted") return "warning"
  if (status === "running" || status === "queued") return "processing"
  return "default"
}
