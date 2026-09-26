import { afterEach, expect, it, vi } from "vitest"
import { streamH3PromptJobEvents } from "./workshop-prompt-stream"

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it("reconnects after the first fetch TypeError and delivers the persisted completion", async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("network disconnected"))
    .mockResolvedValueOnce(new Response('id: 2\nevent: done\ndata: {"status":"succeeded","preview":{}}\n\n', { headers: { "Content-Type": "text/event-stream" } }))
  vi.stubGlobal("fetch", fetch)
  const listener = vi.fn()
  const done = streamH3PromptJobEvents("project", "job", listener)
  await vi.runAllTimersAsync()
  expect(await done).toBe("terminal")
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(listener.mock.calls[0][0].event).toBe("done")
})
