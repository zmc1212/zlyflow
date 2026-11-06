/** 扩图编辑器共享几何逻辑（即梦式画布交互）：pads 为原图像素坐标系下四边向外扩展量。 */

/** 目标画布单边上限：与后端 OUTPAINT_MAX_SIDE 一致（原图超过时放宽到原图边长）。 */
export const OUTPAINT_MAX_SIDE = 4096

/** 倍数预设：画布每边相对原图线性放大（1.5x = 各边 1.5 倍、面积约 2.25 倍）。 */
export const OUTPAINT_SCALE_PRESETS = [1.5, 2, 3] as const

/** 比例预设（即梦同款顺序）：ratio 为 null 表示"原比例"（按当前面积倍数重置为原图比例）。 */
export const OUTPAINT_RATIO_PRESETS = [
  { id: "original", label: "原比例", ratio: null },
  { id: "1:1", label: "1:1", ratio: 1 },
  { id: "3:4", label: "3:4", ratio: 3 / 4 },
  { id: "9:16", label: "9:16", ratio: 9 / 16 },
  { id: "4:3", label: "4:3", ratio: 4 / 3 },
] as const

export type OutpaintRatioId = (typeof OUTPAINT_RATIO_PRESETS)[number]["id"]

export type OutpaintPads = { left: number; top: number; right: number; bottom: number }

/** 拖拽手柄：四角 + 四边中点。 */
export type OutpaintHandle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w"

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/** 当前目标画布尺寸（原图 + 四边扩展）。 */
export function outpaintCanvasSize(
  size: { width: number; height: number }, pads: OutpaintPads,
): { width: number; height: number } {
  return {
    width: size.width + pads.left + pads.right,
    height: size.height + pads.top + pads.bottom,
  }
}

/** 线性倍数 = 画布相对原图的最大边比（与即梦一致：1.5x 表示画布每边 1.5 倍）。 */
export function outpaintScaleFactor(
  size: { width: number; height: number }, pads: OutpaintPads,
): number {
  const canvas = outpaintCanvasSize(size, pads)
  return Math.max(canvas.width / size.width, canvas.height / size.height)
}

/** 显示文案：一位小数，整数去掉 ".0"（1.5x / 2x / 2.3x）。 */
export function formatOutpaintScale(factor: number): string {
  const rounded = Math.round(factor * 10) / 10
  return Number.isInteger(rounded) ? `${rounded}x` : `${rounded.toFixed(1)}x`
}

function maxExpand(size: { width: number; height: number }): { x: number; y: number } {
  return {
    x: Math.max(OUTPAINT_MAX_SIDE, size.width) - size.width,
    y: Math.max(OUTPAINT_MAX_SIDE, size.height) - size.height,
  }
}

/** 倍数预设 → 对称 pads（居中扩展，夹取到单边上限内）。 */
export function padsForScale(
  size: { width: number; height: number }, scale: number,
): OutpaintPads {
  const limit = maxExpand(size)
  const padX = clamp(Math.round((size.width * (scale - 1)) / 2), 0, Math.floor(limit.x / 2))
  const padY = clamp(Math.round((size.height * (scale - 1)) / 2), 0, Math.floor(limit.y / 2))
  return { left: padX, top: padY, right: padX, bottom: padY }
}

/** 比例预设 → 对称 pads：原图尺寸不变，扩展不足的一边（与后端 outpaint_canvas 同语义）。 */
export function padsForRatio(
  size: { width: number; height: number }, ratio: number,
): OutpaintPads {
  const limit = maxExpand(size)
  const sourceRatio = size.width / size.height
  let canvasW = sourceRatio <= ratio ? Math.round(size.height * ratio) : size.width
  let canvasH = sourceRatio <= ratio ? size.height : Math.round(size.width / ratio)
  canvasW = Math.min(canvasW, size.width + limit.x)
  canvasH = Math.min(canvasH, size.height + limit.y)
  const left = Math.floor((canvasW - size.width) / 2)
  const top = Math.floor((canvasH - size.height) / 2)
  return { left, top, right: canvasW - size.width - left, bottom: canvasH - size.height - top }
}

/** "原比例"：保留当前面积倍数，重置为原图比例的对称扩展。 */
export function padsForOriginalRatio(
  size: { width: number; height: number }, pads: OutpaintPads,
): OutpaintPads {
  return padsForScale(size, outpaintScaleFactor(size, pads))
}

/** 匹配倍数预设（±0.05 容差），无匹配返回 null（Segmented 不高亮）。 */
export function matchedScalePreset(factor: number): number | null {
  const matched = OUTPAINT_SCALE_PRESETS.find((preset) => Math.abs(factor - preset) < 0.05)
  return matched ?? null
}

/** 匹配比例预设（长宽比 ±0.5%），无匹配返回 null。 */
export function matchedRatioPreset(
  size: { width: number; height: number }, pads: OutpaintPads,
): OutpaintRatioId | null {
  const canvas = outpaintCanvasSize(size, pads)
  const ratio = canvas.width / canvas.height
  const matched = OUTPAINT_RATIO_PRESETS.find(
    (preset) => preset.ratio !== null && Math.abs(ratio - preset.ratio) / preset.ratio < 0.005,
  )
  return matched?.id ?? null
}

/** 提交前偶数化：画布尺寸取偶，差值记入右侧/下侧 pad（与后端画布对齐）。 */
export function evenizedPads(size: { width: number; height: number }, pads: OutpaintPads): OutpaintPads {
  const canvas = outpaintCanvasSize(size, pads)
  return {
    ...pads,
    right: pads.right + (canvas.width % 2),
    bottom: pads.bottom + (canvas.height % 2),
  }
}

/** 拖拽更新：按手柄方向应用位移（位移已换算为原图像素），双向夹取 [0, 上限]。 */
export function padsAfterDrag(
  start: OutpaintPads, size: { width: number; height: number },
  handle: OutpaintHandle, dx: number, dy: number,
): OutpaintPads {
  const limit = maxExpand(size)
  let left = start.left
  let top = start.top
  let right = start.right
  let bottom = start.bottom
  if (handle.includes("w")) left = clamp(start.left - dx, 0, limit.x - start.right)
  if (handle.includes("e")) right = clamp(start.right + dx, 0, limit.x - start.left)
  if (handle.includes("n")) top = clamp(start.top - dy, 0, limit.y - start.bottom)
  if (handle.includes("s")) bottom = clamp(start.bottom + dy, 0, limit.y - start.top)
  return {
    left: Math.round(left), top: Math.round(top),
    right: Math.round(right), bottom: Math.round(bottom),
  }
}
