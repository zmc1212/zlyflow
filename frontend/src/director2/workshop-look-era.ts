/** 与 backend character_looks.py 的时代关键词保持一致。 */
const MODERN_RE = /现代|当代|21世纪|大学|图书馆|电脑|白领|硕士|衬衫|西装|研究生|26岁/
const ANCIENT_RE = /古代|茅屋|长衫|粗布|发髻|陶碗|木床|土墙|米缸|17岁/
const LOOK_MODERN_RE = /现代|当代|西装|衬衫|研究生|硕士|26岁/
const LOOK_ANCIENT_RE = /古代|长衫|粗布|发髻|17岁/

export type WorkshopLookEra = "modern" | "ancient" | ""

export type WorkshopLookOption = {
  value: string
  label: string
  description?: string
}

export type WorkshopLookBeat = {
  heading?: string
  scene?: string
  speaker?: string
  characters?: unknown
  action?: string
  visual_prompt?: string
  character_ids?: string[] | null
  triptych_url?: string | null
  triptych_panels?: { start?: string | null } | null
  triptych_look_ids?: Record<string, string> | null
}

function classify(text: string, modernRe: RegExp, ancientRe: RegExp): WorkshopLookEra {
  const blob = String(text || "")
  const modern = modernRe.test(blob)
  const ancient = ancientRe.test(blob)
  if (modern && !ancient) return "modern"
  if (ancient && !modern) return "ancient"
  if (modern && ancient) return "modern"
  return ""
}

export function beatLookEra(beat: WorkshopLookBeat | null | undefined): WorkshopLookEra {
  if (!beat) return ""
  const primary = [beat.heading, beat.scene, beat.speaker, ...(Array.isArray(beat.characters) ? beat.characters : [])]
    .map((item) => String(item || ""))
    .join(" ")
  const primaryEra = classify(primary, MODERN_RE, ANCIENT_RE)
  if (primaryEra) return primaryEra
  return classify(`${beat.action || ""} ${beat.visual_prompt || ""}`, MODERN_RE, ANCIENT_RE)
}

export function lookOptionEra(look: WorkshopLookOption | null | undefined): WorkshopLookEra {
  if (!look) return ""
  return classify(`${look.label || ""} ${look.description || ""}`, LOOK_MODERN_RE, LOOK_ANCIENT_RE)
}

export function inferCharacterLookId(
  lookOptions: WorkshopLookOption[],
  beat: WorkshopLookBeat | null | undefined,
  selectedLookId?: string | null,
  legacyLookId?: string | null,
): string {
  const ids = new Set(lookOptions.map((item) => item.value))
  if (selectedLookId && ids.has(selectedLookId)) return selectedLookId
  if (legacyLookId && ids.has(legacyLookId)) return legacyLookId
  const era = beatLookEra(beat)
  if (era) {
    const match = lookOptions.find((item) => lookOptionEra(item) === era)
    if (match) return match.value
    return ""
  }
  return lookOptions.length === 1 ? lookOptions[0].value : ""
}

export function beatLookEraWarning(
  beat: WorkshopLookBeat | null | undefined,
  lookOptions: WorkshopLookOption[],
  selectedLookId: string,
): string {
  if (selectedLookId) return ""
  const era = beatLookEra(beat)
  if (!era || !lookOptions.length) return ""
  const matching = lookOptions.some((look) => {
    const lookEra = lookOptionEra(look)
    return !lookEra || lookEra === era
  })
  if (matching) return ""
  const existing = lookOptions[0]
  const eraLabel = era === "modern" ? "现代" : "古代"
  return `本镜偏${eraLabel}，当前设定板「${existing.label}」对不上。请到资产库补一套对应造型，或在下方指定已有造型后出片。`
}

export function triptychLooksStaleWarning(
  beat: WorkshopLookBeat | null | undefined,
  currentLookIds: Record<string, string>,
): string {
  const hasTriptych = Boolean(
    String(beat?.triptych_url || "").trim() || String(beat?.triptych_panels?.start || "").trim(),
  )
  if (!hasTriptych) return ""
  const snapshot = beat?.triptych_look_ids
  if (!snapshot || typeof snapshot !== "object" || !Object.keys(snapshot).length) {
    return "当前三联关键帧生成时没有锁定本镜角色造型，服装可能与设定板不一致。请重生成三联后再写稿或出片。"
  }
  const characterIds = (beat?.character_ids || []).filter(Boolean)
  const keys = characterIds.length ? characterIds : Object.keys(currentLookIds)
  for (const cid of keys) {
    const now = String(currentLookIds[cid] || "")
    const then = String(snapshot[cid] || "")
    if (now && then && now !== then) {
      return "当前三联关键帧用的是另一套角色造型。请重生成三联后再写稿或出片，否则成片服装会对不上设定板。"
    }
  }
  return ""
}
