import { describe, expect, it } from "vitest"
import { ApiRequestError } from "../api"
import {
  CANVAS_CONTENT_LIMIT_BYTES,
  CANVAS_CONTENT_WARN_BYTES,
  CANVAS_SAVE_RETRY_DELAYS_MS,
  CANVAS_VIRTUALIZE_NODE_LIMIT,
  canvasByteSize,
  canvasConflictVersion,
  canvasContentSizeLevel,
  createCanvasSaveQueue,
  formatCanvasBytes,
  isCanvasSaveRetryable,
  nextCanvasSaveRetryDelay,
  saveStateAfterCanvasEdit,
  saveStateAfterCanvasSave,
  shouldVirtualizeCanvasNodes,
} from "./canvas-save"

describe("canvas save queue", () => {
  it("saves the latest edits made while a previous request is pending before leaving", async () => {
    let release!: () => void
    const first = new Promise<void>((resolve) => { release = resolve })
    let content = "before"
    const saved: string[] = []
    const save = createCanvasSaveQueue(async () => {
      const snapshot = content
      if (!saved.length) await first
      saved.push(snapshot)
      return snapshot === content ? "saved" : "dirty"
    })
    const automatic = save()
    content = "last edit before leaving"
    const leaving = save()
    release()
    expect(await leaving).toBe(true)
    expect(await automatic).toBe(true)
    expect(saved).toEqual(["before", "last edit before leaving"])
  })

  it("keeps concurrent save callers on one request and allows another save afterwards", async () => {
    let count = 0
    const save = createCanvasSaveQueue(async () => { count += 1; return "saved" })
    expect(await Promise.all([save(), save(true), save()])).toEqual([true, true, true])
    expect(count).toBe(1)
    expect(await save()).toBe(true)
    expect(count).toBe(2)
  })

  it("stops on a conflict or failed request so navigation can remain in the editor", async () => {
    let count = 0
    const save = createCanvasSaveQueue(async () => { count += 1; return "failed" })
    expect(await save()).toBe(false)
    expect(count).toBe(1)
  })

  it("releases the queue after an unexpected rejection so a later retry works", async () => {
    let failed = true
    const save = createCanvasSaveQueue(async () => {
      if (failed) throw new Error("offline")
      return "saved"
    })
    await expect(save()).rejects.toThrow("offline")
    failed = false
    expect(await save()).toBe(true)
  })
})

function apiError(status: number, body: unknown = null) {
  return new ApiRequestError(status, body)
}

describe("canvas save retry policy", () => {
  it("uses 2s, 5s and 10s for three retries and then stops", () => {
    expect([...CANVAS_SAVE_RETRY_DELAYS_MS]).toEqual([2000, 5000, 10000])
    expect(nextCanvasSaveRetryDelay(0)).toBe(2000)
    expect(nextCanvasSaveRetryDelay(1)).toBe(5000)
    expect(nextCanvasSaveRetryDelay(2)).toBe(10000)
    expect(nextCanvasSaveRetryDelay(3)).toBeNull()
    expect(nextCanvasSaveRetryDelay(-1)).toBeNull()
    expect(nextCanvasSaveRetryDelay(1.5)).toBeNull()
  })

  it("retries network and server errors but not client or conflict errors", () => {
    expect(isCanvasSaveRetryable(new TypeError("Failed to fetch"))).toBe(true)
    expect(isCanvasSaveRetryable(new Error("服务端返回了非 JSON 响应"))).toBe(true)
    expect(isCanvasSaveRetryable(apiError(500))).toBe(true)
    expect(isCanvasSaveRetryable(apiError(503))).toBe(true)
    expect(isCanvasSaveRetryable(apiError(408))).toBe(true)
    expect(isCanvasSaveRetryable(apiError(429))).toBe(true)
    expect(isCanvasSaveRetryable(apiError(400))).toBe(false)
    expect(isCanvasSaveRetryable(apiError(401))).toBe(false)
    expect(isCanvasSaveRetryable(apiError(409))).toBe(false)
  })

  it("reads the current version from 409 conflict responses", () => {
    expect(canvasConflictVersion(apiError(409, { detail: { current_version: 12 } }))).toBe(12)
    expect(canvasConflictVersion(apiError(409, { detail: {} }))).toBe(0)
    expect(canvasConflictVersion(apiError(409, null))).toBe(0)
    expect(canvasConflictVersion(apiError(400, { detail: { current_version: 12 } }))).toBeNull()
    expect(canvasConflictVersion(new TypeError("offline"))).toBeNull()
  })

  it("keeps retrying and conflict states while editing, otherwise marks dirty", () => {
    expect(saveStateAfterCanvasEdit("conflict")).toBe("conflict")
    expect(saveStateAfterCanvasEdit("retrying")).toBe("retrying")
    expect(saveStateAfterCanvasEdit("saved")).toBe("dirty")
    expect(saveStateAfterCanvasEdit("dirty")).toBe("dirty")
    expect(saveStateAfterCanvasEdit("saving")).toBe("saving")
    expect(saveStateAfterCanvasEdit("error")).toBe("dirty")
    expect(saveStateAfterCanvasSave(true)).toBe("saved")
    expect(saveStateAfterCanvasSave(false)).toBe("dirty")
  })
})

describe("canvas content size", () => {
  it("counts UTF-8 bytes for JSON content", () => {
    expect(canvasByteSize("abc")).toBe(3)
    expect(canvasByteSize("画布")).toBe(6)
    expect(canvasByteSize("")).toBe(0)
  })

  it("warns at 6 MB and refuses content beyond the 8 MB server limit", () => {
    expect(canvasContentSizeLevel(CANVAS_CONTENT_WARN_BYTES - 1)).toBe("ok")
    expect(canvasContentSizeLevel(CANVAS_CONTENT_WARN_BYTES)).toBe("warning")
    expect(canvasContentSizeLevel(CANVAS_CONTENT_LIMIT_BYTES)).toBe("warning")
    expect(canvasContentSizeLevel(CANVAS_CONTENT_LIMIT_BYTES + 1)).toBe("over")
  })

  it("formats sizes for save notices", () => {
    expect(formatCanvasBytes(512 * 1024)).toBe("512 KB")
    expect(formatCanvasBytes(2.25 * 1024 * 1024)).toBe("2.3 MB")
    expect(formatCanvasBytes(CANVAS_CONTENT_LIMIT_BYTES + 1024)).toBe("8.0 MB")
  })
})

describe("canvas render virtualization", () => {
  it("virtualizes only after the node threshold", () => {
    expect(shouldVirtualizeCanvasNodes(0)).toBe(false)
    expect(shouldVirtualizeCanvasNodes(CANVAS_VIRTUALIZE_NODE_LIMIT)).toBe(false)
    expect(shouldVirtualizeCanvasNodes(CANVAS_VIRTUALIZE_NODE_LIMIT + 1)).toBe(true)
  })
})
