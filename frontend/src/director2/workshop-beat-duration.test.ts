import { describe, expect, it } from "vitest"
import {
  beatDurationSec,
  formatBeatDurationLabel,
  formatBeatDurationZh,
  sumBeatDurationSec,
} from "./workshop-beat-duration"

describe("workshop beat duration", () => {
  it("uses stored seconds and falls back to 8", () => {
    expect(beatDurationSec("11")).toBe(11)
    expect(beatDurationSec(5)).toBe(5)
    expect(beatDurationSec("")).toBe(8)
    expect(beatDurationSec(undefined)).toBe(8)
  })

  it("clamps MiniMax H3 range", () => {
    expect(beatDurationSec(1)).toBe(2)
    expect(beatDurationSec(20)).toBe(15)
  })

  it("formats labels for tiles and inspector", () => {
    expect(formatBeatDurationLabel("11")).toBe("11s")
    expect(formatBeatDurationZh("11")).toBe("11秒")
  })

  it("sums episode beats", () => {
    expect(sumBeatDurationSec([{ video_duration: "11" }, { video_duration: "8" }, {}])).toBe(27)
  })
})
