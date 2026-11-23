import { describe, expect, it, vi } from "vitest"
import { directorCanvasPath, isDirectorCanvasPath, openDirectorCanvasWindow } from "./director-canvas-window"

describe("director asset canvas window path", () => {
  it("builds the standalone canvas path for a project", () => {
    expect(directorCanvasPath("proj-1")).toBe("/director/projects/proj-1/assets/canvas")
  })

  it("escapes the project id and carries the focused asset and node", () => {
    expect(directorCanvasPath("proj/1", { assetId: "a-1", nodeId: "n-2" }))
      .toBe("/director/projects/proj%2F1/assets/canvas?asset=a-1&node=n-2")
    expect(directorCanvasPath("proj-1", { assetId: "a-1" }))
      .toBe("/director/projects/proj-1/assets/canvas?asset=a-1")
  })

  it("only accepts the standalone canvas path", () => {
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets/canvas")).toBe(true)
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets/canvas/")).toBe(true)
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets/canvas?asset=a-1")).toBe(true)
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets")).toBe(false)
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets?view=canvas")).toBe(false)
    expect(isDirectorCanvasPath("/director/projects/proj-1/assets/canvas/extra")).toBe(false)
  })

  it("opens the canvas in a new browser window", () => {
    const focus = vi.fn()
    const open = vi.fn(() => ({ focus }) as unknown as Window)
    expect(openDirectorCanvasWindow("/director/projects/proj-1/assets/canvas", open)).toBe(true)
    expect(open).toHaveBeenCalledWith("/director/projects/proj-1/assets/canvas", "_blank")
    expect(focus).toHaveBeenCalled()
  })

  it("reports a blocked popup so the caller can fall back to in-page navigation", () => {
    const open = vi.fn(() => null)
    expect(openDirectorCanvasWindow("/director/projects/proj-1/assets/canvas", open)).toBe(false)
    expect(open).toHaveBeenCalledTimes(1)
  })

  it("never opens the embedded asset list in a new window", () => {
    const open = vi.fn(() => null)
    expect(openDirectorCanvasWindow("/director/projects/proj-1/assets", open)).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })
})
