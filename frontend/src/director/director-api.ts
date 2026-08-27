import { apiErrorMessage, jsonMutation, requestJson } from "../api"
import { persistableTimelineProject } from "./director-storage"
import { createEmptyProject, createInitialSubjectSlots, TimelineProject } from "./types"

export type DirectorGenerationStatus = "pending" | "partial" | "complete"

export type DirectorProjectListItem = {
  id: string
  title: string
  summary: string
  has_source_script: boolean
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

export function getDirectorProject(projectId: string) {
  return requestJson<DirectorProjectResponse>(`/api/director/projects/${encodeURIComponent(projectId)}`)
}

export function createDirectorProject(project: TimelineProject, csrfToken: string) {
  return requestJson<DirectorProjectResponse>("/api/director/projects", jsonMutation(csrfToken, directorProjectToCreateBody(project)))
}

export function updateDirectorProject(project: TimelineProject, csrfToken: string) {
  return requestJson<DirectorProjectResponse>(
    `/api/director/projects/${encodeURIComponent(project.id)}`,
    jsonMutation(csrfToken, directorProjectToUpdateBody(project), "PUT"),
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

export function migrateDirectorProjects(projects: TimelineProject[], csrfToken: string) {
  return requestJson<DirectorProjectMigrateResponse>(
    "/api/director/projects/migrate",
    jsonMutation(csrfToken, { projects: projects.map((project) => directorProjectToCreateBody(project, true)) }),
  )
}
