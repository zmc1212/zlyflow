import { describe, expect, it } from "vitest"
import {
  DEFAULT_WORKSHOP_ASPECT,
  aspectConfirmDescription,
  documentNeedsAspectConfirm,
  isAwaitingAspectDocument,
  uniqueAspectHits,
  videoSettingsWithWorkshopAspect,
  workshopAspectFromExtra,
} from "./workshop-aspect"

describe("workshop-aspect", () => {
  it("reads workshop_aspect_ratio from project extra", () => {
    expect(workshopAspectFromExtra({ workshop_aspect_ratio: "16:9" })).toBe("16:9")
    expect(workshopAspectFromExtra({ extra: { workshop_aspect_ratio: " 9 : 16 " } })).toBe("9:16")
    expect(workshopAspectFromExtra(null)).toBe("")
  })

  it("overlays confirmed extra aspect onto saved generation settings", () => {
    expect(videoSettingsWithWorkshopAspect({ aspect_ratio: "16:9", quality: "0.4" }, { workshop_aspect_ratio: "9:16" })).toEqual({
      aspect_ratio: "9:16",
      quality: "0.4",
    })
    expect(videoSettingsWithWorkshopAspect(null, { workshop_aspect_ratio: "1:1" })).toEqual({ aspect_ratio: "1:1" })
    expect(videoSettingsWithWorkshopAspect({ aspect_ratio: "16:9" }, null)).toEqual({ aspect_ratio: "16:9" })
  })

  it("describes script hits, conflicts, and recipe fallback", () => {
    expect(aspectConfirmDescription({ hits: ["竖屏", "9:16"], suggested: "9:16" })).toContain("竖屏")
    expect(aspectConfirmDescription({ hits: ["竖屏", "9:16"], suggested: "9:16" })).toContain("9:16")
    expect(aspectConfirmDescription({ conflicts: ["9:16", "16:9"], hits: ["9:16", "16:9"] })).toContain("同时提到了")
    expect(aspectConfirmDescription({ hits: [] }, DEFAULT_WORKSHOP_ASPECT)).toContain("没有写明画幅")
    expect(aspectConfirmDescription({ hits: ["竖屏", "竖屏", "9:16"] })).toEqual(
      expect.stringContaining("请确认成片画幅"),
    )
    expect(uniqueAspectHits({ hits: ["竖屏", "竖屏", "9:16"] })).toEqual(["竖屏", "9:16"])
  })

  it("flags imported documents that still need aspect confirmation", () => {
    expect(isAwaitingAspectDocument({ status: "awaiting_aspect" })).toBe(true)
    expect(documentNeedsAspectConfirm({ status: "awaiting_aspect" })).toBe(true)
    expect(documentNeedsAspectConfirm({ status: "ready", needs_shot_plan: true })).toBe(true)
    expect(documentNeedsAspectConfirm({ status: "planning", shot_plan_job_id: "job-1" })).toBe(false)
  })
})
