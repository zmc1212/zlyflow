import { describe, expect, it } from "vitest"
import { asMediaPreviewTarget } from "./media-preview"

describe("asMediaPreviewTarget", () => {
  it("returns null for empty src", () => {
    expect(asMediaPreviewTarget({ src: "  " })).toBeNull()
    expect(asMediaPreviewTarget({ src: null })).toBeNull()
    expect(asMediaPreviewTarget({})).toBeNull()
  })

  it("defaults to in-app image preview", () => {
    expect(asMediaPreviewTarget({ src: " https://cdn.example/a.jpg " })).toEqual({
      kind: "image",
      src: "https://cdn.example/a.jpg",
      title: "图片预览",
      description: undefined,
    })
  })

  it("keeps video kind and custom title", () => {
    expect(asMediaPreviewTarget({
      src: "https://cdn.example/a.mp4",
      kind: "video",
      title: "生成结果",
      description: "  MiniMax H3  ",
    })).toEqual({
      kind: "video",
      src: "https://cdn.example/a.mp4",
      title: "生成结果",
      description: "MiniMax H3",
    })
  })
})
