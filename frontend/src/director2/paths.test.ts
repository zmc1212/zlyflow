import { describe, expect, it } from "vitest"
import {
  DIRECTOR2_PREFIX,
  director2ContentLibraryDocPath,
  director2HomePath,
  director2ProjectPath,
  director2WorkshopEpisodePath,
  parseDirector2Path,
} from "./paths"

describe("director2 paths", () => {
  it("uses /director as the studio prefix", () => {
    expect(DIRECTOR2_PREFIX).toBe("/director")
    expect(director2HomePath()).toBe("/director")
  })

  it("opens a content-library document from a shot_plan job", () => {
    expect(director2ProjectPath("proj-1", "content")).toBe("/director/projects/proj-1/content")
    expect(director2ContentLibraryDocPath("proj-1", "doc-9")).toBe(
      "/director/projects/proj-1/content?mode=manual&doc=doc-9&tab=episodes",
    )
  })

  it("opens a workshop episode on the dubbing tab", () => {
    expect(director2WorkshopEpisodePath("proj-1", "ep-2")).toBe("/director/projects/proj-1/workshop/ep-2")
    expect(director2WorkshopEpisodePath("proj-1", "ep-2", "dubbing")).toBe(
      "/director/projects/proj-1/workshop/ep-2?tab=dubbing",
    )
  })

  it("parses home and project menus under /director", () => {
    expect(parseDirector2Path("/director")).toEqual({ kind: "home" })
    expect(parseDirector2Path("/director/projects/proj-1/workshop/ep-2")).toEqual({
      kind: "project",
      projectId: "proj-1",
      menu: "workshop",
      episodeId: "ep-2",
    })
  })
})
