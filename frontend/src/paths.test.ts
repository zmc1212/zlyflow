import { describe, expect, it } from "vitest"
import {
  director2RedirectTarget,
  isDirectorLegacyStudioPath,
  PATHS,
  ROUTE_PATTERNS,
  STUDIO_ROUTE_PATHS,
  studioWorkspaceFromPath,
} from "./paths"

describe("studio director routes", () => {
  it("treats /director and leftover /director2 bookmarks as one director workspace", () => {
    expect(studioWorkspaceFromPath("/director")).toBe("director")
    expect(studioWorkspaceFromPath("/director/projects/p1/content")).toBe("director")
    expect(studioWorkspaceFromPath("/director/batch/p1")).toBe("director")
    expect(studioWorkspaceFromPath("/director2")).toBe("director")
    expect(studioWorkspaceFromPath("/director2/projects/p1/content")).toBe("director")
    expect(studioWorkspaceFromPath("/generate/video")).toBe("generate")
    expect(studioWorkspaceFromPath("/assets")).toBe("assets")
  })

  it("marks only batch / replication / hypit as leftover studios", () => {
    expect(isDirectorLegacyStudioPath("/director/batch/p1")).toBe(true)
    expect(isDirectorLegacyStudioPath("/director/replication/p1")).toBe(true)
    expect(isDirectorLegacyStudioPath("/director/hypit/p1")).toBe(true)
    expect(isDirectorLegacyStudioPath("/director")).toBe(false)
    expect(isDirectorLegacyStudioPath("/director/projects/p1/content")).toBe(false)
    expect(isDirectorLegacyStudioPath("/director/old-recipe")).toBe(false)
  })

  it("rewrites /director2 bookmarks onto /director and keeps query", () => {
    expect(director2RedirectTarget({ pathname: "/director2", search: "", hash: "" })).toBe("/director")
    expect(director2RedirectTarget({
      pathname: "/director2/projects/p1/content",
      search: "?mode=manual",
      hash: "#jobs",
    })).toBe("/director/projects/p1/content?mode=manual#jobs")
  })

  it("registers the new /director project shell and keeps the three leftover studios", () => {
    expect(STUDIO_ROUTE_PATHS).toContain(PATHS.director)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProject)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectMenu)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectEpisode)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorBatch)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorReplication)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorHypit)
    expect(STUDIO_ROUTE_PATHS).not.toContain(ROUTE_PATTERNS.directorLegacyRecipe)
    expect(STUDIO_ROUTE_PATHS).not.toContain(PATHS.director2)
    expect(ROUTE_PATTERNS.directorProject).toBe("/director/projects/:projectId")
  })
})
