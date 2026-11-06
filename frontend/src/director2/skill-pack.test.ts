import { describe, expect, it } from "vitest"
import type { Director2SkillPack } from "./api"
import {
  HALF_NARRATED_PACK_ID,
  UNBOUND_PACK_SELECT_VALUE,
  createProjectSkillPackExtra,
  defaultCreateSkillPackId,
  packIdFromSelectValue,
  projectBoundSkillPackId,
  selectValueForPackId,
  skillPackAuthor,
  skillPackCardTitle,
  skillPackCoverUrl,
  skillPackDisplayName,
  skillPackPickerOrder,
  skillPackSelectOptions,
} from "./skill-pack"

const unbound: Director2SkillPack = {
  id: "",
  name: "H3 官方六段式",
  summary: "不绑定 Plaza 制作配方，直接按 H3 官方六段式 Skill 用大模型装箱。",
  surfaces: ["workshop"],
  visual_lock: "",
  workshop_shot: [],
  packing_overrides: { skip_program_pack: true },
  confirm_format: {},
}

const half: Director2SkillPack = {
  id: HALF_NARRATED_PACK_ID,
  name: "半解说真人短剧",
  summary: "旁白推进的真人短剧。",
  surfaces: ["director2", "workshop"],
  visual_lock: "photoreal-live-action-short-drama",
  workshop_shot: ["write_timestamped_zh_prompt", "polish_ref2va", "bind_r2v_slots"],
  packing_overrides: {},
  confirm_format: {},
}

describe("skill pack picker helpers", () => {
  it("defaults new projects to half-narrated when the catalog has it", () => {
    expect(defaultCreateSkillPackId([unbound, half])).toBe(HALF_NARRATED_PACK_ID)
    expect(defaultCreateSkillPackId([unbound])).toBe("")
  })

  it("writes extra only when a pack is bound", () => {
    expect(createProjectSkillPackExtra(HALF_NARRATED_PACK_ID)).toEqual({
      skill_pack_id: HALF_NARRATED_PACK_ID,
    })
    expect(createProjectSkillPackExtra("")).toBeUndefined()
  })

  it("reads bound id from project extra", () => {
    expect(projectBoundSkillPackId({ extra: { skill_pack_id: HALF_NARRATED_PACK_ID }, settings: null })).toBe(
      HALF_NARRATED_PACK_ID,
    )
    expect(projectBoundSkillPackId({ extra: null, settings: { extra: { skillPackId: HALF_NARRATED_PACK_ID } } })).toBe(
      HALF_NARRATED_PACK_ID,
    )
    expect(projectBoundSkillPackId({ extra: {}, settings: {} })).toBe("")
  })

  it("maps empty pack id through the Select sentinel", () => {
    expect(selectValueForPackId("")).toBe(UNBOUND_PACK_SELECT_VALUE)
    expect(packIdFromSelectValue(UNBOUND_PACK_SELECT_VALUE)).toBe("")
    expect(packIdFromSelectValue(HALF_NARRATED_PACK_ID)).toBe(HALF_NARRATED_PACK_ID)
    expect(skillPackDisplayName(unbound)).toContain("H3 官方六段式")
    expect(skillPackSelectOptions([unbound, half]).map((item) => item.value)).toEqual([
      UNBOUND_PACK_SELECT_VALUE,
      HALF_NARRATED_PACK_ID,
    ])
  })

  it("only plays http(s) cover videos and titles unbound cards separately", () => {
    expect(skillPackCoverUrl({ cover: "https://cdn.hailuoai.com/demo.mp4" })).toBe("https://cdn.hailuoai.com/demo.mp4")
    expect(skillPackCoverUrl({ cover: "/local/cover.mp4" })).toBe("")
    expect(skillPackCoverUrl({ cover: "javascript:alert(1)" })).toBe("")
    expect(skillPackAuthor({ author: " MiniMax Design " })).toBe("MiniMax Design")
    expect(skillPackCardTitle(unbound)).toBe("H3 官方六段式")
    expect(skillPackCardTitle(half)).toBe("半解说真人短剧")
    expect(skillPackPickerOrder([unbound, half]).map((item) => item.id)).toEqual([HALF_NARRATED_PACK_ID, ""])
  })
})
