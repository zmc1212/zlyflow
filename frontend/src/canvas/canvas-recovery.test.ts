import { afterEach, describe, expect, it } from "vitest"
import { claimCanvasRecovery, clearCanvasRecovery, readCanvasRecovery, resolveCanvasRecovery, writeCanvasRecovery } from "./canvas-recovery"

const draft = (text: string) => JSON.stringify({ nodes: [{ id: "text", type: "text", position: { x: 0, y: 0 }, data: { text } }], edges: [] })
const values = new Map<string, string>()
const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
afterEach(() => { clearCanvasRecovery("canvas", undefined, storage); values.clear() })

describe("canvas draft recovery", () => {
  it("recovers unsaved edits against the same server version after changing pages", () => {
    writeCanvasRecovery("canvas", { baseVersion: 4, content: draft("离开前的修改") }, storage)
    const recovered = resolveCanvasRecovery(draft("服务端"), 4, readCanvasRecovery("canvas", storage))
    expect(recovered).toMatchObject({ restored: true, conflict: false, baseVersion: 4, content: draft("离开前的修改") })
  })

  it("keeps a different server version in conflict instead of overwriting it", () => {
    const recovered = resolveCanvasRecovery(draft("另一窗口"), 5, { baseVersion: 4, content: draft("本地草稿") })
    expect(recovered).toMatchObject({ restored: true, conflict: true, baseVersion: 4 })
    expect(recovered.content).toBe(draft("本地草稿"))
  })

  it("recognizes that an in-flight save has already reached the server", () => {
    expect(resolveCanvasRecovery(draft("相同内容"), 5, { baseVersion: 4, content: draft("相同内容") }))
      .toMatchObject({ restored: false, conflict: false, baseVersion: 5 })
  })

  it("does not discard a newer local edit when an earlier save completes", () => {
    writeCanvasRecovery("canvas", { baseVersion: 4, content: draft("最新") }, storage)
    clearCanvasRecovery("canvas", draft("较早"), storage)
    expect(readCanvasRecovery("canvas", storage)?.content).toBe(draft("最新"))
    clearCanvasRecovery("canvas", draft("最新"), storage)
    expect(readCanvasRecovery("canvas", storage)).toBeNull()
  })

  it("retains a draft in memory when session storage is unavailable or full", () => {
    const blocked = { ...storage, setItem: () => { throw new Error("QuotaExceededError") } }
    writeCanvasRecovery("canvas", { baseVersion: 1, content: draft("保留") }, blocked)
    expect(readCanvasRecovery("canvas", blocked)?.content).toBe(draft("保留"))
  })

  it("ignores a late failure from an unmounted editor after the user has returned and edited again", () => {
    const old = claimCanvasRecovery("canvas")
    writeCanvasRecovery("canvas", { baseVersion: 3, content: draft("旧页面") }, storage, old)
    const current = claimCanvasRecovery("canvas")
    writeCanvasRecovery("canvas", { baseVersion: 3, content: draft("回来后的最新修改") }, storage, current)
    writeCanvasRecovery("canvas", { baseVersion: 3, content: draft("旧请求失败") }, storage, old)
    expect(readCanvasRecovery("canvas", storage)?.content).toBe(draft("回来后的最新修改"))
  })

  it("ignores malformed or unversioned recovery payloads", () => {
    for (const raw of ["broken", "null", JSON.stringify({ baseVersion: -1, content: draft("a") }), JSON.stringify({ baseVersion: 2, content: "{}" })]) {
      values.set("zly-canvas-recovery:canvas", raw)
      expect(readCanvasRecovery("canvas", storage)).toBeNull()
    }
  })
})
