import { describe, expect, it } from "vitest"
import { splitWorkshopGroup, mergeWorkshopGroups, type WorkshopGroup } from "./workshop-api"

const group = (id: string, beat_ids: string[]): WorkshopGroup => ({ id, beat_ids, common_prompt: "书房", reference_slots: [] })
describe("workshop group edits", () => {
  it("splits and rejoins without reordering or mutating shots", () => {
    const input = [group("g", ["a", "b", "c"])]
    const split = splitWorkshopGroup(input, "g", 1)
    expect(split.map(g => g.beat_ids)).toEqual([["a"], ["b", "c"]])
    expect(input[0].beat_ids).toEqual(["a", "b", "c"])
    expect(mergeWorkshopGroups(split, 0)[0].beat_ids).toEqual(["a", "b", "c"])
  })
  it("does not discard different shared settings on merge", () => {
    const input = [group("a", ["a"]), {...group("b", ["b"]), common_prompt:"夜晚"}]
    expect(mergeWorkshopGroups(input, 0)).toBe(input)
  })
})
