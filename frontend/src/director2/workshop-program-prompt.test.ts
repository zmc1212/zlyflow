import { describe, expect, it } from "vitest"
import { programPreviewPrompts, sameProgramPreviewPrompts } from "./workshop-program-prompt"

describe("programPreviewPrompts", () => {
  it("uses the latest program preview job with prompts for the episode", () => {
    const result = programPreviewPrompts(
      [
        {
          id: "job-new",
          status: "running",
          payload: {
            episode_id: "ep-1",
            prompt_source: "program_preview",
            shots: [
              { beat_id: "b1", prompt: "subject_definitions:\nlatest" },
              { beat_id: "b2", prompt: "subject_definitions:\nsecond" },
            ],
          },
        },
        {
          id: "job-old",
          status: "completed",
          payload: {
            episode_id: "ep-1",
            prompt_source: "program_preview",
            shots: [{ beat_id: "b1", prompt: "subject_definitions:\nold" }],
          },
        },
      ],
      "ep-1",
    )
    expect(result?.jobId).toBe("job-new")
    expect(result?.status).toBe("running")
    expect(result?.prompts).toEqual({
      b1: "subject_definitions:\nlatest",
      b2: "subject_definitions:\nsecond",
    })
  })

  it("ignores saved H3 jobs and other episodes", () => {
    const result = programPreviewPrompts(
      [
        {
          id: "job-h3",
          payload: {
            episode_id: "ep-1",
            prompt_source: "workshop_material",
            shots: [{ beat_id: "b1", prompt: "saved" }],
          },
        },
        {
          id: "job-other",
          payload: {
            episode_id: "ep-2",
            prompt_source: "program_preview",
            shots: [{ beat_id: "b1", prompt: "other" }],
          },
        },
      ],
      "ep-1",
    )
    expect(result).toBeNull()
  })

  it("skips program jobs whose shots have no prompt yet", () => {
    const result = programPreviewPrompts(
      [
        {
          id: "job-empty",
          payload: {
            episode_id: "ep-1",
            prompt_source: "program_preview",
            shots: [{ beat_id: "b1" }],
          },
        },
        {
          id: "job-ready",
          payload: {
            episode_id: "ep-1",
            prompt_source: "program_preview",
            shots: [{ beat_id: "b2", prompt: "ready" }],
          },
        },
      ],
      "ep-1",
    )
    expect(result?.jobId).toBe("job-ready")
    expect(result?.prompts).toEqual({ b2: "ready" })
  })

  it("returns null without an episode id", () => {
    expect(programPreviewPrompts([], "")).toBeNull()
    expect(programPreviewPrompts(null, "ep-1")).toBeNull()
  })
})

describe("sameProgramPreviewPrompts", () => {
  it("detects unchanged and changed prompt maps", () => {
    const base = { jobId: "job-1", status: "running", prompts: { b1: "p1" } }
    expect(sameProgramPreviewPrompts(base, { ...base, prompts: { b1: "p1" } })).toBe(true)
    expect(sameProgramPreviewPrompts(base, { ...base, status: "completed" })).toBe(false)
    expect(sameProgramPreviewPrompts(base, { ...base, prompts: { b1: "p2" } })).toBe(false)
    expect(sameProgramPreviewPrompts(base, null)).toBe(false)
  })
})
