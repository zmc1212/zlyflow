import { describe, expect, it } from "vitest"
import { createEmptyRecipe, createEmptyRecipeShot } from "./types"
import { mergeContinuityRepair } from "./recipe-continuity"

function recipeWithPair() {
  const recipe = createEmptyRecipe("测试")
  return {
    ...recipe,
    scenes: [{
      id: "scene-1",
      sceneNumber: 1,
      title: "场景",
      description: "",
      locationName: "庭院",
      shots: [
        { ...createEmptyRecipeShot(1, 5), id: "shot-1", title: "本地标题 1", promptText: "old one", continuityOut: "old out" },
        { ...createEmptyRecipeShot(2, 5), id: "shot-2", title: "本地标题 2", promptText: "old two", dialogue: "保留对白", continuityIn: "old in" },
      ],
    }],
  }
}

describe("continuity repair merge", () => {
  it("applies only continuity-owned fields and preserves concurrent creative state", () => {
    const current = recipeWithPair()
    current.scenes[0]!.shots[1]!.camera!.scale = "CU"
    const repaired = recipeWithPair()
    repaired.scenes[0]!.shots[0]!.promptText = "server must not replace shot one prompt"
    repaired.scenes[0]!.shots[0]!.continuityOut = "new shared state"
    repaired.scenes[0]!.shots[1]!.promptText = "new opening prompt"
    repaired.scenes[0]!.shots[1]!.continuityIn = "new shared state"
    repaired.scenes[0]!.shots[1]!.dialogue = "服务端错误对白"
    repaired.scenes[0]!.shots[1]!.camera!.scale = "WS"
    repaired.continuityQa = { status: "passed", issues: [], pairs: [] }

    const merged = mergeContinuityRepair(current, repaired, 1, 2)

    expect(merged.scenes[0]!.shots[0]!.promptText).toBe("old one")
    expect(merged.scenes[0]!.shots[0]!.continuityOut).toBe("new shared state")
    expect(merged.scenes[0]!.shots[1]!.promptText).toBe("new opening prompt")
    expect(merged.scenes[0]!.shots[1]!.dialogue).toBe("保留对白")
    expect(merged.scenes[0]!.shots[1]!.camera!.scale).toBe("CU")
    expect(merged.continuityQa?.status).toBe("passed")
  })
})
