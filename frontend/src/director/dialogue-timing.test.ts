import { describe, expect, it } from "vitest"

import { dialogueTimingWarning, estimateDialogueDurationSec, estimateShotDurationSec } from "./dialogue-timing"

describe("dialogue-timing", () => {
  it("estimates Chinese dialogue at about 4 chars per second", () => {
    expect(estimateDialogueDurationSec("一二三四五六七八九十")).toBeCloseTo(2.5, 1)
  })

  it("recommends longer shots when dialogue exceeds duration", () => {
    expect(dialogueTimingWarning("一二三四五六七八九十", 5)).toBeNull()
    expect(dialogueTimingWarning("一二三四五六七八九十", 2)).toMatch(/建议时长/)
  })

  it("budgets action beats into shot duration", () => {
    expect(estimateShotDurationSec("", 3)).toBeGreaterThanOrEqual(6)
  })
})
