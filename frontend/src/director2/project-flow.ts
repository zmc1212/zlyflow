import type { Director2Asset, Director2Document, Director2Episode } from "./api"
import { canvasIdentities } from "./asset-canvas-model"
import { director2ProjectPath, type Director2Route } from "./paths"

export type ProjectMenu = Extract<Director2Route, { kind: "project" }>["menu"]
export type ProjectPosition = { menu: ProjectMenu; episodeId: string | null; search?: string }
export type ProjectFlow = { documents: Director2Document[]; assets: Director2Asset[]; episodes: Director2Episode[] }
const menus = new Set<ProjectMenu>(["content", "assets", "workshop", "workbench", "edit", "jobs"])
const key = (projectId: string) => `director-project-position-v1:${projectId}`

export function readProjectPosition(projectId: string): ProjectPosition | null {
  try { return parseProjectPosition(localStorage.getItem(key(projectId))) } catch { return null }
}

export function parseProjectPosition(raw: string | null): ProjectPosition | null {
  try {
    const value = JSON.parse(raw || "null")
    if (!value || !menus.has(value.menu)) return null
    const params = new URLSearchParams(typeof value.search === "string" ? value.search : "")
    const search = new URLSearchParams()
    for (const name of ["doc", "section", "asset", "tab"]) if (params.get(name)) search.set(name, params.get(name)!)
    return { menu: value.menu, episodeId: ["workshop", "workbench", "edit"].includes(value.menu) && typeof value.episodeId === "string" ? value.episodeId : null, search: search.toString() }
  } catch { return null }
}

export function rememberProjectPosition(projectId: string, position: ProjectPosition) {
  try { localStorage.setItem(key(projectId), JSON.stringify(position)) } catch { /* Navigation still works without browser storage. */ }
}

export function projectStageAccess(flow: ProjectFlow) {
  const script = flow.documents.some(doc => !!doc.raw_text?.trim())
  const produced = flow.assets.length > 0 || flow.episodes.length > 0
  return { content: true, assets: script || produced, workshop: produced, workbench: produced, edit: true, jobs: true }
}

/** Only resume positions that still exist in this project's current server data. */
export function resumeProjectPath(projectId: string, flow: ProjectFlow, saved: ProjectPosition | null): string {
  const access = projectStageAccess(flow)
  if (saved && access[saved.menu]) {
    const episodeId = saved.episodeId && flow.episodes.some(ep => ep.id === saved.episodeId) ? saved.episodeId : null
    const params = new URLSearchParams(saved.search)
    if (params.has("doc") && !flow.documents.some(doc => doc.id === params.get("doc"))) params.delete("doc")
    if (params.has("asset") && !flow.assets.some(asset => asset.id === params.get("asset"))) params.delete("asset")
    const path = director2ProjectPath(projectId, saved.menu, episodeId)
    return path + (params.size ? `?${params}` : "")
  }
  return director2ProjectPath(projectId, flow.episodes.length ? "workshop" : flow.assets.length ? "assets" : "content")
}

export function assetReadiness(asset: Director2Asset): { total: number; ready: number; label: string } {
  if (asset.kind === "character") {
    const looks = canvasIdentities(asset)
    const ready = looks.filter(look => typeof look.image_url === "string" && look.image_url.trim()).length
    const total = Math.max(1, looks.length)
    return { total, ready, label: ready === total ? `${total} 套造型已就绪` : `待完善 ${total - ready} 套造型` }
  }
  const ready = asset.kind === "scene" ? !!(asset.extra?.master_url || asset.image_url) : !!(asset.extra?.reference_url || asset.image_url)
  return { total: 1, ready: ready ? 1 : 0, label: ready ? (asset.kind === "scene" ? "主视角已就绪" : "参考图已就绪") : "待完善参考图" }
}
