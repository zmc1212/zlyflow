export const DEFAULT_DIRECTOR_PROJECT_NAME = "未命名导演工程"
export const MAX_DIRECTOR_PROJECT_NAME_LEN = 80

export function isPlaceholderDirectorProjectName(name: string | null | undefined): boolean {
  const text = String(name || "").trim()
  return !text || text === DEFAULT_DIRECTOR_PROJECT_NAME || text.startsWith("未命名")
}

export function sanitizeDirectorProjectName(name: string | null | undefined): string {
  const stripped = String(name || "").replace(/\s+/g, " ").trim().replace(/\.(md|markdown|txt|docx)$/i, "").trim()
  if (stripped.length <= MAX_DIRECTOR_PROJECT_NAME_LEN) return stripped
  return stripped.slice(0, MAX_DIRECTOR_PROJECT_NAME_LEN).trim()
}
