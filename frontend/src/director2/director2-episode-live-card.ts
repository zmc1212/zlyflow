export type Director2EpisodeLiveCard = {
  title: string
  summary?: string
  targetShots?: number
}

export type Director2EpisodeLiveCardSource = Record<string, unknown>

const EPISODE_HEADING = /^第\s*(\d+)\s*集/

function textValue(value: unknown): string | undefined {
  const text = typeof value === "string" ? value.trim() : ""
  return text || undefined
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return undefined
}

function asRecord(value: unknown): Director2EpisodeLiveCardSource | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Director2EpisodeLiveCardSource : undefined
}

function nestedRecord(source: Director2EpisodeLiveCardSource): Director2EpisodeLiveCardSource | undefined {
  const raw = source.data_json ?? source.dataJson ?? source.data
  if (typeof raw === "string" && raw.trim()) {
    try {
      return asRecord(JSON.parse(raw) as unknown)
    } catch {
      return undefined
    }
  }
  return asRecord(raw)
}

function episodeNumber(source: Director2EpisodeLiveCardSource, title: string | undefined, fallbackIndex?: number): number | undefined {
  const explicit = numberValue(source.num ?? source.number ?? source.episode_num ?? source.episodeNumber)
  if (explicit && explicit > 0) return explicit
  const fromTitle = title ? EPISODE_HEADING.exec(title)?.[1] : undefined
  const parsed = numberValue(fromTitle)
  if (parsed && parsed > 0) return parsed
  if (title && fallbackIndex != null && fallbackIndex >= 0) return fallbackIndex + 1
  return undefined
}

function episodeTitle(num: number | undefined, rawTitle: string | undefined): string | undefined {
  if (rawTitle && EPISODE_HEADING.test(rawTitle)) return rawTitle
  if (num && rawTitle) return `第 ${num} 集 · ${rawTitle}`
  if (num) return `第 ${num} 集`
  return rawTitle
}

function positiveCount(...values: unknown[]): number | undefined {
  for (const value of values) {
    const count = numberValue(value)
    if (count != null && count > 0) return count
  }
  return undefined
}

function compactCard(card: Director2EpisodeLiveCard): Director2EpisodeLiveCard {
  const next: Director2EpisodeLiveCard = { title: card.title }
  if (card.summary) next.summary = card.summary
  if (card.targetShots) next.targetShots = card.targetShots
  return next
}

export function normalizeEpisodeLiveCard(item: object, options?: { fallbackIndex?: number }): Director2EpisodeLiveCard | null {
  const source = item as Director2EpisodeLiveCardSource
  const nested = nestedRecord(source)
  const rawTitle = textValue(source.title ?? source.name)
  const num = episodeNumber(source, rawTitle, options?.fallbackIndex)
  const title = episodeTitle(num, rawTitle)
  if (!title) return null
  return compactCard({
    title,
    summary: textValue(source.summary) || textValue(nested?.summary),
    targetShots: positiveCount(
      source.targetShots,
      source.target_shots,
      nested?.targetShots,
      nested?.target_shots,
      source.shots_count,
      source.shotsCount,
      nested?.shots_count,
      nested?.shotsCount,
    ),
  })
}
