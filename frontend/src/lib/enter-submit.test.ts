import { describe, expect, it } from "vitest"
import { isSubmitEnter } from "./enter-submit"

function enterEvent(init: { key?: string; shiftKey?: boolean; altKey?: boolean; isComposing?: boolean; keyCode?: number }) {
  return {
    key: init.key ?? "Enter",
    shiftKey: Boolean(init.shiftKey),
    altKey: Boolean(init.altKey),
    nativeEvent: { isComposing: Boolean(init.isComposing), keyCode: init.keyCode ?? 13 } as KeyboardEvent,
  }
}

describe("isSubmitEnter", () => {
  it("plain Enter submits", () => {
    expect(isSubmitEnter(enterEvent({}))).toBe(true)
  })

  it("Ctrl / ⌘ + Enter still submits", () => {
    expect(isSubmitEnter(enterEvent({ keyCode: 13, altKey: false }))).toBe(true)
  })

  it("Shift / Alt + Enter keeps the newline", () => {
    expect(isSubmitEnter(enterEvent({ shiftKey: true }))).toBe(false)
    expect(isSubmitEnter(enterEvent({ altKey: true }))).toBe(false)
  })

  it("does not fire during IME composition or the composition-confirm keydown", () => {
    expect(isSubmitEnter(enterEvent({ isComposing: true }))).toBe(false)
    expect(isSubmitEnter(enterEvent({ keyCode: 229 }))).toBe(false)
  })

  it("ignores other keys", () => {
    expect(isSubmitEnter(enterEvent({ key: "Escape" }))).toBe(false)
  })
})
