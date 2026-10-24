import { describe, expect, it } from "vitest"
import {
  CANVAS_COVER_CROP_MAX_ZOOM,
  CANVAS_COVER_FILE_MAX_BYTES,
  CANVAS_COVER_MAX_DATA_URL,
  canvasCoverAspectRatio,
  canvasCoverCaptureTime,
  canvasCoverCropFocus,
  canvasCoverCropRect,
  canvasCoverFrameSize,
  canvasCoverFromFile,
  canvasCoverSummary,
  clampCanvasCoverTime,
  moveCanvasCoverCropFocus,
  normalizeCanvasCover,
  readCanvasCover,
} from "./canvas-cover"

const JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2w=="

describe("canvas cover", () => {
  it("accepts only compact raster data URLs", () => {
    expect(normalizeCanvasCover(`  ${JPEG}  `)).toBe(JPEG)
    expect(normalizeCanvasCover("data:image/webp;base64,UklGRg==")).toBe("data:image/webp;base64,UklGRg==")
    expect(normalizeCanvasCover("data:image/png;base64,iVBORw0KGgo=")).toBe("data:image/png;base64,iVBORw0KGgo=")
    expect(normalizeCanvasCover("data:image/svg+xml;base64,PHN2Zz4=")).toBeNull()
    expect(normalizeCanvasCover("https://cdn.example/cover.jpg")).toBeNull()
    expect(normalizeCanvasCover("data:image/jpeg;base64,not base64!")).toBeNull()
    expect(normalizeCanvasCover(`${JPEG.slice(0, -2)}${"A".repeat(CANVAS_COVER_MAX_DATA_URL)}`)).toBeNull()
    expect(normalizeCanvasCover(null)).toBeNull()
  })

  it("uses a cover only when its source matches the current video", () => {
    const data = { url: "/api/media/a.mp4", cover: JPEG, coverSource: "/api/media/a.mp4", coverTime: 0.5 }
    expect(readCanvasCover(data)).toBe(JPEG)
    expect(readCanvasCover({ ...data, url: "/api/media/b.mp4" })).toBeNull()
    expect(readCanvasCover({ ...data, coverSource: undefined })).toBeNull()
    expect(readCanvasCover({ ...data, url: "" })).toBeNull()
    expect(readCanvasCover({ ...data, cover: "javascript:alert(1)" })).toBeNull()
  })

  it("seeks a representative frame and clamps short or long videos", () => {
    expect(canvasCoverCaptureTime(0)).toBe(0)
    expect(canvasCoverCaptureTime(Number.NaN)).toBe(0)
    expect(canvasCoverCaptureTime(0.2)).toBe(0)
    expect(canvasCoverCaptureTime(2)).toBeCloseTo(0.2)
    expect(canvasCoverCaptureTime(10)).toBeCloseTo(1)
    expect(canvasCoverCaptureTime(30)).toBeCloseTo(1.5)
    expect(canvasCoverCaptureTime(1.5)).toBeCloseTo(0.15)
  })

  it("fits landscape and portrait frames within the cover edge", () => {
    expect(canvasCoverFrameSize(1920, 1080)).toEqual({ width: 320, height: 180 })
    expect(canvasCoverFrameSize(1080, 1920)).toEqual({ width: 180, height: 320 })
    expect(canvasCoverFrameSize(160, 90)).toEqual({ width: 160, height: 90 })
    expect(canvasCoverFrameSize(320, 320, 240)).toEqual({ width: 240, height: 240 })
    expect(canvasCoverFrameSize(0, 90)).toBeNull()
    expect(canvasCoverFrameSize(Number.NaN, 90)).toBeNull()
  })

  it("describes the captured cover for the inspector", () => {
    expect(canvasCoverSummary(JPEG, 0.5)).toContain("取帧 0.5 秒")
    expect(canvasCoverSummary(JPEG, 0.5)).toContain("KB")
    expect(canvasCoverSummary(JPEG, 0)).not.toContain("取帧")
    expect(canvasCoverSummary(JPEG, null)).not.toContain("取帧")
  })

  it("clamps a requested frame time into the playable range", () => {
    expect(clampCanvasCoverTime(12, 30)).toBe(12)
    expect(clampCanvasCoverTime(30, 10)).toBeCloseTo(9.95)
    expect(clampCanvasCoverTime(0, 10)).toBe(0)
    expect(clampCanvasCoverTime(-1, 10)).toBe(0)
    expect(clampCanvasCoverTime(Number.NaN, 10)).toBe(0)
    expect(clampCanvasCoverTime(5, 0)).toBe(0)
  })

  it("resolves crop aspect presets and the original image ratio", () => {
    expect(canvasCoverAspectRatio("16:9", 100, 100)).toBeCloseTo(16 / 9)
    expect(canvasCoverAspectRatio("9:16", 100, 100)).toBeCloseTo(9 / 16)
    expect(canvasCoverAspectRatio("1:1", 1600, 900)).toBe(1)
    expect(canvasCoverAspectRatio("original", 1600, 900)).toBeCloseTo(16 / 9)
    expect(canvasCoverAspectRatio("original", 900, 1600)).toBeCloseTo(9 / 16)
    expect(canvasCoverAspectRatio("original", 0, 0)).toBeCloseTo(16 / 9)
  })

  it("fits, zooms and clamps the cover crop rect", () => {
    const center = { x: 0.5, y: 0.5 }
    expect(canvasCoverCropRect(1600, 900, 16 / 9, 1, center)).toEqual({ x: 0, y: 0, width: 1600, height: 900 })
    const portrait = canvasCoverCropRect(900, 1600, 16 / 9, 1, center)
    expect(portrait).not.toBeNull()
    expect(portrait!.width).toBe(900)
    expect(portrait!.height).toBeCloseTo(506.25)
    expect(portrait!.y).toBeCloseTo((1600 - 506.25) / 2)
    const zoomed = canvasCoverCropRect(1600, 900, 16 / 9, 2, center)
    expect(zoomed!.width).toBe(800)
    expect(zoomed!.height).toBe(450)
    expect(zoomed!.x).toBe(400)
    expect(zoomed!.y).toBe(225)
    const topLeft = canvasCoverCropRect(1600, 900, 16 / 9, 2, { x: 0, y: 0 })
    expect(topLeft!.x).toBe(0)
    expect(topLeft!.y).toBe(0)
    const bottomRight = canvasCoverCropRect(1600, 900, 16 / 9, 2, { x: 1, y: 1 })
    expect(bottomRight!.x).toBe(800)
    expect(bottomRight!.y).toBe(450)
    const maxZoom = canvasCoverCropRect(1600, 900, 16 / 9, 99, center)
    expect(maxZoom!.width).toBeCloseTo(1600 / CANVAS_COVER_CROP_MAX_ZOOM)
    expect(canvasCoverCropRect(0, 900, 1, 1, center)).toBeNull()
    expect(canvasCoverCropRect(1600, 900, 0, 1, center)).toBeNull()
  })

  it("converts the crop center to focus and pans it by screen delta", () => {
    const crop = { x: 300, y: 137.5, width: 400, height: 225 }
    expect(canvasCoverCropFocus(crop, 1000, 500)).toEqual({ x: 0.5, y: 0.5 })
    const moved = moveCanvasCoverCropFocus(1000, 500, crop, 320, 180, 80, -40)
    expect(moved!.x).toBeCloseTo(0.4)
    expect(moved!.y).toBeCloseTo(0.6)
    expect(moveCanvasCoverCropFocus(1000, 500, crop, 320, 180, 9999, 9999)).toEqual({ x: 0, y: 0 })
    expect(moveCanvasCoverCropFocus(1000, 500, crop, 320, 180, -9999, -9999)).toEqual({ x: 1, y: 1 })
    expect(moveCanvasCoverCropFocus(0, 500, crop, 320, 180, 0, 0)).toBeNull()
    expect(moveCanvasCoverCropFocus(1000, 500, crop, 0, 180, 0, 0)).toBeNull()
  })

  it("rejects cover uploads that are not usable images", async () => {
    await expect(canvasCoverFromFile({ type: "text/plain", size: 10 } as File)).resolves.toBeNull()
    await expect(canvasCoverFromFile({ type: "image/png", size: 0 } as File)).resolves.toBeNull()
    await expect(canvasCoverFromFile({
      type: "image/png",
      size: CANVAS_COVER_FILE_MAX_BYTES + 1,
    } as File)).resolves.toBeNull()
  })
})
