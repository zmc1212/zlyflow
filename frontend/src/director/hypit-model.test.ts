import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { directorHypitPath, directorReplicationPath, ROUTE_PATTERNS, STUDIO_ROUTE_PATHS } from "../paths"
import { createEmptyHypit, conflictingDirectorOperationId, hypitResumeFromProject, hypitStatusLineFromPayload, isHypitPayload, normalizeHypitPayload } from "./hypit-model"
import { createEmptyReplication, isReplicationPayload } from "./replication-model"

const here = dirname(fileURLToPath(import.meta.url))

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
    expect(payload.h3Quality).toBe("safe")
    expect("shots" in payload).toBe(false)
    expect("renderSettings" in payload).toBe(false)
  })

  it("keeps running compile progress so the studio can restore the bar after a reload", () => {
    const payload = normalizeHypitPayload({
      kind: "hypit_replication",
      compile: { status: "running", operationId: "director-op-abc", progress: 55, message: "正在编译；H3 走局域网" },
    })
    expect(payload.compile.status).toBe("running")
    expect(payload.compile.operationId).toBe("director-op-abc")
    expect(payload.compile.progress).toBe(55)
    expect(payload.compile.message).toBe("正在编译；H3 走局域网")
    expect(hypitStatusLineFromPayload(payload)).toEqual({
      progress: 55,
      message: "正在编译；H3 走局域网",
    })
  })

  it("resumes an in-flight Hypit operation from active_operation or payload.operationId", () => {
    expect(hypitResumeFromProject({
      payload: { kind: "hypit_replication", compile: { status: "running", progress: 28, message: "正在 plan" } },
      active_operation: { id: "director-op-1", kind: "hypit_compile", status: "running", progress: 20 },
    })).toEqual({
      operationId: "director-op-1",
      progress: 28,
      message: "正在 plan",
    })
    expect(hypitResumeFromProject({
      payload: {
        kind: "hypit_replication",
        compile: { status: "running", operationId: "director-op-2", progress: 40, message: "H3 sampling" },
      },
    })).toBeNull()
    expect(hypitResumeFromProject({
      payload: { kind: "hypit_replication", compile: { status: "done", progress: 100, message: "成片已导出" } },
    })).toBeNull()
    expect(conflictingDirectorOperationId(new Error("工程已有未完成的导演操作：director-op-deadbeef"))).toBe("director-op-deadbeef")
  })

  it("keeps an explicit H3 quality preset and rejects unknown values", () => {
    expect(normalizeHypitPayload({ kind: "hypit_replication", h3Quality: "official" }).h3Quality).toBe("official")
    expect(normalizeHypitPayload({ kind: "hypit_replication", h3Quality: "0.98" }).h3Quality).toBe("safe")
    expect(createEmptyHypit().h3Quality).toBe("safe")
  })

  it("uses a route that is not the VACE replication studio", () => {
    expect(directorHypitPath("p1")).toBe("/director/hypit/p1")
    expect(directorReplicationPath("p1")).toBe("/director/replication/p1")
    const hypitIndex = STUDIO_ROUTE_PATHS.indexOf(ROUTE_PATTERNS.directorHypit)
    const projectIndex = STUDIO_ROUTE_PATHS.indexOf(ROUTE_PATTERNS.directorProject)
    expect(hypitIndex).toBeGreaterThanOrEqual(0)
    expect(projectIndex).toBeGreaterThanOrEqual(0)
    expect(STUDIO_ROUTE_PATHS).not.toContain(ROUTE_PATTERNS.directorLegacyRecipe)
  })

  it("loads guided-flow.css from the studio module so Hypit dual-column layout survives a hard refresh", () => {
    const moduleSource = readFileSync(resolve(here, "./DirectorStudioModule.tsx"), "utf8")
    const css = readFileSync(resolve(here, "./guided-flow.css"), "utf8")
    expect(moduleSource).toContain('import "./guided-flow.css"')
    expect(css).toContain(".replication-layout")
    expect(css).toContain("grid-template-columns: 320px minmax(0, 1fr)")
  })
})
