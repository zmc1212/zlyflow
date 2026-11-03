import { describe, expect, it } from "vitest"
import { assetReadiness, parseProjectPosition, projectStageAccess, resumeProjectPath, type ProjectFlow } from "./project-flow"
import type { Director2Asset, Director2Document, Director2Episode } from "./api"

const empty: ProjectFlow = { documents: [], assets: [], episodes: [] }
describe("project flow and safe restoration", () => {
  it("locks future stages only for an empty project and supports existing production", () => {
    expect(projectStageAccess(empty)).toMatchObject({ assets: false, workshop: false })
    expect(projectStageAccess({ ...empty, documents: [{ raw_text: "正文" } as Director2Document] })).toMatchObject({ assets: true, workshop: false })
    expect(projectStageAccess({ ...empty, episodes: [{ id: "ep" } as Director2Episode] })).toMatchObject({ assets: true, workshop: true })
  })
  it("validates stored navigation and discards unrelated query parameters", () => {
    expect(parseProjectPosition('{"menu":"other"}')).toBeNull()
    expect(parseProjectPosition("invalid")).toBeNull()
    expect(parseProjectPosition(JSON.stringify({ menu: "content", episodeId: "ep", search: "doc=d&section=body&redirect=https://example.com" }))).toEqual({ menu: "content", episodeId: null, search: "doc=d&section=body" })
  })
  it("restores an existing episode and falls back to overview after deletion", () => {
    const flow = { ...empty, episodes: [{ id: "ep" } as Director2Episode] }
    expect(resumeProjectPath("p", flow, { menu: "workshop", episodeId: "ep" })).toBe("/director/projects/p/workshop/ep")
    expect(resumeProjectPath("p", flow, { menu: "workshop", episodeId: "deleted" })).toBe("/director/projects/p/workshop")
    expect(resumeProjectPath("p", empty, { menu: "assets", episodeId: null })).toBe("/director/projects/p/content")
  })
  it("requires every character look to have a real image", () => {
    expect(assetReadiness({ kind: "character", extra: { identities: [{ image_url: "image.jpg" }, { image_url: "" }] } } as unknown as Director2Asset)).toMatchObject({ ready: 1, total: 2, label: "待完善 1 套造型" })
    expect(assetReadiness({ kind: "scene", extra: { master_url: "image.jpg" } } as unknown as Director2Asset).ready).toBe(1)
    expect(assetReadiness({ kind: "character", image_url: "legacy.png", extra: {} } as Director2Asset)).toMatchObject({ ready: 1, total: 1 })
  })
})
