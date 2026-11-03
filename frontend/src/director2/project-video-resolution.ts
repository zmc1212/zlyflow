import { getProject } from "./api"

export type ProjectVideoResolution = { value: string; label: string }
export type ProjectVideoPreferences = { resolution: ProjectVideoResolution | null; aspectRatio?: string }

export async function projectVideoPreferences(projectId: string): Promise<ProjectVideoPreferences | null> {
  try {
    const project = await getProject(projectId)
    const extra = (project.extra || (project.settings as { extra?: Record<string, unknown> } | null)?.extra || {}) as Record<string, unknown>
    const value = String(extra.video_resolution || "").trim().toLowerCase()
    const aspectRatio = String(extra.workshop_aspect_ratio || "").trim()
    const resolution = value === "768p" || value === "2k" ? { value, label: String(extra.video_resolution_label || (value === "768p" ? "768P" : "2K")) } : null
    return { resolution, ...(aspectRatio ? { aspectRatio } : {}) }
  } catch {
    // 工程元数据失败时沿用当前设置
  }
  return null
}

export async function projectVideoResolution(projectId: string): Promise<ProjectVideoResolution | null> {
  return (await projectVideoPreferences(projectId))?.resolution || null
}
