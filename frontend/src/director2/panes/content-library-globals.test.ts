import { describe, expect, it } from "vitest"
import { hasVisualStyleContent, positioningEntries } from "./content-library-globals"

describe("positioningEntries", () => {
  it("keeps labelled fields in fixed order", () => {
    expect(
      positioningEntries({
        main_storyline: "女主逆袭",
        genre: "现代都市情感短剧",
        worldview: "当代都市",
        shots_per_episode: 6,
      }),
    ).toEqual([
      { key: "genre", label: "作品类型", text: "现代都市情感短剧" },
      { key: "worldview", label: "世界观设定", text: "当代都市" },
      { key: "shots_per_episode", label: "镜头规划", text: "6" },
      { key: "main_storyline", label: "主线剧情", text: "女主逆袭" },
    ])
  })

  it("renders an unlabelled positioning paragraph without a label", () => {
    const entries = positioningEntries({
      items: ["现代都市情感短剧。讲述苏念在民政局门口偶遇厉景深，两人一拍即合闪婚。"],
    })
    expect(entries).toHaveLength(1)
    expect(entries[0].label).toBeNull()
    expect(entries[0].text).toContain("闪婚")
  })

  it("puts labelled fields before paragraphs", () => {
    const entries = positioningEntries({ genre: "都市", items: ["一整段定位描述"] })
    expect(entries.map((entry) => entry.label)).toEqual(["作品类型", null])
  })

  it("skips blank values and missing sections", () => {
    expect(positioningEntries(null)).toEqual([])
    expect(positioningEntries(undefined)).toEqual([])
    expect(positioningEntries({ genre: "  ", items: ["", "   "] })).toEqual([])
  })
})

describe("hasVisualStyleContent", () => {
  it("detects either description or prohibited words", () => {
    expect(hasVisualStyleContent({ description: "暖色调实拍质感" })).toBe(true)
    expect(hasVisualStyleContent({ prohibited: "禁止出现文字水印" })).toBe(true)
    expect(hasVisualStyleContent({ description: "", prohibited: "  " })).toBe(false)
    expect(hasVisualStyleContent(undefined)).toBe(false)
  })
})
