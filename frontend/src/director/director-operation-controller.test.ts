import { describe, expect, it } from "vitest"
import type { DirectorOperationResponse } from "./director-api"
import {
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
