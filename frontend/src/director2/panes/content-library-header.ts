const HEADER_TAG_MAX_CHARS = 64

/** 剧本顶栏只放短标签；定位长文/句号段落会把「转入资产库」挤出卡片。 */
export function contentLibraryHeaderTagText(value: unknown): string | null {
  if (typeof value !== "string") return null
  const text = value.trim()
  if (!text) return null
  if (text.length > HEADER_TAG_MAX_CHARS || /[。！？\n]/.test(text)) return null
  return text
}
