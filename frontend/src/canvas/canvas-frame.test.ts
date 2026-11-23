import { describe, expect, it } from "vitest"
import {
  CANVAS_FRAME_MAX_WIDTH,
  CANVAS_FRAME_MIN_WIDTH,
  canvasFrameSize,
  generatorFrameRatio,
  parseCanvasFrameRatio,
} from "./canvas-frame"
import type { CanvasWorkflowMode } from "./canvas-generation"

function modeWith(properties: Record<string, unknown>): CanvasWorkflowMode {
  return {
    id: "minimax-h3-image-t2i",
    name: "H3 图像 文生图",
    media_type: "image",
    parameters: [{ name: "options", schema: { properties } }],
  } as unknown as CanvasWorkflowMode
}

describe("画布画幅解析", () => {
  it("读得懂工作流注册表里的各种比例写法", () => {
    expect(parseCanvasFrameRatio("9:16")).toBeCloseTo(9 / 16)
    expect(parseCanvasFrameRatio("16:9 (Widescreen)")).toBeCloseTo(16 / 9)
    expect(parseCanvasFrameRatio("9：16")).toBeCloseTo(9 / 16)
    expect(parseCanvasFrameRatio("1:1")).toBe(1)
    expect(parseCanvasFrameRatio("2.35:1")).toBeCloseTo(2.35)
  })

  it("语义值与数值都映射成宽高比", () => {
    expect(parseCanvasFrameRatio("landscape")).toBeCloseTo(16 / 9)
    expect(parseCanvasFrameRatio("portrait")).toBeCloseTo(9 / 16)
    expect(parseCanvasFrameRatio("竖屏")).toBeCloseTo(9 / 16)
    expect(parseCanvasFrameRatio(0.75)).toBe(0.75)
  })

  it("auto、空值、脏数据一律不改框", () => {
    expect(parseCanvasFrameRatio("auto")).toBeNull()
    expect(parseCanvasFrameRatio("")).toBeNull()
    expect(parseCanvasFrameRatio("高清")).toBeNull()
    expect(parseCanvasFrameRatio(undefined)).toBeNull()
    expect(parseCanvasFrameRatio(0)).toBeNull()
    expect(parseCanvasFrameRatio(-2)).toBeNull()
    expect(parseCanvasFrameRatio(Number.NaN)).toBeNull()
  })
})

describe("生成节点画幅", () => {
  it("按工作流定义取比例，取不到就不动节点", () => {
    const mode = modeWith({
      aspect_ratio: { label: "画面比例", type: "string", default: "1:1", ui_group: "primary", enum: ["1:1", "9:16"] },
    })
    expect(generatorFrameRatio(mode, { aspect_ratio: "9:16" })).toBeCloseTo(9 / 16)
    expect(generatorFrameRatio(mode, {})).toBe(1)
    expect(generatorFrameRatio(null, { aspect_ratio: "9:16" })).toBeNull()
  })

  it("没有比例参数的工作流不参与换框", () => {
    const mode = modeWith({
      duration: { label: "时长", type: "integer", default: 5, ui_group: "primary" },
    })
    expect(generatorFrameRatio(mode, { duration: 5 })).toBeNull()
  })
})

describe("画幅尺寸换算", () => {
  it("宽度不变、高度按比例增长", () => {
    const square = canvasFrameSize({ ratio: 1, width: 400, chromeHeight: 72 })
    expect(square.width).toBe(400)
    expect(square.height).toBe(382 + 72)

    const portrait = canvasFrameSize({ ratio: 9 / 16, width: 400, chromeHeight: 72 })
    expect(portrait.width).toBe(400)
    expect(portrait.height).toBe(Math.round(382 / (9 / 16)) + 72)

    const wide = canvasFrameSize({ ratio: 16 / 9, width: 400, chromeHeight: 72 })
    expect(wide.height).toBeLessThan(square.height)
  })

  it("竖屏过高时按内容区上限回缩宽度，比例不失真", () => {
    const size = canvasFrameSize({ ratio: 9 / 21, width: 560, chromeHeight: 72 })
    expect(size.height).toBe(720 + 72)
    const mediaWidth = size.width - 18
    expect(mediaWidth / 720).toBeCloseTo(9 / 21, 2)
    expect(size.width).toBeLessThanOrEqual(CANVAS_FRAME_MAX_WIDTH)
  })

  it("宽度被夹在允许区间内", () => {
    expect(canvasFrameSize({ ratio: 1, width: 80, chromeHeight: 0 }).width).toBe(CANVAS_FRAME_MIN_WIDTH)
    expect(canvasFrameSize({ ratio: 1, width: 4000, chromeHeight: 0 }).width).toBe(CANVAS_FRAME_MAX_WIDTH)
  })

  it("非法比例按 1:1 兜底，不会产生 0 或负数高度", () => {
    const size = canvasFrameSize({ ratio: Number.NaN, width: 400, chromeHeight: 72 })
    expect(size.width).toBe(400)
    expect(size.height).toBe(382 + 72)
  })
})
