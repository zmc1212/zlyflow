import { describe, expect, it } from "vitest"
import {
  VOICE_EXTRACT_HINT,
  clampVoiceExtractWindow,
  isVoiceExtractWindowValid,
  voiceExtractSourceLabel,
} from "./voice-extract-window"

describe("voice extract window", () => {
  it("clamps to 1–15 seconds and the shot duration", () => {
    expect(clampVoiceExtractWindow(0, 20, 8)).toEqual([0, 8])
    expect(clampVoiceExtractWindow(0, 20, 30)).toEqual([0, 15])
    expect(clampVoiceExtractWindow(10, 30, 30)).toEqual([10, 25])
    expect(clampVoiceExtractWindow(2, 2.2, 8)).toEqual([2, 3])
    expect(clampVoiceExtractWindow(7.5, 7.6, 8)).toEqual([7, 8])
  })

  it("rejects unmarked, too short, too long, and out-of-range windows", () => {
    expect(isVoiceExtractWindowValid(0, 0, 8)).toBe(false)
    expect(isVoiceExtractWindowValid(0, 0.4, 8)).toBe(false)
    expect(isVoiceExtractWindowValid(0, 16, 20)).toBe(false)
    expect(isVoiceExtractWindowValid(0, 9, 8)).toBe(false)
    expect(isVoiceExtractWindowValid(3.2, 6.5, 8)).toBe(true)
    expect(VOICE_EXTRACT_HINT).toContain("框选")
  })

  it("labels multi-speaker shots without using the first seconds", () => {
    expect(voiceExtractSourceLabel({
      episode_num: 1,
      seq: "1",
      line_preview: "大爷，我什么都可以做。",
    })).toBe("第1集 · 镜1 · 大爷，我什么都可以做。")
  })
})
