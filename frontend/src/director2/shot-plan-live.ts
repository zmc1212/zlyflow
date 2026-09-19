import {
  applyPromptStreamEvent,
  emptyPromptLiveState,
  type WorkshopPromptLiveState,
  type WorkshopPromptStreamEvent,
} from "./workshop-prompt-stream"

export type ShotPlanEpisodeDone = {
  episode_num: number | null
  shots: Array<Record<string, unknown>>
  shots_count: number
  shots_source: string | null
  error: string | null
}

export type ShotPlanLiveState = WorkshopPromptLiveState & {
  episodeNum: number | null
  episodeIndex: number
  episodeTotal: number
  episodesDone: ShotPlanEpisodeDone[]
  lastCompletedEpisodeNum: number | null
}

export type ShotPlanDocumentLike = {
  status?: string | null
  shot_plan_job_id?: string | null
  input_mode?: string | null
  analysis?: {
    logs?: string[] | null
    episodes?: Array<{
      episode_num?: number
      shots_source?: string | null
      shots?: Array<Record<string, unknown>> | null
    }> | null
  } | null
}

export function emptyShotPlanLiveState(jobId = ""): ShotPlanLiveState {
  return {
    ...emptyPromptLiveState(jobId),
    phase: "plan",
    message: jobId ? "正在按集规划镜头" : "",
    episodeNum: null,
    episodeIndex: 0,
    episodeTotal: 0,
    episodesDone: [],
    lastCompletedEpisodeNum: null,
  }
}

function asEpisodeNum(value: unknown): number | null {
  if (value == null || value === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function readEpisodeProgress(data: Record<string, unknown> | undefined, state: ShotPlanLiveState) {
  return {
    episodeNum: asEpisodeNum(data?.episode_num) ?? state.episodeNum,
    episodeIndex: Number(data?.episode_index ?? state.episodeIndex) || state.episodeIndex,
    episodeTotal: Number(data?.episode_total ?? state.episodeTotal) || state.episodeTotal,
  }
}

function normalizeDone(row: Record<string, unknown> | ShotPlanEpisodeDone): ShotPlanEpisodeDone {
  return {
    episode_num: asEpisodeNum(row.episode_num),
    shots: Array.isArray(row.shots) ? row.shots as Array<Record<string, unknown>> : [],
    shots_count: Number(row.shots_count || 0),
    shots_source: row.shots_source ? String(row.shots_source) : null,
    error: row.error ? String(row.error) : null,
  }
}

function upsertDone(list: ShotPlanEpisodeDone[], item: ShotPlanEpisodeDone): ShotPlanEpisodeDone[] {
  return [...list.filter((row) => row.episode_num !== item.episode_num), item]
}

export function applyShotPlanStreamEvent(
  state: ShotPlanLiveState,
  event: WorkshopPromptStreamEvent,
): ShotPlanLiveState {
  if (event.event === "keep-alive") return state
  const data = event.data as Record<string, unknown>
  const progress = readEpisodeProgress(data, state)

  if (event.event === "episode_done") {
    const done = normalizeDone(data)
    return {
      ...state,
      working: true,
      episodeNum: done.episode_num ?? progress.episodeNum,
      episodeIndex: progress.episodeIndex,
      episodeTotal: progress.episodeTotal,
      episodesDone: upsertDone(state.episodesDone, done),
      lastCompletedEpisodeNum: done.episode_num,
      reasoning: "",
      text: "",
      message: done.error
        ? `第${done.episode_num ?? "?"}集规划失败，已保留解析器镜头`
        : `第${done.episode_num ?? "?"}集已写入 ${done.shots_count || done.shots.length} 条出片镜头`,
    }
  }

  if (event.event === "done") {
    return {
      ...state,
      working: false,
      episodeNum: progress.episodeNum,
      episodeIndex: progress.episodeIndex,
      episodeTotal: progress.episodeTotal,
      message: "镜头规划完成",
    }
  }

  if (event.event === "error") {
    return {
      ...state,
      working: false,
      episodeNum: progress.episodeNum,
      episodeIndex: progress.episodeIndex,
      episodeTotal: progress.episodeTotal,
      message: String(data.message || "规划失败"),
    }
  }

  const promptState = applyPromptStreamEvent(state, event)
  return {
    ...state,
    ...promptState,
    episodeNum: progress.episodeNum,
    episodeIndex: progress.episodeIndex,
    episodeTotal: progress.episodeTotal,
    episodesDone: state.episodesDone,
    lastCompletedEpisodeNum: state.lastCompletedEpisodeNum,
  }
}

export function applyShotPlanJobSnapshot(
  state: ShotPlanLiveState,
  payload: {
    stream?: {
      phase?: string
      message?: string
      reasoning?: string
      text?: string
      episode_num?: number | null
      episode_index?: number
      episode_total?: number
    } | null
    episodes_done?: Array<Record<string, unknown>> | null
    current_episode_num?: number | null
    current_episode_index?: number
    episode_total?: number
  } | null | undefined,
): ShotPlanLiveState {
  if (!payload) return state
  const stream = payload.stream
  let next: ShotPlanLiveState = { ...state }
  if (stream) {
    const nextReasoning = String(stream.reasoning || "")
    const nextText = String(stream.text || "")
    next = {
      ...next,
      phase: String(stream.phase || next.phase),
      message: String(stream.message || next.message),
      reasoning: nextReasoning.length >= next.reasoning.length ? nextReasoning : next.reasoning,
      text: nextText.length >= next.text.length ? nextText : next.text,
      episodeNum: asEpisodeNum(stream.episode_num) ?? next.episodeNum,
      episodeIndex: Number(stream.episode_index ?? next.episodeIndex) || next.episodeIndex,
      episodeTotal: Number(stream.episode_total ?? next.episodeTotal) || next.episodeTotal,
    }
  }
  if (payload.current_episode_num != null) {
    next.episodeNum = asEpisodeNum(payload.current_episode_num) ?? next.episodeNum
  }
  if (payload.current_episode_index != null) {
    next.episodeIndex = Number(payload.current_episode_index) || next.episodeIndex
  }
  if (payload.episode_total != null) {
    next.episodeTotal = Number(payload.episode_total) || next.episodeTotal
  }
  if (Array.isArray(payload.episodes_done) && payload.episodes_done.length >= next.episodesDone.length) {
    next.episodesDone = payload.episodes_done.map((row) => normalizeDone(row))
  }
  return next
}

export function isDocumentShotPlanning(doc: ShotPlanDocumentLike | null | undefined): boolean {
  return Boolean(doc?.shot_plan_job_id) || String(doc?.status || "") === "planning"
}

export function documentCanPlanShots(doc: ShotPlanDocumentLike | null | undefined): boolean {
  if (!doc) return false
  if (String(doc.input_mode || "").toLowerCase() === "ai_pipeline") return false
  if (isDocumentShotPlanning(doc)) return false
  const episodes = doc.analysis?.episodes || []
  if (!episodes.length) return false
  return episodes.some((episode) => String(episode.shots_source || "").toLowerCase() !== "llm")
}

export type ShotPlanBadge = {
  color?: "processing" | "success" | "error" | "warning"
  text: string
}

export function documentShotPlanHeaderTag(doc: ShotPlanDocumentLike | null | undefined): ShotPlanBadge | null {
  if (!doc) return null
  if (String(doc.input_mode || "").toLowerCase() === "ai_pipeline") return null
  if (isDocumentShotPlanning(doc)) return { color: "processing", text: "规划中" }
  const episodes = doc.analysis?.episodes || []
  if (!episodes.length) return null
  const llmCount = episodes.filter((episode) => String(episode.shots_source || "").toLowerCase() === "llm").length
  if (llmCount === episodes.length) return { color: "success", text: "已规划" }
  if (llmCount > 0) return { color: "warning", text: "部分已规划" }
  return { color: "warning", text: "未规划" }
}

export function readShotDurationSec(
  shot: { duration_sec?: unknown } | Record<string, unknown> | null | undefined,
): number | null {
  if (!shot || typeof shot !== "object") return null
  const raw = (shot as { duration_sec?: unknown }).duration_sec
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.round(raw)
  if (typeof raw === "string") {
    const match = raw.trim().match(/-?\d+(?:\.\d+)?/)
    if (!match) return null
    const value = Number(match[0])
    return Number.isFinite(value) ? Math.round(value) : null
  }
  return null
}

export function sumShotDurationSec(shots: Array<{ duration_sec?: unknown }> | null | undefined): number {
  return (shots || []).reduce((sum, shot) => sum + (readShotDurationSec(shot) || 0), 0)
}

export function formatShotDurationLabel(duration: unknown): string {
  const value = readShotDurationSec({ duration_sec: duration })
  return value == null ? "" : `${value} 秒`
}

export function shotPlanEpisodeBadge(input: {
  source: string
  planningCurrent: boolean
  queued?: boolean
  planError?: string | null
  shotCount?: number
  durationSec?: number
}): ShotPlanBadge {
  if (input.planError) return { color: "error", text: "规划失败" }
  if (input.planningCurrent) return { color: "processing", text: "规划中" }
  if (String(input.source || "").toLowerCase() === "llm") {
    const shots = Number(input.shotCount || 0)
    const seconds = Number(input.durationSec || 0)
    if (shots > 0 && seconds > 0) return { color: "success", text: `已规划 · ${shots} 镜 · ${seconds} 秒` }
    if (shots > 0) return { color: "success", text: `已规划 · ${shots} 镜` }
    return { color: "success", text: "已规划" }
  }
  if (input.queued) return { text: "排队" }
  return { text: "剧本切镜" }
}

const INCOMPLETE = Symbol("incomplete")

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

export function isUsablePartialShot(shot: Record<string, unknown>): boolean {
  return Boolean(String(shot.title || "").trim() || String(shot.action || "").trim())
}

function unwrapShotPlanJsonCandidate(text: string): string {
  const raw = String(text || "").replace(/^\uFEFF/, "").trim()
  if (!raw) return ""
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)(?:```|$)/i)
  const body = (fence ? fence[1] : raw).trim()
  const keyAt = body.search(/"shots"\s*:/)
  if (keyAt >= 0) {
    const brace = body.lastIndexOf("{", keyAt)
    return brace >= 0 ? body.slice(brace) : body.slice(keyAt)
  }
  const brace = body.indexOf("{")
  return brace >= 0 ? body.slice(brace) : body
}

type JsonCursor = {
  eof: () => boolean
  peek: () => string
  next: () => string
  skipWs: () => void
  readString: () => string | typeof INCOMPLETE
  readValue: () => unknown | typeof INCOMPLETE
  readShotsArray: () => { shots: Array<Record<string, unknown>>; currentOpen: boolean }
}

function createJsonCursor(source: string): JsonCursor {
  let i = 0
  const eof = () => i >= source.length
  const peek = () => (eof() ? "" : source[i])
  const next = () => (eof() ? "" : source[i++])
  const skipWs = () => {
    while (!eof() && /\s/.test(source[i])) i += 1
  }

  const readString = (): string | typeof INCOMPLETE => {
    if (peek() !== "\"") return INCOMPLETE
    next()
    let out = ""
    while (!eof()) {
      const ch = next()
      if (ch === "\"") return out
      if (ch !== "\\") {
        out += ch
        continue
      }
      if (eof()) return INCOMPLETE
      const esc = next()
      if (esc === "u") {
        const hex = source.slice(i, i + 4)
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) return INCOMPLETE
        i += 4
        out += String.fromCharCode(Number.parseInt(hex, 16))
        continue
      }
      const escaped: Record<string, string> = {
        "\"": "\"",
        "\\": "\\",
        "/": "/",
        b: "\b",
        f: "\f",
        n: "\n",
        r: "\r",
        t: "\t",
      }
      out += escaped[esc] ?? esc
    }
    return INCOMPLETE
  }

  const readNumber = (): number | typeof INCOMPLETE => {
    const start = i
    if (peek() === "-") next()
    if (!/[0-9]/.test(peek())) return INCOMPLETE
    while (/[0-9]/.test(peek())) next()
    if (peek() === ".") {
      next()
      if (!/[0-9]/.test(peek())) return INCOMPLETE
      while (/[0-9]/.test(peek())) next()
    }
    if (peek() === "e" || peek() === "E") {
      next()
      if (peek() === "+" || peek() === "-") next()
      if (!/[0-9]/.test(peek())) return INCOMPLETE
      while (/[0-9]/.test(peek())) next()
    }
    const token = source.slice(start, i)
    const value = Number(token)
    return Number.isFinite(value) ? value : INCOMPLETE
  }

  const readLiteral = (): unknown | typeof INCOMPLETE => {
    const rest = source.slice(i)
    if (rest.startsWith("true") && /^(true)(?:$|[\s,\]\}])/.test(rest)) {
      i += 4
      return true
    }
    if (rest.startsWith("false") && /^(false)(?:$|[\s,\]\}])/.test(rest)) {
      i += 5
      return false
    }
    if (rest.startsWith("null") && /^(null)(?:$|[\s,\]\}])/.test(rest)) {
      i += 4
      return null
    }
    return INCOMPLETE
  }

  const readArray = (): unknown[] => {
    next()
    const items: unknown[] = []
    while (!eof()) {
      skipWs()
      if (peek() === "]") {
        next()
        return items
      }
      if (peek() === ",") {
        next()
        continue
      }
      const value = readValue()
      if (value === INCOMPLETE) return items
      items.push(value)
    }
    return items
  }

  const readObject = (): { obj: Record<string, unknown>; closed: boolean } => {
    next()
    const obj: Record<string, unknown> = {}
    while (!eof()) {
      skipWs()
      if (peek() === "}") {
        next()
        return { obj, closed: true }
      }
      if (peek() === ",") {
        next()
        continue
      }
      const key = readString()
      if (key === INCOMPLETE) return { obj, closed: false }
      skipWs()
      if (peek() !== ":") return { obj, closed: false }
      next()
      skipWs()
      const value = readValue()
      if (value === INCOMPLETE) return { obj, closed: false }
      obj[key] = value
    }
    return { obj, closed: false }
  }

  const readValue = (): unknown | typeof INCOMPLETE => {
    skipWs()
    const ch = peek()
    if (ch === "\"") return readString()
    if (ch === "{") {
      const nested = readObject()
      return nested.closed ? nested.obj : INCOMPLETE
    }
    if (ch === "[") return readArray()
    if (ch === "-" || /[0-9]/.test(ch)) return readNumber()
    return readLiteral()
  }

  const readShotsArray = (): { shots: Array<Record<string, unknown>>; currentOpen: boolean } => {
    next()
    const shots: Array<Record<string, unknown>> = []
    let currentOpen = false
    while (!eof()) {
      skipWs()
      if (peek() === "]") {
        next()
        return { shots, currentOpen: false }
      }
      if (peek() === ",") {
        next()
        continue
      }
      if (peek() === "{") {
        const nested = readObject()
        shots.push(nested.obj)
        currentOpen = !nested.closed
        if (!nested.closed) return { shots, currentOpen: true }
        continue
      }
      const value = readValue()
      if (value === INCOMPLETE) return { shots, currentOpen }
    }
    return { shots, currentOpen }
  }

  return { eof, peek, next, skipWs, readString, readValue, readShotsArray }
}

export type PartialShotPlanJson = {
  shots: Array<Record<string, unknown>>
  currentOpen: boolean
}

export function parsePartialShotPlanJson(text: string): PartialShotPlanJson {
  const source = unwrapShotPlanJsonCandidate(text)
  if (!source.trim()) return { shots: [], currentOpen: false }
  try {
    const parsed = JSON.parse(source) as { shots?: unknown }
    if (Array.isArray(parsed?.shots)) {
      return {
        shots: parsed.shots.filter(isPlainObject),
        currentOpen: false,
      }
    }
  } catch {
    /* fall through to partial parse */
  }

  const cursor = createJsonCursor(source)
  cursor.skipWs()
  if (cursor.peek() !== "{") return { shots: [], currentOpen: false }
  cursor.next()
  let listed: { shots: Array<Record<string, unknown>>; currentOpen: boolean } | null = null
  while (!cursor.eof()) {
    cursor.skipWs()
    if (cursor.peek() === "}") break
    if (cursor.peek() === ",") {
      cursor.next()
      continue
    }
    const key = cursor.readString()
    if (key === INCOMPLETE) break
    cursor.skipWs()
    if (cursor.peek() !== ":") break
    cursor.next()
    cursor.skipWs()
    if (key === "shots" && cursor.peek() === "[") {
      listed = cursor.readShotsArray()
      continue
    }
    if (cursor.readValue() === INCOMPLETE) break
  }
  return listed || { shots: [], currentOpen: false }
}

export function assemblingShotsFromLive(live: ShotPlanLiveState): Array<Record<string, unknown>> {
  return parsePartialShotPlanJson(live.text).shots.filter(isUsablePartialShot).map((shot, index) => {
    const duration = readShotDurationSec(shot)
    return {
      ...shot,
      shot_num: Number(shot.shot_num) > 0 ? Number(shot.shot_num) : index + 1,
      ...(duration != null ? { duration_sec: duration } : {}),
    }
  })
}

export function liveAssemblingShotCount(live: ShotPlanLiveState): number {
  if (!live.working) return 0
  const parsedCount = assemblingShotsFromLive(live).length
  if (parsedCount > 0) return parsedCount
  const done = live.episodesDone.find((row) => row.episode_num === live.episodeNum)
  if (done && !String(live.text || "").trim()) return done.shots_count || done.shots.length
  return 0
}

export function isAssemblingShotPlan(live: ShotPlanLiveState): boolean {
  if (!live.working || !String(live.text || "").trim()) return false
  return parsePartialShotPlanJson(live.text).currentOpen
}

export function episodeShotPlanError(
  episodeNum: number | null | undefined,
  logs: string[] | null | undefined,
  liveError?: string | null,
): string | null {
  if (liveError && String(liveError).trim()) {
    const text = String(liveError).trim()
    if (text.includes("规划失败") || text.includes("保留解析器")) return text
    return `第${episodeNum ?? "?"}集镜头规划失败，已保留解析器镜头：${text}`
  }
  if (episodeNum == null) return null
  const prefix = `第${episodeNum}集镜头规划失败`
  const hit = [...(logs || [])].reverse().find((line) => String(line).includes(prefix))
  return hit ? String(hit) : null
}

export function doneForEpisode(episodeNum: number | undefined, live: ShotPlanLiveState): ShotPlanEpisodeDone | undefined {
  return live.episodesDone.find((row) => row.episode_num === episodeNum)
}

export function shotsForEpisode<T>(
  episode: { episode_num?: number; shots?: T[] | null },
  live: ShotPlanLiveState,
  planning = false,
): T[] {
  const done = doneForEpisode(episode.episode_num, live)
  if (done?.shots?.length) return done.shots as T[]
  if (isCurrentPlanningEpisode(episode.episode_num, live, planning)) {
    return assemblingShotsFromLive(live) as T[]
  }
  return (episode.shots || []) as T[]
}

export function shotPlanSourceForEpisode(
  episode: { episode_num?: number; shots_source?: string | null },
  live: ShotPlanLiveState,
): string {
  const done = doneForEpisode(episode.episode_num, live)
  if (done?.shots_source) return String(done.shots_source)
  return String(episode.shots_source || "")
}

export function isCurrentPlanningEpisode(
  episodeNum: number | undefined,
  live: ShotPlanLiveState,
  planning: boolean,
): boolean {
  if (!planning || !live.working || live.episodeNum == null) return false
  return Number(episodeNum) === Number(live.episodeNum)
}

export function isQueuedPlanningEpisode(
  episodeNum: number | undefined,
  live: ShotPlanLiveState,
  planning: boolean,
): boolean {
  if (!planning || !live.working || live.episodeNum == null || episodeNum == null) return false
  return Number(episodeNum) > Number(live.episodeNum)
}

export type ShotPlanStatusCopy = {
  kind: "working" | "done" | "error" | "idle"
  title: string
  description: string
}

export function shotPlanProgressLabel(live: ShotPlanLiveState): string {
  const total = Number(live.episodeTotal || 0)
  const index = Number(live.episodeIndex || 0)
  if (total > 0) return `第 ${index || live.episodeNum || 1} / ${total} 集`
  if (live.episodeNum != null) return `第 ${live.episodeNum} 集`
  return "即将开始"
}

export function shotPlanSlimProgressLabel(live: ShotPlanLiveState): string {
  return `正在规划 ${shotPlanProgressLabel(live)} · 本集已写出 ${liveAssemblingShotCount(live)} 条镜头`
}

export function shotPlanProgressPercent(live: ShotPlanLiveState): number {
  const total = Number(live.episodeTotal || 0)
  const index = Number(live.episodeIndex || 0)
  if (total > 0) {
    const current = Math.max(0, Math.min(index, total))
    return Math.round((current / total) * 100)
  }
  return live.working ? 8 : 0
}

export function shotPlanStatusCopy(
  live: ShotPlanLiveState,
  planning: boolean,
  _options?: { needsPlan?: boolean },
): ShotPlanStatusCopy | null {
  if (live.working || planning) {
    return {
      kind: "working",
      title: shotPlanSlimProgressLabel(live),
      description: "",
    }
  }
  if (live.message === "镜头规划完成") return null
  if (live.message && !live.working && live.jobId) {
    return { kind: "error", title: "镜头规划未完成", description: live.message }
  }
  return null
}

export function markShotPlanLiveFinished(state: ShotPlanLiveState): ShotPlanLiveState {
  if (!state.jobId) return state
  if (!state.working && state.message) return state
  return {
    ...state,
    working: false,
    message: state.message && state.message !== "正在按集规划镜头" ? state.message : "镜头规划完成",
  }
}
