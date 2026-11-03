import { describe, expect, it } from "vitest"
import { activeBeatAfterDelete, selectedWorkshopBeatIds, workshopBatchDeleteReason } from "./workshop-batch"

const beats = [{ id: "a" }, { id: "b" }, { id: "c" }]
describe("workshop batch selection", () => {
  it("uses current episode order and ignores selections from another episode", () => {
    expect(selectedWorkshopBeatIds(beats, new Set(["c", "missing", "a"]))).toEqual(["a", "c"])
  })
  it("keeps at least one clip and blocks ongoing generation", () => {
    expect(workshopBatchDeleteReason(3, 0, false)).toContain("选择")
    expect(workshopBatchDeleteReason(3, 3, false)).toContain("保留")
    expect(workshopBatchDeleteReason(3, 1, true)).toContain("生成")
    expect(workshopBatchDeleteReason(3, 1, false)).toBe("")
  })
  it("preserves the active clip when it was not deleted", () => {
    expect(activeBeatAfterDelete(beats, [beats[0], beats[2]], "c")).toBe("c")
  })
  it("selects the nearest remaining clip after deleting the active clip", () => {
    expect(activeBeatAfterDelete(beats, [beats[0], beats[2]], "b")).toBe("c")
    expect(activeBeatAfterDelete(beats, [beats[0]], "c")).toBe("a")
  })
})
