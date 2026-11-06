export const INPAINT_WORKFLOW = "minimax-h3-inpaint"

export const INPAINT_REFERENCE_MAX_BYTES = 50 * 1024 * 1024

export type InpaintReferenceAsset = {
  id: string
  file: File
  preview: string
  duration?: number
}

export function inpaintReferenceError(file: Pick<File, "type" | "name" | "size">, kind: "mask" | "video"): string {
  const label = kind === "mask" ? "重绘遮罩图" : "原片视频"
  if (!file.size) return `${label}不能为空文件`
  if (file.size > INPAINT_REFERENCE_MAX_BYTES) return `${label}不能超过 50 MB`
  if (kind === "mask") return file.type.startsWith("image/") ? "" : "重绘遮罩图必须是图片文件"
  const extensionMatches = /\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("video/")
  return extensionMatches && typeMatches ? "" : "请上传 MP4 / MOV / WebM 等原片视频"
}

export function inpaintDurationError(seconds: number | undefined, duration: unknown): string {
  const required = Number.parseFloat(String(duration))
  if (seconds === undefined || !Number.isFinite(seconds) || !Number.isFinite(required)) return ""
  return seconds + 0.1 < required
    ? `原片只有 ${seconds.toFixed(1)} 秒，请选择更短的生成时长或更换原片`
    : ""
}

export {
  motionToolOptions as inpaintToolOptions,
  motionToolDefaults as inpaintToolDefaults,
  motionToolPayload as inpaintToolPayload,
  type ToolOptionDefinition,
} from "./motion-transfer"
