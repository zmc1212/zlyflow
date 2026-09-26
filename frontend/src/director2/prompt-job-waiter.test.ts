import { afterEach, expect, it, vi } from "vitest"
import { waitForPersistedPromptJob } from "./prompt-job-waiter"

afterEach(() => vi.useRealTimers())

it("continues polling through exhausted SSE and network failures until the server completes", async () => {
  vi.useFakeTimers()
  const getJob = vi.fn().mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce({ status: "running" }).mockResolvedValue({ status: "completed", payload: "saved" })
  const reconnect = vi.fn()
  const waiting = waitForPersistedPromptJob({ getJob, stream: vi.fn().mockRejectedValue(new TypeError("offline")),
    onEvent: vi.fn(), onReconnecting: reconnect, signal: new AbortController().signal, pollMs: 100, reconnectMs: 20 })
  await vi.advanceTimersByTimeAsync(210)
  expect(await waiting).toEqual({ status: "completed", payload: "saved" })
  expect(getJob).toHaveBeenCalledTimes(3)
  expect(reconnect).toHaveBeenCalled()
  expect(vi.getTimerCount()).toBe(0)
})

it("does not treat an SSE error as a terminal database state", async () => {
  vi.useFakeTimers()
  const getJob = vi.fn().mockResolvedValueOnce({ status: "running" }).mockResolvedValue({ status: "failed", error: "exact segment" })
  const waiting = waitForPersistedPromptJob({ getJob,
    stream: async onEvent => { onEvent({ seq: 1, event: "error", data: { message: "disconnected" } }) },
    onEvent: vi.fn(), onReconnecting: vi.fn(), signal: new AbortController().signal, pollMs: 100 })
  await vi.advanceTimersByTimeAsync(110)
  expect(await waiting).toEqual({ status: "failed", error: "exact segment" })
})

it("aborts both observation loops when the component unmounts", async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const waiting = waitForPersistedPromptJob({ getJob: async () => ({ status: "running" }),
    stream: async () => undefined, onEvent: vi.fn(), onReconnecting: vi.fn(), signal: controller.signal })
  const rejected = expect(waiting).rejects.toMatchObject({ name: "AbortError" })
  controller.abort()
  await rejected
  expect(vi.getTimerCount()).toBe(0)
})
