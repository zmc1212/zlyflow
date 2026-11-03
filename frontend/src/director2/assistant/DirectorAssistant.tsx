import { Fragment, createContext, useCallback, useContext, useEffect, useRef, useState, type ComponentRef, type ReactNode } from "react"
import { Alert, Button, Collapse, Drawer, Dropdown, Empty, Input, Modal, Popconfirm, Popover, Progress, Select, Space, Spin, Tag, Tooltip, message } from "antd"
import { ArrowDown, ArrowLeft, ArrowUp, AudioLines, BookOpen, Check, ChevronDown, Eye, FileText, Globe, History, Maximize2, Minimize2, Plus, RefreshCw, Sparkles, Square, Wand2, X, Zap } from "lucide-react"
import { useNavigate } from "react-router-dom"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import ThemeToggle from "../../components/ThemeToggle"
import { ApiRequestError } from "../../api"
import { cancelAiOperation, createDocument, createProject, director2ErrorDetail, getActiveAiOperation, getProject, type Director2AiOperation } from "../api"
import { director2ProjectPath } from "../paths"
import { homeProjectExtra, homeProjectMessage, type HomeProjectRequest } from "../home-creation"
import Director2AiStudioPane from "../panes/Director2AiStudioPane"
import ArtifactDialog from "./ArtifactDialog"
import KnowledgeManager from "./KnowledgeManager"
import WorkflowProgressCard from "./WorkflowProgressCard"
import QuestionCard from "./QuestionCard"
import ResourceMarket from "./ResourceMarket"
import ResourcePicker from "./ResourcePicker"
import ResourceCover from "./ResourceCover"
import { ASSISTANT_API, artifactLabels, assistantGet, assistantMutate, emptySelections, isAssistantRunning, mediaLabels, mergeAssistantEvent, type AssistantArtifact, type AssistantCatalog, type AssistantDetail, type AssistantResource, type AssistantRun, type AssistantSelections, type AssistantSession, type MediaExecution, type MediaProposal } from "./api"
import { releaseTerminalAssistantRun } from "./assistant-state"
import { assistantReplyNotification, requestAssistantNotificationPermission, shouldNotifyReply, showAssistantReplyNotification } from "./assistant-notify"
import { EDITING_TOOL_GROUPS, matchesAssistantScope, newestPendingEditingAction, type EditingContext, type EditingOperation, type EditorBridge, type HookStrategy } from "./editing-tools"
import { confirmEditingAction, previewEditingAction, readEditingAction, readTranscript, readUnderstanding, reorderEditingAction, startTranscript, startUnderstanding, type EditingAction, type MediaTranscript, type MediaUnderstanding, type UnderstandingStatus } from "../smart-edit/api"
import "./assistant.css"

type AssistantControl = { enabled: boolean; ready: boolean; open: boolean; setOpen: (open: boolean) => void; prompt: (text: string) => void; registerEditor: (editor: EditorBridge) => () => void }
const AssistantContext = createContext<AssistantControl>({ enabled: false, ready: false, open: false, setOpen: () => {}, prompt: () => {}, registerEditor: () => () => {} })
export const useDirectorAssistant = () => useContext(AssistantContext)
const STORAGE_KEY = "director-assistant-session-v2"
const OPERATION_TITLES: Record<EditingOperation, string> = {
  video_arrange: "智能铺轨",
  subtitle_arrange: "自动字幕",
  audio_subtitle: "音轨字幕",
  dialogue_cut: "对白精剪",
  quick_cut: "成片速剪",
  highlight_cut: "高光合集",
  hook_cut: "引流剪辑"
}
const ACTION_BUTTONS: Record<EditingOperation, string> = {
  video_arrange: "查看并确认铺轨",
  subtitle_arrange: "查看并确认字幕",
  audio_subtitle: "查看并确认音轨字幕",
  dialogue_cut: "查看并确认精剪",
  quick_cut: "查看并确认速剪",
  highlight_cut: "查看并确认高光合集",
  hook_cut: "查看并确认引流剪辑"
}
const CONFIRM_LABELS: Record<EditingOperation, string> = {
  video_arrange: "确认铺轨",
  subtitle_arrange: "生成字幕",
  audio_subtitle: "生成音轨字幕",
  dialogue_cut: "确认精剪",
  quick_cut: "确认速剪",
  highlight_cut: "确认高光合集",
  hook_cut: "确认引流剪辑"
}
const isCutOperation = (operation: EditingOperation) =>
  operation === "dialogue_cut" || operation === "quick_cut" || operation === "highlight_cut" || operation === "hook_cut"
const isCaptionOperation = (operation: EditingOperation) => operation === "subtitle_arrange" || operation === "audio_subtitle"
function emptyHint(operation: EditingOperation) {
  if (operation === "subtitle_arrange") return "没有可用的对白字幕，请先完成配音或补充对白。"
  if (operation === "audio_subtitle") return "还没有可用的音轨转写结果，请先点击「转写音频」并等待完成。"
  if (operation === "video_arrange") return "没有尚未铺轨的视频，请先导入视频或完成本集视频。"
  return "没有可剪辑的镜头视频，请先完成本集视频。"
}
function actionSummary(action: EditingAction) {
  const unit = isCaptionOperation(action.operation) ? "条字幕" : isCutOperation(action.operation) ? "个镜头" : "段视频"
  let text = `${action.strategy_title ? `${action.strategy_title} · ` : ""}${action.count} ${unit} · ${action.total_duration.toFixed(2)} 秒`
  if (action.operation === "video_arrange" && action.skipped_count) text += ` · 跳过 ${action.skipped_count} 项已用或重复视频`
  if (action.operation === "audio_subtitle") {
    if (action.transcript?.segment_count) text += ` · 音轨转写 ${action.transcript.segment_count} 段 / ${(action.transcript.audio_seconds ?? 0).toFixed(1)} 秒`
    if (action.replaced_count) text += ` · 替换 ${action.replaced_count} 条自动字幕`
    if (action.inaudible_count) text += ` · ${action.inaudible_count} 段语音不在有声镜头内`
    if (action.skipped_count) text += ` · 跳过 ${action.skipped_count} 处已有文字`
  } else if (action.operation === "subtitle_arrange" && action.replaced_count) text += ` · 替换 ${action.replaced_count} 条自动字幕`
  if (isCutOperation(action.operation)) {
    if (action.dropped_count) text += ` · 略过 ${action.dropped_count} 个非目标镜头`
    if (action.trimmed_count) text += ` · 截短 ${action.trimmed_count} 个镜头`
    if (action.understanding?.shot_used_count) text += ` · 引用画面理解 ${action.understanding.shot_used_count} 个镜头`
    else if (action.understanding?.used_count) text += ` · 引用画面理解 ${action.understanding.used_count} 条素材`
  }
  return text
}
function successText(action: EditingAction) {
  if (action.operation === "subtitle_arrange") return `已生成 ${action.count} 条字幕，剪辑已保存`
  if (action.operation === "audio_subtitle") return `已按真实音轨生成 ${action.count} 条字幕，剪辑已保存`
  if (isCutOperation(action.operation)) return `${action.title}完成，共 ${action.count} 个镜头，剪辑已保存`
  return `已铺轨 ${action.count} 段视频，剪辑已保存`
}
function feedbackDetail(action: EditingAction) {
  const undo = "可在时间线工具栏一次撤销。"
  if (action.operation === "subtitle_arrange")
    return `${action.replaced_count ? `替换 ${action.replaced_count} 条自动字幕` : "已写入文字轨"}${action.skipped_count ? `，跳过 ${action.skipped_count} 处无对白或占用位置` : ""}，${undo}`
  if (action.operation === "audio_subtitle")
    return `${action.replaced_count ? `替换 ${action.replaced_count} 条自动字幕` : "已写入文字轨"}${action.skipped_count ? `，跳过 ${action.skipped_count} 处已有文字占用` : ""}${action.inaudible_count ? `，${action.inaudible_count} 段语音不在有声镜头内` : ""}，${undo}`
  if (isCutOperation(action.operation))
    return `共 ${action.total_duration.toFixed(2)} 秒${action.dropped_count ? `，略过 ${action.dropped_count} 个镜头` : ""}${action.trimmed_count ? `，截短 ${action.trimmed_count} 个镜头` : ""}，${undo}`
  return `追加 ${action.total_duration.toFixed(2)} 秒，${undo}`
}
const UNDERSTANDING_LABELS: Record<UnderstandingStatus, string> = {
  missing: "未开始",
  queued: "已排队",
  running: "理解中",
  succeeded: "已完成",
  partial: "部分完成",
  empty: "无视频",
  failed: "未完成"
}
const ANALYSIS_COLORS: Record<UnderstandingStatus, string> = {
  missing: "default",
  queued: "processing",
  running: "processing",
  succeeded: "success",
  partial: "warning",
  empty: "default",
  failed: "error"
}
const analysisActive = (status?: string) => status === "queued" || status === "running"
function understandingText(value: MediaUnderstanding | null) {
  if (!value) return "正在读取视频理解状态…"
  if (value.stale) return "时间线视频已变化，当前画面描述已过期，请重新理解后再生成剪辑清单。"
  const videos = value.summary?.video_count ?? 0
  const detected = value.summary?.detected_shot_count ?? 0
  const sampled = value.summary?.shot_count ?? 0
  const analyzed = value.summary?.shot_analyzed_count ?? 0
  if (value.status === "missing") return "检测时间线视频的镜头边界，抽样关键帧生成逐镜画面描述与剪辑依据。不做音频转写，也不改动时间线。"
  if (value.status === "queued") return value.message || "已加入视频理解队列…"
  if (value.status === "running") return value.message || "正在检测镜头边界并理解画面…"
  if (value.status === "empty") return value.message || "时间线上还没有可理解的视频。"
  if (value.status === "failed") return value.message || "视频理解没有成功，请检查视觉模型配置后重试。"
  if (value.status === "partial") return `${value.message || `已理解 ${analyzed}/${sampled} 个镜头`}；剪辑只引用成功的画面结果。`
  if (!sampled) return `已理解 ${value.summary?.analyzed_count ?? 0}/${videos} 条素材的画面，剪辑清单会引用高光画面证据。`
  return `已从 ${videos} 条素材检测到 ${detected} 个镜头，采样分析 ${analyzed}/${sampled} 个；剪辑清单会引用高光画面证据。`
}
function understandingEvidence(action: EditingAction) {
  const value = action.understanding
  if (value?.shot_used_count) return `视频画面：镜头边界检测后采样的 ${value.shot_used_count} 个镜头关键帧描述，结合分镜对白与配音时长。`
  if (value?.used_count) return `视频画面 ${value.used_count} 条素材的关键帧描述，结合分镜对白与配音时长。`
  if (value?.status === "stale") return "画面理解已过期，本次仅使用分镜标题、对白与配音时长。"
  return "分镜标题、动作、对白与配音时长；本次未使用视频画面理解。"
}
const TRANSCRIPT_LABELS: Record<UnderstandingStatus, string> = {
  missing: "未转写",
  queued: "已排队",
  running: "转写中",
  succeeded: "已完成",
  partial: "部分完成",
  empty: "无语音",
  failed: "未完成"
}
function transcriptText(value: MediaTranscript | null) {
  if (!value) return "正在读取音频转写状态…"
  if (value.stale) return "时间线素材已变化，当前转写结果已过期，请重新转写音频后再生成音轨字幕。"
  const media = value.summary?.media_count ?? 0
  const done = value.summary?.transcribed_count ?? 0
  const segments = value.summary?.segment_count ?? 0
  const seconds = value.summary?.audio_seconds ?? 0
  if (value.status === "missing") return "把时间线上有声素材的音轨转成带时间戳的真实语音段落，供「音轨字幕」按声音铺设字幕。不改动任何画面剪辑，也不会自动写入字幕。"
  if (value.status === "queued") return value.message || "已加入音频转写队列…"
  if (value.status === "running") return value.message || "正在提取音轨并转写语音…"
  if (value.status === "empty") return value.message || "音轨已转写，但没有识别到任何语音（0 段）。"
  if (value.status === "failed") return value.message || "音频转写没有成功，请检查素材音轨与转写服务配置后重试。"
  if (value.status === "partial") return `${value.message || `已转写 ${done}/${media} 条素材`}；音轨字幕只引用成功的段落，未成功的素材可重新转写。`
  return `已转写 ${done}/${media} 条素材、${segments} 段语音（${seconds.toFixed(1)} 秒音频）；「音轨字幕」按这些真实段落铺设。`
}
function transcriptEvidence(action: EditingAction) {
  const value = action.transcript
  if (!value) return "音轨转写：本次未使用音轨转写结果。"
  if (value.status === "stale") return "音轨转写已过期，请重新转写音频后再生成音轨字幕。"
  return `音轨转写：${value.used_count} 条有声素材的 ${value.segment_count} 段真实语音（约 ${(value.audio_seconds ?? 0).toFixed(1)} 秒音频，模型 ${value.model || "已配置的转写服务"}），段尾按镜头边界收短。`
}

// The home and drawer surfaces share the same sessions, stream and approval flow.
const AssistantHomeContext = createContext<{ active: boolean; surface: ReactNode; creating: boolean; available: boolean; startProject: (input: HomeProjectRequest) => Promise<void> }>({ active: false, surface: null, creating: false, available: false, startProject: async () => {} })
export const useDirectorAssistantHome = () => useContext(AssistantHomeContext)

export default function DirectorAssistantProvider({ children, csrfToken, projectId, editingContext, presentation = "drawer" }: { children: ReactNode; csrfToken: string; projectId: string | null; editingContext?: EditingContext | null; presentation?: "drawer" | "home" | "project" }) {
  const isHome = presentation === "home"
  const isProject = presentation === "project"
  const [creatingProject, setCreatingProject] = useState(false)
  const projectCreation = useRef<{ signature: string; projectId: string; sessionId?: string; messageId: string } | null>(null)
  const [homeStarted, setHomeStarted] = useState(false)
  const composerInput = useRef<ComponentRef<typeof Input.TextArea>>(null)
  const [catalog, setCatalog] = useState<AssistantCatalog | null>(null)
  const [open, setOpen] = useState(isHome)
  const [expanded, setExpanded] = useState(false)
  const [catalogError, setCatalogError] = useState("")
  const [sid, setSid] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorBridge | null>(null)
  const registerEditor = useCallback((bridge: EditorBridge) => { setEditor(bridge); return () => setEditor(current => current === bridge ? null : current) }, [])
  const isEditing = !!editingContext
  const activeEditor = editor?.projectId === projectId && editor.sequenceId === editingContext?.sequence_id ? editor : null
  const [editingBusy, setEditingBusy] = useState(false)
  const [editingOperation, setEditingOperation] = useState<EditingOperation | null>(null)
  const [editingAction, setEditingAction] = useState<EditingAction | null>(null)
  const [editingOrder, setEditingOrder] = useState<string[]>([])
  const [actionFeedback, setActionFeedback] = useState<EditingAction | null>(null)
  const [actionError, setActionError] = useState("")
  const [confirmingAction, setConfirmingAction] = useState(false)
  const [understanding, setUnderstanding] = useState<MediaUnderstanding | null>(null)
  const [understandingBusy, setUnderstandingBusy] = useState(false)
  const [understandingError, setUnderstandingError] = useState("")
  const understandingKey = useRef<string | null>(null)
  const [transcript, setTranscript] = useState<MediaTranscript | null>(null)
  const [transcriptBusy, setTranscriptBusy] = useState(false)
  const [transcriptError, setTranscriptError] = useState("")
  const transcriptKey = useRef<string | null>(null)
  const editingFlight = useRef(false)
  const openedActions = useRef(new Set<string>())
  const activeStorageKey = useRef<string | null>(null)
  const scope = isEditing ? `${projectId}:${editingContext.sequence_id}` : isHome ? "home" : `project:${projectId || "general"}`
  const scopeRef = useRef(scope); scopeRef.current = scope
  const storageKey = isEditing ? activeEditor ? `director-edit-assistant:${activeEditor.draftKey}` : null : projectId ? `${STORAGE_KEY}:${projectId}` : STORAGE_KEY
  const [viewportWidth, setViewportWidth] = useState(window.innerWidth)
  useEffect(() => { const resize = () => setViewportWidth(window.innerWidth); window.addEventListener("resize", resize); return () => window.removeEventListener("resize", resize) }, [])
  const dockWidth = viewportWidth >= 1800 ? 440 : viewportWidth >= 1560 ? 400 : 360
  const [detail, setDetail] = useState<AssistantDetail | null>(null)
  const [selections, setSelections] = useState<AssistantSelections>(emptySelections)
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [savingSelection, setSavingSelection] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [phase, setPhase] = useState("")
  const [history, setHistory] = useState<AssistantSession[]>([])
  const [market, setMarket] = useState<"skill" | "expert" | null>(null)
  const [picker, setPicker] = useState<"skill" | "expert" | null>(null)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [artifact, setArtifact] = useState<AssistantArtifact | null>(null)
  const [media, setMedia] = useState<MediaProposal | null>(null)
  const [confirmingMedia, setConfirmingMedia] = useState(false)
  const [projectName, setProjectName] = useState("")
  const [legacy, setLegacy] = useState<Director2AiOperation | null>(null)
  const [legacyOpen, setLegacyOpen] = useState(false)
  const sidRef = useRef(sid)
  const detailRef = useRef(detail)
  const loadGeneration = useRef(0)
  const feed = useRef<HTMLDivElement>(null)
  const followTail = useRef(true)
  const submission = useRef<{ signature: string; id: string } | null>(null)
  const navigate = useNavigate()
  sidRef.current = sid; detailRef.current = detail
  const enabled = !!catalog?.enabled
  const scopedHistory = history.filter(s => matchesAssistantScope(s, projectId, editingContext))
  const busy = loading || sending || savingSelection || editingBusy || confirmingAction || isAssistantRunning(detail?.run)
  const understandingScope = isEditing && editingContext ? `${projectId}:${editingContext.sequence_id}` : null
  const understandingRunning = analysisActive(understanding?.status)
  const transcriptScope = understandingScope
  const transcriptRunning = analysisActive(transcript?.status)

  useEffect(() => {
    activeStorageKey.current = storageKey
    let restored: string | null = null
    try { if (storageKey && !isHome) restored = localStorage.getItem(storageKey) } catch { /* Server history remains available. */ }
    sidRef.current = restored; setSid(restored); setDetail(null); setDraft(""); setError(""); setLoading(false)
    setEditingAction(null); setActionFeedback(null); setActionError(""); openedActions.current.clear(); loadGeneration.current++
    setHomeStarted(false); setOpen(isHome)
  }, [storageKey, scope, isHome])
  useEffect(() => {
    if (!understandingScope || !projectId || !editingContext) {
      understandingKey.current = null
      setUnderstanding(null); setUnderstandingError(""); setUnderstandingBusy(false)
      return
    }
    if (understandingKey.current !== understandingScope) {
      understandingKey.current = understandingScope
      setUnderstanding(null); setUnderstandingError(""); setUnderstandingBusy(false)
    }
    let alive = true
    readUnderstanding(projectId, editingContext.sequence_id)
      .then(next => { if (alive && scopeRef.current === understandingScope) setUnderstanding(next) })
      .catch(e => { if (alive && scopeRef.current === understandingScope) setUnderstandingError(director2ErrorDetail(e, "读取视频理解状态失败")) })
    return () => { alive = false }
  }, [understandingScope, projectId, editingContext?.sequence_id, open])
  useEffect(() => {
    if (!understandingRunning || !projectId || !editingContext) return
    const key = `${projectId}:${editingContext.sequence_id}`
    let alive = true
    const timer = window.setInterval(() => {
      readUnderstanding(projectId, editingContext.sequence_id)
        .then(next => { if (alive && scopeRef.current === key) setUnderstanding(next) })
        .catch(() => {})
    }, 2000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [understandingRunning, projectId, editingContext?.sequence_id])
  useEffect(() => {
    if (!transcriptScope || !projectId || !editingContext) {
      transcriptKey.current = null
      setTranscript(null); setTranscriptError(""); setTranscriptBusy(false)
      return
    }
    if (transcriptKey.current !== transcriptScope) {
      transcriptKey.current = transcriptScope
      setTranscript(null); setTranscriptError(""); setTranscriptBusy(false)
    }
    let alive = true
    readTranscript(projectId, editingContext.sequence_id)
      .then(next => { if (alive && scopeRef.current === transcriptScope) setTranscript(next) })
      .catch(e => { if (alive && scopeRef.current === transcriptScope) setTranscriptError(director2ErrorDetail(e, "读取音频转写状态失败")) })
    return () => { alive = false }
  }, [transcriptScope, projectId, editingContext?.sequence_id, open])
  useEffect(() => {
    if (!transcriptRunning || !projectId || !editingContext) return
    const key = `${projectId}:${editingContext.sequence_id}`
    let alive = true
    const timer = window.setInterval(() => {
      readTranscript(projectId, editingContext.sequence_id)
        .then(next => { if (alive && scopeRef.current === key) setTranscript(next) })
        .catch(() => {})
    }, 2000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [transcriptRunning, projectId, editingContext?.sequence_id])

  const refreshCatalog = useCallback(async () => {
    const next = await assistantGet<AssistantCatalog>("/catalog")
    setCatalog(next); setCatalogError("")
    setSelections(current => current.model_id ? current : { ...current, model_id: next.models[0]?.id || "" })
  }, [])
  useEffect(() => { refreshCatalog().catch(e => setCatalogError(director2ErrorDetail(e, "助手暂时无法加载"))) }, [refreshCatalog])
  const loadDetail = useCallback(async (id: string) => {
    const generation = ++loadGeneration.current
    const next = await assistantGet<AssistantDetail>(`/sessions/${id}`)
    if (sidRef.current !== id || generation !== loadGeneration.current) return null
    if (!matchesAssistantScope(next.session, projectId, editingContext)) throw new Error("该会话属于其它工作区，请创建新对话")
    setDetail(next); setSelections(next.session.selections)
    return next
  }, [projectId, editingContext?.sequence_id])
  const restoreSession = useCallback(async (id: string) => {
    if (sidRef.current !== id) return
    setLoading(true)
    try { if (activeStorageKey.current) localStorage.setItem(activeStorageKey.current, id) } catch { /* Server history remains available. */ }
    try {
      const loaded = await loadDetail(id)
      if (loaded && sidRef.current === id) setError("")
    } catch (e) {
      if (sidRef.current !== id) return
      const hasCurrentDetail = detailRef.current?.session.id === id
      if (!hasCurrentDetail) {
        // 本地残留的会话 ID（其它账号登录或会话已删除）属于可自愈状态：
        // 清理后回到欢迎页即可，不再弹出「内容不存在或无权访问」干扰新会话。
        sidRef.current = null
        setSid(null); setDetail(null)
        try { if (activeStorageKey.current) localStorage.removeItem(activeStorageKey.current) } catch { /* Local preference only. */ }
        setLoading(false)
        if (!(e instanceof ApiRequestError) || (e.status !== 404 && e.status !== 403)) setError(director2ErrorDetail(e, "无法恢复上次会话，可创建新对话"))
        else setError("")
        return
      }
      setLoading(false)
      setError(director2ErrorDetail(e, "无法恢复上次会话，可创建新对话"))
    } finally {
      if (sidRef.current === id) setLoading(false)
    }
  }, [loadDetail])
  useEffect(() => {
    if (!enabled || !sid || sidRef.current !== sid) return
    void restoreSession(sid)
  }, [sid, enabled, restoreSession])
  useEffect(() => {
    const id = detail?.session.project_id || (isEditing ? projectId : null)
    setProjectName(""); setLegacy(null)
    if (!id) return
    let alive = true
    getProject(id).then(p => { if (alive) setProjectName(p.name) }).catch(() => { if (alive) setProjectName("关联工程已不可用") })
    getActiveAiOperation(id).then(op => { if (alive) setLegacy(op) }).catch(() => {})
    return () => { alive = false }
  }, [detail?.session.project_id, open, isEditing, projectId])
  useEffect(() => {
    if (followTail.current && feed.current) feed.current.scrollTop = feed.current.scrollHeight
  }, [detail?.messages, phase, open])
  const runId = detail?.run && isAssistantRunning(detail.run) ? detail.run.id : null
  useEffect(() => {
    if (!runId) return
    const run = detailRef.current?.run
    if (!run) return
    const source = new EventSource(`${ASSISTANT_API}/runs/${runId}/events`)
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true; source.close(); setPhase("")
      const current = sidRef.current
      if (current) loadDetail(current).then(next => {
        if (!next || sidRef.current !== current) return
        notifyReply(next)
      }).catch(e => {
        setDetail(state => state ? releaseTerminalAssistantRun(state, runId) : state)
        if (sidRef.current === current) setError(director2ErrorDetail(e, "回复已完成，读取结果失败，请刷新"))
      })
    }
    source.addEventListener("text", event => {
      const data = JSON.parse((event as MessageEvent).data)
      setDetail(current => current && current.run?.id === runId ? mergeAssistantEvent(current, data, run.message_id) : current)
    })
    source.addEventListener("snapshot", event => {
      const data = JSON.parse((event as MessageEvent).data)
      setDetail(current => current && current.run?.id === runId ? mergeAssistantEvent(current, data, run.message_id) : current)
    })
    source.addEventListener("status", event => setPhase(JSON.parse((event as MessageEvent).data).label))
    source.addEventListener("done", finish)
    source.addEventListener("terminal", finish)
    source.onerror = () => { if (!finished) setPhase("连接暂时中断，正在恢复回复…") }
    const fallback = window.setInterval(() => {
      if (source.readyState !== EventSource.OPEN && sidRef.current) void loadDetail(sidRef.current).catch(() => {})
    }, 5000)
    return () => { finished = true; source.close(); window.clearInterval(fallback) }
  }, [runId, loadDetail])
  const executing = detail?.executions.some(e => ["queued", "running"].includes(e.status))
  useEffect(() => {
    if (!executing || !sid) return
    const timer = window.setInterval(() => { void loadDetail(sid).catch(() => {}) }, 3000)
    return () => window.clearInterval(timer)
  }, [executing, sid, loadDetail])

  const changeOpen = useCallback((value: boolean, syncMode = false) => {
    if (isHome) { if (value && sidRef.current) setHomeStarted(true); composerInput.current?.focus(); return }
    setOpen(value)
    if (syncMode && !isEditing) window.dispatchEvent(new CustomEvent("director-assistant-mode", { detail: value ? "agent" : "manual" }))
  }, [isHome, isEditing])
  function notifyReply(next: AssistantDetail) {
    if (!shouldNotifyReply(document.visibilityState, document.hasFocus())) return
    const content = assistantReplyNotification(next)
    if (content) showAssistantReplyNotification(content, () => changeOpen(true, true))
  }
  function selectHistorySession(id: string) {
    if (busy) return
    if (isHome) setHomeStarted(true)
    const reloadCurrent = sidRef.current === id
    if (!reloadCurrent) setDetail(null)
    sidRef.current = id
    setSid(id)
    followTail.current = true
    if (reloadCurrent) void restoreSession(id)
  }
  function resetHomeDraft() {
    if (busy) return
    loadGeneration.current++
    sidRef.current = null; setSid(null); setDetail(null); setDraft(""); setError(""); setPhase("")
    setHomeStarted(false); submission.current = null; followTail.current = true
    try { if (activeStorageKey.current) localStorage.removeItem(activeStorageKey.current) } catch { /* History remains on the server. */ }
  }
  async function newConversation() {
    if (busy) return
    if (isHome) { resetHomeDraft(); return }
    setSending(true); setError("")
    try {
      const targetScope = scopeRef.current
      const session = await assistantMutate<AssistantSession>(csrfToken, "/sessions", { project_id: projectId, context: editingContext || null, selections })
      if (scopeRef.current !== targetScope) return
      sidRef.current = session.id; setSid(session.id)
      setDetail({ session, messages: [], artifacts: [], proposals: [], executions: [], run: null })
      setDraft(""); submission.current = null; followTail.current = true
    } catch (e) { setError(director2ErrorDetail(e, "创建对话失败")) }
    finally { setSending(false) }
  }
  async function select(next: AssistantSelections) {
    if (busy) return
    const previous = selections
    setSelections(next)
    if (!detail) return
    setSavingSelection(true)
    const targetId = detail.session.id
    try {
      let session: AssistantSession
      try {
        session = await assistantMutate<AssistantSession>(csrfToken, `/sessions/${targetId}`, { version: detail.session.version, selections: next }, "PATCH")
      } catch (e) {
        if (!(e instanceof ApiRequestError) || e.status !== 409) throw e
        const fresh = await assistantGet<AssistantDetail>(`/sessions/${targetId}`)
        session = await assistantMutate<AssistantSession>(csrfToken, `/sessions/${targetId}`, { version: fresh.session.version, selections: next }, "PATCH")
      }
      setDetail(current => current && current.session.id === session.id ? { ...current, session } : current); setSelections(session.selections)
    } catch (e) {
      setSelections(previous)
      message.error(director2ErrorDetail(e, "选择保存失败"))
      if (sid) await loadDetail(sid)
    } finally { setSavingSelection(false) }
  }
  async function startProject(input: HomeProjectRequest) {
    if (creatingProject) return
    setCreatingProject(true)
    try {
      const signature = JSON.stringify(input)
      if (projectCreation.current?.signature !== signature) {
        const project = await createProject(csrfToken, { name: input.filename || "未命名短剧", description: input.filename ? undefined : input.adaptation ? `${input.adaptation.sourceName} · 小说改编` : input.text.slice(0, 500), extra: homeProjectExtra(input) })
        projectCreation.current = { signature, projectId: project.id, messageId: crypto.randomUUID() }
      }
      const pending = projectCreation.current
      if (input.filename) {
        const document = await createDocument(csrfToken, pending.projectId, { filename: input.filename, raw_text: input.text, input_mode: "file" })
        navigate(`${director2ProjectPath(pending.projectId, "content")}?doc=${encodeURIComponent(document.id)}&section=body`)
      } else {
        if (!pending.sessionId) {
          const session = await assistantMutate<AssistantSession>(csrfToken, "/sessions", { project_id: pending.projectId, selections })
          pending.sessionId = session.id
        }
        await assistantMutate<AssistantRun>(csrfToken, `/sessions/${pending.sessionId}/messages`, { text: homeProjectMessage(input), client_message_id: pending.messageId })
        try { localStorage.setItem(`${STORAGE_KEY}:${pending.projectId}`, pending.sessionId) } catch { /* Server history remains available. */ }
        navigate(director2ProjectPath(pending.projectId, "content"))
      }
      projectCreation.current = null
    } finally { setCreatingProject(false) }
  }

  async function send(answer?: { question_id?: string; answer_values?: string[]; text?: string; skip?: boolean }) {
    if (busy || editingFlight.current || (!answer && !draft.trim())) return
    if (!catalog?.enabled || !catalog.available) return
    if (isHome) setHomeStarted(true)
    void requestAssistantNotificationPermission()
    setSending(true); setError(""); followTail.current = true
    const text = answer?.text ?? draft
    const targetScope = scopeRef.current
    try {
      if (isEditing) {
        if (!activeEditor) throw new Error("请等待当前剪辑加载完成")
        editingFlight.current = true
        try { await activeEditor.prepare() } finally { activeEditor.release(); editingFlight.current = false }
        if (scopeRef.current !== targetScope) return
      }
      let currentSid = sidRef.current
      if (!currentSid) {
        const session = await assistantMutate<AssistantSession>(csrfToken, "/sessions", { project_id: projectId, context: editingContext || null, selections })
        if (scopeRef.current !== targetScope) return
        currentSid = session.id; sidRef.current = currentSid; setSid(currentSid)
      }
      const signature = JSON.stringify({ sid: currentSid, ...answer, text })
      if (submission.current?.signature !== signature) submission.current = { signature, id: crypto.randomUUID() }
      const answeredQuestion = answer?.question_id ? detail?.session.pending_question : undefined
      await assistantMutate<AssistantRun>(csrfToken, `/sessions/${currentSid}/messages`, { ...answer, text, client_message_id: submission.current.id })
      if (projectId && answeredQuestion?.title?.includes("分辨率")) {
        window.dispatchEvent(new CustomEvent("director-assistant-project-updated", { detail: { projectId } }))
      }
      await loadDetail(currentSid)
      submission.current = null
      if (!answer && scopeRef.current === targetScope) setDraft("")
    } catch (e) { setError(director2ErrorDetail(e, "发送失败，输入内容已保留")) }
    finally { setSending(false) }
  }
  async function stop() {
    if (!detail?.run) return
    try { await assistantMutate(csrfToken, `/runs/${detail.run.id}/cancel`); setPhase("正在停止当前回复…") }
    catch (e) { setError(director2ErrorDetail(e, "停止失败")) }
  }
  async function retry(id: string) {
    if (busy) return
    void requestAssistantNotificationPermission()
    setSending(true)
    try { await assistantMutate(csrfToken, `/runs/${id}/retry`, { client_message_id: crypto.randomUUID() }); if (sid) await loadDetail(sid) }
    catch (e) { setError(director2ErrorDetail(e, "重试失败")) }
    finally { setSending(false) }
  }
  async function confirmMedia() {
    if (!media) return
    setConfirmingMedia(true)
    try { await assistantMutate(csrfToken, `/media/${media.id}/confirm`); setMedia(null); if (sid) await loadDetail(sid); message.success("已确认媒体任务，可在任务中心查看进度") }
    catch (e) { message.error(director2ErrorDetail(e, "提交失败")) }
    finally { setConfirmingMedia(false) }
  }
  async function runUnderstanding(force = false) {
    if (!isEditing || !projectId || !editingContext || understandingBusy) return
    const key = `${projectId}:${editingContext.sequence_id}`
    setUnderstandingBusy(true); setUnderstandingError("")
    try {
      const next = await startUnderstanding(csrfToken, projectId, editingContext.sequence_id, force)
      if (scopeRef.current !== key) return
      setUnderstanding(next)
      if (next.status === "empty") message.info(next.message || "时间线上还没有可理解的视频")
      else if (next.status === "failed") message.warning(next.message || "视频理解未完成，请检查视觉模型配置")
      else if (next.status === "succeeded" || next.status === "partial") message.success(next.message || "视频理解已完成")
    } catch (e) { if (scopeRef.current === key) setUnderstandingError(director2ErrorDetail(e, "启动视频理解失败")) }
    finally { setUnderstandingBusy(false) }
  }
  async function runTranscript(force = false) {
    if (!isEditing || !projectId || !editingContext || transcriptBusy) return
    const key = `${projectId}:${editingContext.sequence_id}`
    setTranscriptBusy(true); setTranscriptError("")
    try {
      const next = await startTranscript(csrfToken, projectId, editingContext.sequence_id, force)
      if (scopeRef.current !== key) return
      setTranscript(next)
      if (next.status === "empty") message.info(next.message || "音轨已转写，但没有识别到任何语音")
      else if (next.status === "failed") message.warning(next.message || "音频转写未完成，请检查素材音轨与转写服务配置")
      else if (next.status === "succeeded" || next.status === "partial") message.success(next.message || "音频转写已完成")
    } catch (e) { if (scopeRef.current === key) setTranscriptError(director2ErrorDetail(e, "启动音频转写失败")) }
    finally { setTranscriptBusy(false) }
  }
  const workflowProjectId = isEditing
    ? null
    : projectId
      ? !detail || detail.session.project_id === projectId ? projectId : null
      : detail?.session.project_id || null
  const selectedSkill = detail?.session.resource_snapshot.skill
  const selectedExpert = detail?.session.resource_snapshot.expert
  function resourceOptions(type: "skill" | "expert") {
    const resources = (catalog?.resources || []).filter(r => r.resource_type === type)
    const snapshot = type === "skill" ? selectedSkill : selectedExpert
    const result = resources.map(r => ({ label: r.name, value: r.version_id }))
    const selected = type === "skill" ? selections.skill_id : selections.expert_id
    if (selected && !result.some(o => o.value === selected) && snapshot) result.push({ label: `${snapshot.name}（已选版本）`, value: selected })
    return result
  }
  const chosenSkillName = resourceOptions("skill").find(r => r.value === selections.skill_id)?.label
  const chosenExpertName = resourceOptions("expert").find(r => r.value === selections.expert_id)?.label
  const chosenKnowledgeNames = selections.knowledge_ids.map(id => catalog?.knowledge.find(k => k.id === id)?.name || "已选知识库")
  const modelCapabilities = catalog?.models.find(m => m.id === selections.model_id)?.capabilities
  const webSearchSupported = !!modelCapabilities?.web_search
  function selectResource(resource: AssistantResource) { void select({ ...selections, [resource.resource_type === "skill" ? "skill_id" : "expert_id"]: resource.version_id }) }
  function resourcePicker(type: "skill" | "expert") {
    const selected = type === "skill" ? selections.skill_id : selections.expert_id
    return <ResourcePicker kind={type} resources={catalog?.resources || []} selectedVersionId={selected} busy={busy} onSelect={resource => { selectResource(resource); setPicker(null) }} onOpenMarket={() => { setPicker(null); setMarket(type) }} />
  }
  function executionStatus(proposal: MediaProposal) {
    const execution = detail?.executions.find(e => e.id === proposal.execution_id)
    return execution ? ({ queued: "已排队", running: "正在提交生成", succeeded: "已提交 / 完成", failed: "执行失败", interrupted: "执行中断，请先核对任务中心" }[execution.status] || execution.status) : "待确认执行"
  }
  function renderProposal(proposal: MediaProposal, execution?: MediaExecution) {
    return <section className="assistant-deliverable" key={proposal.id}><div><Sparkles size={17} /><strong>{proposal.title}</strong><Tag>{mediaLabels[proposal.media_type]}</Tag></div><p>{proposal.project_name} · {executionStatus(proposal)}</p>{execution?.error && <Alert type="error" title={execution.error} />}<Space><Button size="small" disabled={!!proposal.execution_id} onClick={() => setMedia(proposal)}>查看并确认执行</Button><Button size="small" type="text" onClick={() => navigate(director2ProjectPath(proposal.project_id, "jobs"))}>任务中心</Button></Space></section>
  }

  async function openEditingAction(proposal: EditingAction) {
    if (proposal.project_id !== projectId || proposal.sequence_id !== editingContext?.sequence_id) return
    try {
      const action = await readEditingAction(proposal.project_id, proposal.sequence_id, proposal.id)
      if (scopeRef.current !== `${proposal.project_id}:${proposal.sequence_id}`) return
      if (action.status === "succeeded") { setActionFeedback(action); return }
      if (!action.count) { message.info(emptyHint(action.operation)); return }
      setActionError(""); setEditingOrder(action.items.flatMap(item => item.asset_id ? [item.asset_id] : [])); setEditingAction(action)
    } catch (e) { setError(director2ErrorDetail(e, "读取剪辑清单失败")) }
  }
  async function previewEditing(operation: EditingOperation, strategy?: HookStrategy) {
    if (busy || editingFlight.current || !activeEditor) return
    editingFlight.current = true
    const bridge = activeEditor, targetScope = scopeRef.current
    setEditingBusy(true); setEditingOperation(operation); setError("")
    try {
      const revision = await bridge.prepare()
      const action = await previewEditingAction(csrfToken, bridge.projectId, bridge.sequenceId, revision, detail?.session.id, operation, undefined, strategy)
      if (scopeRef.current !== targetScope) return
      openedActions.current.add(action.id)
      if (sidRef.current) await loadDetail(sidRef.current)
      if (!action.count) { setActionFeedback(action); message.info(emptyHint(action.operation)) }
      else { setActionError(""); setEditingOrder(action.items.flatMap(item => item.asset_id ? [item.asset_id] : [])); setEditingAction(action) }
    } catch (e) { if (scopeRef.current === targetScope) setError(director2ErrorDetail(e, `准备${OPERATION_TITLES[operation]}失败，请先完成剪辑保存`)) }
    finally { bridge.release(); editingFlight.current = false; setEditingBusy(false); setEditingOperation(null) }
  }
  async function confirmEditing() {
    if (!editingAction || !activeEditor || confirmingAction || editingFlight.current) return
    editingFlight.current = true
    const action = editingAction, bridge = activeEditor, targetScope = scopeRef.current, order = editingOrder
    const currentOrder = action.items.flatMap(item => item.asset_id ? [item.asset_id] : [])
    const reordered = order.length > 0 && order.length === currentOrder.length && order.join("\n") !== currentOrder.join("\n")
    setConfirmingAction(true); setEditingOperation(action.operation); setActionError("")
    try {
      const revision = await bridge.prepare()
      let result = await readEditingAction(action.project_id, action.sequence_id, action.id)
      if (result.status !== "succeeded") {
        if (revision !== action.base_revision) throw new Error("时间线已变化，请关闭并重新预览清单")
        if (action.operation === "video_arrange" && reordered) result = await reorderEditingAction(csrfToken, action.project_id, action.sequence_id, action.id, order)
        try { result = await confirmEditingAction(csrfToken, action.project_id, action.sequence_id, action.id) }
        catch (error) {
          // The HTTP response may have been lost after the transaction committed.
          result = await readEditingAction(action.project_id, action.sequence_id, action.id).catch(() => { throw error })
          if (result.status !== "succeeded") throw error
        }
      }
      if (!result.snapshot) throw new Error("执行结果缺少剪辑文档，请重新加载剪辑")
      if (scopeRef.current !== targetScope) return
      if (revision === action.base_revision) bridge.apply(result.snapshot, action.base_revision)
      setActionFeedback(result); setEditingAction(null); setEditingOrder([])
      if (sidRef.current) await loadDetail(sidRef.current)
      message.success(successText(result))
    } catch (e) { if (scopeRef.current === targetScope) setActionError(director2ErrorDetail(e, "操作未完成。重试时会先核对执行记录。")) }
    finally { bridge.release(); editingFlight.current = false; setConfirmingAction(false); setEditingOperation(null) }
  }
  function moveEditingItem(index: number, delta: number) {
    setEditingOrder(current => {
      const target = index + delta
      if (target < 0 || target >= current.length) return current
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }
  const orderedEditingItems = editingAction
    ? editingAction.operation === "video_arrange" && editingOrder.length === editingAction.items.length
      ? editingOrder.flatMap(id => {
          const item = editingAction.items.find(entry => entry.asset_id === id)
          return item ? [item] : []
        })
      : editingAction.items
    : []
  useEffect(() => {
    if (!isEditing || busy || !activeEditor) return
    const pending = newestPendingEditingAction(detail?.edit_proposals || [], openedActions.current)
    if (pending) { openedActions.current.add(pending.id); void openEditingAction(pending) }
  }, [detail?.edit_proposals, busy, activeEditor, isEditing])
  function understandingCard() {
    if (!isEditing) return null
    const status = understanding?.status || "missing"
    const stale = !!understanding?.stale
    const active = analysisActive(status)
    const done = (status === "succeeded" || status === "partial") && !stale
    const items = done ? (understanding?.items || []).filter(item => item.status !== "failed") : []
    const failed = done ? (understanding?.items || []).filter(item => item.status === "failed") : []
    const videos = understanding?.summary?.video_count ?? 0
    const detected = understanding?.summary?.detected_shot_count ?? 0
    const sampled = understanding?.summary?.shot_count ?? 0
    const analyzed = understanding?.summary?.shot_analyzed_count ?? 0
    const analyzedAt = understanding?.finished_at ? new Date(understanding.finished_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""
    return <section className={`assistant-understanding${active ? " is-running" : ""}`}>
      <div className="assistant-understanding-head">
        <span><Eye size={15} /><strong>视频理解</strong></span>
        <Tag color={stale ? "warning" : ANALYSIS_COLORS[status]}>{stale ? "素材已变化" : UNDERSTANDING_LABELS[status]}</Tag>
      </div>
      <p className="assistant-understanding-summary">{understanding ? understandingText(understanding) : "正在读取视频理解状态…"}</p>
      {active && <Progress className="assistant-understanding-progress" percent={understanding?.progress ?? 0} size="small" status="active" />}
      {active && videos > 0 && <p className="assistant-understanding-meta">{sampled > 0 ? `共检测 ${detected} 个镜头 · 已采样 ${sampled} 个 · 已理解 ${analyzed} 个` : `共 ${videos} 条素材 · 正在检测镜头边界`}</p>}
      {!!analyzedAt && !active && !stale && <p className="assistant-understanding-meta">{[understanding?.model, analyzedAt].filter(Boolean).join(" · ")}</p>}
      {items.length > 0 && <Collapse ghost size="small" className="assistant-understanding-items" items={[{ key: "shots", label: `逐镜画面依据 · ${items.length} 条素材 · ${analyzed} 个镜头`, children: <div className="assistant-understanding-shots">{items.map((item, index) => {
        const shots = item.shots || []
        const subjects = item.subjects.map(subject => subject.name).join("、")
        return <div key={`${item.asset_id}-${index}`} className="assistant-understanding-shot">
          <div><strong>{item.name}</strong><span>{item.duration.toFixed(2)} 秒 · 检测 {item.detected_count ?? shots.length} 镜 / 采样 {item.sampled_count ?? shots.length} 镜</span></div>
          <p>{item.description}</p>
          {(item.camera || subjects) && <small>{[item.camera, subjects].filter(Boolean).join(" · ")}</small>}
          {item.detection_error && <small>镜头边界检测失败，已按整条视频分析：{item.detection_error}</small>}
          {shots.length > 1 && <div className="assistant-understanding-subshots">{shots.map(shot => {
            const shotSubjects = shot.subjects.map(subject => subject.name).join("、")
            return <div key={shot.index} className="assistant-understanding-subshot">
              <div><strong>镜头 {shot.index}</strong><span>{shot.start.toFixed(2)}–{shot.end.toFixed(2)} 秒{shot.status === "failed" ? " · 未理解" : ""}</span></div>
              <p>{shot.status === "succeeded" ? shot.description : shot.error || "镜头理解失败"}</p>
              {shot.status === "succeeded" && (shot.camera || shotSubjects) && <small>{[shot.camera, shotSubjects].filter(Boolean).join(" · ")}</small>}
            </div>
          })}</div>}
        </div>
      })}</div> }]} />}
      {failed.length > 0 && <p className="assistant-understanding-meta">未理解：{failed.map(item => item.name).join("、")}（可重新理解）</p>}
      {!active && <div className="assistant-understanding-actions">{status === "missing" ? <Popconfirm title="开始视频理解？" description="将下载当前分集的视频素材，用 ffmpeg 检测内部镜头边界；每条素材最多采样 4 个镜头（单次最多 40 个），每个采样镜头抽取 2 个关键帧并调用视觉模型分析，可能消耗模型额度。不会转写音频，也不会改动时间线。" okText="开始分析" cancelText="取消" rootClassName="assistant-analysis-popconfirm" onConfirm={() => void runUnderstanding()}><Button size="small" icon={<Eye size={13} />} loading={understandingBusy}>开始视频理解</Button></Popconfirm> : <Popconfirm title="重新理解视频画面？" description="会重新检测镜头边界并抽取关键帧调用视觉模型，可能消耗模型额度。已有画面描述将被覆盖；时间线不会被改动。" okText="重新分析" cancelText="取消" rootClassName="assistant-analysis-popconfirm" onConfirm={() => void runUnderstanding(true)}><Button size="small" type={status === "succeeded" && !stale ? "text" : "default"} icon={<RefreshCw size={13} />} loading={understandingBusy}>重新理解</Button></Popconfirm>}</div>}
      {understandingError && <Alert className="assistant-understanding-error" type="error" showIcon title={understandingError} />}
    </section>
  }
  function transcriptCard() {
    if (!isEditing) return null
    const status = transcript?.status || "missing"
    const stale = !!transcript?.stale
    const active = analysisActive(status)
    const media = transcript?.summary?.media_count ?? 0
    const done = transcript?.summary?.transcribed_count ?? 0
    const segments = transcript?.summary?.segment_count ?? 0
    const seconds = transcript?.summary?.audio_seconds ?? 0
    const voiced = (transcript?.items || []).filter(item => item.status === "succeeded" && item.segments.length)
    const broken = (transcript?.items || []).filter(item => item.status === "failed" || item.status === "skipped")
    const finishedAt = transcript?.finished_at ? new Date(transcript.finished_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""
    return <section className={`assistant-transcript${active ? " is-running" : ""}`}>
      <div className="assistant-transcript-head">
        <span><AudioLines size={15} /><strong>音频转写</strong></span>
        <Tag color={stale ? "warning" : ANALYSIS_COLORS[status]}>{stale ? "素材已变化" : TRANSCRIPT_LABELS[status]}</Tag>
      </div>
      <p className="assistant-transcript-summary">{transcript ? transcriptText(transcript) : "正在读取音频转写状态…"}</p>
      {active && <Progress className="assistant-transcript-progress" percent={transcript?.progress ?? 0} size="small" status="active" />}
      {active && media > 0 && <p className="assistant-transcript-meta">共 {media} 条有声素材 · 已完成 {done} 条</p>}
      {!!finishedAt && !active && !stale && <p className="assistant-transcript-meta">{[transcript?.model, `${segments} 段 / ${seconds.toFixed(1)} 秒音频`, finishedAt].filter(Boolean).join(" · ")}</p>}
      {voiced.length > 0 && <Collapse ghost size="small" className="assistant-transcript-items" items={[{ key: "segments", label: `逐段语音依据 · ${voiced.length} 条素材 · ${segments} 段`, children: <div className="assistant-transcript-segments">{voiced.map((item, index) => <div key={`${item.asset_id}-${index}`} className="assistant-transcript-asset">
        <div className="assistant-transcript-asset-head"><strong>{item.name}</strong><span>{typeof item.timeline_start === "number" ? `时间线 ${item.timeline_start.toFixed(2)} 秒 · ` : ""}{item.segments.length} 段 / {item.audio_seconds.toFixed(1)} 秒</span></div>
        <div className="assistant-transcript-lines">{item.segments.map(segment => <div className="assistant-transcript-line" key={segment.id}><span>{segment.start.toFixed(2)}–{segment.end.toFixed(2)} 秒</span><p>{segment.text}</p></div>)}</div>
      </div>)}</div> }]} />}
      {!active && broken.length > 0 && <p className="assistant-transcript-meta">未转成功：{broken.map(item => `${item.name}（${item.error || "转写失败"}）`).join("、")}</p>}
      {!active && <div className="assistant-transcript-actions">{status === "missing" ? <Popconfirm title="开始音频转写？" description="会下载时间线上仍在发声的素材，在本地提取 16kHz 单声道音轨，再提交给已配置的第三方转写服务，按音频秒计费；单次最多 40 条素材、600 秒音频，未上时间线的素材不会外发，临时音轨用完即删。转写只生成段落依据，不改动时间线。" okText="开始转写" cancelText="取消" rootClassName="assistant-analysis-popconfirm" onConfirm={() => void runTranscript()}><Button size="small" icon={<AudioLines size={13} />} loading={transcriptBusy}>转写音频</Button></Popconfirm> : <Popconfirm title="重新转写音轨？" description="会重新提取音轨并提交第三方转写服务，按音频秒计费，已有转写段落将被覆盖。时间线不会被改动。" okText="重新转写" cancelText="取消" rootClassName="assistant-analysis-popconfirm" onConfirm={() => void runTranscript(true)}><Button size="small" type={status === "succeeded" && !stale ? "text" : "default"} icon={<RefreshCw size={13} />} loading={transcriptBusy}>重新转写</Button></Popconfirm>}</div>}
      {transcriptError && <Alert className="assistant-transcript-error" type="error" showIcon title={transcriptError} />}
    </section>
  }
  function editingTools() {
    return <div className="assistant-edit-tools"><p className="assistant-edit-group-label">剪辑工具</p><div className="assistant-edit-tool-buttons">{EDITING_TOOL_GROUPS.map(group => {
      const tool = group.tools[0]
      const Icon = tool.Icon
      if (group.tools.length === 1) return <Button key={group.id} icon={<Icon size={14} />} disabled={busy || !activeEditor} loading={editingBusy && editingOperation === tool.id} onClick={() => void previewEditing(tool.id)}>{tool.label}</Button>
      return <Dropdown key={group.id} trigger={["click"]} disabled={busy || !activeEditor} menu={{
        items: group.tools.map(item => ({ key: item.id, label: item.label, icon: <item.Icon size={14} />, children: item.strategies?.map(strategy => ({ key: `${item.id}:${strategy.id}`, label: <span className="assistant-edit-strategy"><strong>{strategy.label}</strong><small>{strategy.description}</small></span> })) })),
        onClick: ({ key }) => {
          const [operation, strategy] = key.split(":")
          const selectedTool = group.tools.find(item => item.id === operation)
          if (selectedTool) void previewEditing(selectedTool.id, strategy as HookStrategy | undefined)
        }
      }}><Button aria-label={`${group.label}工具`} icon={<Icon size={14} />} disabled={busy || !activeEditor} loading={editingBusy && group.tools.some(item => item.id === editingOperation)}>{group.label}<ChevronDown size={11} /></Button></Dropdown>
    })}</div></div>
  }

  function historyControl() { return <Dropdown trigger={["click"]} onOpenChange={value => { if (value) assistantGet<AssistantSession[]>("/sessions").then(sessions => setHistory(sessions.filter(s => matchesAssistantScope(s, projectId, editingContext)))).catch(e => message.error(director2ErrorDetail(e, "读取历史失败"))) }} menu={{ items: scopedHistory.length ? scopedHistory.map(s => ({ key: s.id, label: <span className="assistant-history-title">{s.title}<small>{s.project_id ? "工程对话" : "独立创作"}</small></span> })) : [{ key: "empty", label: "还没有历史对话", disabled: true }], onClick: ({ key }) => selectHistorySession(key), style: { maxWidth: 360, maxHeight: 420, overflowY: "auto" } }}><Button type="text" size="small" aria-label="历史对话" disabled={busy} icon={<History size={isHome ? 13 : 15} />}>{isHome ? "历史对话" : null}</Button></Dropdown> }
  const workspace = (
      <div className={`assistant-workspace${isHome ? ` director-assistant-home ${homeStarted ? "is-conversation" : "is-start"}` : ""}`}>
        {isHome && homeStarted && <div className="assistant-home-nav">
          <Button type="text" icon={<ArrowLeft size={14} />} disabled={busy} onClick={resetHomeDraft}>返回首页</Button>
          <strong title={detail?.session.title}>{detail?.session.title || "新的创作"}</strong>
          <div><Button type="text" icon={<Plus size={14} />} disabled={busy} onClick={newConversation}>新对话</Button>{historyControl()}</div>
        </div>}
        {(!isHome || homeStarted) && <>
        <div className="assistant-project-link"><BookOpen size={13} /><span>{isEditing ? `${projectName || "当前工程"} · ${activeEditor?.sequenceName || "加载剪辑中…"}` : detail?.session.project_id ? `关联工程：${projectName || detail.session.project_id}` : projectId && !detail ? "新对话将关联当前工程" : "独立创作 · 采纳时选择工程"}</span>{detail?.session.project_id && <Button type="link" size="small" onClick={() => navigate(director2ProjectPath(detail.session.project_id!, "content"))}>查看</Button>}</div>
        {workflowProjectId && !isProject && <WorkflowProgressCard projectId={workflowProjectId} csrfToken={csrfToken} open={open} busy={busy} canPrompt={!!catalog?.available} onPrompt={text => { void send({ text }) }} onNavigate={(menu, episodeId) => navigate(director2ProjectPath(workflowProjectId, menu, episodeId))} />}
        {!!legacy && <Alert className="assistant-legacy-notice" type="info" title="此工程有待继续的旧版 AI 任务" action={<Button size="small" onClick={() => setLegacyOpen(true)}>继续旧任务</Button>} />}
        <div ref={feed} className="assistant-feed" onScroll={() => { const node = feed.current; if (node) followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80 }} aria-live="polite">
          {loading && <Spin className="assistant-loading" />}
          {!isHome && !loading && !detail?.messages.length && (isEditing ? <div className="assistant-welcome assistant-edit-welcome"><div className="assistant-welcome-symbol"><Sparkles size={25} /></div><h2>Hi，我是您的智能剪辑助手</h2><p>铺轨、精剪、速剪、高光合集、引流剪辑、自动字幕与音轨字幕，<br />先读取画面理解或音轨转写依据，再预览清单，确认后写入时间线。</p>{understandingCard()}{transcriptCard()}{editingTools()}<p className="assistant-welcome-example">也可以直接说：“按分镜帮我铺轨”、“做一版3秒进冲突的引流剪辑”或“转写音频后按真实声音上字幕”。</p></div> : <div className="assistant-welcome"><div className="assistant-welcome-symbol"><Sparkles size={25} /></div><h2>{isProject ? "继续完善你的故事" : "从一个想法开始"}</h2><p>{isProject ? "告诉我想调整的情节或人物，我会先给出草稿，采纳后写入当前剧本。" : <>选一个 Skill，带上专家和参考资料，<br />我们一步步把故事做出来。</>}</p>{!isProject && <div className="assistant-welcome-skills">{catalog?.resources.filter(r => r.resource_type === "skill" && r.builtin).map(r => <Button key={r.id} className="assistant-welcome-skill" disabled={busy} onClick={() => selectResource(r)}><ResourceCover resource={r} variant="picker" /><span><strong>{r.name}</strong><small>{r.category}</small></span></Button>)}</div>}<p className="assistant-welcome-example">也可以直接说：“我想做一个西游悬疑故事，帮我找方向。”</p></div>)}
          {isEditing && !!detail?.messages.length && <Collapse className="assistant-edit-toolbox" ghost size="small" items={[{ key: "tools", label: "剪辑工具", children: editingTools() }]} />}
          {isEditing && !!detail?.messages.length && understandingCard()}
          {isEditing && !!detail?.messages.length && transcriptCard()}
          {detail?.messages.map(m => <article className={`assistant-message is-${m.role}`} key={m.id}>
            {m.role === "assistant" && <div className="assistant-speaker"><Sparkles size={13} /><span>{m.resource_names?.expert || "智能助手"}</span></div>}
            {m.parts.map((part, index) => {
              if (part.type === "markdown") return part.text ? <div key={index} className="assistant-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]}>{part.text}</Markdown></div> : null
              if (part.type === "tool") return <div key={index} className="assistant-tool-trace">{part.status === "failed" ? <X size={12} /> : <Check size={12} />}<span>{part.label}</span>{part.detail && <small>{part.detail}</small>}</div>
              if (part.type === "question") return <QuestionCard key={part.question.id} question={part.question} active={detail.session.pending_question?.id === part.question.id} busy={busy} onAnswer={send} />
              if (part.type === "artifact") {
                const a = detail.artifacts.find(a => a.id === part.artifact_id)
                return a ? <section className="assistant-deliverable" key={index}><div><FileText size={17} /><strong>{a.title}</strong><Tag>{artifactLabels[a.artifact_type]}</Tag></div><p>第 {a.revision} 版 · {a.application_id ? "已采纳到工程" : "会话草稿，尚未写入工程"}</p><Button size="small" onClick={() => setArtifact(a)}>查看{a.application_id ? "内容" : "并采纳"}</Button></section> : <Spin key={index} size="small" />
              }
              if (part.type === "approval") { const proposal = detail.proposals.find(p => p.id === part.proposal_id); return proposal ? <Fragment key={index}>{renderProposal(proposal, detail.executions.find(e => e.id === proposal.execution_id))}</Fragment> : null }
              if (part.type === "edit_action") {
                const action = detail.edit_proposals?.find(p => p.id === part.action_id)
                return action ? <section className="assistant-deliverable" key={index}><div><Wand2 size={17} /><strong>{action.title}</strong><Tag>{action.status === "succeeded" ? "已完成并保存" : action.count ? "待确认" : "无需执行"}</Tag></div><p>{actionSummary(action)}</p>{action.operation === "video_arrange" && (action.missing_video_count || 0) > 0 && <p>{action.missing_video_count} 个分镜尚无视频，未用分镜图替代。</p>}{action.status === "pending" && <Button size="small" disabled={busy || !activeEditor} onClick={() => void openEditingAction(action)}>{ACTION_BUTTONS[action.operation]}</Button>}</section> : null
              }
              if (part.type === "citations") return <Collapse key={index} ghost size="small" items={[{ key: "sources", label: `参考资料 · ${part.items.length} 处出处`, children: part.items.map(c => <blockquote className="assistant-citation" key={c.id}><strong>{c.filename} · {c.section}</strong><p>{c.text}</p></blockquote>) }]} />
              if (part.type === "web_search") return <Collapse key={index} ghost size="small" items={[{ key: "web", label: `联网来源 · ${part.results.length} 处`, children: part.results.map((item, i) => <a className="assistant-web-result" key={`${item.url}-${i}`} href={item.url} target="_blank" rel="noreferrer noopener"><strong>{item.title}</strong>{item.site && <small>{item.site}</small>}</a>) }]} />
              if (part.type === "usage") {
                const usage = part.usage
                const cached = usage.cached_tokens || 0
                const requests = usage.requests || 0
                return <div key={index} className="assistant-usage-line">输入 {usage.prompt_tokens.toLocaleString("zh-CN")} · 输出 {usage.completion_tokens.toLocaleString("zh-CN")} tokens{cached > 0 && ` · 缓存命中 ${cached.toLocaleString("zh-CN")}`}{requests > 1 && ` · ${requests} 次请求`}</div>
              }
              return null
            })}
            {m.error && <Alert type="error" title={m.error} action={<Button size="small" disabled={busy} onClick={() => retry(m.run_id)}>重试继续</Button>} />}
            {["cancelled", "interrupted"].includes(m.status) && <div className="assistant-stopped">{m.status === "cancelled" ? "已停止本轮回复" : "本轮已中断"}<Button type="link" size="small" disabled={busy} onClick={() => retry(m.run_id)}>继续创作</Button></div>}
          </article>)}
          {busy && <div className="assistant-phase"><Spin size="small" /><span>{editingBusy && editingOperation ? `正在准备${OPERATION_TITLES[editingOperation]}…` : confirmingAction && editingOperation ? `正在应用${OPERATION_TITLES[editingOperation]}并保存…` : phase || "正在准备回复…"}</span></div>}
          {isEditing && actionFeedback && !detail?.edit_proposals?.some(p => p.id === actionFeedback.id) && <Alert className="assistant-edit-feedback" showIcon type={actionFeedback.status === "succeeded" ? "success" : "info"} title={actionFeedback.status === "succeeded" ? successText(actionFeedback) : emptyHint(actionFeedback.operation)} description={actionFeedback.status === "succeeded" ? feedbackDetail(actionFeedback) : "请先完成对应素材准备后重试。"} />}
        </div>
        </>}
        {error && <Alert className="assistant-error" type="error" showIcon title={error} action={sid ? <Button size="small" onClick={() => { setError(""); void restoreSession(sid) }}>重新加载</Button> : undefined} closable onClose={() => setError("")} />}
        {catalogError && <Alert type="error" title={catalogError} action={<Button size="small" onClick={() => refreshCatalog().catch(e => setCatalogError(director2ErrorDetail(e, "加载失败")))}>重试</Button>} />}
        {catalog && (!catalog.enabled || !catalog.available) && <Alert type="warning" title={catalog.unavailable_reason || "请管理员配置大模型服务后开始对话"} />}
        <div className="assistant-composer-shell">
          <div className="assistant-composer">
            {isHome && <div className="assistant-home-composer-heading"><span><Sparkles size={13} />{chosenSkillName || "短剧创作"}{chosenSkillName && <Button type="text" size="small" aria-label="移除 Skill" disabled={busy} icon={<X size={11} />} onClick={() => void select({ ...selections, skill_id: null })} />}</span>{!homeStarted && historyControl()}</div>}
            <div className="assistant-composer-body">
            {!isHome && chosenSkillName && <div className="assistant-selection-chips"><Tooltip classNames={{ root: "director-assistant-tooltip" }} title={chosenSkillName}><Tag className="assistant-skill-tag" icon={<Zap size={11} />} closable={!busy} closeIcon={<X size={11} aria-label="移除 Skill" />} onClose={e => { e.preventDefault(); if (!busy) void select({ ...selections, skill_id: null }) }}><span className="assistant-chip-label">{chosenSkillName}</span></Tag></Tooltip></div>}
            <Input.TextArea ref={composerInput} value={draft} onChange={e => setDraft(e.target.value)} placeholder={isHome && !homeStarted ? "说说你的故事想法，也可以粘贴已有剧本…" : isEditing ? "试试说：“按分镜帮我铺轨”、“先转写音频”或“按真实声音上字幕”…" : "说说你的想法，或告诉我接下来想做什么…"} aria-label="给智能助手发送消息" autoSize={isHome ? false : { minRows: 2, maxRows: 10 }} maxLength={50000} disabled={sending || confirmingAction} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (!busy && enabled && catalog?.available) void send() } }} variant="borderless" />
            <div className="assistant-composer-toolbar">
              <Popover trigger="click" placement="topLeft" destroyOnHidden open={picker === "skill"} onOpenChange={value => setPicker(value ? "skill" : null)} classNames={{ root: "director-assistant-tooltip assistant-picker-popover" }} content={resourcePicker("skill")}><Button type="text" size="small" disabled={busy} icon={<Zap size={14} />}>Skill{isHome && <ChevronDown size={10} />}</Button></Popover>
              <Popover trigger="click" placement="topLeft" destroyOnHidden open={picker === "expert"} onOpenChange={value => setPicker(value ? "expert" : null)} classNames={{ root: "director-assistant-tooltip assistant-picker-popover" }} content={resourcePicker("expert")}><Tooltip classNames={{ root: "director-assistant-tooltip" }} title={chosenExpertName || "选择专家"}><Button type="text" size="small" aria-label="专家" aria-pressed={!!chosenExpertName} className={chosenExpertName ? "assistant-tool-selected" : undefined} disabled={busy} icon={<Wand2 size={14} />}><span className="assistant-expert-label">{chosenExpertName || "专家"}</span></Button></Tooltip></Popover>
              <Popover trigger="click" placement="topLeft" content={<div className="assistant-picker"><Select aria-label="选择知识库" mode="multiple" placeholder="选择参考知识库" value={selections.knowledge_ids} disabled={busy} options={catalog?.knowledge.map(k => ({ label: k.name, value: k.id, disabled: !k.documents.some(d => d.status === "ready") }))} onChange={v => { void select({ ...selections, knowledge_ids: v }) }} /><Button type="text" block onClick={() => setKnowledgeOpen(true)}>管理知识库与资料</Button></div>}><Tooltip classNames={{ root: "director-assistant-tooltip" }} title={chosenKnowledgeNames.length ? <div>{chosenKnowledgeNames.map((name, i) => <div key={selections.knowledge_ids[i]}>{name}</div>)}</div> : "选择知识库"}><Button type="text" size="small" aria-label="知识库" aria-pressed={selections.knowledge_ids.length > 0} className={selections.knowledge_ids.length ? "assistant-tool-selected" : undefined} disabled={busy} icon={<BookOpen size={14} />}>{isHome ? "参考资料" : "知识库"}{selections.knowledge_ids.length > 0 && <span className="assistant-knowledge-count">{selections.knowledge_ids.length}</span>}</Button></Tooltip></Popover>
              <Popover trigger="click" placement="topRight" content={<div className="assistant-picker"><strong>推理模型</strong><Select aria-label="选择助手模型" showSearch value={selections.model_id || undefined} options={catalog?.models.map(m => ({ label: m.label, value: m.id }))} disabled={busy} onChange={v => { void select({ ...selections, model_id: v }) }} /><p className="assistant-secondary">由管理员开放，切换仅影响本会话后续任务。</p></div>}><Button type="text" size="small" disabled={busy} icon={<Sparkles size={13} />}>模型<ChevronDown size={10} /></Button></Popover>
              <Tooltip classNames={{ root: "director-assistant-tooltip" }} title={webSearchSupported ? (selections.web_search ? "已开启联网搜索，本轮可获取实时信息" : "开启联网搜索，获取实时信息并标注来源") : "当前模型未开放联网搜索"}><Button type="text" size="small" aria-label="联网搜索" aria-pressed={!!selections.web_search} className={selections.web_search && webSearchSupported ? "assistant-tool-selected" : undefined} disabled={busy || !webSearchSupported} icon={<Globe size={14} />} onClick={() => { if (!busy) void select({ ...selections, web_search: !selections.web_search }) }}>联网</Button></Tooltip>
              <span className="assistant-toolbar-spacer" />
              {isAssistantRunning(detail?.run) ? <Tooltip classNames={{ root: "director-assistant-tooltip" }} title="停止回复"><Button className="assistant-send" type="primary" shape="circle" aria-label="停止回复" icon={<Square size={12} />} onClick={stop} /></Tooltip> : <Button className="assistant-send" type="primary" shape="circle" aria-label="发送消息" loading={sending} disabled={!draft.trim() || !enabled || !catalog?.available || busy || (isEditing && !activeEditor)} icon={<ArrowUp size={16} />} onClick={() => send()} />}
            </div>
            </div>
          </div>
          {(!isHome || homeStarted) && <p className="assistant-composer-hint" title={selections.model_id}>{selections.model_id || "尚未选择模型"} · Enter 发送，Shift+Enter 换行</p>}
        </div>
        {isHome && !homeStarted && <div className="assistant-home-suggestions">
          {[
            ["写一个短剧", "帮我写一个短剧，先和我确认故事方向。"],
            ["修改剧本", "我想修改一个剧本，请先了解我希望调整的内容。"],
            ["拆分镜", "帮我把剧本拆成分镜，请先确认剧本和画面风格。"],
          ].map(([label, prompt]) => <Button key={label} disabled={busy} onClick={() => { setDraft(prompt); composerInput.current?.focus() }}><span aria-hidden="true">/</span>{label}</Button>)}
          <Button disabled={busy} onClick={() => setMarket("skill")}>更多技能</Button>
        </div>}
      </div>
  )

  return <AssistantContext.Provider value={{ enabled, ready: !!catalog || !!catalogError, open, setOpen: changeOpen, prompt: text => { setDraft(text); changeOpen(true, true); composerInput.current?.focus() }, registerEditor }}>
    <AssistantHomeContext.Provider value={{ active: homeStarted, surface: isHome ? workspace : null, creating: creatingProject, available: !!catalog?.available && enabled, startProject }}>
    <div className={`assistant-app-host${isEditing && open ? " has-editing-assistant" : ""}${isProject && open ? " has-project-assistant" : ""}`} style={isEditing && open ? { paddingRight: dockWidth } : undefined}>{children}{isProject && open && <aside className="director-assistant-drawer director-project-assistant" aria-label="短剧助手"><header><span className="assistant-title"><Sparkles size={16} />短剧助手</span><Space size={2}>{historyControl()}<Button type="text" size="small" aria-label="新对话" disabled={busy} icon={<Plus size={16} />} onClick={newConversation}/><Button type="text" size="small" aria-label="关闭智能助手" icon={<X size={16} />} onClick={() => changeOpen(false, true)}/></Space></header>{workspace}</aside>}</div>
    </AssistantHomeContext.Provider>
    {!isHome && (enabled || catalogError) && !open && <Tooltip classNames={{ root: "director-assistant-tooltip" }} title={catalogError || "打开智能助手"}><Button className="director-assistant-launcher" type="primary" icon={<Sparkles size={18} />} onClick={() => { if (catalogError) void refreshCatalog().catch(e => setCatalogError(director2ErrorDetail(e, "助手加载失败"))); changeOpen(true, true) }}>智能助手</Button></Tooltip>}
    {!isHome && !isProject && <Drawer title={<span className="assistant-title"><Sparkles size={16} />{isEditing ? "智能剪辑助手" : "智能助手"}</span>} open={open} onClose={() => changeOpen(false, true)} closable={false} mask={false} autoFocus={false} size={isEditing ? dockWidth : expanded ? Math.min(800, window.innerWidth - 100) : 480} rootClassName={`director-assistant-drawer${isEditing ? " is-editing-assistant" : ""}`} zIndex={1000} styles={{ root: { pointerEvents: "none" }, wrapper: { pointerEvents: "auto" }, body: { padding: 0, overflow: "hidden" }, header: { padding: "10px 14px" } }} extra={<Space size={2}>
      <Tooltip classNames={{ root: "director-assistant-tooltip" }} title="新对话"><Button type="text" size="small" aria-label="新对话" disabled={busy} icon={<Plus size={16} />} onClick={newConversation} /></Tooltip>
      {historyControl()}
      {!isEditing && <Tooltip classNames={{ root: "director-assistant-tooltip" }} title={expanded ? "收起宽度" : "展开宽度"}><Button type="text" size="small" aria-label={expanded ? "收起宽度" : "展开宽度"} icon={expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />} onClick={() => setExpanded(v => !v)} /></Tooltip>}
      <ThemeToggle tooltipClassName="director-assistant-tooltip" />
      <Button type="text" size="small" aria-label="关闭智能助手" icon={<X size={16} />} onClick={() => changeOpen(false, true)} />
    </Space>}>
      {workspace}
    </Drawer>}
    <Modal title={editingAction ? `${editingAction.title} · 需要你的授权` : "需要你的授权"} open={!!editingAction} onCancel={() => { if (!confirmingAction) { setEditingAction(null); setEditingOrder([]) } }} onOk={() => void confirmEditing()} confirmLoading={confirmingAction} okText={editingAction ? CONFIRM_LABELS[editingAction.operation] : "确认"} cancelText="关闭" width={480} centered zIndex={1200} maskClosable={!confirmingAction} keyboard={!confirmingAction} closable={!confirmingAction} cancelButtonProps={{ disabled: confirmingAction }} rootClassName="director-assistant-drawer assistant-edit-approval">
      {editingAction && <><p className="assistant-edit-approval-intro">{editingAction.operation === "video_arrange" ? `将按以下顺序把 ${editingAction.count} 条视频铺到画面主轨：` : editingAction.operation === "subtitle_arrange" ? `将从分集对白生成 ${editingAction.count} 条字幕，放入时间线文字轨：` : editingAction.operation === "audio_subtitle" ? `将从音轨转写的 ${editingAction.transcript?.segment_count ?? 0} 段真实语音生成 ${editingAction.count} 条字幕，放入时间线文字轨：` : editingAction.operation === "hook_cut" ? `将按「${editingAction.strategy_title || "引流剪辑"}」重建画面与配音，保留 ${editingAction.count} 个镜头：` : `将按策略重建画面与配音，保留 ${editingAction.count} 个镜头：`}</p>{isCutOperation(editingAction.operation) && <p className="assistant-edit-approval-evidence">理解依据：{understandingEvidence(editingAction)}</p>}{editingAction.operation === "audio_subtitle" && <p className="assistant-edit-approval-evidence">语音依据：{transcriptEvidence(editingAction)}</p>}<ol className="assistant-edit-approval-list">{orderedEditingItems.map((item, i) => <li key={`${item.asset_id || item.beat_id || item.name}-${i}`}><span title={item.name}>{item.name}</span>{editingAction.operation === "video_arrange" ? <span className="assistant-edit-approval-order"><small>{item.duration?.toFixed(2)} 秒</small><Button size="small" type="text" aria-label="上移" disabled={i === 0 || confirmingAction} icon={<ArrowUp size={12} />} onClick={() => moveEditingItem(i, -1)} /><Button size="small" type="text" aria-label="下移" disabled={i === orderedEditingItems.length - 1 || confirmingAction} icon={<ArrowDown size={12} />} onClick={() => moveEditingItem(i, 1)} /></span> : <span className="assistant-edit-approval-meta"><small>{editingAction.operation === "audio_subtitle" ? `${item.start?.toFixed(2)}–${((item.start ?? 0) + (item.duration ?? 0)).toFixed(2)} 秒` : isCutOperation(editingAction.operation) ? `${item.action === "trim" ? "截取" : "保留"} ${item.duration?.toFixed(2)} 秒` : `${item.duration?.toFixed(2)} 秒`}</small>{item.reason && <small className="assistant-edit-approval-reason" title={item.reason}>{item.reason}</small>}</span>}</li>)}</ol>{editingAction.operation === "hook_cut" && editingAction.principle && <p className="assistant-secondary">策略原则：{editingAction.principle}</p>}{editingAction.operation === "video_arrange" ? <p className="assistant-secondary">从 {(editingAction.append_at || 0).toFixed(2)} 秒处追加，共 {editingAction.total_duration.toFixed(2)} 秒。已有剪辑、文字和独立音频保留。</p> : editingAction.operation === "subtitle_arrange" ? <p className="assistant-secondary">共 {editingAction.total_duration.toFixed(2)} 秒。会替换上次自动生成的字幕，手动文字保留。</p> : editingAction.operation === "audio_subtitle" ? <p className="assistant-secondary">共 {editingAction.total_duration.toFixed(2)} 秒字幕时长。只替换上次自动生成的字幕，手动文字与画面剪辑保持不变。{editingAction.inaudible_count ? `${editingAction.inaudible_count} 段语音落在镜头外，本次未使用。` : ""}{editingAction.skipped_count ? `${editingAction.skipped_count} 处位置已有文字，已跳过。` : ""}</p> : <p className="assistant-secondary">共 {editingAction.total_duration.toFixed(2)} 秒{editingAction.dropped_count ? `，略过 ${editingAction.dropped_count} 个镜头` : ""}{editingAction.trimmed_count ? `，截短 ${editingAction.trimmed_count} 个镜头` : ""}。手动文字保留，执行后可在工具栏一次撤销。</p>}{editingAction.operation === "video_arrange" && (editingAction.skipped_count || 0) > 0 && <p className="assistant-secondary">跳过 {editingAction.skipped_count} 项已铺轨或重复视频。</p>}{editingAction.operation === "video_arrange" && (editingAction.missing_video_count || 0) > 0 && <p className="assistant-secondary">{editingAction.missing_video_count} 个分镜尚无视频，未用分镜图替代。</p>}{isCaptionOperation(editingAction.operation) && !!editingAction.replaced_count && <p className="assistant-secondary">替换 {editingAction.replaced_count} 条上次自动字幕{editingAction.skipped_count ? `，跳过 ${editingAction.skipped_count} 处无对白或占用位置` : ""}。</p>}{actionError && <Alert showIcon type="error" title={actionError} />}</>}
    </Modal>
    {market && <ResourceMarket key={market} open tab={market} resources={catalog?.resources || []} csrfToken={csrfToken} canManagePlatform={!!catalog?.can_manage_platform} selectedVersions={{ skill: selections.skill_id, expert: selections.expert_id }} onClose={() => setMarket(null)} onRefresh={refreshCatalog} onSelect={selectResource} />}
    <KnowledgeManager open={knowledgeOpen} libraries={catalog?.knowledge || []} csrfToken={csrfToken} onClose={() => setKnowledgeOpen(false)} onRefresh={refreshCatalog} />
    <ArtifactDialog artifact={artifact} projectId={detail?.session.project_id || null} csrfToken={csrfToken} onClose={() => setArtifact(null)} onApplied={async () => { if (sid) await loadDetail(sid) }} />
    <Modal title="确认媒体任务" open={!!media} onCancel={() => { if (!confirmingMedia) setMedia(null) }} onOk={confirmMedia} confirmLoading={confirmingMedia} okText="确认并执行" cancelText="取消" zIndex={1200}>
      {media && <><h3>{media.title}</h3><p>目标工程：{media.project_name}</p><p>任务类型：{mediaLabels[media.media_type]} · {media.quantity} 份任务</p><p>生成模型：{media.model_name}</p><p>目标：{media.target_name || media.asset_id || media.episode_id}</p>{media.creation_parameters?.map((p, i) => <p key={i}>{p.label}：{String(p.value ?? "默认")}</p>)}<Collapse items={[{ key: "options", label: "运行参数", children: <pre className="assistant-reference-text">{JSON.stringify(media.options, null, 2)}</pre> }]} /><Alert type="info" showIcon title="确认后提交生成" description="图片、视频与配音按当前供应商配置执行，可能消耗供应商额度。" /></>}
    </Modal>
    <Modal title="继续旧版 AI 任务" open={legacyOpen} onCancel={() => setLegacyOpen(false)} footer={<Button danger onClick={async () => { if (!legacy || !detail?.session.project_id) return; try { await cancelAiOperation(csrfToken, detail.session.project_id, legacy.id); setLegacyOpen(false); setLegacy(null) } catch (e) { message.error(director2ErrorDetail(e, "取消失败")) } }}>取消旧任务</Button>} width={1160} zIndex={1200} destroyOnHidden>
      {legacyOpen && detail?.session.project_id && <Director2AiStudioPane csrfToken={csrfToken} projectId={detail.session.project_id} onNavigate={menu => { setLegacyOpen(false); navigate(director2ProjectPath(detail.session.project_id!, menu)) }} />}
    </Modal>
  </AssistantContext.Provider>
}
