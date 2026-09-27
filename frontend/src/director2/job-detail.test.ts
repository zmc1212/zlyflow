import { describe, expect, it } from "vitest"
import type { Director2Job } from "./api"
import { jobDetailVideos, mergeJobDetail } from "./job-detail"

function job(overrides: Partial<Director2Job> = {}): Director2Job {
  return { id: "job-1", project_id: "project-1", job_type: "video_generation", title: "视频任务",
    status: "running", progress: 20, result_url: null, error_message: null,
    payload: {}, created_at: "2026-09-27", updated_at: "2026-09-27", ...overrides }
}
const shot = { beat_id: "b1", sequence: 1, heading: "镜头一", prompt: "<Picture 1> walks into frame",
  h3_prompt: "saved H3 prompt", reference_urls: ["/reference.png"], character_references: [{ character_name: "主角" }] }

describe("job detail polling", () => {
  it("preserves full shot details across repeated slim polls while updating results and status", () => {
    const full = job({ payload: { shots: [shot], source_shots: [shot], runtime_stage: "running" } })
    const before = structuredClone(full)
    const summary = job({ status: "completed", progress: 100, result_url: "/result.mp4",
      payload: { shots: [{ beat_id: "b1", video_url: "/result.mp4" }],
        source_shots: [{ beat_id: "b1", video_url: null }], runtime_stage: "completed" } })
    let result = full
    for (let i = 0; i < 3; i++) result = mergeJobDetail(result, summary)
    expect(result.payload.shots[0]).toEqual({ ...shot, video_url: "/result.mp4" })
    expect(result.payload.source_shots[0]).toEqual({ ...shot, video_url: null })
    expect(result).toMatchObject({ status: "completed", progress: 100, result_url: "/result.mp4", payload: { runtime_stage: "completed" } })
    expect(full).toEqual(before)
  })
  it("matches by beat identity even when the list order changes", () => {
    const full = job({ payload: { shots: [shot, { ...shot, beat_id: "b2", prompt: "second" }] } })
    const result = mergeJobDetail(full, job({ payload: { shots: [{ beat_id: "b2" }, { beat_id: "b1" }, { beat_id: "new" }] } }))
    expect(result.payload.shots.map((item: typeof shot) => item.prompt)).toEqual(["second", shot.prompt, undefined])
  })
  it("retains source shot details when runtime shots first arrive", () => {
    const result = mergeJobDetail(job({ payload: { shots: [], source_shots: [shot] } }),
      job({ payload: { shots: [{ beat_id: "b1", video_url: "/result.mp4" }] } }))
    expect(result.payload.shots[0]).toMatchObject(shot)
    expect(result.payload.source_shots).toEqual([shot])
  })
  it("keeps omitted detail fields and accepts explicit top-level updates", () => {
    const result = mergeJobDetail(job({ payload: { shots: [shot], request_body: { prompt: "full" }, upscale_warning: "old" } }),
      job({ payload: { upscale_warning: "", upscaled_video_url: "/4x.mp4" } }))
    expect(result.payload).toMatchObject({ shots: [shot], request_body: { prompt: "full" }, upscale_warning: "", upscaled_video_url: "/4x.mp4" })
  })
  it("does not carry details between different tasks or projects", () => {
    const full = job({ payload: { shots: [shot] } })
    for (const summary of [job({ id: "job-2" }), job({ project_id: "project-2" })]) {
      expect(mergeJobDetail(full, summary)).toBe(summary)
    }
  })
  it("allows list-only details before the full request resolves", () => {
    const summary = job({ payload: { shots: [{ beat_id: "b1", video_url: null }] } })
    expect(mergeJobDetail(job(), summary)).toEqual(summary)
  })
})

describe("job detail video deduplication", () => {
  it("shows an ordinary generated video once", () => {
    expect(jobDetailVideos(job({ result_url: "/result.mp4" }))).toEqual({ resultUrl: "/result.mp4", sourceUrl: "" })
  })
  it("does not render an explicitly repeated source URL", () => {
    expect(jobDetailVideos(job({ result_url: "/result.mp4", payload: { source_video_url: " /result.mp4 " } })).sourceUrl).toBe("")
  })
  it.each([2, 4])("keeps distinct %sx upscaled and original versions once each", scale => {
    expect(jobDetailVideos(job({ result_url: "/original.mp4", payload: { upscaled_video_url: `/${scale}x.mp4` } })))
      .toEqual({ resultUrl: `/${scale}x.mp4`, sourceUrl: "/original.mp4" })
  })
  it("does not repeat the upscaled file when it is also result_url", () => {
    expect(jobDetailVideos(job({ result_url: "/4x.mp4", payload: { upscaled_video_url: "/4x.mp4" } })))
      .toEqual({ resultUrl: "/4x.mp4", sourceUrl: "" })
  })
  it("keeps the original for a separate upscale task", () => {
    expect(jobDetailVideos(job({ result_url: "/4x.mp4", payload: { render_scope: "upscale", source_video_url: "/original.mp4" } })))
      .toEqual({ resultUrl: "/4x.mp4", sourceUrl: "/original.mp4" })
  })
  it("does not invent videos for pending tasks", () => {
    expect(jobDetailVideos(null)).toEqual({ resultUrl: "", sourceUrl: "" })
    expect(jobDetailVideos(job())).toEqual({ resultUrl: "", sourceUrl: "" })
  })
})
