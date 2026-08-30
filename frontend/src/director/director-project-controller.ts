import { ApiRequestError } from "../api"
import type { DirectorProjectResponse } from "./director-api"
import { summarizeJobError } from "./director-submit"
import type { RecipeProject, RecipeShot } from "./recipe-model"

export type DirectorContentConflict = { remote: DirectorProjectResponse }

export function readDirectorContentConflict(error: unknown): DirectorProjectResponse | null {
  if (!(error instanceof ApiRequestError) || error.status !== 409) return null
  const detail = error.body && typeof error.body === "object"
    ? (error.body as { detail?: unknown }).detail
    : null
  if (!detail || typeof detail !== "object") return null
  const record = detail as { code?: unknown; current_project?: unknown }
  if (record.code !== "DIRECTOR_CONTENT_CONFLICT" || !record.current_project || typeof record.current_project !== "object") {
    return null
  }
  return record.current_project as DirectorProjectResponse
}

export function directorFailureMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : ""
  return summarizeJobError(raw).summary || fallback
}

export function shouldPreserveLocalDirectorContent(options: {
  contentRevision: number
  dirty: boolean
  executionOnly: boolean
  hasConflict: boolean
  runningPlan: boolean
}): boolean {
  return options.contentRevision > 0
    && (options.dirty || options.executionOnly || options.hasConflict)
    && !options.runningPlan
}

export function reconcileDirectorShotSelection(
  shots: RecipeShot[],
  selectedShotId: string | null,
  checkedShotIds: string[],
): { selectedShotId: string | null; checkedShotIds: string[] } {
  const validIds = new Set(shots.map((shot) => shot.id))
  return {
    selectedShotId: selectedShotId && validIds.has(selectedShotId)
      ? selectedShotId
      : shots[0]?.id || null,
    checkedShotIds: checkedShotIds.filter((id) => validIds.has(id)),
  }
}

export function mergeInsertedDirectorAssets(
  current: RecipeProject,
  incoming: RecipeProject,
  requestedLibraryAssetIds: string[],
): RecipeProject {
  const requested = new Set(requestedLibraryAssetIds)
  const merge = <T extends { id: string; libraryAssetId?: string | null }>(existing: T[], received: T[]): T[] => {
    const ids = new Set(existing.map((item) => item.id))
    const libraryIds = new Set(
      existing.map((item) => item.libraryAssetId).filter((id): id is string => Boolean(id)),
    )
    const added = received.filter((item) => (
      Boolean(item.libraryAssetId)
      && requested.has(item.libraryAssetId as string)
      && !ids.has(item.id)
      && !libraryIds.has(item.libraryAssetId as string)
    ))
    return added.length ? [...existing, ...added] : existing
  }
  return {
    ...current,
    characters: merge(current.characters, incoming.characters),
    locations: merge(current.locations, incoming.locations),
  }
}
