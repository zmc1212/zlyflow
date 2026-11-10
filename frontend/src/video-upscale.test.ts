import { describe, expect, it } from "vitest"
import {
  RELAYVSR_MODE,
  RELAYVSR_OUTPUT_LABEL,
  SEEDVR2_MODE,
  SEEDVR2_OUTPUT_LABEL,
  UPSCALE_OUTPUT_LABEL,
  activeUpscaleJob,
  canUpscaleRound,
  extraUpscaleResults,
  isUpscaleJob,
  isUpscaleOutput,
  relatedUpscaleJobs,
  upscaleOutputLabel,
  type UpscaleJobLike,
} from "./video-upscale"

describe("source video upscale eligibility", () => {
  const source = { mode: "minimax-h3-video-edit", status: "succeeded", rounds: [{ id: "old" }, { id: "latest" }] }

  it("only offers the latest round because the endpoint selects the latest source", () => {
    expect(canUpscaleRound(source, "latest")).toBe(true)
    expect(canUpscaleRound(source, "old")).toBe(false)
    expect(canUpscaleRound({ ...source, rounds: [] }, "latest")).toBe(false)
  })

  it("waits for a fully successful source", () => {
    for (const status of ["queued", "running", "failed", "interrupted", "partially_succeeded"]) {
      expect(canUpscaleRound({ ...source, status }, "latest")).toBe(false)
    }
  })

  it("does not offer enhancement while inspecting another user or on an upscale result", () => {
    expect(canUpscaleRound(source, "latest", true)).toBe(false)
    expect(canUpscaleRound(source, "latest", false, { label: SEEDVR2_OUTPUT_LABEL })).toBe(false)
    expect(canUpscaleRound(source, "latest", false, { label: "H3 视频编辑试片" })).toBe(true)
    for (const mode of [SEEDVR2_MODE, RELAYVSR_MODE, "nvidia-rtx-vsr"]) {
      expect(canUpscaleRound({ ...source, mode }, "latest")).toBe(false)
    }
  })
})

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

describe("legacy 2x upscale result readers", () => {
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
    expect(isUpscaleJob(running)).toBe(true)
    expect(isUpscaleOutput({ label: UPSCALE_OUTPUT_LABEL })).toBe(true)
    expect(relatedUpscaleJobs([source, running], "src-1")).toEqual([running])
    expect(activeUpscaleJob([source, running], "src-1")?.id).toBe("vsr-1")
  })

  it("merges the independent result of a finished legacy upscale job", () => {
    const source = videoJob({ id: "src-1" })
    const done = videoJob({
      id: "vsr-2",
      mode: "nvidia-rtx-vsr",
      status: "succeeded",
      source: { job_id: "src-1" },
      outputs: [{ kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" }],
      rounds: [{ generation_items: [{ id: "g3", outputs: [{ kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" }] }] }],
    })
    expect(extraUpscaleResults(source, [source, done])).toEqual([{
      jobId: "vsr-2",
      generationItemId: "g3",
      outputIndex: 0,
      output: { kind: "video", label: UPSCALE_OUTPUT_LABEL, path: "up.mp4" },
    }])
  })

  it("labels each legacy engine with its own version name", () => {
    const source = videoJob({ id: "src-4" })
    const enhanced = videoJob({
      id: "seedvr2-2",
      mode: SEEDVR2_MODE,
      source: { job_id: "src-4" },
      outputs: [{ kind: "video", label: SEEDVR2_OUTPUT_LABEL, path: "enhanced.mp4" }],
      rounds: [{ generation_items: [{ id: "g4", outputs: [{ kind: "video", label: SEEDVR2_OUTPUT_LABEL, path: "enhanced.mp4" }] }] }],
    })
    expect(isUpscaleJob(enhanced)).toBe(true)
    expect(isUpscaleOutput({ label: SEEDVR2_OUTPUT_LABEL })).toBe(true)
    expect(isUpscaleOutput({ label: "MiniMax H3 视频" })).toBe(false)
    expect(upscaleOutputLabel({ label: SEEDVR2_OUTPUT_LABEL })).toBe("2× 高清增强")
    expect(upscaleOutputLabel({ label: RELAYVSR_OUTPUT_LABEL })).toBe("2× 细节超分")
    expect(isUpscaleOutput({ label: RELAYVSR_OUTPUT_LABEL })).toBe(true)
    expect(isUpscaleJob({ mode: RELAYVSR_MODE })).toBe(true)
    expect(upscaleOutputLabel({ label: UPSCALE_OUTPUT_LABEL })).toBe("2× 超分")
    expect(upscaleOutputLabel({ label: "MiniMax H3 视频" })).toBe("")
    expect(extraUpscaleResults(source, [source, enhanced])).toEqual([{
      jobId: "seedvr2-2",
      generationItemId: "g4",
      outputIndex: 0,
      output: { kind: "video", label: SEEDVR2_OUTPUT_LABEL, path: "enhanced.mp4" },
    }])
  })
})
