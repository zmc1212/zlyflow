import { describe, expect, it } from "vitest"
import {
  resolveTakeGenerationMeta,
  takeGenerationDiff,
  workflowFamilyLabel,
} from "./take-generation-params"
import type { ShotTake } from "./types"

function sampleTake(overrides: Partial<ShotTake> = {}): ShotTake {
  return {
    id: "job-1",
    takeNumber: 1,
    jobId: "job-1",
    status: "succeeded",
    progress: 100,
    createdAt: "2026-09-01T06:00:00.000Z",
    renderPass: "final",
    workflowId: "minimax-h3-t2v",
    videoWorkflowFamily: "official_h3",
    options: {
      aspect_ratio: "16:9",
      quality: "1.0",
      speed: "quality",
      weight_profile: "full",
      duration: 5,
    },
    ...overrides,
  }
}

const previewTake = sampleTake({
  id: "job-2",
  jobId: "job-2",
  takeNumber: 2,
  renderPass: "preview",
  workflowId: "minimax-h3-lightx2v-t2v",
  videoWorkflowFamily: "lightx2v",
  options: {
    aspect_ratio: "16:9",
    quality: "0.4",
    speed: "fast",
    weight_profile: "full",
    duration: 5,
  },
})

describe("take generation params", () => {
  it("resolves generation meta and diff", () => {
    expect(workflowFamilyLabel("official_h3")).toBe("MiniMax H3")

    const finalMeta = resolveTakeGenerationMeta(sampleTake())
    expect(finalMeta.summary.includes("成片")).toBe(true)
    expect(finalMeta.summary.includes("1.0 MP")).toBe(true)

    const backfilled = resolveTakeGenerationMeta(
      sampleTake({ options: undefined, workflowId: undefined }),
      { mode: "minimax-h3-t2v", options: { quality: "1.0", speed: "quality", weight_profile: "full", duration: 5 } },
    )
    expect(backfilled.options.quality).toBe("1.0")
    expect(backfilled.workflowId).toBe("minimax-h3-t2v")

    const diff = takeGenerationDiff(finalMeta, resolveTakeGenerationMeta(previewTake))
    expect(diff.includes("档位")).toBe(true)
    expect(diff.includes("分辨率")).toBe(true)
    expect(diff.includes("生成速度")).toBe(true)
  })
})
