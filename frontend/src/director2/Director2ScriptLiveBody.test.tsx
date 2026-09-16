import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import Director2ScriptLiveBody, { ScriptLiveBlocks } from "./Director2ScriptLiveBody"

describe("Director2ScriptLiveBody", () => {
  it("renders a manuscript with episode heading, shot card and dialogue line", () => {
    const html = renderToStaticMarkup(
      <Director2ScriptLiveBody
        title="寒门硕士"
        summary="穿越逆袭"
        fullStory={`# 《寒门硕士》
# 第1集：醒来
**剧情：** 穿越第一天。
### 镜头1｜破屋
- 人物：沈砚
- 动作：猛然睁眼
- 台词：“这里……是什么地方？”
`}
      />,
    )
    expect(html).toContain("director-stream-article")
    expect(html).toContain("director-stream-title")
    expect(html).toContain("寒门硕士")
    expect(html).toContain("穿越逆袭")
    expect(html).toContain("is-episode")
    expect(html).toContain("第1集：醒来")
    expect(html).toContain("director-script-shot-card")
    expect(html).toContain("镜头1｜破屋")
    expect(html).toContain("director-script-shot-field is-dialogue")
    expect(html).toContain("这里……是什么地方？")
    expect(html).not.toContain("director-block-text")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
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
})
