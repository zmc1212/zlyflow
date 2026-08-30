import { describe, expect, it } from "vitest"
import { createEmptyRecipe, createEmptyRecipeShot, type RecipeProject } from "./types"
import { hasLatestShotSubmissionFailure, mergeRecipeExecutionState } from "./recipe-execution"

function recipeWithShot(overrides: Partial<ReturnType<typeof createEmptyRecipeShot>> = {}): RecipeProject {
  const recipe = createEmptyRecipe("本地标题")
  const shot = {
    ...createEmptyRecipeShot(1, 5),
    id: "shot-1",
    title: "本地镜头文案",
    promptText: "本地未保存提示词",
    approvedTakeId: "take-old",
    takes: [{
      id: "take-old",
      takeNumber: 1,
      jobId: "job-old",
      status: "succeeded" as const,
      progress: 100,
      videoUrl: "/old.mp4",
      createdAt: "2026-08-30T00:00:00Z",
    }],
    ...overrides,
  }
  return {
    ...recipe,
    scenes: [{
      id: "scene-1",
      sceneNumber: 1,
      title: "场景",
      description: "",
      locationName: "",
      shots: [shot],
    }],
  }
}

describe("recipe execution merge", () => {
  it("retains local creative edits and approved take while appending a new take", () => {
    const current = recipeWithShot()
    const incoming = recipeWithShot({
      title: "服务端旧文案",
      promptText: "服务端旧提示词",
      jobId: "job-new",
      status: "queued",
      progress: 4,
      error: null,
      approvedTakeId: null,
      takes: [
        ...current.scenes[0].shots[0].takes,
        {
          id: "take-new",
          takeNumber: 2,
          jobId: "job-new",
          status: "queued",
          progress: 4,
          createdAt: "2026-08-30T00:01:00Z",
        },
      ],
    })

    const merged = mergeRecipeExecutionState(current, incoming)
    const shot = merged.scenes[0].shots[0]
    expect(shot.title).toBe("本地镜头文案")
    expect(shot.promptText).toBe("本地未保存提示词")
    expect(shot.approvedTakeId).toBe("take-old")
    expect(shot.jobId).toBe("job-new")
    expect(shot.takes.map((take) => take.id)).toEqual(["take-old", "take-new"])
  })

  it("keeps a successful old take previewable while exposing the latest submission error", () => {
    const current = recipeWithShot({ status: "succeeded", outputVideoUrl: "/old.mp4" })
    const failed = recipeWithShot({
      status: "succeeded",
      outputVideoUrl: "/old.mp4",
      jobId: null,
      error: "本次提交超时",
    })
    const merged = mergeRecipeExecutionState(current, failed)
    const shot = merged.scenes[0].shots[0]
    expect(shot.outputVideoUrl).toBe("/old.mp4")
    expect(hasLatestShotSubmissionFailure(shot, "video")).toBe(true)
  })
})
