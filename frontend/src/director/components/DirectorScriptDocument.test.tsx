import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import DirectorScriptDocument from "./DirectorScriptDocument"

describe("DirectorScriptDocument manuscript highlighting", () => {
  it("reuses the standard script parser so episode and shot headings are styled", () => {
    const html = renderToStaticMarkup(
      <DirectorScriptDocument
        script={{
          title: "雨夜",
          summary: "巷口对峙",
          fullStory: `# 第1集：伏笔
### 镜头1｜暗巷
- 动作：他跑进巷口
- 台词：别动。
【天台】他停步。
`,
        }}
        mode="document"
        onEdit={() => undefined}
        onDoneEdit={() => undefined}
        onChange={() => undefined}
        onNext={() => undefined}
      />,
    )
    expect(html).toContain("director-document-story")
    expect(html).toContain("is-episode")
    expect(html).toContain("第1集：伏笔")
    expect(html).toContain("director-script-shot-card")
    expect(html).toContain("镜头1｜暗巷")
    expect(html).toContain("is-dialogue")
    expect(html).toContain("别动。")
    expect(html).toContain("is-scene")
    expect(html).toContain("【天台】")
    expect(html).not.toContain("director-episode-row")
  })
})
