import { describe, expect, it } from "vitest"
import { materialAdopted, materialsForUnit, productionFilm, type ProductionState, type ProductionMaterial } from "./production"

const base = { id: "base", plan_key: "p1", unit_ids: ["s1", "s2", "s3"], url: "base" } as ProductionMaterial
const next = { id: "next", plan_key: "p1", unit_ids: ["s2"], url: "next" } as ProductionMaterial
const state = { plan_key: "p1", materials: [base, next, { ...next, id: "history", plan_key: "p0" }],
  adopted: { s1: "base", s2: "next", s3: "base" }, exports: [{ url: "old" }], legacy_exports: [{ url: "legacy" }], current_export: null } as unknown as ProductionState

describe("production adoption and preview", () => {
  it("keeps partially superseded whole-film take available without marking it fully adopted", () => {
    expect(materialAdopted(state, base)).toBe(false)
    expect(materialAdopted(state, next)).toBe(true)
    expect(materialsForUnit(state, "s2").map(m => m.id)).toEqual(["next", "base"])
    expect(materialsForUnit(state, "s3").map(m => m.id)).toEqual(["base"])
  })
  it("retains prior film until a current export exists", () => {
    expect(productionFilm(state)?.url).toBe("old")
    expect(productionFilm({ ...state, current_export: { url: "current" } })?.url).toBe("current")
    expect(productionFilm({ ...state, exports: [] })?.url).toBe("legacy")
  })
})
