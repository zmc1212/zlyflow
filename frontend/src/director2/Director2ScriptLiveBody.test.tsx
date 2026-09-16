import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import Director2ScriptLiveBody, { ScriptLiveBlocks } from "./Director2ScriptLiveBody"

const STANDARD_STORY = `# 《寒门硕士》
## 视频定位
- 类型：古装穿越
## 一、主要人物固定设定
### 沈砚——男主
清瘦少年。
# 第1集：醒来
**剧情：** 穿越第一天。
### 镜头1｜破屋
- 人物：沈砚
- 动作：猛然睁眼
- 台词：“这里……是什么地方？”
# 第2集：出门
**剧情：** 推门见天光。
### 镜头1｜院门
- 动作：推开木门
`

describe("Director2ScriptLiveBody", () => {
  it("renders review capsules collapsed with preamble and episode titles visible", () => {
    const html = renderToStaticMarkup(
      <Director2ScriptLiveBody
        title="寒门硕士"
        summary="穿越逆袭"
        fullStory={STANDARD_STORY}
      />,
    )
    expect(html).toContain("director-stream-article")
    expect(html).toContain("director-stream-title")
    expect(html).toContain("寒门硕士")
    expect(html).toContain("穿越逆袭")
    expect(html).toContain("视频定位")
    expect(html).toContain("主要人物固定设定")
    expect(html).toContain("director-episode-row is-completed")
    expect(html).toContain("第1集：醒来")
    expect(html).toContain("第2集：出门")
    expect(html).toContain("1 镜")
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('aria-expanded="true"')
    expect(html).toContain("director-episode-row-fold")
    expect(html).toContain("director-script-shot-card")
    expect(html).toContain("镜头1｜破屋")
    expect(html).toContain("director-script-shot-field is-dialogue")
    expect(html).toContain("这里……是什么地方？")
    expect(html).toContain("is-script")
    expect(html).not.toContain("director-block-text")
  })

  it("expands the last episode while live streaming", () => {
    const html = renderToStaticMarkup(
      <Director2ScriptLiveBody
        title="寒门硕士"
        summary="穿越逆袭"
        fullStory={STANDARD_STORY}
        live
      />,
    )
    expect(html).toContain("director-episode-row is-running is-open")
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("第2集：出门")
    expect(html).toContain("stream-caret")
  })

  it("keeps glued wall-text shots on separate cards without an episode accordion", () => {
    const html = renderToStaticMarkup(
      <ScriptLiveBlocks text="Beat 1：保安A拦住门口。对白：保安A：站住！Beat 2：主角出示证件。" />,
    )
    expect(html).toContain("镜头1｜场景")
    expect(html).toContain("保安A拦住门口。")
    expect(html).toContain("保安A：站住！")
    expect(html).toContain("镜头2｜场景")
    expect((html.match(/director-script-shot-card/g) || []).length).toBe(2)
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })

  it("falls back to a linear manuscript when there is no episode heading", () => {
    const html = renderToStaticMarkup(
      <Director2ScriptLiveBody
        title="门岗"
        fullStory={"### 镜头1｜门口\n- 动作：拦住\n- 台词：站住！"}
      />,
    )
    expect(html).toContain("director-script-shot-card")
    expect(html).toContain("镜头1｜门口")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })
})
