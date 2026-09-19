import { describe, expect, it } from "vitest"
import { director2ContentLibraryDocPath, director2ProjectPath, director2WorkshopEpisodePath } from "./paths"

describe("director2 paths", () => {
  it("opens a content-library document from a shot_plan job", () => {
    expect(director2ProjectPath("proj-1", "content")).toBe("/director2/projects/proj-1/content")
    expect(director2ContentLibraryDocPath("proj-1", "doc-9")).toBe(
      "/director2/projects/proj-1/content?mode=manual&doc=doc-9&tab=episodes",
    )
  })

  it("opens a workshop episode on the dubbing tab", () => {
    expect(director2WorkshopEpisodePath("proj-1", "ep-2")).toBe("/director2/projects/proj-1/workshop/ep-2")
    expect(director2WorkshopEpisodePath("proj-1", "ep-2", "dubbing")).toBe(
      "/director2/projects/proj-1/workshop/ep-2?tab=dubbing",
    )
  })
})
