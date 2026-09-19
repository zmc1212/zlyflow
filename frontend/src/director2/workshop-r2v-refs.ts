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

const TRIPTYCH_PANEL_SPECS = [
  { key: "start" as const, name: "起幅构图" },
  { key: "mid" as const, name: "中格构图" },
  { key: "end" as const, name: "结果构图" },
]

const COMPOSITION_DROP_ORDER = ["mid", "end"] as const

export function withTriptychPanels(
  beat: WorkshopTriptychBeat | null | undefined,
  imgs: WorkshopR2VRefImage[],
): WorkshopR2VRefImage[] {
  const fullUrl = String(beat?.triptych_url || "").trim()
  const identity = (fullUrl ? imgs.filter((item) => item.url !== fullUrl) : [...imgs])
    .filter((item) => item.url)
  const panels: WorkshopR2VRefImage[] = []
  for (const spec of TRIPTYCH_PANEL_SPECS) {
    const url = String(beat?.triptych_panels?.[spec.key] || "").trim()
    if (!url || url === fullUrl) continue
    if (identity.some((item) => item.url === url) || panels.some((item) => item.url === url)) continue
    panels.push({
      id: `triptych-${spec.key}-${beat?.id || "beat"}`,
      url,
      name: spec.name,
      category: "composition",
    })
  }
  return fitWorkshopR2VRefs(identity, panels, R2V_REF_LIMIT)
}

function fitWorkshopR2VRefs(
  identity: WorkshopR2VRefImage[],
  panels: WorkshopR2VRefImage[],
  limit: number,
): WorkshopR2VRefImage[] {
  const remaining = limit - identity.length
  if (remaining <= 0) return identity.slice(0, limit)
  let kept = [...panels]
  for (const key of COMPOSITION_DROP_ORDER) {
    if (kept.length <= remaining) break
    kept = kept.filter((item) => !item.id.startsWith(`triptych-${key}-`))
  }
  return [...identity, ...kept.slice(0, remaining)]
}
