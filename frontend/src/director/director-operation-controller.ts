import type { DirectorOperationResponse } from "./director-api"
import type { RecipeProject, RecipeShot } from "./recipe-model"

export function directorOperationStorageKey(projectId: string): string {
  return `director-operation:${projectId}`
}

export function directorOperationIsActive(operation: DirectorOperationResponse | undefined): boolean {
  return operation?.status === "queued" || operation?.status === "running"
}

export function directorOperationTargetShotIds(
  operation: DirectorOperationResponse,
  shots: RecipeShot[],
): string[] {
  const valid = new Set(shots.map((shot) => shot.id))
  const requested = operation.request.shot_ids
  return requested?.length
    ? requested.filter((id) => valid.has(id))
    : shots.map((shot) => shot.id)
}

export function directorOperationFailedAgents(
  operation: DirectorOperationResponse,
  recipe: RecipeProject | null,
): string[] {
  if (operation.result.failed_agents?.length) return operation.result.failed_agents
  const requested = new Set(operation.request.agents || [])
  return (recipe?.agentStatus || [])
    .filter((item) => item.status === "failed" && (!requested.size || requested.has(item.id)))
    .map((item) => item.id)
}
