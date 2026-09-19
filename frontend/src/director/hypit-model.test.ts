import { describe, expect, it } from "vitest"
import { directorHypitPath, directorReplicationPath, ROUTE_PATTERNS, STUDIO_ROUTE_PATHS } from "../paths"
import { createEmptyHypit, isHypitPayload, normalizeHypitPayload } from "./hypit-model"
import { createEmptyReplication, isReplicationPayload } from "./replication-model"

describe("hypit_replication payload", () => {
  it("is a distinct kind from VACE shot_replication", () => {
    const hypit = createEmptyHypit("结构复刻")
    const vace = createEmptyReplication("参考片复刻")
    expect(hypit.kind).toBe("hypit_replication")
    expect(vace.kind).toBe("shot_replication")
    expect(isHypitPayload(hypit)).toBe(true)
    expect(isReplicationPayload(hypit)).toBe(false)
    expect(isHypitPayload(vace)).toBe(false)
  })

  it("normalizes brief, language and result urls without inventing VACE shots", () => {
    const payload = normalizeHypitPayload({
      kind: "hypit_replication",
      brief: " 换口播产品名 ",
      language: "en",
      result: { url: "/api/director/hypit/p1/result", buildId: "bld_1" },
    })
    expect(payload.brief).toBe("换口播产品名")
    expect(payload.language).toBe("en")
    expect(payload.result.url).toBe("/api/director/hypit/p1/result")
    expect(payload.transcript.status).toBe("idle")
    expect("shots" in payload).toBe(false)
    expect("renderSettings" in payload).toBe(false)
  })

  it("uses a route that is not the VACE replication studio", () => {
    expect(directorHypitPath("p1")).toBe("/director/hypit/p1")
    expect(directorReplicationPath("p1")).toBe("/director/replication/p1")
    const hypitIndex = STUDIO_ROUTE_PATHS.indexOf(ROUTE_PATTERNS.directorHypit)
    const recipeIndex = STUDIO_ROUTE_PATHS.indexOf(ROUTE_PATTERNS.directorProject)
    expect(hypitIndex).toBeGreaterThanOrEqual(0)
    expect(hypitIndex).toBeLessThan(recipeIndex)
  })
})
