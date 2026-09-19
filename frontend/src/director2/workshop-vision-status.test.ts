import { describe, expect, it } from "vitest"
import { workshopPromptAsideLine, workshopVisionStatusLine } from "./workshop-vision-status"

describe("workshopVisionStatusLine", () => {
  it("shows model and image count when vision was used", () => {
    expect(workshopVisionStatusLine({
      vision_status: "used",
      vision_model: "gpt-5.6-sol",
      vision_image_count: 5,
    })).toBe("已看图 · gpt-5.6-sol · 5 张")
  })

  it("does not pretend vision succeeded after a text fallback", () => {
    expect(workshopVisionStatusLine({
      vision_status: "failed_text_fallback",
      vision_model: "gpt-5.6-sol",
      vision_image_count: 5,
    })).toBe("未看图，已用纯文本")
  })

  it("hides the line when there were no images to look at", () => {
    expect(workshopVisionStatusLine({
      vision_status: "unavailable",
      vision_model: "Qwen/Qwen2.5-7B-Instruct",
      vision_image_count: 0,
    })).toBe("")
  })

  it("adds a validation hint when writing failed", () => {
    expect(workshopPromptAsideLine({
      vision_status: "used",
      vision_model: "gpt-5.6-sol",
      vision_image_count: 5,
    }, { failed: true })).toBe("已看图 · gpt-5.6-sol · 5 张 · 写稿未通过校验")
    expect(workshopPromptAsideLine({}, { failed: true })).toBe("写稿未通过校验")
  })
})
