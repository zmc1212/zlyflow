import { describe, expect, it } from "vitest"
import type { Director2Episode } from "./api"
import { episodeOverviewCounts, episodeScriptSummary, episodeStageStates, episodeStatusLabel, nextEpisodeNumber, visibleEpisodes } from "./episode-overview"

const ep = (num: number, status = "draft", extra: Partial<Director2Episode> = {}): Director2Episode => ({
  id: `ep-${num}`, project_id: "project", episode_num: num, title: `第 ${num} 集`, status,
  script_text: "", shots_count: 0, created_at: "2026-10-25 00:00:00", updated_at: "2026-10-25 00:00:00", ...extra,
})

describe("剧集管理的数据展示", () => {
  it("在分集被删除或序号稀疏后仍从最大集数递增", () => {
    expect(nextEpisodeNumber([])).toBe(1)
    expect(nextEpisodeNumber([ep(1), ep(6), ep(3)])).toBe(7)
  })
  it("脚本生成中和未知状态不冒充脚本已就绪", () => {
    const counts = episodeOverviewCounts([ep(1, "draft"), ep(2, "scripting"), ep(3, "script_ready", { shots_count: 8 }), ep(4, "sketching", { shots_count: 4 }), ep(5, "sketched", { shots_count: 6 }), ep(6, "future_status")])
    expect(counts).toEqual({ all: 6, draft: 1, ready: 1, working: 2, complete: 1, scriptReady: 3, shots: 18 })
    expect(episodeStatusLabel("future_status")).toBe("future_status")
  })
  it("搜索与状态同时生效，兼容集号、剧本和大小写并忽略外部空格", () => {
    const list = [ep(2, "script_ready", { title: "雨夜来客", script_text: "旧站台 Echo" }), ep(12, "draft", { title: "来客" })]
    expect(visibleEpisodes(list, "  ECHO  ", "ready", "number_asc").map(e => e.id)).toEqual(["ep-2"])
    expect(visibleEpisodes(list, "第2集", "all", "number_asc").map(e => e.id)).toEqual(["ep-2"])
    expect(visibleEpisodes(list, "02", "all", "number_asc").map(e => e.id)).toEqual(["ep-2"])
    expect(visibleEpisodes(list, "雨夜", "draft", "number_asc")).toEqual([])
  })
  it("对集号做数字排序，更新时间相同或无效时稳定排序且不修改原数组", () => {
    const list = [ep(10), ep(2), ep(1, "draft", { updated_at: "2026-10-26 00:00:00" })]
    expect(visibleEpisodes(list, "", "all", "number_asc").map(e => e.episode_num)).toEqual([1, 2, 10])
    expect(visibleEpisodes(list, "", "all", "number_desc").map(e => e.episode_num)).toEqual([10, 2, 1])
    expect(visibleEpisodes(list, "", "all", "updated_desc").map(e => e.episode_num)).toEqual([1, 2, 10])
    expect(list.map(e => e.episode_num)).toEqual([10, 2, 1])
  })
  it("草稿与未知状态不虚构完成节点，制作中只标出实际阶段", () => {
    expect(episodeStageStates("draft")).toEqual(["wait", "wait", "wait", "wait"])
    expect(episodeStageStates("scripting")).toEqual(["finish", "process", "wait", "wait"])
    expect(episodeStageStates("script_ready")).toEqual(["finish", "finish", "wait", "wait"])
    expect(episodeStageStates("sketching")).toEqual(["finish", "finish", "process", "wait"])
    expect(episodeStageStates("sketched")).toEqual(["finish", "finish", "finish", "finish"])
    expect(episodeStageStates("unknown")).toEqual(["wait", "wait", "wait", "wait"])
  })
  it("摘要清理排版标记但保留正常短横线，不为短文本凭空追加省略号", () => {
    expect(episodeScriptSummary("# 雨夜\n- 林澈坐上 D-7 号车。\n\n下一幕")).toBe("雨夜 林澈坐上 D-7 号车。 下一幕")
    expect(episodeScriptSummary(null)).toBe("")
  })
})
