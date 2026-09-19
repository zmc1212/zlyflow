import type { DirectorPayloadKind, DirectorProjectListItem } from "../director/director-api"
import type { Director2Project } from "./api"

export const HOME_DIRECTOR_KINDS = ["batch_run", "shot_replication", "hypit_replication"] as const
export type HomeDirectorKind = (typeof HOME_DIRECTOR_KINDS)[number]

export type HomeProjectItem = {
  id: string
  source: "studio" | "director"
  kind: "studio" | HomeDirectorKind
  title: string
  summary: string
  cover_url?: string | null
  updated_at: string
  shot_count?: number
}

const HOME_DIRECTOR_KIND_SET = new Set<string>(HOME_DIRECTOR_KINDS)

export function isHomeDirectorKind(kind: DirectorPayloadKind | string): kind is HomeDirectorKind {
  return HOME_DIRECTOR_KIND_SET.has(kind)
}

export function studioProjectToHomeItem(project: Director2Project): HomeProjectItem {
  return {
    id: project.id,
    source: "studio",
    kind: "studio",
    title: project.name,
    summary: project.description || "",
    cover_url: project.cover_url,
    updated_at: project.updated_at,
  }
}

export function directorProjectToHomeItem(project: DirectorProjectListItem): HomeProjectItem | null {
  if (!isHomeDirectorKind(project.kind)) return null
  return {
    id: project.id,
    source: "director",
    kind: project.kind,
    title: project.title,
    summary: project.summary || "",
    cover_url: project.cover_url,
    updated_at: project.updated_at,
    shot_count: project.shot_count,
  }
}

export function mergeHomeProjects(
  studioProjects: Director2Project[],
  directorProjects: DirectorProjectListItem[],
): HomeProjectItem[] {
  const studioItems = studioProjects.map(studioProjectToHomeItem)
  const directorItems = directorProjects
    .map(directorProjectToHomeItem)
    .filter((item): item is HomeProjectItem => item !== null)
  return [...studioItems, ...directorItems].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at) || 0
    const rightTime = Date.parse(right.updated_at) || 0
    return rightTime - leftTime
  })
}

export const HOME_PROJECT_FILTERS = ["studio", "batch_run", "shot_replication", "hypit_replication", "all"] as const
export type HomeProjectFilter = (typeof HOME_PROJECT_FILTERS)[number]
export const DEFAULT_HOME_PROJECT_FILTER: HomeProjectFilter = "studio"

export function homeProjectKindLabel(kind: HomeProjectItem["kind"]): string {
  if (kind === "batch_run") return "短视频批量"
  if (kind === "shot_replication") return "参考片复刻"
  if (kind === "hypit_replication") return "Hypit 复刻"
  return "创作项目"
}

export function homeProjectFilterLabel(filter: HomeProjectFilter): string {
  if (filter === "all") return "全部"
  if (filter === "studio") return "导演创作"
  return homeProjectKindLabel(filter)
}

export function filterHomeProjects(items: HomeProjectItem[], filter: HomeProjectFilter): HomeProjectItem[] {
  if (filter === "all") return items
  return items.filter((item) => item.kind === filter)
}

export function homeProjectFilterEmptyCopy(filter: HomeProjectFilter): { title: string; hint: string; action: string } {
  if (filter === "batch_run") {
    return { title: "还没有短视频批量工程", hint: "从一个主题开始，生成多条短视频。", action: "新建短视频批量" }
  }
  if (filter === "shot_replication") {
    return { title: "还没有参考片复刻工程", hint: "分析参考片，批量转绘。", action: "新建参考片复刻" }
  }
  if (filter === "hypit_replication") {
    return { title: "还没有 Hypit 复刻工程", hint: "拆结构、换内容、合字幕图形。", action: "新建 Hypit 复刻" }
  }
  if (filter === "all") {
    return { title: "还没有工程", hint: "从上方选择一种创作方式，开始你的第一部片。", action: "新建导演工程" }
  }
  return { title: "还没有导演创作项目", hint: "一句话开始，完成剧本与分镜。可切换筛选查看批量或复刻工程。", action: "新建导演工程" }
}
