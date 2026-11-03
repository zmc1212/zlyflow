import { describe, expect, it } from "vitest"
import {
  IMAGE_BACKGROUND_REMOVE_WORKFLOW,
  IMAGE_LAYER_SPLIT_WORKFLOW,
  PHOTO_EDIT_MAX_REFERENCES,
  drawRegionAnnotation,
  imageToolSourceError,
  photoEditCountBounds,
  photoEditOptions,
  photoEditResolutionChoices,
  photoEditWorkflowChoices,
  regionAnnotationPromptSuffix,
} from "./image-edit"

describe("image edit tool helpers", () => {
  it("uses the registry workflow ids", () => {
    expect(IMAGE_BACKGROUND_REMOVE_WORKFLOW).toBe("image-background-remove")
    expect(IMAGE_LAYER_SPLIT_WORKFLOW).toBe("image-layer-split")
  })

  it("validates single source images", () => {
    expect(imageToolSourceError({ type: "image/png", size: 1024 })).toBe("")
    expect(imageToolSourceError({ type: "image/jpeg", size: 0 })).toBe("原图不能为空文件")
    expect(imageToolSourceError({ type: "video/mp4", size: 10 })).toBe("原图必须是图片文件")
    expect(imageToolSourceError({ type: "image/png", size: 21 * 1024 * 1024 })).toBe("原图不能超过 20 MB")
    expect(imageToolSourceError({ type: "", size: 10 }, "参考图")).toBe("参考图必须是图片文件")
  })

  it("keeps only available GRS image workflows as photo edit models", () => {
    const choices = photoEditWorkflowChoices([
      { id: "grs-gpt-image-2", name: "GPT Image 2", media_type: "image", available: true },
      { id: "grs-nano-banana-2", name: "Nano Banana 2", media_type: "image", available: false },
      { id: "image-background-remove", name: "图片去背景", media_type: "image", available: true },
      { id: "minimax-h3-t2v", name: "官方 H3 文生视频", media_type: "video", available: true },
    ])
    expect(choices).toEqual([{ id: "grs-gpt-image-2", name: "GPT Image 2" }])
  })

  it("submits photo edits with auto aspect ratio; resolution and count only when meaningful", () => {
    expect(photoEditOptions()).toEqual({ aspect_ratio: "auto" })
    expect(photoEditOptions("2K", 1)).toEqual({ aspect_ratio: "auto", resolution: "2K" })
    expect(photoEditOptions("2K", 3)).toEqual({ aspect_ratio: "auto", resolution: "2K", count: 3 })
    expect(PHOTO_EDIT_MAX_REFERENCES).toBe(10)
  })

  it("describes numbered regions in the prompt suffix only when regions exist", () => {
    expect(regionAnnotationPromptSuffix(0)).toBe("")
    const suffix = regionAnnotationPromptSuffix(2)
    expect(suffix).toContain("第2张参考图")
    expect(suffix).toContain("虚线框 1、2 号")
    expect(suffix).toContain("框外画面与原图保持一致")
  })

  it("draws dashed cyan frames with numbered badges for the overlay", () => {
    const calls: Array<[string, ...unknown[]]> = []
    const context = {
      save: () => calls.push(["save"]),
      restore: () => calls.push(["restore"]),
      beginPath: () => calls.push(["beginPath"]),
      arc: (...args: unknown[]) => calls.push(["arc", ...args]),
      fill: () => calls.push(["fill"]),
      stroke: () => calls.push(["stroke"]),
      strokeRect: (...args: unknown[]) => calls.push(["strokeRect", ...args]),
      fillText: (...args: unknown[]) => calls.push(["fillText", ...args]),
      setLineDash: (...args: unknown[]) => calls.push(["setLineDash", ...args]),
    } as unknown as CanvasRenderingContext2D
    drawRegionAnnotation(context, { x: 10, y: 20, w: 100, h: 60 }, 3, 2)
    expect(calls).toContainEqual(["strokeRect", 10, 20, 100, 60])
    expect(calls).toContainEqual(["setLineDash", []])
    const fillText = calls.find(([name]) => name === "fillText") as unknown[] | undefined
    expect(fillText?.[1]).toBe("3")
    // 徽标圆心落在区域右上角附近。
    const arc = calls.find(([name]) => name === "arc") as unknown[] | undefined
    expect(Number(arc?.[1])).toBeGreaterThan(90)
    expect(Number(arc?.[2])).toBeLessThan(40)
  })

  it("reads resolution choices and count bounds from the mode option schema", () => {
    const mode = {
      id: "grs-nano-banana-2",
      parameters: [{
        name: "options",
        schema: {
          properties: {
            resolution: { label: "分辨率", default: "2K", enum: ["1K", "2K", "4K"] },
            count: { label: "生成数量", default: 1, minimum: 1, maximum: 4 },
          },
        },
      }],
    }
    expect(photoEditResolutionChoices(mode)).toEqual({ values: ["1K", "2K", "4K"], defaultValue: "2K" })
    expect(photoEditResolutionChoices(undefined)).toEqual({ values: [], defaultValue: null })
    expect(photoEditCountBounds(mode)).toEqual({ min: 1, max: 4, default: 1 })
    // 缺 schema 时托管为单张输出。
    expect(photoEditCountBounds(undefined)).toEqual({ min: 1, max: 1, default: 1 })
    // 声明的默认值不在枚举内时回退到 1K。
    const broken = {
      id: "grs-broken",
      parameters: [{ name: "options", schema: { properties: { resolution: { default: "8K", enum: ["2K"] } } } }],
    }
    expect(photoEditResolutionChoices(broken)).toEqual({ values: ["2K"], defaultValue: "2K" })
  })
})
