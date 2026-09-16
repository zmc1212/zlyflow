import type { Director2AiOperation, Director2AiStage, Director2ClarificationQuestion } from "./api"

export const DIRECTOR2_EPISODE_COUNT_QUESTION: Director2ClarificationQuestion = {
  id: "episode_count",
  question: "这部剧分多少集？",
  why: "分集决定叙事节奏：多集时每集是相对独立的故事段落，集尾留钩子，分镜会按集逐集生成。",
  options: [
    { label: "1 集 · 单集成片", value: "1", recommended: true },
    { label: "3 集 · 连载短剧", value: "3" },
    { label: "6 集 · 系列短剧", value: "6" },
    { label: "12 集 · 完整系列", value: "12" },
  ],
  allowCustom: true,
}

export const DIRECTOR2_SHOTS_PER_EPISODE_QUESTION: Director2ClarificationQuestion = {
  id: "shots_per_episode",
  question: "每一集默认拍多少个镜头？",
  why: "每集镜头数决定单集节奏与成片时长：每个镜头约 3-8 秒，确认后剧本、分集和分镜都会按这个默认值拆写。",
  options: [
    { label: "4 个镜头 · 更紧凑", value: "4" },
    { label: "6 个镜头 · 推荐单集节奏", value: "6", recommended: true },
    { label: "8 个镜头 · 稍铺陈", value: "8" },
    { label: "12 个镜头 · 单集更完整", value: "12" },
  ],
  allowCustom: true,
}

export function ensureDirector2OpeningQuestions(
  questions: Director2ClarificationQuestion[] | null | undefined,
): Director2ClarificationQuestion[] {
  const items = (questions || []).filter((item) => item && item.id !== "beat_count")
  const ids = new Set(items.map((item) => String(item.id || "")))
  if (!ids.has("episode_count")) items.push(DIRECTOR2_EPISODE_COUNT_QUESTION)
  if (!ids.has("shots_per_episode")) items.push(DIRECTOR2_SHOTS_PER_EPISODE_QUESTION)
  return items
}

export type Director2StageChoice = {
  id?: string
  question: string
  answer: string
}

export type Director2StageChoiceFallback = "skipped"

export type Director2StageChoiceEcho = {
  items: Director2StageChoice[]
  fallback: Director2StageChoiceFallback | null
}

export const DIRECTOR2_STAGE_CHOICE_FALLBACK: Record<Director2StageChoiceFallback, string> = {
  skipped: "已跳过，沿用默认",
}

/** 集数 / Beat / 每集镜头数的 value 是给 Agent 用的纯数字，回显要用中文档位。 */
const KNOWN_SCALE_LABELS: Record<string, Record<string, string>> = {
  episode_count: {
    "1": "1 集 · 单集成片",
    "3": "3 集 · 连载短剧",
    "6": "6 集 · 系列短剧",
    "12": "12 集 · 完整系列",
  },
  beat_count: {
    "8": "约 8 个镜头 · 1 分钟内",
    "16": "约 16 个镜头 · 1-2 分钟",
    "30": "约 30 个镜头 · 3 分钟左右",
    "50": "约 50 个镜头 · 完整短剧",
  },
  shots_per_episode: {
    "4": "4 个镜头 · 更紧凑",
    "6": "6 个镜头 · 推荐单集节奏",
    "8": "8 个镜头 · 稍铺陈",
    "12": "12 个镜头 · 单集更完整",
  },
}

export function choiceEchoLabel(item: Director2StageChoice): string {
  return `${item.question} → ${item.answer}`
}

function questionCatalog(operation: Pick<Director2AiOperation, "request"> | null | undefined): Director2ClarificationQuestion[] {
  const raw = operation?.request?.clarify_questions
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is Director2ClarificationQuestion => Boolean(item && typeof item === "object"))
}

function displayAnswer(
  record: Record<string, unknown>,
  questions: Director2ClarificationQuestion[],
): string {
  const value = String(record.answer || record.value || "").trim()
  const stored = String(record.label || "").trim()
  if (stored) return stored
  const id = record.id == null || record.id === "" ? "" : String(record.id)
  if (id && KNOWN_SCALE_LABELS[id]?.[value]) return KNOWN_SCALE_LABELS[id][value]
  const questionText = String(record.question || "").trim()
  const catalog = questions.find((item) => item.id === id || item.question === questionText)
  const option = (catalog?.options || []).find((item) => item.value === value)
  if (option?.label?.trim()) return option.label.trim()
  return value
}

export function normalizeStageChoices(
  raw: unknown,
  questions: Director2ClarificationQuestion[] = [],
): Director2StageChoice[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const items: Director2StageChoice[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue
    const record = entry as Record<string, unknown>
    const question = String(record.question || "").trim()
    const answer = displayAnswer(record, questions)
    if (!question || !answer) continue
    const key = `${question}\0${answer}`
    if (seen.has(key)) continue
    seen.add(key)
    const id = record.id == null || record.id === "" ? undefined : String(record.id)
    items.push(id ? { id, question, answer } : { question, answer })
  }
  return items
}

/** 开机确认题会注入后续每一腿；回显时按题意挂到真正受影响的步骤。 */
export function choiceDestinationStage(item: Pick<Director2StageChoice, "id" | "question">): Director2AiStage {
  const id = String(item.id || "")
  const question = String(item.question || "")
  if (id === "episode_count" || /分多少集|几集|集数/.test(question)) return "episodes"
  if (id === "beat_count" || id === "shots_per_episode" || /拍多少个镜头|每一集默认拍多少|Beat/.test(question)) {
    return "storyboard"
  }
  if (/结局|基调|悬念|叙事|冲突升级|视角|时空/.test(question)) return "script"
  if (/角色|主角|人物|道具|场景|气质|动机/.test(question)) return "assets"
  return "script"
}

function mergeChoices(inherited: Director2StageChoice[], own: Director2StageChoice[]): Director2StageChoice[] {
  const byQuestion = new Map<string, Director2StageChoice>()
  for (const item of inherited) byQuestion.set(item.question, item)
  for (const item of own) byQuestion.set(item.question, item)
  return [...byQuestion.values()]
}

function openingChoices(
  operation: Pick<Director2AiOperation, "request"> | null | undefined,
): Director2StageChoice[] {
  if (!operation) return []
  return normalizeStageChoices(operation.request?.clarifications, questionCatalog(operation))
}

function ownStageChoices(
  operation: Pick<Director2AiOperation, "request" | "stage_clarifications"> | null | undefined,
  stage: Director2AiStage,
): { items: Director2StageChoice[]; skipped: boolean } {
  if (!operation || stage === "clarify") return { items: [], skipped: false }
  const store = operation.stage_clarifications
  const raw = store && typeof store === "object" ? store[stage] : undefined
  const items = normalizeStageChoices(raw, questionCatalog(operation))
  return { items, skipped: Array.isArray(raw) && items.length === 0 }
}

export function stageChoiceEcho(
  operation: Pick<Director2AiOperation, "request" | "stage_clarifications"> | null | undefined,
  stage: Director2AiStage,
): Director2StageChoiceEcho {
  const opening = openingChoices(operation)
  if (stage === "clarify") {
    if (opening.length) return { items: opening, fallback: null }
    if (Array.isArray(operation?.request?.clarifications)) return { items: [], fallback: "skipped" }
    return { items: [], fallback: null }
  }
  const own = ownStageChoices(operation, stage)
  const inherited = opening.filter((item) => choiceDestinationStage(item) === stage)
  const items = mergeChoices(inherited, own.items)
  if (items.length) return { items, fallback: null }
  if (own.skipped && !inherited.length) return { items: [], fallback: "skipped" }
  return { items: [], fallback: null }
}

export function stageChoiceFallbackLabel(echo: Director2StageChoiceEcho): string | undefined {
  if (echo.items.length || !echo.fallback) return undefined
  return DIRECTOR2_STAGE_CHOICE_FALLBACK[echo.fallback]
}

export function stageChoicePreviewAnswer(
  operation: Pick<Director2AiOperation, "request" | "stage_clarifications"> | null | undefined,
  stage: Director2AiStage,
): string | null {
  const items = stageChoiceEcho(operation, stage).items
  const preferred = items.find((item) => item.id === "episode_count") || items[0]
  return preferred?.answer || null
}

export const DIRECTOR2_CHOICE_STAGE_ORDER: Director2AiStage[] = [
  "clarify",
  "script",
  "assets",
  "episodes",
  "storyboard",
]

export type Director2StageChoicePathGroup = {
  stage: Director2AiStage
  items: Director2StageChoice[]
}

/** 记录流顶部「创作路径」：按选项真正影响的步骤分组，不在创意确认重复堆一遍。 */
export function stageChoicePathGroups(
  operation: Pick<Director2AiOperation, "request" | "stage_clarifications"> | null | undefined,
): Director2StageChoicePathGroup[] {
  if (!operation) return []
  const groups: Director2StageChoicePathGroup[] = []
  for (const stage of DIRECTOR2_CHOICE_STAGE_ORDER) {
    if (stage === "clarify") continue
    const items = stageChoiceEcho(operation, stage).items
    if (items.length) groups.push({ stage, items })
  }
  return groups
}
