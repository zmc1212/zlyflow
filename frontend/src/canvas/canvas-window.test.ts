import { describe, expect, it, vi } from "vitest"
import { isCanvasEditorPath, leaveCanvasEditor, openCanvasEditorWindow } from "./canvas-window"

describe("canvas editor window routing", () => {
  it("treats only the canvas editor path as a standalone window page", () => {
    expect(isCanvasEditorPath("/canvas/abc")).toBe(true)
    expect(isCanvasEditorPath("/canvas/abc/")).toBe(true)
    expect(isCanvasEditorPath("/canvas/abc?asset=job-1&index=0")).toBe(true)
    expect(isCanvasEditorPath("/canvas")).toBe(false)
    expect(isCanvasEditorPath("/canvas/")).toBe(false)
    expect(isCanvasEditorPath("/canvas/abc/extra")).toBe(false)
    expect(isCanvasEditorPath("/director/projects/abc/assets")).toBe(false)
  })

  it("opens the editor in a new browser window", () => {
    const focus = vi.fn()
    const open = vi.fn(() => ({ focus }) as unknown as Window)
    expect(openCanvasEditorWindow("/canvas/abc", open)).toBe(true)
    expect(open).toHaveBeenCalledWith("/canvas/abc", "_blank")
    expect(focus).toHaveBeenCalled()
  })

  it("reports a blocked popup so the caller can fall back to in-page navigation", () => {
    const open = vi.fn(() => null)
    expect(openCanvasEditorWindow("/canvas/abc", open)).toBe(false)
    expect(open).toHaveBeenCalledTimes(1)
  })

  it("never opens a non-editor path in a new window", () => {
    const open = vi.fn(() => null)
    expect(openCanvasEditorWindow("/canvas", open)).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })
})

describe("leaving the canvas editor window", () => {
  it("closes the window when the list page opened it", () => {
    const close = vi.fn()
    const fallback = vi.fn()
    leaveCanvasEditor({ opener: {}, close } as unknown as Window, fallback)
    expect(close).toHaveBeenCalledTimes(1)
    expect(fallback).not.toHaveBeenCalled()
  })

  it("returns to the canvas list inside the current window otherwise", () => {
    const close = vi.fn()
    const fallback = vi.fn()
    leaveCanvasEditor({ opener: null, close } as unknown as Window, fallback)
    expect(close).not.toHaveBeenCalled()
    expect(fallback).toHaveBeenCalledTimes(1)
  })
})
