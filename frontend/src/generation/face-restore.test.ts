import { describe, expect, it, vi } from "vitest"
import { FACE_RESTORE_WORKFLOW, facePoint, faceRestorePath, faceRestoreReferences, faceVideoError, selectedVideoReference, type FaceRestoreJob } from "./face-restore"

const job = (id = "base", mode = "minimax-h3"): FaceRestoreJob => ({ id, mode, references: [], rounds: [{
  id: "old-round", mode, prompt: "", options: {}, reference_count: 0, references: [],
  generation_items: [{ id: "selected", outputs: [
    { kind: "video", path: "one.mp4", label: "第一版", download_url: "/selected-1.mp4" },
    { kind: "video", path: "two.mp4", label: "第二版", download_url: "/selected-2.mp4" },
  ] }],
}, { id: "new-round", mode, prompt: "", options: {}, reference_count: 0, references: [],
  generation_items: [{ id: "latest", outputs: [{ kind: "video", path: "latest.mp4", label: "新一轮", download_url: "/latest.mp4" }] }],
}] })
const locator = { job_id: "base", generation_item_id: "selected", output_index: 1 }

describe("face repair sources", () => {
  it("uses the exact selected round and output and keeps source locators in the tool URL", () => {
    expect(selectedVideoReference(job(), locator).url).toBe("/selected-2.mp4")
    expect(faceRestorePath({ jobId: "base", generationItemId: "selected", outputIndex: 1 })).toBe("/tools/face-restore?sourceJob=base&generation=selected&output=1&kind=video")
    expect(faceRestorePath({ generationItemId: "selected", outputIndex: 1 })).toBeNull()
    expect(() => selectedVideoReference(job(), { ...locator, output_index: -1 })).toThrow("版本不存在")
    const image = job(); image.rounds[0].generation_items[0].outputs[1].kind = "image"
    expect(() => selectedVideoReference(image, locator)).toThrow("版本不存在")
  })
  it("associates the original of a selected enhanced version without replacing the enhanced canvas", async () => {
    const enhanced = job("enhanced", "seedvr2-upscale")
    enhanced.source = locator
    const load = vi.fn().mockResolvedValue(job())
    const result = await faceRestoreReferences(enhanced, { ...locator, job_id: "enhanced", output_index: 0 }, load)
    expect(result.references.map((r) => [r.index, r.url])).toEqual([[1, "/selected-1.mp4"], [2, "/selected-2.mp4"]])
    expect(load).toHaveBeenCalledWith("base")
    expect(result.warning).toBe("")
  })
  it("keeps the canvas usable and explains when the original cannot be loaded", async () => {
    const enhanced = job("enhanced", "seedvr2-upscale"); enhanced.source = locator
    const result = await faceRestoreReferences(enhanced, locator, vi.fn().mockRejectedValue(new Error("source unavailable")))
    expect(result.references).toHaveLength(1)
    expect(result.warning).toContain("补充上传")
  })
  it("reuses the original reference of the selected repair round, including legacy reference URLs", async () => {
    const repaired = job("repair", FACE_RESTORE_WORKFLOW)
    repaired.rounds[0].reference_count = 2
    repaired.rounds[1].references = [{ index: 2, url: "/wrong-new-original.mp4" }]
    const load = vi.fn()
    const result = await faceRestoreReferences(repaired, locator, load)
    expect(result.references[1].url).toBe("/api/jobs/repair/rounds/old-round/references/2")
    expect(result.references[1].kind).toBe("video")
    expect(load).not.toHaveBeenCalled()
  })
  it("validates a single finite normalized face point and video file limits", () => {
    expect(facePoint('{"x":0.37,"y":0.38}')).toEqual({ x: .37, y: .38 })
    for (const point of [null, "broken", { x: true, y: .5 }, { x: Infinity, y: .5 }, { x: -.01, y: .5 }, { x: .5, y: 1.01 }]) expect(facePoint(point)).toBeNull()
    expect(faceVideoError({ name: "clip.MP4", type: "application/octet-stream", size: 60*1024*1024 })).toBe("")
    expect(faceVideoError({ name: "clip.mp4", type: "video/mp4", size: 501*1024*1024 })).toContain("500 MB")
    expect(faceVideoError({ name: "face.png", type: "image/png", size: 100 })).toContain("视频文件")
  })
})
