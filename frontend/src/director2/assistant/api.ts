import { jsonMutation, requestJson } from "../../api"
import type { EditingContext } from "./editing-tools"
import type { EditingAction } from "../smart-edit/api"

export const ASSISTANT_API = "/api/director-assistant"
export type RecordBase = { id: string; status: string; version: number; created_at: string; updated_at: string }
export type AssistantSelections = { skill_id: string | null; expert_id: string | null; knowledge_ids: string[]; model_id: string }
export type AssistantResource = RecordBase & {
  resource_type: "skill" | "expert"; name: string; description: string; category: string
  instructions: string; references: Record<string, string>; builtin: boolean; favorite?: boolean; version_id: string
}
export type KnowledgeDocument = RecordBase & { filename: string; error?: string | null; chunk_count?: number }
export type KnowledgeLibrary = RecordBase & { name: string; description: string; builtin: boolean; documents: KnowledgeDocument[] }
export type AssistantCatalog = {
  enabled: boolean; available: boolean; unavailable_reason?: string | null; resources: AssistantResource[]
  knowledge: KnowledgeLibrary[]; models: { id: string; label: string }[]
}
export type AssistantSession = RecordBase & {
  title: string; project_id: string | null; selections: AssistantSelections; active_run_id: string | null
  resource_snapshot: { skill?: AssistantResource; expert?: AssistantResource }; pending_question: AssistantQuestion | null
  context?: EditingContext | null
}
export type AssistantQuestion = { id: string; title: string; type: "single" | "multiple" | "text"; allow_custom: boolean; options: { label: string; value: string; recommended?: boolean }[] }
export type KnowledgeCitation = { id: string; filename: string; section: string; page: string; text: string }
export type MessagePart =
  | { type: "markdown"; text: string }
  | { type: "question"; question: AssistantQuestion }
  | { type: "artifact"; artifact_id: string }
  | { type: "approval"; proposal_id: string }
  | { type: "edit_action"; action_id: string }
  | { type: "tool"; name: string; label: string; status: string; detail?: string }
  | { type: "citations"; items: KnowledgeCitation[] }
export type AssistantMessage = RecordBase & { role: "user" | "assistant"; parts: MessagePart[]; run_id: string; error?: string | null; resource_names?: { expert?: string; skill?: string }; selections: AssistantSelections }
export type AssistantArtifact = RecordBase & {
  title: string; artifact_type: "script" | "assets" | "episodes" | "storyboard" | "prompt" | "plan"
  content: string; revision: number; session_id: string; application_id?: string; applied_project_id?: string
  data: { assets?: { name: string; kind: string }[]; episodes?: { episode_num: number; title: string; episode_id?: string }[] }
}
export type AssistantRun = RecordBase & { session_id: string; message_id: string; cancel_requested: boolean; error?: string | null }
export type MediaProposal = RecordBase & {
  title: string; media_type: "asset_image" | "storyboard_image" | "video" | "voice" | "compose"
  project_id: string; project_name: string; asset_id?: string; episode_id?: string; beat_id?: string
  options: Record<string, unknown>; quantity: number; execution_id?: string
  model_name?: string; target_name?: string; creation_parameters?: { label: string; value: unknown }[]
}
export type MediaExecution = RecordBase & { error?: string; result?: Record<string, unknown>; title: string }
export type AssistantDetail = { session: AssistantSession; messages: AssistantMessage[]; artifacts: AssistantArtifact[]; proposals: MediaProposal[]; executions: MediaExecution[]; edit_proposals?: EditingAction[]; run: AssistantRun | null }
export type ApplicationPreview = RecordBase & { project_id: string; project_name: string; changes: { entity: string; label: string; operation: "add" | "update"; target_id: string }[] }

export const emptySelections = (): AssistantSelections => ({ skill_id: null, expert_id: null, knowledge_ids: [], model_id: "" })
export function assistantGet<T>(path: string) { return requestJson<T>(ASSISTANT_API + path) }
export function assistantMutate<T>(csrfToken: string, path: string, value?: unknown, method = "POST") {
  return requestJson<T>(ASSISTANT_API + path, jsonMutation(csrfToken, value, method))
}
export function assistantUpload<T>(csrfToken: string, path: string, file: File) {
  const body = new FormData(); body.append("file", file)
  return requestJson<T>(ASSISTANT_API + path, { method: "POST", headers: { "X-CSRF-Token": csrfToken }, body })
}
export const mediaLabels = { asset_image: "资产生图", storyboard_image: "分镜生图", video: "视频生成", voice: "配音", compose: "成片合成" }
export const artifactLabels = { script: "剧本", assets: "资产设定", episodes: "分集大纲", storyboard: "分镜", prompt: "提示词", plan: "制作计划" }

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
