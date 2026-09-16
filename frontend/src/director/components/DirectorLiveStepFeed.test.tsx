import { renderToStaticMarkup } from "react-dom/server"
import { FileText } from "lucide-react"
import { describe, expect, it } from "vitest"
import { DirectorLiveBlock, DirectorLiveStepRow, DirectorPathChips, DirectorReviewBlock } from "./DirectorLiveStepFeed"

describe("DirectorLiveStepFeed", () => {
  it("keeps the director completed-step DOM contract", () => {
    const html = renderToStaticMarkup(
      <DirectorLiveStepRow id="script" label="剧本" status="completed" preview="剧本已完成" onOpen={() => undefined} />,
    )
    expect(html).toContain("director-step-row is-completed")
    expect(html).toContain("director-step-row-icon-chevron")
    expect(html).toContain("director-step-row-chip")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })

  it("keeps the director expanded live-card DOM contract", () => {
    const html = renderToStaticMarkup(
      <DirectorLiveBlock label="剧本" message="正在生成" icon={FileText}><p>直播正文</p></DirectorLiveBlock>,
    )
    expect(html).toContain("director-block is-running is-live")
    expect(html).toContain("director-step-spinner")
    expect(html).toContain("director-block-body")
    expect(html).toContain("直播正文")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })

  it("keeps the checkpoint review-card DOM contract", () => {
    const html = renderToStaticMarkup(
      <DirectorReviewBlock label="剧本" message="剧本已生成，请确认或提出调整" icon={FileText} onAccept={() => undefined} onRevise={() => undefined}>
        <p>剧本正文</p>
      </DirectorReviewBlock>,
    )
    expect(html).toContain("director-block")
    expect(html).not.toContain("director-step-spinner")
    expect(html).toContain("director-completion-card")
    expect(html).toContain("采纳，继续下一步")
    expect(html).toContain("不满意，调整")
    expect(html).toContain("剧本正文")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("aria-expanded")
  })

  it("echoes recorded choices under the completed row without turning it into an accordion", () => {
    const html = renderToStaticMarkup(
      <DirectorLiveStepRow
        id="assets"
        label="角色 / 场景 / 道具"
        status="completed"
        preview="已有 3 项角色 / 场景 / 道具"
        choices={[
          { question: "气质？", answer: "更冷" },
          { question: "本轮调整诉求", answer: "道具再少一点" },
        ]}
        onOpen={() => undefined}
      />,
    )
    expect(html).toContain("director-step-row-choices")
    expect(html).toContain("气质？ → 更冷")
    expect(html).toContain("本轮调整诉求 → 道具再少一点")
    expect(html).toContain("director-step-choice-chip")
    expect(html).toContain("director-step-row-head")
    expect(html).not.toContain("aria-expanded")
    expect(html).not.toContain("director-episode-row")
    expect(html).not.toContain("director-episode-row-fold")
  })

  it("shows a muted skipped fallback only when the card was skipped", () => {
    const html = renderToStaticMarkup(
      <DirectorLiveStepRow id="script" label="剧本" status="completed" preview="剧本已完成" choiceFallback="已跳过，沿用默认" onOpen={() => undefined} />,
    )
    expect(html).toContain("已跳过，沿用默认")
    expect(html).toContain("is-muted")
    expect(html).not.toContain("aria-expanded")
    expect(renderToStaticMarkup(
      <DirectorLiveStepRow id="script" label="剧本" status="completed" preview="剧本已完成" onOpen={() => undefined} />,
    )).not.toContain("director-step-row-choices")
  })

  it("renders grouped path chips as compact answer pills, not an accordion", () => {
    const html = renderToStaticMarkup(
      <DirectorPathChips
        groups={[
          { id: "clarify", label: "创意确认", items: [{ question: "这部剧分多少集？", answer: "12集" }] },
          { id: "assets", label: "角色 / 场景 / 道具", items: [{ question: "气质？", answer: "更冷" }] },
        ]}
      />,
    )
    expect(html).toContain("director-direction-chips is-path")
    expect(html).toContain("创作路径")
    expect(html).toContain("director-direction-stage-label")
    expect(html).toContain("创意确认")
    expect(html).toContain("角色 / 场景 / 道具")
    expect(html).toContain("12集")
    expect(html).toContain("更冷")
    expect(html).toContain("这部剧分多少集？ → 12集")
    expect(html).not.toContain("这部剧分多少集？ → 12集</span>")
    expect(html).not.toContain("aria-expanded")
    expect(html).not.toContain("director-episode-row")
    expect(renderToStaticMarkup(<DirectorPathChips groups={[]} />)).toBe("")
  })
})
