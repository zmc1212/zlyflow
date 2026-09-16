import { describe, expect, it } from "vitest"
import {
  DIRECTOR2_DEFAULT_JOB_TYPE,
  DIRECTOR2_JOB_TYPES,
  countJobsByType,
  defaultJobTypeTab,
  director2JobTypeLabel,
  filterJobsByType,
  h3PromptResultText,
  isDirector2JobType,
  isH3PromptJob,
  videoShotPromptText,
} from "./director2-job-types"

describe("director2 job types", () => {
  it("lists the fixed tabs without an all tab", () => {
    expect(DIRECTOR2_JOB_TYPES).toEqual(["image_generation", "video_generation", "h3_prompt", "ai_pipeline"])
    expect(DIRECTOR2_DEFAULT_JOB_TYPE).toBe("image_generation")
  })

  it("labels known types in Chinese and leaves unknown keys as-is", () => {
    expect(director2JobTypeLabel("image_generation")).toBe("图片生成")
    expect(director2JobTypeLabel("video_generation")).toBe("视频生成")
    expect(director2JobTypeLabel("h3_prompt")).toBe("H3 提示词")
    expect(director2JobTypeLabel("ai_pipeline")).toBe("AI 生成")
    expect(director2JobTypeLabel("weird")).toBe("weird")
    expect(isDirector2JobType("ai_pipeline")).toBe(true)
    expect(isDirector2JobType("weird")).toBe(false)
  })

  it("filters and counts by job_type", () => {
    const jobs = [
      { job_type: "video_generation" },
      { job_type: "image_generation" },
      { job_type: "image_generation" },
      { job_type: "ai_pipeline" },
      { job_type: "other" },
    ]
    expect(filterJobsByType(jobs, "image_generation")).toHaveLength(2)
    expect(filterJobsByType(jobs, "video_generation")).toHaveLength(1)
    expect(filterJobsByType(jobs, "ai_pipeline")).toHaveLength(1)
    expect(countJobsByType(jobs)).toEqual({
      image_generation: 2,
      video_generation: 1,
      h3_prompt: 0,
      ai_pipeline: 1,
    })
  })

  it("reads generated H3 prompt text from job payload", () => {
    expect(isH3PromptJob({ job_type: "h3_prompt" })).toBe(true)
    expect(isH3PromptJob({ job_type: "image_generation", payload: { target_type: "h3_prompt" } })).toBe(true)
    expect(isH3PromptJob({ job_type: "image_generation" })).toBe(false)
    expect(h3PromptResultText({ payload: { h3_prompt: "subject_definitions:\nA shot." } })).toBe(
      "subject_definitions:\nA shot.",
    )
    expect(h3PromptResultText({ payload: { result_prompt: "fallback prompt" } })).toBe("fallback prompt")
    expect(h3PromptResultText({ payload: {} })).toBe("")
    expect(videoShotPromptText({ prompt: "from video job" })).toBe("from video job")
    expect(videoShotPromptText({ h3_prompt: "from workshop" })).toBe("from workshop")
    expect(videoShotPromptText({ prompt: "generated", h3_prompt: "from workshop" })).toBe("generated")
    expect(videoShotPromptText({ prompt: "  ", h3_prompt: "" })).toBe("")
  })

  it("defaults to the newest job type and falls back when empty", () => {
    expect(defaultJobTypeTab([])).toBe("image_generation")
    expect(defaultJobTypeTab([{ job_type: "video_generation" }, { job_type: "image_generation" }])).toBe(
      "video_generation",
    )
    expect(defaultJobTypeTab([{ job_type: "unknown" }])).toBe("image_generation")
  })
})
