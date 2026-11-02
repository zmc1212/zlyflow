import { describe, expect, it, vi } from "vitest"
import type { Director2Beat, Director2Job } from "../api"
import { activeEpisodeVideoJobs, ensureEpisodeShotPrompts, submitEpisodeShotTasks } from "./episode-shot-tasks"

function job(overrides: Partial<Director2Job> & { payload?: Record<string, any> }): Director2Job {
  return {
    id: "job-a",
    project_id: "p1",
    job_type: "video_generation",
    title: "视频任务",
    status: "running",
    progress: 10,
    result_url: null,
    error_message: null,
    payload: {},
    created_at: "",
    updated_at: "",
    ...overrides,
  }
}

function beat(id: string, sequence: number, extra: Partial<Director2Beat> = {}): Director2Beat {
  return { id, sequence, ...extra }
}

describe("active episode video jobs", () => {
  it("reports a blocking episode task and the beats occupied by shot tasks", () => {
    const activity = activeEpisodeVideoJobs([
      job({ id: "job-episode", payload: { episode_id: "ep-1", render_scope: "episode" } }),
      job({ id: "job-shot", status: "comfy_queued", payload: { episode_id: "ep-1", render_scope: "shot", beat_id: "beat-2" } }),
      job({ id: "job-selection", status: "running", payload: { episode_id: "ep-1", render_scope: "selection", beat_ids: ["beat-3", "beat-4"] } }),
      job({ id: "job-done", status: "completed", payload: { episode_id: "ep-1", render_scope: "shot", beat_id: "beat-9" } }),
      job({ id: "job-other", payload: { episode_id: "ep-2", render_scope: "episode" } }),
      job({ id: "job-image", job_type: "image_generation", payload: { episode_id: "ep-1", render_scope: "episode" } }),
    ], "ep-1")
    expect(activity.blockingJobId).toBe("job-episode")
    expect(activity.activeBeatIds.sort()).toEqual(["beat-2", "beat-3", "beat-4"])
  })

  it("does not report anything for other episodes or empty input", () => {
    expect(activeEpisodeVideoJobs([], "ep-1")).toEqual({ blockingJobId: "", activeBeatIds: [] })
    expect(activeEpisodeVideoJobs([
      job({ payload: { episode_id: "ep-2", render_scope: "episode" } }),
    ], "ep-1")).toEqual({ blockingJobId: "", activeBeatIds: [] })
  })
})

describe("submit episode shot tasks", () => {
  it("submits one task per shot in sequence order and reports progress", async () => {
    const calls: Array<{ beatId: string; options: Record<string, unknown> }> = []
    const progress: Array<{ index: number; total: number; sequence: number }> = []
    const result = await submitEpisodeShotTasks({
      beats: [beat("beat-3", 3), beat("beat-1", 1), beat("beat-2", 2)],
      options: { workflow: "wf", aspect_ratio: "16:9" },
      api: {
        generateBeatVideo: async (beatId, options) => {
          calls.push({ beatId, options })
          return { job_id: `job-${beatId}` }
        },
      },
      onProgress: (item) => progress.push(item),
    })
    expect(calls.map((item) => item.beatId)).toEqual(["beat-1", "beat-2", "beat-3"])
    expect(calls[0].options).toEqual({ workflow: "wf", aspect_ratio: "16:9" })
    expect(progress).toEqual([
      { index: 1, total: 3, sequence: 1 },
      { index: 2, total: 3, sequence: 2 },
      { index: 3, total: 3, sequence: 3 },
    ])
    expect(result).toMatchObject({
      ok: true,
      submitted: 3,
      skipped: 0,
      jobIds: ["job-beat-1", "job-beat-2", "job-beat-3"],
      submittedBeatIds: ["beat-1", "beat-2", "beat-3"],
      failures: [],
    })
  })

  it("skips finished shots, already submitted shots and shots already generating", async () => {
    const generateBeatVideo = vi.fn(async (beatId: string) => ({ job_id: `job-${beatId}` }))
    const result = await submitEpisodeShotTasks({
      beats: [
        beat("beat-1", 1, { video_url: "https://cdn/one.mp4" }),
        beat("beat-2", 2),
        beat("beat-3", 3),
        beat("beat-4", 4),
      ],
      options: {},
      skipBeatIds: new Set(["beat-2"]),
      inFlightBeatIds: ["beat-3"],
      api: { generateBeatVideo },
    })
    expect(generateBeatVideo).toHaveBeenCalledTimes(1)
    expect(generateBeatVideo).toHaveBeenCalledWith("beat-4", {})
    expect(result).toMatchObject({
      ok: true,
      submitted: 1,
      skipped: 3,
      jobIds: ["job-beat-4"],
      submittedBeatIds: ["beat-4"],
    })
  })

  it("keeps submitting the rest when one shot fails", async () => {
    const result = await submitEpisodeShotTasks({
      beats: [beat("beat-1", 1), beat("beat-2", 2), beat("beat-3", 3)],
      options: {},
      api: {
        generateBeatVideo: async (beatId) => {
          if (beatId === "beat-2") throw new Error("该镜头已有进行中的视频任务")
          return { job_id: `job-${beatId}` }
        },
      },
    })
    expect(result.ok).toBe(false)
    expect(result.submitted).toBe(2)
    expect(result.jobIds).toEqual(["job-beat-1", "job-beat-3"])
    expect(result.failures).toEqual([
      { beatId: "beat-2", sequence: 2, message: "该镜头已有进行中的视频任务" },
    ])
  })

  it("treats a response without a job id as a failure", async () => {
    const result = await submitEpisodeShotTasks({
      beats: [beat("beat-1", 1)],
      options: {},
      api: { generateBeatVideo: async () => ({}) },
    })
    expect(result.ok).toBe(false)
    expect(result.submitted).toBe(0)
    expect(result.failures[0]).toMatchObject({ beatId: "beat-1", message: "后端没有返回任务 ID" })
  })

  it("returns an empty result when nothing is left to submit", async () => {
    const generateBeatVideo = vi.fn(async () => ({ job_id: "unused" }))
    const result = await submitEpisodeShotTasks({
      beats: [],
      options: {},
      api: { generateBeatVideo },
    })
    expect(generateBeatVideo).not.toHaveBeenCalled()
    expect(result).toEqual({
      ok: true,
      submitted: 0,
      skipped: 0,
      jobIds: [],
      submittedBeatIds: [],
      failures: [],
    })
  })
})

describe("ensure episode shot prompts", () => {
  it("generates prompts only for beats missing one and waits for the saved result", async () => {
    const submitted: string[] = []
    const progress: Array<{ index: number; total: number; phase: string }> = []
    let polled = 0
    const result = await ensureEpisodeShotPrompts({
      beats: [
        beat("beat-2", 2),
        beat("beat-1", 1, { h3_prompt: "already saved" }),
        beat("beat-3", 3),
        beat("beat-4", 4),
      ],
      skipBeatIds: ["beat-4"],
      pollIntervalMs: 0,
      api: {
        generateBeatPrompt: async (beatId) => {
          submitted.push(beatId)
          return { job_id: `job-${beatId}` }
        },
        listJobs: async () => {
          polled += 1
          return [
            job({ id: "job-beat-2", job_type: "h3_prompt", status: "completed", payload: { h3_prompt: "prompt two" } }),
            job({
              id: "job-beat-3",
              job_type: "h3_prompt",
              status: polled > 1 ? "completed" : "running",
              payload: polled > 1 ? { h3_prompt: "prompt three" } : {},
            }),
          ]
        },
      },
      onProgress: (item) => progress.push(item),
    })
    expect(submitted).toEqual(["beat-2", "beat-3"])
    expect(polled).toBe(2)
    expect(progress[0]).toEqual({ index: 1, total: 2, sequence: 2, phase: "submit" })
    expect(progress.some((item) => item.phase === "wait")).toBe(true)
    expect(result).toEqual({ ok: true, prepared: 2, failures: [] })
  })

  it("counts a synchronous prompt response without polling", async () => {
    const listJobs = vi.fn(async () => [] as Director2Job[])
    const result = await ensureEpisodeShotPrompts({
      beats: [beat("beat-1", 1)],
      pollIntervalMs: 0,
      api: {
        generateBeatPrompt: async () => ({ prompt: "ready prompt", duplicate: true }),
        listJobs,
      },
    })
    expect(listJobs).not.toHaveBeenCalled()
    expect(result).toEqual({ ok: true, prepared: 1, failures: [] })
  })

  it("reports failed prompt jobs so the video tasks are not submitted", async () => {
    const result = await ensureEpisodeShotPrompts({
      beats: [beat("beat-1", 1), beat("beat-2", 2)],
      pollIntervalMs: 0,
      api: {
        generateBeatPrompt: async (beatId) => ({ job_id: `job-${beatId}` }),
        listJobs: async () => [
          job({ id: "job-beat-1", job_type: "h3_prompt", status: "failed", error_message: "模型超时", payload: {} }),
          job({ id: "job-beat-2", job_type: "h3_prompt", status: "completed", payload: { h3_prompt: "prompt two" } }),
        ],
      },
    })
    expect(result.ok).toBe(false)
    expect(result.prepared).toBe(1)
    expect(result.failures).toEqual([{ beatId: "beat-1", sequence: 1, message: "模型超时" }])
  })

  it("fails fast when a prompt job cannot be submitted", async () => {
    const result = await ensureEpisodeShotPrompts({
      beats: [beat("beat-1", 1), beat("beat-2", 2)],
      pollIntervalMs: 0,
      api: {
        generateBeatPrompt: async (beatId) => {
          if (beatId === "beat-1") throw new Error("Beat 1 缺少三联图")
          return { job_id: "job-beat-2" }
        },
        listJobs: async () => [
          job({ id: "job-beat-2", job_type: "h3_prompt", status: "completed", payload: { h3_prompt: "prompt two" } }),
        ],
      },
    })
    expect(result.ok).toBe(false)
    expect(result.prepared).toBe(1)
    expect(result.failures).toEqual([{ beatId: "beat-1", sequence: 1, message: "Beat 1 缺少三联图" }])
  })

  it("reports a timeout for prompt jobs that never finish", async () => {
    const result = await ensureEpisodeShotPrompts({
      beats: [beat("beat-1", 1)],
      pollIntervalMs: 0,
      timeoutMs: 0,
      api: {
        generateBeatPrompt: async () => ({ job_id: "job-beat-1" }),
        listJobs: async () => [job({ id: "job-beat-1", job_type: "h3_prompt", status: "running", payload: {} })],
      },
    })
    expect(result.ok).toBe(false)
    expect(result.failures[0]).toMatchObject({ beatId: "beat-1", sequence: 1 })
    expect(result.failures[0].message).toContain("超时")
  })
})
