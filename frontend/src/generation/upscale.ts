export const UPSCALE_ENGINE_RTX = "nvidia-rtx-vsr"
export const UPSCALE_ENGINE_SEEDVR2 = "seedvr2-upscale"

export type UpscaleEngine = typeof UPSCALE_ENGINE_RTX | typeof UPSCALE_ENGINE_SEEDVR2

export const UPSCALE_SOURCE_MAX_BYTES = 500 * 1024 * 1024

export type UpscaleSourceAsset = {
  id: string
  file: File
  preview: string
  duration?: number
}

export function upscaleSourceError(file: Pick<File, "type" | "name" | "size">): string {
  if (!file.size) return "原片不能为空文件"
  if (file.size > UPSCALE_SOURCE_MAX_BYTES) return "原片不能超过 500 MB"
  const extensionMatches = /\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("video/")
  return extensionMatches && typeMatches ? "" : "请上传 MP4 / MOV / WebM 等视频文件"
}

export const UPSCALE_ENGINE_LABEL: Record<UpscaleEngine, string> = {
  [UPSCALE_ENGINE_RTX]: "RTX 2x 超分（快）",
  [UPSCALE_ENGINE_SEEDVR2]: "SeedVR2 高清增强（慢）",
}
