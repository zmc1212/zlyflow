import { describe, expect, it } from "vitest"
import {
  beatHasWorkshopTriptych,
  workshopH3GenerateLabel,
  workshopH3PromptGate,
} from "./workshop-h3-gate"

const readyBeat = {
  character_ids: ["ast-1"],
  scene_id: "ast-scene",
  triptych_url: "https://img.example/triptych.png",
  triptych_panels: { start: "https://img.example/start.jpg" },
}

describe("workshop H3 prompt gate", () => {
  it("treats start panel or full triptych as ready", () => {
    expect(beatHasWorkshopTriptych({ triptych_url: "https://x/a.png" })).toBe(true)
    expect(beatHasWorkshopTriptych({ triptych_panels: { start: "https://x/start.jpg" } })).toBe(true)
    expect(beatHasWorkshopTriptych({ character_ids: ["a"], scene_id: "s" })).toBe(false)
  })

  it("asks for cast before triptych", () => {
    expect(workshopH3PromptGate({ scene_id: "s" })).toBe("need_cast")
    expect(workshopH3PromptGate({ character_ids: ["a"] })).toBe("need_cast")
  })

  it("blocks prompt generation until triptych exists", () => {
    expect(workshopH3PromptGate({
      character_ids: ["a"],
      scene: "走廊",
    })).toBe("need_triptych")
    expect(workshopH3PromptGate(
      { character_ids: ["a"], scene_id: "s" },
      { triptychGenerating: true },
    )).toBe("triptych_running")
    expect(workshopH3PromptGate({
      character_ids: ["a"],
      scene_id: "s",
      triptych_status: "queued",
    })).toBe("triptych_running")
    expect(workshopH3PromptGate(readyBeat)).toBe("ready")
  })

  it("keeps regenerate label after a prompt already exists", () => {
    expect(workshopH3GenerateLabel({})).toBe("生成 H3 提示词")
    expect(workshopH3GenerateLabel({ hasPrompt: true })).toBe("重新生成")
    expect(workshopH3GenerateLabel({ generating: true, hasPrompt: true })).toBe("生成中")
  })
})
