import { jsonMutation, requestJson } from "../api"
import type { CanvasLibraryItem, CanvasProject, CanvasProjectDetail, CanvasVersion } from "./canvas-model"
import { canvasCopyTitle, canvasLibraryQueryString, type CanvasLibraryQuery } from "./canvas-manage"

export type CanvasLibraryPage = {
  items: CanvasLibraryItem[]
  total: number
  limit: number
  offset: number
  has_more: boolean
  counts: { image: number; video: number }
}

export function listCanvasProjects(trashed = false): Promise<CanvasProject[]> {
  return requestJson<CanvasProject[]>(`/api/canvas/projects${trashed ? "?trashed=1" : ""}`)
}

export function queryCanvasLibraryItems(query: CanvasLibraryQuery = {}): Promise<CanvasLibraryPage> {
  return requestJson<CanvasLibraryPage>(`/api/library/query?${canvasLibraryQueryString(query)}`)
}

export function createCanvasProject(csrfToken: string, title: string): Promise<CanvasProjectDetail> {
  return requestJson<CanvasProjectDetail>("/api/canvas/projects", jsonMutation(csrfToken, { title }))
}

export function getCanvasProject(projectId: string): Promise<CanvasProjectDetail> {
  return requestJson<CanvasProjectDetail>(`/api/canvas/projects/${encodeURIComponent(projectId)}`)
}

/** 导演项目资产画布：按 (用户, 导演项目) 幂等获取绑定的 linked 画布。 */
export function ensureLinkedCanvas(csrfToken: string, directorProjectId: string, title: string): Promise<CanvasProjectDetail> {
  return requestJson<CanvasProjectDetail>("/api/canvas/linked", jsonMutation(csrfToken, { director_project_id: directorProjectId, title }))
}

export type CanvasProjectPatch = {
  title?: string
  tags?: string[]
  is_favorite?: boolean
}

export function updateCanvasProject(
  csrfToken: string,
  projectId: string,
  patch: CanvasProjectPatch,
): Promise<CanvasProjectDetail> {
  return requestJson<CanvasProjectDetail>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, patch, "PATCH"),
  )
}

export function renameCanvasProject(csrfToken: string, projectId: string, title: string): Promise<CanvasProjectDetail> {
  return updateCanvasProject(csrfToken, projectId, { title })
}

export function trashCanvasProject(csrfToken: string, projectId: string): Promise<{ ok: boolean; deleted_at: string }> {
  return requestJson<{ ok: boolean; deleted_at: string }>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}/trash`,
    jsonMutation(csrfToken),
  )
}

export function restoreCanvasProject(csrfToken: string, projectId: string): Promise<CanvasProjectDetail> {
  return requestJson<CanvasProjectDetail>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}/restore`,
    jsonMutation(csrfToken),
  )
}

export function deleteCanvasProject(csrfToken: string, projectId: string): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export async function duplicateCanvasProject(csrfToken: string, projectId: string): Promise<CanvasProjectDetail> {
  const source = await getCanvasProject(projectId)
  const created = await createCanvasProject(csrfToken, canvasCopyTitle(source.title))
  try {
    await saveCanvasDraft(csrfToken, created.id, created.version, source.content, source.checksum)
  } catch (error) {
    await deleteCanvasProject(csrfToken, created.id).catch(() => undefined)
    throw error
  }
  return created
}

export type SaveDraftResult = {
  id: string
  version: number
  checksum: string
  node_count: number
  updated_at: string
}

export function saveCanvasDraft(
  csrfToken: string,
  projectId: string,
  baseVersion: number,
  content: string,
  checksum: string | null,
): Promise<SaveDraftResult> {
  return requestJson<SaveDraftResult>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}/draft`,
    jsonMutation(csrfToken, { base_version: baseVersion, content, checksum }, "PUT"),
  )
}

export function listCanvasVersions(projectId: string): Promise<CanvasVersion[]> {
  return requestJson<CanvasVersion[]>(`/api/canvas/projects/${encodeURIComponent(projectId)}/versions`)
}

export function restoreCanvasVersion(csrfToken: string, projectId: string, version: number): Promise<SaveDraftResult> {
  return requestJson<SaveDraftResult>(
    `/api/canvas/projects/${encodeURIComponent(projectId)}/versions/${version}/restore`,
    jsonMutation(csrfToken),
  )
}
