export const DIGITAL_HUMAN_WORKFLOW = "minimax-h3-avatar"
/** 单渲染窗口的口播时长上限（H3 24fps、17n+5 网格 124 帧）。 */
export const AUDIO_MAX_SECONDS = 5
export const REFERENCE_MAX_BYTES = 50 * 1024 * 1024

export type DigitalHumanAudio = {
  id: string
  file: File
  duration?: number
}

export function digitalHumanImageError(file: Pick<File, "type" | "size">, label = "人物形象图"): string {
  if (!file.size) return `${label}不能为空文件`
  if (file.size > REFERENCE_MAX_BYTES) return `${label}不能超过 50 MB`
  return file.type.startsWith("image/") ? "" : `${label}必须是图片文件`
}

export function digitalHumanAudioError(file: { name: string; size: number; type?: string }, label = "口播音频"): string {
  if (!file.size) return `${label}不能为空文件`
  if (file.size > REFERENCE_MAX_BYTES) return `${label}不能超过 50 MB`
  const extensionMatches = /\.(wav|mp3|m4a|aac|ogg|flac)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("audio/")
  return extensionMatches && typeMatches ? "" : `请上传 WAV / MP3 等音频`
}

/** 读取媒体时长（秒，音视频通用）；无法解析时返回 undefined。 */
export function probeMediaDuration(file: File): Promise<number | undefined> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const probe = document.createElement(file.type.startsWith("video/") ? "video" : "audio")
    const finish = (duration: number | undefined) => {
      URL.revokeObjectURL(url)
      resolve(duration)
    }
    probe.onloadedmetadata = () => finish(Number.isFinite(probe.duration) ? probe.duration : undefined)
    probe.onerror = () => finish(undefined)
    probe.src = url
  })
}
