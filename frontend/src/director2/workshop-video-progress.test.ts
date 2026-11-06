import { describe, expect, it } from "vitest"
import {
  clampWorkshopProgress,
  hasActiveWorkshopVideoProgress,
  isActiveWorkshopJobStatus,
  isWorkshopShotRendered,
  mapWorkshopVideoProgress,
  mapWorkshopVideoFailures,
  workshopVideoOverlayLabel,
  workshopVideoPercentLabel,
  workshopVideoStageLabel,
  workshopEpisodeBannerLabel,
  workshopEpisodeStageLabel,
  type WorkshopVideoJobLike,
} from "./workshop-video-progress"

function job(partial: Partial<WorkshopVideoJobLike> = {}): WorkshopVideoJobLike {
  return {
    job_type: "video_generation",
    status: "running",
    progress: 40,
    ...partial,
    payload: {
      episode_id: "ep-1",
      render_scope: "shot",
      beat_id: "beat-a",
      ...partial.payload,
    },
  }
}

describe("workshop video progress mapping", () => {
  it("maps shot jobs by beat_id and keeps the newest in-progress job", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({ status: "running", progress: 42, payload: { beat_id: "beat-a" } }),
        job({ status: "queued", progress: 0, payload: { beat_id: "beat-a" } }),
        job({ status: "preparing", progress: 10, payload: { beat_id: "beat-b" } }),
      ],
      "ep-1",
    )
    expect(mapped.beats).toEqual({
      "beat-a": { status: "running", progress: 42, scope: "shot", stage: "", jobId: "", previewUrl: "", shotCount: 1 },
      "beat-b": { status: "preparing", progress: 10, scope: "shot", stage: "", jobId: "", previewUrl: "", shotCount: 1 },
    })
    expect(mapped.episode).toBeNull()
  })

  it("maps episode and compose jobs without stamping every shot", () => {
    const episode = mapWorkshopVideoProgress(
      [job({ payload: { render_scope: "episode", beat_id: "beat-a" }, progress: 55 })],
      "ep-1",
    )
    expect(episode.beats).toEqual({})
    expect(episode.episode).toEqual({ status: "running", progress: 55, scope: "episode", jobId: "" })

    const compose = mapWorkshopVideoProgress(
      [
        job({ status: "storing", progress: 90, payload: { render_scope: "compose", beat_id: undefined } }),
        job({ status: "running", progress: 30, payload: { render_scope: "episode" } }),
      ],
      "ep-1",
    )
    expect(compose.episode).toEqual({ status: "storing", progress: 90, scope: "compose", jobId: "" })
    expect(hasActiveWorkshopVideoProgress(compose)).toBe(true)
  })

  it("ignores other episodes, other job types, and terminal video jobs", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({ job_type: "image_generation", payload: { beat_id: "beat-a" } }),
        job({ status: "completed", progress: 100, payload: { beat_id: "beat-a" } }),
        job({ status: "failed", progress: 0, payload: { beat_id: "beat-b" } }),
        job({ payload: { episode_id: "ep-2", beat_id: "beat-a" } }),
        job({ status: "queued", progress: 0, payload: { beat_id: "beat-c" } }),
      ],
      "ep-1",
    )
    expect(mapped.beats).toEqual({
      "beat-c": { status: "queued", progress: 0, scope: "shot", stage: "", jobId: "", previewUrl: "", shotCount: 1 },
    })
    expect(hasActiveWorkshopVideoProgress(mapped)).toBe(true)
    expect(hasActiveWorkshopVideoProgress({ beats: {}, episode: null })).toBe(false)
  })

  it("stamps a Director selection job onto every selected beat", () => {
    const mapped = mapWorkshopVideoProgress(
      [job({
        status: "preparing",
        progress: 12,
        payload: { render_scope: "selection", beat_id: undefined, beat_ids: ["beat-a", "beat-b"] },
      })],
      "ep-1",
    )
    expect(mapped.beats).toEqual({
      "beat-a": { status: "preparing", progress: 12, scope: "selection", stage: "", jobId: "", previewUrl: "", shotCount: 2 },
      "beat-b": { status: "preparing", progress: 12, scope: "selection", stage: "", jobId: "", previewUrl: "", shotCount: 2 },
    })
    expect(mapped.episode).toBeNull()
  })

  it("clamps progress and uses workshop stage copy", () => {
    expect(clampWorkshopProgress(undefined)).toBe(0)
    expect(clampWorkshopProgress(141.6)).toBe(100)
    expect(workshopVideoPercentLabel(42.2)).toBe("42%")
    expect(isActiveWorkshopJobStatus("running")).toBe(true)
    expect(isActiveWorkshopJobStatus("succeeded")).toBe(false)
    expect(workshopVideoStageLabel("queued")).toBe("排队中")
    expect(workshopVideoStageLabel("preparing")).toBe("准备素材")
    expect(workshopVideoStageLabel("prompt_generation")).toBe("整理生成指令")
    expect(workshopVideoStageLabel("preparing", { message: "正在规划关键帧" })).toBe("正在规划关键帧")
    expect(workshopVideoStageLabel("comfy_queued")).toBe("远端排队")
    expect(workshopVideoOverlayLabel("comfy_queued", 5)).toBe("远端排队")
    expect(workshopVideoStageLabel("storing")).toBe("保存结果")
    expect(workshopVideoOverlayLabel("running", 42)).toBe("生成中 42%")
    expect(workshopVideoOverlayLabel("queued", 0)).toBe("排队中")
    expect(workshopVideoOverlayLabel("upscaling", 97)).toBe("智能超清中 97%")
    expect(workshopVideoOverlayLabel("running", 98, { scope: "upscale" })).toBe("智能超清中 98%")
  })

  it("keeps preparation progress after reloading and clears superseded failures", () => {
    const prepared = job({ status: "prompt_generation", payload: { preparation: { stage: "prompt", message: "正在整理生成指令" } } })
    expect(mapWorkshopVideoProgress([prepared], "ep-1").beats["beat-a"].message).toBe("正在整理生成指令")
    const failure = job({ id: "failed", status: "failed", error_message: "提示词服务不可用" })
    expect(mapWorkshopVideoFailures([failure], "ep-1")["beat-a"]).toMatchObject({ jobId: "failed", error: "提示词服务不可用" })
    expect(mapWorkshopVideoFailures([job({ status: "completed" }), failure], "ep-1")).toEqual({})
    expect(mapWorkshopVideoFailures([job({ status: "queued" }), failure], "ep-1")).toEqual({})
    expect(mapWorkshopVideoFailures([failure], "other-episode")).toEqual({})
    expect(mapWorkshopVideoFailures([job({ status: "failed", error_message: "missing <Picture 1>" })], "ep-1")["beat-a"].error).toBe("生成指令未完整引用角色或场景参考图，请重试当前步骤。")
    const batch = job({ status: "prompt_generation", payload: { prompt_generation_progress: { completed: 3, total: 15 } } })
    const progress = mapWorkshopVideoProgress([batch], "ep-1").beats["beat-a"]
    expect(workshopVideoOverlayLabel(progress.status, progress.progress, progress)).toBe("整理生成指令 3 / 15")
  })

  it("maps a dedicated beat upscale job onto that shot", () => {
    const mapped = mapWorkshopVideoProgress(
      [job({
        status: "upscaling",
        progress: 97,
        payload: { render_scope: "upscale", beat_id: "beat-a", runtime_stage: "upscaling" },
      })],
      "ep-1",
    )
    expect(mapped.beats).toEqual({
      "beat-a": { status: "upscaling", progress: 97, scope: "upscale", stage: "upscaling", jobId: "", previewUrl: "", shotCount: 1 },
    })
    expect(mapped.episode).toBeNull()
  })

  it("distinguishes the batch group count from a step percentage that can reset", () => {
    const batch = job({ payload: { render_scope: "selection", render_progress: { total: 8, completed: 2, current: 3 } } })
    const progress = mapWorkshopVideoProgress([batch], "ep-1").beats["beat-a"]
    expect(workshopVideoOverlayLabel("running", 80, progress)).toBe("正在生成第 3 / 8 组 · 当前步骤 80%")
    expect(workshopVideoOverlayLabel("running", 12, progress)).toBe("正在生成第 3 / 8 组 · 当前步骤 12%")
    expect(workshopVideoOverlayLabel("comfy_queued", 5, progress)).toBe("第 3 / 8 组远端排队")
    expect(workshopVideoOverlayLabel("assembling", 96, progress)).toBe("保存结果")
  })

  it("splits a running batch into per-shot stages once a segment lands", () => {
    const batch = job({
      progress: 62,
      payload: {
        render_scope: "selection",
        beat_id: undefined,
        beat_ids: ["beat-a", "beat-b", "beat-c"],
        render_progress: { total: 2, completed: 1, current: 2 },
        shot_status: { "beat-a": "succeeded", "beat-b": "running", "beat-c": "queued" },
        shots: [{ beat_id: "beat-a", video_url: "/api/shot-a.mp4" }, { beat_id: "beat-b", video_url: null }],
      },
    })
    const mapped = mapWorkshopVideoProgress([batch], "ep-1")
    expect(mapped.beats["beat-a"]).toMatchObject({ shotStage: "succeeded", shotUrl: "/api/shot-a.mp4" })
    expect(mapped.beats["beat-b"]).toMatchObject({ shotStage: "running" })
    expect(mapped.beats["beat-c"]).toMatchObject({ shotStage: "queued", progress: 62 })
    expect(isWorkshopShotRendered(mapped.beats["beat-a"])).toBe(true)
    expect(isWorkshopShotRendered(mapped.beats["beat-b"])).toBe(false)
    expect(workshopVideoOverlayLabel("running", 62, mapped.beats["beat-a"])).toBe("本镜已出片 · 整批 1 / 2 组")
    expect(workshopVideoOverlayLabel("running", 62, mapped.beats["beat-c"])).toBe("排队中 · 第 2 / 2 组")
    expect(workshopVideoOverlayLabel("running", 62, mapped.beats["beat-b"])).toBe("正在生成第 2 / 2 组 · 当前步骤 62%")
    expect(hasActiveWorkshopVideoProgress(mapped)).toBe(true)
  })

  it("keeps a rendered segment honest until its shot files land in the job", () => {
    const saving = job({
      progress: 95,
      payload: {
        render_scope: "selection",
        beat_id: undefined,
        beat_ids: ["beat-a", "beat-b"],
        render_progress: { total: 2, completed: 2, current: 2 },
        shot_status: { "beat-a": "succeeded", "beat-b": "succeeded" },
        shots: [{ beat_id: "beat-a", video_url: null }, { beat_id: "beat-b", video_url: null }],
      },
    })
    const mapped = mapWorkshopVideoProgress([saving], "ep-1")
    expect(mapped.beats["beat-a"]).toMatchObject({ shotStage: "saving" })
    expect(mapped.beats["beat-a"].shotUrl).toBeUndefined()
    expect(isWorkshopShotRendered(mapped.beats["beat-a"])).toBe(false)
    expect(workshopVideoOverlayLabel("running", 95, mapped.beats["beat-a"])).toBe("画面已渲染 · 正在保存成片 · 当前步骤 95%")
    const landed = job({
      progress: 95,
      payload: {
        render_scope: "selection",
        beat_id: undefined,
        beat_ids: ["beat-a", "beat-b"],
        render_progress: { total: 2, completed: 2, current: 2 },
        shot_status: { "beat-a": "succeeded", "beat-b": "succeeded" },
        shots: [{ beat_id: "beat-a", video_url: "/api/shot-a.mp4" }, { beat_id: "beat-b", video_url: null }],
      },
    })
    const after = mapWorkshopVideoProgress([landed], "ep-1")
    expect(after.beats["beat-a"]).toMatchObject({ shotStage: "succeeded", shotUrl: "/api/shot-a.mp4" })
    expect(after.beats["beat-b"]).toMatchObject({ shotStage: "saving" })
  })

  it("shows a single-shot batch as its own shot without group counts", () => {
    const single = job({ payload: { shot_status: { "beat-a": "succeeded" }, shots: [{ beat_id: "beat-a", video_url: "/api/a.mp4" }] } })
    const progress = mapWorkshopVideoProgress([single], "ep-1").beats["beat-a"]
    expect(workshopVideoOverlayLabel("running", 70, progress)).toBe("本镜已出片")
  })

  it("keeps a first-pass preview available while waiting for a refinement decision", () => {
    const mapped = mapWorkshopVideoProgress([
      job({ id: "preview-job", status: "awaiting_refine", progress: 50, result_url: "/api/preview/first-pass.mp4" }),
    ], "ep-1")
    expect(mapped.beats["beat-a"]).toMatchObject({
      status: "awaiting_refine", jobId: "preview-job", previewUrl: "/api/preview/first-pass.mp4", shotCount: 1,
    })
    expect(hasActiveWorkshopVideoProgress(mapped)).toBe(false)
    expect(workshopVideoStageLabel("awaiting_refine")).toBe("一采预览待确认")
  })

  it("stamps per-shot progress onto the cards once an episode job starts rendering segments", () => {
    const mapped = mapWorkshopVideoProgress([
      job({
        status: "running",
        progress: 62,
        payload: {
          render_scope: "episode",
          beat_id: undefined,
          render_progress: { total: 3, completed: 1, current: 2 },
          shot_status: { "beat-a": "succeeded", "beat-b": "running", "beat-c": "queued" },
          shots: [{ beat_id: "beat-a", video_url: "/api/a.mp4" }],
        },
      }),
    ], "ep-1")
    expect(mapped.beats["beat-a"]).toMatchObject({ shotStage: "succeeded", shotUrl: "/api/a.mp4", scope: "episode" })
    expect(mapped.beats["beat-b"]).toMatchObject({ shotStage: "running" })
    expect(mapped.beats["beat-c"]).toMatchObject({ shotStage: "queued" })
    expect(isWorkshopShotRendered(mapped.beats["beat-a"])).toBe(true)
    expect(mapped.episode).toMatchObject({ scope: "episode", renderProgress: { total: 3, completed: 1, current: 2 }, shotCount: 3 })
    expect(hasActiveWorkshopVideoProgress(mapped)).toBe(true)
  })

  it("keeps cards blank during prompt prep and reports the whole-episode stage on the banner", () => {
    const mapped = mapWorkshopVideoProgress([
      job({ status: "prompt_generation", progress: 5, payload: { render_scope: "episode", beat_id: undefined, prompt_generation_progress: { completed: 3, total: 15 } } }),
    ], "ep-1")
    expect(mapped.beats).toEqual({})
    expect(mapped.episode).toMatchObject({ scope: "episode", promptProgress: { completed: 3, total: 15 } })
    expect(workshopEpisodeStageLabel(mapped.episode!)).toBe("整理生成指令 3 / 15")
  })

  it("phrases the episode banner across render, save and compose stages", () => {
    expect(workshopEpisodeStageLabel({ status: "running", progress: 40, scope: "episode", renderProgress: { total: 4, completed: 1, current: 2 } })).toBe("正在生成第 2 / 4 组 · 已完成 1 · 40%")
    expect(workshopEpisodeStageLabel({ status: "storing", progress: 90, scope: "episode", renderProgress: { total: 4, completed: 4, current: 4 } })).toBe("保存结果 · 已完成 4 / 4 组")
    expect(workshopEpisodeStageLabel({ status: "preparing", progress: 0, scope: "episode", message: "正在规划关键帧" })).toBe("正在规划关键帧")
    expect(workshopEpisodeStageLabel({ status: "running", progress: 20, scope: "compose" })).toBe("整集合片中")
  })

  it("prefixes the banner with 整集生成中 only when the stage wording does not already say it", () => {
    expect(workshopEpisodeBannerLabel({ status: "running", progress: 40, scope: "episode", renderProgress: { total: 4, completed: 1, current: 2 } }))
      .toBe("整集生成中 · 正在生成第 2 / 4 组 · 已完成 1 · 40%")
    expect(workshopEpisodeBannerLabel({ status: "running", progress: 20, scope: "compose" })).toBe("整集合片中")
  })
})

describe("gap_fill progress mapping", () => {
  it("surfaces a gap_fill selection job as the episode banner with segment i/n", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({
          status: "running",
          progress: 55,
          payload: {
            render_scope: "selection",
            beat_ids: ["beat-2", "beat-3"],
            strategy: "gap_fill",
            segment_index: 2,
            segment_total: 3,
          },
        }),
      ],
      "ep-1",
    )
    expect(mapped.episode).not.toBeNull()
    expect(mapped.episode!.gapSegment).toEqual({ index: 2, total: 3 })
    expect(workshopEpisodeStageLabel(mapped.episode!)).toBe("补跑区间 2 / 3 · 生成中 55%")
    expect(workshopEpisodeBannerLabel(mapped.episode!)).toBe("整集补跑中 · 生成中 55%")
    expect(mapped.beats["beat-2"]).toBeTruthy()
    expect(mapped.beats["beat-3"]).toBeTruthy()
  })

  it("keeps plain selection jobs off the episode banner", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({
          payload: { render_scope: "selection", beat_ids: ["beat-2"] },
        }),
      ],
      "ep-1",
    )
    expect(mapped.episode).toBeNull()
    expect(mapped.beats["beat-2"]).toBeTruthy()
  })

  it("prefers a real episode job over an older gap_fill selection job", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({ payload: { render_scope: "episode" } }),
        job({ payload: { render_scope: "selection", beat_ids: ["beat-2"], strategy: "gap_fill", segment_index: 1, segment_total: 2 } }),
      ],
      "ep-1",
    )
    expect(mapped.episode?.scope).toBe("episode")
    expect(mapped.episode?.gapSegment).toBeUndefined()
  })

  it("ignores gap_fill payloads without segment_total", () => {
    const mapped = mapWorkshopVideoProgress(
      [
        job({ payload: { render_scope: "selection", beat_ids: ["beat-2"], strategy: "gap_fill" } }),
      ],
      "ep-1",
    )
    expect(mapped.episode).toBeNull()
  })
})
