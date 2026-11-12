import { describe, expect, it } from "vitest"
import { filterGroupedOptions, filterSearchOptions, matchesSearchQuery, scoreSearchMatch, searchFilterOption } from "./search-match"

// 与截图同款的模型目录，全部“价格未知”。
const ids = [
  "antdigital/Ling-3.1-flash",
  "cmaas-glm-5.3",
  "cmaas-qwen3.8-flash",
  "deepseek-r1-distill-llama-70b",
  "deepseek-r1-distill-qwen-1.5b",
  "deepseek-v4-flash-0731",
  "deepseek-v4-pro",
  "deepseek-v4-pro-0813",
]
const options = ids.map(id => ({ value: id, label: `${id} · 价格未知` }))

describe("fuzzy dropdown search", () => {
  it("lists everything in original order while the keyword is empty", () => {
    expect(filterSearchOptions(options, "")).toEqual(options)
    expect(filterSearchOptions(options, "   ")).toEqual(options)
  })

  it("ignores separators so glm53 finds glm-5.3", () => {
    expect(filterSearchOptions(options, "glm53").map(row => row.value)).toEqual(["cmaas-glm-5.3"])
    expect(filterSearchOptions(options, "GLM 5.3").map(row => row.value)).toEqual(["cmaas-glm-5.3"])
    expect(filterSearchOptions(options, "qwen3.8").map(row => row.value)).toEqual(["cmaas-qwen3.8-flash"])
    expect(filterSearchOptions(options, "v4pro").map(row => row.value)).toEqual(["deepseek-v4-pro", "deepseek-v4-pro-0813"])
  })

  it("ranks boundary matches above accidental digit matches", () => {
    const filtered = filterSearchOptions(options, "3.1")
    expect(filtered[0].value).toBe("antdigital/Ling-3.1-flash")
    expect(filtered.map(row => row.value)).not.toContain("cmaas-glm-5.3")
  })

  it("matches multiple keywords in order or out of order", () => {
    expect(filterSearchOptions(options, "deepseek v4 flash").map(row => row.value)).toEqual(["deepseek-v4-flash-0731"])
    expect(filterSearchOptions(options, "deepseek pro")[0].value).toBe("deepseek-v4-pro")
  })

  it("accepts abbreviations through subsequence matching only from three characters", () => {
    expect(filterSearchOptions(options, "dsv4").map(row => row.value)).toEqual([
      "deepseek-v4-flash-0731",
      "deepseek-v4-pro",
      "deepseek-v4-pro-0813",
    ])
    expect(scoreSearchMatch("zz", options[0])).toBe(0)
  })

  it("returns an empty list instead of falling back to the whole list", () => {
    expect(filterSearchOptions(options, "not-a-model")).toEqual([])
    expect(matchesSearchQuery("deepseek", { value: "deepseek-v4-pro", label: "deepseek-v4-pro · 价格未知" })).toBe(true)
    expect(matchesSearchQuery("glm", { value: "deepseek-v4-pro", label: "deepseek-v4-pro · 价格未知" })).toBe(false)
  })
})

describe("searchFilterOption", () => {
  it("keeps every option while the input is empty", () => {
    expect(searchFilterOption("", options[0])).toBe(true)
    expect(searchFilterOption("  ", options[1])).toBe(true)
  })

  it("filters exactly like the shared matcher", () => {
    expect(searchFilterOption("glm53", options[1])).toBe(true)
    expect(searchFilterOption("glm53", options[0])).toBe(false)
    expect(searchFilterOption("冰糖", { value: "bingtang", label: "冰糖 · 中文女声" })).toBe(true)
    expect(searchFilterOption("bingtang", { value: "bingtang", label: "冰糖 · 中文女声" })).toBe(true)
  })

  it("rejects group headers so a group name cannot whitelist its children", () => {
    expect(searchFilterOption("视频", { label: "视频生成", options: [{ value: "minimax" }] })).toBe(false)
    expect(searchFilterOption("", { label: "视频生成", options: [] })).toBe(false)
    expect(searchFilterOption("视频", undefined)).toBe(false)
  })

  it("falls back to the value when the label is not plain text", () => {
    expect(searchFilterOption("qwen-max", { value: "qwen-max", label: {} })).toBe(true)
    expect(searchFilterOption("qwen max", { value: "qwen-max", label: null })).toBe(true)
    expect(searchFilterOption("glm", { value: "qwen-max", label: {} })).toBe(false)
  })
})

describe("filterGroupedOptions", () => {
  type Opt = { value: string; label: string }
  type Entry = Opt | { label: string; options: Opt[] }

  const groups: Entry[] = [
    { label: "图片生成", options: [
      { value: "gpt-image-2.5", label: "GPT Image 2.5" },
      { value: "nano-banana", label: "Nano Banana" },
    ] },
    { label: "视频生成", options: [
      { value: "kling-2.5", label: "Kling 2.5" },
      { value: "minimax-h3", label: "MiniMax H3" },
    ] },
    { value: "custom", label: "无分组选项" },
  ]

  const childrenOf = (entry: unknown) => {
    const options = (entry as { options?: Opt[] }).options
    return Array.isArray(options) ? options.map(row => row.value) : []
  }

  it("keeps every entry while the keyword is empty", () => {
    expect(filterGroupedOptions(groups, "")).toBe(groups)
    expect(filterGroupedOptions(groups, "  ")).toBe(groups)
  })

  it("filters children and drops groups without a match", () => {
    const filtered = filterGroupedOptions(groups, "kling25")
    expect(filtered).toHaveLength(1)
    expect((filtered[0] as { label: string }).label).toBe("视频生成")
    expect(childrenOf(filtered[0])).toEqual(["kling-2.5"])
  })

  it("keeps surviving groups in their original order", () => {
    const filtered = filterGroupedOptions(groups, "2.5")
    expect(filtered.map(entry => (entry as { label: string }).label)).toEqual(["图片生成", "视频生成"])
    expect(filtered.map(entry => childrenOf(entry))).toEqual([["gpt-image-2.5"], ["kling-2.5"]])
  })

  it("sorts matched children by relevance inside a group", () => {
    const filtered = filterGroupedOptions([
      { label: "图片生成", options: [
        { value: "b-gpt-image", label: "x GPT Image" },
        { value: "gpt-image-2.5", label: "GPT Image 2.5" },
      ] },
    ] as Entry[], "gpt image")
    expect(childrenOf(filtered[0])).toEqual(["gpt-image-2.5", "b-gpt-image"])
  })

  it("keeps ungrouped options and removes them when they miss", () => {
    expect(filterGroupedOptions(groups, "无分组").map(entry => (entry as Opt).value)).toEqual(["custom"])
    expect(filterGroupedOptions(groups, "zzz9")).toEqual([])
  })

  it("never lets a group label whitelist its children", () => {
    expect(filterGroupedOptions([{ label: "视频生成", options: [{ value: "minimax-h3", label: "MiniMax H3" }] }], "视频生成")).toEqual([])
  })
})
