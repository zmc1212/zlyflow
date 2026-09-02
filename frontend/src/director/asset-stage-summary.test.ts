import { describe, expect, it } from "vitest"
import {
  formatSimpleAssetStageSummary,
  simpleAssetStageCounts,
} from "./asset-stage-summary"

describe("asset stage summary", () => {
  it("summarizes approved, approvable and idle simple assets", () => {
    const counts = simpleAssetStageCounts([
      {
        imageUrl: "/approved.png",
        plate: { versions: [{ id: "v1", status: "succeeded", imageUrl: "/approved.png", promptSnapshot: "", options: {}, createdAt: "" }], approvedVersionId: "v1" },
      },
      {
        plate: {
          versions: [{ id: "v2", status: "succeeded", imageUrl: "/pending.png", promptSnapshot: "", options: {}, createdAt: "" }],
          activeVersionId: "v2",
        },
      },
      { plate: { versions: [] } },
    ], "plate")

    expect(counts).toEqual({ total: 3, approved: 1, approvable: 1, idle: 1, running: 0 })
    expect(formatSimpleAssetStageSummary(counts, "场景")).toBe("1 已批准 · 1 待批准 · 1 待生成")
  })
})
