// 剧集工坊面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/EpisodeWorkshopPane.vue
// Vue → React 对应：ref→useState、computed→useMemo、watch(route.params.episodeId)→useEffect(episodeId)、
// onMounted/onUnmounted→useEffect（生图/视频/合成任务静默轮询：空闲 3 秒，本集视频任务活跃时 1 秒）；
// currentEpisode / selectedBeat 等深响应对象的就地改写收敛为 applyCurrentEpisode / mutateCurrentEpisode /
// updateSelectedBeat（同步维护 ref 供轮询与异步续体读取，等价 Vue 的 .value 语义）；
// reactive(Set) generatingBeatIds / generatingRenderBeatIds 以 ref 镜像 + state 双写保持同步读取语义；
// 路由联动：openEpisodeDetail/handleBackToOverview → navigate(director2ProjectPath(...))；
// 父组件可经 ref 调用 fetchEpisodes()。
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type CSSProperties } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import {
  Alert,
  Button,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Upload,
  message,
} from "antd"
import {
  Plus,
  Film,
  Clapperboard,
  RefreshCw,
  Sparkles,
  Users,
  FileText,
  Check,
  Maximize2,
  Image as LucideImage,
  ImageIcon,
  Pencil,
  Crop,
  Download,
  Upload as UploadIcon,
  Box,
  ExternalLink,
  Video,
  ArrowLeft,
  Layers,
  Copy,
} from "lucide-react"
import {
  listEpisodes,
  createEpisode,
  updateEpisode,
  deleteEpisode,
  getEpisodeDetail,
  updateEpisodeBeat,
  generateBeatSketch,
  generateBeatRender,
  generateBeatTriptych,
  generateBeatImagesBatch,
  generateBeatH3Prompt,
  generateBeatVideo,
  generateEpisodeVideo,
  upscaleBeatVideo,
  composeEpisodeVideo,
  getEpisodeDubbing,
  listAssets,
  listJobs,
  listVideoWorkflowModes,
  director2ErrorDetail,
  type Director2Episode,
  type Director2EpisodeDetail,
  type Director2Beat,
  type Director2Asset,
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
import { parseWorkshopTab, type WorkshopTabKey } from "../dubbing-track"
import {
  DIRECTOR2_DEFAULT_VIDEO_WORKFLOW,
  DIRECTOR2_VIDEO_FALLBACK_FIELDS,
  beatHasUpscaled,
  beatPlaybackUrl,
  beatUpscaleDisabledReason,
  buildVideoJobOptions,
  defaultVideoOptionValues,
  episodeFilmSource,
  episodeFilmUrl,
  episodeVideoRenderMode,
  formatEpisodeVideoSubmitMessage,
  formatSelectedShotSubmitMessage,
  groupedVideoWorkflowOptions,
  loadSavedVideoSettings,
  playbackAspectRatio,
  sanitizeVideoOptionValues,
  saveVideoSettings,
  selectedShotGenerateExtra,
  shotVideoActionLabel,
  shotVideoReadyCount,
  timelineVideoWorkflows,
  visibleVideoOptionFields,
  type Director2WorkflowMode,
} from "../director2-video-settings"
import { useMediaPreview } from "../media-preview"
import { mediaAspectVars, parseMediaAspect, type MediaAspectSize } from "../../lib/utils"
import { firstCharacterLookImageUrl } from "./assets/shared"
import { renderH3PromptHtml } from "../h3-prompt-display"
import {
  beatDurationSec,
  formatBeatDurationLabel,
  formatBeatDurationZh,
  sumBeatDurationSec,
} from "../workshop-beat-duration"
import { workshopBeatHasSplitTakes, workshopBeatLabel } from "../workshop-beat-label"
import {
  WORKSHOP_H3_TRIPTYCH_GATE,
  workshopH3GenerateLabel,
  workshopH3PromptGate,
} from "../workshop-h3-gate"
import { withTriptychPanels } from "../workshop-r2v-refs"
import { shouldShowWorkshopPromptLive, workshopFailedLiveText, workshopH3StatusLabel } from "../workshop-h3-status"
import { workshopPromptAsideLine } from "../workshop-vision-status"
import {
  WORKSHOP_IDLE_POLL_MS,
  WORKSHOP_VIDEO_POLL_MS,
  hasActiveWorkshopVideoProgress,
  mapWorkshopVideoProgress,
  workshopVideoOverlayLabel,
  workshopVideoPercentLabel,
  type WorkshopEpisodeVideoProgress,
  type WorkshopShotVideoProgress,
} from "../workshop-video-progress"
import "./episode-workshop.css"

interface EpisodeWorkshopPaneProps {
  csrfToken: string
  projectId: string
  episodeId?: string | null
  onDetailModeChange?: (inDetail: boolean) => void
}

export type EpisodeWorkshopPaneHandle = {
  fetchEpisodes: () => Promise<void> | void
}

type InspectorTab = "film" | "text" | "sketch" | "material"

type H3RefImage = {
  id: string
  url: string
  name: string
  category?: string
}

// 新增/编辑分集弹窗表单（openEditModal 会整表 spread 分集数据）
type EpisodeFormState = {
  id: string
  episode_num: number | null
  title: string
  status: string
  script_text: string | null
  shots_count: number
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

const timeOptions = [
  { value: "日", label: "日间 (Day)" },
  { value: "夜", label: "夜间 (Night)" },
  { value: "清晨", label: "清晨 (Dawn)" },
  { value: "黄昏", label: "黄昏 (Dusk)" },
  { value: "室内", label: "室内 (Interior)" },
  { value: "室外", label: "室外 (Exterior)" },
]

const editableBeatFields = [
  "heading", "speaker", "dialogue", "action", "camera", "scene", "scene_id", "time_of_day",
  "characters", "character_ids", "character_look_id", "character_look_ids", "props", "prop_ids", "visual_prompt", "video_prompt_zh", "video_duration",
]

const TERMINAL_JOB_STATUSES = new Set(["completed", "succeeded", "failed", "cancelled", "interrupted"])
const SUCCEEDED_JOB_STATUSES = new Set(["completed", "succeeded"])

const EpisodeWorkshopPane = forwardRef<EpisodeWorkshopPaneHandle, EpisodeWorkshopPaneProps>(
  function EpisodeWorkshopPane({ csrfToken, projectId, episodeId, onDetailModeChange }, ref) {
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const { openMediaPreview } = useMediaPreview()

    // 剧集列表与当前选中的分集
    const [episodes, setEpisodes] = useState<Director2Episode[]>([])
    const [loading, setLoading] = useState(false)
    const [currentEpisodeId, setCurrentEpisodeId] = useState<string | null>(episodeId ?? null)
    const [currentEpisode, setCurrentEpisode] = useState<Director2EpisodeDetail | null>(null)
    const [refreshingDetail, setRefreshingDetail] = useState(false)
    const [regeneratingScript, setRegeneratingScript] = useState(false)
    const [generatingEpisodeVideo, setGeneratingEpisodeVideo] = useState(false)

    // 当前分集工作区 Tab: shots | script | dubbing | compose
    const [currentTab, setCurrentTab] = useState<WorkshopTabKey>(() => parseWorkshopTab(searchParams.get("tab")) || "shots")
    const [mixDubbing, setMixDubbing] = useState(true)
    const [composeBlockReason, setComposeBlockReason] = useState("")

    // 镜头工作台状态
    const [showSketch, setShowSketch] = useState(true)
    const [selectedBeatId, setSelectedBeatId] = useState<string | null>(null)
    const [checkedBeatIds, setCheckedBeatIds] = useState<Set<string>>(new Set())
    const [splitPct, setSplitPct] = useState(40)
    const splitRef = useRef<HTMLDivElement | null>(null)

    // 资产关联与选项
    const [projectAssets, setProjectAssets] = useState<Director2Asset[]>([])
    const projectCharacters = useMemo(() => projectAssets.filter((a) => a.kind === "character"), [projectAssets])
    const projectScenes = useMemo(() => projectAssets.filter((a) => a.kind === "scene"), [projectAssets])
    const projectProps = useMemo(() => projectAssets.filter((a) => a.kind === "prop"), [projectAssets])

    const characterOptions = useMemo(
      () => projectCharacters.map((c) => ({ value: c.name, label: c.name })),
      [projectCharacters],
    )
    const sceneOptions = useMemo(
      () => projectScenes.map((s) => {
        const hasMaster = Boolean(String(s.extra?.master_url || s.image_url || "").trim())
        const duplicate = projectScenes.filter((other) => other.name === s.name).length > 1
        let label = s.name
        if (!hasMaster) label = `${s.name}（无主视图）`
        else if (duplicate) label = `${s.name}（已生成）`
        return { value: s.id, label }
      }),
      [projectScenes],
    )

    const [inspectorTab, setInspectorTab] = useState<InspectorTab>("text")
    const [playbackMeasured, setPlaybackMeasured] = useState<MediaAspectSize>()

    // 各种生成 Loading 状态
    const [generatingBeatIds, setGeneratingBeatIds] = useState<Set<string>>(new Set())
    const [generatingRenderBeatIds, setGeneratingRenderBeatIds] = useState<Set<string>>(new Set())
    const [generatingTriptychBeatIds, setGeneratingTriptychBeatIds] = useState<Set<string>>(new Set())
    const [batchGenerating, setBatchGenerating] = useState(false)
    const [batchGeneratingRenders, setBatchGeneratingRenders] = useState(false)
    const [generatingVideo, setGeneratingVideo] = useState(false)
    const [upscalingBeatId, setUpscalingBeatId] = useState<string | null>(null)
    const [beatVideoProgress, setBeatVideoProgress] = useState<Record<string, WorkshopShotVideoProgress>>({})
    const [episodeVideoProgress, setEpisodeVideoProgress] = useState<WorkshopEpisodeVideoProgress | null>(null)
    const [composingEpisode, setComposingEpisode] = useState(false)
    const [currentSceneView, setCurrentSceneView] = useState<"front" | "reverse">("front")
    const [beatJobStates, setBeatJobStates] = useState<Map<string, string>>(new Map())
    const [h3RefImages, setH3RefImages] = useState<H3RefImage[]>([])
    const [h3ImagesExpanded, setH3ImagesExpanded] = useState(false)
    const [generatingH3Prompt, setGeneratingH3Prompt] = useState(false)
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
    const isDraggingRef = useRef(false)

    // 视频设置参数（来自 /api/modes 注册表，按项目记住）
    const [videoWorkflow, setVideoWorkflow] = useState(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW)
    const [videoWorkflows, setVideoWorkflows] = useState<Director2WorkflowMode[]>([])
    const [videoOptionFields, setVideoOptionFields] = useState(DIRECTOR2_VIDEO_FALLBACK_FIELDS)
    const [videoOptions, setVideoOptions] = useState(() => defaultVideoOptionValues(DIRECTOR2_VIDEO_FALLBACK_FIELDS))

    // 新增/编辑分集弹窗表单
    const [modalVisible, setModalVisible] = useState(false)
    const [isEdit, setIsEdit] = useState(false)
    const [submitting, setSubmitting] = useState(false)
    const [form, setForm] = useState<EpisodeFormState>({
      id: "",
      episode_num: 1,
      title: "",
      status: "draft",
      script_text: "",
      shots_count: 8,
    })

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
      applyVideoSettings(nextId, mode, videoOptions)
      if (episodeVideoRenderMode(mode) !== "shot") setCheckedBeatIds(new Set())
    }

    function handleVideoOptionChange(name: string, value: string) {
      const next = { ...videoOptions, [name]: value }
      setVideoOptions(next)
      saveVideoSettings(projectId, { workflow: videoWorkflow, ...next })
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

    function updateSelectedBeat(updater: (beat: WorkshopBeat) => WorkshopBeat) {
      mutateCurrentEpisode((ep) => {
        const target = resolveSelectedBeat(ep)
        if (!target) return ep
        return { ...ep, beats: (ep.beats || []).map((b) => (b.id === target.id ? updater(b) : b)) }
      })
    }

    function patchSelectedBeat(patch: Partial<WorkshopBeat>) {
      updateSelectedBeat((beat) => ({ ...beat, ...patch }))
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
      setPlaybackMeasured(undefined)
    }, [selectedBeat?.id])

    useEffect(() => {
      if (inspectorTab === "film" && !beatPlaybackUrl(selectedBeat)) setInspectorTab("text")
    }, [inspectorTab, selectedBeat?.id, selectedBeat?.video_url, selectedBeat?.upscaled_video_url])

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

    const episodeProtagonist = useMemo<Director2Asset | null>(() => {
      const beats = currentEpisode?.beats || []
      for (const beat of beats) {
        const assetId = beat.character_ids?.[0]
        const character = projectCharacters.find((item) => item.id === assetId)
        if (character) return character
      }
      return null
    }, [currentEpisode, projectCharacters])

    const selectedBeatCharacters = useMemo<Director2Asset[]>(() => {
      const ids = selectedBeat?.character_ids || []
      return ids
        .map((id) => projectCharacters.find((item) => item.id === id))
        .filter((item): item is Director2Asset => Boolean(item))
    }, [selectedBeat, projectCharacters])

    const sketchedCount = useMemo(() => {
      return (currentEpisode?.beats || []).filter((b) => Boolean(b.sketch_url)).length
    }, [currentEpisode])

    const h3PromptCount = useMemo(() => {
      return (currentEpisode?.beats || []).filter((b) => Boolean(String(b.h3_prompt || "").trim())).length
    }, [currentEpisode])
    const h3RefImagesVisible = h3ImagesExpanded ? h3RefImages : h3RefImages.slice(0, 3)
    const savedH3Prompt = String(selectedBeat?.h3_prompt || "")
    const h3PromptDirty = h3PromptDraft !== savedH3Prompt
    const h3Failed = Boolean(h3Live.failed) && !generatingH3Prompt
    const showH3Live = shouldShowWorkshopPromptLive({
      generating: generatingH3Prompt,
      failed: h3Failed,
      editing: h3PromptEditing,
      liveText: h3Live.text,
    })
    const h3VisionLine = workshopPromptAsideLine(h3JobMeta || selectedBeat, { failed: h3Failed })
    const showH3Editor = Boolean(h3PromptEditing || (!savedH3Prompt.trim() && !showH3Live))
    const h3StatusLabel = workshopH3StatusLabel({
      generating: generatingH3Prompt,
      failed: h3Failed,
      editing: h3PromptEditing,
      dirty: h3PromptDirty,
      savedPrompt: savedH3Prompt,
      source: selectedBeat?.h3_prompt_source,
    })
    const h3PromptCopyText = showH3Live
      ? h3Live.text
      : (showH3Editor ? h3PromptDraft : savedH3Prompt)
    const selectedTriptychGenerating = Boolean(selectedBeat?.id && generatingTriptychBeatIds.has(selectedBeat.id))
    const h3GenerateBusy = generatingH3Prompt || selectedTriptychGenerating
    const h3GenerateLabel = workshopH3GenerateLabel({
      generating: generatingH3Prompt,
      hasPrompt: Boolean(savedH3Prompt.trim()),
    })
    const playbackAspect = playbackAspectRatio(videoOptions)
    const playbackAspectSize = playbackMeasured || parseMediaAspect(playbackAspect)
    const playbackPortrait = Boolean(playbackAspectSize && playbackAspectSize.height > playbackAspectSize.width)
    const playbackAspectVars = mediaAspectVars(playbackAspectSize)
    const selectedBeatPlayback = beatPlaybackUrl(selectedBeat)

    const selectedVideoWorkflow = useMemo(
      () => videoWorkflows.find((item) => item.id === videoWorkflow) || videoWorkflows[0],
      [videoWorkflow, videoWorkflows],
    )
    const videoRenderMode = episodeVideoRenderMode(selectedVideoWorkflow)
    const videoWorkflowSelectOptions = useMemo(() => groupedVideoWorkflowOptions(videoWorkflows), [videoWorkflows])
    const episodeFilm = episodeFilmUrl(currentEpisode)
    const episodeSource = episodeFilmSource(currentEpisode)
    const videoReadyCount = shotVideoReadyCount(currentEpisode?.beats)
    const generatingVideoBeatIds = useMemo(() => new Set(Object.keys(beatVideoProgress)), [beatVideoProgress])
    const episodeVideoJobActive = Boolean(episodeVideoProgress)
    const selectedBeatVideoBusy = Boolean(
      selectedBeat && (generatingVideo || generatingVideoBeatIds.has(selectedBeat.id)),
    )
    const beatCount = currentEpisode?.beats?.length || 0
    const episodeDurationSec = useMemo(
      () => sumBeatDurationSec(currentEpisode?.beats || []),
      [currentEpisode],
    )
    const checkedBeatCount = useMemo(() => {
      const valid = new Set((currentEpisode?.beats || []).map((beat) => beat.id))
      return [...checkedBeatIds].filter((id) => valid.has(id)).length
    }, [checkedBeatIds, currentEpisode])
    const allBeatsChecked = beatCount > 0 && checkedBeatCount === beatCount
    const selectedBeatSplit = workshopBeatHasSplitTakes(selectedBeat, currentEpisode?.beats)

    const stats = useMemo(() => {
      const eps = episodes || []
      return {
        total: eps.length,
        ready: eps.filter((e) => e.status !== "draft").length,
        characters: projectCharacters.length,
        scenes: projectScenes.length,
        props: projectProps.length,
        beats: eps.reduce((sum, e) => sum + (e.shots_count || 0), 0),
      }
    }, [episodes, projectCharacters, projectScenes, projectProps])

    function getStatusColor(s: string): string {
      const map: Record<string, string> = { draft: "default", script_ready: "blue", scripting: "processing", sketching: "processing", sketched: "green" }
      return map[s] || "default"
    }

    function getStatusText(s: string): string {
      const map: Record<string, string> = { draft: "草稿", script_ready: "脚本就绪", scripting: "生成中", sketching: "出图中", sketched: "分镜完成" }
      return map[s] || s || "草稿"
    }

    function getEpisodeCharCount(ep: Director2Episode): number {
      return projectCharacters.length || 2
    }

    function getEpisodeSceneCount(ep: Director2Episode): number {
      return projectScenes.length || 1
    }

    function getCharName(cid: string): string {
      const c = projectCharacters.find((item) => item.id === cid)
      return c ? c.name : "角色"
    }

    function generationStatusText(beatId: string, stage: GenerationStage): string {
      const status = beatJobStates.get(`${stage}:${beatId}`)
      if (status === "queued") return "排队中"
      if (status === "preparing") return "准备素材"
      if (status === "storing") return "保存结果"
      if (status === "failed") return "生成失败"
      return status === "running" ? "生成中" : ""
    }

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
          setInspectorTab("material")
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
      } catch {
        message.error("加载剧集列表失败")
      } finally {
        setLoading(false)
      }
    }

    async function loadAssets() {
      try {
        const res = await listAssets(projectId)
        setProjectAssets(res || [])
      } catch (err) {
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
      setRefreshingDetail(true)
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
      } finally {
        setRefreshingDetail(false)
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

    // ---------------- 分镜数据编辑与保存 ----------------
    async function saveCurrentBeat(fields: string[] | null = null) {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat) return
      const episodeId = ep.id
      const beatId = beat.id
      const keys = Array.isArray(fields) ? fields : editableBeatFields
      const payload: Record<string, unknown> = {}
      keys.filter((key) => key in beat).forEach((key) => {
        payload[key] = (beat as unknown as Record<string, unknown>)[key]
      })
      try {
        await updateEpisodeBeat(csrfToken, projectId, episodeId, beatId, payload)
        message.success("分镜设定已同步保存")
      } catch {
        message.error("保存分镜失败")
      }
    }

    function onSceneSelectChange(val: string | undefined) {
      const beat = resolveSelectedBeat(currentEpisodeRef.current)
      if (!beat) return
      const s = projectScenes.find((item) => item.id === val)
      patchSelectedBeat({ scene_id: val, ...(s ? { scene: s.name } : {}) })
      saveCurrentBeat()
    }

    function toggleBeatCharacter(cid: string) {
      if (!resolveSelectedBeat(currentEpisodeRef.current)) return
      updateSelectedBeat((cur) => {
        const characterIds = [...(cur.character_ids || [])]
        const idx = characterIds.indexOf(cid)
        if (idx === -1) {
          characterIds.push(cid)
        } else {
          characterIds.splice(idx, 1)
        }
        const lookIds: Record<string, string> = { ...(cur.character_look_ids || {}) }
        if (idx !== -1) {
          delete lookIds[cid]
        }
        return {
          ...cur,
          character_ids: characterIds,
          character_look_ids: lookIds,
          ...(idx !== -1 && episodeProtagonist?.id === cid ? { character_look_id: undefined } : {}),
        }
      })
      saveCurrentBeat()
    }

    function onCharacterLookChange(characterId: string, lookId: string | undefined) {
      updateSelectedBeat((cur) => {
        const lookIds: Record<string, string> = { ...(cur.character_look_ids || {}) }
        if (lookId) lookIds[characterId] = lookId
        else delete lookIds[characterId]
        return {
          ...cur,
          character_look_ids: lookIds,
          ...(episodeProtagonist?.id === characterId ? { character_look_id: lookId || undefined } : {}),
        }
      })
      saveCurrentBeat(["character_look_id", "character_look_ids"])
    }

    function toggleBeatProp(pid: string) {
      if (!resolveSelectedBeat(currentEpisodeRef.current)) return
      updateSelectedBeat((cur) => {
        const propIds = [...(cur.prop_ids || [])]
        const idx = propIds.indexOf(pid)
        if (idx === -1) {
          propIds.push(pid)
        } else {
          propIds.splice(idx, 1)
        }
        return { ...cur, prop_ids: propIds }
      })
      saveCurrentBeat()
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

    async function generateSingleBeatSketch() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat) return
      const episodeId = ep.id
      if (stageSetHas("sketch", beat.id)) return
      addToStageSet("sketch", beat.id)
      try {
        const res = await generateBeatSketch(csrfToken, projectId, episodeId, beat.id, {
          scene_view: currentSceneView,
          force: true,
        })
        message.success(`Beat ${beat.sequence} 草图生成成功！`)
        applyBeatGenerationResult(episodeId, res, "sketch")
      } catch (err) {
        message.error(director2ErrorDetail(err, "草图生成失败"))
      } finally {
        deleteFromStageSet("sketch", beat.id)
      }
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
      if (options.fromPromptGate) {
        setInspectorTab("material")
      }
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

    async function generateSingleBeatRender() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat) return
      if (!beat.sketch_url) {
        message.warning("请先生成草图")
        return
      }
      const episodeId = ep.id
      if (stageSetHas("render", beat.id)) return
      addToStageSet("render", beat.id)
      try {
        const res = await generateBeatRender(csrfToken, projectId, episodeId, beat.id, {
          scene_view: currentSceneView,
          force: true,
        })
        message.success(`Beat ${beat.sequence} 渲染图生成成功！`)
        applyBeatGenerationResult(episodeId, res, "render")
      } catch (err) {
        message.error(director2ErrorDetail(err, "渲染图生成失败"))
      } finally {
        deleteFromStageSet("render", beat.id)
      }
    }

    async function handleBatchGenerateSketches() {
      const ep = currentEpisodeRef.current
      if (!ep?.beats?.length) return
      const unsketched = ep.beats.filter((b) => !b.sketch_url)
      if (!unsketched.length) {
        message.info("当前分集所有分镜草图已全部就绪！")
        return
      }
      setBatchGenerating(true)
      const episodeId = ep.id
      const batchBeatIds = new Set<string>()
      message.loading({ content: `开始批量生成 ${unsketched.length} 张草图...`, key: "batchGen" })
      try {
        for (const b of unsketched) {
          if (stageSetHas("sketch", b.id)) continue
          addToStageSet("sketch", b.id)
          batchBeatIds.add(b.id)
          try {
            const res = await generateBeatSketch(csrfToken, projectId, episodeId, b.id, {
              scene_view: currentSceneView,
              force: true,
            })
            applyBeatGenerationResult(episodeId, res, "sketch")
          } finally {
            deleteFromStageSet("sketch", b.id)
          }
        }
        message.success({ content: "批量草图生成完成！", key: "batchGen" })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "部分草图生成失败"), key: "batchGen" })
      } finally {
        setBatchGenerating(false)
        batchBeatIds.forEach((id) => deleteFromStageSet("sketch", id))
      }
    }

    async function handleBatchGenerateRenders() {
      const ep = currentEpisodeRef.current
      if (!ep?.beats?.length) return
      const pending = ep.beats.filter((b) => b.sketch_url && !b.render_url)
      if (!pending.length) {
        const missingSketch = ep.beats.filter((b) => !b.sketch_url).length
        message.info(missingSketch ? "请先为分镜生成草图，再批量生成渲染图" : "当前分集渲染图已全部就绪")
        return
      }
      setBatchGeneratingRenders(true)
      const episodeId = ep.id
      const batchBeatIds = new Set<string>()
      message.loading({ content: `开始批量生成 ${pending.length} 张渲染图...`, key: "batchRender" })
      try {
        for (const b of pending) {
          if (stageSetHas("render", b.id)) continue
          addToStageSet("render", b.id)
          batchBeatIds.add(b.id)
          try {
            const res = await generateBeatRender(csrfToken, projectId, episodeId, b.id, {
              scene_view: currentSceneView,
              force: true,
            })
            applyBeatGenerationResult(episodeId, res, "render")
          } finally {
            deleteFromStageSet("render", b.id)
          }
        }
        message.success({ content: "批量渲染图生成完成！", key: "batchRender" })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "部分渲染图生成失败"), key: "batchRender" })
      } finally {
        setBatchGeneratingRenders(false)
        batchBeatIds.forEach((id) => deleteFromStageSet("render", id))
      }
    }

    async function enqueueSingleSketch() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat || stageSetHas("sketch", beat.id)) return
      addToStageSet("sketch", beat.id)
      try {
        const res = await generateBeatSketch(csrfToken, projectId, ep.id, beat.id, {
          scene_view: currentSceneView, force: true,
        })
        updateBeatById(beat.id, { sketch_job_id: res.job_id })
        message.success(`Beat ${beat.sequence} 草图任务已提交`)
      } catch (err) {
        deleteFromStageSet("sketch", beat.id)
        message.error(director2ErrorDetail(err, "草图任务提交失败"))
      }
    }

    async function enqueueSingleRender() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat || stageSetHas("render", beat.id)) return
      if (!beat.sketch_url) {
        message.warning("请先生成草图")
        return
      }
      addToStageSet("render", beat.id)
      try {
        const res = await generateBeatRender(csrfToken, projectId, ep.id, beat.id, {
          scene_view: currentSceneView, force: true,
        })
        updateBeatById(beat.id, { render_job_id: res.job_id, render_status: res.status })
        message.success(`Beat ${beat.sequence} 渲染图任务已提交`)
      } catch (err) {
        deleteFromStageSet("render", beat.id)
        message.error(director2ErrorDetail(err, "渲染图任务提交失败"))
      }
    }

    async function enqueueBatch(stage: GenerationStage) {
      const ep = currentEpisodeRef.current
      if (!ep?.beats?.length) return
      const candidates = stage === "sketch"
        ? ep.beats.filter((beat) => !beat.sketch_url && !stageSetHas("sketch", beat.id))
        : ep.beats.filter((beat) => beat.sketch_url && !beat.render_url && !stageSetHas("render", beat.id))
      if (!candidates.length) {
        message.info(stage === "sketch" ? "当前分集没有待生成草图" : "当前分集没有可生成的渲染图")
        return
      }
      const messageKey = stage === "sketch" ? "batchGen" : "batchRender"
      if (stage === "sketch") setBatchGenerating(true)
      else setBatchGeneratingRenders(true)
      message.loading({ content: `正在提交 ${candidates.length} 个任务...`, key: messageKey })
      try {
        const res = await generateBeatImagesBatch(csrfToken, projectId, ep.id, {
          stage, beat_ids: candidates.map((beat) => beat.id), scene_view: currentSceneView, force: true,
        })
        res.jobs.forEach((job: Record<string, any>) => addToStageSet(stage, job.beat_id))
        trackedBatchJobsRef.current.set(stage, new Set<string>(res.jobs.map((job: Record<string, any>) => job.job_id)))
        message.success({
          content: `已提交 ${res.jobs.length} 个任务${res.skipped.length ? `，跳过 ${res.skipped.length} 个` : ""}`,
          key: messageKey,
        })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "批量任务提交失败"), key: messageKey })
      } finally {
        if (stage === "sketch") setBatchGenerating(false)
        else setBatchGeneratingRenders(false)
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
        const nextBeatJobStates = new Map<string, string>()
        episodeJobs.forEach((job) => {
          const stage = job.payload?.target_type === "beat_sketch"
            ? "sketch"
            : job.payload?.target_type === "beat_render"
              ? "render"
              : job.payload?.target_type === "beat_triptych"
                ? "triptych"
                : ""
          if (stage) {
            const key = `${stage}:${job.payload.beat_id}`
            if (!nextBeatJobStates.has(key)) nextBeatJobStates.set(key, job.status)
            if (activeStatuses.has(job.status)) {
              if (stage === "sketch") nextSketchIds.add(job.payload.beat_id)
              if (stage === "render") nextRenderIds.add(job.payload.beat_id)
              if (stage === "triptych") nextTriptychIds.add(job.payload.beat_id)
            }
          }
        })
        const videoProgress = mapWorkshopVideoProgress(jobs, epId)
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
        setBeatJobStates(nextBeatJobStates)
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
            const composed = relevant.some((job) => String(job.payload?.render_scope || "") === "compose")
            if (failed) {
              message.warning(composed ? `合成完成：成功 ${completed}，失败 ${failed}` : `视频任务完成：成功 ${completed}，失败 ${failed}`)
            } else {
              message.success(composed ? "分集成片已合成" : "视频任务已完成，成片已写入本集")
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

    function toggleSceneBackground() {
      const next = currentSceneView === "front" ? "reverse" : "front"
      setCurrentSceneView(next)
      message.info(`已切换场景机位视角：${next === "front" ? "正面源图" : "背面反打"}`)
    }

    function handleUploadSketch(file: File): boolean {
      const reader = new FileReader()
      reader.onload = (e) => {
        const beat = resolveSelectedBeat(currentEpisodeRef.current)
        if (beat) {
          updateBeatById(beat.id, { sketch_url: (e.target?.result as string) || "" })
          saveCurrentBeat(["sketch_url"])
          message.success("已替换分镜草图")
        }
      }
      reader.readAsDataURL(file)
      return false
    }

    function handleUploadRender(file: File): boolean {
      const reader = new FileReader()
      reader.onload = (e) => {
        const beat = resolveSelectedBeat(currentEpisodeRef.current)
        if (beat) {
          updateBeatById(beat.id, { render_url: (e.target?.result as string) || "" })
          saveCurrentBeat(["render_url"])
          message.success("已上传高精渲染图")
        }
      }
      reader.readAsDataURL(file)
      return false
    }

    function generateVideoPrompt() {
      const beat = resolveSelectedBeat(currentEpisodeRef.current)
      if (!beat) return
      const action = beat.action || beat.heading
      patchSelectedBeat({ video_prompt_zh: `${action}，电影级流畅运镜，景深层次逼真流动` })
      saveCurrentBeat(["video_prompt_zh"])
      message.success("已自动提炼视频运镜提示词")
    }

    async function handleGenerateVideo() {
      const ep = currentEpisodeRef.current
      const beat = resolveSelectedBeat(ep)
      if (!ep || !beat) return
      setGeneratingVideo(true)
      try {
        message.loading({ content: "正在提交单镜视频任务...", key: "vGen" })
        const res = await generateBeatVideo(csrfToken, projectId, ep.id, beat.id, buildVideoJobOptions(
          videoWorkflow,
          videoOptions,
          { duration_per_beat: beatDurationSec(beat.video_duration) },
        ))
        rememberVideoJobIds([res.job_id])
        message.success({ content: `单镜任务已进入队列：${res.job_id}`, key: "vGen", duration: 6 })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "单镜视频任务创建失败"), key: "vGen", duration: 10 })
      } finally {
        setGeneratingVideo(false)
      }
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
        message.loading({ content: "正在提交 2x 超分...", key: "vUpscale" })
        const res = await upscaleBeatVideo(
          csrfToken,
          projectId,
          ep.id,
          beat.id,
          buildVideoJobOptions(videoWorkflow, videoOptions),
        )
        rememberVideoJobIds([res.job_id])
        message.success({ content: `超分任务已进入队列：${res.job_id}`, key: "vUpscale", duration: 6 })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "超分任务创建失败"), key: "vUpscale", duration: 10 })
      } finally {
        setUpscalingBeatId(null)
      }
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

    async function handleGenerateEpisodeVideo() {
      const ep = currentEpisodeRef.current
      if (!ep || generatingEpisodeVideo) return
      setGeneratingEpisodeVideo(true)
      try {
        const res = await generateEpisodeVideo(
          csrfToken,
          projectId,
          ep.id,
          buildVideoJobOptions(videoWorkflow, videoOptions),
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
      const beatIds = (ep.beats || [])
        .map((beat) => beat.id)
        .filter((id) => checkedBeatIds.has(id))
      if (!beatIds.length) {
        message.warning("请先勾选要生成的镜头")
        return
      }
      setGeneratingEpisodeVideo(true)
      try {
        const res = await generateEpisodeVideo(
          csrfToken,
          projectId,
          ep.id,
          buildVideoJobOptions(videoWorkflow, videoOptions, selectedShotGenerateExtra(beatIds)),
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

    async function handleComposeEpisode() {
      const ep = currentEpisodeRef.current
      if (!ep || composingEpisode) return
      if (composeBlockReason) {
        message.warning(composeBlockReason)
        return
      }
      setComposingEpisode(true)
      try {
        const res = await composeEpisodeVideo(csrfToken, projectId, ep.id, { mix_dubbing: mixDubbing })
        rememberVideoJobIds([res.job_id])
        message.success({ content: "合成任务已进入队列，可在「全部任务 → 视频生成」中查看进度", duration: 6 })
      } catch (err) {
        message.error({ content: director2ErrorDetail(err, "合成任务创建失败"), duration: 10 })
      } finally {
        setComposingEpisode(false)
      }
    }

    function handleToolNotice(name: string) {
      message.info(`已开启「${name}」模式`)
    }

    useEffect(() => {
      const tab = parseWorkshopTab(searchParams.get("tab"))
      if (tab) setCurrentTab(tab)
    }, [searchParams])

    useEffect(() => {
      if (currentTab !== "compose" || !currentEpisodeId) {
        setComposeBlockReason("")
        return
      }
      let cancelled = false
      void getEpisodeDubbing(projectId, currentEpisodeId)
        .then((track) => {
          if (!cancelled) setComposeBlockReason(track.compose_block_reason || "")
        })
        .catch(() => {
          if (!cancelled) setComposeBlockReason("")
        })
      return () => {
        cancelled = true
      }
    }, [currentTab, currentEpisodeId, projectId])

    // ---------------- 左右拖拽调节分栏 ----------------
    // 经 ref 转发保持监听器注册/移除一致（等价 Vue 的稳定函数引用）
    const onDraggingRef = useRef<(e: MouseEvent) => void>(() => {})
    const onStopDraggingRef = useRef<() => void>(() => {})

    function onDragging(e: MouseEvent) {
      if (!isDraggingRef.current || !splitRef.current) return
      const rect = splitRef.current.getBoundingClientRect()
      const offset = e.clientX - rect.left
      const pct = Math.max(25, Math.min(65, (offset / rect.width) * 100))
      setSplitPct(pct)
    }
    onDraggingRef.current = onDragging

    function stopDragging() {
      isDraggingRef.current = false
      document.removeEventListener("mousemove", onDraggingRef.current)
      document.removeEventListener("mouseup", onStopDraggingRef.current)
    }
    onStopDraggingRef.current = stopDragging

    function startDragging() {
      isDraggingRef.current = true
      document.addEventListener("mousemove", onDraggingRef.current)
      document.addEventListener("mouseup", onStopDraggingRef.current)
    }

    // ---------------- 新建/修改分集弹窗 ----------------
    function openCreateModal() {
      setIsEdit(false)
      setForm({
        id: "",
        episode_num: episodes.length + 1,
        title: `第 ${episodes.length + 1} 集`,
        status: "draft",
        script_text: "",
        shots_count: 6,
      })
      setModalVisible(true)
    }

    function openEditModal(ep: Director2Episode) {
      setIsEdit(true)
      setForm({ ...ep })
      setModalVisible(true)
    }

    async function handleSubmit() {
      if (!form.title.trim()) {
        message.warning("请输入分集标题")
        return
      }
      setSubmitting(true)
      try {
        if (isEdit) {
          await updateEpisode(csrfToken, projectId, form.id, form)
          message.success("分集已更新")
        } else {
          await createEpisode(csrfToken, projectId, form)
          message.success("分集已创建")
        }
        setModalVisible(false)
        await fetchEpisodes()
      } catch {
        message.error("操作失败")
      } finally {
        setSubmitting(false)
      }
    }

    async function handleDeleteEpisode(id: string) {
      try {
        await deleteEpisode(csrfToken, projectId, id)
        message.success("分集已删除")
        await fetchEpisodes()
      } catch {
        message.error("删除失败")
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
        stopDragging()
        clearPollTimer()
      }
      // 对应原版 onMounted + onUnmounted
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
      let cancelled = false
      const saved = loadSavedVideoSettings(projectId)
      ;(async () => {
        try {
          const payload = await listVideoWorkflowModes()
          if (cancelled) return
          const workflows = timelineVideoWorkflows(payload.modes)
          setVideoWorkflows(workflows)
          const requested = saved?.workflow || videoWorkflow
          const selected = workflows.find((item) => item.id === requested) || workflows[0]
          applyVideoSettings(selected?.id || DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, selected, saved)
        } catch {
          if (cancelled) return
          applyVideoSettings(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, undefined, saved)
        }
      })()
      return () => {
        cancelled = true
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
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

    return (
      <div className={`d2-episode-workshop workshop-container${currentEpisodeId ? " in-episode-detail" : ""}`}>
        {/* ==================== 层级 1: 剧集工坊概览列表 (xiaji-workshop) ==================== */}
        {!currentEpisodeId ? (
          <div className="xiaji-workshop">
            <header className="xiaji-workshop-hero">
              <span className="xiaji-ingest-hero-icon" aria-hidden="true">
                <Clapperboard size={20} />
              </span>
              <div className="hero-text-col">
                <h1>剧集工坊</h1>
                <p>把内容库规划落成剧集，生成脚本 Beat，再按镜头出草图与视频。</p>
              </div>
              <Space>
                <Button loading={loading} icon={<RefreshCw size={14} />} onClick={() => fetchEpisodes()}>
                  刷新
                </Button>
                <Button type="primary" className="primary-action-btn" icon={<Plus size={15} />} onClick={openCreateModal}>
                  新增分集
                </Button>
              </Space>
            </header>

            {/* 统计栏 (对齐 source1) */}
            <div className="xiaji-workshop-stats">
              <span>总集数 <strong>{stats.total}</strong></span>
              <span>已就绪脚本 <strong>{stats.ready}</strong></span>
              <span>出场身份 <strong>{stats.characters}</strong></span>
              <span>规划场景 <strong>{stats.scenes}</strong></span>
              <span>关键道具 <strong>{stats.props}</strong></span>
              <span>规划 Beat 分镜 <strong>{stats.beats}</strong></span>
            </div>

            {/* 列表内容区 */}
            <Spin spinning={loading}>
              {episodes.length === 0 ? (
                <div className="empty-workshop-box">
                  <Film size={48} className="empty-icon" />
                  <h3>暂无编排剧集</h3>
                  <p>可直接在上方新增剧集，或在「内容库」导入剧本后一键同步各集分镜。</p>
                  <Button type="primary" onClick={openCreateModal}>新增第 1 集</Button>
                </div>
              ) : (
                <div className="xiaji-episode-grid">
                  {episodes.map((ep) => (
                    <div
                      key={ep.id}
                      className="xiaji-episode-card"
                      onClick={() => openEpisodeDetail(ep.id)}
                    >
                      <div className="card-head">
                        <strong className="card-title">第 {ep.episode_num} 集 · {ep.title}</strong>
                        <Tag color={getStatusColor(ep.status)}>{getStatusText(ep.status)}</Tag>
                      </div>
                      <p className="card-summary">
                        {ep.script_text ? ep.script_text.replace(/[#\n-]/g, " ").slice(0, 85) + "..." : "暂未编排镜头对白内容"}
                      </p>
                      <div className="card-footer">
                        <em className="card-meta">
                          {ep.shots_count || 0} 个分镜 · {getEpisodeCharCount(ep)} 身份 · {getEpisodeSceneCount(ep)} 场景
                        </em>
                        <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                          <Button type="link" size="small" onClick={() => openEditModal(ep)}>
                            修改分集
                          </Button>
                          <Popconfirm
                            title="确定删除此集？"
                            okText="删除"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                            onConfirm={() => handleDeleteEpisode(ep.id)}
                          >
                            <Button type="link" danger size="small">删除</Button>
                          </Popconfirm>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Spin>
          </div>
        ) : currentEpisode ? (
          /* ==================== 层级 2: 分集详细工作区 (完全对齐 source1 EpisodeWorkspace) ==================== */
          <div className="xiaji-episode">
            {/* 顶部 Header 导航条 */}
            <header className="xiaji-episode-head">
              <div className="xiaji-episode-head-main">
                <div className="xiaji-episode-head-title">
                  <Button className="back-btn" icon={<ArrowLeft size={14} />} onClick={() => handleBackToOverview()}>
                    返回概览
                  </Button>
                  <h2>第 {currentEpisode.number} 集 {currentEpisode.title}</h2>
                  <Tag color={getStatusColor(currentEpisode.status)}>{getStatusText(currentEpisode.status)}</Tag>
                </div>
                <p className="episode-meta-line">
                  {currentEpisode.line_count || (currentEpisode.beats?.length || 0) * 4} 行原文 ·{" "}
                  {currentEpisode.beats?.length || 0} 个 Beat 分镜 · 共 {episodeDurationSec} 秒 ·{" "}
                  {currentEpisode.character_count || 0} 个身份 ·{" "}
                  {currentEpisode.scene_count || 0} 个场景 ·{" "}
                  {currentEpisode.prop_count || 0} 个道具
                </p>
              </div>

              <Space className="xiaji-episode-head-actions">
                <Director2VideoSettingsPopover
                  workflowId={videoWorkflow}
                  workflows={videoWorkflows}
                  fields={videoOptionFields}
                  values={videoOptions}
                  onWorkflowChange={handleVideoWorkflowChange}
                  onChange={handleVideoOptionChange}
                />
                <Button loading={generatingEpisodeVideo || episodeVideoJobActive} icon={<Video size={14} />} onClick={() => handleGenerateEpisodeVideo()}>
                  一键生成视频
                </Button>
                <Button loading={refreshingDetail} icon={<RefreshCw size={14} />} onClick={() => refreshCurrentEpisode()}>
                  刷新数据
                </Button>
                <Button type="primary" loading={regeneratingScript} icon={<Sparkles size={14} />} onClick={() => handleRegenerateScript()}>
                  重新生成脚本
                </Button>
              </Space>
            </header>

            {/* 四大核心 Tab: 镜头 | 剧本 | 配音 | 合成 */}
            <Tabs
              activeKey={currentTab}
              onChange={(key) => {
                const next = (parseWorkshopTab(key) || "shots") as WorkshopTabKey
                setCurrentTab(next)
                setSearchParams((prev) => {
                  const params = new URLSearchParams(prev)
                  if (next === "shots") params.delete("tab")
                  else params.set("tab", next)
                  return params
                }, { replace: true })
              }}
              className="episode-tabs"
              items={[
                /* ==================== Tab 1: 🎬 镜头工作台 (XiajiShotsWorkbench) ==================== */
                {
                  key: "shots",
                  label: "🎬 镜头",
                  children: (
                    <div className="xiaji-shots-workbench">
                      {/* 镜头工具条 */}
                      <div className="xiaji-shots-toolbar">
                        <div className="toolbar-left">
                          <Checkbox checked={showSketch} onChange={(e) => setShowSketch(e.target.checked)}>显示草图</Checkbox>
                          <Checkbox
                            checked={allBeatsChecked}
                            indeterminate={checkedBeatCount > 0 && !allBeatsChecked}
                            onChange={(e) => toggleCheckAllBeats(e.target.checked)}
                          >
                            全选（共 {beatCount} 镜）
                          </Checkbox>
                          <span className="sketched-count-label">已选 {checkedBeatCount} / {beatCount} 镜</span>
                          <Button
                            type="link"
                            size="small"
                            disabled={!checkedBeatCount}
                            onClick={() => setCheckedBeatIds(new Set())}
                          >
                            清空
                          </Button>
                          <span className="sketched-count-label">
                            {sketchedCount}/{currentEpisode.beats?.length || 0} 张草图 ·{" "}
                            {h3PromptCount}/{currentEpisode.beats?.length || 0} 条 H3 提示词
                            {` · ${videoReadyCount}/${beatCount} 镜视频`}
                          </span>
                        </div>
                        <div className="toolbar-right">
                          <Button
                            type="primary"
                            size="small"
                            loading={generatingEpisodeVideo}
                            disabled={!checkedBeatCount}
                            icon={<Video size={13} />}
                            onClick={() => handleGenerateSelectedShots()}
                          >
                            生成选中（{checkedBeatCount}）
                          </Button>
                          <Button
                            type="primary"
                            size="small"
                            loading={batchGenerating}
                            icon={<Sparkles size={13} />}
                            onClick={() => enqueueBatch("sketch")}
                          >
                            批量生成分镜草图
                          </Button>
                        </div>
                      </div>

                      {/* 分栏布局：左侧缩略图卡片网格 + 右侧检视器 */}
                      <div ref={splitRef} className="xiaji-shots-split">
                        {/* 左侧分镜卡片栅格 (BeatGrid) */}
                        <div className="xiaji-shots-grid-pane" style={{ flex: `0 0 ${splitPct}%` }}>
                          <div className="xiaji-shot-tiles">
                            {(currentEpisode.beats || []).map((beat) => {
                              const videoProgress = beatVideoProgress[beat.id]
                              return (
                              <div
                                key={beat.id}
                                className={`xiaji-shot-tile${selectedBeat?.id === beat.id ? " is-selected" : ""}${checkedBeatIds.has(beat.id) ? " is-checked" : ""}`}
                              >
                                <div className="xiaji-shot-tile-head">
                                  <Checkbox
                                    checked={checkedBeatIds.has(beat.id)}
                                    aria-label={`勾选 ${workshopBeatLabel(beat)}`}
                                    onClick={(event) => event.stopPropagation()}
                                    onChange={(event) => toggleCheckedBeat(beat, event.target.checked)}
                                  />
                                  <button
                                    type="button"
                                    className="xiaji-shot-tile-select"
                                    onClick={() => selectBeat(beat)}
                                  >
                                    <span className="xiaji-shot-tile-identity">
                                      <span className="xiaji-shot-tile-num">{workshopBeatLabel(beat)}</span>
                                      <em className="xiaji-shot-tile-duration">{formatBeatDurationLabel(beat.video_duration)}</em>
                                    </span>
                                    {beat.video_url || videoProgress ? (
                                      <span className="xiaji-shot-tile-flags">
                                        {beat.video_url ? <em className="xiaji-shot-tile-ready">已出片</em> : null}
                                        {beatHasUpscaled(beat) ? <em className="xiaji-shot-tile-upscaled">2x</em> : null}
                                        {videoProgress ? (
                                          <em className="xiaji-shot-tile-busy-label">
                                            {workshopVideoPercentLabel(videoProgress.progress)}
                                          </em>
                                        ) : null}
                                      </span>
                                    ) : null}
                                  </button>
                                </div>
                                <button
                                  type="button"
                                  className="xiaji-shot-tile-body"
                                  onClick={() => selectBeat(beat)}
                                >
                                  <div className="xiaji-shot-tile-media">
                                    {showSketch && beat.sketch_url ? (
                                      <img
                                        src={beat.sketch_url}
                                        alt={workshopBeatLabel(beat)}
                                      />
                                    ) : generatingBeatIds.has(beat.id) || generatingRenderBeatIds.has(beat.id) ? (
                                      <div className="xiaji-shot-tile-busy">
                                        <Spin size="small" />
                                        <em>{generationStatusText(beat.id, generatingBeatIds.has(beat.id) ? "sketch" : "render") || "GRS 生成中"}</em>
                                      </div>
                                    ) : (
                                      <div className="shot-tile-empty">
                                        <ImageIcon size={24} />
                                      </div>
                                    )}
                                    {videoProgress ? (
                                      <div
                                        className="xiaji-shot-tile-video-progress"
                                        role="status"
                                        aria-label={`视频${workshopVideoOverlayLabel(videoProgress.status, videoProgress.progress, videoProgress)}`}
                                      >
                                        <Progress
                                          percent={videoProgress.progress}
                                          size="small"
                                          status="active"
                                          showInfo={false}
                                          strokeColor="var(--studio-primary)"
                                          trailColor="var(--studio-border-strong)"
                                          aria-label={`视频进度 ${workshopVideoPercentLabel(videoProgress.progress)}`}
                                        />
                                        <em className="xiaji-shot-tile-video-progress-label">
                                          {workshopVideoOverlayLabel(videoProgress.status, videoProgress.progress, videoProgress)}
                                        </em>
                                      </div>
                                    ) : null}
                                  </div>
                                  <p className="tile-caption" title={beat.action || beat.dialogue || beat.heading}>
                                    {beat.dialogue ? `「${beat.speaker || "对白"}」${beat.dialogue}` : (beat.action || beat.heading || "未填写画面描述")}
                                  </p>
                                </button>
                              </div>
                              )
                            })}
                          </div>
                        </div>

                        {/* 分栏手柄 (Gutter) */}
                        <div
                          className="xiaji-shots-gutter"
                          onMouseDown={() => startDragging()}
                        />

                        {/* 右侧分镜检视器 (Inspector) */}
                        <div className="xiaji-shots-detail">
                          {selectedBeat ? (
                            <div className="xiaji-shot-pane-container">
                              {/* 顶部 Header 状态栏 */}
                              <div className="xiaji-shot-pane-topbar">
                                <span className="topbar-title">
                                  {workshopBeatLabel(selectedBeat)} 镜头检视
                                  <em className="topbar-duration">{formatBeatDurationZh(selectedBeat.video_duration)}</em>
                                </span>
                                <Space size="small">
                                  <Tooltip title={beatUpscaleDisabledReason(selectedBeat, beatVideoProgress[selectedBeat.id]) || "用本机 RTX 放大到 2 倍，原片保留"}>
                                    <Button
                                      size="small"
                                      disabled={Boolean(beatUpscaleDisabledReason(selectedBeat, beatVideoProgress[selectedBeat.id])) || upscalingBeatId === selectedBeat.id}
                                      loading={upscalingBeatId === selectedBeat.id || beatVideoProgress[selectedBeat.id]?.scope === "upscale" || beatVideoProgress[selectedBeat.id]?.status === "upscaling"}
                                      onClick={() => void handleUpscaleBeat(selectedBeat)}
                                      aria-label="2x 超分"
                                    >
                                      超分
                                    </Button>
                                  </Tooltip>
                                  <button type="button" className="xiaji-pane-btn" onClick={() => saveCurrentBeat()}>
                                    <Check size={12} />
                                    <span>保存设定</span>
                                  </button>
                                  <button type="button" className="xiaji-pane-btn" onClick={() => refreshCurrentEpisode()}>
                                    <RefreshCw size={12} />
                                    <span>重建索引</span>
                                  </button>
                                </Space>
                              </div>

                              <Tabs
                                className="xiaji-inspector-tabs"
                                activeKey={inspectorTab}
                                onChange={(key) => {
                                  if (key === "film" || key === "text" || key === "sketch" || key === "material") {
                                    setInspectorTab(key)
                                  }
                                }}
                                tabBarExtraContent={inspectorTab === "material" && selectedBeatSplit ? (
                                  <Button
                                    size="small"
                                    disabled={h3GenerateBusy}
                                    onClick={() => requestMergeH3Prompt()}
                                  >
                                    合并为一条生成
                                  </Button>
                                ) : null}
                                items={[
                                  ...(selectedBeatPlayback ? [{
                                    key: "film",
                                    label: (
                                      <span className="xiaji-inspector-tab-label">
                                        <Film size={14} />
                                        成片
                                        <span className="status-chip is-active">
                                          <span className="chip-dot" /> {beatHasUpscaled(selectedBeat) ? "2x" : "已出片"}
                                        </span>
                                      </span>
                                    ),
                                    children: (
                                      <div className="xiaji-inspector-pane is-film">
                                        <div className={`xiaji-shot-playback is-stage${playbackPortrait ? " is-portrait" : " is-landscape"}`}>
                                          <div
                                            className="xiaji-shot-playback-frame"
                                            style={playbackAspectVars as CSSProperties}
                                          >
                                            <video
                                              src={selectedBeatPlayback}
                                              controls
                                              playsInline
                                              preload="metadata"
                                              onLoadedMetadata={(event) => {
                                                const width = event.currentTarget.videoWidth
                                                const height = event.currentTarget.videoHeight
                                                if (width > 0 && height > 0) setPlaybackMeasured({ width, height })
                                              }}
                                            />
                                            <button
                                              type="button"
                                              className="xiaji-shot-playback-expand"
                                              aria-label="放大预览成片"
                                              onClick={() => openMediaPreview({
                                                src: selectedBeatPlayback,
                                                kind: "video",
                                                title: `${workshopBeatLabel(selectedBeat)} 成片`,
                                                description: beatHasUpscaled(selectedBeat) ? "正在播放 2x 超分，原片仍保留" : "本镜成片",
                                                aspectRatio: playbackAspect,
                                              })}
                                            >
                                              <Maximize2 size={14} />
                                            </button>
                                          </div>
                                          <div className="xiaji-shot-playback-meta">
                                            <p>{beatHasUpscaled(selectedBeat) ? "正在播放 2x 超分，原片仍保留" : "本镜成片"}</p>
                                            <Button
                                              size="small"
                                              icon={<Maximize2 size={12} />}
                                              onClick={() => openMediaPreview({
                                                src: selectedBeatPlayback,
                                                kind: "video",
                                                title: `${workshopBeatLabel(selectedBeat)} 成片`,
                                                description: beatHasUpscaled(selectedBeat) ? "正在播放 2x 超分，原片仍保留" : "本镜成片",
                                                aspectRatio: playbackAspect,
                                              })}
                                            >
                                              放大
                                            </Button>
                                          </div>
                                        </div>
                                      </div>
                                    ),
                                  }] : []),
                                  {
                                    key: "text",
                                    label: (
                                      <span className="xiaji-inspector-tab-label">
                                        <FileText size={14} />
                                        文案
                                        <span className="status-chip is-active">
                                          <span className="chip-dot" /> 已同步
                                        </span>
                                      </span>
                                    ),
                                    children: (
                                    <div className="xiaji-inspector-pane">
                                    <div className="xiaji-shot-form">
                                      {/* 对白台词 */}
                                      <div className="form-group">
                                        <label className="form-label">台词对白 (Dialogue)</label>
                                        <Input.TextArea
                                          value={selectedBeat.dialogue || ""}
                                          rows={3}
                                          placeholder="输入对白台词..."
                                          onChange={(e) => patchSelectedBeat({ dialogue: e.target.value })}
                                          onBlur={() => saveCurrentBeat()}
                                        />
                                      </div>

                                      {/* 说话人 + 景别机位 */}
                                      <div className="form-row-two">
                                        <div className="form-group">
                                          <label className="form-label">说话人 (Speaker)</label>
                                          <Select
                                            value={selectedBeat.speaker || undefined}
                                            allowClear
                                            placeholder="选择说话人"
                                            options={characterOptions}
                                            onChange={(value: string | undefined) => {
                                              patchSelectedBeat({ speaker: value })
                                              saveCurrentBeat()
                                            }}
                                          />
                                        </div>
                                        <div className="form-group">
                                          <label className="form-label">景别机位 (Camera)</label>
                                          <Input.TextArea
                                            value={selectedBeat.camera || ""}
                                            rows={3}
                                            placeholder="输入景别、机位与运镜..."
                                            onChange={(e) => patchSelectedBeat({ camera: e.target.value })}
                                            onBlur={() => saveCurrentBeat()}
                                          />
                                        </div>
                                      </div>

                                      {/* 场景环境 + 时间氛围 */}
                                      <div className="form-row-two">
                                        <div className="form-group">
                                          <label className="form-label">场景环境 (Scene)</label>
                                          <Select
                                            value={selectedBeat.scene_id || undefined}
                                            allowClear
                                            placeholder="选择关联场景"
                                            options={sceneOptions}
                                            onChange={(value: string | undefined) => onSceneSelectChange(value)}
                                          />
                                        </div>
                                        <div className="form-group">
                                          <label className="form-label">时间氛围 (Time)</label>
                                          <Select
                                            value={selectedBeat.time_of_day || undefined}
                                            allowClear
                                            placeholder="日 / 夜 / 晨 / 昏"
                                            options={timeOptions}
                                            onChange={(value: string | undefined) => {
                                              patchSelectedBeat({ time_of_day: value })
                                              saveCurrentBeat()
                                            }}
                                          />
                                        </div>
                                      </div>

                                      <div className="form-row-two">
                                        <div className="form-group">
                                          <label className="form-label">镜头时长 (Duration)</label>
                                          <InputNumber
                                            min={2}
                                            max={15}
                                            value={beatDurationSec(selectedBeat.video_duration)}
                                            addonAfter="秒"
                                            style={{ width: "100%" }}
                                            onChange={(value) => patchSelectedBeat({ video_duration: String(beatDurationSec(value)) })}
                                            onBlur={() => saveCurrentBeat()}
                                          />
                                        </div>
                                        <div className="form-group">
                                          <label className="form-label">场景与镜头标题 (Heading)</label>
                                          <Input
                                            value={selectedBeat.heading || ""}
                                            placeholder="如：现代大学图书馆夜景 · 中景"
                                            onChange={(e) => patchSelectedBeat({ heading: e.target.value })}
                                            onBlur={() => saveCurrentBeat()}
                                          />
                                        </div>
                                      </div>

                                      {/* 画面动作描述 Action */}
                                      <div className="form-group">
                                        <label className="form-label">画面动作与视觉描述 (Action)</label>
                                        <Input.TextArea
                                          value={selectedBeat.action || ""}
                                          rows={4}
                                          placeholder="描述画面中角色动作、神态与空间视觉细节..."
                                          onChange={(e) => patchSelectedBeat({ action: e.target.value })}
                                          onBlur={() => saveCurrentBeat()}
                                        />
                                      </div>

                                      {/* 出场身份 Chips */}
                                      <div className="form-group">
                                        <label className="form-label">出场身份 (Characters)</label>
                                        <div className="chips-flex-row">
                                          {projectCharacters.map((c) => (
                                            <button
                                              key={c.id}
                                              type="button"
                                              className={`xiaji-ref-chip${selectedBeat.character_ids?.includes(c.id) ? " is-on" : ""}`}
                                              onClick={() => toggleBeatCharacter(c.id)}
                                            >
                                              {c.image_url ? <img src={c.image_url} alt="" /> : <span className="chip-avatar-fallback">{c.name.slice(0, 1)}</span>}
                                              {c.name}
                                            </button>
                                          ))}
                                          {!projectCharacters.length ? <span className="empty-hint">资产库暂无角色</span> : null}
                                        </div>
                                      </div>

                                      <div className="form-group">
                                        <label className="form-label">出场角色服饰造型 (Pictures)</label>
                                        {selectedBeatCharacters.length ? (
                                          <div className="character-look-list">
                                            {selectedBeatCharacters.map((character, index) => {
                                              const lookOptions = getCharacterLookOptions(character)
                                              const selectedLook = getSelectedCharacterLook(character)
                                              return (
                                                <div key={character.id} className="character-look-row">
                                                  <div className="character-look-heading">
                                                    {character.image_url ? <img src={character.image_url} alt="" /> : <span className="chip-avatar-fallback">{character.name.slice(0, 1)}</span>}
                                                    <strong>{character.name}</strong>
                                                    <span>Picture {index + 1}</span>
                                                  </div>
                                                  <Select
                                                    value={getBeatCharacterLookId(character) || undefined}
                                                    allowClear
                                                    showSearch
                                                    optionFilterProp="label"
                                                    style={{ width: "100%" }}
                                                    placeholder="选择该角色在当前镜头的服饰造型"
                                                    onChange={(value: string | undefined) => onCharacterLookChange(character.id, value)}
                                                  >
                                                    {lookOptions.map((look) => (
                                                      <Select.Option key={look.value} value={look.value} label={look.label}>
                                                        <span className="look-option">
                                                          {look.imageUrl ? <img src={look.imageUrl} alt="" /> : null}
                                                          <span>{look.label}</span>
                                                        </span>
                                                      </Select.Option>
                                                    ))}
                                                  </Select>
                                                  {selectedLook ? (
                                                    <div className="selected-look-preview">
                                                      <img
                                                        src={selectedLook.imageUrl}
                                                        alt={`${character.name}当前服饰造型`}
                                                        onClick={() => openMediaPreview({
                                                          src: selectedLook.imageUrl,
                                                          title: `${character.name} · ${selectedLook.label}`,
                                                          description: selectedLook.description,
                                                        })}
                                                      />
                                                      <div>
                                                        <strong>{selectedLook.label}</strong>
                                                        <p>{selectedLook.description || "已选择为该角色当前镜头的造型参考图"}</p>
                                                      </div>
                                                    </div>
                                                  ) : !lookOptions.length ? (
                                                    <p className="look-empty-hint">
                                                      该角色还没有可用服饰造型，请先到资产库生成造型图。
                                                    </p>
                                                  ) : null}
                                                </div>
                                              )
                                            })}
                                          </div>
                                        ) : (
                                          <p className="look-empty-hint">请先在“出场身份”中选择角色。</p>
                                        )}
                                      </div>

                                      {/* 出场道具 Chips */}
                                      <div className="form-group">
                                        <label className="form-label">出场道具 (Props)</label>
                                        <div className="chips-flex-row">
                                          {projectProps.map((p) => (
                                            <button
                                              key={p.id}
                                              type="button"
                                              className={`xiaji-ref-chip${selectedBeat.prop_ids?.includes(p.id) ? " is-on" : ""}`}
                                              onClick={() => toggleBeatProp(p.id)}
                                            >
                                              {p.image_url ? <img src={p.image_url} alt="" /> : <span className="chip-avatar-fallback">{p.name.slice(0, 1)}</span>}
                                              {p.name}
                                            </button>
                                          ))}
                                          {!projectProps.length ? <span className="empty-hint">资产库暂无道具</span> : null}
                                        </div>
                                      </div>
                                    </div>
                                    </div>
                                    ),
                                  },
                                  {
                                    key: "sketch",
                                    label: (
                                      <span className="xiaji-inspector-tab-label">
                                        <Pencil size={14} />
                                        草图
                                        <span className={`status-chip ${selectedBeat.sketch_url ? "is-active" : "is-idle"}`}>
                                          <span className="chip-dot" /> {selectedBeat.sketch_url ? "已就绪" : "待出图"}
                                        </span>
                                      </span>
                                    ),
                                    children: (
                                    <div className="xiaji-inspector-pane">
                                    <div className="sketch-block">
                                      {/* 绑定的角色/身份 Pill */}
                                      <div className="sketch-actor-row">
                                        {(selectedBeat.character_ids || []).map((cid) => (
                                          <span
                                            key={cid}
                                            className="sketch-actor-pill"
                                          >
                                            <span className="dot" />
                                            <span>{getCharName(cid)}</span>
                                          </span>
                                        ))}
                                        {!selectedBeat.character_ids?.length ? (
                                          <span className="sketch-actor-pill is-none">
                                            <span className="dot" />
                                            <span>{selectedBeat.speaker || "未指定主角色"}</span>
                                          </span>
                                        ) : null}
                                      </div>

                                      {/* 主草图大卡片 + 版本缩略图 */}
                                      <div className="sketch-cards-row">
                                        <div className="sketch-main-card">
                                          {selectedBeat.sketch_url ? (
                                            <img
                                              src={selectedBeat.sketch_url}
                                              className="main-preview-img"
                                              alt={`${workshopBeatLabel(selectedBeat)} 分镜草图`}
                                              onClick={() => openMediaPreview({
                                                src: selectedBeat.sketch_url,
                                                title: `${workshopBeatLabel(selectedBeat)} 分镜草图`,
                                                description: selectedBeat.heading || selectedBeat.action,
                                              })}
                                            />
                                          ) : generatingBeatIds.has(selectedBeat.id) ? (
                                            <div className="sketch-placeholder is-busy">
                                              <Spin />
                                              <span>{generationStatusText(selectedBeat.id, "sketch") || "GRS 正在生成"}</span>
                                            </div>
                                          ) : (
                                            <div
                                              className="sketch-placeholder"
                                              onClick={() => enqueueSingleSketch()}
                                            >
                                              <ImageIcon size={32} />
                                              <span>点此使用 GRS (gpt-image-2) 生成草图</span>
                                            </div>
                                          )}
                                        </div>

                                        {/* 右侧缩略卡片 */}
                                        <div className="sketch-thumb-card">
                                          {selectedBeat.sketch_url ? (
                                            <img
                                              src={selectedBeat.sketch_url}
                                              alt={`${workshopBeatLabel(selectedBeat)} 草图缩略图`}
                                              onClick={() => openMediaPreview({
                                                src: selectedBeat.sketch_url,
                                                title: `${workshopBeatLabel(selectedBeat)} 分镜草图`,
                                                description: selectedBeat.heading || selectedBeat.action,
                                              })}
                                            />
                                          ) : (
                                            <div className="thumb-empty" />
                                          )}
                                          <span className="version-badge">2:3 1K</span>
                                        </div>
                                      </div>

                                      {/* 8 个专业工具操作按钮条 (对齐 source1) */}
                                      <div className="sketch-bottom-toolbar">
                                        <button
                                          type="button"
                                          className="tool-btn is-primary"
                                          disabled={generatingBeatIds.has(selectedBeat.id)}
                                          onClick={() => enqueueSingleSketch()}
                                        >
                                          <RefreshCw size={12} className={generatingBeatIds.has(selectedBeat.id) ? "animate-spin" : undefined} />
                                          <span>{generatingBeatIds.has(selectedBeat.id) ? "生成中" : (selectedBeat.sketch_url ? "重新生成草图" : "✨ 生成草图")}</span>
                                        </button>

                                        <button type="button" className="tool-btn" onClick={() => handleToolNotice("姿势骨骼编辑")}>
                                          <Users size={12} />
                                          <span>姿势编辑</span>
                                        </button>

                                        <button type="button" className="tool-btn" onClick={() => handleToolNotice("画幅智能裁剪")}>
                                          <Crop size={12} />
                                          <span>裁剪保存</span>
                                        </button>

                                        <button type="button" className="tool-btn" onClick={() => toggleSceneBackground()}>
                                          <LucideImage size={12} />
                                          <span>{currentSceneView === "front" ? "场景正面" : "场景背面"}</span>
                                        </button>

                                        <a
                                          href={selectedBeat.sketch_url || undefined}
                                          target="_blank"
                                          download
                                          className={`tool-btn${selectedBeat.sketch_url ? "" : " is-disabled"}`}
                                        >
                                          <Download size={12} />
                                          <span>下载原图</span>
                                        </a>

                                        <Upload
                                          accept="image/*"
                                          showUploadList={false}
                                          beforeUpload={handleUploadSketch}
                                        >
                                          <button type="button" className="tool-btn">
                                            <UploadIcon size={12} />
                                            <span>上传替换</span>
                                          </button>
                                        </Upload>

                                        <button type="button" className="tool-btn" onClick={() => handleToolNotice("导演世界资产同步")}>
                                          <Box size={12} />
                                          <span>导演世界</span>
                                        </button>

                                        <button type="button" className="tool-btn" onClick={() => handleToolNotice("画板深度精绘")}>
                                          <ExternalLink size={12} />
                                          <span>虾画编辑</span>
                                        </button>
                                      </div>
                                    </div>
                                    </div>
                                    ),
                                  },
                                  {
                                    key: "material",
                                    label: (
                                      <span className="xiaji-inspector-tab-label">
                                        <Layers size={14} />
                                        素材组
                                        <span className={`status-chip ${h3Failed || !(savedH3Prompt.trim() && !h3PromptDirty) ? "is-idle" : "is-active"}`}>
                                          <span className="chip-dot" /> {h3StatusLabel}
                                        </span>
                                      </span>
                                    ),
                                    children: (
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
                                              loading={generatingH3Prompt}
                                              disabled={h3GenerateBusy && !generatingH3Prompt}
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
                                                  setH3PromptDraft(savedH3Prompt)
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
                                        ) : (
                                          <div
                                            className="h3-prompt-display"
                                            dangerouslySetInnerHTML={{ __html: renderH3PromptHtml(savedH3Prompt) }}
                                          />
                                        )}
                                      </div>
                                    </div>
                                    </div>
                                    ),
                                  },
                                ]}
                              />
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ),
                },
                /* ==================== Tab 2: 📝 原文剧本 (ScriptPane) ==================== */
                {
                  key: "script",
                  label: "📝 剧本",
                  children: (
                    <div className="xiaji-script-grid">
                      {/* 左侧：出场资产规划 + 原文 */}
                      <div className="xiaji-script-col">
                        <section className="script-section-box">
                          <header className="section-head">
                            <Users size={15} />
                            <h3>资产规划</h3>
                            <em>{currentEpisode.links?.filter((l) => l.kind === "character").length || 0} 个身份</em>
                          </header>
                          <ul className="xiaji-workshop-assets">
                            {projectCharacters.map((c) => (
                              <li
                                key={c.id}
                              >
                                {c.image_url ? <img src={c.image_url} alt="" /> : <span className="xiaji-workshop-asset-fallback">{c.name.slice(0, 1)}</span>}
                                <div className="asset-info">
                                  <strong>{c.name}</strong>
                                  <em>{c.role || "主要人物"}</em>
                                </div>
                              </li>
                            ))}
                          </ul>
                        </section>

                        <section className="script-section-box">
                          <header className="section-head">
                            <FileText size={15} />
                            <h3>原文剧本</h3>
                            <em>共 {currentEpisode.original_lines?.length || 0} 行</em>
                          </header>
                          <ol className="xiaji-original-lines">
                            {(currentEpisode.original_lines || []).map((line, idx) => (
                              <li
                                key={idx}
                              >
                                <span className="line-no">{idx + 1}.</span>
                                <p className="line-content">{line}</p>
                              </li>
                            ))}
                          </ol>
                        </section>
                      </div>

                      {/* 右侧：脚本预览列表 (BeatCards) */}
                      <div className="xiaji-script-col">
                        <section className="script-section-box">
                          <header className="section-head">
                            <Clapperboard size={15} />
                            <h3>编排脚本预览</h3>
                            <em>{currentEpisode.beats?.length || 0} 个 Beat · 共 {episodeDurationSec} 秒</em>
                          </header>
                          <div className="xiaji-beat-list">
                            {(currentEpisode.beats || []).map((beat) => (
                              <div
                                key={beat.id}
                                className="xiaji-beat"
                              >
                                <span className="beat-header">
                                  {workshopBeatLabel(beat)} · {formatBeatDurationZh(beat.video_duration)} · {beat.heading || "分镜"}
                                </span>
                                {beat.dialogue ? (
                                  <p className="beat-dialogue">
                                    <strong>{beat.speaker || "角色"}</strong>：{beat.dialogue}
                                  </p>
                                ) : null}
                                {beat.action ? (
                                  <p className="beat-action">
                                    <span className="lbl">画面：</span>{beat.action}
                                  </p>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>
                    </div>
                  ),
                },
                {
                  key: "dubbing",
                  label: "🎙️ 配音",
                  children: (
                    <DubbingWorkbench csrfToken={csrfToken} projectId={projectId} episodeId={currentEpisode.id} />
                  ),
                },
                /* ==================== Tab 3: 🎞️ 成片合成 (ComposePane) ==================== */
                {
                  key: "compose",
                  label: "🎞️ 合成",
                  children: (
                    <div className="xiaji-compose-pane">
                      <div className="compose-summary-card">
                        <Clapperboard size={32} className="text-purple" />
                        <div className="summary-info">
                          <h3>
                            {videoRenderMode === "episode"
                              ? "第 " + currentEpisode.number + " 集 H3 Director 整集直出"
                              : "第 " + currentEpisode.number + " 集成片合成流水线"}
                          </h3>
                          <p>
                            {videoRenderMode === "episode"
                              ? (episodeFilm
                                ? "本集已由 H3 Director 加速版一次直出。勾选镜头点「生成选中」可单独重跑单镜。"
                                : "「一键生成视频」一次出整集成片；勾选镜头后点「生成选中」只提交这些镜。")
                              : `已出片 ${videoReadyCount}/${currentEpisode.beats?.length || 0} · 开口对白默认保留 H3 口型声，内心/旁白可叠配音轨`}
                          </p>
                        </div>
                        <Space wrap>
                          <Switch
                            size="small"
                            checked={mixDubbing}
                            onChange={setMixDubbing}
                            checkedChildren="混入配音"
                            unCheckedChildren="不混配音"
                          />
                          <Button
                            type="primary"
                            icon={<Sparkles size={14} />}
                            loading={composingEpisode || episodeVideoJobActive}
                            disabled={
                              composingEpisode
                              || episodeVideoJobActive
                              || !currentEpisode.beats?.length
                              || videoReadyCount < (currentEpisode.beats?.length || 0)
                              || Boolean(composeBlockReason)
                            }
                            onClick={() => handleComposeEpisode()}
                          >
                            一键合成全集成片
                          </Button>
                          <Button onClick={() => handleToolNotice("字幕导出")}>
                            导出字幕 SRT
                          </Button>
                        </Space>
                      </div>

                      {composeBlockReason ? (
                        <Alert
                          type="warning"
                          showIcon
                          className="mt-4"
                          message="解说剧还不能合成"
                          description={composeBlockReason}
                        />
                      ) : null}

                      {episodeFilm ? (
                        <div className="compose-episode-player mt-4">
                          <h4>分集成片</h4>
                          <video src={episodeFilm} controls playsInline className="compose-episode-video" />
                          {episodeSource === "director_direct" ? (
                            <p className="compose-episode-note">来源：H3 Director 加速版一次直出</p>
                          ) : episodeSource === "composed" ? (
                            <p className="compose-episode-note">来源：逐镜拼接合成</p>
                          ) : null}
                        </div>
                      ) : null}

                      <div className="timeline-preview-section mt-4">
                        <h4>分镜轨道时间线预览（已出片 {videoReadyCount}/{currentEpisode.beats?.length || 0}）</h4>
                        <div className="timeline-tiles-scroll">
                          {(currentEpisode.beats || []).map((b) => {
                            const busy = generatingVideoBeatIds.has(b.id)
                            const playback = beatPlaybackUrl(b)
                            const ready = Boolean(playback)
                            const upscaled = beatHasUpscaled(b)
                            return (
                              <div
                                key={b.id}
                                className={`timeline-shot-card${ready ? " is-ready" : busy ? " is-busy" : " is-missing"}`}
                              >
                                <div className="shot-thumb">
                                  {ready ? (
                                    <video src={playback} muted playsInline />
                                  ) : b.render_url || b.sketch_url ? (
                                    <img src={b.render_url || b.sketch_url || undefined} alt="" />
                                  ) : (
                                    <div className="placeholder-thumb">Shot {b.sequence}</div>
                                  )}
                                </div>
                                <div className="shot-title">Shot {b.sequence} ({formatBeatDurationLabel(b.video_duration)})</div>
                                <div className="shot-status">{upscaled ? "已出片 · 2x" : ready ? "已出片" : busy ? "生成中" : "未出片"}</div>
                                <Tooltip title={beatUpscaleDisabledReason(b, beatVideoProgress[b.id]) || "用本机 RTX 放大到 2 倍，原片保留"}>
                                  <Button
                                    size="small"
                                    className="mt-1"
                                    disabled={Boolean(beatUpscaleDisabledReason(b, beatVideoProgress[b.id])) || upscalingBeatId === b.id}
                                    loading={upscalingBeatId === b.id}
                                    onClick={() => void handleUpscaleBeat(b)}
                                    aria-label={`2x 超分 ${workshopBeatLabel(b)}`}
                                  >
                                    超分
                                  </Button>
                                </Tooltip>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  ),
                },
              ]}
            />
          </div>
        ) : currentEpisodeId && !currentEpisode ? (
          /* 加载中占位 */
          <div className="workshop-loading-box">
            <Spin size="large" />
            <span className="loading-text">正在加载剧集分镜数据...</span>
          </div>
        ) : null}

        {/* ==================== 新建/编辑分集弹窗 ==================== */}
        <Modal
          open={modalVisible}
          title={isEdit ? "编辑分集信息" : "新增剧集"}
          confirmLoading={submitting}
          okText="确认保存"
          cancelText="取消"
          width={600}
          destroyOnHidden
          onOk={() => handleSubmit()}
          onCancel={() => setModalVisible(false)}
          className="d2-episode-workshop"
        >
          <Form layout="vertical">
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item label="集数序号" required>
                  <InputNumber
                    value={form.episode_num}
                    min={1}
                    style={{ width: "100%" }}
                    onChange={(value) => setForm((prev) => ({ ...prev, episode_num: value }))}
                  />
                </Form.Item>
              </Col>
              <Col span={16}>
                <Form.Item label="分集标题" required>
                  <Input
                    value={form.title}
                    placeholder="例如：风起青萍"
                    onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                  />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item label="制作状态">
              <Select value={form.status} onChange={(value: string | undefined) => setForm((prev) => ({ ...prev, status: value ?? prev.status }))}>
                <Select.Option value="draft">草稿规划</Select.Option>
                <Select.Option value="script_ready">脚本就绪</Select.Option>
                <Select.Option value="sketching">出图中</Select.Option>
                <Select.Option value="sketched">分镜完成</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item label="分镜剧本内容">
              <Input.TextArea
                value={form.script_text || ""}
                placeholder="输入分集对白、画面提示与镜头描述..."
                rows={6}
                onChange={(e) => setForm((prev) => ({ ...prev, script_text: e.target.value }))}
              />
            </Form.Item>
          </Form>
        </Modal>
      </div>
    )
  },
)

export default EpisodeWorkshopPane
