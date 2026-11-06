import { describe, expect, it } from "vitest"
import {
  OUTPAINT_MAX_SIDE,
  evenizedPads,
  formatOutpaintScale,
  matchedRatioPreset,
  matchedScalePreset,
  outpaintCanvasSize,
  outpaintScaleFactor,
  padsAfterDrag,
  padsForOriginalRatio,
  padsForRatio,
  padsForScale,
} from "./outpaint-editor"

const SIZE = { width: 400, height: 300 }

describe("outpaint editor geometry", () => {
  it("computes canvas size from pads", () => {
    expect(outpaintCanvasSize(SIZE, { left: 10, top: 0, right: 20, bottom: 5 })).toEqual({ width: 430, height: 305 })
  })

  it("scale presets expand symmetrically and cap to max side", () => {
    expect(padsForScale(SIZE, 1.5)).toEqual({ left: 100, top: 75, right: 100, bottom: 75 })
    expect(outpaintCanvasSize(SIZE, padsForScale(SIZE, 2))).toEqual({ width: 800, height: 600 })
    // 3x 超过 4096 上限时夹取：400*3=1200 < 4096，不受影响；极端小图测试夹取语义。
    const tiny = { width: 10, height: 10 }
    const capped = padsForScale(tiny, 3)
    expect(outpaintCanvasSize(tiny, capped).width).toBeLessThanOrEqual(Math.max(OUTPAINT_MAX_SIDE, tiny.width))
  })

  it("ratio presets expand the deficient side (backend outpaint_canvas semantics)", () => {
    // 4:3 原图扩到 1:1：更横 → 宽度不变，向上下扩展。
    expect(outpaintCanvasSize(SIZE, padsForRatio(SIZE, 1))).toEqual({ width: 400, height: 400 })
    // 竖版目标（3:4）：画布必须包含 400 宽的原图 → 高度扩到 533。
    expect(outpaintCanvasSize(SIZE, padsForRatio(SIZE, 3 / 4))).toEqual({ width: 400, height: 533 })
    const portrait = { width: 300, height: 400 }
    expect(outpaintCanvasSize(portrait, padsForRatio(portrait, 3 / 4))).toEqual({ width: 300, height: 400 })
  })

  it("original-ratio preset keeps the current linear factor but recenters", () => {
    const dragged = { left: 200, top: 0, right: 0, bottom: 0 }
    const factor = outpaintScaleFactor(SIZE, dragged)
    const reset = padsForOriginalRatio(SIZE, dragged)
    const canvas = outpaintCanvasSize(SIZE, reset)
    expect(canvas.width / canvas.height).toBeCloseTo(SIZE.width / SIZE.height, 2)
    expect(outpaintScaleFactor(SIZE, reset)).toBeCloseTo(factor, 2)
  })

  it("formats scale like jimeng (1.5x / 2x / 2.3x)", () => {
    expect(formatOutpaintScale(1.5)).toBe("1.5x")
    expect(formatOutpaintScale(2)).toBe("2x")
    expect(formatOutpaintScale(2.34)).toBe("2.3x")
  })

  it("matches presets within tolerance", () => {
    expect(matchedScalePreset(1.5)).toBe(1.5)
    expect(matchedScalePreset(2.02)).toBe(2)
    expect(matchedScalePreset(1.8)).toBeNull()
    // 4:3 原图 1.5x 对称扩展仍是 4:3 → 命中 4:3 预设（"原比例"由组件按原图比例兜底）。
    expect(matchedRatioPreset(SIZE, padsForScale(SIZE, 1.5))).toBe("4:3")
    expect(matchedRatioPreset(SIZE, padsForRatio(SIZE, 1))).toBe("1:1")
  })

  it("evenizes canvas on submit by absorbing the remainder into right/bottom", () => {
    const pads = { left: 0, top: 0, right: 0, bottom: 0 }
    const odd = { width: 401, height: 301 }
    const evened = evenizedPads(odd, pads)
    expect(outpaintCanvasSize(odd, evened)).toEqual({ width: 402, height: 302 })
  })

  it("drag updates only the dragged sides and clamps to limits", () => {
    const start = padsForScale(SIZE, 1.5)
    // 向右拖右缘 50px：只有右边增加。
    expect(padsAfterDrag(start, SIZE, "e", 50, 10).right).toBe(start.right + 50)
    expect(padsAfterDrag(start, SIZE, "e", 50, 10).left).toBe(start.left)
    // 向右拖左缘（dx 为正）收拢左边，过界夹到 0；向左拖（dx 为负）扩大左边。
    expect(padsAfterDrag({ left: 5, top: 0, right: 0, bottom: 0 }, SIZE, "w", 50, 0).left).toBe(0)
    expect(padsAfterDrag({ left: 5, top: 0, right: 0, bottom: 0 }, SIZE, "w", -50, 0).left).toBe(55)
    // 上限：右缘拖到画布总宽不允许超过 maxSide。
    const huge = padsAfterDrag(start, SIZE, "e", 100000, 0)
    expect(outpaintCanvasSize(SIZE, huge).width).toBeLessThanOrEqual(Math.max(OUTPAINT_MAX_SIDE, SIZE.width))
    // 角手柄同时更新两个方向。
    const corner = padsAfterDrag(start, SIZE, "se", 30, 40)
    expect(corner.right).toBe(start.right + 30)
    expect(corner.bottom).toBe(start.bottom + 40)
  })
})
