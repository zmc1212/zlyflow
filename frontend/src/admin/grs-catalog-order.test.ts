import { describe, expect, it } from "vitest"
import { reorderCatalogRows } from "./grs-catalog-order"

const rows = [
  { workflow_id: "a", sort_order: 10, enabled: true },
  { workflow_id: "b", sort_order: 20, enabled: true },
  { workflow_id: "c", sort_order: 30, enabled: false },
]

describe("reorderCatalogRows", () => {
  it("moves a row down and renumbers the whole catalog densely", () => {
    expect(reorderCatalogRows(rows, "a", "c")).toEqual([
      { workflow_id: "b", sort_order: 10, enabled: true },
      { workflow_id: "c", sort_order: 20, enabled: false },
      { workflow_id: "a", sort_order: 30, enabled: true },
    ])
  })

  it("moves a row up without losing the other rows' fields", () => {
    expect(reorderCatalogRows(rows, "c", "a").map((item) => item.workflow_id)).toEqual(["c", "a", "b"])
    expect(reorderCatalogRows(rows, "c", "a")[0]).toEqual({ workflow_id: "c", sort_order: 10, enabled: false })
  })

  it("keeps the list untouched for the same row or an unknown id", () => {
    expect(reorderCatalogRows(rows, "b", "b")).toBe(rows)
    expect(reorderCatalogRows(rows, "missing", "a")).toBe(rows)
  })

  it("leaves gaps of 10 so newly imported models can be inserted later", () => {
    const reordered = reorderCatalogRows(rows, "a", "c")
    expect(reordered.map((item) => item.sort_order)).toEqual([10, 20, 30])
  })
})
