import { describe, expect, it } from "vitest"
import { workshopNextAction, workshopVideoBlockReason } from "./workshop-ui-state"

const ready = { hasPlan: true, busy: false, dirty: false, sourceChanged: false, referencesMissing: false, shots: [{ id: "a", sequence: 1, h3_prompt_reference_state: "current" }, { id: "b", sequence: 2, h3_prompt_reference_state: "current" }], prompts: { a: { h3_prompt: "甲" }, b: { h3_prompt: "乙" } } }
describe("workshop generation readiness", () => {
  it("allows a fully checked group", () => expect(workshopVideoBlockReason(ready)).toBe(""))
  it.each([
    [{ hasPlan: false }, "镜头规划"],
    [{ busy: true }, "正在提交"],
    [{ dirty: true }, "先保存"],
    [{ sourceChanged: true }, "来源剧本"],
    [{ referencesMissing: true }, "参考素材"],
    [{ shots: [] }, "选择一个镜头"],
    [{ prompts: { a: { h3_prompt: "甲" } } }, "镜头 2"],
    [{ prompts: { a: { h3_prompt: " " }, b: { h3_prompt: "乙" } } }, "镜头 1"],
    [{ prompts: { a: {} as any, b: { h3_prompt: "乙" } } }, "镜头 1"],
    [{ prompts: { a: null as any, b: { h3_prompt: "乙" } } }, "镜头 1"],
    [{ shots: [{ id: "b", sequence: 2, h3_prompt_reference_state: "stale" }] }, "重新检查"],
    [{ shots: [{ id: "b", sequence: 2 }] }, "重新检查"],
  ])("explains the block without hiding it: %j", (change, expected) => expect(workshopVideoBlockReason({ ...ready, ...change })).toContain(expected))
  it("checks all shots in the generation scope, not only the active shot", () => {
    expect(workshopVideoBlockReason({ ...ready, prompts: { a: ready.prompts.a } })).toContain("镜头 2")
    expect(ready.shots).toHaveLength(2)
  })
})
describe("workshop next action priority", () => {
  const state = { hasPlan: true, dirty: false, pending: false, hasPrompt: true, videoBlocked: false }
  it.each([
    [{ hasPlan: false }, "plan"],
    [{ dirty: true, pending: true }, "save"],
    [{ dirty: true, hasPlan: false }, "save"],
    [{ pending: true }, "review"],
    [{ hasPrompt: false }, "write"],
    [{ videoBlocked: true }, "check"],
    [{}, "generate"],
  ])("guides the next action: %j", (change, expected) => expect(workshopNextAction({ ...state, ...change })).toBe(expected))
})
