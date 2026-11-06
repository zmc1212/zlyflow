export const STEM_SPLIT_MODE = "stem-split"
export const STEM_SPLIT_SOURCE_MAX_BYTES = 300 * 1024 * 1024

const STEM_SPLIT_AUDIO_EXTENSIONS = /\.(mp3|wav|flac|m4a|aac|ogg|opus|wma)$/i
const STEM_SPLIT_VIDEO_EXTENSIONS = /\.(mp4|mov|webm|mkv|m4v|avi)$/i

export type StemSplitSourceAsset = {
  id: string
  file: File
  preview: string
}

export function isStemSplitAudio(file: Pick<File, "name">): boolean {
  return STEM_SPLIT_AUDIO_EXTENSIONS.test(file.name)
}

/** 返回空字符串表示素材可用；否则返回给用户看的错误文案。 */
export function stemSplitSourceError(file: Pick<File, "type" | "name" | "size">): string {
  if (!file.size) return "素材不能为空文件"
  if (file.size > STEM_SPLIT_SOURCE_MAX_BYTES) return "素材不能超过 300 MB"
  const extensionMatches = STEM_SPLIT_AUDIO_EXTENSIONS.test(file.name) || STEM_SPLIT_VIDEO_EXTENSIONS.test(file.name)
  const typeMatches =
    !file.type
    || file.type === "application/octet-stream"
    || file.type.startsWith("audio/")
    || file.type.startsWith("video/")
  return extensionMatches && typeMatches
    ? ""
    : "仅支持 MP3 / WAV / FLAC / M4A 等音频，或 MP4 / MOV / WebM 视频"
}
