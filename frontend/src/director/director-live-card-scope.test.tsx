import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { renderToStaticMarkup } from "react-dom/server"
import { FileText } from "lucide-react"
import { describe, expect, it } from "vitest"
import DirectorAssetSummaryCard from "./components/DirectorAssetSummaryCard"
import { DirectorLiveBlock, DirectorLiveStepRow, DirectorPathChips, DirectorReviewBlock } from "./components/DirectorLiveStepFeed"
import DirectorTaskRows from "./components/DirectorTaskRows"

const here = dirname(fileURLToPath(import.meta.url))

function readSource(relativePath: string): string {
  return readFileSync(resolve(here, relativePath), "utf8")
}

function sliceBetween(source: string, startMarker: string, endMarker: string): string {
  const start = source.indexOf(startMarker)
  expect(start, `missing ${startMarker}`).toBeGreaterThanOrEqual(0)
  const end = source.indexOf(endMarker, start + startMarker.length)
  expect(end, `missing ${endMarker} after ${startMarker}`).toBeGreaterThan(start)
  return source.slice(start, end)
}

function expectNoEpisodeAccordion(markup: string) {
  expect(markup).not.toContain("director-episode-row")
  expect(markup).not.toContain("director-episode-row-fold")
  expect(markup).not.toContain("director-episode-row-head")
  expect(markup).not.toContain("Capsules")
}

describe("live-card accordion stays on storyboard episode rows only", () => {
  it("does not put Task Rows episode accordion on the outer live block or completed step rows", () => {
    const live = renderToStaticMarkup(
      <DirectorLiveBlock label="剧本" message="正在生成" icon={FileText}><p>直播正文</p></DirectorLiveBlock>,
    )
    expect(live).toContain("director-block is-running is-live")
    expect(live).toContain("director-step-spinner")
    expect(live).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(live)

    const step = renderToStaticMarkup(
      <DirectorLiveStepRow id="script" label="剧本" status="completed" preview="剧本已完成" onOpen={() => undefined} />,
    )
    expect(step).toContain("director-step-row is-completed")
    expect(step).toContain("director-step-row-icon-chevron")
    expect(step).not.toContain("director-episode-row-chevron")
    expectNoEpisodeAccordion(step)

    const echoed = renderToStaticMarkup(
      <DirectorLiveStepRow
        id="assets"
        label="角色 / 场景 / 道具"
        status="completed"
        preview="已有 3 项"
        choices={[{ question: "气质？", answer: "更冷" }]}
        choiceFallback="已跳过，沿用默认"
        onOpen={() => undefined}
      />,
    )
    expect(echoed).toContain("气质？")
    expect(echoed).toContain("更冷")
    expect(echoed).toContain("气质？ → 更冷")
    expect(echoed).toContain("director-step-choice-q")
    expect(echoed).toContain("director-step-row-choices")
    expect(echoed).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(echoed)

    const path = renderToStaticMarkup(
      <DirectorPathChips
        groups={[{ id: "clarify", label: "创意确认", items: [{ question: "这部剧分多少集？", answer: "12集" }] }]}
      />,
    )
    expect(path).toContain("director-direction-chips is-path")
    expect(path).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(path)

    const review = renderToStaticMarkup(
      <DirectorReviewBlock label="剧本" message="剧本已生成" icon={FileText} onAccept={() => undefined} onRevise={() => undefined}>
        <p>剧本正文</p>
      </DirectorReviewBlock>,
    )
    expect(review).toContain("director-completion-card")
    expect(review).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(review)
  })

  it("keeps asset summary cards as visual cards, not accordion rows", () => {
    const html = renderToStaticMarkup(
      <DirectorAssetSummaryCard
        asset={{
          kind: "character",
          name: "沈砚",
          role: "男主",
          visualPrompt: "古风人物肖像",
        }}
      />,
    )
    expect(html).toContain("director-asset-card director-asset-card--character")
    expect(html).toContain("一致性生图 Prompt")
    expect(html).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(html)
  })

  it("keeps the left task rail always open, without nested episode substeps", () => {
    const html = renderToStaticMarkup(
      <DirectorTaskRows
        rows={[
          { id: "script", label: "剧本", status: "completed", message: "剧本已完成" },
          { id: "assets", label: "角色 / 场景 / 道具", status: "running", message: "正在建立资产" },
        ]}
        running
        elapsedSec={12}
        variant="rail"
        onOpen={() => undefined}
      />,
    )
    expect(html).toContain("director-task-rows is-rail is-open")
    expect(html).toContain("生成任务")
    expect(html).toContain("查看这一步的产出")
    expect(html).not.toContain("is-collapsed")
    expect(html).not.toContain("aria-expanded")
    expect(html).not.toContain("director-task-rows-head")
    expectNoEpisodeAccordion(html)
  })

  it("keeps script, assets, episode outlines and the live-block shell free of episode-row markup in source", () => {
    const liveFeed = readSource("./components/DirectorLiveStepFeed.tsx")
    expect(liveFeed).toContain("director-block is-running is-live")
    expect(liveFeed).toContain("director-step-row-head")
    expectNoEpisodeAccordion(liveFeed)

    const assets = readSource("./components/DirectorAssetSummaryCard.tsx")
    expect(assets).toContain("director-asset-card director-asset-card--character")
    expectNoEpisodeAccordion(assets)

    const taskRows = readSource("./components/DirectorTaskRows.tsx")
    expect(taskRows).toContain('variant === "rail"')
    expect(taskRows).toContain("director-task-rows is-rail is-open")
    expect(taskRows).not.toContain("director-episode-row")
    expect(taskRows).not.toContain("Capsules")

    const scriptPanel = readSource("./components/DirectorScriptStreamPanel.tsx")
    const scriptBody = sliceBetween(scriptPanel, 'if (agent === "script") {', 'if (agent === "art_style")')
    expect(scriptBody).toContain("director-stream-article")
    expect(scriptBody).toContain("director-stream-text")
    expect(scriptBody).toContain("StoryParagraphs")
    expectNoEpisodeAccordion(scriptBody)
    expect(scriptPanel).toContain("ScriptLiveBlocks")
    expect(scriptPanel).toContain("不再使用折叠卡片")
    expect(scriptPanel).toContain("不可折叠")
    expect(scriptPanel).toContain('variant="rail"')
    expect(scriptPanel).not.toContain("director-episode-row")
    expect(scriptPanel).not.toContain("Capsules")

    const studio = readSource("../director2/panes/Director2AiStudioPane.tsx")
    const scriptStage = sliceBetween(studio, 'if (stage === "script") {', 'if (stage === "assets" && !itemEntries.length)')
    expect(scriptStage).toContain("Director2ScriptLiveBody")
    expect(scriptStage).toContain("resolveDirector2ScriptLiveSource")
    expect(scriptStage).toContain("recipe")
    expect(scriptStage).not.toContain("director-block-text")
    // Pane wires Director2ScriptLiveBody only; episode capsules live inside that body, not the stage shell.
    expect(scriptStage).not.toContain("director-episode-row")
    expect(scriptStage).not.toContain("DirectorEpisodeCapsule")

    const scriptLiveBody = readSource("../director2/Director2ScriptLiveBody.tsx")
    expect(scriptLiveBody).toContain("DirectorEpisodeCapsule")
    expect(scriptLiveBody).toContain("groupScriptLiveView")
    expect(scriptLiveBody).toContain("bodyClassName=\"is-script\"")
    expect(scriptLiveBody).toContain("idPrefix=\"director-script-episode-body\"")

    const assetStage = sliceBetween(studio, 'if (stage === "assets") {', 'if (stage === "episodes") {')
    expect(assetStage).toContain("DirectorAssetSummaryCard")
    expect(assetStage).toContain("director-asset-card-grid")
    expectNoEpisodeAccordion(assetStage)

    const episodeStage = sliceBetween(studio, 'if (stage === "episodes") {', 'if (stage === "storyboard") {')
    expect(episodeStage).toContain("is-episode-outline")
    expect(episodeStage).toContain("card.summary")
    expect(episodeStage).toContain("约 {card.targetShots} 镜")
    expect(episodeStage).not.toContain("DirectorStoryboardLiveBody")
    expect(episodeStage).not.toContain("aria-expanded")
    expectNoEpisodeAccordion(episodeStage)

    const storyboardStage = sliceBetween(studio, 'if (stage === "storyboard") {', "const items = itemEntries.map")
    expect(storyboardStage).toContain("DirectorStoryboardLiveBody")

    const fallback = sliceBetween(studio, "if (!text.length && !items.length) return null", "function stagePreview")
    expect(fallback).toContain("director-block-text")
    expectNoEpisodeAccordion(fallback)

    expect(studio).toContain('variant="rail"')
    expect(studio).toContain("<DirectorLiveBlock")
    expect(studio).toContain("<DirectorLiveStepRow")
    expect(studio).toContain("<DirectorPathChips")
    expect(studio).not.toContain("director-episode-row")
    expect(studio).not.toContain("Capsules")

    const storyboard = readSource("./components/DirectorStoryboardLiveBody.tsx")
    expect(storyboard).toContain("DirectorEpisodeCapsule")
    expect(storyboard).toContain("director-phase-chip")
    expect(storyboard).not.toContain("director-episode-detail-row")

    const capsule = readSource("./components/DirectorEpisodeCapsule.tsx")
    expect(capsule).toContain("director-episode-row")
    expect(capsule).toContain("director-episode-row-fold")
    expect(capsule).toContain("director-episode-row-head")
  })

  it("does not reuse the episode accordion animation on outline cards, asset cards or the live-block shell", () => {
    const css = readSource("./guided-flow.css")
    const episodeFold = sliceBetween(css, ".director-episode-row-fold {", ".director-episode-row {")
    expect(episodeFold).toContain("grid-template-rows: 0fr")
    expect(css).toContain(".director-episode-row-fold.is-open { grid-template-rows: 1fr; }")
    expect(css).toContain(".director-block-card.is-episode-outline p {")
    expect(css).toContain(".director-episode-row-body.is-script")
    expect(css).not.toMatch(/\.director-block[^{]*\{[^}]*grid-template-rows:\s*0fr/)
    expect(css).not.toMatch(/\.director-asset-card[^{]*\{[^}]*grid-template-rows:\s*0fr/)
    expect(css).not.toMatch(/\.is-episode-outline[^{]*\{[^}]*grid-template-rows:\s*0fr/)
    expect(css).not.toMatch(/\.director-task-rows\.is-rail[^{]*\{[^}]*grid-template-rows:\s*0fr/)
    expect(css).not.toMatch(/\.director-direction-chips\.is-path[^{]*\{[^}]*grid-template-rows:\s*0fr/)
    expect(css).toContain(".director-direction-chips.is-path")
    expect(css).toContain(".director-direction-stage-label")
  })
})
