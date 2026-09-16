export type StoryboardPolishPhase = {
  title: string
  episode?: number
  index?: number
  total?: number
  range?: [number, number]
  currentShot?: number
  chars?: number
}

export type StoryboardPolishShotGroup = {
  episode: number
  label: string
  numbers: number[]
}

export function parseStoryboardPhase(message: string | undefined | null): StoryboardPolishPhase | null {
  if (!message) return null
  const episodeMatch = message.match(/^第\s*(\d+)\s*集\s*·\s*/)
  const episode = episodeMatch ? Number(episodeMatch[1]) : undefined
  const hasEpisodePrefix = episode !== undefined
  const text = message.replace(/^第\s*\d+\s*集\s*·\s*/, "")
  const charsMatch = text.match(/已收 (\d+) 字/)
  const rangeMatch = text.match(/第 (\d+)-(\d+) 镜/)
  const shotMatch = text.match(/正在第 (\d+) 镜/)
  const range = rangeMatch ? [Number(rangeMatch[1]), Number(rangeMatch[2])] as [number, number] : undefined
  const withStep = (title: string, index: number, total: number): StoryboardPolishPhase => ({
    title, episode, index, total, range, currentShot: shotMatch ? Number(shotMatch[1]) : undefined,
    chars: charsMatch ? Number(charsMatch[1]) : undefined,
  })
  const writing = text.match(/^正在写分镜 \((\d+)\/(\d+)\)/)
  if (writing && hasEpisodePrefix) return withStep("写分镜", Number(writing[1]), Number(writing[2]))
  const reading = text.match(/^正在读剧本并构思 \((\d+)\/(\d+)\)/)
  if (reading) return withStep("阅读剧本并构思", Number(reading[1]), Number(reading[2]))
  const rewrite = text.match(/^镜头不完整，正在重拆 \((\d+)\/(\d+)\)/)
  if (rewrite) return withStep("重拆不完整镜头", Number(rewrite[1]), Number(rewrite[2]))
  const timing = text.match(/^正在按秒分配对白与动作 \((\d+)\/(\d+)\)/)
  if (timing) return withStep("按秒分配对白与动作", Number(timing[1]), Number(timing[2]))
  const continuity = text.match(/^正在校验镜头衔接 \((\d+)\/(\d+)\)/)
  if (continuity) return withStep("校验镜头衔接", Number(continuity[1]), Number(continuity[2]))
  const misc = text.match(/^(正在整理镜头|正在从剧本补全对白|正在修复镜头因果衔接|正在拆分分集)/)
  if (misc) return { title: misc[1], episode, chars: charsMatch ? Number(charsMatch[1]) : undefined }
  return null
}

export function resolvePolishCurrentShot(
  phase: StoryboardPolishPhase,
  polishLive?: { ordinal: number } | null,
): number | undefined {
  if (phase.currentShot != null) return phase.currentShot
  if (phase.range?.[0] != null) return phase.range[0] + (polishLive?.ordinal ?? 0)
  return undefined
}

export function polishPhaseTitle(phase: StoryboardPolishPhase): string {
  const episode = phase.episode ? `第 ${phase.episode} 集 · ` : ""
  const batch = phase.total && phase.total > 1 && phase.index ? ` · 第 ${phase.index}/${phase.total} 批` : ""
  return `${episode}${phase.title}${batch}`
}

export function shotDisplayNumber(shot: Record<string, unknown>, fallback: number): number {
  const raw = shot.shotNumber ?? shot.shot_number
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export function groupPolishShotNumbers(episodes: Array<{ number: number; shots: Array<Record<string, unknown>> }>): StoryboardPolishShotGroup[] {
  return episodes.flatMap((episode) => {
    const numbers: number[] = []
    const seen = new Set<number>()
    let next = 1
    for (const shot of episode.shots) {
      const no = shotDisplayNumber(shot, 0)
      const value = no > 0 ? no : next
      next = Math.max(next, value) + 1
      if (seen.has(value)) continue
      seen.add(value)
      numbers.push(value)
    }
    if (!numbers.length) return []
    return [{ episode: episode.number, label: `第 ${episode.number} 集`, numbers }]
  })
}

export function polishShotLegend(phase: StoryboardPolishPhase, groups: StoryboardPolishShotGroup[]): string {
  const totalShots = groups.reduce((sum, group) => sum + group.numbers.length, 0)
  const episodeCount = groups.length
  const parts: string[] = []
  if (episodeCount > 1) parts.push(`全剧 ${episodeCount} 集`)
  parts.push(`共 ${totalShots} 镜`)
  if (phase.episode) parts.push(`当前第 ${phase.episode} 集`)
  if (phase.range) parts.push(`正在打磨第 ${phase.range[0]}–${phase.range[1]} 镜`)
  return parts.join(" · ")
}

export type StoryboardStreamItem = Record<string, unknown>
export type StoryboardStreamInput = {
  shownTexts: Record<string, string>
  targetTexts?: Record<string, string>
  streamItems: Record<string, StoryboardStreamItem>
  activeIndex?: Record<string, number>
  message?: string
  live?: boolean
  recipe?: { episodes?: unknown[]; scenes?: unknown[] } | null
}
export type StoryboardShotView = StoryboardStreamItem & { index: number; episode: number; episodeTitle?: string; title?: string; description?: string; dialogue?: string; active?: boolean; draining?: boolean }
export type StoryboardSceneView = StoryboardStreamItem & { index: number; episode: number; episodeTitle?: string; title?: string }
export type StoryboardEpisodeView = { number: number; title: string; scenes: StoryboardSceneView[]; shots: StoryboardShotView[] }
export type StoryboardStreamModel = { episodes: StoryboardEpisodeView[]; polish: StoryboardPolishPhase | null; polishLive?: { ordinal: number; description: string; dialogue: string }; activeShot?: number; activeScene?: number }
export type StoryboardEpisodeRowStatus = "running" | "completed" | "pending"

export function shotDurationLabel(shot: Record<string, unknown>): string {
  const raw = shot.durationSec ?? shot.duration_sec ?? shot.duration
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed <= 0) return ""
  const label = Number.isInteger(parsed) ? String(parsed) : String(Math.round(parsed * 10) / 10)
  return `${label}s`
}

export function episodeShotCountLabel(count: number): string {
  return `${count} 镜`
}

/** 直播时默认展开的那一集：当前镜所在集 → 打磨文案里的集（该集已有镜头）→ 最新已有镜头的集。审片/完成后返回 undefined。 */
export function resolveActiveEpisodeNumber(
  episodes: StoryboardEpisodeView[],
  input: { live: boolean; polish?: StoryboardPolishPhase | null },
): number | undefined {
  if (!input.live) return undefined
  const withActive = episodes.find((episode) => episode.shots.some((shot) => shot.active))
  if (withActive) return withActive.number
  if (input.polish?.episode) {
    const target = episodes.find((episode) => episode.number === input.polish?.episode)
    if (target?.shots.length) return target.number
  }
  return [...episodes].reverse().find((episode) => episode.shots.length)?.number
}

export function resolveEpisodeRowStatus(
  episode: StoryboardEpisodeView,
  activeEpisode?: number,
): StoryboardEpisodeRowStatus {
  if (activeEpisode === episode.number) return "running"
  if (episode.shots.length) return "completed"
  return "pending"
}

export function resolvePolishGroupStatus(
  group: StoryboardPolishShotGroup,
  currentShot?: number,
  range?: [number, number],
): StoryboardEpisodeRowStatus {
  const first = group.numbers[0]
  const last = group.numbers[group.numbers.length - 1]
  if (first == null || last == null) return "pending"
  if (currentShot != null) {
    if (currentShot > last) return "completed"
    if (currentShot >= first) return "running"
    return "pending"
  }
  if (range) {
    if (range[0] > last) return "completed"
    if (range[1] >= first) return "running"
    return "pending"
  }
  return "pending"
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function recipeOutline(recipe?: StoryboardStreamInput["recipe"]): Array<{ num: number; title: string; targetShots: number }> {
  if (!Array.isArray(recipe?.episodes)) return []
  return recipe.episodes.flatMap((item, index) => {
    const source = asRecord(item)
    if (!source) return []
    const num = number(source.num ?? source.number ?? source.episode_num ?? source.episodeNumber ?? source.episode, index + 1)
    const targetShots = number(source.targetShots ?? source.target_shots ?? source.shots_count ?? source.shotsCount, 0)
    return [{ num, title: text(source.title || source.name) || `第 ${num} 集`, targetShots }]
  })
}

function recipeShotRows(recipe?: StoryboardStreamInput["recipe"]): Array<{ ep: number; title: string; shot: Record<string, unknown>; index: number }> {
  if (!Array.isArray(recipe?.scenes)) return []
  const rows: Array<{ ep: number; title: string; shot: Record<string, unknown>; index: number }> = []
  let index = 0
  for (const scene of recipe.scenes) {
    const source = asRecord(scene)
    if (!source) continue
    const sceneEp = number(source.episodeNumber ?? source.episode, 0)
    const shots = Array.isArray(source.shots) ? source.shots : []
    for (const shot of shots) {
      const item = asRecord(shot)
      if (!item) continue
      const ep = number(item.episodeNumber ?? item.episode, sceneEp || 1)
      rows.push({ ep, title: text(item.episodeTitle || item.episode_title), shot: item, index: index++ })
    }
  }
  return rows
}

function splitUntaggedShots<T extends { ep: number }>(rows: T[], outlines: Array<{ num: number; targetShots: number }>): T[] {
  if (outlines.length <= 1 || rows.length <= 1) return rows
  if (new Set(rows.map((row) => row.ep)).size > 1) return rows
  const sizes = outlines.map((outline) => (
    outline.targetShots > 0 ? outline.targetShots : Math.ceil(rows.length / outlines.length)
  ))
  const next = rows.map((row) => ({ ...row }))
  let cursor = 0
  outlines.forEach((outline, index) => {
    const take = index === outlines.length - 1 ? next.length - cursor : sizes[index]
    for (let count = 0; count < take && cursor < next.length; count += 1, cursor += 1) {
      next[cursor] = { ...next[cursor], ep: outline.num }
    }
  })
  return next
}

const text = (value: unknown): string => typeof value === "string" ? value : value == null ? "" : String(value)
const number = (value: unknown, fallback = 1): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function itemKeyParts(key: string): { agent: string; field: string; index: number; episode?: number } | null {
  const parts = key.split("|")
  if (parts.length < 3) return null
  const offset = parts.length >= 4 ? 1 : 0
  const index = Number(parts[2 + offset])
  return { agent: parts[offset], field: parts[1 + offset], index: Number.isFinite(index) ? index : 0, episode: parts[3 + offset] ? number(parts[3 + offset]) : undefined }
}

export function buildStoryboardStreamModel(input: StoryboardStreamInput): StoryboardStreamModel {
  const { shownTexts, targetTexts = {}, streamItems, activeIndex = {}, message, live = true } = input
  const episodesMap = new Map<number, StoryboardEpisodeView>()
  const ensureEpisode = (ep: number, title = "") => {
    const existing = episodesMap.get(ep)
    if (existing) { if (title && (!existing.title || existing.title === `第 ${ep} 集`)) existing.title = title; return existing }
    const created = { number: ep, title: title || `第 ${ep} 集`, scenes: [], shots: [] }
    episodesMap.set(ep, created); return created
  }
  for (const [key, item] of Object.entries(streamItems)) {
    const parts = itemKeyParts(key)
    if (!parts) continue
    if (parts.agent === "episodes") {
      const ep = number(item.number ?? item.episodeNumber ?? parts.index + 1, parts.index + 1)
      ensureEpisode(ep, text(item.title || item.name || item.heading) || `第 ${ep} 集`)
      continue
    }
    if (parts.agent !== "storyboard") continue
    const ep = number(item.episodeNumber ?? item.episode ?? parts.episode, 1)
    const episodeTitle = text(item.episodeTitle || item.episode_title)
    const episode = ensureEpisode(ep, episodeTitle)
    if (parts.field === "scenes") episode.scenes.push({ ...item, index: parts.index, episode: ep, episodeTitle, title: text(item.title || item.name) })
    if (parts.field === "shots") episode.shots.push({ ...item, index: parts.index, episode: ep, episodeTitle, title: text(item.title), description: text(item.description), dialogue: text(item.dialogue) })
  }
  // Delta-only scenes/shots are represented as an active tail so the user sees skeleton/text before JSON closes.
  const shotOrdinals = Object.keys({ ...targetTexts, ...shownTexts }).flatMap((key) => {
    const parts = itemKeyParts(key); return parts && parts.agent === "storyboard" && ["title", "description", "dialogue"].includes(parts.field) ? [parts.index] : []
  })
  const activeShot = [activeIndex["storyboard|title"], activeIndex["storyboard|description"], activeIndex["storyboard|dialogue"], ...shotOrdinals].filter((v): v is number => Number.isFinite(v)).reduce<number | undefined>((max, v) => max === undefined || v > max ? v : max, undefined)
  if (live && activeShot !== undefined) {
    const activePart = Object.keys({ ...targetTexts, ...shownTexts }).map(itemKeyParts).find((part) => part && part.agent === "storyboard" && part.index === activeShot)
    const ep = activePart?.episode || 1
    const episode = ensureEpisode(ep)
    const findText = (source: Record<string, string>, field: string) => {
      const exact = source[`storyboard|storyboard|${field}|${activeShot}`] || source[`storyboard|${field}|${activeShot}`]
      if (exact) return exact
      const prefix = `storyboard|storyboard|${field}|${activeShot}|`
      const match = Object.entries(source).find(([key]) => key.startsWith(prefix))
      return match?.[1] || ""
    }
    const get = (field: string) => findText(shownTexts, field)
    const goal = (field: string) => findText(targetTexts, field)
    const existing = episode.shots.find((shot) => shot.index === activeShot)
    if (!existing) episode.shots.push({ index: activeShot, episode: ep, title: get("title"), description: get("description"), dialogue: get("dialogue"), active: true, draining: get("title") !== goal("title") || get("description") !== goal("description") || get("dialogue") !== goal("dialogue") })
    else { existing.active = true; existing.draining = true }
  }
  const outlines = recipeOutline(input.recipe)
  for (const outline of outlines) ensureEpisode(outline.num, outline.title)
  const taggedRecipeShots = splitUntaggedShots(recipeShotRows(input.recipe), outlines)
  if (taggedRecipeShots.length) {
    const liveByNumber = new Map<number, StoryboardShotView>()
    for (const episode of episodesMap.values()) {
      for (const shot of episode.shots) liveByNumber.set(shotDisplayNumber(shot, shot.index + 1), shot)
    }
    for (const episode of episodesMap.values()) episode.shots = []
    for (const row of taggedRecipeShots) {
      const episode = ensureEpisode(row.ep, row.title)
      const seriesNo = shotDisplayNumber(row.shot, row.index + 1)
      const live = liveByNumber.get(seriesNo)
      episode.shots.push({
        ...row.shot,
        index: row.index,
        episode: row.ep,
        episodeTitle: row.title,
        title: text(row.shot.title) || live?.title,
        description: text(row.shot.description) || live?.description,
        dialogue: text(row.shot.dialogue) || live?.dialogue,
        active: live?.active,
        draining: live?.draining,
      })
    }
    for (const live of liveByNumber.values()) {
      if (!live.active) continue
      const episode = ensureEpisode(live.episode)
      if (!episode.shots.some((shot) => shot.active || shotDisplayNumber(shot, shot.index + 1) === shotDisplayNumber(live, live.index + 1))) {
        episode.shots.push(live)
      }
    }
  }
  for (const episode of episodesMap.values()) {
    episode.scenes.sort((a, b) => a.index - b.index)
    episode.shots.sort((a, b) => a.index - b.index)
  }
  const polish = parseStoryboardPhase(message)
  let polishLive: StoryboardStreamModel["polishLive"]
  const polishKeys = Object.keys({ ...targetTexts, ...shownTexts }).map(itemKeyParts).filter(Boolean) as Array<{ agent: string; field: string; index: number }>
  const polishOrdinals = polishKeys.filter((part) => part.agent === "storyboard_polish" && ["description", "dialogue"].includes(part.field)).map((part) => part.index)
  if (polishOrdinals.length) {
    const ordinal = Math.max(...polishOrdinals)
    polishLive = { ordinal, description: shownTexts[`storyboard_polish|description|${ordinal}`] || "", dialogue: shownTexts[`storyboard_polish|dialogue|${ordinal}`] || "" }
  }
  return { episodes: [...episodesMap.values()].sort((a, b) => a.number - b.number), polish, polishLive, activeShot, activeScene: activeIndex["storyboard|scenes"] }
}
