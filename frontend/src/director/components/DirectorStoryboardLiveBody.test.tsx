import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import DirectorStoryboardLiveBody from "./DirectorStoryboardLiveBody"

describe("DirectorStoryboardLiveBody", () => {
  it("renders episode, scene and shot hierarchy", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody shownTexts={{}} streamItems={{
      "episodes|episodes|0": { title: "第 1 集 · 初见" },
      "storyboard|storyboard|scenes|0|1": { title: "咖啡馆", episodeNumber: 1 },
      "storyboard|storyboard|shots|0|1": { title: "推近", description: "镜头推进", episodeNumber: 1 },
    }} settled />)
    expect(html).toContain("第 1 集 · 初见")
    expect(html).toContain("【咖啡馆】")
    expect(html).toContain("推近")
    expect(html).toContain("director-shot-stream-row")
    expect(html).toContain("director-episode-row is-completed")
    expect(html).toContain("1 镜")
    expect(html).toContain("已完成")
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("director-episode-row-fold")
    expect(html).toContain("director-shot-stream-fold")
    expect(html).toContain("镜头推进")
  })

  it("shows a waiting panel while live storyboard has not emitted shots yet", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody shownTexts={{}} streamItems={{}} message="正在读剧本并构思 (1/3)" live />)
    expect(html).toContain("阅读剧本并构思")
    expect(html).toContain("director-live-skeleton")
    expect(html).toContain("开始输出后会显示字数与镜头")
  })

  it("shows a waiting empty state when live and there is no phase copy yet", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody shownTexts={{}} streamItems={{}} live />)
    expect(html).toContain("等待模型开始输出")
    expect(html).toContain("远端模型正在阅读剧本，开始输出后会逐镜出现")
  })

  it("keeps streamed shots visible while the writing status message is still live", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody shownTexts={{}} streamItems={{
      "storyboard|storyboard|shots|0|1": { title: "推近", description: "镜头推进", episodeNumber: 1 },
    }} message="正在写分镜 (1/3) - 已收 12 字" live />)
    expect(html).toContain("推近")
    expect(html).not.toContain("等待模型开始输出")
  })

  it("uses episode capsules during polish and keeps shot chips inside each episode", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody
      shownTexts={{}}
      streamItems={{
        "episodes|episodes|0": { title: "第 1 集 · 夜巡" },
        "episodes|episodes|1": { title: "第 2 集 · 回忆" },
        "episodes|episodes|2": { title: "第 3 集 · 结尾" },
        "storyboard|storyboard|shots|0|1": { title: "夜巡", shotNumber: 1, episodeNumber: 1, description: "巷口" },
        "storyboard|storyboard|shots|1|1": { title: "发现", shotNumber: 2, episodeNumber: 1 },
        "storyboard|storyboard|shots|0|2": { title: "回忆", shotNumber: 3, episodeNumber: 2 },
        "storyboard|storyboard|shots|0|3": { title: "结尾", shotNumber: 4, episodeNumber: 3 },
      }}
      message="第 2 集 · 正在按秒分配对白与动作 (1/3) · 第 3-3 镜 · 正在第 3 镜 - 已收 120 字"
      live
    />)
    expect(html).toContain("全剧 3 集")
    expect(html).toContain("共 4 镜")
    expect(html).toContain("当前第 2 集")
    expect(html).toContain("第 1/3 批")
    expect(html).toContain("第 1 集 · 夜巡")
    expect(html).toContain("第 2 集 · 回忆")
    expect(html).toContain("第 3 集 · 结尾")
    expect(html).toContain("director-episode-row is-completed")
    expect(html).toContain("director-episode-row is-running is-open")
    expect(html).toContain("director-episode-row is-pending")
    expect(html).toContain("正在打磨第 3 镜")
    expect(html).toContain("director-phase-chip is-done")
    expect(html).toContain("director-phase-chip is-active")
    expect(html).toContain("第 1 镜（全剧第 3 镜）")
    expect(html).not.toContain("director-episode-detail-row")
    expect(html).not.toContain("已完成 2 镜")
    expect((html.match(/director-phase-chip/g) || []).length).toBe(4)
  })

  it("keeps a single-episode polish card as one capsule with the original shot chips inside", () => {
    const shots = Object.fromEntries(Array.from({ length: 16 }, (_, index) => [
      `storyboard|storyboard|shots|${index}|1`,
      { title: `镜 ${index + 1}`, shotNumber: index + 1, episodeNumber: 1 },
    ]))
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody
      shownTexts={{}}
      streamItems={{ "episodes|episodes|0": { title: "第 1 集 · 开场" }, ...shots }}
      message="正在按秒分配对白与动作 (8/16) · 第 15-16 镜 · 正在第 16 镜"
      live
    />)
    expect(html).toContain("director-episode-row is-running is-open")
    expect(html).toContain("第 1 集 · 开场")
    expect(html).toContain("16 镜")
    expect(html).toContain("正在打磨第 16 镜")
    expect(html).toContain("director-phase-chip is-active")
    expect((html.match(/director-phase-chip/g) || []).length).toBe(16)
    expect((html.match(/director-episode-row /g) || []).length).toBe(1)
    expect(html).not.toContain("已完成 15 镜")
  })

  it("only puts the current episode's shot chips inside each capsule", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody
      shownTexts={{}}
      streamItems={{
        "storyboard|storyboard|shots|0": { title: "巷口", shotNumber: 1 },
        "storyboard|storyboard|shots|1": { title: "窗边", shotNumber: 2 },
        "storyboard|storyboard|shots|2": { title: "对峙", shotNumber: 3 },
        "storyboard|storyboard|shots|3": { title: "结尾", shotNumber: 4 },
      }}
      recipe={{
        episodes: [
          { num: 1, title: "第 1 集 · 雨夜", targetShots: 2 },
          { num: 2, title: "第 2 集 · 白日", targetShots: 2 },
        ],
        scenes: [
          { shots: [
            { title: "巷口", shotNumber: 1, episodeNumber: 1 },
            { title: "窗边", shotNumber: 2, episodeNumber: 1 },
            { title: "对峙", shotNumber: 3, episodeNumber: 2 },
            { title: "结尾", shotNumber: 4, episodeNumber: 2 },
          ] },
        ],
      }}
      message="第 2 集 · 正在按秒分配对白与动作 (1/1) · 第 3-4 镜 · 正在第 4 镜"
      live
    />)
    expect(html).toContain("第 1 集 · 雨夜")
    expect(html).toContain("第 2 集 · 白日")
    expect(html).toContain("director-episode-row is-completed")
    expect(html).toContain("director-episode-row is-running is-open")
    expect(html).toContain("2 镜")
    expect(html).toContain("第 1 镜（全剧第 3 镜）")
    expect(html).toContain("第 2 镜（全剧第 4 镜）")
    expect(html).not.toContain("第 4 镜（全剧第 4 镜）")
    expect((html.match(/director-phase-chip/g) || []).length).toBe(4)
  })

  it("expands the live episode capsule and collapses finished ones", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody
      shownTexts={{ "storyboard|storyboard|title|0|2": "窗边" }}
      targetTexts={{ "storyboard|storyboard|title|0|2": "窗边" }}
      streamItems={{
        "episodes|episodes|0": { title: "第 1 集 · 雨夜" },
        "episodes|episodes|1": { title: "第 2 集 · 白日" },
        "storyboard|storyboard|shots|0|1": { title: "巷口", description: "雨巷", dialogue: "站住", episodeNumber: 1, durationSec: 6 },
        "storyboard|storyboard|shots|0|2": { title: "窗边", description: "晨光", episodeNumber: 2 },
      }}
      activeIndex={{ "storyboard|title": 0 }}
      live
    />)
    expect(html).toContain("director-episode-row is-completed")
    expect(html).toContain("director-episode-row is-running is-open")
    expect(html).toContain("第 1 集 · 雨夜")
    expect(html).toContain("第 2 集 · 白日")
    expect(html).toContain("6s")
    expect(html).toContain("巷口")
    expect(html).toContain("窗边")
    expect(html).toContain("director-shot-stream-row is-active")
    expect(html).toContain("晨光")
    expect(html).toContain("director-shot-stream-row is-done is-expandable")
    expect(html).toContain("雨巷")
    expect(html).toContain("「站住」")
    expect(html).not.toContain("director-phase-chip")
  })

  it("collapses every episode capsule on the settled review card", () => {
    const html = renderToStaticMarkup(<DirectorStoryboardLiveBody
      shownTexts={{}}
      streamItems={{
        "storyboard|storyboard|shots|0|1": { title: "巷口", episodeNumber: 1 },
        "storyboard|storyboard|shots|0|2": { title: "窗边", episodeNumber: 2 },
      }}
      settled
    />)
    expect(html).toContain("director-episode-row is-completed")
    expect(html).not.toContain("director-episode-row is-running")
    expect(html).not.toContain("director-episode-row-fold is-open")
    expect(html).toContain("已完成")
  })
})

