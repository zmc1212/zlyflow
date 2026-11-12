// 导演台（AI Media Studio）路由解析
// 原版 dev0914 是独立 hash 路由（/、/projects/:id/...、/settings），
// 复刻后映射到工作台路径 /director 前缀下；旧书签 /director2 由 router 重定向到这里。
export const DIRECTOR2_PREFIX = "/director"

export type Director2Route =
  | { kind: "home" }
  | { kind: "diagnosis" }
  | { kind: "featured"; featuredId: string }
  | { kind: "featured-process"; featuredId: string }
  | { kind: "project"; projectId: string; menu: "content" | "assets" | "workshop" | "workbench" | "edit" | "jobs"; episodeId: string | null }

const MENU_SEGMENTS = new Set(["content", "assets", "workshop", "workbench", "edit", "jobs"])

export function parseDirector2Path(pathname: string): Director2Route {
  const rest = pathname === DIRECTOR2_PREFIX || pathname.startsWith(`${DIRECTOR2_PREFIX}/`)
    ? pathname.slice(DIRECTOR2_PREFIX.length)
    : pathname
  const segments = rest.split("/").filter(Boolean)

  if (segments[0] === "script-diagnosis") return { kind: "diagnosis" }
  if (segments[0] === "featured" && segments[1]) {
    // /director/featured/:id → 图文详情；/director/featured/:id/process → 只读创作过程画布。
    if (segments[2] === "process") return { kind: "featured-process", featuredId: decodeURIComponent(segments[1]) }
    return { kind: "featured", featuredId: decodeURIComponent(segments[1]) }
  }

  if (segments[0] === "projects" && segments[1]) {
    const projectId = segments[1]
    const menu = segments[2] && MENU_SEGMENTS.has(segments[2])
      ? (segments[2] as "content" | "assets" | "workshop" | "workbench" | "edit" | "jobs")
      : "content"
    const episodeId = (menu === "workshop" || menu === "workbench" || menu === "edit") && segments[3] ? decodeURIComponent(segments[3]) : null
    return { kind: "project", projectId, menu, episodeId }
  }

  return { kind: "home" }
}

export function director2HomePath(): string {
  return DIRECTOR2_PREFIX
}

export function director2FeaturedPath(featuredId: string): string {
  return `${DIRECTOR2_PREFIX}/featured/${encodeURIComponent(featuredId)}`
}

export function director2FeaturedProcessPath(featuredId: string): string {
  return `${DIRECTOR2_PREFIX}/featured/${encodeURIComponent(featuredId)}/process`
}

export function director2DiagnosisPath(input: { id?: string; projectId?: string; documentId?: string } = {}): string {
  const params = new URLSearchParams()
  if (input.id) params.set("id", input.id)
  else if (input.projectId && input.documentId) {
    params.set("project", input.projectId)
    params.set("doc", input.documentId)
  }
  return DIRECTOR2_PREFIX + "/script-diagnosis" + (params.size ? "?" + params : "")
}

export function director2ProjectPath(projectId: string, menu: string, episodeId?: string | null): string {
  const base = `${DIRECTOR2_PREFIX}/projects/${encodeURIComponent(projectId)}`
  if (!menu || menu === "content") return `${base}/content`
  if ((menu === "workshop" || menu === "workbench" || menu === "edit") && episodeId) return `${base}/${menu}/${encodeURIComponent(episodeId)}`
  return `${base}/${menu}`
}

/**
 * 侧栏/下拉切换模块时该带上的分集 ID。
 * 剧集工坊与智能剪辑是同一集的两个视图：离开时把「正在制作的这集」带过去，
 * 否则智能剪辑会回落到自由剪辑序列，后端不加载镜头成片，素材库看起来是空的。
 * 已经在剪辑页时保持当前序列，避免把用户显式选择的「自由剪辑」顶掉。
 */
export function director2MenuEpisodeId(input: {
  targetMenu: string
  currentMenu: string
  currentEpisodeId: string | null
  lastEpisodeId?: string | null
}): string | null {
  const { targetMenu, currentMenu, currentEpisodeId, lastEpisodeId } = input
  if (targetMenu === "edit")
    return currentMenu === "edit" ? currentEpisodeId : currentEpisodeId || lastEpisodeId || null
  if (targetMenu === "workshop" && currentMenu === "edit") return currentEpisodeId?.startsWith("canvas-") ? null : currentEpisodeId
  if (targetMenu === "workbench") return currentMenu === "workbench" ? currentEpisodeId : currentEpisodeId || lastEpisodeId || null
  return null
}

export function director2WorkshopEpisodePath(
  projectId: string,
  episodeId: string,
  tab?: string | null,
): string {
  const path = director2ProjectPath(projectId, "workshop", episodeId)
  const key = String(tab || "").trim()
  if (!key) return path
  const params = new URLSearchParams()
  params.set("tab", key)
  return `${path}?${params.toString()}`
}

export function director2ContentLibraryDocPath(projectId: string, docId: string): string {
  const params = new URLSearchParams()
  params.set("mode", "manual")
  params.set("doc", docId)
  params.set("tab", "episodes")
  return `${director2ProjectPath(projectId, "content")}?${params.toString()}`
}
