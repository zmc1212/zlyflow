import { Button, Drawer } from "antd"
import {
  ArrowDown, ArrowUp, CheckCircle2, ChevronLeft, ChevronRight, Clapperboard, FileText, MapPinned,
  Mic2, Music2, Palette, Search, Users, XCircle,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import {
  SCRIPT_ART_BLOCK_TITLE, SCRIPT_ART_CHANGE_LABEL, SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER, SCRIPT_CLARIFY_HINT,
  SCRIPT_CLARIFY_SKIP_ALL, SCRIPT_CLARIFY_SKIP_ONE, SCRIPT_CLARIFY_SUBMIT, SCRIPT_CLARIFY_TITLE,
  SCRIPT_DIRECTION_LABEL, SCRIPT_HISTORY_TITLE,
  SCRIPT_JUMP_LATEST_LABEL, SCRIPT_STEP_EMPTY_LABEL, SCRIPT_STEP_REGENERATE_TITLE, SCRIPT_STEP_VIEW_LABEL,
  SCRIPT_STREAM_CANCEL_LABEL, SCRIPT_STREAM_STATE_LABELS, SCRIPT_STREAM_TITLE, SCRIPT_STREAM_WRITING_LABELS,
  SCRIPT_USER_BUBBLE_LABEL, STAGE_CLARIFY_HINTS, STAGE_CLARIFY_TITLES,
} from "../action-copy"
import type { RecipeAgentStatus, RecipeProject } from "../recipe-model"
import { artStylePreviewUrl, flattenRecipeShots } from "../recipe-model"
import type { TaskRowPreview } from "./DirectorTaskRows"
import { RECIPE_AGENT_LABELS, RECIPE_AGENT_ORDER, RECIPE_AGENT_RUNNING_MESSAGES } from "../types"
import DirectorTaskRows from "./DirectorTaskRows"
import {
  streamDirectorOperationEvents,
  type AgentStreamItem,
  type DirectorOperationStreamEvent,
} from "../director-operation-stream"

const AGENT_BLOCK_ICONS: Record<string, typeof FileText> = {
  research: Search,
  script: FileText,
  art_style: Palette,
  characters: Users,
  locations: MapPinned,
  storyboard: Clapperboard,
  voice: Mic2,
  music: Music2,
}

export type ClarifyOption = { label: string; value: string; recommended?: boolean }
export type ClarifyQuestion = { id: string; question: string; why?: string; options: ClarifyOption[]; allowCustom?: boolean }
export type ClarifyAnswer = { id?: string; question: string; answer: string }

type TerminalState = { kind: "done" | "cancelled" | "error"; message?: string }

type AgentRowState = { id: string; label: string; status: string; message: string }

type Props = {
  operationId: string
  operationKind: string
  startedAt: number
  agentStatus: RecipeAgentStatus[]
  artStyleName?: string
  cancelRequested: boolean
  /** The brief snapshot this run started from, shown as the user's chat bubble. */
  brief?: string
  /** Refresh recovery: unanswered clarify questions persisted by the studio. */
  initialQuestions?: ClarifyQuestion[]
  /** Confirmed directions to show as chips once the pipeline transcript runs. */
  clarifications?: ClarifyAnswer[]
  /** Open the art style catalog modal (handled by the studio). */
  onOpenPicker?: () => void
  /** Finished-run replay: rebuild the transcript from the saved recipe payload. */
  historyMode?: boolean
  recipe?: RecipeProject
  /** Rendered at the end of the transcript (completion card, finished script…). */
  transcriptFooter?: ReactNode
  /** Retry a single failed agent step from the task rows. */
  onRetryAgent?: (agentId: string) => void
  /** Ask to regenerate a completed agent step (opens the scope confirm in the studio). */
  onRegenerateAgent?: (agentId: string) => void
  onCancel: () => void
  /** Guided step this clarify belongs to (art_style/characters/…); unset = script direction. */
  clarifyAgent?: string
  onConfirmStep: (answers: ClarifyAnswer[]) => void
}

const TRANSCRIPT_AGENTS = ["research", "script", "art_style", "characters", "locations", "storyboard", "voice", "music"] as const

const TRANSCRIPT_AGENT_SET = new Set<string>(TRANSCRIPT_AGENTS)

/* 官方 task-rows.tsx RetryIcon 原路径：复用为已完成环节的「重新生成」图标。 */
function RegenerateIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
  )
}

/** 分镜打磨阶段（按秒分配/校验衔接等）的进度消息解析结果。
 *  打磨阶段同时有 storyboard_polish 命名空间的 delta 直播字幕（当前正在改写的镜头文本）。 */
export type StoryboardPolishPhase = {
  title: string
  index?: number
  total?: number
  range?: [number, number]
  currentShot?: number
  chars?: number
}

export function parseStoryboardPhase(message: string | undefined | null): StoryboardPolishPhase | null {
  if (!message) return null
  const charsMatch = message.match(/已收 (\d+) 字/)
  const chars = charsMatch ? Number(charsMatch[1]) : undefined
  const rangeMatch = message.match(/第 (\d+)-(\d+) 镜/)
  const range = rangeMatch ? [Number(rangeMatch[1]), Number(rangeMatch[2])] as [number, number] : undefined
  const shotMatch = message.match(/正在第 (\d+) 镜/)
  const currentShot = shotMatch ? Number(shotMatch[1]) : undefined
  const withStep = (title: string, index: number, total: number): StoryboardPolishPhase => ({
    title, index, total, range, currentShot, chars,
  })
  const timing = message.match(/^正在按秒分配对白与动作 \((\d+)\/(\d+)\)/)
  if (timing) return withStep("按秒分配对白与动作", Number(timing[1]), Number(timing[2]))
  const continuity = message.match(/^正在校验镜头衔接 \((\d+)\/(\d+)\)/)
  if (continuity) return withStep("校验镜头衔接", Number(continuity[1]), Number(continuity[2]))
  const misc = message.match(/^(正在整理镜头|正在从剧本补全对白|正在修复镜头因果衔接)/)
  if (misc) return { title: misc[1], chars }
  return null
}

function useIsMobile(query = "(max-width: 767px)") {
  const [mobile, setMobile] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMobile(event.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])
  return mobile
}

function textKey(agent: string, field: string, index: number | null): string {
  return `${agent}|${field}|${index ?? ""}`
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒` : `${seconds} 秒`
}

function itemText(item: AgentStreamItem | undefined, key: string): string {
  const value = item ? item[key] : undefined
  return typeof value === "string" ? value : ""
}

function StoryParagraphs({ text, active }: { text: string; active: boolean }) {
  const lines = text.split("\n")
  return (
    <>
      {lines.map((line, index) => {
        const isLast = index === lines.length - 1
        const caretHere = active && isLast
        if (!line.trim()) return caretHere ? <p key={index} className="director-stream-caret-line">{null}</p> : <p key={index} className="is-blank">&nbsp;</p>
        const sceneMarker = line.trim().startsWith("【") && line.trim().includes("】")
        return (
          <p key={index} className={sceneMarker ? "is-scene" : undefined}>
            {line}
            {caretHere ? <span className="stream-caret" aria-hidden /> : null}
          </p>
        )
      })}
    </>
  )
}

/** Chat-transcript style live view of the whole generation, plus the clarify approval cards. */
export default function DirectorScriptStreamPanel({
  operationId, operationKind, startedAt, agentStatus, artStyleName, cancelRequested, brief,
  initialQuestions, clarifications, onOpenPicker, historyMode = false, recipe, transcriptFooter,
  onRetryAgent, onRegenerateAgent, onCancel, clarifyAgent, onConfirmStep,
}: Props) {
  // Streaming content, keyed by `${agent}|${field}|${index ?? ""}`.
  const [targetTexts, setTargetTexts] = useState<Record<string, string>>({})
  const [shownTexts, setShownTexts] = useState<Record<string, string>>({})
  const [items, setItems] = useState<Record<string, Record<number, AgentStreamItem>>>({})
  // Latest streaming item ordinal per `${agent}|${field}` — the item being
  // typed right now, which has no agent_item event until its JSON closes.
  const [activeIndex, setActiveIndex] = useState<Record<string, number>>({})
  const [agentOverrides, setAgentOverrides] = useState<Record<string, { status: string; message: string }>>({})
  const [statusText, setStatusText] = useState("")
  const [streamLive, setStreamLive] = useState(false)
  const [terminal, setTerminal] = useState<TerminalState | null>(null)
  const [elapsed, setElapsed] = useState(() => (startedAt > 0 ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0))
  // 环节产出抽屉（查看已完成/失败环节的完整内容）。
  const [viewingAgent, setViewingAgent] = useState<string | null>(null)
  // 跟随滚动状态的渲染镜像：false 时浮现"回到底部"。
  const [tailFollowing, setTailFollowing] = useState(true)
  const isMobile = useIsMobile()

  // Clarify (approval card) state.
  const [questions, setQuestions] = useState<ClarifyQuestion[] | null>(() => initialQuestions ?? null)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [customValue, setCustomValue] = useState("")
  const [selectedOption, setSelectedOption] = useState<string | null>(null)
  const answersRef = useRef<ClarifyAnswer[]>([])

  // 与 Studio 的澄清作用域保持同步：作用域清空或换轮时重置问题卡与作答进度。
  // 否则旧问题卡会在新一轮澄清准备期间仍然可点，答完走的是过期作用域（表现为“选了没效果”）。
  useEffect(() => {
    setQuestions(initialQuestions ?? null)
    setQuestionIndex(0)
    answersRef.current = []
    setSelectedOption(null)
    setCustomValue("")
  }, [initialQuestions])

  // 官方 Approval Card 交互：单选立即高亮，480ms 后自动翻到下一题。
  const handleSelect = (value: string) => {
    setSelectedOption(value)
    setCustomValue("")
    window.setTimeout(() => {
      answerCurrent(value)
      setSelectedOption(null)
    }, 480)
  }

  const targetRef = useRef(targetTexts)
  targetRef.current = targetTexts
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const feedRef = useRef<HTMLDivElement | null>(null)
  const footerRef = useRef<HTMLDivElement | null>(null)
  const followTailRef = useRef(!historyMode)
  const startedAtRef = useRef(startedAt)
  startedAtRef.current = startedAt

  // 新一轮操作接入时清掉上一轮的终态与流式覆盖，面板回到直播模式；
  // 操作结束回落到空 id 时不重置，保留终态头部。已有创作记录正文保留，由新一轮流式覆盖。
  useEffect(() => {
    if (!operationId) return
    setTerminal(null)
    setAgentOverrides({})
    setStreamLive(false)
    setStatusText("")
    followTailRef.current = true
    setTailFollowing(true)
    const base = startedAtRef.current
    setElapsed(base > 0 ? Math.max(0, Math.floor((Date.now() - base) / 1000)) : 0)
  }, [operationId])

  // 恢复记录：页面加载时用已保存的 recipe 重建已完成的对话记录
  //（流式数据只在内存里，刷新后靠 recipe 恢复任务面板与产出块）。
  const seededRef = useRef(false)
  useEffect(() => {
    if (!recipe || seededRef.current) return
    // 空的初始 recipe（工程查询未返回）不消费 seed 机会，等真实数据到达再重建。
    const hasContent = Boolean(
      recipe.script?.fullStory?.trim() || recipe.characters?.length || recipe.scenes?.length,
    )
    if (!hasContent) return
    seededRef.current = true
    const texts: Record<string, string> = {}
    if (recipe.researchNotes) texts["research|notes|"] = recipe.researchNotes
    const script = recipe.script
    if (script.title) texts["script|title|"] = script.title
    if (script.summary) texts["script|summary|"] = script.summary
    if (script.fullStory) texts["script|fullStory|"] = script.fullStory
    if (recipe.globalMusic) texts["music|globalMusic|"] = recipe.globalMusic
    if (recipe.globalSoundscape) texts["music|globalSoundscape|"] = recipe.globalSoundscape
    const indexList = (list: AgentStreamItem[]) => Object.fromEntries(list.map((item, index) => [index, item]))
    const characters = (recipe.characters || []).filter((item) => item.type !== "object")
    const voiceRows = characters
      .filter((item) => item.voiceId)
      .map((item) => ({ name: item.name, voiceId: item.voiceId }))
    const itemsMap: Record<string, Record<number, AgentStreamItem>> = {
      "characters|characters": indexList(characters.map((item) => ({
        name: item.name, role: item.role, description: item.description,
      }))),
      "characters|props": indexList((recipe.props || []).map((item) => ({
        name: item.name, description: item.description,
      }))),
      "locations|locations": indexList((recipe.locations || []).map((item) => ({
        name: item.name, description: item.description,
      }))),
      "voice|characters": indexList(voiceRows),
      "storyboard|shots": indexList(flattenRecipeShots(recipe).map((shot) => ({
        title: shot.title, description: shot.description, dialogue: shot.dialogue,
      }))),
      "storyboard|scenes": indexList((recipe.scenes || []).map((scene) => ({ title: scene.title }))),
    }
    setTargetTexts((prev) => ({ ...texts, ...prev }))
    setShownTexts((prev) => ({ ...texts, ...prev }))
    setItems((prev) => {
      const merged: Record<string, Record<number, AgentStreamItem>> = { ...itemsMap }
      for (const key of Object.keys(prev)) {
        merged[key] = { ...(merged[key] || {}), ...prev[key] }
      }
      return merged
    })
  }, [historyMode, recipe])

  const shown = (agent: string, field: string, index: number | null = null): string => (
    shownTexts[textKey(agent, field, index)] || ""
  )

  const handleEvent = (event: DirectorOperationStreamEvent) => {
    setStreamLive(true)
    if (event.event === "agent_delta") {
      const { agent, field, index, delta, reset } = event.data
      const key = textKey(agent, field, index)
      setTargetTexts((current) => ({ ...current, [key]: reset ? delta : (current[key] || "") + delta }))
      if (index !== null) {
        setActiveIndex((current) => {
          const mapKey = `${agent}|${field}`
          const known = current[mapKey]
          if (known !== undefined && known >= index) return current
          return { ...current, [mapKey]: index }
        })
      }
    } else if (event.event === "agent_item") {
      const { agent, field, index, item } = event.data
      setItems((current) => {
        const map = { ...(current[`${agent}|${field}`] || {}) }
        map[index] = item
        return { ...current, [`${agent}|${field}`]: map }
      })
    } else if (event.event === "agent") {
      setAgentOverrides((current) => ({
        ...current,
        [event.data.id]: { status: event.data.status, message: event.data.message || "" },
      }))
    } else if (event.event === "status") {
      if (event.data.message) setStatusText(event.data.message)
    } else if (event.event === "done") {
      const result = event.data.result as { questions?: unknown } | undefined
      const incoming = result?.questions
      if (operationKind === "plan_clarify" && Array.isArray(incoming) && incoming.length) {
        setQuestions(incoming as ClarifyQuestion[])
      } else {
        setTerminal({ kind: "done" })
      }
    } else if (event.event === "cancelled") {
      setTerminal({ kind: "cancelled", message: event.data.message })
    } else if (event.event === "error") {
      setTerminal({ kind: "error", message: event.data.message })
    }
  }
  const handleEventRef = useRef(handleEvent)
  handleEventRef.current = handleEvent

  useEffect(() => {
    if (!operationId) return
    const controller = new AbortController()
    let alive = true
    void streamDirectorOperationEvents(
      operationId,
      (event) => handleEventRef.current(event),
      { signal: controller.signal, shouldContinue: () => alive },
    ).then((result) => {
      if (alive && result === "failed") setStreamLive(false)
    })
    return () => {
      alive = false
      controller.abort()
    }
  }, [operationId])

  // Typewriter drain: shown text catches up to target a few characters per
  // tick so throttled backend batches render as continuous writing.
  useEffect(() => {
    const timer = window.setInterval(() => {
      setShownTexts((current) => {
        let next: Record<string, string> | null = null
        for (const key of Object.keys(targetRef.current)) {
          const goal: string = targetRef.current[key]
          const base: Record<string, string> = next ?? current
          const now: string = base[key] ?? ""
          if (now === goal) continue
          if (!goal.startsWith(now)) {
            base[key] = goal
          } else {
            const gap: number = goal.length - now.length
            base[key] = goal.slice(0, now.length + Math.min(gap, gap > 400 ? 36 : gap > 120 ? 14 : 4))
          }
          next = base
        }
        return next ?? current
      })
    }, 32)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (terminal) return
    const timer = window.setInterval(() => {
      setElapsed((current) => (
        startedAt > 0 ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : current + 1
      ))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [startedAt, terminal])

  const agentRows = useMemo<AgentRowState[]>(() => RECIPE_AGENT_ORDER.map((id) => {
    const streamed = agentOverrides[id]
    const polled = agentStatus.find((item) => item.id === id)
    const status = streamed?.status ?? polled?.status ?? "pending"
    const message = streamed?.message || polled?.message
      || (status === "running" ? RECIPE_AGENT_RUNNING_MESSAGES[id] : "")
    return { id, label: RECIPE_AGENT_LABELS[id], status, message }
  }), [agentOverrides, agentStatus])

  const phase: "clarify-stream" | "clarify-ask" | "pipeline" = historyMode
    ? "pipeline"
    : operationKind === "plan_clarify"
      ? (questions && questions.length ? "clarify-ask" : "clarify-stream")
      : "pipeline"

  // 跟随滚动：流式内容高度任何变化（打字机、卡片、完成页脚）都贴住底部；
  // 用户上滚离开底部 48px 即停止跟随，由"回到底部"按钮恢复。
  useEffect(() => {
    const element = bodyRef.current
    const feed = feedRef.current
    if (!element || !feed || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(() => {
      if (followTailRef.current) element.scrollTop = element.scrollHeight
      setTailFollowing(followTailRef.current)
    })
    observer.observe(element)
    observer.observe(feed)
    return () => observer.disconnect()
  }, [phase])

  // 跳底必须即时定位：平滑滚动的目标值在内容持续增长时会过期，
  // 且动画途中的 scroll 事件会被误判为"用户上滚"而关闭跟随。
  const jumpToLatest = () => {
    followTailRef.current = true
    setTailFollowing(true)
    const element = bodyRef.current
    if (element) element.scrollTop = element.scrollHeight
  }

  const handleBodyScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    const following = element.scrollHeight - element.scrollTop - element.clientHeight < 48
    followTailRef.current = following
    setTailFollowing(following)
  }

  const sortedItems = (agent: string, field: string): AgentStreamItem[] => {
    const map = items[`${agent}|${field}`]
    if (!map) return []
    return Object.keys(map).map(Number).sort((a, b) => a - b).map((index) => map[index])
  }

  const runningAgent = agentRows.find((row) => row.status === "running")
  const settled = terminal !== null || historyMode

  // 新环节开始时强制恢复跟随：直播内容始终从最新处可见，不要求用户手动回底。
  const runningAgentId = runningAgent?.id ?? null
  const prevRunningAgentRef = useRef<string | null>(null)
  useEffect(() => {
    if (runningAgentId && prevRunningAgentRef.current !== runningAgentId) {
      followTailRef.current = true
      setTailFollowing(true)
      const element = bodyRef.current
      if (element) element.scrollTop = element.scrollHeight
    }
    prevRunningAgentRef.current = runningAgentId
  }, [runningAgentId])

  // 分镜直播：新镜头开始时强制恢复跟随并跳到最新处（镜头完成自动展开下一镜）。
  // 注意：后端 agent_delta 的 field 是具体字段名（title/description/dialogue）、
  // index 是数组内全局序号，activeIndex 里没有 "storyboard|shots" 这个键，
  // 当前镜头序号要取各字段序号的最大值。
  const storyboardShotOrdinal = (() => {
    const values = [
      activeIndex["storyboard|title"],
      activeIndex["storyboard|description"],
      activeIndex["storyboard|dialogue"],
    ].filter((value): value is number => value !== undefined)
    return values.length ? Math.max(...values) : undefined
  })()
  // 打字机视角的"当前镜头"：agent_item（JSON 闭合）到达时不立即翻转已完成行——
  // LLM 分块批量到达时镜头瞬间闭合，立即收起会让流式打印一闪而过；
  // 只要该镜头的 shown 还没追上 target，就保持展开继续逐字打印。
  const storyboardPrintingOrdinal = (() => {
    let draining: number | undefined
    for (const key of Object.keys(targetTexts)) {
      if (!key.startsWith("storyboard|")) continue
      const field = key.split("|")[1]
      if (field !== "title" && field !== "description" && field !== "dialogue") continue
      const ordinal = Number(key.split("|")[2])
      if (!Number.isFinite(ordinal)) continue
      if ((shownTexts[key] || "") !== (targetTexts[key] || "")) {
        if (draining === undefined || ordinal > draining) draining = ordinal
      }
    }
    return draining ?? storyboardShotOrdinal
  })()
  const prevStoryboardShotRef = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (runningAgentId !== "storyboard" || storyboardShotOrdinal === undefined) {
      prevStoryboardShotRef.current = undefined
      return
    }
    if (prevStoryboardShotRef.current !== storyboardShotOrdinal) {
      followTailRef.current = true
      setTailFollowing(true)
      const element = bodyRef.current
      if (element) element.scrollTop = element.scrollHeight
    }
    prevStoryboardShotRef.current = storyboardShotOrdinal
  }, [storyboardShotOrdinal, runningAgentId])

  // 打磨直播字幕：storyboard_polish 命名空间的 delta（后端每个分块索引归零），
  // 取仍在打字或最新的序号作为当前直播文本，随镜头切换被 reset 覆盖。
  const polishLive = (() => {
    let draining: number | undefined
    let latest: number | undefined
    for (const key of Object.keys(targetTexts)) {
      if (!key.startsWith("storyboard_polish|")) continue
      const field = key.split("|")[1]
      if (field !== "description" && field !== "dialogue") continue
      const ordinal = Number(key.split("|")[2])
      if (!Number.isFinite(ordinal)) continue
      if (latest === undefined || ordinal > latest) latest = ordinal
      if ((shownTexts[key] || "") !== (targetTexts[key] || "")) {
        if (draining === undefined || ordinal > draining) draining = ordinal
      }
    }
    const ordinal = draining ?? latest
    if (ordinal === undefined) return undefined
    return {
      ordinal,
      description: shownTexts[`storyboard_polish|description|${ordinal}`] || "",
      dialogue: shownTexts[`storyboard_polish|dialogue|${ordinal}`] || "",
    }
  })()

  // 打磨分块切换（消息里的阶段 (i/N) 变化）时清掉上一分块的直播字幕键：
  // 每个分块的 delta 序号都从 0 重来，不清会与上一分块的序号混在一起。
  const polishPhaseKey = runningAgentId === "storyboard"
    ? (() => {
      const phase = parseStoryboardPhase(runningAgent?.message)
      return phase ? `${phase.title}|${phase.index ?? ""}` : null
    })()
    : null
  const prevPolishPhaseKeyRef = useRef<string | null>(null)
  useEffect(() => {
    const previous = prevPolishPhaseKeyRef.current
    prevPolishPhaseKeyRef.current = polishPhaseKey
    if (polishPhaseKey === null || previous === null || previous === polishPhaseKey) return
    const dropPolishKeys = (current: Record<string, string>) => {
      const next: Record<string, string> = {}
      for (const key of Object.keys(current)) {
        if (!key.startsWith("storyboard_polish|")) next[key] = current[key]
      }
      return next
    }
    setTargetTexts(dropPolishKeys)
    setShownTexts(dropPolishKeys)
  }, [polishPhaseKey])

  // 分镜打磨阶段切换（写分镜 → 按秒分配 → 校验衔接）时强制恢复跟随，
  // 让用户第一时间看到切换后的阶段面板。
  const storyboardPhaseTitle = runningAgentId === "storyboard"
    ? parseStoryboardPhase(runningAgent?.message)?.title ?? null
    : null
  const prevPhaseTitleRef = useRef<string | null>(null)
  useEffect(() => {
    if (storyboardPhaseTitle && prevPhaseTitleRef.current !== storyboardPhaseTitle) {
      followTailRef.current = true
      setTailFollowing(true)
      const element = bodyRef.current
      if (element) element.scrollTop = element.scrollHeight
    }
    prevPhaseTitleRef.current = storyboardPhaseTitle
  }, [storyboardPhaseTitle])

  // 生成结束瞬间定位到完成卡：继续贴底会落在长文档的末尾。
  // footer 由 studio 侧稍晚挂载（historyMode 翻转后），依赖两个状态到位后再定位。
  useEffect(() => {
    if (!terminal || !historyMode) return
    followTailRef.current = false
    setTailFollowing(false)
    footerRef.current?.scrollIntoView({ block: "start", behavior: "smooth" })
  }, [terminal, historyMode])

  /* 已完成环节的产出预览：分镜行取最新镜头的视频/首帧，画风行取画风封面。
     只使用 recipe 数据模型里已有的字段，纯装饰用途，任何缺失都静默降级。
     注意：必须位于下方 `if (phase !== "pipeline")` 提前 return 之前，保证 hooks 顺序稳定。 */
  const taskPreviews = useMemo(() => {
    const previews: Record<string, TaskRowPreview> = {}
    if (!recipe) return previews
    try {
      const shots = flattenRecipeShots(recipe)
      const withMedia = shots.filter((shot) => shot.outputVideoUrl || shot.firstFrameUrl || shot.stillUrl)
      const latest = withMedia[withMedia.length - 1]
      if (latest) {
        const totalSeconds = Math.max(0, Math.round(latest.durationSec || 0))
        previews.storyboard = {
          src: (latest.outputVideoUrl || latest.firstFrameUrl || latest.stillUrl) as string,
          kind: latest.outputVideoUrl ? "video" : "image",
          durationLabel: `00:00 / 00:${String(totalSeconds).padStart(2, "0")}`,
          ratioLabel: recipe.aspectRatio === "9:16" ? "9:16" : "16:9",
        }
      }
      if (recipe.artStyle) {
        const styleCover = artStylePreviewUrl(recipe.artStyle)
        if (styleCover) previews.art_style = { src: styleCover, kind: "image" }
      }
    } catch {
      /* 预览是装饰能力，数据异常时直接不展示 */
    }
    return previews
  }, [recipe])

  // 分环节提问的标题与说明：script 方向沿用开场文案，其余环节按步骤展示。
  const clarifyTitle = clarifyAgent ? STAGE_CLARIFY_TITLES[clarifyAgent] || SCRIPT_CLARIFY_TITLE : SCRIPT_CLARIFY_TITLE
  const clarifyHint = clarifyAgent ? STAGE_CLARIFY_HINTS[clarifyAgent] || SCRIPT_CLARIFY_HINT : SCRIPT_CLARIFY_HINT

  const headTitle = terminal
    ? SCRIPT_STREAM_STATE_LABELS[terminal.kind]
    : historyMode
      ? SCRIPT_HISTORY_TITLE
      : phase === "pipeline" ? SCRIPT_STREAM_TITLE : clarifyTitle
  const headDetail = terminal
    ? (terminal.message || (terminal.kind === "done" ? "成稿已就绪，可在下方记录中查看；编辑请切换「手动编辑」。" : "已停止本次创作。"))
    : phase === "clarify-stream"
      ? clarifyAgent ? "正在结合剧本构思这一步的确认问题…" : "正在根据你的创意构思创作方向问题…"
      : phase === "clarify-ask"
        ? clarifyHint
        : historyMode
          ? "以下是本次生成的完整过程记录。"
          : `${runningAgent?.message || statusText || "正在连接 AI 导演…"}${elapsed > 0 ? ` · 已进行 ${formatElapsed(elapsed)}` : ""}`

  const answerCurrent = (value: string) => {
    const list = questions
    if (!list) return
    const current = list[questionIndex]
    if (!current) return
    const next = [...answersRef.current, { id: current.id, question: current.question, answer: value }]
    answersRef.current = next
    setCustomValue("")
    if (value === "保留并跳过 AI 生成" || questionIndex + 1 >= list.length) {
      onConfirmStep(next)
    } else {
      setQuestionIndex(questionIndex + 1)
    }
  }

  const skipOne = () => {
    const list = questions
    if (!list) return
    setCustomValue("")
    if (questionIndex + 1 < list.length) {
      setQuestionIndex(questionIndex + 1)
    } else {
      onConfirmStep(answersRef.current)
    }
  }

  const userBubble = brief && brief.trim() ? (
    <div className="director-user-bubble" aria-label={SCRIPT_USER_BUBBLE_LABEL}>
      <span className="director-user-bubble-label">{SCRIPT_USER_BUBBLE_LABEL}</span>
      <p>{brief.trim()}</p>
    </div>
  ) : null

  const head = (
    <div className="director-script-stream-head">
      {terminal ? (
        terminal.kind === "done"
          ? <CheckCircle2 size={18} className="director-stream-head-icon is-done" />
          : <XCircle size={18} className="director-stream-head-icon is-failed" />
      ) : historyMode ? (
        <CheckCircle2 size={18} className="director-stream-head-icon is-done" />
      ) : (
        <span className="director-stream-pulse" aria-hidden />
      )}
      <div className="director-script-stream-copy">
        <strong>{headTitle}</strong>
        <span>{headDetail}</span>
      </div>
      {/* 仅在还有活动操作可取消时显示；澄清问题已就绪（操作已结束）时不渲染死按钮。 */}
      {!settled && operationId ? (
        <Button size="small" danger loading={cancelRequested} disabled={cancelRequested} onClick={onCancel}>
          {SCRIPT_STREAM_CANCEL_LABEL}
        </Button>
      ) : null}
    </div>
  )

  if (phase !== "pipeline") {
    const list = questions
    const current = phase === "clarify-ask" && list ? list[questionIndex] : undefined
    const streamedQuestions = Object.keys(targetTexts).filter((key) => key.startsWith("clarify|question|")).sort()
    const last = Boolean(list && questionIndex === list.length - 1)
    const customAnswer = customValue.trim()
    const hasAnswer = selectedOption !== null || customAnswer.length > 0
    const submitArrow = () => {
      if (selectedOption) answerCurrent(selectedOption)
      else if (customAnswer) answerCurrent(customAnswer)
      else skipOne()
    }
    return (
      <div className={`director-script-stream is-clarify${terminal ? " is-terminal" : ""}`} data-stream-live={streamLive || undefined}>
        {head}
        <div className="director-stream-wrap">
          <div className="director-stream-body" ref={bodyRef} onScroll={handleBodyScroll}>
            <div className="director-stream-feed" ref={feedRef}>
              {userBubble}
              {current ? (
            <div className="director-approval">
              <div key={questionIndex} className="director-approval-card">
                <div className="director-approval-question">
                  <span>{current.question}</span>
                </div>
                {current.why ? <p className="director-approval-why">{current.why}</p> : null}
                <div className="director-approval-options">
                  {current.options.map((option) => {
                    const on = selectedOption === option.value
                    return (
                      <button
                        key={option.value}
                        type="button"
                        aria-pressed={on}
                        disabled={terminal !== null}
                        className="director-approval-option"
                        onClick={() => handleSelect(option.value)}
                      >
                        <span className={`director-approval-radio${on ? " is-on" : ""}`} aria-hidden>
                          <span className="director-approval-radio-dot" />
                        </span>
                        <span className={`director-approval-option-label${on ? " is-on" : ""}`}>{option.label}</span>
                        {option.recommended ? <em className="director-approval-recommended">推荐</em> : null}
                      </button>
                    )
                  })}
                  {/* 产品规则：每道确认题最后必须保留自定义输入，不按 allowCustom 关闭。 */}
                  <label className="director-approval-option is-custom">
                    <span className={`director-approval-radio${customValue.trim() ? " is-on" : ""}`} aria-hidden>
                      <span className="director-approval-radio-dot" />
                    </span>
                    <span className="director-approval-option-label is-custom-label">{SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}</span>
                    <input
                      value={customValue}
                      disabled={terminal !== null}
                      aria-label={SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}
                      placeholder={SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}
                      onChange={(event) => {
                        setCustomValue(event.target.value)
                        setSelectedOption(null)
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && customAnswer) answerCurrent(customAnswer)
                      }}
                    />
                  </label>
                </div>
                <div className="director-approval-footer">
                  <span className="director-approval-pager">
                    <button
                      type="button"
                      aria-label="上一题"
                      disabled={questionIndex === 0 || terminal !== null}
                      onClick={() => { setSelectedOption(null); setCustomValue(""); setQuestionIndex((index) => Math.max(0, index - 1)) }}
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span className="director-approval-dots">
                      {(list || []).map((_, index) => (
                        <button
                          key={index}
                          type="button"
                          aria-label={`第 ${index + 1} 题`}
                          aria-current={index === questionIndex || undefined}
                          disabled={terminal !== null}
                          className={`director-approval-dot${index === questionIndex ? " is-current" : ""}${index < questionIndex ? " is-done" : ""}`}
                          onClick={() => { setSelectedOption(null); setCustomValue(""); setQuestionIndex(index) }}
                        />
                      ))}
                    </span>
                    <button
                      type="button"
                      aria-label="下一题"
                      disabled={last || terminal !== null}
                      onClick={() => { setSelectedOption(null); setCustomValue(""); setQuestionIndex((index) => Math.min((list?.length ?? 1) - 1, index + 1)) }}
                    >
                      <ChevronRight size={14} />
                    </button>
                  </span>
                  <button
                    type="button"
                    aria-label={hasAnswer ? "确认这个方向" : SCRIPT_CLARIFY_SKIP_ONE}
                    title={hasAnswer ? (last ? SCRIPT_CLARIFY_SUBMIT : "下一题") : SCRIPT_CLARIFY_SKIP_ONE}
                    disabled={terminal !== null}
                    className={`director-approval-send${hasAnswer ? " is-armed" : ""}`}
                    onClick={submitArrow}
                  >
                    <ArrowUp size={14} />
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="director-approval-skip-all"
                disabled={terminal !== null}
                onClick={() => onConfirmStep(answersRef.current)}
              >
                {SCRIPT_CLARIFY_SKIP_ALL}
              </button>
            </div>
          ) : (
            <div className="director-clarify is-waiting">
              {streamedQuestions.length ? (
                streamedQuestions.map((key) => (
                  <p key={key} className="director-clarify-echo">
                    {shownTexts[key]}
                    <span className="stream-caret" aria-hidden />
                  </p>
                ))
              ) : (
                <div className="director-pixel-loader">
                  <span className="director-pixel-grid" aria-hidden>
                    {Array.from({ length: 9 }, (_, index) => <span key={index} />)}
                  </span>
                  <span className="director-pixel-label">{clarifyTitle}</span>
                </div>
              )}
            </div>
          )}
            </div>
          </div>
          {!settled && !tailFollowing ? (
            <button type="button" className="director-jump-latest" onClick={jumpToLatest}>
              <ArrowDown size={13} aria-hidden />
              {SCRIPT_JUMP_LATEST_LABEL}
            </button>
          ) : null}
        </div>
      </div>
    )
  }

  const directionAnswers = clarifications || []
  // 直播工作区：已完成/失败环节压成单行记录（点开抽屉看全文），
  // 正在运行的环节全宽直播，不再使用折叠卡片。
  const feedAgents = TRANSCRIPT_AGENTS.filter((agent) => {
    const status = agentRows.find((row) => row.id === agent)?.status
    return status && status !== "pending"
  })
  const liveAgent = historyMode
    ? undefined
    : feedAgents.find((agent) => agentRows.find((row) => row.id === agent)?.status === "running")
  const doneAgents = feedAgents.filter((agent) => agent !== liveAgent)

  const renderBlockBody = (agent: string) => {
    if (agent === "research") {
      const text = shown("research", "notes")
      return text ? <p className="director-block-text">{text}{streamLive ? <span className="stream-caret" aria-hidden /> : null}</p> : null
    }
    if (agent === "script") {
      const title = shown("script", "title")
      const summary = shown("script", "summary")
      const fullStory = shown("script", "fullStory")
      if (!title && !summary && !fullStory) return null
      return (
        <div className="director-stream-article">
          {title ? <h3 className="director-stream-title">{title}</h3> : null}
          {summary ? <p className="director-stream-lead">{summary}</p> : null}
          {fullStory ? <div className="director-stream-text"><StoryParagraphs text={fullStory} active={runningAgent?.id === "script"} /></div> : null}
        </div>
      )
    }
    if (agent === "art_style") {
      if (!artStyleName) return null
      return (
        <div className="director-style-card">
          <Palette size={16} />
          <div className="director-style-card-copy">
            <strong>{artStyleName}</strong>
            <span>{SCRIPT_ART_BLOCK_TITLE}</span>
          </div>
          {onOpenPicker ? (
            <Button size="small" onClick={onOpenPicker}>{SCRIPT_ART_CHANGE_LABEL}</Button>
          ) : null}
        </div>
      )
    }
    if (agent === "characters") {
      const cards = sortedItems("characters", "characters")
      const props = sortedItems("characters", "props")
      const activeIndexVal = activeIndex["characters|name"] ?? activeIndex["characters|description"]
      const isPropActive = props.length > 0 || (cards.length > 0 && activeIndexVal !== undefined && activeIndexVal < cards.length)
      const activeCharLive = !isPropActive && activeIndexVal !== undefined && activeIndexVal === cards.length
      const activePropLive = isPropActive && activeIndexVal !== undefined && activeIndexVal === props.length

      if (!cards.length && !props.length && !activeCharLive && !activePropLive) return null

      const charIndices = cards.map((_, i) => i)
      if (activeCharLive) charIndices.push(cards.length)

      const propIndices = props.map((_, i) => i)
      if (activePropLive) propIndices.push(props.length)

      return (
        <div className="director-block-cards">
          {charIndices.map((index) => {
            const item = items["characters|characters"]?.[index]
            const isActive = activeCharLive && index === cards.length
            const name = (isActive ? shown("characters", "name", index) : "") || itemText(item, "name")
            const role = (isActive ? shown("characters", "role", index) : "") || itemText(item, "role")
            const description = (isActive ? shown("characters", "description", index) : "") || itemText(item, "description")
            const caret = isActive ? <span className="stream-caret" aria-hidden /> : null
            return (
              <div key={`char-${index}`} className={`director-block-card${isActive ? " is-active" : ""}`}>
                <strong>
                  {name || (isActive ? "正在生成角色…" : "角色")}
                  {isActive && !name && !role && !description ? caret : null}
                </strong>
                {role ? <em>{role}{isActive && role && !description ? caret : null}</em> : null}
                <p>{description}{isActive && description ? caret : null}</p>
              </div>
            )
          })}
          {propIndices.map((index) => {
            const item = items["characters|props"]?.[index]
            const isActive = activePropLive && index === props.length
            const name = (isActive ? shown("characters", "name", index) : "") || itemText(item, "name")
            const description = (isActive ? shown("characters", "description", index) : "") || itemText(item, "description")
            const caret = isActive ? <span className="stream-caret" aria-hidden /> : null
            return (
              <div key={`prop-${index}`} className={`director-block-card${isActive ? " is-active" : ""}`}>
                <strong>
                  {name || (isActive ? "正在生成道具…" : "道具")}
                  {isActive && !name && !description ? caret : null}
                </strong>
                <em>道具</em>
                <p>{description}{isActive && description ? caret : null}</p>
              </div>
            )
          })}
        </div>
      )
    }
    if (agent === "locations") {
      const cards = sortedItems("locations", "locations")
      const activeIndexVal = activeIndex["locations|name"] ?? activeIndex["locations|description"]
      const activeLocLive = activeIndexVal !== undefined && activeIndexVal === cards.length

      if (!cards.length && !activeLocLive) return null
      
      const indices = cards.map((_, i) => i)
      if (activeLocLive) indices.push(cards.length)

      return (
        <div className="director-block-cards">
          {indices.map((index) => {
            const item = items["locations|locations"]?.[index]
            const isActive = activeLocLive && index === cards.length
            const name = (isActive ? shown("locations", "name", index) : "") || itemText(item, "name")
            const description = (isActive ? shown("locations", "description", index) : "") || itemText(item, "description")
            const caret = isActive ? <span className="stream-caret" aria-hidden /> : null
            return (
              <div key={`loc-${index}`} className={`director-block-card${isActive ? " is-active" : ""}`}>
                <strong>
                  {name || (isActive ? "正在生成场景…" : "场景")}
                  {isActive && !name && !description ? caret : null}
                </strong>
                <p>{description}{isActive && description ? caret : null}</p>
              </div>
            )
          })}
        </div>
      )
    }
    if (agent === "storyboard") {
      const scenes = sortedItems("storyboard", "scenes")
      const shots = sortedItems("storyboard", "shots")
      // 当前镜头 = 打字机视角（闭合但未打印完的镜头保持展开），见 storyboardPrintingOrdinal。
      const activeShot = storyboardPrintingOrdinal
      const activeScene = activeIndex["storyboard|scenes"]
      // 尚无 agent_item（JSON 未闭合）的镜头不在 items 里，需追加到列表尾部。
      const activeShotLive = activeShot !== undefined && items["storyboard|shots"]?.[activeShot] === undefined
      const activeSceneLive = activeScene !== undefined && items["storyboard|scenes"]?.[activeScene] === undefined
      if (!scenes.length && !shots.length && !activeShotLive && !activeSceneLive) return null
      const shotIndices = activeShotLive && activeShot !== undefined && activeShot >= shots.length
        ? [...shots.map((_, index) => index), activeShot]
        : shots.map((_, index) => index)
      const seenSceneTitles = new Set<string>()
      const sceneTitles = scenes
        .map((item) => itemText(item, "title"))
        .filter((title) => {
          if (!title || seenSceneTitles.has(title)) return false
          seenSceneTitles.add(title)
          return true
        })
      // 直播中用 TaskRows 式镜头行：完成镜头收成一行（镜号 + 标题），
      // 只有当前镜头展开实时流式文字（不截断），写完自动切到下一镜。
      const liveStoryboard = runningAgent?.id === "storyboard" && !historyMode
      if (liveStoryboard) {
        // 打磨阶段（按秒分配/校验衔接）：阶段进度面板 + 当前镜头直播字幕。
        const polish = parseStoryboardPhase(runningAgent?.message)
        if (polish) {
          const shotCount = shots.length
          const rangeStart = polish.range?.[0]
          const rangeEnd = polish.range?.[1]
          // 当前镜号优先取后端消息里的「正在第 N 镜」；缺失时用直播流序号推
          // 导（分块内第 ordinal 个对象 = rangeStart + ordinal，模型按序输出）。
          const currentShot = polish.currentShot
            ?? (rangeStart !== undefined
              ? rangeStart + (polishLive?.ordinal ?? 0)
              : undefined)
          const shotState = (no: number): string => {
            if (currentShot !== undefined) {
              if (no < currentShot) return " is-done"
              if (no === currentShot) return " is-active"
              return ""
            }
            if (rangeStart !== undefined && no < rangeStart) return " is-done"
            if (rangeStart !== undefined && rangeEnd !== undefined && no >= rangeStart && no <= rangeEnd) return " is-active"
            return ""
          }
          const knownShot = currentShot !== undefined ? items["storyboard|shots"]?.[currentShot - 1] : undefined
          const liveTitle = itemText(knownShot, "title")
          const liveDescription = polishLive?.description || ""
          const liveDialogue = polishLive?.dialogue || ""
          const caret = <span className="stream-caret" aria-hidden />
          return (
            <div className="director-phase-panel">
              <div className="director-phase-head">
                <span className="director-phase-title">
                  {polish.title}{polish.total && polish.total > 1 && polish.index ? ` (${polish.index}/${polish.total})` : ""}
                </span>
              </div>
              {shotCount > 0 ? (
                <div className="director-phase-shots">
                  {Array.from({ length: shotCount }, (_, i) => i + 1).map((no) => (
                    <span key={no} className={`director-phase-chip${shotState(no)}`}>{no}</span>
                  ))}
                </div>
              ) : (
                <div className="director-live-skeleton" aria-hidden>
                  <span style={{ width: "52%" }} />
                  <span style={{ width: "70%" }} />
                </div>
              )}
              <div className="director-shot-stream-row is-active director-phase-live">
                <span className="director-shot-no">{currentShot ?? "…"}</span>
                <div className="director-shot-stream-text">
                  {liveTitle
                    ? <strong>{liveDescription || liveDialogue ? liveTitle : <>{liveTitle}{caret}</>}</strong>
                    : <strong className="is-skeleton">{currentShot !== undefined ? `正在打磨第 ${currentShot} 镜…` : `正在${polish.title}…`}</strong>}
                  {liveDescription ? <p>{liveDialogue ? liveDescription : <>{liveDescription}{caret}</>}</p> : null}
                  {liveDialogue ? <p className="is-dialogue">「{liveDialogue}{caret}」</p> : null}
                </div>
              </div>
              {polish.chars ? (
                <div className="director-phase-meta is-live">
                  <span className="director-live-dot" aria-hidden />
                  已收 {polish.chars.toLocaleString()} 字
                </div>
              ) : null}
            </div>
          )
        }
        return (
          <div className="director-block-shots">
            {sceneTitles.map((title) => (
              <div key={`scene-${title}`} className="director-shot-scene">【{title}】</div>
            ))}
            {activeSceneLive && shown("storyboard", "title", activeScene) ? (
              <div className="director-shot-scene is-active">
                【{shown("storyboard", "title", activeScene)}
                <span className="stream-caret" aria-hidden />】
              </div>
            ) : null}
            {shotIndices.map((index) => {
              const done = items["storyboard|shots"]?.[index]
              const isActive = activeShot !== undefined && index === activeShot
              if (!isActive) {
                const title = itemText(done, "title")
                return (
                  <div key={`shot-${index}`} className="director-shot-stream-row is-done" title={itemText(done, "description")}>
                    <span className="director-shot-no">{index + 1}</span>
                    <span className="director-shot-stream-title">{title || `第 ${index + 1} 镜`}</span>
                    <CheckCircle2 size={12} className="director-shot-stream-check" aria-hidden />
                  </div>
                )
              }
              const title = shown("storyboard", "title", index)
              const description = shown("storyboard", "description", index)
              const dialogue = shown("storyboard", "dialogue", index)
              const caret = <span className="stream-caret" aria-hidden />
              return (
                <div key={`shot-${index}`} className="director-shot-stream-row is-active">
                  <span className="director-shot-no">{index + 1}</span>
                  <div className="director-shot-stream-text">
                    {title
                      ? <strong>{description || dialogue ? title : <>{title}{caret}</>}</strong>
                      : <strong className="is-skeleton">正在写第 {index + 1} 镜…</strong>}
                    {description ? <p>{dialogue ? description : <>{description}{caret}</>}</p> : null}
                    {dialogue ? <p className="is-dialogue">「{dialogue}{caret}」</p> : null}
                  </div>
                </div>
              )
            })}
          </div>
        )
      }
      return (
        <div className="director-block-shots">
          {sceneTitles.map((title) => (
            <div key={`scene-${title}`} className="director-shot-scene">【{title}】</div>
          ))}
          {activeSceneLive && shown("storyboard", "title", activeScene) ? (
            <div className="director-shot-scene is-active">
              【{shown("storyboard", "title", activeScene)}
              <span className="stream-caret" aria-hidden />】
            </div>
          ) : null}
          {shotIndices.map((index) => {
            const done = items["storyboard|shots"]?.[index]
            const isActive = activeShotLive && index === activeShot
            const title = (isActive ? shown("storyboard", "title", index) : "") || itemText(done, "title")
            const description = (isActive ? shown("storyboard", "description", index) : "") || itemText(done, "description")
            const dialogue = (isActive ? shown("storyboard", "dialogue", index) : "") || itemText(done, "dialogue")
            return (
              <div key={`shot-${index}`} className={`director-shot-row${isActive ? " is-active" : ""}`}>
                <span className="director-shot-no">{index + 1}</span>
                <span className="director-shot-copy">
                  {title
                    ? <strong>{title}{isActive ? <span className="stream-caret" aria-hidden /> : null}</strong>
                    : <strong className="is-skeleton">正在写第 {index + 1} 镜…</strong>}
                  {description ? <span>{description}</span> : null}
                  {dialogue ? <em>「{dialogue}」</em> : null}
                </span>
              </div>
            )
          })}
        </div>
      )
    }
    if (agent === "voice") {
      const rows = sortedItems("voice", "characters")
      if (!rows.length) return null
      return (
        <div className="director-block-voice">
          {rows.map((item, index) => (
            <div key={index} className="director-voice-row">
              <span>{itemText(item, "name")}</span>
              <em>→ {itemText(item, "voiceId")}</em>
            </div>
          ))}
        </div>
      )
    }
    if (agent === "music") {
      const music = shown("music", "globalMusic")
      const soundscape = shown("music", "globalSoundscape")
      if (!music && !soundscape) return null
      return (
        <div className="director-block-text">
          {music ? <p>配乐：{music}</p> : null}
          {soundscape ? <p>环境声：{soundscape}</p> : null}
        </div>
      )
    }
    return null
  }

  const blockPreview = (agent: string): string => {
    if (agent === "script") return shown("script", "title") || "剧本已完成"
    if (agent === "research") {
      const notes = shown("research", "notes").trim()
      if (!notes) return "研究已完成"
      const firstLine = notes.split("\n").find((line) => line.trim()) || notes
      return firstLine.length > 26 ? `${firstLine.slice(0, 26)}…` : firstLine
    }
    if (agent === "art_style") return artStyleName ? `画风：${artStyleName}` : "画风已选定"
    if (agent === "characters") {
      const count = sortedItems("characters", "characters").length
      const props = sortedItems("characters", "props").length
      return `已建立 ${count} 个角色${props ? `、${props} 个道具` : ""}`
    }
    if (agent === "locations") return `已建立 ${sortedItems("locations", "locations").length} 个场景`
    if (agent === "storyboard") return `已拆出 ${sortedItems("storyboard", "shots").length} 个镜头`
    if (agent === "voice") return `已分配 ${sortedItems("voice", "characters").length} 个声线`
    if (agent === "music") return "配乐方案已完成"
    return ""
  }

  /* 官方 tool-chips 行语法：状态图标 + 环节名 + 摘要 chip，整行点开抽屉。
     失败重试由任务栏/任务面板的官方重试 pill 承担，这里不再放第二个入口；
     已完成环节行尾提供「重新生成」入口，与任务栏行内按钮一致（范围在弹窗里确认）。 */
  const renderStepRow = (agent: string) => {
    const row = agentRows.find((item) => item.id === agent)
    const status = row?.status || "pending"
    const failed = status === "failed"
    // 仅在非直播状态（历史回放或已终态）展示重新生成，避免与进行中的生成混淆。
    const canRegenerate = Boolean(onRegenerateAgent) && status === "completed" && settled
    return (
      <div key={agent} className={`director-step-row is-${status}`}>
        <button
          type="button"
          className="director-step-row-head"
          title={`${RECIPE_AGENT_LABELS[agent as keyof typeof RECIPE_AGENT_LABELS] || agent} · ${SCRIPT_STEP_VIEW_LABEL}`}
          onClick={() => setViewingAgent(agent)}
        >
          {/* 官方 tool-chips 行首语法：状态图标与 chevron 同位叠放，hover 时图标淡出、chevron 旋入。 */}
          <span className="director-step-row-icon" aria-hidden>
            {failed
              ? <XCircle size={14} className="is-failed" />
              : <CheckCircle2 size={14} className="is-done" />}
            <ChevronRight size={12} className="director-step-row-icon-chevron" />
          </span>
          <span className="director-step-row-name">{RECIPE_AGENT_LABELS[agent as keyof typeof RECIPE_AGENT_LABELS] || agent}</span>
          <span className="director-step-row-chip">{blockPreview(agent)}</span>
        </button>
        {canRegenerate ? (
          <button
            type="button"
            className="director-step-regen"
            title={SCRIPT_STEP_REGENERATE_TITLE}
            onClick={(event) => {
              event.stopPropagation()
              onRegenerateAgent?.(agent)
            }}
          >
            <span className="director-step-regen-icon" aria-hidden><RegenerateIcon /></span>
          </button>
        ) : null}
      </div>
    )
  }

  /* 当前运行环节：唯一的全宽直播卡片（官方 thinking.tsx 工作中语法），不可折叠。
     无流式产出的环节（如画风选择）渲染骨架占位行，避免直播卡只剩标题。 */
  const renderLiveBlock = (agent: string) => {
    const row = agentRows.find((item) => item.id === agent)
    const body = renderBlockBody(agent)
    const BlockIcon = AGENT_BLOCK_ICONS[agent]
    return (
      <section key={agent} className="director-block is-running is-live">
        <div className="director-block-head">
          <span className="director-step-spinner" aria-hidden />
          {BlockIcon ? <BlockIcon size={13} className="director-block-icon" /> : null}
          <span className="director-block-title">{RECIPE_AGENT_LABELS[agent as keyof typeof RECIPE_AGENT_LABELS] || agent}</span>
          {row?.message && !(agent === "storyboard" && parseStoryboardPhase(row.message)) ? <span className="director-step-status">{row.message}</span> : null}
        </div>
        <div className="director-block-body">
          {body || (
            <div className="director-live-skeleton" aria-hidden>
              <span style={{ width: "38%" }} />
              <span style={{ width: "72%" }} />
              <span style={{ width: "56%" }} />
              <span style={{ width: "64%" }} />
            </div>
          )}
        </div>
      </section>
    )
  }

  const openAgentTranscript = (id: string) => {
    if (TRANSCRIPT_AGENT_SET.has(id)) setViewingAgent(id)
  }

  const directionChips = directionAnswers.length ? (
    <div className="director-direction-chips" aria-label={SCRIPT_DIRECTION_LABEL}>
      <span className="director-direction-label">{SCRIPT_DIRECTION_LABEL}</span>
      {directionAnswers.map((item, index) => (
        <span key={index} className="director-direction-chip">{item.question} → {item.answer}</span>
      ))}
    </div>
  ) : null

  const taskRowsProps = {
    rows: agentRows,
    running: !terminal && !historyMode,
    elapsedSec: historyMode ? -1 : elapsed,
    onRetry: onRetryAgent,
    onRegenerate: onRegenerateAgent,
    onOpen: openAgentTranscript,
    previews: taskPreviews,
  }

  // 桌面端：任务列表走左侧窄栏（只负责进度全景），右侧整块给直播时间线；
  // 移动端空间有限，保留原折叠面板置于时间线上方。
  const showTaskRail = phase === "pipeline" && !isMobile
  const streamCard = (
    <div className={`director-script-stream is-transcript${terminal ? " is-terminal" : ""}`} data-stream-live={streamLive || undefined}>
      {head}
      {phase === "pipeline" && !showTaskRail ? <DirectorTaskRows {...taskRowsProps} /> : null}
      <div className="director-stream-wrap">
        <div className="director-stream-body" ref={bodyRef} onScroll={handleBodyScroll}>
          <div className="director-stream-feed" ref={feedRef}>
            {userBubble}
            {directionChips}
            {!feedAgents.length ? (
              <div className="director-pixel-loader" aria-hidden>
                <span className="director-pixel-grid">
                  {Array.from({ length: 9 }, (_, index) => <span key={index} />)}
                </span>
                <span className="director-pixel-label">{SCRIPT_STREAM_TITLE}</span>
              </div>
            ) : (
              <div className="director-step-feed">
                {doneAgents.map((agent) => renderStepRow(agent))}
                {liveAgent ? renderLiveBlock(liveAgent) : null}
              </div>
            )}
            <div ref={footerRef}>{transcriptFooter}</div>
          </div>
        </div>
        {!settled && !tailFollowing ? (
          <button type="button" className="director-jump-latest" onClick={jumpToLatest}>
            <ArrowDown size={13} aria-hidden />
            {SCRIPT_JUMP_LATEST_LABEL}
          </button>
        ) : null}
      </div>
      {!terminal && runningAgent?.id === "script" ? (
        <div className="director-stream-writing">
          {shown("script", "fullStory")
            ? SCRIPT_STREAM_WRITING_LABELS.fullStory
            : shown("script", "summary")
              ? SCRIPT_STREAM_WRITING_LABELS.summary
              : SCRIPT_STREAM_WRITING_LABELS.title}
        </div>
      ) : null}
      <Drawer
        rootClassName="director-agent-drawer"
        open={viewingAgent !== null}
        onClose={() => setViewingAgent(null)}
        width={isMobile ? "100%" : 480}
        destroyOnHidden
        title={
          viewingAgent ? (
            <span className="director-agent-drawer-title">
              {(() => {
                const DrawerIcon = AGENT_BLOCK_ICONS[viewingAgent]
                return DrawerIcon ? <DrawerIcon size={15} aria-hidden /> : null
              })()}
              {RECIPE_AGENT_LABELS[viewingAgent as keyof typeof RECIPE_AGENT_LABELS] || viewingAgent}
              <em className={`director-agent-drawer-state is-${agentRows.find((row) => row.id === viewingAgent)?.status || "completed"}`}>
                {agentRows.find((row) => row.id === viewingAgent)?.status === "failed"
                  ? "失败"
                  : agentRows.find((row) => row.id === viewingAgent)?.status === "running"
                    ? "进行中"
                    : "已完成"}
              </em>
            </span>
          ) : null
        }
      >
        {viewingAgent ? (
          <div className="director-agent-drawer-body">
            {renderBlockBody(viewingAgent) || <p className="director-agent-drawer-empty">{SCRIPT_STEP_EMPTY_LABEL}</p>}
          </div>
        ) : null}
      </Drawer>
    </div>
  )

  if (!showTaskRail) return streamCard
  return (
    <div className="director-script-layout">
      <aside className="director-task-rail">
        <DirectorTaskRows {...taskRowsProps} variant="rail" />
      </aside>
      {streamCard}
    </div>
  )
}
