import { ApiRequestError, apiErrorMessage, jsonMutation, notifyUnauthorized, requestJson } from "../api"
import { DirectorLibraryAsset } from "./types"
import {
  isBatchRunPayload,
  type BatchRunPayload, type DirectorArtStyleCatalog, type RecipeProject,
} from "./recipe-model"

export type DirectorGenerationStatus = "pending" | "partial" | "complete"
export type DirectorPayloadKind = "timeline" | "director_recipe" | "batch_run" | "shot_replication"

export type DirectorProjectListItem = {
  id: string
  title: string
  summary: string
  has_source_script: boolean
  cover_url?: string | null
  kind: DirectorPayloadKind
  shot_count: number
  generated_count: number
  generation_status: DirectorGenerationStatus
  revision: number
  content_revision: number
  style_vibe?: string | null
  requested_shot_count?: number | null
  created_at: string
  updated_at: string
}

export type DirectorProjectResponse = DirectorProjectListItem & {
  source_script: string
  payload: Record<string, unknown>
  active_operation?: DirectorOperationResponse | null
}

export type DirectorOperationKind =
  | "plan_pipeline"
  | "plan_clarify"
  | "shot_render_prepare"
  | "analyze_reference_video"
  | "replicate_shots"
export type DirectorOperationStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"

export type DirectorClarificationInput = { id?: string; agent?: string; question: string; answer: string }

export type DirectorOperationResponse = {
  id: string
  project_id: string
  kind: DirectorOperationKind
  status: DirectorOperationStatus
  progress: number
  request: {
    goal?: string
    agents?: string[]
    agent?: string
    guided?: boolean
    art_style_id?: string
    skip_research?: boolean
    reset_following?: boolean
    resume?: boolean
    shot_ids?: string[]
    render_pass?: "preview" | "final"
    clarifications?: DirectorClarificationInput[]
  }
  result: {
    message?: string
    job_ids?: string[]
    failed_agents?: string[]
    project_revision?: number
    content_revision?: number
    reset_following?: boolean
    questions?: unknown
  }
  error?: string | null
  cancel_requested: boolean
  created_at: string
  updated_at: string
}

export function listDirectorArtStyles() {
  return requestJson<DirectorArtStyleCatalog>("/api/director/art-styles")
}

export function listWorkflowModes() {
  return requestJson<{ modes: Array<{
    id: string
    name: string
    media_type?: string
    reference_mode?: string
    min_references?: number
    max_references?: number
    catalog_group?: string
    catalog_group_label?: string
      catalog_group_order?: number
      director_controls?: import("./director-workflows").DirectorControl[]
  }> }>("/api/modes")
}

export function batchPayloadFromApi(row: DirectorProjectResponse): BatchRunPayload | null {
  if (!isBatchRunPayload(row.payload)) return null
  return {
    ...row.payload,
    videoWorkflowFamily: row.payload.videoWorkflowFamily || "official_h3",
    weightProfile: row.payload.weightProfile === "pruned" ? "pruned" : "full",
  }
}

export function getDirectorProject(projectId: string) {
  return requestJson<DirectorProjectResponse>(`/api/director/projects/${encodeURIComponent(projectId)}`)
}

export function updateDirectorProjectRecord(
  projectId: string,
  body: {
    title?: string
    summary?: string
    source_script?: string
    payload?: RecipeProject | BatchRunPayload | Record<string, unknown>
    deleted_take_ids?: string[]
    expected_content_revision?: number
    force?: boolean
  },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, body, "PUT"),
  )
}

export function createReplicationOperation(
  projectId: string,
  body: {
    kind: "analyze_reference_video" | "replicate_shots"
    analysis_mode?: "smart" | "fixed"
    segment_seconds?: number
    scene_threshold?: number
    shot_ids?: string[]
  },
  csrfToken: string,
) {
  return requestJson<DirectorOperationResponse>(
    `/api/director/replications/${encodeURIComponent(projectId)}/operations`,
    jsonMutation(csrfToken, body),
  )
}

export async function uploadReplicationSourceVideo(
  projectId: string,
  body: { file: File; expected_content_revision?: number },
  csrfToken: string,
) {
  const form = new FormData()
  form.set("file", body.file)
  if (body.expected_content_revision) {
    form.set("expected_content_revision", String(body.expected_content_revision))
  }
  const response = await fetch(
    `/api/director/replications/${encodeURIComponent(projectId)}/source-video`,
    { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } },
  )
  if (response.status === 401) notifyUnauthorized()
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? ""
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => "")
    throw new ApiRequestError(response.status, payload, "上传参考片失败")
  }
  return response.json() as Promise<DirectorProjectResponse>
}

export function renderDirectorBatchItems(
  projectId: string,
  body: { item_ids?: string[] },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/batches/${encodeURIComponent(projectId)}/render`,
    jsonMutation(csrfToken, body),
  )
}

export function createDirectorBatch(
  body: {
    theme: string
    count: number
    aspect_ratio: string
    duration_sec: number
    video_workflow_family?: string
    art_style_id?: string
    title?: string
    project_id?: string
  },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>("/api/director/batches", jsonMutation(csrfToken, body))
}

export function listDirectorLibraryAssets(kind?: "character" | "scene" | "prop") {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : ""
  return requestJson<DirectorLibraryAsset[]>(`/api/director/library-assets${query}`)
}

export function createDirectorLibraryAsset(
  body: {
    kind: "character" | "scene" | "prop"
    name: string
    description?: string
    promptText?: string
    gender?: string
    imageUrl?: string | null
    imageJobId?: string | null
  },
  csrfToken: string,
) {
  return requestJson<DirectorLibraryAsset>("/api/director/library-assets", jsonMutation(csrfToken, body))
}

export function updateDirectorLibraryAsset(
  assetId: string,
  body: {
    kind?: "character" | "scene" | "prop"
    name?: string
    description?: string
    promptText?: string
    gender?: string
    imageUrl?: string | null
    imageJobId?: string | null
  },
  csrfToken: string,
) {
  return requestJson<DirectorLibraryAsset>(
    `/api/director/library-assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, body, "PUT"),
  )
}

export async function deleteDirectorLibraryAsset(assetId: string, csrfToken: string): Promise<void> {
  const response = await fetch(
    `/api/director/library-assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
  if (response.status === 401) notifyUnauthorized()
  if (response.status === 204 || response.ok) return
  const contentType = response.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) {
    const body = await response.json().catch(() => null)
    throw new Error(apiErrorMessage(body, "删除资产失败"))
  }
  throw new Error(`删除资产失败（HTTP ${response.status}）`)
}

export async function uploadDirectorLibraryAssetImage(assetId: string, file: File, csrfToken: string) {
  const form = new FormData()
  form.set("file", file)
  const response = await fetch(
    `/api/director/library-assets/${encodeURIComponent(assetId)}/image`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken }, body: form },
  )
  if (response.status === 401) notifyUnauthorized()
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? ""
    if (contentType.includes("application/json")) {
      const body = await response.json().catch(() => null)
      throw new Error(apiErrorMessage(body, "上传资产图失败"))
    }
    throw new Error(`上传资产图失败（HTTP ${response.status}）`)
  }
  return response.json() as Promise<DirectorLibraryAsset>
}
