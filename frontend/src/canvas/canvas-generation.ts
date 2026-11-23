import { notifyUnauthorized, requestJson } from "../api"
import { fileFromReferenceBlob } from "../reference-assets"
import type { CanvasEdge, CanvasMediaKind, CanvasNode, CanvasResultVersion, CanvasRunSnapshot } from "./canvas-model"

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
  ui_summary?: "value" | "label"
  ui_companion?: string
  ui_companions?: string[]
  ui_options?: { value: string | number; label: string; short_label?: string; hint?: string }[]
  ui_visible_when?: Record<string, string | number | boolean>
}

export type CanvasOptionValue = string | number | boolean

/**
 * The card selector and inspector must reset the same workflow-dependent state.
 * 传入 previous（节点当前数据）时保留已有生成产物：改工作流只影响下一次生成，
 * 不得抹掉节点上正在展示的结果、版本历史与任务溯源。
 */
export function canvasWorkflowChangePatch(
  workflowId: string,
  mode: CanvasWorkflowMode | null,
  previous?: Pick<
    CanvasNode["data"],
    "jobId" | "jobStatus" | "jobError" | "resultUrl" | "resultPath" | "resultKind" | "resultHistory" | "resultIndex"
  > | null,
): Partial<CanvasNode["data"]> {
  const base: Partial<CanvasNode["data"]> = {
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
  if (!previous) return base
  return {
    ...base,
    jobId: previous.jobId ?? null,
    jobStatus: previous.jobStatus ?? null,
    jobError: previous.jobError ?? null,
    resultUrl: previous.resultUrl ?? null,
    resultPath: previous.resultPath ?? null,
    resultKind: previous.resultKind ?? mode?.media_type,
    resultHistory: previous.resultHistory ?? [],
    resultIndex: previous.resultIndex ?? -1,
  }
}

export type CanvasWorkflowParameter = {
  name: string
  schema?: { properties?: Record<string, CanvasOptionDefinition> } | null
}

export type CanvasReferenceKind = CanvasMediaKind | "audio"

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
  reference_slots?: CanvasReferenceKind[]
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
  // /api/modes 附带的计价语义；enabled 为真时前端可调 /api/credits/estimate 做实时预估。
  billing?: { enabled?: boolean; summary?: string | null } | null
  parameters?: CanvasWorkflowParameter[]
}

export type CanvasModesPayload = { modes: CanvasWorkflowMode[] }

export function canvasWorkflowReferenceKind(mode: CanvasWorkflowMode, index: number, count: number): CanvasReferenceKind {
  const slots = mode.reference_slots ?? []
  if (index >= 1 && index <= slots.length) {
    // Variable-length workflows keep the final slot (e.g. a motion video) after the images.
    if (index <= count && count < slots.length) return index === count ? slots[slots.length - 1] : "image"
    return slots[index - 1]
  }
  if (index === 2 && mode.accepts_video_reference) return "video"
  if (index === 2 && mode.accepts_audio_reference) return "audio"
  return "image"
}

export function canvasWorkflowReferenceKinds(mode: CanvasWorkflowMode, count = mode.max_references ?? 0): CanvasReferenceKind[] {
  return Array.from({ length: count }, (_, index) => canvasWorkflowReferenceKind(mode, index + 1, count))
}

/** 选中结果节点回显参数时，判断该工作流是否接受这类素材作为参考输入。 */
export function canvasModeAcceptsReferenceKind(mode: CanvasWorkflowMode, kind: CanvasReferenceKind): boolean {
  return canvasWorkflowReferenceKinds(mode).includes(kind)
}

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

/**
 * 即梦式加号传图：0 参考位工作流（如文生图）点加号添加参考时，自动升级到的目标工作流。
 * 优先 id 前缀同系（minimax-h3-image-t2i → minimax-h3-image-edit），其次收集式，保持注册表顺序兜底。
 */
export function pickCanvasReferenceUpgradeMode(
  modes: CanvasWorkflowMode[],
  current: CanvasWorkflowMode,
  kind: CanvasReferenceKind,
): CanvasWorkflowMode | null {
  const candidates = modes.filter((item) => item.available !== false
    && item.media_type === current.media_type
    && item.id !== current.id
    && canvasWorkflowReferenceKinds(item, 1).includes(kind))
  if (!candidates.length) return null
  const sharedPrefix = (item: CanvasWorkflowMode) => {
    let length = 0
    while (length < item.id.length && length < current.id.length && item.id[length] === current.id[length]) length += 1
    return length
  }
  return [...candidates].sort((a, b) => {
    const prefixGap = sharedPrefix(b) - sharedPrefix(a)
    if (prefixGap) return prefixGap
    return (b.reference_mode === "collection" ? 1 : 0) - (a.reference_mode === "collection" ? 1 : 0)
  })[0]
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

/** 新建生成节点时的默认画幅：图片竖屏、视频横屏。 */
const CREATION_ASPECT_BY_KIND: Record<CanvasMediaKind, string> = {
  image: "9:16",
  video: "16:9",
}

/** 云端工作流用语义值表示横竖屏时，映射到对应画幅。 */
const SEMANTIC_ASPECT_VALUES: Record<string, string[]> = {
  "16:9": ["landscape", "horizontal", "wide"],
  "9:16": ["portrait", "vertical"],
}

/**
 * 新建节点使用的默认参数：在注册表默认值之上，把图片节点设为 9:16、视频节点设为 16:9。
 * 工作流未声明比例参数、或枚举里没有对应画幅时保持注册表默认。
 */
export function generatorDefaultOptionValues(
  mode: CanvasWorkflowMode | null | undefined,
  mediaKind?: CanvasMediaKind,
): Record<string, CanvasOptionValue> {
  const values = defaultGeneratorOptionValues(mode)
  const desired = mediaKind ? CREATION_ASPECT_BY_KIND[mediaKind] : undefined
  if (!desired) return values
  const definitions = canvasModeOptionDefinitions(mode)
  const name = definitions.aspect_ratio ? "aspect_ratio" : definitions.ratio ? "ratio" : null
  if (!name) return values
  const allowed = (definitions[name].enum ?? definitions[name].ui_options?.map((item) => item.value) ?? []).map(String)
  if (!allowed.length || allowed.includes(desired)) {
    values[name] = desired
    return values
  }
  const alias = SEMANTIC_ASPECT_VALUES[desired].find((candidate) => allowed.includes(candidate))
  if (alias) values[name] = alias
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

export const CANVAS_REFERENCE_LABELS: Record<CanvasReferenceKind, string> = {
  image: "参考图",
  video: "参考视频",
  audio: "参考音频",
}

export function canvasReferenceKind(node: CanvasNode): CanvasReferenceKind | null {
  if (node.type === "image" || node.type === "video" || node.type === "audio") return node.type
  if (node.type === "generator") return generatorResultFromNodeData(node.data)?.kind ?? node.data.resultKind ?? null
  return null
}

export function bindCanvasReferenceSlots(mode: CanvasWorkflowMode, references: CanvasNode[], count: number) {
  const remaining = references.map((node) => ({ node, kind: canvasReferenceKind(node) }))
  const slots = canvasWorkflowReferenceKinds(mode, count).map((kind) => {
    const index = remaining.findIndex((reference) => reference.kind === kind)
    return { kind, node: index < 0 ? null : remaining.splice(index, 1)[0].node }
  })
  return { slots, unmatched: remaining.map(({ node }) => node) }
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
    if (!node || !canvasReferenceKind(node)) continue
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

function referenceUrlFromData(data: CanvasNode["data"], kind: CanvasReferenceKind, preferDisplay = false): string | null {
  const assetPath = typeof data.assetPath === "string" ? data.assetPath.trim() : ""
  const url = typeof data.url === "string" ? data.url.trim() : ""
  const resultPath = typeof data.resultPath === "string" ? data.resultPath.trim() : ""
  const resultUrl = typeof data.resultUrl === "string" ? data.resultUrl.trim() : ""
  const assetUrl = assetPath ? `/api/media/${encodeURIComponent(assetPath)}` : null
  const resultPathUrl = resultPath ? `/api/media/${encodeURIComponent(resultPath)}` : null
  const directUrl = url ? safeReferenceUrl(url, kind === "image") : null
  const directResultUrl = resultUrl ? safeReferenceUrl(resultUrl, kind === "image") : null
  // 缩略图要跟节点自身的渲染一致：先取节点正在显示的那个地址；上传读取仍优先同源素材路径。
  if (preferDisplay) return directUrl ?? directResultUrl ?? assetUrl ?? resultPathUrl
  return assetUrl ?? directUrl ?? resultPathUrl ?? directResultUrl
}

export function canvasReferenceUrl(node: CanvasNode, kind = canvasReferenceKind(node) ?? "image"): string | null {
  const result = node.type === "generator" ? generatorResultFromNodeData(node.data) : null
  return referenceUrlFromData(result ? { resultUrl: result.url, resultPath: result.path } : node.data, kind)
}

/** 参考图缩略图专用：与节点自身显示同一个地址，避免只依赖带目录的 /api/media 路径。 */
export function canvasReferencePreviewUrl(node: CanvasNode, kind = canvasReferenceKind(node) ?? "image"): string | null {
  const result = node.type === "generator" ? generatorResultFromNodeData(node.data) : null
  return referenceUrlFromData(result ? { resultUrl: result.url, resultPath: result.path } : node.data, kind, true)
}

export function canvasReferenceLabel(node: CanvasNode, index: number): string {
  return String(node.data.label ?? "").trim() || `${CANVAS_REFERENCE_LABELS[canvasReferenceKind(node) ?? "image"]} ${index}`
}

export async function canvasReferenceFile(node: CanvasNode, index: number, expectedKind = canvasReferenceKind(node) ?? "image"): Promise<File> {
  const url = canvasReferenceUrl(node, expectedKind)
  const label = CANVAS_REFERENCE_LABELS[expectedKind]
  if (!url) throw new Error(`${label} ${index}「${canvasReferenceLabel(node, index)}」没有可用地址`)
  let response: Response
  try {
    const crossOrigin = url.startsWith("//") || /^https?:\/\//i.test(url)
      ? new URL(url, location.origin).origin !== location.origin
      : false
    response = await fetch(url, { credentials: crossOrigin ? "omit" : "include" })
  } catch {
    throw new Error(`${label} ${index} 无法读取，可能受跨域限制`)
  }
  if (response.status === 401) {
    notifyUnauthorized()
    throw new Error("登录已过期，请重新登录")
  }
  if (!response.ok) {
    throw new Error(`${label} ${index} 读取失败（HTTP ${response.status}）`)
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
  const media = canvasWorkflowReferenceKinds(mode).some((kind) => kind !== "image")
  const unit = media ? "份参考素材" : "张参考图"
  if (references.length < minimum || references.length > maximum) {
    const current = `当前 ${references.length} ${media ? "份" : "张"}`
    if (minimum === maximum) return `${mode.name} 需要 ${minimum} ${unit}，${current}`
    return `${mode.name} 支持 ${minimum}-${maximum} ${unit}，${current}`
  }
  const { slots, unmatched } = bindCanvasReferenceSlots(mode, references, references.length)
  if (unmatched.length) return `${mode.name} 的参考素材类型不匹配，请更换素材或工作流`
  for (const [index, { kind, node }] of slots.entries()) {
    if (node && !canvasReferenceUrl(node, kind)) {
      return `${CANVAS_REFERENCE_LABELS[kind]} ${index + 1}「${canvasReferenceLabel(node, index + 1)}」没有可用地址`
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

/**
 * 结果节点（图片/视频）的生成来源快照：选中节点后在底部回显上次提示词与参数。
 * 插入结果与自动填充都会写入 sourceRun；更早的草稿退回 lastRun 兜底。
 */
export function canvasResultProvenance(node: CanvasNode): CanvasRunSnapshot | null {
  if (node.type !== "image" && node.type !== "video") return null
  return readCanvasRunSnapshot(node.data.sourceRun) ?? readCanvasRunSnapshot(node.data.lastRun)
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
