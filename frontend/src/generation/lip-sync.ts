import { REFERENCE_MAX_BYTES } from "./digital-human"

export const LIP_SYNC_WORKFLOW = "minimax-h3-lip-sync"
/** 官方参考视频政策：2-15 秒（24fps 下 48-360 帧）。 */
export const LIPSYNC_SOURCE_MIN_SECONDS = 2
export const LIPSYNC_SOURCE_MAX_SECONDS = 15
/** 单渲染窗口上限（与数字人口播一致）。 */
export const LIPSYNC_AUDIO_MAX_SECONDS = 5

export type LipSyncVideo = {
  id: string
  file: File
  preview: string
  duration?: number
}

export type LipSyncAudio = {
  id: string
  file: File
  duration?: number
}

export function lipsyncVideoError(file: { name: string; size: number; type?: string }): string {
  if (!file.size) return "原视频不能为空文件"
  if (file.size > REFERENCE_MAX_BYTES) return "原视频不能超过 50 MB"
  const extensionMatches = /\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("video/")
  return extensionMatches && typeMatches ? "" : "请上传 MP4 / MOV / WebM 等视频文件"
}

export function lipsyncSourceDurationError(seconds: number | undefined): string {
  if (seconds === undefined || !Number.isFinite(seconds)) return "无法读取原视频时长，请使用标准视频文件"
  if (seconds < LIPSYNC_SOURCE_MIN_SECONDS) return `原视频仅 ${seconds.toFixed(1)} 秒，口型同步要求至少 ${LIPSYNC_SOURCE_MIN_SECONDS} 秒`
  if (seconds > LIPSYNC_SOURCE_MAX_SECONDS) return `原视频 ${seconds.toFixed(1)} 秒超出 ${LIPSYNC_SOURCE_MAX_SECONDS} 秒上限，请先裁剪视频`
  return ""
}
