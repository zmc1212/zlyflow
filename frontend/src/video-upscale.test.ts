import { describe, expect, it } from "vitest"
import {
  UPSCALE_OUTPUT_LABEL,
  activeUpscaleJob,
  canRequestJobUpscale,
  extraUpscaleResults,
  hasOriginalVideo,
  isRtxVsrJob,
  isUpscaleOutput,
  relatedUpscaleJobs,
  upscaleDisabledReason,
  type UpscaleJobLike,
} from "./video-upscale"

function videoJob(partial: Partial<UpscaleJobLike> & Pick<UpscaleJobLike, "id">): UpscaleJobLike {
  return {
    mode: "minimax-h3-t2v",
    status: "succeeded",
    stage: "生成完成",
    outputs: [{ kind: "video", label: "MiniMax H3 视频", path: "orig.mp4" }],
    rounds: [{ generation_items: [{ id: "g1", outputs: [{ kind: "video", label: "MiniMax H3 视频", path: "orig.mp4" }] }] }],
    ...partial,
  }
}

describe("creation-page RTX upscale helpers", () => {
  it("detects original vs 2x outputs and related jobs", () => {
    const source = videoJob({ id: "src-1" })
    const running = videoJob({
      id: "vsr-1",
      mode: "nvidia-rtx-vsr",
      status: "running",
      stage: "正在 2x 超分",
      source: { job_id: "src-1" },
      outputs: [],
      rounds: [{ generation_items: [{ id: "g2", outputs: [] }] }],
    })
    expect(isRtxVsrJob(running)).toBe(true)
    expect(isUpscaleOutput({ label: UPSCALE_OUTPUT_LABEL })).toBe(true)
    expect(hasOriginalVideo(source)).toBe(true)
    expect(relatedUpscaleJobs([source, running], "src-1")).toEqual([running])
    expect(activeUpscaleJob([source, running], "src-1")?.id).toBe("vsr-1")
    expect(canRequestJobUpscale(source, [source, running])).toBe(false)
    expect(upscaleDisabledReason(source, [source, running])).toBe("正在 2x 超分")
  })

  it("enables the button on a successful original and merges the independent result", () => {
    const source = videoJob({ id: "src-1" })
    const done = videoJob({
      id: "vsr-2",
      mode: "nvidia-rtx-vsr",
      status: "succeeded",
      source: { job_id: "src-1" },
      outputs: [{ kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" }],
      rounds: [{ generation_items: [{ id: "g3", outputs: [{ kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" }] }] }],
    })
    expect(canRequestJobUpscale(source, [source, done])).toBe(true)
    expect(upscaleDisabledReason(source, [source, done])).toBeUndefined()
    expect(extraUpscaleResults(source, [source, done])).toEqual([{
      jobId: "vsr-2",
      generationItemId: "g3",
      outputIndex: 0,
      output: { kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" },
    }])
  })

  it("disables without a finished original and does not offer upscale on vsr jobs", () => {
    const queued = videoJob({ id: "src-2", status: "running", stage: "正在生成", outputs: [], rounds: [{ generation_items: [{ id: "g1", outputs: [] }] }] })
    const vsr = videoJob({ id: "vsr-3", mode: "nvidia-rtx-vsr", source: { job_id: "src-2" } })
    expect(canRequestJobUpscale(queued, [queued])).toBe(false)
    expect(canRequestJobUpscale(vsr, [vsr])).toBe(false)
    expect(canRequestJobUpscale(videoJob({ id: "src-3" }), [videoJob({ id: "src-3" })], true)).toBe(false)
  })
})
