import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import DirectorAssetSummaryCard from "./DirectorAssetSummaryCard"

describe("DirectorAssetSummaryCard", () => {
  it("renders character metadata and optional prompt", () => {
    const html = renderToStaticMarkup(
      <DirectorAssetSummaryCard
        asset={{
          kind: "character",
          name: "沈砚",
          role: "男主",
          age: "17岁",
          gender: "男",
          fixedProps: ["旧书箱"],
          description: "清瘦的古代少年。",
          visualPrompt: "古风人物肖像",
        }}
      />,
    )
    expect(html).toContain("director-asset-card--character")
    expect(html).toContain("沈砚")
    expect(html).toContain("旧书箱")
    expect(html).toContain("一致性生图 Prompt")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })

  it("omits absent optional fields instead of inventing content", () => {
    const html = renderToStaticMarkup(<DirectorAssetSummaryCard asset={{ kind: "scene", name: "陆家宅院" }} />)
    expect(html).toContain("director-asset-card--scene")
    expect(html).toContain("陆家宅院")
    expect(html).not.toContain("出现分镜")
    expect(html).not.toContain("陈设元素")
  })

  it("renders scene prompt when supplied", () => {
    const html = renderToStaticMarkup(
      <DirectorAssetSummaryCard
        asset={{
          kind: "scene",
          name: "旧商场",
          sceneType: "固定场景",
          elements: ["橱窗"],
          visualPrompt: "empty mall corridor at night",
        }}
      />,
    )
    expect(html).toContain("director-asset-card--scene")
    expect(html).toContain("陈设元素")
    expect(html).toContain("一致性生图 Prompt")
    expect(html).toContain("empty mall corridor at night")
  })

  it("renders prop relation and count only when supplied", () => {
    const html = renderToStaticMarkup(
      <DirectorAssetSummaryCard asset={{ kind: "prop", name: "台灯", propKind: "场景陈设道具", relatedCharacter: "书房", count: 2 }} />,
    )
    expect(html).toContain("director-asset-card--prop")
    expect(html).toContain("场景陈设道具")
    expect(html).toContain("书房")
    expect(html).toContain("2 次")
  })

  it("hides prop frequency when count is absent", () => {
    const html = renderToStaticMarkup(
      <DirectorAssetSummaryCard asset={{ kind: "prop", name: "手电筒", propKind: "人物固定道具", relatedCharacter: "阿强" }} />,
    )
    expect(html).toContain("阿强")
    expect(html).not.toContain("出现频次")
  })
})
