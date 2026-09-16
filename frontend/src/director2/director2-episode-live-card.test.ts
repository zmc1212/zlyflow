import { describe, expect, it } from "vitest"
import { normalizeEpisodeLiveCard } from "./director2-episode-live-card"

describe("director2 episode live card mapping", () => {
  it("maps streamed episode titles without leaking body copy", () => {
    expect(normalizeEpisodeLiveCard({
      title: "第 1 集 · 开场（单集）",
      summary: "甲在咖啡馆落座，乙始终没有开口。",
      text: "Beat 1\n甲走进咖啡馆。",
      description: "这段不该出现在分集卡。",
      beats: [{ title: "Beat 1", action: "推门" }],
    })).toEqual({
      title: "第 1 集 · 开场（单集）",
      summary: "甲在咖啡馆落座，乙始终没有开口。",
    })
  })

  it("maps recipe outlines to 第 N 集 titles and targetShots", () => {
    expect(normalizeEpisodeLiveCard({
      num: 2,
      title: "终局",
      summary: "乙揭开身份。",
      targetShots: 12,
      text: "乙揭开身份。\nBeat 3\n对白：你是谁？",
      scenes: [{ title: "天台" }],
    })).toEqual({
      title: "第 2 集 · 终局",
      summary: "乙揭开身份。",
      targetShots: 12,
    })
  })

  it("reads saved episode summary and shot count from data_json, never script_text", () => {
    expect(normalizeEpisodeLiveCard({
      episode_num: 1,
      title: "开场",
      script_text: "Beat 1\n甲走进咖啡馆。\n对白：来了。",
      shots_count: 8,
      data_json: JSON.stringify({
        summary: "落座之后，旧账被重新提起。",
        targetShots: 8,
        beats: [{ title: "Beat 1", action: "推门", dialogue: "来了。" }],
      }),
    })).toEqual({
      title: "第 1 集 · 开场",
      summary: "落座之后，旧账被重新提起。",
      targetShots: 8,
    })
  })

  it("hides missing summary and shot counts instead of inventing them", () => {
    expect(normalizeEpisodeLiveCard({
      number: 3,
      name: "余波",
      script_text: "整集正文",
      shots_count: 0,
      target_shots: 0,
    })).toEqual({
      title: "第 3 集 · 余波",
    })
  })

  it("never treats description, text, script_text or beats as the outline summary", () => {
    const card = normalizeEpisodeLiveCard({
      num: 1,
      title: "开场（单集）",
      description: "这段不该出现在分集卡。",
      text: "Beat 1\n甲走进咖啡馆。\n对白：来了。",
      script_text: "Beat 2\n乙没有开口。",
      beats: [{ title: "Beat 1", action: "推门", dialogue: "来了。" }],
    })
    expect(card).toEqual({ title: "第 1 集 · 开场（单集）" })
    expect(JSON.stringify(card)).not.toMatch(/Beat|对白|这段不该/)
  })

  it("reads snake_case target_shots and object data_json without using nested scenes", () => {
    expect(normalizeEpisodeLiveCard({
      episode_num: 5,
      title: "夜访",
      target_shots: 9,
      data_json: {
        summary: "雨夜里旧账被重新提起。",
        scenes: [{ title: "天台", text: "Beat 4\n对白：你是谁？" }],
      },
    })).toEqual({
      title: "第 5 集 · 夜访",
      summary: "雨夜里旧账被重新提起。",
      targetShots: 9,
    })
  })

  it("falls back to shots_count when outline targetShots is absent", () => {
    expect(normalizeEpisodeLiveCard({
      episode_num: 4,
      title: "尾声",
      shots_count: 6,
    })?.targetShots).toBe(6)
  })

  it("rejects objects that cannot form an episode heading", () => {
    expect(normalizeEpisodeLiveCard({
      summary: "没有标题",
      text: "正文",
      script_text: "剧本",
    })).toBeNull()
    expect(normalizeEpisodeLiveCard({ script_text: "整集正文" }, { fallbackIndex: 0 })).toBeNull()
  })

  it("stays an outline payload and never grows episode-accordion fields", () => {
    const card = normalizeEpisodeLiveCard({
      num: 1,
      title: "雨夜追踪",
      summary: "巷口对峙后，追踪转入旧宅。",
      targetShots: 8,
      text: "Beat 1\n对白：站住。",
      beats: [{ title: "开场巷口" }],
    })
    expect(card).toEqual({
      title: "第 1 集 · 雨夜追踪",
      summary: "巷口对峙后，追踪转入旧宅。",
      targetShots: 8,
    })
    expect(Object.keys(card || {})).toEqual(["title", "summary", "targetShots"])
  })

  it("uses fallback index only when a bare title needs 第 N 集", () => {
    expect(normalizeEpisodeLiveCard({ title: "开场", summary: "落座" }, { fallbackIndex: 0 })).toEqual({
      title: "第 1 集 · 开场",
      summary: "落座",
    })
  })
})

