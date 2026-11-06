import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ShowcaseThumb, type ShowcaseItem } from "./InspirationWorkspace"

const base: ShowcaseItem = {
  id: "showcase-1",
  slug: "demo",
  category: "影视",
  title: "示例标题",
  blurb: "",
  origin: "local",
  mode: "minimax-h3-r2v",
  prompt: "提示词",
  display_prompt: "",
  negative_prompt: "",
  image_size: "",
  options: {},
  references: [],
  tags: [],
  cover_url: "",
  media_url: "",
  media_type: "video",
  duration_seconds: 15,
  source_job_id: "job-1",
  sort_order: 1,
}

describe("ShowcaseThumb", () => {
  it("prefers a stored cover over the media itself", () => {
    const html = renderToStaticMarkup(<ShowcaseThumb item={{ ...base, cover_url: "/cdn/cover.png", media_url: "/cdn/clip.mp4" }} />)
    expect(html).toContain('src="/cdn/cover.png"')
    expect(html).not.toContain("clip.mp4")
  })

  it("uses the media url directly for image examples", () => {
    const html = renderToStaticMarkup(<ShowcaseThumb item={{ ...base, media_type: "image", media_url: "/cdn/poster.jpg" }} />)
    expect(html).toContain('src="/cdn/poster.jpg"')
    expect(html).not.toContain("#t=0.5")
  })

  it("lets the video seek to 0.5s instead of running a frame-extraction pipeline", () => {
    const html = renderToStaticMarkup(<ShowcaseThumb item={{ ...base, media_url: "/cdn/clip.mp4" }} />)
    expect(html).toContain("<video")
    expect(html).toContain('src="/cdn/clip.mp4#t=0.5"')
    expect(html).toContain('preload="metadata"')
  })

  it("falls back to a placeholder when the media is gone", () => {
    const html = renderToStaticMarkup(<ShowcaseThumb item={base} />)
    expect(html).toContain("inspiration-thumb-empty")
  })
})
