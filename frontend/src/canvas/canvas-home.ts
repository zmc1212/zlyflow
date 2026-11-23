import { normalizeCanvasCover } from "./canvas-cover"
import { isSafeMediaUrl, type CanvasPreview, type CanvasProject } from "./canvas-model"

function timestamp(value?: string | null): number {
  const parsed = value ? Date.parse(value) : NaN
  return Number.isFinite(parsed) ? parsed : 0
}

function lastSaved(project: CanvasProject): number {
  return timestamp(project.draft_updated_at) || timestamp(project.updated_at) || timestamp(project.created_at)
}

/** 最近入口按保存时间排序，收藏状态不影响顺序。 */
export function recentCanvasProjects(projects: CanvasProject[]): CanvasProject[] {
  return projects.filter((project) => !project.deleted_at)
    .sort((left, right) => lastSaved(right) - lastSaved(left))
    .slice(0, 3)
}

export function canvasSavedTime(value?: string | null, now = Date.now()): string {
  const saved = timestamp(value)
  if (!saved) return "尚未保存"
  const elapsed = Math.max(0, now - saved)
  if (elapsed < 60_000) return "刚刚"
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  if (elapsed < 172_800_000) return "昨天"
  if (elapsed < 604_800_000) return `${Math.floor(elapsed / 86_400_000)} 天前`
  return new Date(saved).toLocaleDateString("zh-CN", { year: "numeric", month: "numeric", day: "numeric" })
}

/** 先选生成结果或已保存的视频封面，再从图片节点取图。 */
export function canvasProjectCoverSources(preview?: CanvasPreview | null): string[] {
  const sources = new Set<string>()
  const items = preview?.items ?? []
  for (const type of ["generator", "video", "image"] as const) {
    for (const item of items) {
      if (item.type !== type) continue
      const source = type === "video" ? normalizeCanvasCover(item.cover) : item.url?.trim()
      if (source && isSafeMediaUrl(source)) sources.add(source)
    }
  }
  return [...sources]
}
