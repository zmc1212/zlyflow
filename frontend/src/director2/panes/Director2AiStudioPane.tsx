import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Button, Drawer, Modal, Space, message } from "antd"
import { Boxes, CheckCircle2, Clapperboard, FileText, ListTree, RefreshCw, Wand2, XCircle } from "lucide-react"
import {
  advanceAiOperation,
  aiOperationEventsUrl,
  cancelAiOperation,
  createAiOperation,
  director2ErrorDetail,
  getAiOperation,
  getActiveAiOperation,
  getEpisodeDetail,
  listAssets,
  listDocuments,
  listEpisodes,
  rerunAiStage,
  retryAiOperation,
  reviseAiOperation,
  type Director2AiOperation,
  type Director2Asset,
  type Director2Episode,
  type Director2EpisodeDetail,
  type Director2AiStage,
  type Director2ClarificationQuestion,
} from "../api"
import { SCRIPT_STREAM_CANCEL_LABEL } from "../../director/action-copy"
import DirectorPromptBar from "../../director/components/DirectorPromptBar"
import DirectorTaskRows, { type TaskRow } from "../../director/components/DirectorTaskRows"
import DirectorClarificationCard, { type DirectorClarificationAnswer } from "../../director/components/DirectorClarificationCard"
import DirectorAssetSummaryCard, { type DirectorAssetCardData, type DirectorAssetCardKind } from "../../director/components/DirectorAssetSummaryCard"
import { assetKindFor, normalizeDirectorAssetCard, relateLiveAssetCards } from "../../director/components/director-asset-card"
import DirectorStoryboardLiveBody from "../../director/components/DirectorStoryboardLiveBody"
import { DirectorLiveBlock, DirectorLiveStepChoices, DirectorLiveStepRow, DirectorPathChips, DirectorReviewBlock } from "../../director/components/DirectorLiveStepFeed"
import { stageChoiceEcho, stageChoiceFallbackLabel, stageChoicePathGroups, stageChoicePreviewAnswer, ensureDirector2OpeningQuestions } from "../director2-stage-choices"
import {
  DIRECTOR2_ACTIVE_AI_STATUSES,
  director2AiHeadlineDetail,
  director2CheckpointHeadline,
  director2RailStageStatus,
  deriveDirector2ContentSummary,
  isDirector2AiOperationActive,
  isDirector2AiOperationOccupying,
  isDirector2AwaitingReview,
  isDirector2LastPipelineStage,
  markDirector2AiOperationCancelling,
  mergeDirector2AiStatusEvent,
  mergeDirector2StageCompletion,
  type Director2ContentSummary,
} from "../director2-ai-operation-state"
import { normalizeEpisodeLiveCard, type Director2EpisodeLiveCard } from "../director2-episode-live-card"
import Director2ScriptLiveBody from "../Director2ScriptLiveBody"
import { resolveDirector2ScriptLiveSource, scriptLiveSourceHasContent } from "../director2-script-live-view"
import "../../director/guided-flow.css"
import "../../director/components/director-asset-card.css"

const STORAGE_PREFIX = "director2-ai-operation:"
const STAGES: Array<{ key: Director2AiStage; label: string; message: string; icon: typeof FileText }> = [
  { key: "clarify", label: "创意确认", message: "先把创作方向确认清楚", icon: Wand2 },
  { key: "script", label: "剧本", message: "把一句话创意整理成完整故事", icon: FileText },
  { key: "assets", label: "角色 / 场景 / 道具", message: "固定人物、空间与关键道具", icon: Boxes },
  { key: "episodes", label: "分集", message: "拆分每集结构与戏剧节奏", icon: ListTree },
  { key: "storyboard", label: "分镜", message: "远端模型正在阅读剧本并逐镜写分镜，这一步通常需要几分钟", icon: Clapperboard },
]

type StreamItem = Record<string, unknown>

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stageForAgent(agent: string, fallback: Director2AiStage | null): Director2AiStage {
  if (agent === "clarify") return "clarify"
  if (agent === "script") return "script"
  if (["characters", "locations", "props"].includes(agent)) return "assets"
  if (agent === "episodes") return "episodes"
  if (agent === "storyboard") return fallback === "episodes" ? "episodes" : "storyboard"
  return fallback || "script"
}

function stageRows(operation: Director2AiOperation | null, completed: Set<Director2AiStage>): TaskRow[] {
  return STAGES.map((stage) => {
    const status = director2RailStageStatus(stage.key, operation, completed)
    return {
      id: stage.key,
      label: stage.label,
      status,
      message: status === "review" ? "待确认" : stage.message,
    }
  })
}

function displayItem(item: StreamItem): { title: string; detail: string } {
  const title = String(item.name || item.title || item.heading || item.question || "生成内容")
  const detail = String(item.description || item.summary || item.action || item.dialogue || item.answer || "")
  return { title, detail }
}

export { assetKindFor, normalizeDirectorAssetCard as normalizeAssetCard, relateLiveAssetCards }

export default function Director2AiStudioPane({
  csrfToken,
  projectId,
  onNavigate,
  onBusyChange,
}: {
  csrfToken: string
  projectId: string
  onNavigate: (menu: "content" | "assets" | "workshop") => void
  onBusyChange?: (busy: boolean) => void
}) {
  const [brief, setBrief] = useState("")
  const [operation, setOperation] = useState<Director2AiOperation | null>(null)
  const [questions, setQuestions] = useState<Director2ClarificationQuestion[]>([])
  const [busy, setBusy] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [targetTexts, setTargetTexts] = useState<Record<string, string>>({})
  const [shownTexts, setShownTexts] = useState<Record<string, string>>({})
  const [streamItems, setStreamItems] = useState<Record<string, StreamItem>>({})
  const [activeIndex, setActiveIndex] = useState<Record<string, number>>({})
  const [stageMessages, setStageMessages] = useState<Partial<Record<Director2AiStage, string>>>({})
  const [viewingStage, setViewingStage] = useState<Director2AiStage | null>(null)
  const [contentSummary, setContentSummary] = useState<Director2ContentSummary | null>(null)
  const [savedAssets, setSavedAssets] = useState<Director2Asset[]>([])
  const [savedEpisodes, setSavedEpisodes] = useState<Director2Episode[]>([])
  const [savedEpisodeDetails, setSavedEpisodeDetails] = useState<Director2EpisodeDetail[]>([])
  const [feedback, setFeedback] = useState("")
  const [revisionNote, setRevisionNote] = useState("")
  const [feedbackMode, setFeedbackMode] = useState(false)
  const sourceRef = useRef<EventSource | null>(null)
  const targetTextsRef = useRef(targetTexts)
  const operationRef = useRef(operation)
  const streamBodyRef = useRef<HTMLDivElement | null>(null)
  const streamFeedRef = useRef<HTMLDivElement | null>(null)
  const streamFollowTailRef = useRef(true)
  const streamStageRef = useRef<Director2AiStage | null>(null)
  const streamActiveRef = useRef(false)
  const storageKey = `${STORAGE_PREFIX}${projectId}`

  targetTextsRef.current = targetTexts
  operationRef.current = operation
  const active = isDirector2AiOperationActive(operation)
  const awaitingReview = isDirector2AwaitingReview(operation)
  const checkpointTitle = director2CheckpointHeadline(operation)
  // 有 pipeline 任务时完成态以任务记录为准；无任务时才用项目存量点亮步骤。
  const completed = useMemo(() => mergeDirector2StageCompletion(operation, contentSummary), [operation, contentSummary])
  const hasContent = Boolean(
    contentSummary && (contentSummary.scriptCount > 0 || contentSummary.assetCount > 0 || contentSummary.episodeCount > 0 || contentSummary.shotCount > 0),
  )
  const contentHeroDetail = useMemo(() => {
    if (!contentSummary) return ""
    const parts: string[] = []
    if (contentSummary.scriptCount) parts.push(`${contentSummary.scriptCount} 篇剧本`)
    if (contentSummary.assetCount) parts.push(`${contentSummary.assetCount} 项角色 / 场景 / 道具`)
    if (contentSummary.episodeCount) parts.push(`${contentSummary.episodeCount} 集`)
    if (contentSummary.shotCount) parts.push(`${contentSummary.shotCount} 个分镜`)
    return `项目已有${parts.join("、")}，左侧步骤对应当前就绪情况，可以继续输入创意推进剩余阶段。`
  }, [contentSummary])
  const questionMode = operation?.kind === "clarify" && operation.status === "succeeded" && questions.length > 0
  const openingQuestions = useMemo(
    () => (operation?.kind === "clarify" || operation?.current_stage === "clarify" ? ensureDirector2OpeningQuestions(questions) : questions),
    [operation?.kind, operation?.current_stage, questions],
  )
  const openingClarify = operation?.kind === "pipeline" && operation.current_stage === "clarify" && (operation.status === "revising" || Boolean(questions.length && operation.status === "clarifying"))
  const stageQuestionMode = operation?.status === "revising" && questions.length > 0
  const done = operation?.status === "succeeded" && operation.kind === "pipeline"
  const currentStage = STAGES.find((stage) => stage.key === (operation?.awaiting_stage || operation?.current_stage))
  const followFeed = active || questionMode || stageQuestionMode || awaitingReview
  const rows = useMemo(() => stageRows(operation, completed), [operation, completed])
  const pathGroups = useMemo(
    () => stageChoicePathGroups(operation).map((group) => ({
      id: group.stage,
      label: STAGES.find((stage) => stage.key === group.stage)?.label || group.stage,
      items: group.items,
    })),
    [operation],
  )

  // 直播内容（尤其是分镜逐镜输出）会在同一个滚动容器里持续增长。
  // 直播开始、阶段切换或询问卡就绪时贴住底部；内容尺寸变化时继续跟随，
  // 避免最新镜头或询问卡底部操作被容器裁掉。用户手动上滚后暂停跟随，
  // 回到底部后会自动恢复。
  const streamStage = operation?.current_stage || null
  useEffect(() => {
    if (!followFeed) {
      streamActiveRef.current = false
      return
    }
    const body = streamBodyRef.current
    const feed = streamFeedRef.current
    if (!body) return
    if ((active && !streamActiveRef.current) || streamStageRef.current !== streamStage || questionMode || stageQuestionMode || awaitingReview) {
      streamFollowTailRef.current = true
    }
    streamActiveRef.current = active
    streamStageRef.current = streamStage
    const scrollToBottom = () => {
      if (streamFollowTailRef.current || questionMode || stageQuestionMode || awaitingReview) body.scrollTop = body.scrollHeight
    }
    scrollToBottom()
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(scrollToBottom)
    observer.observe(body)
    if (feed) observer.observe(feed)
    return () => observer.disconnect()
  }, [active, awaitingReview, followFeed, questionMode, questions.length, stageQuestionMode, streamStage])

  const handleStreamScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const body = event.currentTarget
    streamFollowTailRef.current = body.scrollHeight - body.scrollTop - body.clientHeight < 48
  }

  useEffect(() => { onBusyChange?.(active) }, [active, onBusyChange])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setShownTexts((current) => {
        let next: Record<string, string> | null = null
        for (const [key, goal] of Object.entries(targetTextsRef.current)) {
          const shown = (next ?? current)[key] || ""
          if (shown === goal) continue
          if (!next) next = { ...current }
          next[key] = goal.startsWith(shown)
            ? goal.slice(0, shown.length + Math.min(goal.length - shown.length, goal.length - shown.length > 120 ? 14 : 4))
            : goal
        }
        return next ?? current
      })
    }, 32)
    return () => window.clearInterval(timer)
  }, [])

  function closeEvents() {
    sourceRef.current?.close()
    sourceRef.current = null
  }

  function persistOperation(next: Director2AiOperation | null) {
    setOperation(next)
    operationRef.current = next
    if (next) window.localStorage.setItem(storageKey, next.id)
    else window.localStorage.removeItem(storageKey)
  }

  function applyOperation(next: Director2AiOperation) {
    persistOperation(next)
    const restoredGoal = typeof next.request.goal === "string" ? next.request.goal.trim() : ""
    if (restoredGoal) setBrief((current) => current || restoredGoal)
    if (next.result.questions) {
      const opening = next.kind === "clarify" || next.current_stage === "clarify"
      setQuestions(opening ? ensureDirector2OpeningQuestions(next.result.questions) : next.result.questions)
    } else if (next.status !== "revising" && next.status !== "clarifying") setQuestions([])
    const liveMessage = next.result.message?.trim()
    if (liveMessage && next.current_stage) {
      setStageMessages((current) => ({ ...current, [next.current_stage as Director2AiStage]: liveMessage }))
    }
    if (!DIRECTOR2_ACTIVE_AI_STATUSES.has(next.status)) closeEvents()
  }

  async function refreshOperation(id: string, connect = false, discardOnError = false): Promise<Director2AiOperation | null> {
    try {
      const next = await getAiOperation(projectId, id)
      applyOperation(next)
      if (connect && DIRECTOR2_ACTIVE_AI_STATUSES.has(next.status)) subscribe(next)
      return next
    } catch {
      if (discardOnError) {
        persistOperation(null)
        closeEvents()
      }
      return null
    }
  }

  // 项目同一时间最多一个进行中的 AI 任务；本地存储丢失（换浏览器、清缓存）时也必须能重新接管它。
  async function adoptActiveOperation(): Promise<Director2AiOperation | null> {
    try {
      const activeOp = await getActiveAiOperation(projectId)
      if (!activeOp || !isDirector2AiOperationOccupying(activeOp)) return null
      applyOperation(activeOp)
      if (isDirector2AiOperationActive(activeOp)) subscribe(activeOp)
      return activeOp
    } catch {
      return null
    }
  }

  // 进入 AI 模式时按项目真实存量统计各阶段（与手动编辑共享同一批数据）；
  // AI 任务落定（成功 / 失败 / 取消）后再刷新一次，让流水新写入的内容即时点亮。
  const refreshContentSummary = useCallback(async () => {
    try {
      const [documents, assets, episodes] = await Promise.all([
        listDocuments(projectId),
        listAssets(projectId),
        listEpisodes(projectId),
      ])
      setSavedAssets(assets)
      setSavedEpisodes(episodes)
      setContentSummary(deriveDirector2ContentSummary({ documents, assets, episodes }))
    } catch { /* 统计失败时保留现状，仅影响左侧步骤亮度 */ }
  }, [projectId])

  const hadActiveOperationRef = useRef(false)
  useEffect(() => {
    if (active) {
      hadActiveOperationRef.current = true
      return
    }
    if (hadActiveOperationRef.current) {
      hadActiveOperationRef.current = false
      void refreshContentSummary()
    }
  }, [active, refreshContentSummary])

  // 旧任务可能没有保存 Recipe 快照，但适配层已将分集/Beat 写入项目表。
  // 终态主动读取一次，确保刷新后打开抽屉仍能看到这些可继续编辑的内容。
  useEffect(() => {
    if (!operation || !["failed", "cancelled", "succeeded"].includes(operation.status)) return
    void refreshContentSummary()
    let disposed = false
    void listEpisodes(projectId).then(async (episodes) => {
      if (disposed) return
      setSavedEpisodes(episodes)
      const details = await Promise.all(episodes.map((episode) => getEpisodeDetail(projectId, episode.id).catch(() => null)))
      if (!disposed) setSavedEpisodeDetails(details.filter((item): item is Director2EpisodeDetail => Boolean(item)))
    }).catch(() => { /* 抽屉仍可使用流式/Recipe 快照 */ })
    return () => { disposed = true }
  }, [projectId, operation?.id, operation?.status, refreshContentSummary])

  function subscribe(next: Director2AiOperation) {
    closeEvents()
    const source = new EventSource(aiOperationEventsUrl(projectId, next.id))
    sourceRef.current = source

    const readData = (event: Event): Record<string, unknown> => {
      if (!(event instanceof MessageEvent)) return {}
      try { return JSON.parse(event.data || "{}") as Record<string, unknown> }
      catch { return {} }
    }

    source.addEventListener("status", (event) => {
      const data = readData(event)
      setOperation((current) => {
        if (!current) return current
        const merged = mergeDirector2AiStatusEvent(current, data)
        operationRef.current = merged
        return merged
      })
      const stage = (data.stage as Director2AiStage) || next.current_stage
      if (stage && typeof data.message === "string") setStageMessages((current) => ({ ...current, [stage]: data.message as string }))
      if (data.status === "awaiting_review" || data.questions_ready) void refreshOperation(next.id)
    })

    source.addEventListener("agent", (event) => {
      const data = readData(event)
      const stage = stageForAgent(String(data.id || ""), operationRef.current?.current_stage || next.current_stage)
      if (typeof data.message === "string") setStageMessages((current) => ({ ...current, [stage]: data.message as string }))
      if (data.status === "running") setOperation((current) => {
        if (!current) return current
        const merged = { ...current, current_stage: stage, status: "running" as const }
        operationRef.current = merged
        return merged
      })
    })

    source.addEventListener("agent_delta", (event) => {
      const data = readData(event)
      const agent = String(data.agent || "")
      const stage = stageForAgent(agent, operationRef.current?.current_stage || next.current_stage)
      const field = String(data.field || "content")
      const index = data.index === null || data.index === undefined ? "" : String(data.index)
      const episode = numberValue(data.episode)
      const key = `${stage}|${agent}|${field}|${index}${episode ? `|${episode}` : ""}`
      const delta = String(data.delta || "")
      setTargetTexts((current) => ({ ...current, [key]: data.reset ? delta : (current[key] || "") + delta }))
      if (agent === "storyboard" && index !== "") {
        setActiveIndex((current) => {
          const k = `storyboard|${field}`
          const n = Number(index)
          return current[k] !== undefined && current[k] >= n ? current : { ...current, [k]: n }
        })
      }
    })

    source.addEventListener("agent_item", (event) => {
      const data = readData(event)
      const agent = String(data.agent || "")
      const stage = stageForAgent(agent, operationRef.current?.current_stage || next.current_stage)
      const episode = numberValue(data.episode)
      const key = `${stage}|${agent}|${String(data.field || "items")}|${String(data.index ?? 0)}${episode ? `|${episode}` : ""}`
      if (data.item && typeof data.item === "object") {
        const item = { ...(data.item as StreamItem), ...(episode ? { episodeNumber: episode } : {}) }
        setStreamItems((current) => ({ ...current, [key]: item }))
      }
    })

    const finish = () => {
      void refreshOperation(next.id)
      closeEvents()
    }
    source.addEventListener("done", finish)
    source.addEventListener("cancelled", finish)
    source.addEventListener("error", (event) => {
      if (event instanceof MessageEvent) finish()
      else void refreshOperation(next.id)
    })
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const activeOp = await adoptActiveOperation()
      if (cancelled || activeOp) return
      const storedId = window.localStorage.getItem(storageKey)
      if (storedId) await refreshOperation(storedId, true, true)
    })()
    return () => { cancelled = true; closeEvents() }
  }, [projectId])

  useEffect(() => { void refreshContentSummary() }, [refreshContentSummary])

  useEffect(() => {
    if (!awaitingReview) setFeedbackMode(false)
  }, [awaitingReview])

  useEffect(() => {
    if (!feedbackMode) return
    const input = document.querySelector<HTMLTextAreaElement>(".director2-ai-studio .director-prompt-textarea")
    input?.focus()
  }, [feedbackMode])

  useEffect(() => {
    if (!operation?.id || !active) return
    const id = operation.id
    const timer = window.setInterval(() => { void refreshOperation(id) }, 1200)
    return () => window.clearInterval(timer)
  }, [operation?.id, active])

  async function startClarify() {
    if (!brief.trim()) { message.warning("请先输入创意简报"); return }
    setBusy(true)
    setTargetTexts({})
    setShownTexts({})
    setStreamItems({})
    setActiveIndex({})
    setStageMessages({})
    setFeedback("")
    setRevisionNote("")
    setFeedbackMode(false)
    try {
      const next = await createAiOperation(csrfToken, projectId, { kind: "clarify", surface: "director2", goal: brief.trim() })
      persistOperation(next)
      subscribe(next)
    } catch (err) {
      const adopted = await adoptActiveOperation()
      if (adopted) message.info("该项目已有进行中的 AI 任务，已恢复显示其进度")
      else message.error(director2ErrorDetail(err, "启动创意确认失败"))
    } finally { setBusy(false) }
  }

  async function startPipeline(clarifications: DirectorClarificationAnswer[]) {
    if (!brief.trim()) return
    setBusy(true)
    try {
      const next = await createAiOperation(csrfToken, projectId, {
        kind: "pipeline",
        goal: brief.trim(),
        clarifications,
        clarify_questions: questions,
        stages: ["script", "assets", "episodes", "storyboard"],
      })
      persistOperation(next)
      subscribe(next)
      setQuestions([])
    } catch (err) {
      const adopted = await adoptActiveOperation()
      if (adopted) message.info("该项目已有进行中的 AI 任务，已恢复显示其进度")
      else message.error(director2ErrorDetail(err, "启动 AI 生成失败"))
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!operation || operation.cancel_requested) return
    const snapshot = operation
    persistOperation(markDirector2AiOperationCancelling(snapshot))
    try {
      const next = await cancelAiOperation(csrfToken, projectId, snapshot.id)
      applyOperation(next)
      if (DIRECTOR2_ACTIVE_AI_STATUSES.has(next.status) && !sourceRef.current) subscribe(next)
    } catch (err) {
      persistOperation(snapshot)
      message.error(director2ErrorDetail(err, "取消失败"))
    }
  }

  async function retry(stage?: Director2AiStage) {
    if (!operation || retrying) return
    setRetrying(true)
    try {
      // 以服务端最新状态为准，避免轮询/SSE 尚未落地时使用旧的 terminal
      // 快照发起第二次请求。若第一次重试已经入队，直接接管它即可。
      const latest = await getAiOperation(projectId, operation.id)
      if (DIRECTOR2_ACTIVE_AI_STATUSES.has(latest.status)) {
        applyOperation(latest)
        subscribe(latest)
        return
      }
      if (!stage && latest.status !== "failed" && latest.status !== "cancelled") {
        message.info("任务状态正在更新，请稍后再试")
        applyOperation(latest)
        return
      }
      if (stage) {
        const start = STAGES.findIndex((item) => item.key === stage)
        for (const item of STAGES.slice(Math.max(0, start))) clearStageStreams(item.key)
      }
      const next = await retryAiOperation(csrfToken, projectId, latest.id, stage)
      persistOperation(next)
      subscribe(next)
    } catch (err) { message.error(director2ErrorDetail(err, "重试失败")) }
    finally { setRetrying(false) }
  }

  function confirmRegenerate(stage: Director2AiStage): Promise<boolean> {
    const label = STAGES.find((item) => item.key === stage)?.label || stage
    const start = STAGES.findIndex((item) => item.key === stage)
    const downstream = STAGES.slice(start + 1).filter((item) => completed.has(item.key)).map((item) => item.label)
    return new Promise((resolve) => {
      Modal.confirm({
        title: `重新生成「${label}」`,
        content: downstream.length
          ? `将从「${label}」重新生成。后续阶段（${downstream.join("、")}）不再视为完成，确认后需要再次生成。`
          : `将重新生成「${label}」。该阶段跑完后会覆盖已写入的对应内容。`,
        okText: "重新生成",
        cancelText: "取消",
        centered: true,
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      })
    })
  }

  async function regenerateStage(stage: Director2AiStage) {
    if (!operation || retrying || active) return
    const confirmed = await confirmRegenerate(stage)
    if (!confirmed) return
    await retry(stage)
  }

  function followOperation(next: Director2AiOperation) {
    applyOperation(next)
    if (isDirector2AiOperationActive(next) && !sourceRef.current) subscribe(next)
  }

  function clearStageStreams(stage: Director2AiStage) {
    const drop = <T,>(record: Record<string, T>) => {
      const next = { ...record }
      for (const key of Object.keys(next)) if (key.startsWith(`${stage}|`)) delete next[key]
      return next
    }
    setTargetTexts(drop)
    setShownTexts(drop)
    setStreamItems(drop)
  }

  async function acceptStage() {
    if (!operation || busy) return
    setBusy(true)
    setFeedbackMode(false)
    try {
      const next = await advanceAiOperation(csrfToken, projectId, operation.id)
      followOperation(next)
    } catch (err) {
      message.error(director2ErrorDetail(err, "进入下一步失败"))
    } finally { setBusy(false) }
  }

  function beginRevise() {
    setFeedbackMode(true)
  }

  async function submitRevise() {
    if (!operation || busy) return
    const text = feedback.trim()
    if (!text) { message.warning("请先说明想怎么改"); return }
    setBusy(true)
    setQuestions([])
    setRevisionNote(text)
    try {
      const next = await reviseAiOperation(csrfToken, projectId, operation.id, text)
      setFeedback("")
      setFeedbackMode(false)
      followOperation(next)
    } catch (err) {
      message.error(director2ErrorDetail(err, "提交调整失败"))
    } finally { setBusy(false) }
  }

  async function rerunCurrent(answers: DirectorClarificationAnswer[]) {
    if (!operation || busy) return
    const stage = (operation.awaiting_stage || operation.current_stage) as Director2AiStage | null
    if (stage === "clarify") {
      for (const item of STAGES) if (item.key !== "clarify") clearStageStreams(item.key)
    } else if (stage) clearStageStreams(stage)
    setBusy(true)
    setQuestions([])
    try {
      const next = await rerunAiStage(csrfToken, projectId, operation.id, answers)
      followOperation(next)
    } catch (err) {
      message.error(director2ErrorDetail(err, stage === "clarify" ? "重新确认创意方向失败" : "重跑当前阶段失败"))
    } finally { setBusy(false) }
  }

  function copyPrompt(prompt: string) {
    if (!prompt) return
    navigator.clipboard.writeText(prompt).then(
      () => message.success("已复制到剪贴板"),
      () => message.info("请手动复制内容"),
    )
  }

  function stageContent(stage: Director2AiStage) {
    const text = Object.entries(shownTexts).filter(([key]) => key.startsWith(`${stage}|`)).map(([, value]) => value).filter(Boolean)
    const itemEntries = Object.entries(streamItems)
      .filter(([key]) => key.startsWith(`${stage}|`))
      .map(([key, item]) => {
        const [, agent, field, index] = key.split("|")
        const kind = assetKindFor(agent, field)
        return { key, agent, field, index: Number(index), item, kind }
      })

    const persistedRecipe = operation?.result.recipe
    if (stage === "script") {
      const live = resolveDirector2ScriptLiveSource({ shownTexts, recipe: persistedRecipe })
      if (!scriptLiveSourceHasContent(live)) return null
      return (
        <Director2ScriptLiveBody
          title={live.title}
          summary={live.summary}
          fullStory={live.fullStory}
          live={active && operation?.current_stage === "script"}
        />
      )
    }
    if (stage === "assets" && !itemEntries.length) {
      const persistedAssets: Array<{ key: string; agent: string; field: string; index: number; item: StreamItem; kind: DirectorAssetCardKind | null }> = []
      const sources: Array<[string, string, DirectorAssetCardKind, unknown[]]> = [
        ["characters", "characters", "character", Array.isArray(persistedRecipe?.characters) ? persistedRecipe.characters : savedAssets.filter((item) => item.kind === "character")],
        ["characters", "props", "prop", Array.isArray(persistedRecipe?.props) ? persistedRecipe.props : savedAssets.filter((item) => item.kind === "prop")],
        ["locations", "locations", "scene", Array.isArray(persistedRecipe?.locations) ? persistedRecipe.locations : savedAssets.filter((item) => ["scene", "location"].includes(item.kind))],
      ]
      for (const [agent, field, kind, values] of sources) {
        values.forEach((item, index) => {
          if (item && typeof item === "object") persistedAssets.push({ key: `persisted-${agent}-${field}-${index}`, agent, field, index, item: item as StreamItem, kind })
        })
      }
      itemEntries.push(...persistedAssets)
    }

    if (stage === "assets") {
      const cards = itemEntries
        .filter((entry): entry is typeof entry & { kind: DirectorAssetCardKind } => Boolean(entry.kind))
        .sort((left, right) => left.index - right.index)
        .map((entry) => ({ key: entry.key, asset: normalizeDirectorAssetCard(entry.kind, entry.item) }))
        .filter((entry): entry is { key: string; asset: DirectorAssetCardData } => Boolean(entry.asset))
      const related = relateLiveAssetCards(cards.map((entry) => entry.asset))
      const keyed = cards.map((entry, index) => ({ key: entry.key, asset: related[index] }))
      const groups: Array<{ kind: DirectorAssetCardKind; label: string; className: string }> = [
        { kind: "character", label: "角色", className: "director-asset-card-grid" },
        { kind: "scene", label: "场景", className: "director-asset-card-grid" },
        { kind: "prop", label: "道具", className: "director-asset-card-grid is-props" },
      ]
      const visible = groups
        .map((group) => ({ ...group, cards: keyed.filter((entry) => entry.asset.kind === group.kind) }))
        .filter((group) => group.cards.length)
      if (!visible.length) return null
      return (
        <div className="director-asset-live-groups">
          {visible.map((group) => (
            <section key={group.kind} className="director-asset-live-group">
              <h5 className="director-asset-live-group-label">{group.label}</h5>
              <div className={group.className}>
                {group.cards.map(({ key, asset }) => (
                  <DirectorAssetSummaryCard key={key} asset={asset} onCopyPrompt={copyPrompt} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )
    }

    if (stage === "episodes") {
      let rows: Array<{ key: string; item: object; index: number }> = itemEntries
        .filter((entry) => entry.agent === "episodes")
        .sort((a, b) => a.index - b.index)
        .map((entry) => ({ key: entry.key, item: entry.item, index: entry.index }))
      if (!rows.length && persistedRecipe && Array.isArray(persistedRecipe.episodes)) {
        rows = persistedRecipe.episodes.flatMap((item, index) => (
          item && typeof item === "object" ? [{ key: `persisted-episode-${index}`, item, index }] : []
        ))
      }
      if (!rows.length && savedEpisodes.length) {
        rows = savedEpisodes.map((episode, index) => ({ key: `saved-episode-${episode.id}`, item: episode, index }))
      }
      const cards = rows
        .map((row) => ({ key: row.key, card: normalizeEpisodeLiveCard(row.item, { fallbackIndex: row.index }) }))
        .filter((row): row is { key: string; card: Director2EpisodeLiveCard } => Boolean(row.card))
      if (!cards.length) return null
      return (
        <div className="director-block-cards">
          {cards.map(({ key, card }) => (
            <div className="director-block-card is-episode-outline" key={key}>
              <strong>{card.title}</strong>
              {card.summary ? <p>{card.summary}</p> : null}
              {card.targetShots ? <em>约 {card.targetShots} 镜</em> : null}
            </div>
          ))}
        </div>
      )
    }
    if (stage === "storyboard") {
      const hasLiveStoryboard = Object.keys(shownTexts).some((key) => key.startsWith("storyboard|")) || itemEntries.length > 0
      if (!hasLiveStoryboard && persistedRecipe && Array.isArray(persistedRecipe.scenes)) {
        const shots = persistedRecipe.scenes.flatMap((scene) => {
          if (!scene || typeof scene !== "object") return []
          const nested = (scene as StreamItem).shots
          return Array.isArray(nested) ? nested : []
        }).filter((shot): shot is StreamItem => Boolean(shot && typeof shot === "object"))
        if (shots.length) return <div className="director-block-cards">{shots.map((shot, index) => <div className="director-block-card" key={String(shot.id || index)}><strong>{String(shot.title || `镜头 ${index + 1}`)}</strong>{shot.description ? <p>{String(shot.description)}</p> : null}{shot.dialogue ? <p>{String(shot.dialogue)}</p> : null}</div>)}</div>
      }
      if (!hasLiveStoryboard && savedEpisodeDetails.some((episode) => episode.beats?.length)) {
        return <div className="director-block-cards">{savedEpisodeDetails.flatMap((episode) => episode.beats.map((beat, index) => <div className="director-block-card" key={beat.id}><strong>第 {episode.number} 集 · 镜头 {beat.sequence || index + 1}</strong>{beat.action ? <p>{beat.action}</p> : null}{beat.dialogue ? <p>{beat.dialogue}</p> : null}</div>))}</div>
      }
      return <DirectorStoryboardLiveBody
        shownTexts={shownTexts}
        targetTexts={targetTexts}
        streamItems={streamItems}
        activeIndex={activeIndex}
        message={stageMessages.storyboard}
        live={active}
        settled={!active}
        recipe={{
          episodes: Array.isArray(persistedRecipe?.episodes) && persistedRecipe.episodes.length
            ? persistedRecipe.episodes
            : savedEpisodes.map((episode) => ({
              num: episode.episode_num,
              title: episode.title,
              shots_count: episode.shots_count,
              targetShots: episode.shots_count,
            })),
          scenes: persistedRecipe?.scenes,
        }}
      />
    }
    const items = itemEntries.map(({ item }) => item)
    if (!text.length && !items.length) return null
    return (
      <>
        {text.length ? <div className="director-block-text">{text.map((value, index) => <p key={index}>{value}</p>)}</div> : null}
        {items.length ? <div className="director-block-cards">{items.map((item, index) => {
          const display = displayItem(item)
          return <div className="director-block-card" key={index}><strong>{display.title}</strong>{display.detail ? <p>{display.detail}</p> : null}</div>
        })}</div> : null}
      </>
    )
  }

  function stagePreview(stage: Director2AiStage): string {
    if (operation?.status === "cancelled" && operation.current_stage === stage) return "已取消，已生成内容已保留"
    if (operation?.status === "failed" && operation.current_stage === stage) return operation.error || "这一阶段未完成"
    if (stage === "clarify") {
      const clarifyAnswer = stageChoicePreviewAnswer(operation, "clarify")
      if (clarifyAnswer) return clarifyAnswer
    }
    const count = Object.keys(streamItems).filter((key) => key.startsWith(`${stage}|`)).length
    if (stage === "episodes" && count) return `共 ${count} 集`
    if (stage === "storyboard" && count) return `已拆出 ${count} 个镜头`
    if (count) return `已生成 ${count} 项内容`
    if (contentSummary) {
      if (stage === "script" && contentSummary.scriptCount) return `已有 ${contentSummary.scriptCount} 篇剧本`
      if (stage === "assets" && contentSummary.assetCount) return `已有 ${contentSummary.assetCount} 项角色 / 场景 / 道具`
      if (stage === "episodes" && contentSummary.episodeCount) return `已有 ${contentSummary.episodeCount} 集`
      if (stage === "storyboard" && contentSummary.shotCount) return `已有 ${contentSummary.shotCount} 个分镜`
    }
    return ({ clarify: "创作方向已确认", script: "剧本已完成", assets: "角色、场景与道具已建立", episodes: "分集结构已完成", storyboard: "Beat 分镜已完成" })[stage]
  }

  function stageChoiceProps(stage: Director2AiStage, failed = false) {
    const echo = stageChoiceEcho(operation, stage)
    return {
      choices: echo.items,
      choiceFallback: failed ? undefined : stageChoiceFallbackLabel(echo),
    }
  }

  function openStage(stage: Director2AiStage) {
    setViewingStage(stage)
  }

  const feedRows = STAGES.filter((stage) => {
    if (awaitingReview && (operation?.awaiting_stage || operation?.current_stage) === stage.key) return false
    if (stageQuestionMode && operation?.current_stage === stage.key) return false
    if (active && operation?.current_stage === stage.key) return false
    if (completed.has(stage.key)) return true
    if (stage.key === "clarify" && operation?.kind === "pipeline" && !openingClarify) return true
    return !active && operation?.current_stage === stage.key && ["failed", "cancelled"].includes(operation.status)
  })
  const canRegenerate = Boolean(
    operation
    && !active
    && !retrying
    && ["failed", "cancelled", "awaiting_review", "succeeded"].includes(operation.status),
  )
  const headTitle = checkpointTitle || (questionMode ? "创意方向确认" : done ? "AI 创作已完成" : operation?.status === "cancelled" ? "生成已取消" : operation?.status === "failed" ? "生成遇到问题" : operation ? (currentStage?.label || "AI 导演正在创作") : hasContent ? "继续这个项目的创作" : "开始一段新的创作")
  const messageStage = operation?.awaiting_stage || operation?.current_stage || "script"
  const headDetail = questionMode
    ? "回答这些问题，AI 才会继续生成完整剧本与分镜。"
    : stageQuestionMode
      ? (openingClarify || operation?.current_stage === "clarify" ? "回答这些问题后，将从剧本重新开始生成。" : "回答这些问题后，将只重跑当前阶段。")
      : done
        ? "剧本、资产、分集和 Beat 已写入导演台2。"
        : director2AiHeadlineDetail(operation, stageMessages[messageStage], currentStage?.message || (hasContent ? "项目已有部分内容，左侧步骤显示各阶段就绪情况，可继续输入创意推进。" : "从一句话创意开始，导演台会逐阶段推进。"))
  const viewingFailed = Boolean(
    viewingStage
    && (operation?.status === "failed" || operation?.status === "cancelled")
    && operation.current_stage === viewingStage,
  )
  const viewingChoices = viewingStage ? stageChoiceProps(viewingStage, viewingFailed) : null

  return (
    <div className="director-recipe-shell director2-ai-studio">
      <div className="director-recipe-layout is-chat" aria-busy={active}>
        <section className="director-recipe-main">
          <div className={`director-script-room${active ? " is-streaming" : ""}`}>
            <div className="director-script-layout">
              <aside className="director-task-rail">
                            <DirectorTaskRows
                              rows={rows}
                              running={active || retrying || !operation}
                              elapsedSec={-1}
                              variant="rail"
                              onRetry={operation?.status === "failed" && !retrying ? (id) => { void retry(id as Director2AiStage) } : undefined}
                              onRegenerate={canRegenerate ? (id) => { void regenerateStage(id as Director2AiStage) } : undefined}
                              onOpen={(id) => setViewingStage(id as Director2AiStage)}
                            />
              </aside>
              <div className={`director-script-stream is-transcript${operation?.status === "failed" || operation?.status === "cancelled" ? " is-terminal" : ""}`} data-stream-live={active || undefined}>
                <div className="director-script-stream-head">
                  {done ? <CheckCircle2 size={18} className="director-stream-head-icon is-done" /> : operation?.status === "failed" || operation?.status === "cancelled" ? <XCircle size={18} className="director-stream-head-icon is-failed" /> : active ? <span className="director-stream-pulse" aria-hidden /> : awaitingReview ? <CheckCircle2 size={18} className="director-stream-head-icon is-done" /> : <span className="director-stream-pulse" aria-hidden />}
                  <div className="director-script-stream-copy"><strong>{headTitle}</strong><span>{headDetail}</span></div>
                  {active || awaitingReview ? <Button size="small" danger loading={Boolean(operation?.cancel_requested)} disabled={Boolean(operation?.cancel_requested) || busy} onClick={() => void cancel()}>{SCRIPT_STREAM_CANCEL_LABEL}</Button> : null}
                </div>
                <div className="director-stream-wrap">
                  <div className="director-stream-body" ref={streamBodyRef} onScroll={handleStreamScroll}>
                    <div className="director-stream-feed" ref={streamFeedRef}>
                      {brief.trim() ? <div className="director-user-bubble"><span className="director-user-bubble-label">你的创意</span><p>{brief.trim()}</p></div> : null}
                      {revisionNote.trim() ? <div className="director-user-bubble"><span className="director-user-bubble-label">你的调整</span><p>{revisionNote.trim()}</p></div> : null}
                      <DirectorPathChips groups={pathGroups} />
                      {!operation ? (
                        <div className="director-hero">
                          <span className="director-hero-icon"><Wand2 size={22} /></span>
                          <strong>{hasContent ? "项目中已有创作内容" : "从一句创意开始"}</strong>
                          <p>{hasContent ? contentHeroDetail : "AI 会先澄清方向，再生成剧本、角色 / 场景 / 道具、分集和 Beat 分镜。"}</p>
                          {hasContent ? (
                            <Space wrap style={{ justifyContent: "center" }}>
                              <Button onClick={() => onNavigate("content")}>查看内容库</Button>
                              <Button onClick={() => onNavigate("assets")}>查看资产库</Button>
                              <Button type="primary" onClick={() => onNavigate("workshop")}>进入剧集工坊</Button>
                            </Space>
                          ) : (
                            <div className="director-hero-examples"><button type="button" className="director-hero-example" onClick={() => setBrief("一个现代都市逆袭短剧，主角从外卖员成长为创业者")}>一个现代都市逆袭短剧，主角从外卖员成长为创业者</button><button type="button" className="director-hero-example" onClick={() => setBrief("三个夜班保安在旧商场里发现一段被隐藏的记忆")}>三个夜班保安在旧商场里发现一段被隐藏的记忆</button></div>
                          )}
                        </div>
                      ) : null}
                      {questionMode ? <DirectorClarificationCard questions={openingQuestions} disabled={busy} onConfirm={(nextAnswers) => { void startPipeline(nextAnswers) }} /> : null}
                      {operation && !questionMode ? (
                        <div className="director-step-feed">
                          {feedRows.map((stage) => {
                            const failed = (operation.status === "failed" || operation.status === "cancelled") && operation.current_stage === stage.key
                            const recorded = stageChoiceProps(stage.key, failed)
                            return <DirectorLiveStepRow key={stage.key} id={stage.key} label={stage.label} status={failed ? "failed" : "completed"} preview={stagePreview(stage.key)} choices={recorded.choices} choiceFallback={recorded.choiceFallback} onOpen={() => openStage(stage.key)} onRegenerate={!failed && canRegenerate ? () => { void regenerateStage(stage.key) } : undefined} />
                          })}
                          {stageQuestionMode ? <DirectorClarificationCard questions={openingClarify || operation.current_stage === "clarify" ? openingQuestions : questions} disabled={busy} onConfirm={(nextAnswers) => { void rerunCurrent(nextAnswers) }} /> : null}
                          {awaitingReview && currentStage ? (
                            <DirectorReviewBlock
                              label={currentStage.label}
                              message={stageMessages[currentStage.key] || operation.result.message || "该阶段已生成，请确认"}
                              icon={currentStage.icon}
                              lastStep={isDirector2LastPipelineStage(currentStage.key)}
                              busy={busy}
                              onAccept={() => { void acceptStage() }}
                              onRevise={beginRevise}
                            >
                              {stageContent(currentStage.key)}
                            </DirectorReviewBlock>
                          ) : null}
                          {active && currentStage && !stageQuestionMode ? <DirectorLiveBlock label={currentStage.label} message={operation.cancel_requested ? "正在停止当前生成…" : operation.status === "revising" ? (stageMessages[currentStage.key] || "正在按你的反馈重新规划…") : stageMessages[currentStage.key] || operation.result.message || currentStage.message} icon={currentStage.icon}>{stageContent(currentStage.key)}</DirectorLiveBlock> : null}
                        </div>
                      ) : null}
                      {done ? <div className="director-completion-card"><div className="director-completion-copy"><strong>生成结果已经进入导演台2</strong><p>你可以继续查看内容库、资产库或剧集工坊，并在手动编辑模式中调整细节。</p></div><Space wrap><Button onClick={() => onNavigate("content")}>查看内容库</Button><Button onClick={() => onNavigate("assets")}>查看资产库</Button><Button type="primary" onClick={() => onNavigate("workshop")}>进入剧集工坊</Button></Space></div> : null}
                      {operation?.status === "failed" ? <div className="director-completion-card"><div className="director-completion-copy"><strong>这一阶段没有完成</strong><p>{operation.error || "AI 返回了错误，请重试当前阶段。"}</p></div><Button type="primary" loading={retrying} disabled={retrying} icon={<RefreshCw size={14} />} onClick={() => void retry()}>重试本阶段</Button></div> : null}
                      {operation?.status === "cancelled" ? <div className="director-completion-card"><div className="director-completion-copy"><strong>本次生成已停止</strong><p>已经完成并写入的内容不会被删除，可以从当前阶段重新生成。</p></div><Button type="primary" loading={retrying} disabled={retrying} icon={<RefreshCw size={14} />} onClick={() => void retry()}>从当前阶段重试</Button></div> : null}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            {!active ? <DirectorPromptBar value={awaitingReview ? feedback : brief} phase={questionMode || (awaitingReview && !feedbackMode) ? "clarify" : "idle"} placeholder={awaitingReview ? (feedbackMode ? "说明想怎么改…" : "点「不满意，调整」后，在这里说明想怎么改…") : questionMode ? "回答上方的问题后才会开始生成" : "描述你的故事、人物和想要的情绪…"} hint={awaitingReview ? (feedbackMode ? "提交后 AI 会按你的反馈生成本阶段的确认问题。" : "先确认这一步，或点「不满意，调整」后说明想怎么改。") : undefined} onChange={awaitingReview ? setFeedback : setBrief} onSubmit={() => { if (awaitingReview) void submitRevise(); else void startClarify() }} cancelRequested={Boolean(operation?.cancel_requested)} /> : null}
          </div>
        </section>
      </div>
      <Drawer title={viewingStage ? STAGES.find((stage) => stage.key === viewingStage)?.label : "阶段结果"} open={Boolean(viewingStage)} onClose={() => setViewingStage(null)} width={520}>
        {viewingStage ? <Space direction="vertical" size={18} style={{ width: "100%" }}>
          {viewingChoices ? <DirectorLiveStepChoices items={viewingChoices.choices} fallback={viewingChoices.choiceFallback} inset={false} /> : null}
          {stageContent(viewingStage) || <p>{stagePreview(viewingStage)}</p>}
          {viewingStage === "script" ? <Button type="primary" onClick={() => onNavigate("content")}>前往内容库继续编辑</Button> : null}
          {viewingStage === "assets" ? <Button type="primary" onClick={() => onNavigate("assets")}>前往资产库继续编辑</Button> : null}
          {["episodes", "storyboard"].includes(viewingStage) ? <Button type="primary" onClick={() => onNavigate("workshop")}>前往剧集工坊继续编辑</Button> : null}
        </Space> : null}
      </Drawer>
    </div>
  )
}
