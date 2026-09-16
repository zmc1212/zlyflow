import { describe, expect, it } from "vitest"
import {
  clampWorkshopProgress,
  hasActiveWorkshopVideoProgress,
  isActiveWorkshopJobStatus,
  mapWorkshopVideoProgress,
  workshopVideoOverlayLabel,
  workshopVideoPercentLabel,
  workshopVideoStageLabel,
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
      "beat-a": { status: "running", progress: 42 },
      "beat-b": { status: "preparing", progress: 10 },
    })
    expect(mapped.episode).toBeNull()
  })

  it("maps episode and compose jobs without stamping every shot", () => {
    const episode = mapWorkshopVideoProgress(
      [job({ payload: { render_scope: "episode", beat_id: "beat-a" }, progress: 55 })],
      "ep-1",
    )
    expect(episode.beats).toEqual({})
    expect(episode.episode).toEqual({ status: "running", progress: 55, scope: "episode" })

    const compose = mapWorkshopVideoProgress(
      [
        job({ status: "storing", progress: 90, payload: { render_scope: "compose", beat_id: undefined } }),
        job({ status: "running", progress: 30, payload: { render_scope: "episode" } }),
      ],
      "ep-1",
    )
    expect(compose.episode).toEqual({ status: "storing", progress: 90, scope: "compose" })
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
      "beat-c": { status: "queued", progress: 0 },
    })
    expect(hasActiveWorkshopVideoProgress(mapped)).toBe(true)
    expect(hasActiveWorkshopVideoProgress({ beats: {}, episode: null })).toBe(false)
  })

  it("clamps progress and uses workshop stage copy", () => {
    expect(clampWorkshopProgress(undefined)).toBe(0)
    expect(clampWorkshopProgress(141.6)).toBe(100)
    expect(workshopVideoPercentLabel(42.2)).toBe("42%")
    expect(isActiveWorkshopJobStatus("running")).toBe(true)
    expect(isActiveWorkshopJobStatus("succeeded")).toBe(false)
    expect(workshopVideoStageLabel("queued")).toBe("排队中")
    expect(workshopVideoStageLabel("preparing")).toBe("准备素材")
    expect(workshopVideoStageLabel("comfy_queued")).toBe("准备素材")
    expect(workshopVideoStageLabel("storing")).toBe("保存结果")
    expect(workshopVideoOverlayLabel("running", 42)).toBe("生成中 42%")
    expect(workshopVideoOverlayLabel("queued", 0)).toBe("排队中")
    expect(workshopVideoOverlayLabel("preparing", 10)).toBe("准备素材")
  })
})
