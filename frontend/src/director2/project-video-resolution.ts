import { getProject } from "./api"

export type ProjectVideoResolution = { value: string; label: string }

export async function projectVideoResolution(projectId: string): Promise<ProjectVideoResolution | null> {
  try {
    const project = await getProject(projectId)
    const extra = (project.extra || (project.settings as { extra?: Record<string, unknown> } | null)?.extra || {}) as Record<string, unknown>
    const value = String(extra.video_resolution || "").trim().toLowerCase()
    if (value === "768p" || value === "2k") {
      return { value, label: String(extra.video_resolution_label || (value === "768p" ? "768P" : "2K")) }
    }
  } catch {
    // 工程元数据失败时沿用当前设置
  }
  return null
}
