import { describe, expect, it } from "vitest"
import { canvasPreviewLines, canvasSavedTime, layoutCanvasPreview, recentCanvasProject } from "./canvas-home"
import type { CanvasPreview, CanvasProject } from "./canvas-model"

const project = (id: string, patch: Partial<CanvasProject> = {}): CanvasProject => ({
  id, title: id, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z", ...patch,
})

describe("canvas home recent project", () => {
  it("uses real draft saves, excludes trash, and is independent of favorite ordering", () => {
    const projects = [
      project("favorite", { is_favorite: true, updated_at: "2026-10-27T00:00:00Z" }),
      project("saved", { draft_updated_at: "2026-10-28T08:00:00Z" }),
      project("trashed", { updated_at: "2026-10-28T09:00:00Z", deleted_at: "2026-10-28T09:01:00Z" }),
    ]
    expect(recentCanvasProject(projects)?.id).toBe("saved")
    expect(projects[0].id).toBe("favorite")
    expect(recentCanvasProject([])).toBeNull()
    expect(recentCanvasProject([projects[2]])).toBeNull()
  })

  it("falls back from invalid legacy draft timestamps without losing a usable project", () => {
    expect(recentCanvasProject([
      project("legacy", { draft_updated_at: "invalid", updated_at: "2026-10-28T00:00:00Z" }),
      project("older"),
    ])?.id).toBe("legacy")
  })

  it("formats elapsed time without negative ages or invalid date labels", () => {
    const now = Date.parse("2026-10-28T08:00:00Z")
    expect(canvasSavedTime("2026-10-28T07:40:00Z", now)).toBe("20 分钟前")
    expect(canvasSavedTime("2026-10-28T06:00:00Z", now)).toBe("2 小时前")
    expect(canvasSavedTime("2026-10-27T08:00:00Z", now)).toBe("昨天")
    expect(canvasSavedTime("2026-10-29T08:00:00Z", now)).toBe("刚刚")
    expect(canvasSavedTime("bad", now)).toBe("尚未保存")
    expect(canvasSavedTime(undefined, now)).toBe("尚未保存")
  })
})

describe("real canvas preview framing", () => {
  const preview: CanvasPreview = {
    x: -400, y: 120, width: 900, height: 500, nodeCount: 2,
    items: [
      { type: "text", x: -400, y: 120, width: 260, height: 150, text: "开场" },
      { type: "image", x: 100, y: 260, width: 400, height: 300, url: "/actual.jpg" },
    ],
    links: [[0, 1]],
  }

  it("fits offset real nodes into a thumbnail, preserving their spatial relationship and links", () => {
    const layout = layoutCanvasPreview(preview, 360, 246)
    expect(layout.items[0].x).toBeLessThan(layout.items[1].x)
    expect(layout.items[0].y).toBeLessThan(layout.items[1].y)
    expect(layout.items[1].url).toBe("/actual.jpg")
    expect(layout.links).toEqual([[0, 1]])
    expect(layout.cropped).toBe(false)
    for (const item of layout.items) {
      expect(item.x).toBeGreaterThanOrEqual(0)
      expect(item.y).toBeGreaterThanOrEqual(0)
      expect(item.x + item.width).toBeLessThanOrEqual(360)
      expect(item.y + item.height).toBeLessThanOrEqual(246)
    }
    expect(preview.items[0].x).toBe(-400)
  })

  it("focuses a real connected group in a dense canvas, without returning dangling connections", () => {
    const dense: CanvasPreview = {
      ...preview, nodeCount: 80,
      items: Array.from({ length: 30 }, (_, index) => ({
        type: index === 12 ? "image" : "text", x: index * 300, y: index % 3 * 150,
        width: 260, height: 120, ...(index === 12 ? { url: "/real-anchor.jpg" } : {}),
      })),
      links: Array.from({ length: 29 }, (_, index) => [index, index + 1]),
    }
    const layout = layoutCanvasPreview(dense, 360, 246)
    expect(layout.cropped).toBe(true)
    expect(layout.items).toHaveLength(7)
    expect(layout.items.some((item) => item.sourceIndex === 12)).toBe(true)
    expect(layout.items.every((item) => dense.items[item.sourceIndex])).toBe(true)
    for (const [source, target] of layout.links) {
      expect(layout.items[source]).toBeDefined()
      expect(layout.items[target]).toBeDefined()
    }
    expect(layoutCanvasPreview({ ...dense, items: [], links: [] }, 360, 246).items).toEqual([])
  })

  it("wraps Chinese and emoji as complete glyphs and limits overflowing preview text", () => {
    expect(canvasPreviewLines("雨夜🌧️街道的光影与人物", 42, 10, 2)).toHaveLength(2)
    expect(canvasPreviewLines("雨夜街道的光影与人物", 42, 10, 1)[0]).toMatch(/…$/)
    expect(canvasPreviewLines("Hi", 42, 10, 1)).toEqual(["Hi"])
    expect(canvasPreviewLines("正文", 5, 10, 1)).toEqual([])
  })
})
