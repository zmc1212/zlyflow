import { Button } from "antd"
import {
  ArrowUp, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle, Clapperboard, FileText, Loader2, MapPinned,
  Mic2, Music2, Palette, Search, Users, XCircle,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  SCRIPT_ART_BLOCK_TITLE, SCRIPT_ART_CHANGE_LABEL, SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER, SCRIPT_CLARIFY_HINT,
  SCRIPT_CLARIFY_SKIP_ALL, SCRIPT_CLARIFY_SKIP_ONE, SCRIPT_CLARIFY_SUBMIT, SCRIPT_CLARIFY_TITLE,
  SCRIPT_DIRECTION_LABEL, SCRIPT_HISTORY_TITLE,
  SCRIPT_STREAM_CANCEL_LABEL, SCRIPT_STREAM_STATE_LABELS, SCRIPT_STREAM_TITLE, SCRIPT_STREAM_WRITING_LABELS,
  SCRIPT_USER_BUBBLE_LABEL,
} from "../action-copy"
import type { RecipeAgentStatus, RecipeProject } from "../recipe-model"
import { flattenRecipeShots } from "../recipe-model"
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
export type ClarifyAnswer = { question: string; answer: string }

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
  onCancel: () => void
  onStartPipeline: (answers: ClarifyAnswer[]) => void
}

const TRANSCRIPT_AGENTS = ["research", "script", "art_style", "characters", "locations", "storyboard", "voice", "music"] as const

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
  initialQuestions, clarifications, onOpenPicker, historyMode = false, recipe,
  onCancel, onStartPipeline,
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
  const [manualExpanded, setManualExpanded] = useState<Record<string, boolean>>({})

  // Clarify (approval card) state.
  const [questions, setQuestions] = useState<ClarifyQuestion[] | null>(() => initialQuestions ?? null)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [customValue, setCustomValue] = useState("")
  const [selectedOption, setSelectedOption] = useState<string | null>(null)
  const answersRef = useRef<ClarifyAnswer[]>([])

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
  const followTailRef = useRef(true)

  // 历史回放：活动操作结束后，用已保存的 recipe 一次性重建对话记录
  //（流式数据只在内存里，刷新后靠 recipe 恢复任务面板与产出块）。
  const seededRef = useRef(false)
  useEffect(() => {
    if (!historyMode || !recipe || seededRef.current) return
    // 空的初始 recipe（工程查询未返回）不消费 seed 机会，等真实数据到达再重建。
    const hasContent = Boolean(
      recipe.script?.fullStory?.trim() || recipe.characters?.length || recipe.scenes?.length,
    )
    if (!hasContent) return
    seededRef.current = true
    const texts: Record<string, string> = {}
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
    setTargetTexts(texts)
    setShownTexts(texts)
    setItems(itemsMap)
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

  useEffect(() => {
    const element = bodyRef.current
    if (!element || !followTailRef.current) return
    element.scrollTop = element.scrollHeight
  }, [shownTexts, items, questions, questionIndex])

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

  const sortedItems = (agent: string, field: string): AgentStreamItem[] => {
    const map = items[`${agent}|${field}`]
    if (!map) return []
    return Object.keys(map).map(Number).sort((a, b) => a - b).map((index) => map[index])
  }

  const runningAgent = agentRows.find((row) => row.status === "running")
  const settled = terminal !== null || historyMode
  const headTitle = terminal
    ? SCRIPT_STREAM_STATE_LABELS[terminal.kind]
    : historyMode
      ? SCRIPT_HISTORY_TITLE
      : phase === "pipeline" ? SCRIPT_STREAM_TITLE : SCRIPT_CLARIFY_TITLE
  const headDetail = terminal
    ? (terminal.message || (terminal.kind === "done" ? "成稿已就绪，可以在下方查看与编辑。" : "已停止本次创作。"))
    : phase === "clarify-stream"
      ? "正在根据你的创意构思创作方向问题…"
      : phase === "clarify-ask"
        ? SCRIPT_CLARIFY_HINT
        : historyMode
          ? "以下是本次生成的完整过程记录。"
          : `${runningAgent?.message || statusText || "正在连接 AI 导演…"}${elapsed > 0 ? ` · 已进行 ${formatElapsed(elapsed)}` : ""}`

  const answerCurrent = (value: string) => {
    const list = questions
    if (!list) return
    const current = list[questionIndex]
    if (!current) return
    const next = [...answersRef.current, { question: current.question, answer: value }]
    answersRef.current = next
    setCustomValue("")
    if (questionIndex + 1 < list.length) {
      setQuestionIndex(questionIndex + 1)
    } else {
      onStartPipeline(next)
    }
  }

  const skipOne = () => {
    const list = questions
    if (!list) return
    setCustomValue("")
    if (questionIndex + 1 < list.length) {
      setQuestionIndex(questionIndex + 1)
    } else {
      onStartPipeline(answersRef.current)
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
      {!settled && (
        <Button size="small" danger loading={cancelRequested} disabled={cancelRequested} onClick={onCancel}>
          {SCRIPT_STREAM_CANCEL_LABEL}
        </Button>
      )}
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
        <div
          className="director-stream-body"
          ref={bodyRef}
          onScroll={(event) => {
            const element = event.currentTarget
            followTailRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
          }}
        >
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
                  {current.allowCustom !== false ? (
                    <label className="director-approval-option is-custom">
                      <span className="director-approval-radio" aria-hidden />
                      <input
                        value={customValue}
                        disabled={terminal !== null}
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
                  ) : null}
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
                onClick={() => onStartPipeline(answersRef.current)}
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
                  <span className="director-pixel-label">{SCRIPT_CLARIFY_TITLE}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  const directionAnswers = clarifications || []
  const visibleBlocks = TRANSCRIPT_AGENTS.filter((agent) => {
    const status = agentRows.find((row) => row.id === agent)?.status
    return status && status !== "pending"
  })

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
      if (!cards.length && !props.length) return null
      return (
        <div className="director-block-cards">
          {cards.map((item, index) => (
            <div key={index} className="director-block-card">
              <strong>{itemText(item, "name") || "角色"}</strong>
              {itemText(item, "role") ? <em>{itemText(item, "role")}</em> : null}
              <p>{shown("characters", "description", index) || itemText(item, "description")}</p>
            </div>
          ))}
          {props.length ? (
            <div className="director-block-props">
              {props.map((item, index) => <span key={index} className="director-prop-chip">道具 · {itemText(item, "name")}</span>)}
            </div>
          ) : null}
        </div>
      )
    }
    if (agent === "locations") {
      const cards = sortedItems("locations", "locations")
      if (!cards.length) return null
      return (
        <div className="director-block-cards">
          {cards.map((item, index) => (
            <div key={index} className="director-block-card">
              <strong>{itemText(item, "name") || "场景"}</strong>
              <p>{shown("locations", "description", index) || itemText(item, "description")}</p>
            </div>
          ))}
        </div>
      )
    }
    if (agent === "storyboard") {
      const scenes = sortedItems("storyboard", "scenes")
      const shots = sortedItems("storyboard", "shots")
      const activeShot = activeIndex["storyboard|shots"]
      const activeScene = activeIndex["storyboard|scenes"]
      // 活跃镜头/场景尚无 agent_item（JSON 未闭合），用 delta 流式值实时打印。
      const activeShotLive = activeShot !== undefined && items["storyboard|shots"]?.[activeShot] === undefined
      const activeSceneLive = activeScene !== undefined && items["storyboard|scenes"]?.[activeScene] === undefined
      if (!scenes.length && !shots.length && !activeShotLive && !activeSceneLive) return null
      const shotIndices = activeShotLive ? [...shots.map((_, index) => index), activeShot as number] : shots.map((_, index) => index)
      const seenSceneTitles = new Set<string>()
      const sceneTitles = scenes
        .map((item) => itemText(item, "title"))
        .filter((title) => {
          if (!title || seenSceneTitles.has(title)) return false
          seenSceneTitles.add(title)
          return true
        })
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
    if (agent === "research") return "研究已完成"
    return ""
  }

  return (
    <div className={`director-script-stream is-transcript${terminal ? " is-terminal" : ""}`} data-stream-live={streamLive || undefined}>
      {head}
      {phase === "pipeline" ? (
        <DirectorTaskRows
          rows={agentRows}
          running={!terminal && !historyMode}
          elapsedSec={historyMode ? -1 : elapsed}
          pinnedOpen={historyMode}
        />
      ) : null}
      {directionAnswers.length ? (
        <div className="director-direction-chips" aria-label={SCRIPT_DIRECTION_LABEL}>
          <span className="director-direction-label">{SCRIPT_DIRECTION_LABEL}</span>
          {directionAnswers.map((item, index) => (
            <span key={index} className="director-direction-chip">{item.question} → {item.answer}</span>
          ))}
        </div>
      ) : null}
      <div
        className="director-stream-body"
        ref={bodyRef}
        onScroll={(event) => {
          const element = event.currentTarget
          followTailRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
        }}
      >
        {userBubble}
        {!visibleBlocks.length ? (
          <div className="director-pixel-loader" aria-hidden>
            <span className="director-pixel-grid">
              {Array.from({ length: 9 }, (_, index) => <span key={index} />)}
            </span>
            <span className="director-pixel-label">{SCRIPT_STREAM_TITLE}</span>
          </div>
        ) : (
          visibleBlocks.map((agent) => {
            const row = agentRows.find((item) => item.id === agent)
            const status = row?.status || "pending"
            const body = renderBlockBody(agent)
            // 实时生成时只展开当前步骤；历史回放默认全部展开，手动点击可折叠。
            const expanded = manualExpanded[agent] ?? (status === "running" || historyMode)
            return (
              <section key={agent} className={`director-block is-${status}${expanded ? " is-expanded" : ""}`}>
                <button
                  type="button"
                  className="director-block-head"
                  onClick={() => setManualExpanded((current) => ({ ...current, [agent]: !expanded }))}
                >
                  {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  {(() => {
                    const BlockIcon = AGENT_BLOCK_ICONS[agent]
                    return BlockIcon ? <BlockIcon size={13} className="director-block-icon" /> : null
                  })()}
                  <span className="director-block-title">{RECIPE_AGENT_LABELS[agent as keyof typeof RECIPE_AGENT_LABELS] || agent}</span>
                  {status === "running" ? <Loader2 size={12} className="is-spin director-block-status" /> : null}
                  {status === "completed" ? <CheckCircle2 size={12} className="director-block-status is-done" /> : null}
                  {status === "failed" ? <XCircle size={12} className="director-block-status is-failed" /> : null}
                  {!expanded ? <span className="director-block-preview">{blockPreview(agent)}</span> : null}
                  {status === "running" && row?.message ? <span className="director-block-preview">{row.message}</span> : null}
                </button>
                {expanded ? <div className="director-block-body">{body}</div> : null}
              </section>
            )
          })
        )}
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
    </div>
  )
}
