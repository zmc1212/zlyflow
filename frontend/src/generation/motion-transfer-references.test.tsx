import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import MotionTransferReferences from "./MotionTransferReferences"

describe("MotionTransferReferences", () => {
  const props = {
    labels: ["角色形象图", "动作参考视频"], motion: null,
    onPickPortrait: () => {}, onPickMotion: () => {}, onRemovePortrait: () => {}, onRemoveMotion: () => {},
    onPreviewPortrait: () => {}, onPreviewMotion: () => {}, onMotionDuration: () => {},
  }

  it("renders independent, labelled image and video file inputs", () => {
    const html = renderToStaticMarkup(<MotionTransferReferences {...props} />)
    expect(html).toContain('aria-label="上传角色形象图"')
    expect(html).toContain('aria-label="上传动作参考视频"')
    expect(html).toContain('accept="image/*"')
    expect(html).toContain('accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi"')
    expect(html).not.toContain("<Picture")
  })

  it("uses video, not an img, for a selected motion reference", () => {
    const motion = { id: "video", file: new File(["video"], "dance.mp4", { type: "video/mp4" }), preview: "blob:video", duration: 5.17 }
    const html = renderToStaticMarkup(<MotionTransferReferences {...props} motion={motion} />)
    expect(html).toContain('<video src="blob:video"')
    expect(html).not.toContain('<img src="blob:video"')
    expect(html).toContain('aria-label="移除动作参考视频"')
    expect(html).toContain("5.2 秒")
  })
})
