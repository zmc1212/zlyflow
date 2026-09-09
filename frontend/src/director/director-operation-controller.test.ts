import { describe, expect, it } from "vitest"
import type { DirectorOperationResponse } from "./director-api"
import { ApiRequestError } from "../api"
import {
  conflictingDirectorOperationId,
  directorOperationFailedAgents,
  directorOperationIsActive,
  directorOperationStorageKey,
  directorOperationTargetShotIds,
} from "./director-operation-controller"
import { createEmptyRecipe, createEmptyRecipeShot } from "./types"

function operation(overrides: Partial<DirectorOperationResponse> = {}): DirectorOperationResponse {
  return {
    id: "operation-1",
    project_id: "project-1",
    kind: "shot_render_prepare",
    status: "queued",
    progress: 0,
    request: {},
    result: {},
    error: null,
    cancel_requested: false,
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
    ...overrides,
  }
}

describe("director operation controller", () => {
  it("extracts an active operation id from the exclusive guard response", () => {
    const error = new ApiRequestError(409, {
      detail: "工程已有未完成的导演操作：director-op-2d93282087a441a48f305e044e3cda9e",
    })
    expect(conflictingDirectorOperationId(error)).toBe("director-op-2d93282087a441a48f305e044e3cda9e")
    expect(conflictingDirectorOperationId(new ApiRequestError(409, { detail: "其他冲突" }))).toBeNull()
    expect(conflictingDirectorOperationId(new ApiRequestError(500, { detail: "服务异常" }))).toBeNull()
  })

  it("restores stable storage keys and filters stale requested shot ids", () => {
    const shots = [{ ...createEmptyRecipeShot(1), id: "shot-1" }]
    const value = operation({ request: { shot_ids: ["shot-1", "deleted"] } })
    expect(directorOperationStorageKey("project-1")).toBe("director-operation:project-1")
    expect(directorOperationIsActive(value)).toBe(true)
    expect(directorOperationTargetShotIds(value, shots)).toEqual(["shot-1"])
    expect(directorOperationTargetShotIds(operation({ request: { shot_ids: ["deleted"] } }), shots)).toEqual([])
  })

  it("treats persisted failed_agents as authoritative", () => {
    const recipe = createEmptyRecipe()
    recipe.agentStatus[1] = { ...recipe.agentStatus[1], status: "failed", error: "timeout" }
    const value = operation({
      kind: "plan_pipeline",
      status: "succeeded",
      result: { failed_agents: ["storyboard"] },
    })
    expect(directorOperationFailedAgents(value, recipe)).toEqual(["storyboard"])
  })
})
