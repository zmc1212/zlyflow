import type { DirectorAssetCardData, DirectorAssetCardKind } from "./DirectorAssetSummaryCard"

export type DirectorAssetCardSource = Record<string, unknown>

const GENDER_LABELS: Record<string, string> = {
  male: "男",
  female: "女",
  nonbinary: "非二元",
  男: "男",
  女: "女",
  非二元: "非二元",
}

function textValue(value: unknown): string | undefined {
  const text = typeof value === "string" ? value.trim() : ""
  return text || undefined
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return undefined
}

function stringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const values = value.map((item) => textValue(item)).filter((item): item is string => Boolean(item))
  return values.length ? values : undefined
}

function splitList(value: unknown): string[] | undefined {
  const fromArray = stringArray(value)
  if (fromArray) return fromArray
  const text = textValue(value)
  if (!text) return undefined
  const values = text.split(/[、,，;；/|]+/).map((item) => item.trim()).filter(Boolean)
  return values.length ? values : undefined
}

function asRecord(value: unknown): DirectorAssetCardSource | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as DirectorAssetCardSource : undefined
}

function displayGender(value: unknown): string | undefined {
  const text = textValue(value)
  if (!text) return undefined
  const key = text.toLowerCase()
  if (key === "unspecified" || key === "unknown" || key === "none") return undefined
  return GENDER_LABELS[key] || GENDER_LABELS[text]
}

function lookPrompt(item: DirectorAssetCardSource): string | undefined {
  if (!Array.isArray(item.looks)) return undefined
  for (const look of item.looks) {
    const record = asRecord(look)
    const prompt = textValue(record?.promptText ?? record?.prompt_text)
    if (prompt) return prompt
  }
  return undefined
}

function identitySpec(item: DirectorAssetCardSource): DirectorAssetCardSource | undefined {
  return asRecord(item.identitySpec ?? item.identity_spec)
}

function compactCard(card: DirectorAssetCardData): DirectorAssetCardData {
  const next: DirectorAssetCardData = { kind: card.kind, name: card.name }
  for (const [key, value] of Object.entries(card) as Array<[keyof DirectorAssetCardData, DirectorAssetCardData[keyof DirectorAssetCardData]]>) {
    if (key === "kind" || key === "name") continue
    if (value == null || value === "") continue
    if (Array.isArray(value) && value.length === 0) continue
    ;(next[key] as DirectorAssetCardData[typeof key]) = value
  }
  return next
}

export function assetKindFor(agent: string, field: string): DirectorAssetCardKind | null {
  if (agent === "characters" && field === "characters") return "character"
  if (agent === "characters" && field === "props") return "prop"
  if (agent === "locations" && field === "locations") return "scene"
  return null
}

export function normalizeDirectorAssetCard(kind: DirectorAssetCardKind, item: object): DirectorAssetCardData | null {
  const source = item as DirectorAssetCardSource
  const name = textValue(source.name || source.title)
  if (!name) return null
  if (kind === "character") {
    const spec = identitySpec(source)
    return compactCard({
      kind,
      name,
      role: textValue(source.role),
      age: textValue(source.age) || textValue(spec?.ageRange ?? spec?.age_range),
      gender: displayGender(source.gender),
      shotsCount: numberValue(source.shots_count ?? source.shotsCount),
      fixedProps: stringArray(source.fixed_props ?? source.fixedProps) || splitList(spec?.immutableAccessories ?? spec?.immutable_accessories),
      description: textValue(source.description || source.appearance || source.details),
      visualPrompt: textValue(source.visual_prompt || source.visualPrompt || source.promptText || source.prompt_text) || lookPrompt(source),
    })
  }
  if (kind === "scene") {
    return compactCard({
      kind,
      name,
      sceneType: textValue(source.type || source.sceneType),
      shotsCount: numberValue(source.shots_count ?? source.shotsCount),
      description: textValue(source.description || source.details),
      elements: stringArray(source.elements) || splitList(source.elements),
      visualPrompt: textValue(source.visual_prompt || source.visualPrompt || source.promptText || source.prompt_text),
    })
  }
  return compactCard({
    kind,
    name,
    propKind: textValue(source.kind === "prop" ? undefined : source.kind) || textValue(source.propKind || source.type),
    relatedCharacter: textValue(source.related_character || source.relatedCharacter),
    count: numberValue(source.count),
    description: textValue(source.description),
  })
}

export function relateLiveAssetCards(cards: DirectorAssetCardData[]): DirectorAssetCardData[] {
  const characters = cards.filter((card) => card.kind === "character")
  return cards.map((card) => {
    if (card.kind !== "prop") return card
    if (card.relatedCharacter && card.propKind) return card
    const owner = characters.find((character) => {
      if (character.fixedProps?.includes(card.name)) return true
      return Boolean(character.description?.includes(card.name))
    })
    if (owner) {
      return compactCard({
        ...card,
        propKind: card.propKind || "人物固定道具",
        relatedCharacter: card.relatedCharacter || owner.name,
      })
    }
    if (card.description) {
      return compactCard({
        ...card,
        propKind: card.propKind || "场景陈设道具",
      })
    }
    return card
  })
}
