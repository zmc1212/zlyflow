/**
 * 画布画幅框：把「生成参数里的画面比例」换算成节点的几何尺寸。
 *
 * 无限画布的预览框就是构图框。用户改 9:16 后，节点必须在同一次交互里变成竖框，
 * 否则参数写的是 9:16、画面仍是横的，直到生成返回才变化——这正是「比例没变」的缺陷来源。
 *
 * 本模块只做纯计算；节点组件负责量测标题栏/底栏占用的固定高度并写回 React Flow。
 */
import {
  canvasModeOptionDefinitions,
  type CanvasOptionValue,
  type CanvasWorkflowMode,
} from "./canvas-generation"

/** 画幅框宽度上下限：竖屏比例靠上限回缩，避免一个节点撑满整个视口。 */
export const CANVAS_FRAME_MIN_WIDTH = 240
export const CANVAS_FRAME_MAX_WIDTH = 560
/** 画幅内容区最大高度；超过时按该高度反推宽度，保持比例不失真。 */
export const CANVAS_FRAME_MAX_HEIGHT = 720
/** 媒体区左右内缩：节点左右各 8px 内边距 + 媒体区左右各 1px 边框。 */
export const CANVAS_FRAME_SIDE_INSET = 18
/** 量不到 DOM 时，生成节点用顶部内边距 10 + 底栏 34 兜底。 */
export const CANVAS_GENERATOR_CHROME_HEIGHT = 44
/** 图片节点用顶部内边距 10 + 说明行 28 兜底。 */
export const CANVAS_IMAGE_CHROME_HEIGHT = 38

/** 端点值不是 a:b 时（云端工作流用 landscape/portrait 这类语义值）的映射。 */
const NAMED_FRAME_RATIOS: Record<string, number> = {
  landscape: 16 / 9,
  wide: 16 / 9,
  horizontal: 16 / 9,
  "横屏": 16 / 9,
  "横版": 16 / 9,
  portrait: 9 / 16,
  vertical: 9 / 16,
  "竖屏": 9 / 16,
  "竖版": 9 / 16,
  square: 1,
  "方形": 1,
  "正方形": 1,
}

/** 解析比例值；auto 或无法识别时返回 null（不改动节点框）。 */
export function parseCanvasFrameRatio(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) && value > 0 ? value : null
  }
  if (typeof value !== "string") return null
  const text = value.trim()
  if (!text) return null
  const matched = text.match(/^(\d+(?:\.\d+)?)\s*[:：/]\s*(\d+(?:\.\d+)?)/)
  if (matched) {
    const width = Number(matched[1])
    const height = Number(matched[2])
    return width > 0 && height > 0 ? width / height : null
  }
  if (text.toLowerCase() === "auto") return null
  return NAMED_FRAME_RATIOS[text] ?? NAMED_FRAME_RATIOS[text.toLowerCase()] ?? null
}

/** 生成节点当前应使用的画幅；工作流没有比例参数时为 null。 */
export function generatorFrameRatio(
  mode: CanvasWorkflowMode | null | undefined,
  values: Record<string, CanvasOptionValue>,
): number | null {
  const definitions = canvasModeOptionDefinitions(mode)
  for (const name of ["aspect_ratio", "ratio"]) {
    const definition = definitions[name]
    if (!definition) continue
    const ratio = parseCanvasFrameRatio(values[name] ?? definition.default)
    if (ratio) return ratio
  }
  return null
}

export type CanvasFrameSizeInput = {
  ratio: number
  /** 当前节点宽度，作为换框基准。 */
  width: number
  /** 标题栏、底栏、内边距等非媒体区高度（节点高 − 媒体高）。 */
  chromeHeight?: number
  sideInset?: number
  minWidth?: number
  maxWidth?: number
  maxHeight?: number
}

/**
 * 按比例算出节点尺寸：宽度基本不变，高度随比例增长；
 * 竖屏过高时改用「内容区最大高度」反推宽度，避免节点失控。
 */
export function canvasFrameSize({
  ratio,
  width,
  chromeHeight = 0,
  sideInset = CANVAS_FRAME_SIDE_INSET,
  minWidth = CANVAS_FRAME_MIN_WIDTH,
  maxWidth = CANVAS_FRAME_MAX_WIDTH,
  maxHeight = CANVAS_FRAME_MAX_HEIGHT,
}: CanvasFrameSizeInput): { width: number; height: number } {
  const safeRatio = Math.min(Math.max(Number.isFinite(ratio) && ratio > 0 ? ratio : 1, 0.2), 5)
  const clampWidth = (value: number) => Math.min(maxWidth, Math.max(minWidth, Math.round(value)))
  let frameWidth = clampWidth(width)
  let mediaWidth = Math.max(1, frameWidth - sideInset)
  let mediaHeight = mediaWidth / safeRatio
  if (mediaHeight > maxHeight) {
    mediaHeight = maxHeight
    mediaWidth = mediaHeight * safeRatio
    frameWidth = clampWidth(mediaWidth + sideInset)
  }
  return { width: frameWidth, height: Math.round(mediaHeight + Math.max(0, chromeHeight)) }
}
