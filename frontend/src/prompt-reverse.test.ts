import { describe, expect, it } from "vitest"
import { normalizePromptReverseResult, promptReverseImageError } from "./prompt-reverse"

function imageFile(name: string, type: string, size: number): File {
  return new File([new ArrayBuffer(size)], name, { type })
}

describe("promptReverseImageError", () => {
  it("accepts normal image files", () => {
    expect(promptReverseImageError(imageFile("ref.png", "image/png", 1024))).toBeNull()
    expect(promptReverseImageError(imageFile("ref.webp", "image/webp", 1024))).toBeNull()
  })

  it("rejects non-image files", () => {
    expect(promptReverseImageError(imageFile("note.txt", "text/plain", 10))).toContain("图片")
  })

  it("rejects oversized images", () => {
    expect(promptReverseImageError(imageFile("big.png", "image/png", 9 * 1024 * 1024))).toContain("8MB")
  })
})

describe("normalizePromptReverseResult", () => {
  it("keeps both prompts when present", () => {
    expect(normalizePromptReverseResult({ chinese_prompt: " 雨夜霓虹街头 ", english_prompt: "Neon street" }))
      .toEqual({ chinese_prompt: "雨夜霓虹街头", english_prompt: "Neon street" })
  })

  it("falls back to the other language when one is missing", () => {
    expect(normalizePromptReverseResult({ chinese_prompt: "雪原日落", english_prompt: "  " }))
      .toEqual({ chinese_prompt: "雪原日落", english_prompt: "雪原日落" })
    expect(normalizePromptReverseResult({ chinese_prompt: "", english_prompt: "sunset" }))
      .toEqual({ chinese_prompt: "sunset", english_prompt: "sunset" })
  })

  it("rejects empty or malformed payloads", () => {
    expect(() => normalizePromptReverseResult(null)).toThrow()
    expect(() => normalizePromptReverseResult({ chinese_prompt: "", english_prompt: "" })).toThrow()
    expect(() => normalizePromptReverseResult("text")).toThrow()
  })
})
