import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { ReferenceSource } from "../reference-assets"
import VideoRoundHeader from "./VideoRoundHeader"

function render(references: ReferenceSource[]) {
  return renderToStaticMarkup(
    <VideoRoundHeader
      roundId="round-1"
      sequence={1}
      prompt="分离人声与伴奏"
      expanded
      onExpand={() => {}}
      onLanguageChange={() => {}}
      references={references}
      modelName="人声/伴奏分离"
      status="succeeded"
      statusLabel="已完成"
      stage="生成完成"
      parameters={[]}
      formatParameter={() => ""}
      elapsed={null}
      results={[]}
      onSelect={() => {}}
      detailsOpen={false}
      runtimeExpanded={false}
      onDetailsChange={() => {}}
      onReferencePreview={() => {}}
    />,
  )
}

describe("video round header reference thumbnails", () => {
  it("renders a neutral icon for generic audio-or-video references instead of a broken image", () => {
    const html = render([{ index: 1, url: "/api/jobs/job-1/references/1", kind: "media", label: "待分离音频或视频" }])
    expect(html).not.toContain("<img")
    expect(html).toContain("lucide-audio-lines")
  })

  it("keeps image references as thumbnails", () => {
    const html = render([{ index: 1, url: "/api/jobs/job-1/references/1", kind: "image" }])
    expect(html).toContain('src="/api/jobs/job-1/references/1"')
  })
})
