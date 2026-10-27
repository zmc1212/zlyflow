import { describe, expect, it } from "vitest"
import { CLOUD_THUMBNAIL_WIDTH, cloudThumbnailSrc } from "./media-thumbnails"

describe("cloudThumbnailSrc", () => {
  it("builds a webp image thumbnail for cloud images", () => {
    expect(cloudThumbnailSrc("image", "https://cdn.example.com/a/b.png")).toBe(
      `https://cdn.example.com/a/b.png?imageView2/2/w/${CLOUD_THUMBNAIL_WIDTH}/format/webp`,
    )
  })

  it("builds a first-frame poster for cloud videos", () => {
    expect(cloudThumbnailSrc("video", "https://cdn.example.com/a/b.mp4")).toBe(
      `https://cdn.example.com/a/b.mp4?vframe/jpg/offset/1/w/${CLOUD_THUMBNAIL_WIDTH}`,
    )
  })

  it("appends processing parameters after an existing query string", () => {
    expect(cloudThumbnailSrc("image", "https://cdn.example.com/a.png?v=2")).toBe(
      `https://cdn.example.com/a.png?v=2&imageView2/2/w/${CLOUD_THUMBNAIL_WIDTH}/format/webp`,
    )
  })

  it("returns null for missing or non-cloud urls", () => {
    expect(cloudThumbnailSrc("image", "")).toBeNull()
    expect(cloudThumbnailSrc("image", null)).toBeNull()
    expect(cloudThumbnailSrc("video", "/api/jobs/1/outputs/0/download")).toBeNull()
  })
})
