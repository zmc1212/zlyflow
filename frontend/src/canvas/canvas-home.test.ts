import { describe, expect, it } from "vitest"
import { canvasProjectCoverSources, canvasSavedTime, recentCanvasProjects } from "./canvas-home"
import type { CanvasPreview, CanvasProject } from "./canvas-model"

const project = (id: string, patch: Partial<CanvasProject> = {}): CanvasProject => ({
  id, title: id, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z", ...patch,
})

describe("canvas home recent projects", () => {
  it("shows the three most recent draft saves, independent of favorites or trash", () => {
    const projects = [
      project("favorite", { is_favorite: true, updated_at: "2026-10-27T00:00:00Z" }),
      project("old"),
      project("saved", { draft_updated_at: "2026-10-28T08:00:00Z" }),
      project("new", { updated_at: "2026-10-28T00:00:00Z" }),
      project("trashed", { updated_at: "2026-10-28T09:00:00Z", deleted_at: "2026-10-28T09:01:00Z" }),
    ]
    expect(recentCanvasProjects(projects).map(({ id }) => id)).toEqual(["saved", "new", "favorite"])
    expect(projects[0].id).toBe("favorite")
    expect(recentCanvasProjects([])).toEqual([])
    expect(recentCanvasProjects([projects[4]])).toEqual([])
  })

  it("falls back from invalid legacy draft timestamps", () => {
    expect(recentCanvasProjects([
      project("older"),
      project("legacy", { draft_updated_at: "invalid", updated_at: "2026-10-28T00:00:00Z" }),
    ])[0].id).toBe("legacy")
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

describe("canvas project cover", () => {
  const rect = { x: 0, y: 0, width: 100, height: 100 }
  const preview = (items: CanvasPreview["items"]): CanvasPreview => ({
    ...rect, nodeCount: items.length, items, links: [],
  })

  it("prioritizes generated images and video posters, with distinct image nodes as fallbacks", () => {
    const poster = "data:image/jpeg;base64,YQ=="
    const summary = preview([
      { ...rect, type: "image", url: "/reference.jpg" },
      { ...rect, type: "video", url: "/clip.mp4", cover: poster },
      { ...rect, type: "generator", url: "/generated.jpg" },
      { ...rect, type: "image", url: "/generated.jpg" },
    ])
    expect(canvasProjectCoverSources(summary)).toEqual(["/generated.jpg", poster, "/reference.jpg"])
  })

  it("uses a placeholder for a missing summary or an old draft without usable image sources", () => {
    const summary = preview([
      { ...rect, type: "text", text: "节点正文" },
      { ...rect, type: "audio", url: "/audio.mp3" },
      { ...rect, type: "video", url: "/old.mp4", cover: "invalid" },
      { ...rect, type: "image", url: "javascript:invalid" },
    ])
    expect(canvasProjectCoverSources(summary)).toEqual([])
    expect(canvasProjectCoverSources(null)).toEqual([])
  })
})
