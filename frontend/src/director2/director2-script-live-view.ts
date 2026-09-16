export type ScriptShotField = {
  label: string
  value: string
}

export type ScriptLiveBlock =
  | { type: "title"; text: string }
  | { type: "heading"; text: string }
  | { type: "episode"; text: string }
  | { type: "plot"; text: string }
  | { type: "shot"; heading: string; fields: ScriptShotField[] }
  | { type: "paragraph"; text: string }
  | { type: "blank" }

export type ScriptLiveSource = {
  title: string
  summary: string
  fullStory: string
}

const EPISODE_HEADING = /^#\s*第\s*[0-9一二三四五六七八九十百]+\s*集/
const SHOT_HEADING = /^#{1,3}\s*镜头/
const TITLE_HEADING = /^#\s+(?!第\s*[0-9一二三四五六七八九十百]+\s*集)/
const SECTION_HEADING = /^#{2,3}\s+/
const PLOT_LINE = /^(?:\*\*)?剧情[：:](?:\*\*)?\s*(.*)$/
const FIELD_LINE = /^[-*]\s*(人物|场景|道具|时长|动作|镜头|运镜|台词|对白|音效|字幕|提示词)[：:]\s*(.*)$/
const BARE_FIELD_LINE = /^(人物|场景|道具|时长|动作|镜头|运镜|台词|对白|音效|字幕|提示词)[：:]\s*(.*)$/
const SCENE_HEADER = /^【([^】]+)】\s*(.*)$/
const BEAT_HEAD = /^Beat\s*(\d+)\s*[：:.．]?\s*(.*)$/i
const BEAT_ANY = /^Beat\s*\d+/im
const DIALOGUE_HEAD = /^对白[：:]\s*(.*)$/
const ANCHOR_HEAD = /^视觉锚点[：:]\s*(.*)$/
const STRUCTURAL_TOKEN = /【[^】\n]{1,40}】|Beat\s*\d+|#{1,3}\s*镜头|#\s*第\s*[0-9一二三四五六七八九十百]+\s*集|#{1,2}\s*视频定位|#{1,3}\s*(?:一[、.])?\s*主要人物固定设定|\*\*剧情[：:]\*\*|视觉锚点[：:]|对白[：:]|[-*]\s*(?:人物|场景|道具|时长|动作|镜头|运镜|台词|音效|字幕|提示词)[：:]/gi
const INLINE_FIELD = /(人物|场景|道具|时长|动作|镜头|运镜|台词|对白|音效|字幕)[：:]/g
const HIDDEN_SHOT_LABELS = new Set(["提示词", "prompt", "prompttext"])

function textValue(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function stripHeadingMarks(line: string): string {
  return line.replace(/^#{1,6}\s+/, "").replace(/^\*\*(.+?)\*\*$/g, "$1").trim()
}

function titlesMatch(left: string, right: string): boolean {
  const normalize = (value: string) => value.replace(/[#《》\s]/g, "")
  return Boolean(left && right && normalize(left) === normalize(right))
}

function insertStructuralNewlines(text: string): string {
  let out = ""
  let last = 0
  for (const match of text.matchAll(STRUCTURAL_TOKEN)) {
    const index = match.index ?? 0
    out += text.slice(last, index)
    if (out.length > 0 && !out.endsWith("\n")) out += "\n"
    out += match[0]
    last = index + match[0].length
  }
  return out + text.slice(last)
}

function isBlockBoundary(line: string): boolean {
  return Boolean(
    SCENE_HEADER.test(line)
    || BEAT_HEAD.test(line)
    || SHOT_HEADING.test(line)
    || ANCHOR_HEAD.test(line)
    || EPISODE_HEADING.test(line)
    || TITLE_HEADING.test(line)
    || SECTION_HEADING.test(line)
    || FIELD_LINE.test(line)
    || PLOT_LINE.test(line),
  )
}

function consumeDialogue(lines: string[], start: number): { collected: string[]; next: number } {
  const collected: string[] = []
  let index = start
  while (index < lines.length) {
    const nxt = lines[index].trim()
    const match = DIALOGUE_HEAD.exec(nxt)
    if (!match) break
    if (match[1].trim()) collected.push(match[1].trim())
    index += 1
    while (index < lines.length) {
      const follow = lines[index].trim()
      if (!follow) break
      if (DIALOGUE_HEAD.test(follow) || isBlockBoundary(follow)) break
      collected.push(follow)
      index += 1
    }
    while (index < lines.length && !lines[index].trim()) index += 1
  }
  return { collected, next: index }
}

function convertBeatsToShots(text: string): string {
  const lines = text.split("\n")
  const out: string[] = []
  let currentScene = ""
  let pendingAnchor = ""
  let index = 0
  while (index < lines.length) {
    const raw = lines[index]
    const line = raw.trim()
    if (!line) {
      if (out.length && out[out.length - 1] !== "") out.push("")
      index += 1
      continue
    }

    const sceneMatch = SCENE_HEADER.exec(line)
    if (sceneMatch) {
      currentScene = sceneMatch[1].trim()
      const rest = sceneMatch[2].trim()
      if (rest) {
        lines[index] = rest
        continue
      }
      index += 1
      continue
    }

    const anchorMatch = ANCHOR_HEAD.exec(line)
    if (anchorMatch) {
      pendingAnchor = anchorMatch[1].trim()
      index += 1
      continue
    }

    const beatMatch = BEAT_HEAD.exec(line)
    if (beatMatch) {
      const number = beatMatch[1]
      const action = beatMatch[2].trim()
      index += 1
      while (index < lines.length && !lines[index].trim()) index += 1
      const { collected, next } = consumeDialogue(lines, index)
      index = next
      const sceneLabel = currentScene || "场景"
      out.push(`### 镜头${number}｜${sceneLabel}`)
      const sceneParts = [currentScene, pendingAnchor].filter(Boolean)
      pendingAnchor = ""
      if (sceneParts.length) out.push(`- 场景：${sceneParts.join("。")}`)
      if (action) out.push(`- 动作：${action}`)
      for (const item of collected) out.push(`- 台词：${item}`)
      out.push("")
      continue
    }

    const leftover = DIALOGUE_HEAD.exec(line)
    if (leftover) {
      if (leftover[1].trim()) out.push(`- 台词：${leftover[1].trim()}`)
      index += 1
      continue
    }

    out.push(raw.replace(/\s+$/g, ""))
    index += 1
  }
  return out.join("\n")
}

function collapseBlankLines(text: string): string {
  return text.replace(/\n{3,}/g, "\n\n").trim()
}

export function normalizeScriptLiveText(text: string): string {
  const raw = (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim()
  if (!raw) return raw
  let spaced = insertStructuralNewlines(raw)
  if (BEAT_ANY.test(spaced)) spaced = convertBeatsToShots(spaced)
  return collapseBlankLines(spaced)
}

function parseInlineFields(line: string): ScriptShotField[] {
  const matches = [...line.matchAll(INLINE_FIELD)]
  if (!matches.length) return line.trim() ? [{ label: "动作", value: line.trim() }] : []
  const fields: ScriptShotField[] = []
  matches.forEach((match, index) => {
    const label = match[1]
    const valueStart = (match.index ?? 0) + match[0].length
    const valueEnd = index + 1 < matches.length ? (matches[index + 1].index ?? line.length) : line.length
    const value = line.slice(valueStart, valueEnd).replace(/[；;]\s*$/g, "").trim()
    if (value) fields.push({ label, value })
  })
  return fields
}

function pushField(fields: ScriptShotField[], label: string, value: string) {
  const trimmed = value.trim()
  if (!trimmed) return
  const mapped = label === "对白" ? "台词" : label
  fields.push({ label: mapped, value: trimmed })
}

function parseShotFields(lines: string[], start: number): { fields: ScriptShotField[]; next: number } {
  const fields: ScriptShotField[] = []
  let index = start
  while (index < lines.length) {
    const line = lines[index].trim()
    if (!line) {
      index += 1
      if (index < lines.length && isStructuralHeading(lines[index].trim())) break
      continue
    }
    if (isStructuralHeading(line)) break
    const listed = FIELD_LINE.exec(line)
    if (listed) {
      pushField(fields, listed[1], listed[2])
      index += 1
      continue
    }
    const bare = BARE_FIELD_LINE.exec(line)
    if (bare) {
      pushField(fields, bare[1], bare[2])
      index += 1
      continue
    }
    parseInlineFields(line).forEach((field) => pushField(fields, field.label, field.value))
    index += 1
  }
  return { fields, next: index }
}

function isStructuralHeading(line: string): boolean {
  return Boolean(
    EPISODE_HEADING.test(line)
    || SHOT_HEADING.test(line)
    || TITLE_HEADING.test(line)
    || SECTION_HEADING.test(line)
    || PLOT_LINE.test(line)
    || SCENE_HEADER.test(line)
    || BEAT_HEAD.test(line),
  )
}

function dropLeadingBlanks(blocks: ScriptLiveBlock[]) {
  while (blocks[0]?.type === "blank") blocks.shift()
}

export function parseScriptLiveView(text: string, options?: { skipTitle?: string }): ScriptLiveBlock[] {
  const normalized = normalizeScriptLiveText(text)
  if (!normalized) return []
  const lines = normalized.split("\n")
  const blocks: ScriptLiveBlock[] = []
  let index = 0
  while (index < lines.length) {
    const raw = lines[index]
    const line = raw.trim()
    if (!line) {
      if (blocks.length && blocks[blocks.length - 1]?.type !== "blank") blocks.push({ type: "blank" })
      index += 1
      continue
    }

    if (EPISODE_HEADING.test(line)) {
      blocks.push({ type: "episode", text: stripHeadingMarks(line) })
      index += 1
      continue
    }
    if (SHOT_HEADING.test(line)) {
      const heading = stripHeadingMarks(line)
      index += 1
      const parsed = parseShotFields(lines, index)
      blocks.push({ type: "shot", heading, fields: parsed.fields })
      index = parsed.next
      continue
    }
    if (TITLE_HEADING.test(line)) {
      blocks.push({ type: "title", text: stripHeadingMarks(line) })
      index += 1
      continue
    }
    if (SECTION_HEADING.test(line)) {
      blocks.push({ type: "heading", text: stripHeadingMarks(line) })
      index += 1
      continue
    }
    const plot = PLOT_LINE.exec(line.replace(/\*\*/g, ""))
    if (plot && (line.includes("剧情") && (line.includes("**") || /^剧情[：:]/.test(line)))) {
      const body = plot[1].trim()
      blocks.push({ type: "plot", text: body ? `剧情：${body}` : "剧情" })
      index += 1
      continue
    }
    if (SCENE_HEADER.test(line)) {
      blocks.push({ type: "heading", text: line })
      index += 1
      continue
    }
    blocks.push({ type: "paragraph", text: line })
    index += 1
  }

  dropLeadingBlanks(blocks)
  while (blocks[blocks.length - 1]?.type === "blank") blocks.pop()
  const skipTitle = options?.skipTitle?.trim()
  if (skipTitle && blocks[0]?.type === "title" && titlesMatch(blocks[0].text, skipTitle)) {
    blocks.shift()
  }
  dropLeadingBlanks(blocks)
  return blocks
}

export function visibleShotFields(fields: ScriptShotField[]): ScriptShotField[] {
  return fields.filter((field) => !HIDDEN_SHOT_LABELS.has(field.label.toLowerCase()))
}

export type ScriptLiveEpisodeGroup = {
  title: string
  blocks: ScriptLiveBlock[]
  shotCount: number
  /** 1-based display order for the capsule badge; prefers 「第N集」 when present. */
  number: number
}

export type ScriptLiveGroupedView = {
  preamble: ScriptLiveBlock[]
  episodes: ScriptLiveEpisodeGroup[]
}

const EPISODE_NUMBER = /第\s*([0-9一二三四五六七八九十百]+)\s*集/

function chineseEpisodeNumber(token: string): number | undefined {
  if (/^\d+$/.test(token)) return Number(token)
  const map: Record<string, number> = {
    一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
  }
  if (token in map) return map[token]
  if (token.startsWith("十") && token.length <= 2) {
    const ones = token.length === 1 ? 0 : map[token[1]]
    return ones === undefined ? undefined : 10 + ones
  }
  if (token.endsWith("十") && token.length === 2) {
    const tens = map[token[0]]
    return tens === undefined ? undefined : tens * 10
  }
  return undefined
}

export function scriptEpisodeNumber(title: string, fallback: number): number {
  const match = EPISODE_NUMBER.exec(title)
  if (!match) return fallback
  return chineseEpisodeNumber(match[1]) ?? fallback
}

function trimEpisodeBlocks(blocks: ScriptLiveBlock[]): ScriptLiveBlock[] {
  const next = [...blocks]
  dropLeadingBlanks(next)
  while (next[next.length - 1]?.type === "blank") next.pop()
  return next
}

/** Split parsed manuscript blocks into a sticky preamble + per-episode groups for capsule UI. */
export function groupScriptLiveView(blocks: ScriptLiveBlock[]): ScriptLiveGroupedView {
  const preamble: ScriptLiveBlock[] = []
  const episodes: ScriptLiveEpisodeGroup[] = []
  let current: ScriptLiveEpisodeGroup | null = null

  for (const block of blocks) {
    if (block.type === "episode") {
      if (current) {
        current.blocks = trimEpisodeBlocks(current.blocks)
        episodes.push(current)
      }
      const order = episodes.length + 1
      current = {
        title: block.text,
        blocks: [],
        shotCount: 0,
        number: scriptEpisodeNumber(block.text, order),
      }
      continue
    }
    if (!current) {
      preamble.push(block)
      continue
    }
    current.blocks.push(block)
    if (block.type === "shot") current.shotCount += 1
  }

  if (current) {
    current.blocks = trimEpisodeBlocks(current.blocks)
    episodes.push(current)
  }

  return {
    preamble: trimEpisodeBlocks(preamble),
    episodes,
  }
}

export function extractScriptShownTexts(shownTexts: Record<string, string>): ScriptLiveSource {
  const result: ScriptLiveSource = { title: "", summary: "", fullStory: "" }
  for (const [key, value] of Object.entries(shownTexts)) {
    if (!key.startsWith("script|") || !value) continue
    const field = key.split("|")[2]
    if (field === "title" || field === "summary" || field === "fullStory") {
      if (value.length >= result[field].length) result[field] = value
    }
  }
  return result
}

export function resolveDirector2ScriptLiveSource(input: {
  shownTexts: Record<string, string>
  recipe?: Record<string, unknown> | null
}): ScriptLiveSource {
  const live = extractScriptShownTexts(input.shownTexts)
  const script = asRecord(input.recipe?.script)
  return {
    title: live.title || textValue(script?.title).trim(),
    summary: live.summary || textValue(script?.summary).trim(),
    fullStory: live.fullStory || textValue(script?.fullStory).trim(),
  }
}

export function scriptLiveSourceHasContent(source: ScriptLiveSource): boolean {
  return Boolean(source.title.trim() || source.summary.trim() || source.fullStory.trim())
}
