import { describe, expect, it } from "vitest"
import { collectImageOutputs, type AssetJob } from "./AssetPickerModal"

function imageOutput(overrides: Partial<AssetJob["outputs"][number]> = {}): AssetJob["outputs"][number] {
  return { kind: "image", label: "图片", download_url: "/download", cloud_url: null, ...overrides }
}

describe("collectImageOutputs", () => {
  it("reads round outputs only when the job mirrors them into top-level outputs", () => {
    const job: AssetJob = {
      id: "job-1",
      media_type: "image",
      status: "succeeded",
      title: "赛博小龙虾",
      outputs: [imageOutput({ download_url: "/api/jobs/job-1/outputs/0/download", path: "studio/a.png", cloud_url: "https://cdn/a.png" })],
      rounds: [{
        generation_items: [{
          id: "item-1",
          outputs: [imageOutput({ download_url: "/api/jobs/job-1/generations/item-1/outputs/0/download", path: "studio/a.png", cloud_url: "https://cdn/a.png" })],
        }],
      }],
    }
    const items = collectImageOutputs([job])
    expect(items).toHaveLength(1)
    expect(items[0].url).toBe("/api/jobs/job-1/generations/item-1/outputs/0/download")
  })

  it("falls back to top-level outputs for legacy jobs without rounds", () => {
    const job: AssetJob = {
      id: "job-2",
      media_type: "image",
      status: "succeeded",
      outputs: [imageOutput({ download_url: "/api/jobs/job-2/outputs/0/download" })],
      rounds: [],
    }
    const items = collectImageOutputs([job])
    expect(items).toHaveLength(1)
    expect(items[0].url).toBe("/api/jobs/job-2/outputs/0/download")
  })

  it("falls back to top-level outputs when rounds exist but carry no outputs", () => {
    const job: AssetJob = {
      id: "job-3",
      media_type: "image",
      status: "running",
      outputs: [imageOutput({ download_url: "/api/jobs/job-3/outputs/0/download" })],
      rounds: [{ generation_items: [{ id: "item-3", outputs: [] }] }],
    }
    const items = collectImageOutputs([job])
    expect(items).toHaveLength(1)
    expect(items[0].url).toBe("/api/jobs/job-3/outputs/0/download")
  })

  it("deduplicates the same underlying file across jobs by path or cloud url", () => {
    const first: AssetJob = {
      id: "job-4",
      media_type: "image",
      status: "succeeded",
      outputs: [],
      rounds: [{ generation_items: [{ id: "item-4", outputs: [imageOutput({ path: "studio/same.png", cloud_url: "https://cdn/same.png" })] }] }],
    }
    const second: AssetJob = {
      id: "job-5",
      media_type: "image",
      status: "succeeded",
      outputs: [],
      rounds: [{ generation_items: [{ id: "item-5", outputs: [imageOutput({ path: "studio/same.png", cloud_url: "https://cdn/same.png" })] }] }],
    }
    const items = collectImageOutputs([first, second])
    expect(items).toHaveLength(1)
  })

  it("keeps genuinely different files and skips videos and outputs without urls", () => {
    const job: AssetJob = {
      id: "job-6",
      media_type: "image",
      status: "succeeded",
      outputs: [],
      rounds: [{
        generation_items: [{
          id: "item-6",
          outputs: [
            imageOutput({ path: "studio/one.png", cloud_url: "https://cdn/one.png" }),
            imageOutput({ kind: "video", path: "studio/clip.mp4" }),
            imageOutput({ path: "studio/two.png", cloud_url: "https://cdn/two.png" }),
            imageOutput({ path: "studio/missing.png", download_url: null, cloud_url: null }),
          ],
        }],
      }],
    }
    const items = collectImageOutputs([job])
    expect(items.map(item => item.url)).toEqual(["/download", "/download"])
    expect(items[0].label).toBe("图片")
  })
})
