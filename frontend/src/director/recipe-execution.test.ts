import { describe, expect, it } from "vitest"
import { createEmptyRecipe, createEmptyRecipeCharacter, createEmptyRecipeShot, type RecipeProject } from "./types"
import { ensureRecipeAssetSchema } from "./recipe-model"
import {
  hasLatestShotSubmissionFailure,
  mergeRecipeApprovedAssetState,
  mergeRecipeExecutionState,
  mergeRecipeShotFrameState,
  reconcileShotJobExecution,
} from "./recipe-execution"

function recipeWithShot(overrides: Partial<ReturnType<typeof createEmptyRecipeShot>> = {}): RecipeProject {
  const recipe = createEmptyRecipe("本地标题")
  const shot = {
    ...createEmptyRecipeShot(1, 5),
    id: "shot-1",
    title: "本地镜头文案",
    promptText: "本地未保存提示词",
    voiceId: "voice-local",
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
      voiceId: "voice-stale-server",
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
    expect(shot.voiceId).toBe("voice-local")
    expect(shot.approvedTakeId).toBe("take-old")
    expect(shot.jobId).toBe("job-new")
    expect(shot.takes.map((take) => take.id)).toEqual(["take-old", "take-new"])
    expect(shot.activeTakeIndex).toBeUndefined()
  })

  it("keeps a successful old take previewable while exposing the latest submission error", () => {
    const current = recipeWithShot({
      status: "running",
      outputVideoUrl: "/old.mp4",
      jobId: "job-new",
      takes: [
        ...recipeWithShot().scenes[0].shots[0].takes,
        {
          id: "take-new",
          takeNumber: 2,
          jobId: "job-new",
          status: "failed",
          progress: 0,
          error: "本次提交超时",
          createdAt: "2026-08-30T00:01:00Z",
        },
      ],
    })
    const shot = reconcileShotJobExecution(current.scenes[0].shots[0], {
      status: "failed",
      progress: 0,
      error: "本次提交超时",
    })
    expect(shot.status).toBe("succeeded")
    expect(shot.outputVideoUrl).toBe("/old.mp4")
    expect(shot.error).toBe("本次提交超时")
    expect(hasLatestShotSubmissionFailure(shot, "video")).toBe(true)
  })

  it("keeps a failed status when no usable take exists", () => {
    const current = recipeWithShot({ approvedTakeId: null, takes: [], outputVideoUrl: null })
    const shot = reconcileShotJobExecution(current.scenes[0].shots[0], {
      status: "failed",
      progress: 0,
      error: "提交失败",
    })
    expect(shot.status).toBe("failed")
    expect(shot.error).toBe("提交失败")
  })

  it("keeps unsaved frame choices during polling and applies explicit upload results", () => {
    const current = recipeWithShot({ firstFrameUrl: "/local-frame.png", firstFrameJobId: "local-frame" })
    const incoming = recipeWithShot({ firstFrameUrl: "/stale-frame.png", firstFrameJobId: "stale-frame" })
    const polled = mergeRecipeExecutionState(current, incoming)
    expect(polled.scenes[0].shots[0].firstFrameUrl).toBe("/local-frame.png")
    expect(polled.scenes[0].shots[0].firstFrameJobId).toBe("local-frame")

    const uploaded = mergeRecipeShotFrameState(current, incoming, "shot-1")
    expect(uploaded.scenes[0].shots[0].firstFrameUrl).toBe("/stale-frame.png")
    expect(uploaded.scenes[0].shots[0].title).toBe("本地镜头文案")
  })

  it("applies an explicit asset approval without dropping local character copy", () => {
    const current = createEmptyRecipe("本地标题")
    current.characters = [createEmptyRecipeCharacter({
      id: "char-1",
      name: "本地未保存名字",
      description: "本地描述",
      portrait: {
        versions: [{
          id: "ver-1", jobId: "job-1", imageUrl: "/p.png", status: "succeeded",
          promptSnapshot: "", options: {}, createdAt: "2026-08-31T00:00:00Z",
        }],
        activeVersionId: "ver-1",
        approvedVersionId: null,
      },
    })]
    const incoming = JSON.parse(JSON.stringify(current)) as RecipeProject
    incoming.characters[0].name = "服务端旧名字"
    incoming.characters[0].portrait.approvedVersionId = "ver-1"
    incoming.characters[0].imageUrl = "/p.png"
    const merged = mergeRecipeApprovedAssetState(current, incoming)
    expect(merged.characters[0].name).toBe("本地未保存名字")
    expect(merged.characters[0].portrait.approvedVersionId).toBe("ver-1")
    expect(merged.characters[0].imageUrl).toBe("/p.png")
  })
})

describe("recipe asset schema", () => {
  it("fills missing portrait and look renditions so character stage can render", () => {
    const recipe = ensureRecipeAssetSchema({
      ...createEmptyRecipe("空白角色"),
      characters: [{
        id: "char-1",
        name: "侦探",
        description: "风衣",
        promptText: "detective",
        gender: "male",
        type: "character",
      } as RecipeProject["characters"][number]],
    })
    expect(recipe.characters[0].portrait.versions).toEqual([])
    expect(recipe.characters[0].looks[0].id).toBe("look-default")
    expect(recipe.characters[0].looks[0].sheet.versions).toEqual([])
    expect(recipe.characters[0].identitySpec.faceFeatures).toBe("")
  })
})
