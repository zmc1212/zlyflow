import { describe, expect, it } from "vitest"
import {
  beatLookEra,
  beatLookEraWarning,
  inferCharacterLookId,
  lookOptionEra,
  triptychLooksStaleWarning,
} from "./workshop-look-era"

const ancientLook = {
  value: "ident-1",
  label: "沈砚 (日常/初始造型)",
  description: "17岁古代少年，粗布长衫",
}
const modernLook = {
  value: "ident-modern",
  label: "沈砚 (现代26岁)",
  description: "26岁硕士研究生，白色衬衫",
}
const modernBeat = { scene: "现代大学图书馆深夜", speaker: "现代26岁沈砚", heading: "深夜研读古籍" }

describe("workshop look era", () => {
  it("treats a modern library beat as modern even if the prompt mentions ancient texts", () => {
    expect(beatLookEra({
      heading: "深夜研读古籍 · 现代大学图书馆深夜",
      scene: "现代大学图书馆深夜",
      speaker: "现代26岁沈砚",
      visual_prompt: "26岁硕士研究生研究古代文献",
    })).toBe("modern")
  })

  it("treats a thatched-cottage beat as ancient", () => {
    expect(beatLookEra({
      heading: "破屋惊醒见母亲 · 破旧茅屋",
      scene: "破旧茅屋",
      speaker: "沈砚",
    })).toBe("ancient")
  })

  it("infers the modern sheet for a library beat without an explicit pick", () => {
    expect(inferCharacterLookId([ancientLook, modernLook], modernBeat)).toBe("ident-modern")
  })

  it("does not fall back to the ancient sheet when the beat is modern", () => {
    expect(inferCharacterLookId([ancientLook], modernBeat)).toBe("")
  })

  it("keeps an explicit look even if it is the other era", () => {
    expect(inferCharacterLookId([ancientLook, modernLook], modernBeat, "ident-1")).toBe("ident-1")
  })

  it("warns when the only look is the opposite era and nothing is selected", () => {
    const warning = beatLookEraWarning(modernBeat, [ancientLook], "")
    expect(warning).toContain("现代")
    expect(warning).toContain("资产库")
    expect(lookOptionEra(ancientLook)).toBe("ancient")
  })

  it("does not warn after the user explicitly picks a look", () => {
    expect(beatLookEraWarning(modernBeat, [ancientLook], "ident-1")).toBe("")
  })

  it("warns when an existing triptych was generated without a look snapshot", () => {
    expect(triptychLooksStaleWarning(
      { triptych_url: "https://x/triptych.png", character_ids: ["char-1"] },
      { "char-1": "ident-modern" },
    )).toContain("没有锁定")
  })

  it("warns when the triptych look no longer matches the current sheet", () => {
    expect(triptychLooksStaleWarning(
      {
        triptych_url: "https://x/triptych.png",
        character_ids: ["char-1"],
        triptych_look_ids: { "char-1": "ident-1" },
      },
      { "char-1": "ident-modern" },
    )).toContain("另一套角色造型")
  })

  it("does not warn when the triptych snapshot matches the current look", () => {
    expect(triptychLooksStaleWarning(
      {
        triptych_panels: { start: "https://x/start.png" },
        character_ids: ["char-1"],
        triptych_look_ids: { "char-1": "ident-modern" },
      },
      { "char-1": "ident-modern" },
    )).toBe("")
  })
})
