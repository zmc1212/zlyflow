import { describe, expect, it } from "vitest"
import {
  applyShotPlanJobSnapshot,
  applyShotPlanStreamEvent,
  assemblingShotsFromLive,
  documentCanPlanShots,
  documentShotPlanHeaderTag,
  emptyShotPlanLiveState,
  episodeShotPlanError,
  formatShotDurationLabel,
  isAssemblingShotPlan,
  isCurrentPlanningEpisode,
  isDocumentShotPlanning,
  isQueuedPlanningEpisode,
  isUsablePartialShot,
  markShotPlanLiveFinished,
  parsePartialShotPlanJson,
  readShotDurationSec,
  shotPlanEpisodeBadge,
  shotPlanProgressLabel,
  shotPlanProgressPercent,
  shotPlanSlimProgressLabel,
  shotPlanSourceForEpisode,
  shotPlanStatusCopy,
  shotsForEpisode,
  sumShotDurationSec,
} from "./shot-plan-live"

describe("shot plan live merge", () => {
  it("keeps thinking, JSON delta and episode cards on separate channels", () => {
    let state = emptyShotPlanLiveState("job-plan-1")
    state = applyShotPlanStreamEvent(state, {
      seq: 1,
      event: "status",
      data: { phase: "plan", message: "正在规划第1集（1/2）", reset: true, episode_num: 1, episode_index: 1, episode_total: 2 },
    })
    state = applyShotPlanStreamEvent(state, {
      seq: 2,
      event: "reasoning",
      data: { text: "对白太长，拆成开口和近景", episode_num: 1 },
    })
    state = applyShotPlanStreamEvent(state, {
      seq: 3,
      event: "delta",
      data: { text: '{"shots":[', episode_num: 1 },
    })
    expect(state.message).toBe("正在规划第1集（1/2）")
    expect(state.reasoning).toBe("对白太长，拆成开口和近景")
    expect(state.text).toBe('{"shots":[')
    expect(state.episodeNum).toBe(1)
    expect(state.working).toBe(true)
    expect(isCurrentPlanningEpisode(1, state, true)).toBe(true)

    state = applyShotPlanStreamEvent(state, {
      seq: 4,
      event: "episode_done",
      data: {
        episode_num: 1,
        episode_index: 1,
        episode_total: 2,
        shots: [{ shot_num: 1, title: "开口" }, { shot_num: 2, title: "近景" }],
        shots_count: 2,
        shots_source: "llm",
        error: null,
      },
    })
    expect(state.episodesDone).toHaveLength(1)
    expect(state.lastCompletedEpisodeNum).toBe(1)
    expect(state.reasoning).toBe("")
    expect(state.text).toBe("")
    expect(shotsForEpisode({ episode_num: 1, shots: [{ shot_num: 1, title: "解析器" }] }, state)).toEqual([
      { shot_num: 1, title: "开口" },
      { shot_num: 2, title: "近景" },
    ])
    expect(shotPlanSourceForEpisode({ episode_num: 1, shots_source: "" }, state)).toBe("llm")

    state = applyShotPlanStreamEvent(state, {
      seq: 5,
      event: "done",
      data: { status: "succeeded", document_id: "doc-1" },
    })
    expect(state.working).toBe(false)
    expect(state.message).toBe("镜头规划完成")
  })

  it("keeps parser shots and writes a failure line when an episode errors", () => {
    let state = emptyShotPlanLiveState("job-plan-1")
    state = applyShotPlanStreamEvent(state, {
      seq: 1,
      event: "episode_done",
      data: {
        episode_num: 2,
        shots: [{ shot_num: 1, title: "解析器" }],
        shots_count: 1,
        shots_source: null,
        error: "timeout",
      },
    })
    expect(state.message).toContain("规划失败")
    expect(episodeShotPlanError(2, ["解析完毕"], "timeout")).toBe(
      "第2集镜头规划失败，已保留解析器镜头：timeout",
    )
    expect(episodeShotPlanError(2, ["解析完毕", "第2集镜头规划失败，已保留解析器镜头：timeout"])).toContain(
      "第2集镜头规划失败",
    )
  })

  it("does not let a stale job snapshot overwrite a longer live buffer", () => {
    const live = {
      ...emptyShotPlanLiveState("job-plan-1"),
      reasoning: "abcdefghij",
      text: '{"shots":[{"title":"开口"}]}',
      episodeNum: 1,
    }
    const next = applyShotPlanJobSnapshot(live, {
      stream: { reasoning: "abc", text: '{"shots"', episode_num: 1, episode_index: 1, episode_total: 6 },
      episodes_done: [],
    })
    expect(next.reasoning).toBe("abcdefghij")
    expect(next.text).toBe('{"shots":[{"title":"开口"}]}')
    expect(next.episodeTotal).toBe(6)
  })

  it("builds a persistent banner so planning is visible without switching tabs", () => {
    const working = applyShotPlanStreamEvent(emptyShotPlanLiveState("job-1"), {
      seq: 1,
      event: "status",
      data: { message: "正在规划第2集（2/6）", episode_num: 2, episode_index: 2, episode_total: 6 },
    })
    expect(shotPlanProgressLabel(working)).toBe("第 2 / 6 集")
    expect(shotPlanSlimProgressLabel(working)).toBe("正在规划 第 2 / 6 集 · 本集已写出 0 条镜头")
    expect(shotPlanProgressPercent(working)).toBe(33)
    expect(shotPlanStatusCopy(working, true)).toEqual({
      kind: "working",
      title: "正在规划 第 2 / 6 集 · 本集已写出 0 条镜头",
      description: "",
    })
    expect(shotPlanStatusCopy(emptyShotPlanLiveState(), false)).toBeNull()

    let done = applyShotPlanStreamEvent(working, {
      seq: 2,
      event: "episode_done",
      data: { episode_num: 2, shots: [{ shot_num: 1 }], shots_count: 1, shots_source: "llm" },
    })
    done = applyShotPlanStreamEvent(done, { seq: 3, event: "done", data: { status: "succeeded" } })
    expect(shotPlanStatusCopy(done, false)).toBeNull()
    expect(markShotPlanLiveFinished(emptyShotPlanLiveState("job-1")).message).toBe("镜头规划完成")
  })

  it("gates sync and the plan button from document status", () => {
    expect(isDocumentShotPlanning({ status: "planning" })).toBe(true)
    expect(isDocumentShotPlanning({ status: "ready", shot_plan_job_id: "job-1" })).toBe(true)
    expect(isDocumentShotPlanning({ status: "ready" })).toBe(false)
    expect(documentCanPlanShots({
      status: "ready",
      input_mode: "paste",
      analysis: { episodes: [{ episode_num: 1, shots_source: "" }] },
    })).toBe(true)
    expect(documentCanPlanShots({
      status: "ready",
      input_mode: "paste",
      analysis: { episodes: [{ episode_num: 1, shots_source: "llm" }] },
    })).toBe(false)
    expect(documentCanPlanShots({
      status: "ready",
      input_mode: "ai_pipeline",
      analysis: { episodes: [{ episode_num: 1 }] },
    })).toBe(false)
    expect(documentCanPlanShots({ status: "planning", analysis: { episodes: [{ episode_num: 1 }] } })).toBe(false)
  })

  it("labels parser shots as unplanned instead of hiding the tag", () => {
    expect(documentShotPlanHeaderTag({
      status: "ready",
      analysis: { episodes: [{ episode_num: 1, shots_source: null }] },
    })).toEqual({ color: "warning", text: "未规划" })
    expect(documentShotPlanHeaderTag({
      status: "ready",
      analysis: { episodes: [{ episode_num: 1, shots_source: "llm" }] },
    })).toEqual({ color: "success", text: "已规划" })
    expect(shotPlanEpisodeBadge({ source: "", planningCurrent: false })).toEqual({ text: "剧本切镜" })
    expect(shotPlanEpisodeBadge({ source: "llm", planningCurrent: false })).toEqual({ color: "success", text: "已规划" })
    expect(shotPlanEpisodeBadge({
      source: "llm",
      planningCurrent: false,
      shotCount: 8,
      durationSec: 72,
    })).toEqual({ color: "success", text: "已规划 · 8 镜 · 72 秒" })
    expect(shotPlanEpisodeBadge({ source: "", planningCurrent: false, queued: true })).toEqual({ text: "排队" })
    expect(shotPlanEpisodeBadge({
      source: "",
      planningCurrent: true,
      planError: "timeout",
    })).toEqual({ color: "error", text: "规划失败" })
    expect(shotPlanEpisodeBadge({ source: "", planningCurrent: true })).toEqual({ color: "processing", text: "规划中" })
    expect(shotPlanStatusCopy(emptyShotPlanLiveState(), false, { needsPlan: true })).toBeNull()
  })
})

describe("parsePartialShotPlanJson", () => {
  it("returns nothing for empty or non-json text", () => {
    expect(parsePartialShotPlanJson("")).toEqual({ shots: [], currentOpen: false })
    expect(parsePartialShotPlanJson("Planning shot durations...")).toEqual({ shots: [], currentOpen: false })
  })

  it("parses a complete shots object", () => {
    const parsed = parsePartialShotPlanJson('{"shots":[{"title":"开口","action":"站起来","duration_sec":8}]}')
    expect(parsed.currentOpen).toBe(false)
    expect(parsed.shots).toEqual([{ title: "开口", action: "站起来", duration_sec: 8 }])
  })

  it("unwraps markdown fences even when the closing fence is missing", () => {
    const parsed = parsePartialShotPlanJson("```json\n{\"shots\":[{\"title\":\"开口\",\"action\":\"站起来\"")
    expect(parsed.shots[0]).toMatchObject({ title: "开口", action: "站起来" })
    expect(parsed.currentOpen).toBe(true)
  })

  it("keeps closed objects and completed fields on the open object", () => {
    const parsed = parsePartialShotPlanJson(
      '{"shots":[{"title":"开口","action":"站起来"},{"title":"近景","action":"',
    )
    expect(parsed.shots).toEqual([
      { title: "开口", action: "站起来" },
      { title: "近景" },
    ])
    expect(parsed.currentOpen).toBe(true)
    expect(isUsablePartialShot(parsed.shots[1])).toBe(true)
  })

  it("omits a truncated string value until the quote closes", () => {
    const parsed = parsePartialShotPlanJson('{"shots":[{"title":"开')
    expect(parsed.shots).toEqual([{}])
    expect(parsed.currentOpen).toBe(true)
    expect(isUsablePartialShot(parsed.shots[0])).toBe(false)
  })

  it("accepts fields in any order, including action before title", () => {
    const parsed = parsePartialShotPlanJson(
      '{"shots":[{"action":"走向门口","characters":["吴耐"],"title":"迈步","duration_sec":7}',
    )
    expect(parsed.shots[0]).toMatchObject({
      action: "走向门口",
      characters: ["吴耐"],
      title: "迈步",
      duration_sec: 7,
    })
  })

  it("keeps finished names when a characters array is still open", () => {
    const parsed = parsePartialShotPlanJson('{"shots":[{"title":"开口","characters":["吴耐","沙')
    expect(parsed.shots[0]).toEqual({ title: "开口", characters: ["吴耐"] })
  })

  it("grows fields as more of the same object arrives", () => {
    const first = parsePartialShotPlanJson('{"shots":[{"title":"914就要死"')
    const second = parsePartialShotPlanJson(
      '{"shots":[{"title":"914就要死","scene":"单元楼","action":"吴耐站住"',
    )
    expect(first.shots[0]).toEqual({ title: "914就要死" })
    expect(second.shots[0]).toMatchObject({
      title: "914就要死",
      scene: "单元楼",
      action: "吴耐站住",
    })
  })

  it("ignores prose before the JSON object", () => {
    const parsed = parsePartialShotPlanJson('Here is the plan:\n{"shots":[{"title":"开口","action":"起身"}]}')
    expect(parsed.shots[0]).toMatchObject({ title: "开口", action: "起身" })
  })
})

describe("shot plan assembling cards", () => {
  it("uses partial JSON for the current episode and hides parser cards until a usable shot appears", () => {
    let state = emptyShotPlanLiveState("job-plan-1")
    state = applyShotPlanStreamEvent(state, {
      seq: 1,
      event: "status",
      data: { message: "正在规划第2集（2/6）", reset: true, episode_num: 2, episode_index: 2, episode_total: 6 },
    })
    state = applyShotPlanStreamEvent(state, {
      seq: 2,
      event: "delta",
      data: { text: '{"shots":[{"title":"开', episode_num: 2 },
    })
    const parserShot = { shot_num: 1, title: "914就要死" }
    expect(shotsForEpisode({ episode_num: 2, shots: [parserShot] }, state, true)).toEqual([])
    expect(shotPlanSlimProgressLabel(state)).toBe("正在规划 第 2 / 6 集 · 本集已写出 0 条镜头")
    expect(shotPlanSlimProgressLabel(state)).not.toContain("{")
    expect(isQueuedPlanningEpisode(3, state, true)).toBe(true)
    expect(isQueuedPlanningEpisode(1, state, true)).toBe(false)

    state = applyShotPlanStreamEvent(state, {
      seq: 3,
      event: "delta",
      data: {
        text: '{"shots":[{"title":"开口","action":"站起来","duration_sec":8},{"title":"近景","action":"',
        episode_num: 2,
      },
    })
    expect(assemblingShotsFromLive(state)).toEqual([
      { title: "开口", action: "站起来", duration_sec: 8, shot_num: 1 },
      { title: "近景", shot_num: 2 },
    ])
    expect(shotsForEpisode({ episode_num: 2, shots: [parserShot] }, state, true)).toHaveLength(2)
    expect(shotsForEpisode({ episode_num: 1, shots: [parserShot] }, state, true)).toEqual([parserShot])
    expect(shotsForEpisode({ episode_num: 3, shots: [parserShot] }, state, true)).toEqual([parserShot])
    expect(shotPlanSlimProgressLabel(state)).toBe("正在规划 第 2 / 6 集 · 本集已写出 2 条镜头")
    expect(isAssemblingShotPlan(state)).toBe(true)
  })

  it("keeps parser shots on a failed episode even while that episode is still current", () => {
    let state = emptyShotPlanLiveState("job-plan-1")
    state = applyShotPlanStreamEvent(state, {
      seq: 1,
      event: "status",
      data: { message: "正在规划第2集（2/6）", reset: true, episode_num: 2, episode_index: 2, episode_total: 6 },
    })
    const parserShot = { shot_num: 1, title: "914就要死" }
    state = applyShotPlanStreamEvent(state, {
      seq: 2,
      event: "episode_done",
      data: {
        episode_num: 2,
        shots: [parserShot],
        shots_count: 1,
        shots_source: null,
        error: "timeout",
      },
    })
    expect(shotsForEpisode({ episode_num: 2, shots: [parserShot] }, state, true)).toEqual([parserShot])
    expect(shotPlanEpisodeBadge({
      source: "",
      planningCurrent: isCurrentPlanningEpisode(2, state, true),
      planError: episodeShotPlanError(2, [], "timeout"),
    })).toEqual({ color: "error", text: "规划失败" })
  })

  it("coerces duration_sec strings so live cards can show seconds", () => {
    expect(readShotDurationSec({ duration_sec: "8秒" })).toBe(8)
    expect(formatShotDurationLabel("12")).toBe("12 秒")
    expect(sumShotDurationSec([
      { duration_sec: 8 },
      { duration_sec: "10" },
      { duration_sec: undefined },
    ])).toBe(18)

    const live = {
      ...emptyShotPlanLiveState("job-plan-1"),
      working: true,
      text: '{"shots":[{"title":"开口","duration_sec":"8"}]}',
    }
    expect(assemblingShotsFromLive(live)).toEqual([
      { title: "开口", duration_sec: 8, shot_num: 1 },
    ])
  })
})
