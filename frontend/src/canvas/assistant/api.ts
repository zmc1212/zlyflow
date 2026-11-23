import { jsonMutation, requestJson } from "../../api"

export const CANVAS_ASSISTANT_API = "/api/canvas-assistant"
export type RecordBase = { id: string; status: string; version: number; created_at: string; updated_at: string }
export type AssistantSelections = {
  model_id: string
  web_search: boolean
  /** 生图默认工作流偏好；空表示每次先询问（助手会用选择卡问一次并记住）。 */
  image_workflow_id: string
  /** 生视频默认工作流偏好；空表示每次先询问。 */
  video_workflow_id: string
  /** 预留：画布创作技能包（下轮接入导演台技能资源表）。 */
  skill_id: string
}
export const emptySelections = (): AssistantSelections => ({ model_id: "", web_search: false, image_workflow_id: "", video_workflow_id: "", skill_id: "" })
export type ModelCapabilities = {
  provider: string; native_tools: boolean; structured_output: string | null
  prompt_cache: string | null; web_search: boolean; usage_reporting?: boolean; degraded?: string[]
}
export type AssistantCatalog = {
  enabled: boolean; available: boolean; unavailable_reason?: string | null
  models: { id: string; label: string; capabilities?: ModelCapabilities }[]
  /** 技能列表：与导演台 ResourcePicker 组件契约一致（复用其 AssistantResource 类型）。 */
  skills: import("../../director2/assistant/api").AssistantResource[]
}
export type AssistantQuestion = { id: string; title: string; type: "single" | "multiple" | "text"; allow_custom: boolean; options: { label: string; value: string; description?: string; recommended?: boolean }[] }
export type AssistantUsage = { prompt_tokens: number; completion_tokens: number; total_tokens: number; cached_tokens?: number; cache_creation_tokens?: number; requests?: number; cost_cny?: number; cost_basis?: "actual" | "estimated" | string; unit_credits?: number; model?: string }
export type WebSearchResult = { title: string; url: string; site?: string }
export type MessagePart =
  | { type: "markdown"; text: string }
  | { type: "question"; question: AssistantQuestion }
  | { type: "proposal"; proposal_id: string }
  | { type: "tool"; name: string; label: string; status: string; detail?: string }
  | { type: "usage"; usage: AssistantUsage }
  | { type: "web_search"; results: WebSearchResult[] }
export type AssistantMessage = RecordBase & { role: "user" | "assistant"; parts: MessagePart[]; run_id: string; error?: string | null; selections: AssistantSelections; resource_names?: { skill?: string } }
export type AssistantRun = RecordBase & { session_id: string; message_id: string; user_message_id?: string; cancel_requested: boolean; error?: string | null }

/** 与后端 canvas_assistant.canvas_actions 输出对齐的归一化操作。 */
export type CanvasAssistantOp = {
  op: "create_text" | "create_generator" | "connect" | "update_generator" | "update_text" | "submit" | "insert_library_item" | "delete_node"
  ref: string
  op_index?: number
  label?: string | null
  text?: string | null
  workflow_id?: string | null
  workflow_name?: string | null
  prompt?: string | null
  option_values?: Record<string, string | number | boolean>
  media_kind?: "image" | "video" | null
  connect_from?: string[]
  position?: string | null
  source_ref?: string | null
  target_ref?: string | null
  item?: Record<string, unknown>
  as_reference_of?: string | null
}

export type CanvasProposalSummary = { counts: Record<string, number>; total: number; credit_estimate?: number | null }
export type CanvasProposal = RecordBase & {
  canvas_id: string; title: string; ops: CanvasAssistantOp[]; summary: CanvasProposalSummary; run_id: string
  apply_result?: { applied_ops?: number; failed?: { op_index?: number; error: string }[]; created_node_ids?: string[]; removed_node_ids?: string[] } | null
}
export type AssistantSession = RecordBase & {
  title: string; canvas_id: string; canvas_title?: string; selections: AssistantSelections
  active_run_id: string | null; pending_question: AssistantQuestion | null
  resource_snapshot?: { skill?: { name: string; instructions: string; references: Record<string, string>; version_id: string; category?: string } }
}
export type AssistantDetail = { session: AssistantSession; messages: AssistantMessage[]; proposals: CanvasProposal[]; run: AssistantRun | null }
export type MessageContext = { selection_ids: string[]; viewport_node_ids: string[] }

/** 画布工作流轻量描述（CanvasEditor 的 generationModes 结构子集）。 */
export type CanvasWorkflowModeLite = { id: string; name: string; media_type?: string }

export function canvasAssistantGet<T>(path: string) { return requestJson<T>(CANVAS_ASSISTANT_API + path) }
export function canvasAssistantMutate<T>(csrfToken: string, path: string, value?: unknown, method = "POST") {
  return requestJson<T>(CANVAS_ASSISTANT_API + path, jsonMutation(csrfToken, value, method))
}

export function isAssistantRunning(run: AssistantRun | null | undefined) {
  return !!run && ["queued", "running"].includes(run.status)
}

export function mergeAssistantEvent(detail: AssistantDetail, event: { message_id?: string; parts?: MessagePart[]; index?: number; text?: string }, messageId: string): AssistantDetail {
  return { ...detail, messages: detail.messages.map(message => {
    if (message.id !== (event.message_id || messageId)) return message
    if (event.parts) return { ...message, parts: event.parts }
    if (event.index === undefined) return message
    const parts = [...message.parts]
    parts[event.index] = { type: "markdown", text: event.text || "" }
    return { ...message, parts }
  }) }
}

export const OP_LABELS: Record<CanvasAssistantOp["op"], string> = {
  create_text: "新建文字节点",
  create_generator: "新建生成节点",
  connect: "连线",
  update_generator: "更新生成节点",
  update_text: "更新文字节点",
  submit: "提交生成任务",
  insert_library_item: "插入作品库素材",
  delete_node: "删除节点",
}

/** 常用参数 key 的中文展示名；未收录的 key 原样显示（与工作流参数名一致）。 */
const OPTION_LABELS: Record<string, string> = {
  aspect_ratio: "画幅",
  duration: "时长",
  quality: "分辨率",
  resolution: "分辨率",
  megapixels: "像素规模",
  size: "尺寸",
  image_size: "尺寸",
  count: "数量",
  num_outputs: "数量",
  output_count: "数量",
  generation_count: "数量",
  seed: "随机种子",
  speed: "速度档",
  refine_enabled: "二采精修",
}

export function formatOptionChips(values: Record<string, string | number | boolean> | null | undefined): { label: string; value: string }[] {
  if (!values) return []
  return Object.entries(values)
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => ({ label: OPTION_LABELS[key] || key, value: String(value) }))
}

function formatOptionValues(values: Record<string, string | number | boolean> | null | undefined): string {
  if (!values || !Object.keys(values).length) return ""
  return Object.entries(values)
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => `${OPTION_LABELS[key] || key} ${String(value)}`)
    .join(" · ")
}

export function describeOp(op: CanvasAssistantOp, modes: { id: string; name: string }[], describeNode?: (ref: string) => string): string {
  const workflowName = (id: string | null | undefined) => {
    if (!id) return ""
    return modes.find(mode => mode.id === id)?.name || id
  }
  switch (op.op) {
    case "create_text":
      return `「${(op.label || op.text || "文字").slice(0, 40)}」`
    case "create_generator": {
      // 确认前必须看到关键参数与参考关系：画幅/时长等参数、连入节点数、提示词来源。
      const params = formatOptionValues(op.option_values)
      const refs = op.connect_from?.length ? `连入 ${op.connect_from.length} 个节点` : ""
      const promptText = op.prompt
        ? op.prompt.slice(0, 60)
        : refs ? "（提示词/参考来自连入节点）" : "（使用画布全局提示词）"
      return [workflowName(op.workflow_id), promptText, params, refs].filter(Boolean).join(" · ")
    }
    case "connect":
      return `${describeNode?.(op.source_ref || "") || op.source_ref} → ${describeNode?.(op.target_ref || "") || op.target_ref}`
    case "update_generator": {
      const parts: string[] = []
      if (op.workflow_id) parts.push(`换用 ${workflowName(op.workflow_id)}`)
      if (op.prompt) parts.push(`改提示词「${op.prompt.slice(0, 40)}」`)
      if (op.option_values && Object.keys(op.option_values).length) parts.push(`调参数 ${formatOptionValues(op.option_values)}`)
      return parts.join("；") || "更新节点"
    }
    case "submit":
      return "提交该生成节点为任务"
    case "update_text":
      return `改文字为「${(op.text || op.label || "").slice(0, 40)}」${op.text && op.label ? `（标题「${op.label.slice(0, 16)}」）` : ""}`
    case "delete_node":
      return `删除 ${describeNode?.(op.ref || "") || op.ref} 及其连线`
    case "insert_library_item":
      return `${String(op.item?.label || op.item?.kind || "素材")}（${String(op.item?.kind || "")}）${op.as_reference_of ? ` · 接为 ${describeNode?.(op.as_reference_of) || op.as_reference_of} 的参考` : ""}`
  }
}

/** ref 是否指向画布已有节点（非提案内新建的 n1/n2… 编号）。 */
export function isExistingRef(ref: string | null | undefined): boolean {
  return !!ref && !/^n\d+$/i.test(ref)
}
