import { afterEach, describe, expect, it, vi } from "vitest"
import { notifyUnauthorized, requestJson, setUnauthorizedHandler } from "./api"

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("global 401 handling", () => {
  afterEach(() => {
    setUnauthorizedHandler(null)
    vi.unstubAllGlobals()
  })

  it("notifies the registered handler exactly while it is registered", () => {
    const handler = vi.fn()
    notifyUnauthorized()
    expect(handler).not.toHaveBeenCalled()

    setUnauthorizedHandler(handler)
    notifyUnauthorized()
    expect(handler).toHaveBeenCalledTimes(1)

    setUnauthorizedHandler(null)
    notifyUnauthorized()
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it("marks session-expiry 401 responses from any API path as unauthorized", async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "请先登录" })))

    await expect(requestJson("/api/jobs")).rejects.toMatchObject({ status: 401 })
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it("keeps login credential failures from triggering the unauthorized redirect", async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "账号或密码错误" })))

    await expect(requestJson("/api/auth/login", { method: "POST" })).rejects.toMatchObject({ status: 401 })
    expect(handler).not.toHaveBeenCalled()
  })
})
