import { afterEach, describe, expect, it, vi } from "vitest"
import { createWorkshopSaveQueue } from "./workshop-save-queue"

afterEach(() => vi.useRealTimers())
describe("workshop save queue", () => {
  it("coalesces typing and never lets an older response discard a newer edit", async () => {
    vi.useFakeTimers()
    let resolveFirst!: () => void
    const first = new Promise<void>(resolve => { resolveFirst = resolve })
    const save = vi.fn().mockImplementationOnce(() => first).mockResolvedValue(undefined)
    const changed = vi.fn()
    const queue = createWorkshopSaveQueue<number>(save, changed)
    queue.enqueue("beat", 1)
    const writing = queue.flush("beat")
    queue.enqueue("beat", 2)
    queue.enqueue("beat", 3)
    expect(save).toHaveBeenCalledTimes(1)
    resolveFirst()
    await writing
    expect(save.mock.calls).toEqual([["beat", 1], ["beat", 3]])
    expect(queue.pending()).toBe(false)
    expect(changed.mock.calls.filter(call => call[1] === "saved")).toHaveLength(1)
  })
  it("keeps a failed draft retryable, while another beat can save independently", async () => {
    vi.useFakeTimers()
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined)
    const queue = createWorkshopSaveQueue<string>(save, vi.fn())
    queue.enqueue("a", "edit-a")
    await expect(queue.flush("a")).rejects.toThrow("offline")
    expect(queue.pending()).toBe(true)
    queue.enqueue("b", "edit-b")
    await queue.flush("b")
    await queue.flush("a")
    expect(save.mock.calls).toEqual([["a", "edit-a"], ["b", "edit-b"], ["a", "edit-a"]])
    expect(queue.pending()).toBe(false)
  })
})
