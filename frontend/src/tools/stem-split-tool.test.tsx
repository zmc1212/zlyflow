import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { STEM_SPLIT_MODE, stemSplitSourceError } from "../generation/stem-split"
import StemSplitTool from "./StemSplitTool"

describe("stem split tool default creation form", () => {
  it("renders the tool hero and keeps the submit button disabled without a source file", () => {
    const html = renderToStaticMarkup(<MemoryRouter>
      <StemSplitTool csrfToken="" />
    </MemoryRouter>)
    expect(html).toContain("人声/伴奏分离")
    expect(html).toContain("开始分离")
    expect(html).toContain("上传音频或视频")
  })

  it("validates source media and keeps the registered mode stable", () => {
    expect(STEM_SPLIT_MODE).toBe("stem-split")
    expect(stemSplitSourceError({ type: "audio/mpeg", name: "song.mp3", size: 1024 })).toBe("")
    expect(stemSplitSourceError({ type: "video/mp4", name: "clip.mp4", size: 1024 })).toBe("")
    expect(stemSplitSourceError({ type: "image/png", name: "cover.png", size: 1024 })).not.toBe("")
    expect(stemSplitSourceError({ type: "audio/mpeg", name: "song.mp3", size: 0 })).not.toBe("")
    expect(stemSplitSourceError({ type: "audio/mpeg", name: "song.mp3", size: 400 * 1024 * 1024 })).not.toBe("")
  })
})
