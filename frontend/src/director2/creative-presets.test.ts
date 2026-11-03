import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import catalog from "./creative-presets.json"
import { changeStoryAudience, changeVisibleStoryTopics, creativeStyleText, emptyStoryTopics, filterStylePresets, removeStoryTopic, selectedStoryTopics, STYLE_PRESETS, topicOptions } from "./creative-presets"
import { createHomeDrafts, homeCreationTextLimit, homeProjectExtra, homeProjectMessage, homeProjectRequest } from "./home-creation"

describe("public creative preset catalog", () => {
  it("ships every original preset with a unique identity and an actual local WebP cover", () => {
    expect(STYLE_PRESETS).toHaveLength(101)
    expect(new Set(STYLE_PRESETS.map(item => item.id)).size).toBe(101)
    expect(["real_person", "two_d", "three_d"].map(category => filterStylePresets(category, "").length)).toEqual([52, 25, 23])
    for (const preset of STYLE_PRESETS.filter(item => item.id !== "none")) {
      const image = readFileSync(new URL(`../../public${preset.cover}`, import.meta.url))
      expect(image.subarray(0, 4).toString()).toBe("RIFF")
      expect(image.subarray(8, 12).toString()).toBe("WEBP")
    }
  })

  it("uses the source's audience-dependent lists rather than a single mixed vocabulary", () => {
    expect(Object.values(catalog.topics).map(groups => Object.values(groups).reduce((count, items) => count + items.length, 0))).toEqual([103, 110, 123])
    const topics = emptyStoryTopics()
    expect(topicOptions(topics, "background")).toContain("刑侦")
    expect(topicOptions({ ...topics, audience: "男频" }, "background")).toContain("玄幻")
    expect(topicOptions({ ...topics, audience: "女频" }, "background")).toContain("豪门")
    expect(topicOptions(topics, "audience")).toEqual(["男频", "女频", "泛人群"])
  })

  it("filters covers by both category and name, including empty results", () => {
    expect(filterStylePresets("all", "古偶柔光").map(item => item.label)).toEqual(["古偶柔光滤镜风"])
    expect(filterStylePresets("two_d", "古偶柔光")).toEqual([])
    expect(filterStylePresets("all", "不存在的风格")).toEqual([])
    expect(creativeStyleText({ presetId: "none", custom: "旧输入" })).toBe("")
    expect(creativeStyleText({ presetId: "custom", custom: "  黑白胶片  " })).toBe("黑白胶片")
  })

  it("keeps selections hidden by search or an audience change and removes only the chosen tag", () => {
    const topics = { ...emptyStoryTopics(), audience: "女频" as const, background: ["悬疑", "豪门"] }
    const changed = changeVisibleStoryTopics(topics, "background", ["豪门", "都市"], ["都市"])
    expect(changed.background).toEqual(["悬疑", "都市"])
    expect(removeStoryTopic(changed, "background", "悬疑").background).toEqual(["都市"])
    expect(removeStoryTopic(changed, "audience", "女频").background).toEqual(["悬疑", "都市"])
    expect(topics.background).toEqual(["悬疑", "豪门"])
  })

  it("switches audience regardless of display order and permits clicking the selected audience off", () => {
    const topics = { ...emptyStoryTopics(), audience: "泛人群" as const, background: ["悬疑"] }
    expect(changeStoryAudience(topics, ["男频", "泛人群"]).audience).toBe("男频")
    expect(changeStoryAudience(topics, []).audience).toBe("")
    expect(changeStoryAudience(topics, []).background).toEqual(["悬疑"])
    expect(changeStoryAudience(topics, ["未知受众"]).audience).toBe("")
  })

  it("sends selected styles and grouped topics to the assistant and saves their identities", () => {
    const topics = { ...emptyStoryTopics(), audience: "男频" as const, background: ["都市"], trope: ["系统", "重生"] }
    const preset = STYLE_PRESETS.find(item => item.label === "古偶柔光滤镜风")!
    const request = homeProjectRequest("create", createHomeDrafts().create, { style: preset.label, styleId: preset.id, topics, aspectRatio: "9:16", episodeCount: 3 })
    expect(homeProjectMessage(request)).toContain("请根据以下选题创作短剧")
    expect(homeProjectMessage(request)).toContain(`视觉风格：${preset.label}`)
    expect(homeProjectMessage(request)).toContain("受众偏好：男频；故事背景：都市；热门梗：系统、重生")
    expect(homeProjectExtra(request)).toMatchObject({ creative_style: preset.label, creative_style_preset_id: preset.id, story_topics: topics })
    expect(selectedStoryTopics(topics)).toHaveLength(4)
  })

  it("omits an unselected style and reserves the full 50,000-character envelope without changing originals", () => {
    const draft = { ...createHomeDrafts().novel, text: "", requirements: "要".repeat(1000) }
    const options = { style: "画".repeat(1000), styleId: "custom", topics: { ...emptyStoryTopics(), character: ["学生", "医生", "侦探"] }, aspectRatio: "9:16", episodeCount: 1 }
    draft.text = "文".repeat(homeCreationTextLimit("novel", draft, options))
    const request = homeProjectRequest("novel", draft, options)
    expect(Array.from(homeProjectMessage(request)).length).toBeLessThanOrEqual(50_000)
    expect(request.text).toBe(draft.text)
    expect(homeProjectMessage({ ...request, style: "" })).not.toContain("视觉风格：")
    expect(homeProjectExtra(homeProjectRequest("import", { ...draft, text: "\n 原文 \n" }, options)).creative_style).toBe(options.style)
  })
})
