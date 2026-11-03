import type { Director2Asset, Director2Project } from "./api"

export type HomeProjectImage = { url: string; fit: "cover" | "contain" }

/** Prefer an explicit cover. Otherwise show up to three distinct images from this project's assets. */
export function homeProjectImages(project: Pick<Director2Project, "cover_url">, assets: Pick<Director2Asset, "image_url" | "kind">[] = []): HomeProjectImage[] {
  const cover = project.cover_url?.trim()
  if (cover) return [{ url: cover, fit: "cover" }]
  const seen = new Set<string>()
  return assets.flatMap(asset => {
    const url = asset.image_url?.trim()
    if (!url || seen.has(url)) return []
    seen.add(url)
    return [{ url, fit: asset.kind === "character" || asset.kind === "prop" ? "contain" as const : "cover" as const }]
  }).slice(0, 3)
}

export function formatHomeProjectDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "编辑时间未知"
  const pad = (number: number) => String(number).padStart(2, "0")
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
