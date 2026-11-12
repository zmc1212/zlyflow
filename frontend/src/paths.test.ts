import { describe, expect, it } from "vitest"
import {
  director2RedirectTarget,
  isDirectorLegacyStudioPath,
  PATHS,
  ROUTE_PATTERNS,
  STUDIO_ROUTE_PATHS,
  studioWorkspaceFromPath,
  isGuestStudioPath,
  resolveAuthRedirect,
  loginRedirectFrom,
} from "./paths"

describe("studio director routes", () => {
  it("treats /director and leftover /director2 bookmarks as one director workspace", () => {
    expect(studioWorkspaceFromPath("/director")).toBe("director")
    expect(studioWorkspaceFromPath("/director/projects/p1/content")).toBe("director")
    expect(studioWorkspaceFromPath("/director/batch/p1")).toBe("director")
    expect(studioWorkspaceFromPath("/director2")).toBe("director")
    expect(studioWorkspaceFromPath("/director2/projects/p1/content")).toBe("director")
    expect(studioWorkspaceFromPath("/generate/video")).toBe("generate")
    expect(studioWorkspaceFromPath("/canvas")).toBe("canvas")
    expect(studioWorkspaceFromPath("/canvas/canvas_123")).toBe("canvas")
    expect(studioWorkspaceFromPath("/assets")).toBe("assets")
  })

  it("marks only batch / replication as leftover studios", () => {
    expect(isDirectorLegacyStudioPath("/director/batch/p1")).toBe(true)
    expect(isDirectorLegacyStudioPath("/director/replication/p1")).toBe(true)
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

  it("registers the new /director project shell and keeps the two leftover studios", () => {
    expect(STUDIO_ROUTE_PATHS).toContain(PATHS.director)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorDiagnosis)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProject)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectMenu)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectEpisode)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectEdit)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorProjectWorkbench)
    expect(ROUTE_PATTERNS.directorProjectWorkbench).toBe("/director/projects/:projectId/workbench/:episodeId")
    expect(ROUTE_PATTERNS.directorProjectEdit).toBe("/director/projects/:projectId/edit/:episodeId")
    expect(ROUTE_PATTERNS.directorFeatured).toBe("/director/featured/:featuredId")
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorFeatured)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorBatch)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.directorReplication)
    expect(STUDIO_ROUTE_PATHS).not.toContain(ROUTE_PATTERNS.directorLegacyRecipe)
    expect(STUDIO_ROUTE_PATHS).not.toContain(PATHS.director2)
    expect(ROUTE_PATTERNS.directorProject).toBe("/director/projects/:projectId")
    expect(STUDIO_ROUTE_PATHS).toContain(PATHS.canvas)
    expect(STUDIO_ROUTE_PATHS).toContain(PATHS.toolMotionTransfer)
    expect(STUDIO_ROUTE_PATHS).toContain(ROUTE_PATTERNS.canvasProject)
    expect(ROUTE_PATTERNS.canvasProject).toBe("/canvas/:canvasId")
  })
})

describe("guest browsing and sign-in return", () => {
  const guest = { setup_required: false, authenticated: false }
  const location = (pathname: string) => ({ pathname, search: "?view=latest", hash: "#result", state: null })

  it("lets guests browse both creation pages without a login redirect", () => {
    for (const path of [PATHS.home, PATHS.generateVideo, PATHS.generateImage, PATHS.login]) {
      expect(isGuestStudioPath(path)).toBe(true)
      expect(resolveAuthRedirect(guest, location(path))).toBeNull()
    }
  })

  it("keeps private paths gated and preserves their complete return location", () => {
    for (const path of [PATHS.assets, PATHS.director, PATHS.canvas, PATHS.toolMotionTransfer, PATHS.adminAccounts, PATHS.mcpAuthorize, "/generate/video/job-123"]) {
      expect(isGuestStudioPath(path)).toBe(false)
      const redirect = resolveAuthRedirect(guest, location(path))
      expect(redirect?.to).toBe(PATHS.login)
      expect(loginRedirectFrom(redirect?.state)).toBe(`${path}?view=latest#result`)
    }
  })

  it("preserves setup and mandatory password change gates", () => {
    expect(resolveAuthRedirect({ ...guest, setup_required: true }, location(PATHS.generateVideo))?.to).toBe(PATHS.setup)
    const auth = { ...guest, authenticated: true, csrf_token: "csrf", user: {
      id: "u", username: "worker", display_name: "员工", role: "employee" as const,
      is_active: true, must_change_password: true, created_at: "", updated_at: "",
    } }
    expect(resolveAuthRedirect(auth, location(PATHS.generateVideo))?.to).toBe(PATHS.password)
    expect(resolveAuthRedirect({ ...auth, user: { ...auth.user, must_change_password: false } }, location(PATHS.adminAccounts))?.to).toBe(PATHS.generateVideo)
  })

  it("rejects external login destinations and login loops", () => {
    for (const pathname of ["//example.com", "https://example.com", PATHS.login, PATHS.password]) {
      expect(loginRedirectFrom({ from: { pathname } })).toBe(PATHS.generateVideo)
    }
  })
})
