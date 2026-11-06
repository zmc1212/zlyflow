import { describe, expect, it } from "vitest"
import { isCompareAligned, resolveCompareSource } from "./image-compare"

const overlay = { result_compare: "overlay", reference_labels: ["原图", "遮罩图(白色=消除区)"] }
const references = [
  { index: 1, url: "/api/jobs/j/rounds/r/references/1" },
  { index: 2, url: "/api/jobs/j/rounds/r/references/2" },
]

describe("resolveCompareSource", () => {
  it("ignores workflows that did not declare a pixel-aligned result", () => {
    expect(resolveCompareSource(undefined, references)).toBeUndefined()
    expect(resolveCompareSource({ result_compare: "none", reference_labels: ["原图"] }, references)).toBeUndefined()
    expect(resolveCompareSource({ result_compare: "overlay", reference_labels: ["参考图 1"] }, references)).toBeUndefined()
  })

  it("takes the source image from the declared 原图 slot, not from slot order", () => {
    expect(resolveCompareSource(overlay, references)).toEqual({
      src: "/api/jobs/j/rounds/r/references/1",
      label: "原图",
    })
    const maskFirst = { result_compare: "overlay", reference_labels: ["遮罩图(白色=消除区)", "原图"] }
    expect(resolveCompareSource(maskFirst, references)?.src).toBe("/api/jobs/j/rounds/r/references/2")
  })

  it("needs a real image reference in that slot", () => {
    expect(resolveCompareSource(overlay, [{ index: 2, url: "/mask.png" }])).toBeUndefined()
    expect(resolveCompareSource(overlay, [{ index: 1, url: "", kind: "image" }])).toBeUndefined()
    expect(resolveCompareSource(overlay, [{ index: 1, url: "/clip.mp4", kind: "video" }])).toBeUndefined()
  })
})

describe("isCompareAligned", () => {
  it("allows the same composition at a different resolution", () => {
    expect(isCompareAligned({ width: 1024, height: 1024 }, { width: 1536, height: 1536 })).toBe(true)
    expect(isCompareAligned({ width: 1000, height: 500 }, { width: 1920, height: 960 })).toBe(true)
  })

  it("rejects a different aspect ratio, where the slider would misregister", () => {
    expect(isCompareAligned({ width: 1024, height: 1024 }, { width: 1536, height: 1024 })).toBe(false)
  })
})
