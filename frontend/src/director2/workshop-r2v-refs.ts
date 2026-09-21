export type WorkshopR2VRefImage = {
  id: string
  url: string
  name: string
  category?: string
}

export type WorkshopTriptychBeat = {
  id?: string | null
  triptych_url?: string | null
  triptych_panels?: {
    start?: string | null
    mid?: string | null
    end?: string | null
  } | null
}

const R2V_REF_LIMIT = 9

export const H3_REFERENCE_REGENERATE_LABEL = "按新规则重新生成"

const TRIPTYCH_PANEL_SPECS = [
  { key: "start" as const, name: "三联起幅" },
  { key: "mid" as const, name: "三联中格" },
  { key: "end" as const, name: "三联落幅" },
]

function uniqueByUrl(imgs: WorkshopR2VRefImage[]): WorkshopR2VRefImage[] {
  const seen = new Set<string>()
  return imgs.filter((item) => {
    const url = String(item.url || "").trim()
    if (!url || seen.has(url)) return false
    seen.add(url)
    return true
  })
}

export function videoReferenceImages(imgs: WorkshopR2VRefImage[]): WorkshopR2VRefImage[] {
  return uniqueByUrl(imgs.filter((item) => item.category === "character" || item.category === "prop"))
    .slice(0, R2V_REF_LIMIT)
}

export function authoringContextImages(
  beat: WorkshopTriptychBeat | null | undefined,
  imgs: WorkshopR2VRefImage[],
): WorkshopR2VRefImage[] {
  const context = imgs.filter((item) => item.category === "scene" || item.category === "composition" || item.category === "upload")
  const fullUrl = String(beat?.triptych_url || "").trim()
  if (fullUrl) {
    context.push({
      id: `triptych-full-${beat?.id || "beat"}`,
      url: fullUrl,
      name: "三联关键帧母图",
      category: "composition",
    })
  }
  for (const spec of TRIPTYCH_PANEL_SPECS) {
    const url = String(beat?.triptych_panels?.[spec.key] || "").trim()
    if (!url || url === fullUrl) continue
    context.push({
      id: `triptych-${spec.key}-${beat?.id || "beat"}`,
      url,
      name: spec.name,
      category: "composition",
    })
  }
  return uniqueByUrl(context)
}

export function h3ReferenceWarning(
  state: string | null | undefined,
  reason: string | null | undefined,
): { title: string; description: string } | null {
  if (state !== "stale" && state !== "invalid") return null
  return {
    title: state === "stale" ? "H3 提示词已过期" : "H3 提示词引用无效",
    description: String(reason || "当前提示词与最终视频参考不一致。"),
  }
}
