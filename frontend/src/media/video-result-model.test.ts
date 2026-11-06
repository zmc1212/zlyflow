import { describe, expect, it } from "vitest"
import { jobUpscaleSourceKey, selectVideoResult, videoResultKey, videoVersions, type VideoResult } from "./video-result-model"

const original: VideoResult = {
  jobId: "source", generationItemId: "item-1", outputIndex: 0,
  output: { kind: "video", path: "first.mp4", label: "一采预览" },
}
const second: VideoResult = {
  ...original, outputIndex: 1, output: { ...original.output, path: "second.mp4", label: "最终成片" },
}
const upscale: VideoResult = {
  ...original, jobId: "upscale", generationItemId: "upscale-item",
  output: { ...original.output, path: "upscale.mp4", label: "2x 超分" },
}

describe("video result versions", () => {
  it("labels a face repair as its own result version", () => {
    const face = { ...original, output: { ...original.output, label: "人脸高清修复" } }
    expect(videoVersions([original, face]).map((v) => v.label)).toEqual(["原片 1", "人脸高清修复"])
  })
  it("keeps a selected original when polling appends an upscale result", () => {
    expect(selectVideoResult([original, second, upscale], videoResultKey(second))).toBe(second)
  })
  it("uses the existing upscale default and falls back when a selected output disappears", () => {
    expect(selectVideoResult([original, upscale])).toBe(upscale)
    expect(selectVideoResult([original], videoResultKey(upscale))).toBe(original)
    expect(selectVideoResult([])).toBeUndefined()
  })
  it("distinguishes related jobs and generation items even when output paths match", () => {
    const related = { ...original, jobId: "another-job" }
    const anotherItem = { ...original, generationItemId: "item-2" }
    expect(selectVideoResult([original, related, anotherItem], videoResultKey(related))).toBe(related)
    expect(selectVideoResult([original, related, anotherItem], videoResultKey(anotherItem))).toBe(anotherItem)
  })
  it("counts real video outputs without inferring sampling stages or including images", () => {
    const image: VideoResult = { ...original, output: { ...original.output, kind: "image", path: "ref.png" } }
    const versions = videoVersions([image, original, upscale, second])
    expect(versions.map((version) => version.label)).toEqual(["原片 1", "2× 超分", "原片 2"])
    expect(versions.map((version) => version.detail)).toEqual(["一采预览", "", "最终成片"])
    expect(versions[2].result.output.label).toBe("最终成片")
    expect(selectVideoResult([image])).toBeUndefined()
  })
  it("labels each upscale engine with its own version name", () => {
    const seedvr2 = { ...upscale, output: { ...upscale.output, path: "seedvr2.mp4", label: "2x 高清增强" } }
    const versions = videoVersions([original, upscale, seedvr2])
    expect(versions.map((version) => version.label)).toEqual(["原片 1", "2× 超分", "2× 高清增强"])
  })

  it("limits the job-level upscale action to its source rather than a selected historical version", () => {
    const job = { id: "source", rounds: [
      { generation_items: [{ id: "older-item", outputs: [original.output] }] },
      { generation_items: [{ id: "item-1", outputs: [original.output, second.output, upscale.output] }] },
    ] }
    expect(jobUpscaleSourceKey(job)).toBe(videoResultKey(original))
    expect(jobUpscaleSourceKey(job)).not.toBe(videoResultKey(second))
    expect(jobUpscaleSourceKey({ id: "source", rounds: [] })).toBeUndefined()
  })
})
