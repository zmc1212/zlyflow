import { describe, expect, it } from "vitest"
import {
  buildStoryboardStreamModel,
  episodeShotCountLabel,
  groupPolishShotNumbers,
  parseStoryboardPhase,
  polishPhaseTitle,
  polishShotLegend,
  resolveActiveEpisodeNumber,
  resolveEpisodeRowStatus,
  resolvePolishCurrentShot,
  resolvePolishGroupStatus,
  shotDurationLabel,
} from "./storyboard-stream-view"

describe("storyboard stream view", () => {
  it("parses polish progress messages", () => {
    expect(parseStoryboardPhase("正在按秒分配对白与动作 (2/3) · 第 4-6 镜 · 已收 120 字")).toMatchObject({ title: "按秒分配对白与动作", index: 2, total: 3, range: [4, 6], chars: 120 })
  })

  it("parses writing and reading wait messages including episode prefixes", () => {
    expect(parseStoryboardPhase("第 1 集 · 正在写分镜 (1/3) - 已收 12 字")).toMatchObject({ title: "写分镜", episode: 1, index: 1, total: 3, chars: 12 })
    expect(parseStoryboardPhase("正在读剧本并构思 (2/3)")).toMatchObject({ title: "阅读剧本并构思", index: 2, total: 3 })
    expect(parseStoryboardPhase("第 2 集 · 正在按秒分配对白与动作 (1/3)")).toMatchObject({ title: "按秒分配对白与动作", episode: 2, index: 1, total: 3 })
  })

  it("resolves the current polish shot from the message, not the stream ordinal", () => {
    const phase = parseStoryboardPhase("第 1 集 · 正在按秒分配对白与动作 (1/3) · 第 1-2 镜 · 正在第 1 镜 - 已收 120 字")
    expect(phase).not.toBeNull()
    expect(resolvePolishCurrentShot(phase!, { ordinal: 2 })).toBe(1)
    expect(resolvePolishCurrentShot({ title: "按秒分配对白与动作", range: [1, 2] }, { ordinal: 1 })).toBe(2)
    expect(polishPhaseTitle(phase!)).toBe("第 1 集 · 按秒分配对白与动作 · 第 1/3 批")
  })

  it("groups polish chips by episode and labels the series shot total", () => {
    const groups = groupPolishShotNumbers([
      { number: 1, shots: [{ shotNumber: 1 }, { shotNumber: 2 }, { shotNumber: 1 }] },
      { number: 2, shots: [{ shotNumber: 3 }, { shotNumber: 4 }, { shotNumber: 5 }] },
    ])
    expect(groups).toEqual([
      { episode: 1, label: "第 1 集", numbers: [1, 2] },
      { episode: 2, label: "第 2 集", numbers: [3, 4, 5] },
    ])
    const phase = parseStoryboardPhase("第 1 集 · 正在按秒分配对白与动作 (1/3) · 第 1-2 镜")
    expect(polishShotLegend(phase!, groups)).toBe("全剧 2 集 · 共 5 镜 · 当前第 1 集 · 正在打磨第 1–2 镜")
  })

  it("groups episodes, scenes and shots while preserving episode context", () => {
    const model = buildStoryboardStreamModel({
      shownTexts: { "storyboard|storyboard|title|0|2": "雨夜相遇" },
      targetTexts: { "storyboard|storyboard|title|0|2": "雨夜相遇" },
      streamItems: {
        "episodes|episodes|0": { title: "第 1 集" },
        "episodes|episodes|1": { title: "第 2 集" },
        "storyboard|storyboard|scenes|0|2": { title: "车站" , episodeNumber: 2 },
        "storyboard|storyboard|shots|0|2": { title: "远景", episodeNumber: 2 },
      },
      activeIndex: { "storyboard|title": 0 },
      live: false,
    })
    expect(model.episodes.map((episode) => episode.number)).toEqual([1, 2])
    expect(model.episodes[1].scenes[0].title).toBe("车站")
    expect(model.episodes[1].shots[0].title).toBe("远景")
  })

  it("opens the live episode by default and collapses completed ones", () => {
    const live = buildStoryboardStreamModel({
      shownTexts: { "storyboard|storyboard|title|0|2": "窗边" },
      targetTexts: { "storyboard|storyboard|title|0|2": "窗边" },
      streamItems: {
        "episodes|episodes|0": { title: "第 1 集 · 雨夜" },
        "episodes|episodes|1": { title: "第 2 集 · 白日" },
        "storyboard|storyboard|shots|0|1": { title: "巷口", episodeNumber: 1, durationSec: 6 },
        "storyboard|storyboard|shots|0|2": { title: "窗边", episodeNumber: 2 },
      },
      activeIndex: { "storyboard|title": 0 },
      live: true,
    })
    expect(resolveActiveEpisodeNumber(live.episodes, { live: true, polish: live.polish })).toBe(2)
    expect(resolveEpisodeRowStatus(live.episodes[0], 2)).toBe("completed")
    expect(resolveEpisodeRowStatus(live.episodes[1], 2)).toBe("running")
    expect(shotDurationLabel(live.episodes[0].shots[0])).toBe("6s")
    expect(episodeShotCountLabel(live.episodes[0].shots.length)).toBe("1 镜")

    const fromRecipe = buildStoryboardStreamModel({
      shownTexts: {},
      streamItems: {
        "storyboard|storyboard|shots|0": { title: "巷口", shotNumber: 1 },
        "storyboard|storyboard|shots|1": { title: "窗边", shotNumber: 2 },
        "storyboard|storyboard|shots|2": { title: "对峙", shotNumber: 3 },
        "storyboard|storyboard|shots|3": { title: "结尾", shotNumber: 4 },
      },
      recipe: {
        episodes: [
          { num: 1, title: "第 1 集 · 雨夜", targetShots: 2 },
          { num: 2, title: "第 2 集 · 白日", targetShots: 2 },
        ],
        scenes: [{ shots: [
          { title: "巷口", shotNumber: 1, episodeNumber: 1 },
          { title: "窗边", shotNumber: 2, episodeNumber: 1 },
          { title: "对峙", shotNumber: 3, episodeNumber: 2 },
          { title: "结尾", shotNumber: 4, episodeNumber: 2 },
        ] }],
      },
      live: false,
    })
    expect(fromRecipe.episodes.map((episode) => [episode.number, episode.shots.length])).toEqual([[1, 2], [2, 2]])
    expect(fromRecipe.episodes[0].shots.map((shot) => shot.title)).toEqual(["巷口", "窗边"])
    expect(fromRecipe.episodes[1].shots.map((shot) => shot.title)).toEqual(["对峙", "结尾"])

    const settled = buildStoryboardStreamModel({
      shownTexts: {},
      streamItems: {
        "storyboard|storyboard|shots|0|1": { title: "巷口", episodeNumber: 1 },
        "storyboard|storyboard|shots|0|2": { title: "窗边", episodeNumber: 2 },
      },
      live: false,
    })
    expect(resolveActiveEpisodeNumber(settled.episodes, { live: false, polish: null })).toBeUndefined()
    expect(settled.episodes.every((episode) => resolveEpisodeRowStatus(episode, undefined) === "completed")).toBe(true)
  })

  it("marks polish groups completed/running/pending from the current shot", () => {
    const groups = groupPolishShotNumbers([
      { number: 1, shots: [{ shotNumber: 1 }, { shotNumber: 2 }] },
      { number: 2, shots: [{ shotNumber: 3 }, { shotNumber: 4 }] },
      { number: 3, shots: [{ shotNumber: 5 }] },
    ])
    expect(resolvePolishGroupStatus(groups[0], 3, [3, 4])).toBe("completed")
    expect(resolvePolishGroupStatus(groups[1], 3, [3, 4])).toBe("running")
    expect(resolvePolishGroupStatus(groups[2], 3, [3, 4])).toBe("pending")
  })
})

