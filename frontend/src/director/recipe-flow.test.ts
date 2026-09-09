import { describe, expect, it } from "vitest"
import { createEmptyRecipe, createEmptyRecipeShot } from "./types"
import { recipeShotFlow, recipeStageFlow } from "./recipe-flow"
import { recipeAssetIsAdopted } from "./recipe-readiness"

describe("director guided flow", () => {
  it("distinguishes a candidate from adoption and preserves legacy imported assets", () => {
    const version = { id: "candidate", status: "succeeded" as const, imageUrl: "/portrait.png", promptSnapshot: "", options: {}, createdAt: "" }
    expect(recipeAssetIsAdopted({ versions: [version] }, "/portrait.png")).toBe(false)
    expect(recipeAssetIsAdopted({ versions: [version], approvedVersionId: version.id })).toBe(true)
    expect(recipeAssetIsAdopted({ versions: [] }, "/legacy.png")).toBe(true)
  })
  it("keeps adopted media available when a newer take fails", () => {
    const shot = { ...createEmptyRecipeShot(1), approvedTakeId: "old", takes: [
      { id: "old", status: "succeeded", videoUrl: "/old.mp4" },
      { id: "new", status: "failed", error: "generation failed" },
    ] } as ReturnType<typeof createEmptyRecipeShot>
    expect(recipeShotFlow(shot)).toMatchObject({ usable: true, status: "failed", error: "generation failed" })
    expect(recipeShotFlow(shot).label).toContain("已采用版本")
  })
  it("supports manually imported shots without a script, characters or dialogue", () => {
    const recipe = createEmptyRecipe()
    const shot = { ...createEmptyRecipeShot(1), title: "手动镜头", description: "天空中的云" }
    recipe.scenes = [{ id: "scene", sceneNumber: 1, title: "", description: "", locationName: "", shots: [shot] }]
    expect(recipeStageFlow(recipe, "storyboard").nextStage).toBe("characters")
    expect(recipeStageFlow(recipe, "shots").pending.map((item) => item.id)).toEqual([shot.id])
    expect(recipeStageFlow(recipe, "voice").summary).toContain("无需配音")
    expect(recipeStageFlow(recipe, "characters").summary).toContain("文生")
  })
  it("does not include running or usable shots in pending generation", () => {
    const recipe = createEmptyRecipe()
    recipe.scenes = [{ id: "scene", sceneNumber: 1, title: "", description: "", locationName: "", shots: [
      { ...createEmptyRecipeShot(1), status: "running" },
      { ...createEmptyRecipeShot(2), status: "succeeded", outputVideoUrl: "/ok.mp4" },
      { ...createEmptyRecipeShot(3), status: "failed" },
    ] }]
    expect(recipeStageFlow(recipe, "shots").pending.map((shot) => shot.shotNumber)).toEqual([3])
    expect(recipeStageFlow(recipe, "export").missing).toHaveLength(2)
  })
})
