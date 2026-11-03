/** 图片编辑类工具（去背景 / 图层分离 / 图片编辑 / 局部重绘 / 消除笔 / 扩图）的共享校验与提交助手。 */

export const IMAGE_BACKGROUND_REMOVE_WORKFLOW = "image-background-remove"
export const IMAGE_LAYER_SPLIT_WORKFLOW = "image-layer-split"
export const IMAGE_INPAINT_WORKFLOW = "image-inpaint"
export const IMAGE_ERASER_WORKFLOW = "image-eraser"
export const IMAGE_OUTPAINT_WORKFLOW = "image-outpaint"

/** 扩图工具的目标画幅选项（与注册表 OUTPAINT_TARGET_ASPECTS 一致）。 */
export const OUTPAINT_TARGET_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4"] as const

/** 单张素材上限：与工具页其他素材约束保持同一量级。 */
export const IMAGE_TOOL_SOURCE_MAX_BYTES = 20 * 1024 * 1024

/** GRS 图片编辑最多携带的参考图数量（与注册表 collection 上限一致）。 */
export const PHOTO_EDIT_MAX_REFERENCES = 10

export function imageToolSourceError(
  file: Pick<File, "type" | "size">,
  label = "原图",
): string {
  if (!file.size) return `${label}不能为空文件`
  if (file.size > IMAGE_TOOL_SOURCE_MAX_BYTES) return `${label}不能超过 20 MB`
  return file.type.startsWith("image/") ? "" : `${label}必须是图片文件`
}

export type PhotoEditWorkflowChoice = {
  id: string
  name: string
}

/** 从 /api/modes 里挑出可用的 GRS 图片工作流（图片编辑 = 参考图 + 指令改图）。 */
export function photoEditWorkflowChoices(
  modes: Array<{ id: string; name?: string; media_type?: string; available?: boolean; executor?: string }>,
): PhotoEditWorkflowChoice[] {
  return modes
    .filter((mode) => mode.media_type === "image" && mode.available !== false && mode.id.startsWith("grs-"))
    .map((mode) => ({ id: mode.id, name: mode.name || mode.id }))
}

/** 智能改图区域标记：原图自然像素坐标下的矩形。 */
export type PhotoEditRegion = { id: string; x: number; y: number; w: number; h: number }

/** 单图最多标记的区域数：编号过多会稀释标注示意图的指令效果。 */
export const PHOTO_EDIT_REGION_MAX = 6

/** 标注示意图在 references 中的下标（第 1 项为原图，第 2 项为标注副本）。 */
export const PHOTO_EDIT_REGION_OVERLAY_INDEX = 1

/** 区域编号提示词后缀：告知模型标注示意图的语义与“框外不变”约束。 */
export function regionAnnotationPromptSuffix(regionCount: number): string {
  if (regionCount <= 0) return ""
  const numbers = Array.from({ length: regionCount }, (_, index) => index + 1).join("、")
  return [
    `【区域标注】第${PHOTO_EDIT_REGION_OVERLAY_INDEX + 1}张参考图是原图的标注副本：`,
    `虚线框 ${numbers} 号标出了需要修改的位置，`,
    "请把上述编辑指令应用到这些编号区域，框外画面与原图保持一致。",
  ].join("")
}

/**
 * 在画布上下文上绘制单个区域标注：青色虚线框 + 右上角实心编号徽标（白描边保证浅色画面可见）。
 * unit 为随原图分辨率缩放的基础线宽（约 min(w,h)/220）。
 */
export function drawRegionAnnotation(
  context: CanvasRenderingContext2D,
  region: { x: number; y: number; w: number; h: number },
  number: number,
  unit: number,
): void {
  const radius = clamp(unit * 7, 8, 22)
  const lineWidth = Math.max(1.5, unit)
  context.save()
  context.strokeStyle = "#22d3ee"
  context.lineWidth = lineWidth
  context.setLineDash([unit * 5, unit * 4])
  context.strokeRect(region.x, region.y, region.w, region.h)
  context.setLineDash([])
  const cx = region.x + region.w - radius * 0.85
  const cy = region.y + radius * 0.85
  context.beginPath()
  context.arc(cx, cy, radius, 0, Math.PI * 2)
  context.fillStyle = "#0ea5e9"
  context.fill()
  context.lineWidth = Math.max(1, unit)
  context.strokeStyle = "rgba(255, 255, 255, .92)"
  context.stroke()
  context.fillStyle = "#ffffff"
  context.font = `700 ${Math.round(radius)}px system-ui, sans-serif`
  context.textAlign = "center"
  context.textBaseline = "middle"
  context.fillText(String(number), cx, cy + radius * 0.05)
  context.restore()
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/** 图片编辑提交参数：保持原图画幅；分辨率/数量缺省时交给注册表默认值托管。 */
export function photoEditOptions(resolution?: string | null, count?: number): Record<string, string | number> {
  const options: Record<string, string | number> = { aspect_ratio: "auto" }
  if (resolution) options.resolution = resolution
  if (count && count > 1) options.count = count
  return options
}

export type PhotoEditOptionField = {
  label?: string
  default?: unknown
  enum?: unknown[]
  minimum?: number
  maximum?: number
}

export type PhotoEditModeDetail = {
  id: string
  name?: string
  media_type?: string
  available?: boolean
  parameters?: Array<{
    name: string
    schema?: { properties?: Record<string, PhotoEditOptionField> }
  }>
}

function photoEditOptionProperties(mode: PhotoEditModeDetail | undefined): Record<string, PhotoEditOptionField> {
  return mode?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties ?? {}
}

/** 从模式 payload 的 options schema 读取分辨率枚举与默认值（不按参数名硬编码候选值）。 */
export function photoEditResolutionChoices(mode: PhotoEditModeDetail | undefined): {
  values: string[]
  defaultValue: string | null
} {
  const field = photoEditOptionProperties(mode).resolution
  const values = Array.isArray(field?.enum) ? field.enum.map((value) => String(value)) : []
  const fallback = values.includes("1K") ? "1K" : values[0] ?? null
  const declared = field?.default == null ? null : String(field.default)
  return { values, defaultValue: declared && values.includes(declared) ? declared : fallback }
}

/** 从 options schema 读取生成数量边界。 */
export function photoEditCountBounds(mode: PhotoEditModeDetail | undefined): {
  min: number
  max: number
  default: number
} {
  const field = photoEditOptionProperties(mode).count
  const min = Math.max(1, Math.trunc(field?.minimum ?? 1))
  const max = Math.max(min, Math.trunc(field?.maximum ?? 1))
  const declared = Math.trunc(Number(field?.default ?? 1)) || 1
  return { min, max, default: Math.min(max, Math.max(min, declared)) }
}
