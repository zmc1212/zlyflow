import { describe, expect, it } from "vitest"
import {
  workshopBeatHasSplitTakes,
  workshopBeatLabel,
  workshopStoryShot,
} from "./workshop-beat-label"

describe("workshopBeatLabel", () => {
  it("keeps the story shot number for an unsplit beat", () => {
    expect(workshopBeatLabel({ sequence: 3, story_shot: 3 })).toBe("镜头3")
    expect(workshopStoryShot({ sequence: 8 })).toBe(8)
  })

  it("shows production take role without dropping the story shot", () => {
    expect(workshopBeatLabel({ sequence: 2, story_shot: 1, take_role: "inner_hold" })).toBe("镜头1 · 内心覆盖")
    expect(workshopBeatLabel({ sequence: 1, story_shot: 1, take_role: "lipsync" })).toBe("镜头1 · 口型")
    expect(workshopBeatLabel({ sequence: 3, story_shot: 1, take_role: "push_close" })).toBe("镜头1 · 近景定性")
  })

  it("detects split production takes", () => {
    const parent = { id: "beat-1", sequence: 1, take_role: "lipsync" }
    const child = { id: "beat-1b", sequence: 2, parent_beat_id: "beat-1", take_role: "inner_hold", story_shot: 1 }
    expect(workshopBeatHasSplitTakes(parent, [parent, child])).toBe(true)
    expect(workshopBeatHasSplitTakes(child, [parent, child])).toBe(true)
    expect(workshopBeatHasSplitTakes({ id: "beat-2", sequence: 3 }, [parent, child])).toBe(false)
  })
})
