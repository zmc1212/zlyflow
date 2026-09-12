import { describe, expect, it } from "vitest"
import { createEmptyRecipe } from "./types"
import { nextGuidedStep, parseClarifyScope, tagClarifyAnswers } from "./guided-flow"

describe("nextGuidedStep", () => {
  it("starts at art_style for an empty project and walks the creation order", () => {
    const recipe = createEmptyRecipe()
    expect(nextGuidedStep(recipe)).toBe("art_style")
    recipe.artStyle = { id: "as_1001", name: "写实电影", promptPrefix: "" }
    expect(nextGuidedStep(recipe)).toBe("characters")
    recipe.characters = [{ id: "c1", name: "主角" } as never]
    expect(nextGuidedStep(recipe)).toBe("locations")
    recipe.locations = [{ id: "l1", name: "雨夜街道" } as never]
    expect(nextGuidedStep(recipe)).toBe("storyboard")
  })

  it("treats any split shot as storyboard output", () => {
    const recipe = createEmptyRecipe()
    recipe.artStyle = { id: "as_1001", name: "写实电影", promptPrefix: "" }
    recipe.characters = [{ id: "c1", name: "主角" } as never]
    recipe.locations = [{ id: "l1", name: "雨夜街道" } as never]
    expect(nextGuidedStep(recipe)).toBe("storyboard")
    recipe.scenes = [{
      id: "s1", sceneNumber: 1, title: "", description: "", locationName: "",
      shots: [{ id: "shot-1", title: "开场" } as never],
    }]
    expect(nextGuidedStep(recipe)).toBe("voice")
  })

  it("waits for a voice assignment and a music hint before finishing", () => {
    const recipe = createEmptyRecipe()
    recipe.artStyle = { id: "as_1001", name: "写实电影", promptPrefix: "" }
    recipe.characters = [{ id: "c1", name: "主角", voiceId: "onyx" } as never]
    recipe.locations = [{ id: "l1", name: "雨夜街道" } as never]
    recipe.scenes = [{
      id: "s1", sceneNumber: 1, title: "", description: "", locationName: "",
      shots: [{ id: "shot-1", title: "开场" } as never],
    }]
    expect(nextGuidedStep(recipe)).toBe("music")
    recipe.globalMusic = "warm strings"
    expect(nextGuidedStep(recipe)).toBeNull()
  })
})

describe("tagClarifyAnswers", () => {
  it("tags answers with their step and keeps script-scope answers untagged", () => {
    const answers = [{ id: "q1", question: "基调？", answer: "冷峻" }]
    expect(tagClarifyAnswers(answers, "art_style")).toEqual([
      { id: "q1", agent: "art_style", question: "基调？", answer: "冷峻" },
    ])
    expect(tagClarifyAnswers(answers)).toEqual([{ id: "q1", question: "基调？", answer: "冷峻" }])
  })
})

describe("parseClarifyScope", () => {
  it("parses the scoped object and the legacy bare array", () => {
    const scoped = { agent: "art_style", questions: [{ id: "q1", question: "视觉基调？", options: [{ label: "写实电影质感", value: "写实电影质感", recommended: true }] }] }
    expect(parseClarifyScope(JSON.stringify(scoped))).toEqual(scoped)
    expect(parseClarifyScope(JSON.stringify(scoped.questions))).toEqual({ agent: undefined, questions: scoped.questions })
    expect(parseClarifyScope("[]")).toBeNull()
    expect(parseClarifyScope("not json")).toBeNull()
    expect(parseClarifyScope(null)).toBeNull()
  })
})
