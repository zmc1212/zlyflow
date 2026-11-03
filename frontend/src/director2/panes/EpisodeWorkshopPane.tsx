// 剧集工坊面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/EpisodeWorkshopPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、watch(route.params.episodeId)→useEffect(episodeId)、
// onMounted/onUnmounted→useEffect（生图/视频/合成任务静默轮询：空闲 3 秒，本集视频任务活跃时 1 秒）；
// currentEpisode / selectedBeat 等深响应对象的就地改写收敛为 applyCurrentEpisode / mutateCurrentEpisode /
// updateBeatById（同步维护 ref 供轮询与异步续体读取，等价 Vue 的 .value 语义）；
// reactive(Set) generatingBeatIds / generatingRenderBeatIds 以 ref 镜像 + state 双写保持同步读取语义；
// 路由联动：openEpisodeDetail/handleBackToOverview → navigate(director2ProjectPath(...))；
// 父组件可经 ref 调用 fetchEpisodes()。
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { activeBeatAfterDelete } from "../workshop-batch"
import {
  Alert,
  Button,
  Dropdown,
  Drawer,
  Popover,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Upload,
  message
} from "antd"
import {
  Plus,
  Film,
  Sparkles,
  Check,
  ImageIcon,
  Pencil,
  Layers,
  Copy,
  CircleAlert,
  Info,
  MoreHorizontal,
  ChevronRight,
  ListFilter,
  Settings2
} from "lucide-react"
import {
  episodeStageStates,
  episodeStatusLabel,
  nextEpisodeNumber,
  visibleEpisodes,
  type EpisodeFilter,
  type EpisodeSort
} from "../episode-overview"
import {
  listEpisodes,
  createEpisode,
  updateEpisode,
  deleteEpisode,
  getEpisodeDetail,
  updateEpisodeBeat,
  deleteEpisodeBeats,
  generateBeatTriptych,
  generateBeatH3Prompt,
  generateBeatVideo,
  generateEpisodeVideo,
  retryJob,
  upscaleBeatVideo,
  confirmProjectVideoRefine,
  skipProjectVideoRefine,
  listAssets,
  listJobs,
  listVideoWorkflowModes,
  director2ErrorDetail,
  type Director2Episode,
  type Director2EpisodeDetail,
  type Director2Beat,
  type Director2Asset
} from "../api"
import { director2ProjectPath } from "../paths"
import { WorkshopPromptLive } from "../WorkshopPromptLive"
import {
  applyPromptJobSnapshot,
  applyPromptStreamEvent,
  emptyPromptLiveState,
  streamH3PromptJobEvents,
  type WorkshopPromptLiveState,
} from "../workshop-prompt-stream"
import Director2VideoSettingsPopover from "./Director2VideoSettingsPopover"
import DubbingWorkbench from "./DubbingWorkbench"
import { parseWorkshopTab } from "../dubbing-track"
import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  DIRECTOR2_VIDEO_FALLBACK_FIELDS,
  beatUpscaleDisabledReason,
  buildVideoJobOptions,
  defaultVideoOptionValues,
  episodeVideoRenderMode,
  formatEpisodeVideoSubmitMessage,
  formatSelectedShotSubmitMessage,
  loadProgramPreview,
  loadSavedVideoSettings,
  playbackAspectRatio,
  refineForceWarning,
  sanitizeVideoOptionValues,
  saveProgramPreview,
  saveVideoSettings,
  selectedShotGenerateExtra,
  shotVideoReadyCount,
  smartClarifyConfirmText,
  timelineVideoWorkflows,
  videoResolutionQuality,
  visibleVideoOptionFields,
  withVideoPromptMode,
  type Director2WorkflowMode
} from "../director2-video-settings"
import { projectVideoPreferences, projectVideoResolution } from "../project-video-resolution"
import { useMediaPreview } from "../media-preview"
import { type MediaAspectSize } from "../../lib/utils"
import { firstCharacterLookImageUrl } from "./assets/shared"
import { renderH3PromptHtml } from "../h3-prompt-display"
import {
  beatDurationSec,
  sumBeatDurationSec
} from "../workshop-beat-duration"
import { workshopBeatHasSplitTakes, workshopBeatLabel } from "../workshop-beat-label"
import {
  WORKSHOP_H3_TRIPTYCH_GATE,
  beatsMissingH3Prompt,
  workshopH3GenerateLabel,
  workshopH3PromptGate,
} from "../workshop-h3-gate"
import { withTriptychPanels } from "../workshop-r2v-refs"
import { shouldShowWorkshopPromptLive, workshopFailedLiveText, workshopH3StatusLabel } from "../workshop-h3-status"
import {
  programPreviewPrompts,
  sameProgramPreviewPrompts,
  type ProgramPreviewPrompts,
} from "../workshop-program-prompt"
import { workshopPromptAsideLine } from "../workshop-vision-status"
import {
  WORKSHOP_IDLE_POLL_MS,
  WORKSHOP_VIDEO_POLL_MS,
  hasActiveWorkshopVideoProgress,
  mapWorkshopVideoProgress,
  mapWorkshopVideoFailures,
  type WorkshopEpisodeVideoProgress,
  type WorkshopShotVideoProgress
} from "../workshop-video-progress"
import WorkshopWorkspace from "./WorkshopWorkspace"
import WorkshopOverview, { workshopEpisodeSummary } from "./WorkshopOverview"
import WorkshopHistory from "./WorkshopHistory"
import WorkshopPlayer from "./WorkshopPlayer"
import "./workshop-focus.css"
import "./episode-workshop.css"
import "./episode-overview.css"

interface EpisodeWorkshopPaneProps {
  csrfToken: string
  projectId: string
  episodeId?: string | null
  onDetailModeChange?: (inDetail: boolean) => void
  projectName?: string
  projectControls?: ReactNode
}

export type EpisodeWorkshopPaneHandle = {
  fetchEpisodes: () => Promise<void> | void
}

type H3RefImage = {
  id: string
  url: string
  name: string
  category?: string
}

// 分集表单只保存可编辑字段，原有镜头数由编辑快照保留。
type EpisodeFormState = {
  episode_num: number
  title: string
  status: string
  script_text: string
}

const episodeStatusOptions = [
  { value: "draft", label: "草稿" },
  { value: "script_ready", label: "脚本就绪" },
  { value: "sketching", label: "出图中" },
  { value: "sketched", label: "分镜完成" },
]

function episodeStageItems(status: string) {
  return episodeStageStates(status).map((state, index) => ({
    title: ["草稿", "脚本", "出图", "分镜"][index],
    status: state,
    icon: <span className={`series-stage-icon is-${state}${status === "sketched" && index === 3 ? " is-complete" : ""}`}>
      {state === "finish" ? <Check size={12} strokeWidth={2.6} /> : state === "process" ? <span className="series-stage-current" /> : null}
    </span>,
  }))
}

type LookOption = {
  value: string
  label: string
  imageUrl: string
  description: string
}

// 原版脚本还会读写 beat.time_of_day（api.ts 的 Director2Beat 快照暂未收录），按原版行为扩展该字段
type WorkshopBeat = Director2Beat & { time_of_day?: string }

type GenerationStage = "sketch" | "render" | "triptych"

const TERMINAL_JOB_STATUSES = new Set(["completed", "succeeded", "failed", "cancelled", "interrupted"])
const SUCCEEDED_JOB_STATUSES = new Set(["completed", "succeeded"])

const EpisodeWorkshopPane = forwardRef<EpisodeWorkshopPaneHandle, EpisodeWorkshopPaneProps>(
  function EpisodeWorkshopPane({ csrfToken, projectId, episodeId, onDetailModeChange, projectName, projectControls }, ref) {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const { openMediaPreview } = useMediaPreview()

    // 剧集列表与当前选中的分集
    const [episodes, setEpisodes] = useState<Director2Episode[]>([])
    const [toolPanel, setToolPanel] = useState<"details" | "script" | "dubbing" | null>(null)
    const [historyBeat, setHistoryBeat] = useState<Director2Beat | null>(null)
    const [headerSaveState, setHeaderSaveState] = useState("已保存")
    const headerSaveRef = useRef<() => void>(() => {})
    const beforeVideoSubmitRef = useRef<((ids?: string[]) => Promise<void>) | null>(null)
    const [previewRequest, setPreviewRequest] = useState(0)
    const [overviewPreview, setOverviewPreview] = useState<Director2EpisodeDetail | null>(null)
    const [overviewPreviewId, setOverviewPreviewId] = useState("")
    const [loading, setLoading] = useState(true)
    const [episodeListError, setEpisodeListError] = useState("")
    const [episodeSearch, setEpisodeSearch] = useState("")
    const [episodeFilter, setEpisodeFilter] = useState<EpisodeFilter>("all")
    const [episodeSort, setEpisodeSort] = useState<EpisodeSort>("number_asc")
    const [currentEpisodeId, setCurrentEpisodeId] = useState<string | null>(episodeId ?? null)
    const [currentEpisode, setCurrentEpisode] = useState<Director2EpisodeDetail | null>(null)
    const [regeneratingScript, setRegeneratingScript] = useState(false)
    const [generatingEpisodeVideo, setGeneratingEpisodeVideo] = useState(false)

    // 镜头工作台状态
    const [selectedBeatId, setSelectedBeatId] = useState<string | null>(null)
    const [checkedBeatIds, setCheckedBeatIds] = useState<Set<string>>(new Set())
    const [deletingBeats, setDeletingBeats] = useState(false)
    const deletingBeatsRef = useRef(false)

    // 资产关联与选项
    const [projectAssets, setProjectAssets] = useState<Director2Asset[]>([])
    const [projectAssetsState, setProjectAssetsState] = useState<"loading" | "ready" | "error">("loading")
    const projectCharacters = useMemo(() => projectAssets.filter((a) => a.kind === "character"), [projectAssets])
    const projectScenes = useMemo(() => projectAssets.filter((a) => a.kind === "scene"), [projectAssets])
    const projectProps = useMemo(() => projectAssets.filter((a) => a.kind === "prop"), [projectAssets])

    // 各种生成 Loading 状态
    const [generatingBeatIds, setGeneratingBeatIds] = useState<Set<string>>(new Set())
    const [generatingRenderBeatIds, setGeneratingRenderBeatIds] = useState<Set<string>>(new Set())
    const [generatingTriptychBeatIds, setGeneratingTriptychBeatIds] = useState<Set<string>>(new Set())
    const [generatingVideo, setGeneratingVideo] = useState(false)
    const [retryingVideoJob, setRetryingVideoJob] = useState<string | null>(null)
    const [videoFailures, setVideoFailures] = useState<Record<string, WorkshopShotVideoProgress & { error: string }>>({})
    const [upscalingBeatId, setUpscalingBeatId] = useState<string | null>(null)
    const [refineAction, setRefineAction] = useState<{ jobId: string; action: "confirm" | "skip" } | null>(null)
    const [beatVideoProgress, setBeatVideoProgress] = useState<Record<string, WorkshopShotVideoProgress>>({})
    const [episodeVideoProgress, setEpisodeVideoProgress] = useState<WorkshopEpisodeVideoProgress | null>(null)
    const [programPromptPreview, setProgramPromptPreview] = useState<ProgramPreviewPrompts | null>(null)
    const [h3RefImages, setH3RefImages] = useState<H3RefImage[]>([])
    const [h3ImagesExpanded, setH3ImagesExpanded] = useState(false)
    const [generatingH3Prompt, setGeneratingH3Prompt] = useState(false)
    const [h3LiveBeatId, setH3LiveBeatId] = useState("")
    const [h3PromptEditing, setH3PromptEditing] = useState(false)
    const [h3PromptDraft, setH3PromptDraft] = useState("")
    const [savingH3Prompt, setSavingH3Prompt] = useState(false)
    const [h3Live, setH3Live] = useState<WorkshopPromptLiveState>(() => emptyPromptLiveState())
    const [h3JobMeta, setH3JobMeta] = useState<{
      vision_status?: string | null
      vision_model?: string | null
      vision_image_count?: number | string | null
      author_errors?: string[] | null
    } | null>(null)

    // 与 Vue 实例级可变量对应的同步 ref（供轮询与异步续体读取最新值，等价 .value 语义）
    const currentEpisodeIdRef = useRef<string | null>(episodeId ?? null)
    const currentEpisodeRef = useRef<Director2EpisodeDetail | null>(null)
    const selectedBeatIdRef = useRef<string | null>(null)
    const generatingBeatIdsRef = useRef<Set<string>>(new Set())
    const generatingRenderBeatIdsRef = useRef<Set<string>>(new Set())
    const generatingTriptychBeatIdsRef = useRef<Set<string>>(new Set())
    const beatVideoProgressRef = useRef<Record<string, WorkshopShotVideoProgress>>({})
    const episodeVideoProgressRef = useRef<WorkshopEpisodeVideoProgress | null>(null)
    const imageJobPollDelayRef = useRef(WORKSHOP_IDLE_POLL_MS)
    const trackedBatchJobsRef = useRef<Map<GenerationStage, Set<string>>>(new Map())
    const trackedVideoJobsRef = useRef<Set<string>>(new Set())
    const trackedH3PromptJobIdsRef = useRef<string[]>([])
    const h3MaterialBeatIdRef = useRef<string | null>(null)
    const imageJobPollTimerRef = useRef<number | null>(null)

    // 视频设置参数（来自 /api/modes 注册表，按项目记住）
    const [videoWorkflow, setVideoWorkflow] = useState(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW)
    const [videoWorkflows, setVideoWorkflows] = useState<Director2WorkflowMode[]>([])
    const [videoOptionFields, setVideoOptionFields] = useState(DIRECTOR2_VIDEO_FALLBACK_FIELDS)
    const [videoOptions, setVideoOptions] = useState(() => defaultVideoOptionValues(DIRECTOR2_VIDEO_FALLBACK_FIELDS))
    const [confirmedVideoResolution, setConfirmedVideoResolution] = useState<{ value: string; label: string } | null>(null)
    const [programPreview, setProgramPreview] = useState(() => loadProgramPreview(projectId))

    // 新增/编辑分集弹窗表单
    const [modalVisible, setModalVisible] = useState(false)
    const [editingEpisode, setEditingEpisode] = useState<Director2Episode | null>(null)
    const isEdit = Boolean(editingEpisode)
    const [submitting, setSubmitting] = useState(false)
    const [episodeFormError, setEpisodeFormError] = useState("")
    const [episodeForm] = Form.useForm<EpisodeFormState>()
    const formStatus = Form.useWatch("status", episodeForm) || "draft"
    const submitEpisodeRef = useRef(false)
    const [deletingEpisode, setDeletingEpisode] = useState<Director2Episode | null>(null)
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [deleting, setDeleting] = useState(false)
    const [deleteError, setDeleteError] = useState("")
    const deleteEpisodeRef = useRef(false)
    const deleteCancelRef = useRef<HTMLButtonElement>(null)
    const displayedEpisodes = useMemo(() => visibleEpisodes(episodes, episodeSearch, episodeFilter, episodeSort), [episodes, episodeSearch, episodeFilter, episodeSort])

    // —— 同步 ref 双写辅助 ——
    function applyCurrentEpisode(next: Director2EpisodeDetail | null) {
      currentEpisodeRef.current = next
      setCurrentEpisode(next)
    }

    function applySelectedBeatId(id: string) {
      selectedBeatIdRef.current = id
      setSelectedBeatId(id)
    }

    function applyVideoSettings(workflowId: string, mode: Director2WorkflowMode | undefined, incoming?: Record<string, string> | null) {
      const fields = visibleVideoOptionFields(mode)
      const next = sanitizeVideoOptionValues(fields, incoming)
      setVideoWorkflow(workflowId)
      setVideoOptionFields(fields)
      setVideoOptions(next)
      saveVideoSettings(projectId, { workflow: workflowId, ...next })
    }

    function handleVideoWorkflowChange(nextId: string) {
      const mode = videoWorkflows.find((item) => item.id === nextId)
      const lockedQuality = videoResolutionQuality(confirmedVideoResolution?.value)
      const lockedRefine = videoResolutionQuality(confirmedVideoResolution?.value, true)
      applyVideoSettings(nextId, mode, {
        ...videoOptions,
        ...(lockedQuality ? { quality: lockedQuality } : {}),
        ...(lockedRefine ? { refine_quality: lockedRefine } : {}),
      })
      if (episodeVideoRenderMode(mode) !== "shot") setCheckedBeatIds(new Set())
    }

    function handleVideoOptionChange(name: string, value: string) {
      const next = { ...videoOptions, [name]: value }
      setVideoOptions(next)
      saveVideoSettings(projectId, { workflow: videoWorkflow, ...next })
    }

    function handleProgramPreviewChange(enabled: boolean) {
      setProgramPreview(enabled)
      saveProgramPreview(projectId, enabled)
    }

    function setStageGeneratingSet(stage: GenerationStage, next: Set<string>) {
      if (stage === "sketch") {
        generatingBeatIdsRef.current = next
        setGeneratingBeatIds(next)
      } else if (stage === "render") {
        generatingRenderBeatIdsRef.current = next
        setGeneratingRenderBeatIds(next)
      } else {
        generatingTriptychBeatIdsRef.current = next
        setGeneratingTriptychBeatIds(next)
      }
    }

    function stageSetHas(stage: GenerationStage, beatId: string): boolean {
      if (stage === "sketch") return generatingBeatIdsRef.current.has(beatId)
      if (stage === "render") return generatingRenderBeatIdsRef.current.has(beatId)
      return generatingTriptychBeatIdsRef.current.has(beatId)
    }

    function addToStageSet(stage: GenerationStage, beatId: string) {
      const current = stage === "sketch"
        ? generatingBeatIdsRef.current
        : stage === "render"
          ? generatingRenderBeatIdsRef.current
          : generatingTriptychBeatIdsRef.current
      if (current.has(beatId)) return
      const next = new Set(current)
      next.add(beatId)
      setStageGeneratingSet(stage, next)
    }

    function deleteFromStageSet(stage: GenerationStage, beatId: string) {
      const current = stage === "sketch"
        ? generatingBeatIdsRef.current
        : stage === "render"
          ? generatingRenderBeatIdsRef.current
          : generatingTriptychBeatIdsRef.current
      if (!current.has(beatId)) return
      const next = new Set(current)
      next.delete(beatId)
      setStageGeneratingSet(stage, next)
    }

    function rememberVideoJobIds(ids: Array<string | undefined | null>) {
      const next = new Set(trackedVideoJobsRef.current)
      for (const id of ids) {
        if (id) next.add(id)
      }
      trackedVideoJobsRef.current = next
    }

    function mutateCurrentEpisode(updater: (ep: Director2EpisodeDetail) => Director2EpisodeDetail) {
      const prev = currentEpisodeRef.current
      if (!prev) return
      const next = updater(prev)
      applyCurrentEpisode(next)
    }

    // 等价原版 selectedBeat computed 的 ref 版本（供异步续体读取）
    function resolveSelectedBeat(ep: Director2EpisodeDetail | null): WorkshopBeat | null {
      const beats = ep?.beats || []
      if (!beats.length) return null
      const id = selectedBeatIdRef.current
      return (id ? beats.find((b) => b.id === id) : undefined) || beats[0]
    }

    function updateBeatById(beatId: string, patch: Partial<WorkshopBeat>) {
      mutateCurrentEpisode((ep) => ({
        ...ep,
        beats: (ep.beats || []).map((b) => (b.id === beatId ? { ...b, ...patch } : b)),
      }))
    }

    // 计算属性
    const selectedBeat = useMemo<WorkshopBeat | null>(() => {
      if (!currentEpisode?.beats?.length) return null
      return currentEpisode.beats.find((b) => b.id === selectedBeatId) || currentEpisode.beats[0]
    }, [currentEpisode, selectedBeatId])
    useEffect(() => {
      setH3PromptEditing(false)
      setH3PromptDraft(String(selectedBeat?.h3_prompt || ""))
      setH3Live((prev) => (prev.working ? prev : emptyPromptLiveState()))
      setH3JobMeta(null)
    }, [selectedBeat?.id])

    useEffect(() => {
      if (!h3PromptEditing) {
        setH3PromptDraft(String(selectedBeat?.h3_prompt || ""))
      }
    }, [selectedBeat?.h3_prompt, h3PromptEditing])

    useEffect(() => {
      const jobId = h3Live.jobId
      if (!generatingH3Prompt || !jobId || jobId === "pending") return undefined
      const controller = new AbortController()
      let active = true
      void streamH3PromptJobEvents(projectId, jobId, (event) => {
        if (!active) return
        setH3Live((prev) => (prev.jobId === jobId ? applyPromptStreamEvent(prev, event) : prev))
      }, {
        signal: controller.signal,
        shouldContinue: () => active && trackedH3PromptJobIdsRef.current.includes(jobId),
      })
      return () => {
        active = false
        controller.abort()
      }
    }, [generatingH3Prompt, h3Live.jobId, projectId])

    const h3RefImagesVisible = h3ImagesExpanded ? h3RefImages : h3RefImages.slice(0, 3)
    const savedH3Prompt = String(selectedBeat?.h3_prompt || "")
    const programPrompt = String(programPromptPreview?.prompts?.[selectedBeat?.id || ""] || "")
    const h3PromptDirty = h3PromptDraft !== savedH3Prompt
    const selectedH3Working = generatingH3Prompt && h3LiveBeatId === selectedBeat?.id
    const h3Failed = Boolean(h3Live.failed) && !generatingH3Prompt && h3LiveBeatId === selectedBeat?.id
    const showH3Live = shouldShowWorkshopPromptLive({
      generating: selectedH3Working,
      failed: h3Failed,
      editing: h3PromptEditing,
      liveText: h3Live.text,
    })
    const h3VisionLine = workshopPromptAsideLine(h3JobMeta || selectedBeat, { failed: h3Failed })
    const showH3ProgramPreview = Boolean(
      programPrompt && !savedH3Prompt.trim() && !showH3Live && !h3PromptEditing,
    )
    const showH3Editor = Boolean(
      h3PromptEditing || (!savedH3Prompt.trim() && !showH3Live && !showH3ProgramPreview),
    )
    const h3StatusLabel = showH3ProgramPreview
      ? "程序装箱预览"
      : workshopH3StatusLabel({
        generating: selectedH3Working,
        failed: h3Failed,
        editing: h3PromptEditing,
        dirty: h3PromptDirty,
        savedPrompt: savedH3Prompt,
        source: selectedBeat?.h3_prompt_source,
      })
    const h3PromptCopyText = showH3Live
      ? h3Live.text
      : showH3Editor ? (h3PromptDraft || programPrompt) : (savedH3Prompt || programPrompt)
    const selectedTriptychGenerating = Boolean(selectedBeat?.id && generatingTriptychBeatIds.has(selectedBeat.id))
    const h3GenerateBusy = generatingH3Prompt || selectedTriptychGenerating
    const h3GenerateLabel = workshopH3GenerateLabel({
      generating: selectedH3Working,
      hasPrompt: Boolean(savedH3Prompt.trim()),
    })

    // 镜头成片放大预览：携带整集已出片镜头的播放序列，预览弹窗内可上一个 / 下一个切换镜头

    const selectedVideoWorkflow = useMemo(
      () => videoWorkflows.find((item) => item.id === videoWorkflow) || videoWorkflows[0],
      [videoWorkflow, videoWorkflows],
    )
    const videoRenderMode = episodeVideoRenderMode(selectedVideoWorkflow)
    const videoReadyCount = shotVideoReadyCount(currentEpisode?.beats)
    const episodeVideoJobActive = Boolean(episodeVideoProgress)
    const episodeDurationSec = useMemo(
      () => sumBeatDurationSec(currentEpisode?.beats || []),
      [currentEpisode],
    )
    const selectedBeatSplit = workshopBeatHasSplitTakes(selectedBeat, currentEpisode?.beats)

    function getCharacterLookOptions(character: Director2Asset): LookOption[] {
      const looks = (character?.extra?.identities as Record<string, any>[] | undefined) || []
      return looks
        .filter((look) => look?.id && look?.image_url)
        .map((look) => ({
          value: look.id as string,
          label: (look.name || look.description || look.id) as string,
          imageUrl: look.image_url as string,
          description: (look.appearance_details || look.description || "") as string,
        }))
    }

    function getBeatCharacterLookId(character: Director2Asset): string {
      const mapped = selectedBeat?.character_look_ids?.[character.id]
      if (mapped) return mapped
      const legacy = selectedBeat?.character_look_id
      return getCharacterLookOptions(character).some((look) => look.value === legacy) ? legacy ?? "" : ""
    }

    function getSelectedCharacterLook(character: Director2Asset): LookOption | null {
      const lookId = getBeatCharacterLookId(character)
      return getCharacterLookOptions(character).find((look) => look.value === lookId) || null
    }

    function getCharacterImage(character: Director2Asset | null | undefined): string {
      if (!character) return ""
      const look = getSelectedCharacterLook(character)
      if (look?.imageUrl) return look.imageUrl
      return firstCharacterLookImageUrl(character) || String(character.extra?.avatar_url || character.image_url || "").trim()
    }

    function getSceneImage(scene: Director2Asset | null | undefined): string {
      if (!scene) return ""
      return String(scene.extra?.master_url || scene.image_url || scene.extra?.reference_url || "").trim()
    }

    function getPropImage(prop: Director2Asset | null | undefined): string {
      if (!prop) return ""
      return String(prop.image_url || prop.extra?.reference_url || prop.extra?.turnaround_url || prop.extra?.master_url || "").trim()
    }

    function getBeatSceneAsset(beat: WorkshopBeat | null | undefined): Director2Asset | null {
      if (!beat) return null
      if (beat.scene_id) {
        const found = projectScenes.find((item) => item.id === beat.scene_id)
        if (found) return found
      }
      if (beat.scene) {
        const found = projectScenes.find((item) => item.name === beat.scene)
        if (found) return found
      }
      return projectScenes[0] || null
    }

    function collectH3RefImages(beat: WorkshopBeat | null | undefined): H3RefImage[] {
      if (!beat) return []
      const beatChars = (beat.character_ids || [])
        .map((id) => projectCharacters.find((item) => item.id === id))
        .filter((item): item is Director2Asset => Boolean(item))
      let charImgs = (beatChars.length ? beatChars : projectCharacters)
        .map((item) => ({ id: item.id, url: getCharacterImage(item), name: item.name, category: "character" }))
        .filter((item) => item.url)
      if (!charImgs.length && projectCharacters.length) {
        charImgs = projectCharacters
          .map((item) => ({ id: item.id, url: getCharacterImage(item), name: item.name, category: "character" }))
          .filter((item) => item.url)
          .slice(0, 2)
      } else if (!beatChars.length) {
        charImgs = charImgs.slice(0, 2)
      }

      const sceneAsset = getBeatSceneAsset(beat)
      const sceneUrl = getSceneImage(sceneAsset)
      const sceneImgs = sceneUrl && sceneAsset
        ? [{ id: sceneAsset.id, url: sceneUrl, name: sceneAsset.name || "场景", category: "scene" }]
        : []

      const beatProps = (beat.prop_ids || [])
        .map((id) => projectProps.find((item) => item.id === id))
        .filter((item): item is Director2Asset => Boolean(item))
      for (const name of beat.props || []) {
        if (!beatProps.some((item) => item.name === name)) {
          const found = projectProps.find((item) => item.name === name)
          if (found) beatProps.push(found)
        }
      }
      const propImgs = beatProps
        .map((item) => ({ id: item.id, url: getPropImage(item), name: item.name, category: "prop" }))
        .filter((item) => item.url)

      let source = [...charImgs, ...sceneImgs, ...propImgs]
      if (!source.length) {
        source = projectAssets
          .map((item) => ({
            id: item.id,
            url: String(item.image_url || item.extra?.master_url || item.extra?.reference_url || item.extra?.avatar_url || "").trim(),
            name: item.name,
            category: item.kind,
          }))
          .filter((item) => item.url)
      }
      return withTriptychPanels(beat, source)
    }

    function handleSelectExistingImages() {
      const beat = resolveSelectedBeat(currentEpisodeRef.current)
      const imgs = collectH3RefImages(beat)
      if (imgs.length) {
        setH3RefImages(imgs)
        message.success(`已选入 ${imgs.length} 张参考图片（包含出场角色、场景与道具）`)
      } else {
        message.info("资产库暂无可用图片，请先在资产库上传或生成角色/场景/道具图片")
      }
    }

    function removeH3RefImage(idx: number) {
      setH3RefImages((prev) => prev.filter((_, index) => index !== idx))
    }

    function handleUploadH3Image(file: File): boolean {
      if (h3RefImages.length >= 9) {
        message.warning("最多 9 张参考图")
        return false
      }
      const reader = new FileReader()
      reader.onload = (e) => {
        const url = String(e.target?.result || "")
        if (!url) return
        setH3RefImages((prev) => {
          if (prev.length >= 9) return prev
          return [...prev, { id: `upload-${Date.now()}`, url, name: file.name, category: "upload" }]
        })
        message.success(`已添加参考图片：${file.name}`)
      }
      reader.readAsDataURL(file)
      return false
    }

    function copyH3Prompt() {
      const text = String(h3PromptCopyText || "")
      if (!text.trim()) return
      navigator.clipboard.writeText(text)
        .then(() => message.success("H3 提示词已复制到剪贴板"))
        .catch(() => message.error("复制失败"))
    }

    async function saveH3Prompt() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat || savingH3Prompt) return
      setSavingH3Prompt(true)
      try {
        const nextPrompt = h3PromptDraft
        await updateEpisodeBeat(csrfToken, projectId, ep.id, beat.id, {
          h3_prompt: nextPrompt,
          h3_prompt_source: nextPrompt.trim() ? "manual" : "",
        })
        updateBeatById(beat.id, {
          h3_prompt: nextPrompt,
          h3_prompt_source: nextPrompt.trim() ? "manual" : "",
        })
        setH3PromptEditing(false)
        message.success("H3 提示词已保存，出片将按原文使用")
      } catch (err) {
        message.error(director2ErrorDetail(err, "保存 H3 提示词失败"))
      } finally {
        setSavingH3Prompt(false)
      }
    }

    function cancelH3PromptEdit() {
      setH3PromptDraft(String(resolveSelectedBeat(currentEpisodeRef.current)?.h3_prompt || ""))
      setH3PromptEditing(false)
    }

    function requestGenerateH3Prompt(extra: Record<string, unknown> = {}) {
      const beat = resolveSelectedBeat(currentEpisodeRef.current)
      const gate = workshopH3PromptGate(beat, {
        triptychGenerating: Boolean(beat?.id && generatingTriptychBeatIdsRef.current.has(beat.id)),
      })
      if (gate === "need_cast") {
        message.warning(WORKSHOP_H3_TRIPTYCH_GATE.needCast)
        return
      }
      if (gate === "triptych_running") {
        message.warning(WORKSHOP_H3_TRIPTYCH_GATE.triptychRunning)
        return
      }
      if (gate === "need_triptych") {
        Modal.confirm({
          title: WORKSHOP_H3_TRIPTYCH_GATE.confirmTitle,
          content: WORKSHOP_H3_TRIPTYCH_GATE.confirmContent,
          okText: WORKSHOP_H3_TRIPTYCH_GATE.confirmOk,
          cancelText: "取消",
          onOk: () => generateSingleBeatTriptych({ fromPromptGate: true }),
        })
        return
      }
      const saved = String(beat?.h3_prompt || "").trim()
      const dirty = h3PromptDraft !== String(beat?.h3_prompt || "")
      if (extra.merge_as_one) {
        Modal.confirm({
          title: "合并为一条生成？",
          content: saved
            ? "将同一剧情镜下的出片镜合并回一条，再生成一份 H3 提示词。系统生成会覆盖已保存或正在编辑的提示词。"
            : "将同一剧情镜下的出片镜合并回一条，再生成一份 H3 提示词。适合仍想赌一镜到底的情况。",
          okText: "合并生成",
          cancelText: "取消",
          onOk: () => handleGenerateH3Prompt(extra),
        })
        return
      }
      if (saved || (h3PromptEditing && dirty && h3PromptDraft.trim())) {
        Modal.confirm({
          title: "覆盖当前 H3 提示词？",
          content: "系统生成会覆盖已保存或正在编辑的提示词。请确认本镜三联画面无误后再生成。",
          okText: "覆盖生成",
          cancelText: "取消",
          onOk: () => handleGenerateH3Prompt(extra),
        })
        return
      }
      void handleGenerateH3Prompt(extra)
    }

    function requestMergeH3Prompt() {
      requestGenerateH3Prompt({ merge_as_one: true })
    }

    async function handleGenerateH3Prompt(extra: Record<string, unknown> = {}) {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat || generatingH3Prompt) return
      setH3LiveBeatId(beat.id)
      setGeneratingH3Prompt(true)
      setH3PromptEditing(false)
      setH3JobMeta(null)
      setH3Live(emptyPromptLiveState("pending"))
      try {
        const res = await generateBeatH3Prompt(csrfToken, projectId, ep.id, beat.id, {
          ref_images: h3RefImages.map((img, index) => ({
            index: index + 1,
            name: img.name,
            category: img.category,
            url: img.url,
          })),
          ...extra,
        })
        if (res?.job_id || res?.job_ids?.length) {
          const jobIds = (res.job_ids || []).filter(Boolean)
          trackedH3PromptJobIdsRef.current = jobIds.length ? jobIds : (res.job_id ? [res.job_id] : [])
          const liveJobId = String(res.job_id || trackedH3PromptJobIdsRef.current[0] || "")
          if (liveJobId) setH3Live(emptyPromptLiveState(liveJobId))
          if (res.split || res.merged) {
            await loadEpisodeDetail(ep.id)
            if (res.beat_id) applySelectedBeatId(res.beat_id)
          }
          message.success({
            content: res.split
              ? `已按控制拆成 ${res.beat_ids?.length || jobIds.length} 条出片镜并开始生成 H3 提示词`
              : res.merged
                ? `已合并为一条并开始生成：${res.job_id}`
                : `已提交 H3 提示词生成任务：${res.job_id}，可在「全部任务」查看进度`,
            key: "h3PromptGen",
            duration: 4,
          })
          await pollImageJobs()
        } else if (res?.prompt) {
          updateBeatById(beat.id, { h3_prompt: res.prompt, h3_prompt_source: "generated" })
          setH3PromptDraft(String(res.prompt))
          setH3PromptEditing(false)
          message.success({ content: "已生成电影级 H3 提示词", key: "h3PromptGen" })
          setGeneratingH3Prompt(false)
          setH3Live((prev) => ({ ...prev, working: false, jobId: "" }))
        }
      } catch (err) {
        message.error({ content: `大模型生成失败: ${director2ErrorDetail(err, "生成失败")}`, key: "h3PromptGen" })
        setGeneratingH3Prompt(false)
        setH3Live((prev) => ({
          ...prev,
          working: false,
          failed: true,
          jobId: prev.jobId === "pending" ? "" : prev.jobId,
          message: director2ErrorDetail(err, "生成失败"),
        }))
      }
    }

    // ---------------- 剧集列表与详情流转 ----------------
    async function fetchEpisodes() {
      setLoading(true)
      setEpisodeListError("")
      try {
        const res = await listEpisodes(projectId)
        const list = res || []
        setEpisodes(list)
        const epId = currentEpisodeIdRef.current
        if (!epId) return
        if (list.length && !list.some((item) => item.id === epId)) {
          handleBackToOverview()
          return
        }
        await loadEpisodeDetail(epId)
      } catch (error) {
        setEpisodeListError(director2ErrorDetail(error, "加载剧集列表失败，请稍后重试。"))
      } finally {
        setLoading(false)
      }
    }

    async function loadAssets() {
      setProjectAssetsState("loading")
      try {
        const res = await listAssets(projectId)
        setProjectAssets(res || [])
        setProjectAssetsState("ready")
      } catch (err) {
        setProjectAssetsState("error")
        console.error("加载资产列表失败", err)
      }
    }

    function openEpisodeDetail(epId: string) {
      navigate(director2ProjectPath(projectId, "workshop", epId))
    }

    function handleBackToOverview() {
      navigate(director2ProjectPath(projectId, "workshop"))
    }

    async function loadEpisodeDetail(epId: string) {
      try {
        const res = await getEpisodeDetail(projectId, epId)
        applyCurrentEpisode(res)
        if (res.beats?.length) {
          const currentBeatId = selectedBeatIdRef.current
          if (!currentBeatId || !res.beats.some((b) => b.id === currentBeatId)) {
            applySelectedBeatId(res.beats[0].id)
          }
        }
      } catch {
        message.error("加载分集详细信息失败")
      }
    }

    async function refreshCurrentEpisode() {
      const epId = currentEpisodeIdRef.current
      if (epId) {
        await loadEpisodeDetail(epId)
        message.success("分集分镜数据已刷新")
      }
    }

    function selectBeat(beat: WorkshopBeat) {
      applySelectedBeatId(beat.id)
    }

    function toggleCheckedBeat(beat: WorkshopBeat, checked: boolean) {
      setCheckedBeatIds((prev) => {
        const next = new Set(prev)
        if (checked) next.add(beat.id)
        else next.delete(beat.id)
        return next
      })
      applySelectedBeatId(beat.id)
    }

    function toggleCheckAllBeats(checked: boolean) {
      const beats = currentEpisodeRef.current?.beats || []
      setCheckedBeatIds(checked ? new Set(beats.map((beat) => beat.id)) : new Set())
    }

    // ---------------- GRS 分镜生图调用 ----------------
    function applyBeatGenerationResult(episodeId: string, res: Record<string, any>, stage: GenerationStage) {
      if (!res?.image_url || currentEpisodeRef.current?.id !== episodeId) return
      mutateCurrentEpisode((ep) => ({
        ...ep,
        beats: (ep.beats || []).map((item) => {
          if (item.id !== res.beat_id) return item
          if (stage === "sketch") {
            return {
              ...item,
              sketch_url: res.image_url,
              sketch_prompt: res.beat?.sketch_prompt || item.sketch_prompt,
              sketch_job_id: res.job_id,
              status: res.beat?.status || "sketched",
            }
          }
          if (stage === "triptych") {
            return {
              ...item,
              triptych_url: res.image_url || res.beat?.triptych_url || item.triptych_url,
              triptych_panels: res.beat?.triptych_panels || item.triptych_panels,
              triptych_job_id: res.job_id,
              triptych_status: res.beat?.triptych_status || "succeeded",
            }
          }
          return {
            ...item,
            render_url: res.image_url,
            render_prompt: res.beat?.render_prompt || item.render_prompt,
            render_job_id: res.job_id,
            render_status: res.beat?.render_status || "succeeded",
          }
        }),
      }))
    }

    async function generateSingleBeatTriptych(options: { fromPromptGate?: boolean } = {}) {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat) return
      if (!(beat.character_ids || []).length || !(beat.scene_id || beat.scene)) {
        message.warning(WORKSHOP_H3_TRIPTYCH_GATE.needCast)
        return
      }
      const episodeId = ep.id
      if (stageSetHas("triptych", beat.id)) return
      addToStageSet("triptych", beat.id)
      let enqueued = false
      try {
        const res = await generateBeatTriptych(csrfToken, projectId, episodeId, beat.id, { force: true })
        if (res?.job_id) {
          enqueued = true
          updateBeatById(beat.id, {
            triptych_job_id: String(res.job_id),
            triptych_status: String(res.status || "queued"),
          })
          message.success(options.fromPromptGate
            ? WORKSHOP_H3_TRIPTYCH_GATE.queued
            : `Beat ${beat.sequence} 三联关键帧已入队`)
        }
        applyBeatGenerationResult(episodeId, res, "triptych")
      } catch (err) {
        message.error(director2ErrorDetail(err, WORKSHOP_H3_TRIPTYCH_GATE.failed))
      } finally {
        if (!enqueued) deleteFromStageSet("triptych", beat.id)
      }
    }

    async function pollImageJobs() {
      if (!currentEpisodeRef.current) {
        imageJobPollDelayRef.current = WORKSHOP_IDLE_POLL_MS
        return
      }
      try {
        const previouslyActive = new Set([
          ...generatingBeatIdsRef.current,
          ...generatingRenderBeatIdsRef.current,
          ...generatingTriptychBeatIdsRef.current,
        ])
        const previouslyTriptych = new Set(generatingTriptychBeatIdsRef.current)
        const previouslyActiveVideoBeats = new Set(Object.keys(beatVideoProgressRef.current))
        const previouslyEpisodeVideoActive = Boolean(episodeVideoProgressRef.current)
        const jobs = await listJobs(projectId)
        const epId = currentEpisodeRef.current?.id
        if (!epId) return
        const episodeJobs = jobs.filter((job) => job.payload?.episode_id === epId)
        const activeStatuses = new Set(["queued", "preparing", "running", "storing"])
        const nextSketchIds = new Set<string>()
        const nextRenderIds = new Set<string>()
        const nextTriptychIds = new Set<string>()
        episodeJobs.forEach((job) => {
          const stage = job.payload?.target_type === "beat_sketch"
            ? "sketch"
            : job.payload?.target_type === "beat_render"
              ? "render"
              : job.payload?.target_type === "beat_triptych"
                ? "triptych"
                : ""
          if (stage && activeStatuses.has(job.status)) {
            if (stage === "sketch") nextSketchIds.add(job.payload.beat_id)
            if (stage === "render") nextRenderIds.add(job.payload.beat_id)
            if (stage === "triptych") nextTriptychIds.add(job.payload.beat_id)
          }
        })
        const videoProgress = mapWorkshopVideoProgress(jobs, epId)
        setVideoFailures(mapWorkshopVideoFailures(jobs, epId, currentEpisodeRef.current?.beats.map(beat => beat.id)))
        const previousVideoBeats = beatVideoProgressRef.current
        Object.entries(videoProgress.beats).forEach(([beatId, item]) => {
          if (item.shotStage !== "succeeded" || !item.shotUrl) return
          const before = previousVideoBeats[beatId]
          if (before?.shotStage === "succeeded" && before.shotUrl === item.shotUrl) return
          updateBeatById(beatId, { video_url: item.shotUrl, upscaled_video_url: null, render_status: "completed", status: "completed" })
        })
        const nextProgramPreview = programPreviewPrompts(jobs, epId)
        setProgramPromptPreview((prev) => sameProgramPreviewPrompts(prev, nextProgramPreview) ? prev : nextProgramPreview)
        const nextVideoBeatIds = new Set(Object.keys(videoProgress.beats))
        const nextEpisodeVideoActive = Boolean(videoProgress.episode)
        setStageGeneratingSet("sketch", nextSketchIds)
        setStageGeneratingSet("render", nextRenderIds)
        setStageGeneratingSet("triptych", nextTriptychIds)
        beatVideoProgressRef.current = videoProgress.beats
        episodeVideoProgressRef.current = videoProgress.episode
        imageJobPollDelayRef.current = hasActiveWorkshopVideoProgress(videoProgress)
          ? WORKSHOP_VIDEO_POLL_MS
          : WORKSHOP_IDLE_POLL_MS
        setBeatVideoProgress(videoProgress.beats)
        setEpisodeVideoProgress(videoProgress.episode)
        let refresh = false
        const currentBeatId = selectedBeatIdRef.current
        for (const beatId of previouslyTriptych) {
          if (nextTriptychIds.has(beatId)) continue
          const triptychJob = episodeJobs.find((job) =>
            job.payload?.target_type === "beat_triptych" && job.payload?.beat_id === beatId,
          )
          if (!triptychJob || beatId !== currentBeatId) continue
          if (SUCCEEDED_JOB_STATUSES.has(triptychJob.status)) {
            message.success(WORKSHOP_H3_TRIPTYCH_GATE.ready)
          } else if (triptychJob.status === "failed") {
            message.error(`${WORKSHOP_H3_TRIPTYCH_GATE.failed}${triptychJob.error_message ? `：${triptychJob.error_message}` : ""}`)
          }
        }
        const trackedIds = trackedH3PromptJobIdsRef.current
        const trackedJobs = episodeJobs.filter((job) => trackedIds.includes(job.id))
        const activePromptJob = episodeJobs.find((job) =>
          (job.job_type === "h3_prompt" || job.payload?.target_type === "h3_prompt")
          && job.payload?.beat_id === currentBeatId
          && activeStatuses.has(job.status),
        )
        const trackedActive = trackedJobs.some((job) => activeStatuses.has(job.status))
        if (activePromptJob || trackedActive) {
          setGeneratingH3Prompt(true)
          if (activePromptJob && !trackedIds.includes(activePromptJob.id)) {
            trackedH3PromptJobIdsRef.current = [...trackedIds, activePromptJob.id]
          }
          const liveJob = activePromptJob || trackedJobs.find((job) => activeStatuses.has(job.status))
          if (liveJob) {
            setH3LiveBeatId(String(liveJob.payload?.beat_id || ""))
            setH3Live((prev) => {
              const base = prev.jobId === liveJob.id ? prev : emptyPromptLiveState(liveJob.id)
              return applyPromptJobSnapshot({ ...base, working: true }, liveJob.payload)
            })
          }
        } else if (trackedIds.length) {
          const allKnown = trackedJobs.length === trackedIds.length
          const allTerminal = allKnown && trackedJobs.every((job) => !activeStatuses.has(job.status))
          if (allTerminal) {
            setGeneratingH3Prompt(false)
            trackedH3PromptJobIdsRef.current = []
            const failed = trackedJobs.find((job) => job.status === "failed")
            const succeeded = trackedJobs.filter((job) => SUCCEEDED_JOB_STATUSES.has(job.status))
            if (failed) {
              const payload = failed.payload || {}
              const stream = payload.stream && typeof payload.stream === "object" ? payload.stream : {}
              setH3JobMeta({
                vision_status: payload.vision_status || payload.beat_info?.vision_status,
                vision_model: payload.vision_model || payload.beat_info?.vision_model,
                vision_image_count: payload.vision_image_count ?? payload.beat_info?.vision_image_count,
                author_errors: payload.author_errors,
              })
              setH3Live((prev) => {
                const withSnap = applyPromptJobSnapshot({ ...prev, working: false, failed: true }, payload)
                return {
                  ...withSnap,
                  working: false,
                  failed: true,
                  message: failed.error_message || withSnap.message || "生成失败",
                  text: workshopFailedLiveText({
                    liveText: withSnap.text || prev.text,
                    streamText: stream.text,
                    authorEnDraft: payload.author_en_draft,
                    authorZhDraft: payload.author_zh_draft,
                  }),
                }
              })
              message.error({ content: `H3 提示词生成失败: ${failed.error_message || "未知错误"}`, key: "h3PromptGen" })
            } else if (succeeded.length) {
              const currentJob = succeeded.find((job) => job.payload?.beat_id === currentBeatId) || succeeded[0]
              const newPrompt = currentJob.payload?.h3_prompt || currentJob.payload?.result_prompt
              setH3JobMeta(null)
              setH3Live((prev) => ({ ...prev, working: false, failed: false }))
              if (newPrompt && currentBeatId && currentBeatId === currentJob.payload?.beat_id) {
                updateBeatById(currentBeatId, {
                  h3_prompt: String(newPrompt),
                  h3_prompt_source: "generated",
                  timestamped_zh_prompt: currentJob.payload?.timestamped_zh_prompt || currentJob.payload?.beat_info?.timestamped_zh_prompt,
                  vision_status: currentJob.payload?.vision_status || currentJob.payload?.beat_info?.vision_status,
                  vision_model: currentJob.payload?.vision_model || currentJob.payload?.beat_info?.vision_model,
                  vision_image_count: currentJob.payload?.vision_image_count ?? currentJob.payload?.beat_info?.vision_image_count,
                  vision_source: currentJob.payload?.vision_source || currentJob.payload?.beat_info?.vision_source,
                })
                setH3PromptDraft(String(newPrompt))
                setH3PromptEditing(false)
              }
              message.success({ content: "H3 提示词已生成完成！", key: "h3PromptGen" })
              refresh = true
            } else {
              setH3Live((prev) => ({ ...prev, working: false }))
            }
          }
        } else {
          setGeneratingH3Prompt(false)
          setH3Live((prev) => prev.working ? { ...prev, working: false } : prev)
        }
        for (const [stage, ids] of trackedBatchJobsRef.current.entries()) {
          const relevant = episodeJobs.filter((job) => ids.has(job.id))
          if (relevant.length !== ids.size || relevant.some((job) => activeStatuses.has(job.status))) continue
          const completed = relevant.filter((job) => ["completed", "succeeded"].includes(job.status)).length
          const failed = relevant.filter((job) => job.status === "failed").length
          if (failed) {
            message.warning(`${stage === "sketch" ? "批量草图" : "批量渲染图"}完成：成功 ${completed}，失败 ${failed}`)
          } else {
            message.success(`${stage === "sketch" ? "批量草图" : "批量渲染图"}完成：成功 ${completed}，失败 ${failed}`)
          }
          trackedBatchJobsRef.current.delete(stage)
          refresh = true
        }
        const currentlyActive = new Set([...nextSketchIds, ...nextRenderIds, ...nextTriptychIds])
        if ([...previouslyActive].some((beatId) => !currentlyActive.has(beatId))) refresh = true
        if ([...previouslyActiveVideoBeats].some((beatId) => !nextVideoBeatIds.has(beatId))) refresh = true
        if (previouslyEpisodeVideoActive && !nextEpisodeVideoActive) refresh = true
        const trackedVideoIds = trackedVideoJobsRef.current
        if (trackedVideoIds.size) {
          const relevant = episodeJobs.filter((job) => trackedVideoIds.has(job.id))
          if (relevant.length === trackedVideoIds.size && relevant.every((job) => TERMINAL_JOB_STATUSES.has(job.status))) {
            const completed = relevant.filter((job) => SUCCEEDED_JOB_STATUSES.has(job.status)).length
            const failed = relevant.length - completed
            if (failed) {
              message.warning(`视频任务完成：成功 ${completed}，失败 ${failed}`)
            } else {
              message.success("视频任务已完成，成片已写入本集")
            }
            trackedVideoJobsRef.current = new Set()
            refresh = true
          }
        }
        if (refresh) await loadEpisodeDetail(epId)
      } catch {
        // Explicit actions surface errors; transient polling errors stay silent.
      }
    }

    async function saveBeforeVideoSubmit(ids?: string[]) {
      const episodeId = currentEpisodeRef.current?.id
      await beforeVideoSubmitRef.current?.(ids)
      if (currentEpisodeRef.current?.id !== episodeId) throw new Error("当前分集已切换，请重新点击生成")
    }

    function confirmForceRefine(durationSec: number): Promise<boolean> {
      const warning = refineForceWarning(videoOptions, durationSec)
      if (!warning) return Promise.resolve(true)
      return new Promise((resolve) => {
        Modal.confirm({
          title: "强制高清会显著延长出片时间",
          content: warning,
          okText: "仍然提交",
          cancelText: "取消",
          centered: true,
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        })
      })
    }

    async function handleGenerateVideo(prepareKeyframes = false) {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat || generatingVideo || generatingEpisodeVideo) return
      setGeneratingVideo(true)
      try {
        await saveBeforeVideoSubmit([beat.id])
        if (!(await confirmForceRefine(beatDurationSec(beat.video_duration)))) return
        message.loading({ content: "正在提交片段，生成指令将自动准备…", key: "vGen" })
        const res = await generateBeatVideo(csrfToken, projectId, ep.id, beat.id, withVideoPromptMode(buildVideoJobOptions(
          videoWorkflow,
          videoOptions,
          { duration_per_beat: beatDurationSec(beat.video_duration), prepare_keyframes: prepareKeyframes },
        ), programPreview && !prepareKeyframes))
        rememberVideoJobIds([res.job_id])
        setBeatVideoProgress(previous => ({ ...previous, [beat.id]: { status: "queued", progress: 0, scope: "shot", jobId: res.job_id } }))
        message.success({ content: "已开始准备并生成视频，可在当前片段查看进度", key: "vGen", duration: 4 })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "单镜视频任务创建失败"), key: "vGen", duration: 10 })
      } finally {
        setGeneratingVideo(false)
      }
    }

    async function handleRetryVideo(progress: WorkshopShotVideoProgress) {
      if (!progress.jobId || retryingVideoJob) return
      setRetryingVideoJob(progress.jobId)
      try {
        await retryJob(csrfToken, projectId, progress.jobId)
        rememberVideoJobIds([progress.jobId])
        await pollImageJobs()
        message.success("已继续生成，将复用已完成的准备步骤")
      } catch (error) {
        message.error(director2ErrorDetail(error, "重试失败"))
      } finally { setRetryingVideoJob(null) }
    }

    async function handleUpscaleBeat(beat: Director2Beat) {
      const ep = currentEpisodeRef.current
      if (!ep || !beat) return
      const reason = beatUpscaleDisabledReason(beat, beatVideoProgress[beat.id])
      if (reason) {
        message.warning(reason)
        return
      }
      setUpscalingBeatId(beat.id)
      try {
        message.loading({ content: "正在提交智能超清...", key: "vUpscale" })
        const res = await upscaleBeatVideo(
          csrfToken,
          projectId,
          ep.id,
          beat.id,
          buildVideoJobOptions(videoWorkflow, videoOptions),
        )
        rememberVideoJobIds([res.job_id])
        message.success({ content: `智能超清任务已进入队列：${res.job_id}`, key: "vUpscale", duration: 6 })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "智能超清任务创建失败"), key: "vUpscale", duration: 10 })
      } finally {
        setUpscalingBeatId(null)
      }
    }

    function confirmSmartClarify(beat: Director2Beat) {
      const reason = beatUpscaleDisabledReason(beat, beatVideoProgress[beat.id])
      if (reason) {
        message.warning(reason)
        return
      }
      Modal.confirm({
        title: `智能超清 ${workshopBeatLabel(beat)}`,
        content: smartClarifyConfirmText(
          beatDurationSec(beat.video_duration),
          playbackAspectRatio(videoOptions),
        ),
        okText: "开始超清",
        cancelText: "取消",
        centered: true,
        onOk: () => void handleUpscaleBeat(beat),
      })
    }

    async function handleRegenerateScript() {
      setRegeneratingScript(true)
      try {
        await refreshCurrentEpisode()
        message.success("剧本 Beat 分镜已重新编排就绪")
      } finally {
        setRegeneratingScript(false)
      }
    }

    async function handleRefineDecision(action: "confirm" | "skip", progress: WorkshopShotVideoProgress) {
      const jobId = String(progress.jobId || "").trim()
      if (!jobId) {
        message.error("任务信息缺失，请刷新后重试")
        return
      }
      setRefineAction({ jobId, action })
      try {
        if (action === "confirm") {
          await confirmProjectVideoRefine(csrfToken, projectId, jobId)
          message.success({ content: "已开始二采精修，只重跑第二遍，一采缓存直接复用", duration: 6 })
        } else {
          await skipProjectVideoRefine(csrfToken, projectId, jobId)
          message.success({ content: "已保留一采预览作为本镜成片", duration: 6 })
        }
        await refreshCurrentEpisode()
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, action === "confirm" ? "确认二采失败" : "保留一采失败"), duration: 10 })
      } finally {
        setRefineAction(null)
      }
    }

    async function handleGenerateEpisodeVideo() {
      const ep = currentEpisodeRef.current
      if (!ep || generatingEpisodeVideo) return
      const refineDurationSec = videoRenderMode === "episode"
        ? episodeDurationSec
        : Math.max(0, ...(ep.beats || []).map((beat) => beatDurationSec(beat.video_duration)))
      const jobOptions = withVideoPromptMode(
        buildVideoJobOptions(videoWorkflow, videoOptions),
        programPreview,
      )
      if (videoRenderMode === "episode" && videoOptions.refine_enabled === "true") {
        message.info({ content: "整集直出无法中途确认，本次将连续跑完两段式", duration: 6 })
      }
      setGeneratingEpisodeVideo(true)
      try {
        await saveBeforeVideoSubmit()
        if (!(await confirmForceRefine(refineDurationSec))) return
        const res = await generateEpisodeVideo(
          csrfToken,
          projectId,
          ep.id,
          jobOptions,
        )
        rememberVideoJobIds(res.job_ids?.length ? res.job_ids : [res.job_id])
        message.success({
          content: `${formatEpisodeVideoSubmitMessage(res)}，可在「全部任务 → 视频生成」中查看进度`,
          duration: 6,
        })
      } catch (err) {
        const detail = director2ErrorDetail(err, "视频任务创建失败")
        message.error({ content: detail, duration: 10 })
      } finally {
        setGeneratingEpisodeVideo(false)
      }
    }

    async function handleGenerateSelectedShots() {
      const ep = currentEpisodeRef.current
      if (!ep || generatingEpisodeVideo) return
      const selectedBeats = (ep.beats || []).filter((beat) => checkedBeatIds.has(beat.id))
      const beatIds = selectedBeats.map((beat) => beat.id)
      if (!beatIds.length) {
        message.warning("请先勾选要生成的镜头")
        return
      }
      const refineDurationSec = Math.max(
        0, ...selectedBeats.map((beat) => beatDurationSec(beat.video_duration)),
      )
      setGeneratingEpisodeVideo(true)
      try {
        await saveBeforeVideoSubmit(beatIds)
        if (!(await confirmForceRefine(refineDurationSec))) return
        const res = await generateEpisodeVideo(
          csrfToken,
          projectId,
          ep.id,
          withVideoPromptMode(
            buildVideoJobOptions(videoWorkflow, videoOptions, selectedShotGenerateExtra(beatIds)),
            programPreview,
          ),
        )
        rememberVideoJobIds(res.job_ids?.length ? res.job_ids : [res.job_id])
        message.success({
          content: `${formatSelectedShotSubmitMessage(res)}，可在「全部任务 → 视频生成」中查看进度`,
          duration: 6,
        })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "选中镜头视频任务创建失败"), duration: 10 })
      } finally {
        setGeneratingEpisodeVideo(false)
      }
    }

    async function handleDeleteSelectedBeats(ids: string[]) {
      const ep = currentEpisodeRef.current
      if (!ep || deletingBeatsRef.current) throw new Error("正在删除片段，请稍候")
      deletingBeatsRef.current = true; setDeletingBeats(true)
      try {
        const result = await deleteEpisodeBeats(csrfToken, projectId, ep.id, ids)
        if (currentEpisodeRef.current?.id === ep.id) {
          const current = currentEpisodeRef.current
          const data = { ...current.data }
          for (const key of ["episode_video_url", "episode_video_source", "episode_video_job_id"]) delete data[key]
          applyCurrentEpisode({ ...current, data, beats: result.beats, shots_count: result.beats.length, beat_count: result.beats.length, episode_video_url: "", episode_video_source: "", episode_video_job_id: "" })
          const next = activeBeatAfterDelete(current.beats, result.beats, selectedBeatIdRef.current)
          if (next) applySelectedBeatId(next)
          const remaining = new Set(result.beats.map(beat => beat.id))
          setCheckedBeatIds(checked => new Set([...checked].filter(id => remaining.has(id))))
        }
        void fetchEpisodes()
        message.success(`已删除 ${result.deleted_beat_ids.length} 个片段`)
      } finally { deletingBeatsRef.current = false; setDeletingBeats(false) }
    }

    useEffect(() => {
      const tab = parseWorkshopTab(searchParams.get("tab"))
      if (tab) { setToolPanel(tab === "script" ? "script" : tab === "dubbing" ? "dubbing" : tab === "compose" ? null : "details"); if (tab === "compose") setPreviewRequest(v => v + 1) }
    }, [searchParams])

    // ---------------- 新建/修改分集弹窗 ----------------
    function openCreateModal() {
      setEditingEpisode(null)
      setEpisodeFormError("")
      episodeForm.resetFields()
      episodeForm.setFieldsValue({ episode_num: nextEpisodeNumber(episodes), title: "", status: "draft", script_text: "" })
      setModalVisible(true)
    }

    function openEditModal(ep: Director2Episode) {
      setEditingEpisode(ep)
      setEpisodeFormError("")
      episodeForm.resetFields()
      episodeForm.setFieldsValue({ episode_num: ep.episode_num, title: ep.title, status: ep.status || "draft", script_text: ep.script_text || "" })
      setModalVisible(true)
    }

    async function handleSubmit(values: EpisodeFormState) {
      if (submitEpisodeRef.current) return
      submitEpisodeRef.current = true
      setSubmitting(true)
      setEpisodeFormError("")
      try {
        const payload = { ...values, title: values.title.trim(), script_text: values.script_text || "", shots_count: editingEpisode?.shots_count ?? 0 }
        if (editingEpisode) {
          await updateEpisode(csrfToken, projectId, editingEpisode.id, payload)
          message.success("分集已更新")
        } else {
          await createEpisode(csrfToken, projectId, payload)
          message.success("分集已创建")
          setEpisodeSearch("")
          setEpisodeFilter("all")
        }
        setModalVisible(false)
        await fetchEpisodes()
      } catch (error) {
        setEpisodeFormError(director2ErrorDetail(error, "保存失败，请重试。你的输入仍保留在此处。"))
      } finally {
        submitEpisodeRef.current = false
        setSubmitting(false)
      }
    }

    function confirmDeleteEpisode(ep: Director2Episode) {
      setDeletingEpisode(ep)
      setDeleteError("")
      setDeleteModalOpen(true)
    }

    async function handleDeleteEpisode() {
      if (!deletingEpisode || deleteEpisodeRef.current) return
      deleteEpisodeRef.current = true
      setDeleting(true)
      setDeleteError("")
      try {
        await deleteEpisode(csrfToken, projectId, deletingEpisode.id)
        message.success("分集已删除")
        setDeleteModalOpen(false)
        await fetchEpisodes()
      } catch (error) {
        setDeleteError(director2ErrorDetail(error, "删除失败，请重试。原分集仍保留。"))
      } finally {
        deleteEpisodeRef.current = false
        setDeleting(false)
      }
    }

    // 对应原版 watch(() => route.params.episodeId, { immediate: true })：URL 双向联动
    useEffect(() => {
      if (episodeId) {
        currentEpisodeIdRef.current = episodeId
        setCurrentEpisodeId(episodeId)
        setCheckedBeatIds(new Set())
        onDetailModeChange?.(true)
        loadEpisodeDetail(episodeId)
      } else {
        currentEpisodeIdRef.current = null
        setCurrentEpisodeId(null)
        applyCurrentEpisode(null)
        onDetailModeChange?.(false)
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [episodeId])

    // 最新闭包 trampoline：空闲 3 秒、本集视频任务活跃时 1 秒（等价 Vue 闭包读响应式值）
    const pollImageJobsRef = useRef(pollImageJobs)
    useEffect(() => {
      pollImageJobsRef.current = pollImageJobs
    })

    useEffect(() => {
      let cancelled = false
      const clearPollTimer = () => {
        if (imageJobPollTimerRef.current) {
          window.clearTimeout(imageJobPollTimerRef.current)
          imageJobPollTimerRef.current = null
        }
      }
      const scheduleNextPoll = () => {
        if (cancelled) return
        imageJobPollTimerRef.current = window.setTimeout(() => {
          void (async () => {
            await pollImageJobsRef.current()
            scheduleNextPoll()
          })()
        }, imageJobPollDelayRef.current)
      }
      ;(async () => {
        await Promise.all([fetchEpisodes(), loadAssets()])
        if (cancelled) return
        await pollImageJobs()
        if (cancelled) return
        scheduleNextPoll()
      })()
      return () => {
        cancelled = true
        clearPollTimer()
      }
      // 对应原版 onMounted + onUnmounted
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
      setProgramPreview(loadProgramPreview(projectId))
    }, [projectId])

    useEffect(() => {
      let cancelled = false
      const saved = loadSavedVideoSettings(projectId)
      ;(async () => {
        const preferences = await projectVideoPreferences(projectId)
        if (cancelled) return
        const resolution = preferences?.resolution || null
        setConfirmedVideoResolution(resolution)
        const incoming: Record<string, string> = { ...(preferences?.aspectRatio ? { aspect_ratio: preferences.aspectRatio } : {}), ...(saved || {}) }
        const lockedQuality = videoResolutionQuality(resolution?.value)
        const lockedRefine = videoResolutionQuality(resolution?.value, true)
        if (lockedQuality) incoming.quality = lockedQuality
        if (lockedRefine) incoming.refine_quality = lockedRefine
        const initial = Object.keys(incoming).length ? incoming : null
        try {
          const payload = await listVideoWorkflowModes()
          if (cancelled) return
          const workflows = timelineVideoWorkflows(payload.modes)
          setVideoWorkflows(workflows)
          const requested = saved?.workflow || videoWorkflow
          const selected = workflows.find((item) => item.id === requested) || workflows[0]
          applyVideoSettings(selected?.id || DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, selected, initial)
        } catch {
          if (cancelled) return
          applyVideoSettings(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, undefined, initial)
        }
      })()
      return () => {
        cancelled = true
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [projectId])

    useEffect(() => {
      const syncResolution = async (event: Event) => {
        if ((event as CustomEvent<{ projectId?: string }>).detail?.projectId !== projectId) return
        const resolution = await projectVideoResolution(projectId)
        setConfirmedVideoResolution(resolution)
        const lockedQuality = videoResolutionQuality(resolution?.value)
        const lockedRefine = videoResolutionQuality(resolution?.value, true)
        if (!lockedQuality && !lockedRefine) return
        setVideoOptions(current => {
          const next = { ...current }
          if (lockedQuality && "quality" in next) next.quality = lockedQuality
          if (lockedRefine && "refine_quality" in next) next.refine_quality = lockedRefine
          return next
        })
      }
      window.addEventListener("director-assistant-project-updated", syncResolution)
      return () => window.removeEventListener("director-assistant-project-updated", syncResolution)
    }, [projectId])

    useEffect(() => {
      if (!selectedBeat) {
        h3MaterialBeatIdRef.current = null
        setH3RefImages([])
        return
      }
      if (h3MaterialBeatIdRef.current !== selectedBeat.id) {
        h3MaterialBeatIdRef.current = selectedBeat.id
        setH3ImagesExpanded(false)
        setH3RefImages(collectH3RefImages(selectedBeat))
        return
      }
      setH3RefImages((prev) => withTriptychPanels(selectedBeat, prev.length ? prev : collectH3RefImages(selectedBeat)))
      // collectH3RefImages 读当前资产与造型选择；切镜重建，资产晚到则补齐空组
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedBeat?.id, projectAssets, selectedBeat?.character_ids, selectedBeat?.scene_id, selectedBeat?.prop_ids, selectedBeat?.character_look_ids, selectedBeat?.triptych_panels, selectedBeat?.triptych_url])

    useImperativeHandle(ref, () => ({ fetchEpisodes }))

    function openToolPanel(panel: "details" | "script" | "dubbing") {
      setToolPanel(panel)
    }
    async function previewOverviewEpisode(episode: Director2Episode) {
      try { const detail = await getEpisodeDetail(projectId, episode.id); setOverviewPreview(detail); setOverviewPreviewId(detail.beats[0]?.id || "") }
      catch (error) { message.error(director2ErrorDetail(error, "预览加载失败")) }
    }
    function exportEpisodeText() {
      if (!currentEpisode) return
      const text = "# 第 " + currentEpisode.number + " 集 · " + currentEpisode.title + "\n\n" + currentEpisode.beats.map((beat, index) => "## 片段 " + String(index + 1).padStart(2, "0") + "\n\n" + (beat.video_prompt_zh || beat.action || "")).join("\n\n")
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }))
      const link = document.createElement("a"); link.href = url; link.download = currentEpisode.title + ".md"; link.click(); URL.revokeObjectURL(url)
    }
    return (
      <div className={`d2-episode-workshop ws-root workshop-container${currentEpisodeId ? " in-episode-detail" : ""}`}>
        <header className="ws-project-header">
          {currentEpisodeId ? <div className="ws-breadcrumb"><Button type="text" onClick={handleBackToOverview}>分集视频</Button><ChevronRight size={12}/><Dropdown trigger={["click"]} menu={{ selectedKeys: [currentEpisodeId], selectable: true, items: episodes.map(episode => ({ key: episode.id, label: "第 " + episode.episode_num + " 集 · " + episode.title, onClick: () => openEpisodeDetail(episode.id) })) }}><Button type="text" className="ws-episode-switch">{currentEpisode ? "第 " + currentEpisode.number + " 集 · " + currentEpisode.title : "正在加载分集"}<ListFilter size={14}/></Button></Dropdown><Button type="text" className={"ws-save-state" + (headerSaveState === "保存失败" ? " is-error" : "")} onClick={() => headerSaveRef.current()} aria-label="保存片段正文"><Check size={12}/>{headerSaveState}</Button></div> : <span className="ws-project-name" title={projectName}>{projectName || "剧集工坊"}</span>}
          <div className="ws-header-actions">{projectControls && <Popover trigger="click" placement="bottomRight" content={<div className="ws-project-controls">{projectControls}</div>}><Button type="text" icon={<Settings2 size={14}/>} aria-label="项目设置">{currentEpisodeId ? "" : "项目设置"}</Button></Popover>}
            {currentEpisode && <><Director2VideoSettingsPopover workflowId={videoWorkflow} workflows={videoWorkflows} fields={videoOptionFields} values={videoOptions} durationSec={selectedBeat ? beatDurationSec(selectedBeat.video_duration) : undefined} confirmedResolutionLabel={confirmedVideoResolution?.label} programPreview={programPreview} missingPromptCount={beatsMissingH3Prompt(currentEpisode.beats || []).length} onWorkflowChange={handleVideoWorkflowChange} onChange={handleVideoOptionChange} onProgramPreviewChange={handleProgramPreviewChange}/><Dropdown trigger={["click"]} menu={{ items: [{ key: "text", label: "导出本集文案", onClick: exportEpisodeText }, { key: "edit", label: "进入智能剪辑导出", onClick: () => navigate(director2ProjectPath(projectId, "edit", currentEpisode.id)) }] }}><Button className="ws-subtle">导出</Button></Dropdown><Button className="ws-subtle" disabled={!videoReadyCount} onClick={() => setPreviewRequest(v => v + 1)}>预览全片</Button><Dropdown trigger={["click"]} menu={{ items: [{ key: "script", label: "本集剧本", onClick: () => openToolPanel("script") }, { key: "refresh", label: "刷新数据", onClick: () => void refreshCurrentEpisode() }, { key: "all", label: "生成全片段视频", disabled: generatingEpisodeVideo || episodeVideoJobActive, onClick: () => void handleGenerateEpisodeVideo() }, { key: "script-generation", label: "重新生成脚本", disabled: regeneratingScript, onClick: () => void handleRegenerateScript() }] }}><Button type="text" icon={<MoreHorizontal size={16}/>} aria-label="本集更多操作"/></Dropdown></>}
          </div>
        </header>
        {!currentEpisodeId ? <WorkshopOverview episodes={displayedEpisodes} total={episodes.length} loading={loading} error={episodeListError} query={episodeSearch} filter={episodeFilter} sort={episodeSort} onQuery={setEpisodeSearch} onFilter={setEpisodeFilter} onSort={setEpisodeSort} onCreate={openCreateModal} onEdit={openEpisodeDetail} onSettings={openEditModal} onDelete={confirmDeleteEpisode} onRefresh={() => { void fetchEpisodes(); void loadAssets() }} onPreview={episode => void previewOverviewEpisode(episode)}/>
          : currentEpisode ? <WorkshopWorkspace key={currentEpisode.id} csrfToken={csrfToken} projectId={projectId} episode={currentEpisode} selected={selectedBeat} assets={projectAssets} assetsState={projectAssetsState} progress={beatVideoProgress} checked={checkedBeatIds} generatingPrompt={h3GenerateBusy} upscalingId={upscalingBeatId} onSelect={selectBeat} onPatch={updateBeatById} onCheck={toggleCheckedBeat} onCheckAll={toggleCheckAllBeats} onDetails={() => openToolPanel("details")} onDubbing={() => openToolPanel("dubbing")} onSmartEdit={() => navigate(director2ProjectPath(projectId, "edit", currentEpisode.id))} onGenerate={() => void handleGenerateVideo()} onGenerateKeyframes={() => void handleGenerateVideo(true)} submittingVideo={generatingVideo} failures={videoFailures} retryingJobId={retryingVideoJob} onRetryVideo={progress => void handleRetryVideo(progress)} onBeforeSubmitReady={flush => { beforeVideoSubmitRef.current = flush }} onPrompt={() => { void saveBeforeVideoSubmit([selectedBeat?.id || ""]).then(() => requestGenerateH3Prompt()).catch(error => message.error(director2ErrorDetail(error, "请先保存正文"))) }} onUpscale={confirmSmartClarify} onBatchGenerate={() => void handleGenerateSelectedShots()} onBatchDelete={handleDeleteSelectedBeats} batchGenerating={generatingEpisodeVideo} batchDeleting={deletingBeats} onRefine={(action, progress) => void handleRefineDecision(action, progress)} refineBusy={Boolean(refineAction)} onHistory={setHistoryBeat} onRefreshAssets={() => void loadAssets()} onSaveState={(state, save) => { headerSaveRef.current = save; setHeaderSaveState(previous => previous === state ? previous : state) }} previewRequest={previewRequest}/>
          : <div className="ws-loading"><Spin/><span>正在加载分集…</span></div>}
        <Drawer open={Boolean(toolPanel) && Boolean(currentEpisode)} onClose={() => setToolPanel(null)} title={toolPanel === "script" ? "本集剧本" : toolPanel === "dubbing" ? "配音" : "制作详情"} size={toolPanel === "dubbing" ? 1100 : 880} rootClassName="director2-app ws-details-drawer" destroyOnHidden>
          {/* 抽屉经 portal 挂在 body 上，需自带 .d2-episode-workshop 作用域，否则工坊样式全部失效 */}
          <div className="d2-episode-workshop ws-drawer-scope">
          {toolPanel === "details" && selectedBeat ? <div className="ws-detail-tools"><div className="ws-detail-actions"><span className="xiaji-inspector-tab-label"><Layers size={14} />素材组<span className={`status-chip ${h3Failed || !(savedH3Prompt.trim() && !h3PromptDirty) ? "is-idle" : "is-active"}`}><span className="chip-dot" /> {h3StatusLabel}</span></span>{selectedBeatSplit ? <Button size="small" disabled={h3GenerateBusy} onClick={() => requestMergeH3Prompt()}>合并为一条生成</Button> : null}</div>
                                    <div className="xiaji-inspector-pane is-material">
                                    <div className="h3-material-content">
                                      <div className="h3-material-left">
                                        <div className="h3-ref-block">
                                          <div className="h3-ref-block-head">
                                            <span className="h3-ref-label">参考图片</span>
                                            <Space size={6}>
                                            <Button size="small" onClick={() => handleSelectExistingImages()}>
                                              选已有 {h3RefImages.length}/9
                                            </Button>
                                            <Button
                                              size="small"
                                              loading={generatingTriptychBeatIds.has(selectedBeat?.id || "")}
                                              onClick={() => void generateSingleBeatTriptych()}
                                            >
                                              {selectedBeat?.triptych_panels?.start ? "重生成三联" : "生成三联关键帧"}
                                            </Button>
                                            </Space>
                                          </div>
                                          <div className="h3-ref-grid">
                                            {h3RefImagesVisible.map((img, idx) => (
                                              <div key={img.id || idx} className="h3-ref-img-cell">
                                                {img.url ? (
                                                  <img
                                                    src={img.url}
                                                    alt={`图片${idx + 1}`}
                                                    onClick={() => openMediaPreview({
                                                      src: img.url,
                                                      title: img.name || `图片${idx + 1}`,
                                                      description: img.category,
                                                    })}
                                                  />
                                                ) : (
                                                  <div className="h3-ref-img-empty">
                                                    <ImageIcon size={18} />
                                                    <span>图片{idx + 1}</span>
                                                  </div>
                                                )}
                                                <div className="h3-ref-info">
                                                  <span className="h3-ref-seq">图片{idx + 1}</span>
                                                  {img.name ? (
                                                    <span className="h3-ref-name" title={img.name}>
                                                      <i className={`h3-ref-cat-dot ${img.category === "prop" ? "is-prop" : img.category === "scene" ? "is-scene" : "is-char"}`} />
                                                      {img.name}
                                                    </span>
                                                  ) : null}
                                                </div>
                                                <button
                                                  type="button"
                                                  className="h3-ref-del-btn"
                                                  title="移除此参考图"
                                                  onClick={(e) => { e.stopPropagation(); removeH3RefImage(idx) }}
                                                >
                                                  ×
                                                </button>
                                              </div>
                                            ))}
                                            <Upload accept="image/*" showUploadList={false} beforeUpload={handleUploadH3Image}>
                                              <div className="h3-ref-add-btn">
                                                <Plus size={16} />
                                              </div>
                                            </Upload>
                                          </div>
                                          {h3RefImages.length > 3 ? (
                                            <div className="h3-ref-expand" onClick={() => setH3ImagesExpanded((prev) => !prev)}>
                                              {h3ImagesExpanded ? "收起" : `展开更多 (+${h3RefImages.length - 3})`}
                                            </div>
                                          ) : null}
                                        </div>
                                      </div>
                                      <div className="h3-prompt-panel">
                                        <div className="h3-prompt-head">
                                          <div className="h3-prompt-title-block">
                                            <span className="h3-prompt-title">提示词</span>
                                            {h3VisionLine ? (
                                              <span className="h3-prompt-vision">{h3VisionLine}</span>
                                            ) : null}
                                          </div>
                                          <div className="h3-prompt-head-actions">
                                            <Button
                                              size="small"
                                              type="primary"
                                              icon={<Sparkles size={12} />}
                                              loading={selectedH3Working}
                                              disabled={h3GenerateBusy && !selectedH3Working}
                                              onClick={() => requestGenerateH3Prompt()}
                                            >
                                              {h3GenerateLabel}
                                            </Button>
                                            {showH3Editor ? (
                                              <>
                                                <Button
                                                  size="small"
                                                  loading={savingH3Prompt}
                                                  disabled={generatingH3Prompt || !h3PromptDirty}
                                                  onClick={() => void saveH3Prompt()}
                                                >
                                                  保存
                                                </Button>
                                                {savedH3Prompt.trim() ? (
                                                  <Button size="small" disabled={generatingH3Prompt || savingH3Prompt} onClick={() => cancelH3PromptEdit()}>
                                                    取消
                                                  </Button>
                                                ) : null}
                                              </>
                                            ) : (
                                              <Button
                                                size="small"
                                                icon={<Pencil size={12} />}
                                                disabled={generatingH3Prompt}
                                                onClick={() => {
                                                  setH3PromptDraft(savedH3Prompt || programPrompt)
                                                  setH3PromptEditing(true)
                                                }}
                                              >
                                                编辑
                                              </Button>
                                            )}
                                            <Button
                                              type="link"
                                              size="small"
                                              icon={<Copy size={12} />}
                                              disabled={!String(h3PromptCopyText).trim()}
                                              onClick={() => copyH3Prompt()}
                                            >
                                              复制
                                            </Button>
                                          </div>
                                        </div>
                                        {showH3Live ? (
                                          <WorkshopPromptLive state={h3Live} />
                                        ) : showH3Editor ? (
                                          <Input.TextArea
                                            className="h3-prompt-editor"
                                            value={h3PromptDraft}
                                            disabled={savingH3Prompt}
                                            placeholder={"请先生成三联关键帧并查看画面，再点「生成 H3 提示词」。也可粘贴外部 MiniMax H3 六段，保存后出片按原文使用。"}
                                            onChange={(e) => {
                                              setH3PromptEditing(true)
                                              setH3PromptDraft(e.target.value)
                                            }}
                                          />
                                        ) : showH3ProgramPreview ? (
                                          <>
                                            <div className="h3-program-preview-note">
                                              {`以下是最近一次程序装箱预览的提示词${programPromptPreview?.jobId ? `（任务 ${programPromptPreview.jobId}）` : ""}，未保存到镜头。如需长期复用，请生成 H3 提示词，或点「编辑」后保存。`}
                                            </div>
                                            <div
                                              className="h3-prompt-display"
                                              dangerouslySetInnerHTML={{ __html: renderH3PromptHtml(programPrompt) }}
                                            />
                                          </>
                                        ) : (
                                          <div
                                            className="h3-prompt-display"
                                            dangerouslySetInnerHTML={{ __html: renderH3PromptHtml(savedH3Prompt) }}
                                          />
                                        )}
                                      </div>
                                    </div>
                                    </div>
                              </div> : toolPanel === "dubbing" && currentEpisode ? <DubbingWorkbench csrfToken={csrfToken} projectId={projectId} episodeId={currentEpisode.id}/> : currentEpisode ? <div className="ws-script-original">{currentEpisode.original_lines?.length ? currentEpisode.original_lines.join("\n") : currentEpisode.script_text}</div> : null}
          </div>
        </Drawer>
        {historyBeat && currentEpisode && <WorkshopHistory key={historyBeat.id} projectId={projectId} episodeId={currentEpisode.id} csrfToken={csrfToken} beat={historyBeat} onClose={() => setHistoryBeat(null)} onAdopt={beat => { updateBeatById(beat.id, beat); void fetchEpisodes() }}/>}
        <Modal open={Boolean(overviewPreview)} title={overviewPreview?.title} onCancel={() => setOverviewPreview(null)} footer={null} width={1000} centered destroyOnHidden className="ws-preview-modal">{overviewPreview && <WorkshopPlayer beats={overviewPreview.beats} selectedId={overviewPreviewId} onSelect={setOverviewPreviewId}/>}</Modal>
        {/* ==================== 新建/编辑分集弹窗 ==================== */}
        <Modal
          open={deleteModalOpen}
          title={<div className="series-delete-heading"><CircleAlert size={24} className="series-delete-icon" /><h2>{deletingEpisode ? `删除第 ${deletingEpisode.episode_num} 集？` : "删除分集"}</h2></div>}
          width={440}
          centered
          className="series-delete-modal"
          mask={{ closable: false }}
          keyboard={!deleting}
          closable={!deleting}
          onCancel={() => { if (!deleteEpisodeRef.current) setDeleteModalOpen(false) }}
          afterClose={() => setDeletingEpisode(null)}
          afterOpenChange={(open) => { if (open) deleteCancelRef.current?.focus() }}
          footer={<><Button ref={deleteCancelRef} aria-label="取消" disabled={deleting} onClick={() => { if (!deleteEpisodeRef.current) setDeleteModalOpen(false) }}>取消</Button><Button type="primary" danger aria-label="删除分集" aria-busy={deleting} loading={deleting} disabled={deleting} onClick={() => { void handleDeleteEpisode() }}>删除分集</Button></>}
        >
          {deleteError && <Alert type="error" showIcon title="删除未完成" description={deleteError} className="series-form-error" />}
          <div className="series-delete-content"><strong>{deletingEpisode?.title}</strong><p>该分集的剧本和镜头编排将被删除，且无法恢复。项目资产仍会保留。</p></div>
        </Modal>
        <Modal
          open={modalVisible}
          title={<div className="series-form-heading"><span><Film size={22} /></span><div><h2>{isEdit ? "编辑分集" : "新增分集"}</h2><p>写下这一集的故事，接着进入工坊制作镜头。</p></div></div>}
          confirmLoading={submitting}
          okButtonProps={{ disabled: submitting, "aria-label": isEdit ? "保存修改" : "创建分集", "aria-busy": submitting }}
          okText={isEdit ? "保存修改" : "创建分集"}
          cancelText="取消"
          width={568}
          forceRender
          centered
          onOk={() => episodeForm.submit()}
          onCancel={() => { if (!submitEpisodeRef.current) setModalVisible(false) }}
          closable={!submitting}
          keyboard={!submitting}
          mask={{ closable: !submitting }}
          cancelButtonProps={{ disabled: submitting, "aria-label": "取消" }}
          afterOpenChange={(open) => { if (open) episodeForm.getFieldInstance("title")?.focus({ cursor: "end" }) }}
          className="series-form-modal"
        >
          <Form<EpisodeFormState> form={episodeForm} name="series-episode" layout="vertical" onFinish={handleSubmit} disabled={submitting} requiredMark={false}>
            {episodeFormError && <Alert type="error" showIcon title="保存未完成" description={episodeFormError} className="series-form-error" />}
            <div className="series-form-first-row">
                <Form.Item name="episode_num" label={<span>集数序号 <i className="series-required">*</i></span>} extra={isEdit ? "集数在创建后固定" : "创建后集数固定，请确认序号。"} rules={[
                  { required: true, message: "请输入集数序号" },
                  { validator: (_, value) => {
                    if (value == null) return Promise.resolve()
                    if (!Number.isSafeInteger(value) || value < 1) return Promise.reject(new Error("请输入大于 0 的整数"))
                    if (!isEdit && episodes.some((ep) => ep.episode_num === value)) return Promise.reject(new Error("该集数已存在，请使用其他序号"))
                    return Promise.resolve()
                  } },
                ]}>
                  <InputNumber
                    min={1}
                    precision={0}
                    disabled={isEdit || submitting}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
                <Form.Item name="title" label={<span>分集标题 <i className="series-required">*</i></span>} rules={[
                  { required: true, whitespace: true, message: "请输入分集标题" },
                  { max: 255, message: "分集标题最多 255 个字符" },
                ]}>
                  <Input placeholder="例如：黎明的来信" maxLength={255} />
                </Form.Item>
            </div>

            <Form.Item name="status" label="制作状态" rules={[{ required: true, message: "请选择制作状态" }]}>
              <Select aria-label="分集制作状态" classNames={{ popup: { root: "series-status-popup" } }} options={editingEpisode && !episodeStatusOptions.some((item) => item.value === editingEpisode.status)
                ? [{ value: editingEpisode.status, label: episodeStatusLabel(editingEpisode.status), disabled: true }, ...episodeStatusOptions]
                : episodeStatusOptions} />
            </Form.Item>
            <div className="series-stages series-form-stages" role="img" aria-label={`制作阶段：${episodeStatusLabel(formStatus)}`}><Steps size="small" titlePlacement="vertical" responsive={false} items={episodeStageItems(formStatus)} /></div>

            <Form.Item name="script_text" label={<span>分集剧本 <span className="series-optional">（选填）</span></span>}>
              <Input.TextArea
                placeholder="写下对白、画面与镜头描述…"
                rows={6}
                showCount
              />
            </Form.Item>
            <p className="series-form-note"><Info size={15} />也可以在内容库导入完整剧本，再同步为分集。</p>
          </Form>
        </Modal>
      </div>
    )
  },
)

export default EpisodeWorkshopPane
