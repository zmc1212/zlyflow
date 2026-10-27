import { describe, expect, it } from "vitest"
import { groupTasksByCreatedAt } from "./task-groups"

function task(id: string, date: Date) {
  return { id, created_at: date.toISOString() }
}

describe("groupTasksByCreatedAt", () => {
  const now = new Date(2026, 9, 25, 12, 0, 0)

  it("splits tasks into today, yesterday, past 7 days and older", () => {
    const groups = groupTasksByCreatedAt([
      task("today-start", new Date(2026, 9, 25, 0, 0, 0)),
      task("yesterday", new Date(2026, 9, 24, 23, 59, 0)),
      task("week-start", new Date(2026, 9, 19, 0, 0, 0)),
      task("older", new Date(2026, 9, 18, 23, 59, 0)),
    ], now.getTime())

    expect(groups.map((group) => [group.key, group.tasks.map((item) => item.id)])).toEqual([
      ["today", ["today-start"]],
      ["yesterday", ["yesterday"]],
      ["week", ["week-start"]],
      ["older", ["older"]],
    ])
  })

  it("keeps the incoming order inside a group and omits empty groups", () => {
    const groups = groupTasksByCreatedAt([
      task("newer", new Date(2026, 9, 25, 11, 0, 0)),
      task("older", new Date(2026, 9, 25, 9, 0, 0)),
    ], now.getTime())

    expect(groups).toHaveLength(1)
    expect(groups[0].label).toBe("今天")
    expect(groups[0].tasks.map((item) => item.id)).toEqual(["newer", "older"])
  })

  it("falls back to the older group for invalid timestamps", () => {
    const groups = groupTasksByCreatedAt([{ id: "broken", created_at: "not-a-date" }], now.getTime())

    expect(groups.map((group) => [group.key, group.tasks.map((item) => item.id)])).toEqual([
      ["older", ["broken"]],
    ])
  })

  it("uses local midnight for day boundaries", () => {
    const groups = groupTasksByCreatedAt([
      task("today", new Date(2026, 9, 25, 0, 0, 0)),
      task("yesterday", new Date(2026, 9, 24, 23, 59, 59)),
    ], now.getTime())

    expect(groups.map((group) => group.key)).toEqual(["today", "yesterday"])
  })
})
