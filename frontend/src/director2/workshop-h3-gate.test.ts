import { describe, expect, it } from "vitest"
import {
  beatsMissingH3Prompt,
  workshopH3GenerateLabel,
  workshopH3PromptGate,
} from "./workshop-h3-gate"

const readyBeat = {
  character_ids: ["ast-1"],
  scene_id: "ast-scene",
}

describe("workshop H3 prompt gate", () => {
  it("asks for cast before writing the prompt", () => {
    expect(workshopH3PromptGate({ scene_id: "s" })).toBe("need_cast")
    expect(workshopH3PromptGate({ character_ids: ["a"] })).toBe("need_cast")
    expect(workshopH3PromptGate({ character_ids: ["a"], scene: "走廊" })).toBe("ready")
    expect(workshopH3PromptGate(null)).toBe("need_cast")
  })

  it("never blocks on keyframes", () => {
    expect(workshopH3PromptGate({ character_ids: ["a"], scene_id: "s" })).toBe("ready")
    expect(workshopH3PromptGate(readyBeat)).toBe("ready")
  })

  it("keeps regenerate label after a prompt already exists", () => {
    expect(workshopH3GenerateLabel({})).toBe("生成 H3 提示词")
    expect(workshopH3GenerateLabel({ hasPrompt: true })).toBe("重新生成")
    expect(workshopH3GenerateLabel({ generating: true, hasPrompt: true })).toBe("生成中")
  })

  it("lists the beats that still have no saved H3 prompt", () => {
    expect(beatsMissingH3Prompt([{ h3_prompt: "six sections" }, { h3_prompt: "  " }, {}])).toEqual([
      { h3_prompt: "  " },
      {},
    ])
    expect(beatsMissingH3Prompt([])).toEqual([])
  })
})
