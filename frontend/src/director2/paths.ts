// 导演台（AI Media Studio）路由解析
// 原版 dev0914 是独立 hash 路由（/、/projects/:id/...、/settings），
// 复刻后映射到工作台路径 /director 前缀下；旧书签 /director2 由 router 重定向到这里。
export const DIRECTOR2_PREFIX = "/director"

export type Director2Route =
  | { kind: "home" }
  | { kind: "diagnosis" }
  | { kind: "project"; projectId: string; menu: "content" | "assets" | "workshop" | "edit" | "jobs"; episodeId: string | null }

const MENU_SEGMENTS = new Set(["content", "assets", "workshop", "edit", "jobs"])

export function parseDirector2Path(pathname: string): Director2Route {
  const rest = pathname === DIRECTOR2_PREFIX || pathname.startsWith(`${DIRECTOR2_PREFIX}/`)
    ? pathname.slice(DIRECTOR2_PREFIX.length)
    : pathname
  const segments = rest.split("/").filter(Boolean)

  if (segments[0] === "script-diagnosis") return { kind: "diagnosis" }

  if (segments[0] === "projects" && segments[1]) {
    const projectId = segments[1]
    const menu = segments[2] && MENU_SEGMENTS.has(segments[2])
      ? (segments[2] as "content" | "assets" | "workshop" | "edit" | "jobs")
      : "content"
    const episodeId = (menu === "workshop" || menu === "edit") && segments[3] ? decodeURIComponent(segments[3]) : null
    return { kind: "project", projectId, menu, episodeId }
  }

  return { kind: "home" }
}

export function director2HomePath(): string {
  return DIRECTOR2_PREFIX
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
  if ((menu === "workshop" || menu === "edit") && episodeId) return `${base}/${menu}/${encodeURIComponent(episodeId)}`
  return `${base}/${menu}`
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
