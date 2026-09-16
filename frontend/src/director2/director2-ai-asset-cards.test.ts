import { describe, expect, it } from "vitest"
import { assetKindFor, normalizeAssetCard, relateLiveAssetCards } from "./panes/Director2AiStudioPane"

describe("director2 AI asset stream mapping", () => {
  it.each([
    ["characters", "characters", "character"],
    ["characters", "props", "prop"],
    ["locations", "locations", "scene"],
  ])("maps %s/%s to %s cards", (agent, field, expected) => {
    expect(assetKindFor(agent, field)).toBe(expected)
  })

  it("normalizes streamed character fields without inventing missing values", () => {
    expect(normalizeAssetCard("character", {
      name: "沈砚",
      role: "男主",
      fixed_props: ["旧书箱"],
      description: "清瘦少年",
    })).toEqual({
      kind: "character",
      name: "沈砚",
      role: "男主",
      fixedProps: ["旧书箱"],
      description: "清瘦少年",
    })
  })

  it("localizes gender enums and hides unspecified", () => {
    expect(normalizeAssetCard("character", { name: "阿强", gender: "unspecified" })).toEqual({
      kind: "character",
      name: "阿强",
    })
    expect(normalizeAssetCard("character", { name: "小王", gender: "male" })?.gender).toBe("男")
    expect(normalizeAssetCard("character", { name: "苏婉", gender: "female" })?.gender).toBe("女")
    expect(normalizeAssetCard("character", { name: "阿宁", gender: "nonbinary" })?.gender).toBe("非二元")
  })

  it("maps live recipe fields onto content-library card data", () => {
    expect(normalizeAssetCard("character", {
      name: "阿强",
      role: "夜班保安",
      gender: "male",
      promptText: "a young night-shift security guard",
      identitySpec: { ageRange: "28岁", immutableAccessories: "手电筒、对讲机" },
      description: "年轻保安，手持手电筒巡逻。",
    })).toEqual({
      kind: "character",
      name: "阿强",
      role: "夜班保安",
      age: "28岁",
      gender: "男",
      fixedProps: ["手电筒", "对讲机"],
      description: "年轻保安，手持手电筒巡逻。",
      visualPrompt: "a young night-shift security guard",
    })
  })

  it("maps scene promptText and prop relations without inventing counts", () => {
    expect(normalizeAssetCard("scene", {
      name: "旧商场",
      type: "固定场景",
      description: "空旷过道与熄灭的橱窗。",
      promptText: "empty mall corridor at night",
      elements: ["橱窗", "手扶电梯"],
    })).toEqual({
      kind: "scene",
      name: "旧商场",
      sceneType: "固定场景",
      description: "空旷过道与熄灭的橱窗。",
      elements: ["橱窗", "手扶电梯"],
      visualPrompt: "empty mall corridor at night",
    })
    expect(normalizeAssetCard("prop", { name: "手电筒", description: "保安巡逻用" })).toEqual({
      kind: "prop",
      name: "手电筒",
      description: "保安巡逻用",
    })
  })

  it("links live props to characters when the name appears in fixed props", () => {
    expect(relateLiveAssetCards([
      { kind: "character", name: "阿强", fixedProps: ["手电筒"], description: "夜班保安" },
      { kind: "prop", name: "手电筒", description: "巡逻手电" },
      { kind: "prop", name: "储物柜", description: "商场后勤柜" },
    ])).toEqual([
      { kind: "character", name: "阿强", fixedProps: ["手电筒"], description: "夜班保安" },
      { kind: "prop", name: "手电筒", description: "巡逻手电", propKind: "人物固定道具", relatedCharacter: "阿强" },
      { kind: "prop", name: "储物柜", description: "商场后勤柜", propKind: "场景陈设道具" },
    ])
  })

  it("rejects streamed asset objects without a usable name", () => {
    expect(normalizeAssetCard("prop", { description: "无名称道具" })).toBeNull()
  })
})
