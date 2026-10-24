import { describe, expect, it } from "vitest"
import {
  CANVAS_EXPORT_MAX_EDGE,
  CANVAS_EXPORT_MAX_PIXELS,
  CANVAS_EXPORT_PADDING,
  buildCanvasExportScene,
  canvasExportBackgroundColor,
  canvasExportPalette,
  canvasExportPreviewScale,
  canvasPngFileName,
  fitCanvasExportScale,
} from "./canvas-export"
import type { CanvasEdge, CanvasNode } from "./canvas-model"

function node(
  id: string,
  type: string,
  x: number,
  y: number,
  width: number,
  height: number,
  data: CanvasNode["data"] = {},
  extra: Partial<CanvasNode> = {},
): CanvasNode {
  return {
    id,
    type,
    position: { x, y },
    data,
    style: { width, height },
    ...extra,
  } as CanvasNode
}

function edge(id: string, source: string, target: string, extra: Partial<CanvasEdge> = {}): CanvasEdge {
  return { id, source, target, ...extra }
}

describe("canvas export scene", () => {
  it("computes padded bounds and skips hidden nodes", () => {
    const scene = buildCanvasExportScene([
      node("a", "text", 100, 50, 200, 100),
      node("b", "image", 400, 300, 320, 200),
      node("hidden", "image", -900, -900, 100, 100, {}, { hidden: true }),
    ], [], { padding: CANVAS_EXPORT_PADDING, scale: 1 })
    expect(scene).not.toBeNull()
    expect(scene?.bounds).toEqual({
      x: 100 - CANVAS_EXPORT_PADDING,
      y: 50 - CANVAS_EXPORT_PADDING,
      width: 620 + CANVAS_EXPORT_PADDING * 2,
      height: 450 + CANVAS_EXPORT_PADDING * 2,
    })
    expect(scene?.nodeCount).toBe(2)
  })

  it("returns null when nothing is exportable", () => {
    expect(buildCanvasExportScene([], [])).toBeNull()
    expect(buildCanvasExportScene([node("a", "text", 0, 0, 100, 100)], [], { scope: "selection", selectedNodeIds: [] })).toBeNull()
  })

  it("draws artboards behind other nodes and honors zIndex", () => {
    const scene = buildCanvasExportScene([
      node("top", "image", 0, 0, 100, 100, {}, { zIndex: 5 }),
      node("board", "artboard", 0, 0, 500, 500),
      node("mid", "text", 0, 0, 100, 100, {}, { zIndex: 2 }),
    ], [], { scale: 1 })
    expect(scene?.nodes.map((item) => item.id)).toEqual(["board", "mid", "top"])
  })

  it("keeps only edges between exported nodes and drops hidden edges", () => {
    const nodes = [node("a", "text", 0, 0, 100, 100), node("b", "generator", 300, 0, 300, 300), node("c", "image", 700, 0, 200, 200)]
    const scene = buildCanvasExportScene(nodes, [
      edge("ab", "a", "b"),
      edge("bc", "b", "c"),
      edge("aa", "a", "a"),
      edge("ghost", "a", "missing"),
      edge("hidden", "a", "b", { hidden: true }),
    ], { scale: 1, scope: "selection", selectedNodeIds: ["a", "b"] })
    expect(scene?.links.map((link) => link.id)).toEqual(["ab"])
    expect(scene?.nodeCount).toBe(2)
  })

  it("prefers same-origin asset paths for images and rejects unsafe URLs", () => {
    const scene = buildCanvasExportScene([
      node("img", "image", 0, 0, 320, 200, { assetPath: "user/out.png", url: "https://cdn.example.com/out.png" }),
      node("bad", "image", 400, 0, 320, 200, { url: "javascript:alert(1)" }),
      node("data", "image", 800, 0, 320, 200, { url: "data:image/png;base64,AAAA" }),
    ], [], { scale: 1 })
    const [image, bad, data] = scene?.nodes ?? []
    expect(image.imageCandidates).toEqual(["/api/media/user%2Fout.png", "https://cdn.example.com/out.png"])
    expect(bad.imageCandidates).toEqual([])
    expect(data.imageCandidates).toEqual(["data:image/png;base64,AAAA"])
  })

  it("uses a matching cover as the video image candidate", () => {
    const cover = "data:image/jpeg;base64,AAAA"
    const scene = buildCanvasExportScene([
      node("video", "video", 0, 0, 360, 220, {
        url: "/api/media/a.mp4",
        cover,
        coverSource: "/api/media/a.mp4",
        coverTime: 1,
      }),
      node("stale", "video", 400, 0, 360, 220, {
        url: "/api/media/b.mp4",
        cover,
        coverSource: "/api/media/old.mp4",
      }),
    ], [], { scale: 1 })
    const [video, stale] = scene?.nodes ?? []
    expect(video.imageCandidates).toEqual([cover])
    expect(stale.imageCandidates).toEqual([])
  })

  it("uses the selected generator result version and skips video results", () => {
    const scene = buildCanvasExportScene([
      node("gen", "generator", 0, 0, 356, 446, {
        resultUrl: "/api/media/latest.png",
        resultPath: "latest.png",
        resultKind: "image",
        resultHistory: [
          { url: "/api/media/first.png", path: "first.png", kind: "image" },
          { url: "/api/media/latest.png", path: "latest.png", kind: "image" },
        ],
        resultIndex: 0,
      }),
      node("video", "generator", 500, 0, 356, 446, {
        resultUrl: "/api/media/out.mp4",
        resultPath: "out.mp4",
        resultKind: "video",
        jobStatus: "running",
      }),
    ], [], { scale: 1 })
    const [generator, video] = scene?.nodes ?? []
    expect(generator.imageCandidates).toEqual(["/api/media/first.png"])
    expect(generator.mediaKind).toBe("image")
    expect(video.imageCandidates).toEqual([])
    expect(video.mediaKind).toBe("video")
    expect(video.status).toBe("生成中")
  })

  it("merges connected text prompts in edge order and falls back to the manual prompt", () => {
    const nodes = [
      node("late", "text", 0, 300, 200, 80, { text: "第二段" }),
      node("early", "text", 0, 100, 200, 80, { text: "第一段" }),
      node("empty", "text", 0, 500, 200, 80, { text: "  " }),
      node("gen", "generator", 400, 0, 356, 446, { prompt: "手动提示词" }),
      node("gen2", "generator", 900, 0, 356, 446, { prompt: "兜底提示词" }),
    ]
    const scene = buildCanvasExportScene(nodes, [
      edge("e1", "late", "gen"),
      edge("e2", "early", "gen"),
      edge("e3", "late", "gen"),
      edge("e4", "empty", "gen"),
    ], { scale: 1 })
    const generator = scene?.nodes.find((item) => item.id === "gen")
    const fallback = scene?.nodes.find((item) => item.id === "gen2")
    expect(generator?.prompt).toBe("第二段\n\n第一段")
    expect(fallback?.prompt).toBe("兜底提示词")
  })

  it("clamps the requested scale to the edge and pixel limits", () => {
    expect(fitCanvasExportScale(1000, 800, 2)).toBe(2)
    expect(fitCanvasExportScale(5000, 5000, 2)).toBe(0.97)
    expect(fitCanvasExportScale(10_000, 100, 3)).toBe(0.81)
    const huge = buildCanvasExportScene([node("a", "image", 0, 0, 9000, 3000)], [], { scale: 3 })
    expect(huge?.width).toBeLessThanOrEqual(CANVAS_EXPORT_MAX_EDGE)
    expect(huge?.height).toBeLessThanOrEqual(CANVAS_EXPORT_MAX_EDGE)
    expect((huge?.width ?? 0) * (huge?.height ?? 0)).toBeLessThanOrEqual(CANVAS_EXPORT_MAX_PIXELS)
    expect(huge?.scale).toBeLessThan(3)
  })

  it("resolves backgrounds and palettes", () => {
    expect(canvasExportBackgroundColor("light")).toBe("#f8f9fa")
    expect(canvasExportBackgroundColor("dark")).toBe("#0f1115")
    expect(canvasExportBackgroundColor("transparent")).toBeNull()
    expect(canvasExportPalette("dark").surface).toBe("#171a20")
    const scene = buildCanvasExportScene([node("a", "text", 0, 0, 100, 100)], [], {
      background: "transparent",
      theme: "dark",
      scale: 1,
    })
    expect(scene?.background).toBeNull()
    expect(scene?.paletteMode).toBe("dark")
  })

  it("sizes the preview without upscaling", () => {
    expect(canvasExportPreviewScale({ x: 0, y: 0, width: 400, height: 300 })).toBe(1)
    expect(canvasExportPreviewScale({ x: 0, y: 0, width: 1520, height: 800 })).toBe(0.5)
    expect(canvasExportPreviewScale({ x: 0, y: 0, width: 4000, height: 800 })).toBeCloseTo(0.19, 2)
  })

  it("builds a sanitized png filename with a local timestamp", () => {
    expect(canvasPngFileName("雨夜/分镜: v2", new Date(2026, 9, 24, 1, 5))).toBe("雨夜_分镜_v2-20261024-0105.png")
    expect(canvasPngFileName("   ", new Date(2026, 0, 2, 3, 4))).toBe("canvas-20260102-0304.png")
  })
})
