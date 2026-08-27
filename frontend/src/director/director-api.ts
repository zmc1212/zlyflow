import { apiErrorMessage, jsonMutation, requestJson } from "../api"
import { persistableTimelineProject } from "./director-storage"
import {
  BatchRunPayload,
  createEmptyProject,
  createInitialSubjectSlots,
  DirectorArtStyleCatalog,
  isBatchRunPayload,
  isRecipePayload,
  RecipeProject,
  TimelineProject,
} from "./types"

export type DirectorGenerationStatus = "pending" | "partial" | "complete"
export type DirectorPayloadKind = "timeline" | "director_recipe" | "batch_run"

export type DirectorProjectListItem = {
  id: string
  title: string
  summary: string
  has_source_script: boolean
  kind: DirectorPayloadKind
  shot_count: number
  generated_count: number
  generation_status: DirectorGenerationStatus
  style_vibe?: string | null
  requested_shot_count?: number | null
  created_at: string
  updated_at: string
}

export type DirectorProjectResponse = DirectorProjectListItem & {
  source_script: string
  payload: Record<string, unknown>
}

export type DirectorProjectMigrateResponse = {
  imported: number
  skipped: number
  projects: DirectorProjectListItem[]
}

function timelinePayload(project: TimelineProject): Record<string, unknown> {
  const persistable = persistableTimelineProject(project, false)
  return {
    aspectRatio: persistable.aspectRatio,
    canvasTier: persistable.canvasTier,
    previewQuality: persistable.previewQuality,
    previewSpeed: persistable.previewSpeed,
    finalQuality: persistable.finalQuality,
    finalSpeed: persistable.finalSpeed,
    videoWorkflowFamily: persistable.videoWorkflowFamily,
    width: persistable.width,
    height: persistable.height,
    fps: persistable.fps,
    refsMode: persistable.refsMode,
    globalSoundscape: persistable.globalSoundscape,
    globalMusic: persistable.globalMusic,
    subjectSlots: persistable.subjectSlots,
    globalCast: persistable.globalCast,
    duration: persistable.duration,
    shots: persistable.shots,
    manualPromptOverrideEnabled: persistable.manualPromptOverrideEnabled,
    manualPromptOverrideText: persistable.manualPromptOverrideText,
  }
}

export function directorProjectToCreateBody(project: TimelineProject, keepId = false) {
  return {
    ...(keepId ? { id: project.id } : {}),
    title: project.title.trim() || "未命名分镜工程",
    summary: project.summary || "",
    source_script: project.sourceScript || "",
    style_vibe: project.styleVibe || null,
    requested_shot_count: project.requestedShotCount ?? null,
    payload: timelinePayload(project),
    created_at: project.createdAt,
    updated_at: project.updatedAt,
  }
}

export function directorProjectToUpdateBody(project: TimelineProject) {
  return {
    title: project.title.trim() || "未命名分镜工程",
    summary: project.summary || "",
    source_script: project.sourceScript || "",
    style_vibe: project.styleVibe || null,
    requested_shot_count: project.requestedShotCount ?? null,
    payload: timelinePayload(project),
  }
}

export function timelineProjectFromApi(row: DirectorProjectResponse): TimelineProject {
  const base = createEmptyProject(row.title)
  const payload = row.payload && typeof row.payload === "object" ? row.payload : {}
  const shots = Array.isArray(payload.shots) ? payload.shots : base.shots
  const subjectSlots = Array.isArray(payload.subjectSlots) ? payload.subjectSlots : createInitialSubjectSlots()
  return {
    ...base,
    id: row.id,
    title: row.title,
    summary: row.summary || "",
    sourceScript: row.source_script || "",
    styleVibe: row.style_vibe || undefined,
    requestedShotCount: row.requested_shot_count ?? undefined,
    aspectRatio: typeof payload.aspectRatio === "string" ? payload.aspectRatio : base.aspectRatio,
    canvasTier: (payload.canvasTier as TimelineProject["canvasTier"]) || base.canvasTier,
    previewQuality: (payload.previewQuality as TimelineProject["previewQuality"]) || base.previewQuality,
    previewSpeed: (payload.previewSpeed as TimelineProject["previewSpeed"]) || base.previewSpeed,
    finalQuality: (payload.finalQuality as TimelineProject["finalQuality"]) || (
      payload.canvasTier === "past_native" ? "2.0" : payload.canvasTier === "fast" ? "0.4" : base.finalQuality
    ),
    finalSpeed: (payload.finalSpeed as TimelineProject["finalSpeed"]) || base.finalSpeed,
    videoWorkflowFamily: typeof payload.videoWorkflowFamily === "string" ? payload.videoWorkflowFamily : base.videoWorkflowFamily,
    width: typeof payload.width === "number" ? payload.width : base.width,
    height: typeof payload.height === "number" ? payload.height : base.height,
    fps: typeof payload.fps === "number" ? payload.fps : base.fps,
    refsMode: (payload.refsMode as TimelineProject["refsMode"]) || base.refsMode,
    globalSoundscape: typeof payload.globalSoundscape === "string" ? payload.globalSoundscape : base.globalSoundscape,
    globalMusic: typeof payload.globalMusic === "string" ? payload.globalMusic : base.globalMusic,
    subjectSlots: subjectSlots as TimelineProject["subjectSlots"],
    globalCast: Array.isArray(payload.globalCast) ? payload.globalCast as TimelineProject["globalCast"] : undefined,
    duration: typeof payload.duration === "number" ? payload.duration : undefined,
    shots: shots as TimelineProject["shots"],
    manualPromptOverrideEnabled: Boolean(payload.manualPromptOverrideEnabled),
    manualPromptOverrideText: typeof payload.manualPromptOverrideText === "string" ? payload.manualPromptOverrideText : "",
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

export function listDirectorProjects() {
  return requestJson<DirectorProjectListItem[]>("/api/director/projects")
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
  }> }>("/api/modes")
}

export function recipePayloadFromApi(row: DirectorProjectResponse): RecipeProject | null {
  if (!isRecipePayload(row.payload)) return null
  return {
    ...row.payload,
    videoWorkflowFamily: row.payload.videoWorkflowFamily || "official_h3",
  }
}

export function batchPayloadFromApi(row: DirectorProjectResponse): BatchRunPayload | null {
  if (!isBatchRunPayload(row.payload)) return null
  return {
    ...row.payload,
    videoWorkflowFamily: row.payload.videoWorkflowFamily || "official_h3",
  }
}

export function getDirectorProject(projectId: string) {
  return requestJson<DirectorProjectResponse>(`/api/director/projects/${encodeURIComponent(projectId)}`)
}

export function createDirectorProject(project: TimelineProject, csrfToken: string) {
  return requestJson<DirectorProjectResponse>("/api/director/projects", jsonMutation(csrfToken, directorProjectToCreateBody(project)))
}

export function createDirectorProjectRecord(
  body: {
    title: string
    summary?: string
    source_script?: string
    payload: RecipeProject | BatchRunPayload | Record<string, unknown>
  },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>("/api/director/projects", jsonMutation(csrfToken, body))
}

export function updateDirectorProject(project: TimelineProject, csrfToken: string) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(project.id)}`,
    jsonMutation(csrfToken, directorProjectToUpdateBody(project), "PUT"),
  )
}

export function updateDirectorProjectRecord(
  projectId: string,
  body: {
    title?: string
    summary?: string
    source_script?: string
    payload?: RecipeProject | BatchRunPayload | Record<string, unknown>
  },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, body, "PUT"),
  )
}

export async function deleteDirectorProject(projectId: string, csrfToken: string): Promise<void> {
  const response = await fetch(
    `/api/director/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
  if (response.status === 204 || response.ok) return
  const contentType = response.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) {
    const body = await response.json().catch(() => null)
    throw new Error(apiErrorMessage(body, "删除导演工程失败"))
  }
  throw new Error(`删除导演工程失败（HTTP ${response.status}）`)
}

export function copyDirectorProject(projectId: string, csrfToken: string) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(projectId)}/copy`,
    jsonMutation(csrfToken, {}),
  )
}

export function convertDirectorProjectToRecipe(projectId: string, csrfToken: string) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(projectId)}/convert-to-recipe`,
    jsonMutation(csrfToken, {}),
  )
}

export function migrateDirectorProjects(projects: TimelineProject[], csrfToken: string) {
  return requestJson<DirectorProjectMigrateResponse>(
    "/api/director/projects/migrate",
    jsonMutation(csrfToken, { projects: projects.map((project) => directorProjectToCreateBody(project, true)) }),
  )
}

export function runDirectorRecipe(
  body: { goal: string; project_id?: string; title?: string; art_style_id?: string; skip_research?: boolean },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>("/api/director/recipes/run", jsonMutation(csrfToken, body))
}

export function runDirectorRecipeStep(
  projectId: string,
  body: { agent_id: string; goal?: string; art_style_id?: string },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/recipes/${encodeURIComponent(projectId)}/step`,
    jsonMutation(csrfToken, body),
  )
}

export function generateDirectorAssets(
  projectId: string,
  body: { character_ids?: string[]; location_ids?: string[]; force?: boolean },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/recipes/${encodeURIComponent(projectId)}/generate-assets`,
    jsonMutation(csrfToken, body),
  )
}

export function renderDirectorShots(
  projectId: string,
  body: { shot_ids?: string[]; render_pass?: "preview" | "final" },
  csrfToken: string,
) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/recipes/${encodeURIComponent(projectId)}/render-shots`,
    jsonMutation(csrfToken, body),
  )
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
