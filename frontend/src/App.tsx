import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Dropdown, Input, InputNumber, message, Modal, Popover, Select, Slider, Switch, Tabs, Tooltip } from "antd"
import {
  ChevronDown, ChevronLeft, ChevronRight, Clapperboard, Clock3, FileVideo,
  Download, ExternalLink, FolderOpen, HardDrive, History, ImagePlus, Link2, ListChecks, LoaderCircle, LogOut, Maximize2,
  Minus, MoreHorizontal, MoveLeft, MoveRight, PanelLeftClose, PanelLeftOpen, Pencil, Pin, Plus, RotateCw, Search, Send, Settings2, SlidersHorizontal, Sparkles, Trash2, UserRound, Users, Video, WalletCards, WandSparkles, X,
} from "lucide-react"
import { Fragment, FormEvent, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { jsonMutation, requestJson, User } from "./api"
import {
  chooseResourceDirectory, DirectoryHandleLike, directoryApiSupported, directoryPermission,
  getResourceDirectory, localResourceFile, localResourceUrl, saveToResourceDirectory,
} from "./local-resource-store"
import type { ImageResult } from "./media/ImageStudioModule"
import type { VideoResult } from "./media/VideoStudioModule"

/*
 * THESIS: A conversation-first AI studio, not a dashboard of cards.
 * OWN-WORLD: cool white canvas, hairline dividers, compact black text and one periwinkle action color.
 * STORY: scan a task in the left conversation rail, then create or continue in a quiet central canvas.
 * FIRST VIEWPORT: 76px icon rail, 240px task rail, open workspace and a bottom-anchored composer.
 * FORM: a light operational workspace informed by the observed Jimeng conversation layout.
 */
const ImageStudioModule = lazy(() => import("./media/ImageStudioModule"))
const VideoStudioModule = lazy(() => import("./media/VideoStudioModule"))

type Status = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "partial"
type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null; delivered_at?: string | null
}
type ParameterVisibility = "primary" | "advanced" | "internal"
type RequestParameter = {
  name: string; label: string; value: string | number | boolean; unit?: string | null
  visibility?: ParameterVisibility
}
type Job = {
  id: string; mode: string; status: Status; stage: string; progress?: number; prompt: string
  negative_prompt: string; image_size?: string | null
  reference_count: number; references: { index: number; url: string }[]
  options?: Record<string, unknown>; request_parameters: RequestParameter[]; outputs: Output[]; error?: string | null
  created_at: string; updated_at: string
  media_type: "image" | "video"; title?: string | null; pinned?: boolean
  rounds: JobRound[]
  source?: { job_id: string; generation_item_id?: string | null; output_index?: number | null } | null
}
type GenerationItem = { id: string; index: number; executor: string; status: Status; stage: string; progress: number; outputs: Output[]; error?: string | null }
type JobRound = { id: string; sequence: number; mode: string; media_type: "image" | "video"; status: Status; stage: string; progress: number; prompt: string; options?: Record<string, unknown>; reference_count: number; references: { index: number; url: string }[]; request_parameters: RequestParameter[]; generation_items: GenerationItem[]; error?: string | null }
type Workflow = {
  id: string; name: string; description: string; reference_mode: "none" | "keyframes" | "collection" | "fixed"
  min_references: number; max_references: number; reference_labels: string[]
  accepts_negative_prompt: boolean; accepts_image_size: boolean; supports_h3_options: boolean
  parameters: WorkflowParameter[]
  media_type: "image" | "video"; executor: string; available: boolean; unavailable_reason?: string | null
}
type OptionDefinition = {
  label: string; type: "string" | "number" | "integer" | "boolean"; default: string | number | boolean
  enum?: (string | number)[]; minimum?: number; maximum?: number; step?: number; pattern?: string
  description?: string; unit?: string; ui_group?: ParameterVisibility
  ui_control?: "select" | "visual-settings" | "duration-slider"; ui_companion?: string; ui_companions?: string[]
  ui_options?: { value: string | number; label: string; hint?: string }[]
  megapixels_by_quality?: Record<string, number>
  ui_resolution_preview?: { multiple?: number; max_width?: number; max_height?: number }
  ui_visible_when?: Record<string, string | number | boolean>
}
type WorkflowParameter = { name: string; schema?: { properties?: Record<string, OptionDefinition> } | null }
type OptionInputValue = string | boolean
type ModesPayload = { modes: Workflow[]; image_sizes: string[]; presets: Record<string, string> }
type GrsBalanceSnapshot = { credits: number | null; queried_at: string | null; refresh_error?: string | null }
type ReferenceAsset = { id: string; file: File; preview: string }
type ImagePreview = { src: string; alt: string }
type DirectoryState = "checking" | "unsupported" | "missing" | "prompt" | "granted"
type MediaDraft = {
  workflowId: string; prompt: string; negativePrompt: string; references: ReferenceAsset[]
  optionValues: Record<string, OptionInputValue>; selectedJobId?: string
  source?: { jobId: string; generationItemId: string; outputIndex: number }
}
type AssetMediaFilter = "all" | "image" | "video" | "audio" | "document"
type H3Skill = {
  id: string
  name: string
  description: string
  icon: string
  category: string
}


function normalizeWorkflow(workflow: Workflow): Workflow {
  return {
    ...workflow,
    media_type: workflow.media_type ?? (workflow.id.startsWith("grs-") ? "image" : "video"),
    executor: workflow.executor ?? (workflow.id.startsWith("grs-") ? "grs" : "comfyui"),
    available: workflow.available ?? true,
  }
}

function normalizeJob(job: Job): Job {
  if (job.rounds?.length) return job
  const generation: GenerationItem = {
    id: `${job.id}:legacy-item`, index: 1, executor: "comfyui", status: job.status,
    stage: job.stage, progress: job.progress ?? 0, outputs: job.outputs, error: job.error,
  }
  const round: JobRound = {
    id: `${job.id}:legacy-round`, sequence: 1, mode: job.mode, media_type: job.media_type ?? "video",
    status: job.status, stage: job.stage, progress: job.progress ?? 0, prompt: job.prompt,
    options: job.options, reference_count: job.reference_count, references: job.references,
    request_parameters: job.request_parameters, generation_items: [generation], error: job.error,
  }
  return { ...job, media_type: job.media_type ?? "video", rounds: [round] }
}

const FALLBACK_WORKFLOW = "minimax-h3-i2v"
const api = requestJson
const mediaUrl = (path: string) => `/api/media/${encodeURIComponent(path)}`
const parameterValue = (parameter: RequestParameter) => {
  if (parameter.name === "references") return `${parameter.value} 张`
  if (typeof parameter.value === "boolean") return parameter.value ? "是" : "否"
  if (parameter.unit) return `${parameter.value} ${parameter.unit}`
  return String(parameter.value)
}
const statusText: Record<Status, string> = { queued: "等待队列", running: "生成中", succeeded: "已完成", partial: "部分完成", failed: "失败", interrupted: "已中断" }
const statusColor: Record<Status, string> = {
  queued: "text-amber-300", running: "text-[#9f8cff]", succeeded: "text-emerald-300", partial: "text-amber-200", failed: "text-red-300", interrupted: "text-[#94949d]",
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

function formatAssetDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "未分类"
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function assetDuration(job: Job, kind: Output["kind"]) {
  if (kind !== "video") return ""
  const raw = job.options?.duration_seconds ?? job.options?.duration ?? job.options?.video_duration
  const seconds = Number(raw)
  const safeSeconds = Number.isFinite(seconds) && seconds > 0 ? Math.round(seconds) : 5
  return `00:${String(safeSeconds).padStart(2, "0")}`
}

function formatGrsBalance(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "尚未查询"
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value)
}

function newAssets(files: FileList | File[]) {
  return Array.from(files).filter((file) => file.type.startsWith("image/")).map((file) => ({
    id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
    file,
    preview: URL.createObjectURL(file),
  }))
}

function releaseAssets(assets: ReferenceAsset[]) { assets.forEach((asset) => URL.revokeObjectURL(asset.preview)) }

function workflowOptionDefinitions(workflow?: Workflow) {
  return workflow?.parameters.find((parameter) => parameter.name === "options")?.schema?.properties ?? {}
}

function defaultOptionValues(workflow?: Workflow): Record<string, OptionInputValue> {
  return Object.fromEntries(Object.entries(workflowOptionDefinitions(workflow)).map(([name, definition]) => [
    name,
    definition.type === "boolean" ? Boolean(definition.default) : String(definition.default),
  ]))
}

function optionVisible(definition: OptionDefinition, values: Record<string, OptionInputValue>) {
  if (!definition.ui_visible_when) return true
  return Object.entries(definition.ui_visible_when).every(([name, expected]) => String(values[name]) === String(expected))
}

function generatedResolutionLabel(definition: OptionDefinition, quality: string, aspectRatio: string) {
  const megapixels = definition.megapixels_by_quality?.[quality]
  const match = aspectRatio.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0]
  const [aspectWidth, aspectHeight] = match?.split(":").map(Number) ?? []
  if (!megapixels || !aspectWidth || !aspectHeight) return undefined

  const preview = definition.ui_resolution_preview
  const multiple = preview?.multiple ?? 32
  const ratio = aspectWidth / aspectHeight
  let width = Math.round(Math.sqrt(megapixels * 1024 * 1024 * ratio) / multiple) * multiple
  let height = Math.round(Math.sqrt((megapixels * 1024 * 1024) / ratio) / multiple) * multiple
  const maxWidth = ratio >= 1 ? preview?.max_width : preview?.max_height
  const maxHeight = ratio >= 1 ? preview?.max_height : preview?.max_width
  if (maxWidth && maxHeight && (width > maxWidth || height > maxHeight)) {
    const scale = Math.min(maxWidth / width, maxHeight / height)
    width = Math.max(multiple, Math.round((width * scale) / multiple) * multiple)
    height = Math.max(multiple, Math.round((height * scale) / multiple) * multiple)
  }
  return `${width} × ${height}`
}

function serializeOptionValues(
  definitions: Record<string, OptionDefinition>, values: Record<string, OptionInputValue>,
) {
  return Object.fromEntries(Object.entries(definitions).filter(([, definition]) => definition.ui_group !== "internal").map(([name, definition]) => {
    const value = values[name] ?? (definition.type === "boolean" ? false : "")
    return [name, definition.type === "number" || definition.type === "integer" ? Number(value) : value]
  }))
}

function validateOptionValues(
  definitions: Record<string, OptionDefinition>, values: Record<string, OptionInputValue>, referenceCount: number,
) {
  for (const [name, definition] of Object.entries(definitions)) {
    if (!optionVisible(definition, values)) continue
    const value = values[name]
    if (definition.type === "boolean") continue
    if (value === undefined || String(value).trim() === "") return `${definition.label}不能为空`
    if (definition.enum && !definition.enum.some((item) => String(item) === String(value))) return `${definition.label}不是有效选项`
    if (definition.pattern && !(new RegExp(definition.pattern).test(String(value).trim()))) return `${definition.label}格式不正确`
    if (definition.type === "number" || definition.type === "integer") {
      const numericValue = Number(value)
      if (!Number.isFinite(numericValue)) return `${definition.label}必须为数字`
      if (definition.type === "integer" && !Number.isInteger(numericValue)) return `${definition.label}必须为整数`
      if (definition.minimum !== undefined && numericValue < definition.minimum) return `${definition.label}不能小于 ${definition.minimum}`
      if (definition.maximum !== undefined && numericValue > definition.maximum) return `${definition.label}不能大于 ${definition.maximum}`
    }
  }
  if (values.task_type === "Ref2VA" && referenceCount === 0) return "Ref2VA 任务类型至少需要 1 张参考图"
  if (values.audio_steps !== undefined && Number(values.audio_steps) < Number(values.video_steps)) {
    return "音频采样步数不能小于视频采样步数"
  }
  return ""
}

function MediaTile({ item, localUrl }: { item: Output; localUrl?: string }) {
  const src = item.delivery_status === "local" ? localUrl : (item.download_url ?? mediaUrl(item.path))
  if (!src) return <div className="grid h-full w-full place-items-center bg-[#27282e] text-[#898993]"><HardDrive size={18} /></div>
  return item.kind === "video"
    ? <video className="h-full w-full object-cover" muted playsInline preload="metadata" src={src} />
    : <img className="h-full w-full object-cover" src={src} alt={item.label} />
}

function TaskRail({
  jobs, selectedJobId, onSelect, onPinToggle, onRename, onDelete, localMediaUrls, compact = false, showEmpty = true, scrollMode = "fill",
}: {
  jobs: Job[]
  selectedJobId?: string
  onSelect: (jobId: string) => void
  onPinToggle: (job: Job) => void
  onRename: (job: Job) => void
  onDelete: (job: Job) => void
  localMediaUrls: Record<string, string>
  compact?: boolean
  showEmpty?: boolean
  scrollMode?: "fill" | "content"
}) {
  return <div className={`studio-task-scroll overflow-y-auto ${scrollMode === "fill" ? "min-h-0 flex-1" : "max-h-[132px]"} ${compact ? "px-4 pb-3" : "px-4 pb-4"}`}>
    {jobs.map((job) => {
      const selected = selectedJobId === job.id
      const cover = job.outputs[0]
      const reference = job.references[0]
      return <div
        key={job.id}
        role="button"
        tabIndex={0}
        onClick={() => onSelect(job.id)}
        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(job.id) } }}
        className={`studio-task-card group mb-1 flex h-9 w-full cursor-pointer items-center gap-2 rounded-lg px-2 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/30 ${selected ? "bg-[#eef1ff]" : "hover:bg-black/[0.035]"}`}
      >
        <div className="size-8 shrink-0 overflow-hidden rounded-md bg-[#eef1f4]">
          {cover ? <MediaTile item={cover} localUrl={localMediaUrls[cover.path]} /> : reference ? <img src={reference.url} alt="任务封面" className="h-full w-full object-cover" /> : <div className="grid h-full w-full place-items-center text-[#a0a8b2]">{job.media_type === "image" ? <ImagePlus size={15} /> : <Video size={15} />}</div>}
        </div>
        <span title={statusText[job.status]} className={`size-1.5 shrink-0 rounded-full ${job.status === "succeeded" ? "bg-emerald-500" : job.status === "failed" || job.status === "interrupted" ? "bg-rose-500" : job.status === "running" ? "bg-[#4d6bfe]" : "bg-amber-400"}`} />
        <p className="min-w-0 flex-1 truncate text-sm leading-[21px] text-[#171a1f]">{job.title || job.prompt}</p>
        {job.pinned ? <Pin size={12} className="shrink-0 rotate-45 text-[#4d6bfe]" /> : null}
        <Dropdown
          trigger={["click"]}
          popupRender={(menu) => <div className="studio-task-menu">{menu}</div>}
          menu={{
            items: [
              { key: "pin", icon: <Pin size={14} />, label: job.pinned ? "取消置顶" : "置顶" },
              { key: "rename", icon: <Pencil size={14} />, label: "重命名" },
              { type: "divider" },
              { key: "delete", danger: true, icon: <Trash2 size={14} />, label: "删除" },
            ],
            onClick: ({ key, domEvent }) => {
              domEvent.stopPropagation()
              if (key === "pin") onPinToggle(job)
              if (key === "rename") onRename(job)
              if (key === "delete") onDelete(job)
            },
          }}
        >
          <button type="button" title="任务操作" aria-label={`任务操作：${job.title || job.prompt}`} onClick={(event) => event.stopPropagation()} className="grid size-7 shrink-0 place-items-center rounded-md text-[#65707c] opacity-0 transition hover:bg-white hover:text-[#171a1f] group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/30"><MoreHorizontal size={16} /></button>
        </Dropdown>
      </div>
    })}
    {showEmpty && !jobs.length && <div className="flex min-h-40 flex-col items-center justify-center px-5 text-center text-xs leading-5 text-[#7c8794]"><ListChecks className="mb-2 text-[#a0a8b2]" size={20} />当前类型还没有任务</div>}
  </div>
}

export default function App({
  user, csrfToken, onOpenAdmin, onLogout, logoutPending,
}: {
  user: User
  csrfToken: string
  onOpenAdmin?: () => void
  onLogout: () => void
  logoutPending: boolean
}) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const [workflowId, setWorkflowId] = useState(FALLBACK_WORKFLOW)
  const [mediaType, setMediaType] = useState<"image" | "video">("video")
  const [prompt, setPrompt] = useState("")
  const [negativePrompt, setNegativePrompt] = useState("")
  const [references, setReferences] = useState<ReferenceAsset[]>([])
  const referencesRef = useRef<ReferenceAsset[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [selectedJobId, setSelectedJobId] = useState<string | undefined>()
  const [workspaceView, setWorkspaceView] = useState<"generate" | "assets">("generate")
  const [taskRailCollapsed, setTaskRailCollapsed] = useState(false)
  const [assetSection, setAssetSection] = useState<"history" | "subject" | "canvas">("history")
  const [assetMediaFilter, setAssetMediaFilter] = useState<AssetMediaFilter>("all")
  const [assetSearch, setAssetSearch] = useState("")
  const [isComposerCompact, setIsComposerCompact] = useState(false)
  const [renameTarget, setRenameTarget] = useState<Job | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [source, setSource] = useState<MediaDraft["source"]>()
  const draftsRef = useRef<Partial<Record<"image" | "video", MediaDraft>>>({})
  const restoringDraftRef = useRef(false)
  const [isSelectedPromptExpanded, setIsSelectedPromptExpanded] = useState(false)
  const [previewImage, setPreviewImage] = useState<ImagePreview | null>(null)
  const [referencePreviewIndex, setReferencePreviewIndex] = useState<number | null>(null)
  const [referencePreviewZoom, setReferencePreviewZoom] = useState(1)
  const [referencePreviewRotation, setReferencePreviewRotation] = useState(0)
  const [referencePreviewFullscreen, setReferencePreviewFullscreen] = useState(false)
  const [optionValues, setOptionValues] = useState<Record<string, OptionInputValue>>({})
  const [advancedOptionsOpen, setAdvancedOptionsOpen] = useState(false)
  const [imageSize, setImageSize] = useState("横版 1280 x 720")
  const [directoryHandle, setDirectoryHandle] = useState<DirectoryHandleLike>()
  const [directoryState, setDirectoryState] = useState<DirectoryState>(
    directoryApiSupported() ? "checking" : "unsupported",
  )
  const [storageOpen, setStorageOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [storageError, setStorageError] = useState<string>()
  const [localMediaUrls, setLocalMediaUrls] = useState<Record<string, string>>({})
  const [pendingDeliveries, setPendingDeliveries] = useState<Record<string, true>>({})
  const deliveryInFlight = useRef(new Set<string>())
  const localMediaUrlsRef = useRef<Record<string, string>>({})
  const [messageApi, messageContext] = message.useMessage()
  const restoringComposerRef = useRef(false)

  const modesQuery = useQuery({ queryKey: ["modes"], queryFn: async () => {
    const payload = await api<ModesPayload>("/api/modes")
    return { ...payload, modes: payload.modes.map(normalizeWorkflow) }
  } })
  const jobsQuery = useQuery({ queryKey: ["jobs", user.id], queryFn: async () => (await api<Job[]>("/api/jobs")).map(normalizeJob), refetchInterval: 1600 })
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: () => api<{ comfy: { reachable: boolean }; grs: { available: boolean; message?: string | null } }>("/api/health"), refetchInterval: 8000 })
  const workflows = (modesQuery.data?.modes ?? []).filter((item) => item.media_type === mediaType)
  const workflow = workflows.find((item) => item.id === workflowId) ?? workflows[0]
  const allJobs = jobsQuery.data ?? []
  const jobs = allJobs.filter((job) => job.media_type === mediaType)
  const imageGenerationActive = mediaType === "image" && jobs.some((job) => job.status === "queued" || job.status === "running")
  const grsBalanceQuery = useQuery({
    queryKey: ["grs-balance"],
    queryFn: () => api<GrsBalanceSnapshot>("/api/providers/grs/balance"),
    enabled: mediaType === "image",
    refetchInterval: imageGenerationActive ? 5_000 : 15_000,
  })
  const grsBalanceUnavailable = Boolean(grsBalanceQuery.error || (grsBalanceQuery.data?.refresh_error && grsBalanceQuery.data.credits === null))
  const grsBalanceStale = Boolean(grsBalanceQuery.data?.refresh_error)
  const [selectedSkillId, setSelectedSkillId] = useState<string>("general")
  const skillsQuery = useQuery({
    queryKey: ["llm-skills"],
    queryFn: () => requestJson<{ skills: H3Skill[] }>("/api/llm/skills"),
    enabled: Boolean(user),
    staleTime: 1000 * 60 * 10,
  })
  const h3Skills = skillsQuery.data?.skills || []
  const activeSkill = h3Skills.find((s) => s.id === selectedSkillId) || h3Skills[0]
  const selectedJob = selectedJobId ? jobs.find((job) => job.id === selectedJobId) : undefined

  const recentJobs = selectedJob ? jobs.filter((job) => job.id !== selectedJob.id) : jobs
  const assetEntries = useMemo(
    () => allJobs.flatMap((job) => {
      const roundEntries = job.rounds.flatMap((round) => round.generation_items.flatMap((item) => item.outputs.map((output, outputIndex) => ({
        id: `${item.id}:${outputIndex}`,
        job,
        output,
        outputIndex,
      }))))
      return roundEntries.length ? roundEntries : job.outputs.map((output, outputIndex) => ({
        id: `${job.id}:legacy:${outputIndex}`,
        job,
        output,
        outputIndex,
      }))
    }),
    [allJobs],
  )
  const visibleAssetEntries = useMemo(() => {
    const query = assetSearch.trim().toLocaleLowerCase()
    return assetEntries.filter(({ job, output }) => {
      const matchesType = assetMediaFilter === "all" || output.kind === assetMediaFilter
      const searchable = `${output.label} ${job.title ?? ""} ${job.prompt}`.toLocaleLowerCase()
      return assetSection === "history" && matchesType && (!query || searchable.includes(query))
    })
  }, [assetEntries, assetMediaFilter, assetSearch, assetSection])
  const assetGroups = useMemo(() => {
    const groups = new Map<string, { label: string; timestamp: number; entries: typeof visibleAssetEntries }>()
    visibleAssetEntries.forEach((entry) => {
      const date = new Date(entry.job.created_at)
      const key = Number.isNaN(date.getTime()) ? "unknown" : `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
      const current = groups.get(key)
      if (current) current.entries.push(entry)
      else groups.set(key, { label: formatAssetDate(entry.job.created_at), timestamp: Number.isNaN(date.getTime()) ? 0 : date.getTime(), entries: [entry] })
    })
    return Array.from(groups.values()).sort((left, right) => right.timestamp - left.timestamp)
  }, [visibleAssetEntries])
  const optionDefinitions = useMemo(() => workflowOptionDefinitions(workflow), [workflow])
  const primaryOptionDefinitions = useMemo(
    () => {
      const embeddedOptionNames = new Set(
        Object.values(optionDefinitions).flatMap((definition) => definition.ui_control === "visual-settings"
          ? definition.ui_companions ?? (definition.ui_companion ? [definition.ui_companion] : [])
          : []),
      )
      return Object.entries(optionDefinitions).filter(([name, definition]) => (
        definition.ui_group === "primary" && !embeddedOptionNames.has(name) && optionVisible(definition, optionValues)
      ))
    },
    [optionDefinitions, optionValues],
  )
  const advancedOptionDefinitions = useMemo(
    () => {
      const visualCompanions = new Set(
        Object.values(optionDefinitions)
          .filter((definition) => definition.ui_control === "visual-settings")
          .flatMap((definition) => definition.ui_companions ?? (definition.ui_companion ? [definition.ui_companion] : [])),
      )
      return Object.entries(optionDefinitions).filter(([name, definition]) => definition.ui_group === "advanced" && !visualCompanions.has(name) && optionVisible(definition, optionValues))
    },
    [optionDefinitions, optionValues],
  )
  const resultsForRound = (round: JobRound) => round.generation_items.flatMap((item) => item.outputs.map((output, outputIndex) => ({
    generationItemId: item.id,
    outputIndex,
    output,
    src: localMediaUrls[output.path] ?? output.download_url ?? mediaUrl(output.path),
  })))

  useEffect(() => {
    if (workflows.length && !workflows.some((item) => item.id === workflowId)) setWorkflowId(workflows[0].id)
  }, [workflowId, workflows])
  useEffect(() => {
    restoringComposerRef.current = false
    setIsComposerCompact(false)
  }, [selectedJobId])
  useEffect(() => {
    if (!selectedJob) return
    const syncComposerState = () => {
      const scrollRoot = document.documentElement
      const remaining = scrollRoot.scrollHeight - window.innerHeight - window.scrollY
      if (remaining <= 28) {
        restoringComposerRef.current = false
        setIsComposerCompact(false)
      } else if (!restoringComposerRef.current) {
        setIsComposerCompact(true)
      }
    }
    window.addEventListener("scroll", syncComposerState, { passive: true })
    return () => window.removeEventListener("scroll", syncComposerState)
  }, [selectedJob])
  useEffect(() => {
    if (restoringDraftRef.current) {
      restoringDraftRef.current = false
      return
    }
    setOptionValues(defaultOptionValues(workflow))
    setAdvancedOptionsOpen(false)
  }, [workflow?.id])
  useEffect(() => { referencesRef.current = references }, [references])
  useEffect(() => () => {
    const assets = [
      ...referencesRef.current,
      ...Object.values(draftsRef.current).flatMap((draft) => draft?.references ?? []),
    ]
    const seen = new Set<string>()
    releaseAssets(assets.filter((asset) => !seen.has(asset.id) && Boolean(seen.add(asset.id))))
  }, [])
  useEffect(() => {
    setReferencePreviewIndex((index) => index !== null && index >= references.length ? null : index)
  }, [references.length])
  useEffect(() => { localMediaUrlsRef.current = localMediaUrls }, [localMediaUrls])
  useEffect(() => () => {
    Object.values(localMediaUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
  }, [])
  useEffect(() => {
    let active = true
    if (!directoryApiSupported()) return
    void getResourceDirectory(user.id).then(async (handle) => {
      if (!active) return
      if (!handle) {
        setDirectoryState("missing")
        return
      }
      const permission = await directoryPermission(handle)
      if (!active) return
      setDirectoryHandle(handle)
      setDirectoryState(permission === "granted" ? "granted" : "prompt")
    }).catch(() => { if (active) setDirectoryState("missing") })
    return () => { active = false }
  }, [user.id])

  const loadLocalMedia = useCallback(async (handle: DirectoryHandleLike, sourceJobs: Job[]) => {
    const outputs = sourceJobs.flatMap((job) => job.rounds.flatMap((round) => round.generation_items.flatMap((item) => item.outputs.map((output) => ({ job, output })))))
      .filter(({ output }) => output.delivery_status !== "expired")
    const resolved = await Promise.all(outputs.map(async ({ output }) => [
      output.path,
      await localResourceUrl(handle, user.id, output.path),
    ] as const))
    setLocalMediaUrls((current) => {
      const next: Record<string, string> = {}
      for (const [key, url] of resolved) if (url) next[key] = url
      for (const [key, url] of Object.entries(current)) if (url !== next[key]) URL.revokeObjectURL(url)
      return next
    })
  }, [user.id])

  const connectDirectory = async (): Promise<DirectoryHandleLike | undefined> => {
    try {
      const handle = directoryHandle ?? await chooseResourceDirectory(user.id)
      const permission = await directoryPermission(handle, true)
      setDirectoryHandle(handle)
      setDirectoryState(permission === "granted" ? "granted" : "prompt")
      setStorageError(permission === "granted" ? undefined : "未获得本地目录写入权限")
      return permission === "granted" ? handle : undefined
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return undefined
      setStorageError(error instanceof Error ? error.message : "本地目录授权失败")
      return undefined
    }
  }

  const deliverOutput = useCallback(async (
    job: Job, generationItemId: string, outputIndex: number, output: Output,
    targetDirectory = directoryHandle, announce = false,
  ): Promise<boolean> => {
    if (!targetDirectory || !output?.download_url) return false
    const key = `${job.id}:${generationItemId}:${outputIndex}`
    if (deliveryInFlight.current.has(key)) return false
    deliveryInFlight.current.add(key)
    setPendingDeliveries((current) => ({ ...current, [key]: true }))
    try {
      await saveToResourceDirectory(
        targetDirectory, user.id, job.id, outputIndex, output.path, output.download_url, csrfToken, generationItemId,
      )
      await api<Job>(`/api/jobs/${job.id}/generations/${generationItemId}/outputs/${outputIndex}/delivered`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      })
      const url = await localResourceUrl(targetDirectory, user.id, output.path)
      if (url) setLocalMediaUrls((current) => ({ ...current, [output.path]: url }))
      setStorageError(undefined)
      await queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      if (announce) messageApi.success("已保存到本地目录")
      return true
    } catch (error) {
      const detail = error instanceof Error ? error.message : "保存本地资源失败"
      setStorageError(detail)
      if (announce) messageApi.error(detail)
      return false
    } finally {
      deliveryInFlight.current.delete(key)
      setPendingDeliveries((current) => {
        const { [key]: _, ...remaining } = current
        return remaining
      })
    }
  }, [csrfToken, directoryHandle, messageApi, queryClient, user.id])

  useEffect(() => {
    if (directoryHandle && directoryState === "granted") void loadLocalMedia(directoryHandle, allJobs)
  }, [directoryHandle, directoryState, allJobs, loadLocalMedia])
  useEffect(() => {
    if (!directoryHandle || directoryState !== "granted") return
    for (const job of allJobs) {
      for (const round of job.rounds) for (const item of round.generation_items) item.outputs.forEach((output, outputIndex) => {
        if (output.delivery_status !== "local" && output.download_url && !localMediaUrls[output.path]) void deliverOutput(job, item.id, outputIndex, output)
      })
    }
  }, [deliverOutput, directoryHandle, directoryState, allJobs, localMediaUrls])

  const requiresDirectorySetup = directoryState !== "granted"

  const createMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.set("mode", workflowId)
      form.set("prompt", prompt)
      form.set("negative_prompt", negativePrompt)
      if (workflow?.accepts_image_size) form.set("image_size", imageSize)
      if (Object.keys(optionDefinitions).length) {
        form.set("options", JSON.stringify(serializeOptionValues(optionDefinitions, optionValues)))
      }
      if (source) {
        form.set("source_job_id", source.jobId)
        form.set("source_generation_item_id", source.generationItemId)
        form.set("source_output_index", String(source.outputIndex))
      }
      references.forEach((asset) => form.append("references", asset.file))
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "提交任务失败")
      return response.json() as Promise<Job>
    },
    onSuccess: (job) => {
      setSelectedJobId(job.id)
      setIsSelectedPromptExpanded(false)
      queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      setHistoryOpen(false)
    },
  })

  const retryMutation = useMutation({
    mutationFn: async (jobId: string) => api<Job>(`/api/jobs/${jobId}/retry`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: (job) => {
      setSelectedJobId(job.id)
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
    },
  })

  const createRoundMutation = useMutation({
    mutationFn: async (job: Job) => {
      const form = new FormData()
      form.set("prompt", job.prompt)
      form.set("negative_prompt", job.negative_prompt)
      const response = await fetch(`/api/jobs/${job.id}/rounds`, { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "创建下一轮失败")
      return response.json() as Promise<Job>
    },
    onSuccess: (job) => { setSelectedJobId(job.id); void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] }) },
  })

  const retryFailedMutation = useMutation({
    mutationFn: async ({ jobId, roundId }: { jobId: string; roundId: string }) => api<Job>(`/api/jobs/${jobId}/rounds/${roundId}/retry-failed-items`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] }),
  })

  const metadataMutation = useMutation({
    mutationFn: async ({ jobId, title, pinned }: { jobId: string; title?: string | null; pinned?: boolean }) =>
      api<Job>(`/api/jobs/${jobId}`, jsonMutation(csrfToken, {
        ...(title !== undefined ? { title } : {}),
        ...(pinned !== undefined ? { pinned } : {}),
      }, "PATCH")),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      setRenameTarget(null)
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: async (job: Job) => api<{ id: string }>(`/api/jobs/${job.id}`, jsonMutation(csrfToken, undefined, "DELETE")),
    onSuccess: ({ id }) => {
      if (selectedJobId === id) {
        setSelectedJobId(undefined)
      }
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      messageApi.success("任务已删除")
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const optimizeMutation = useMutation({
    mutationFn: async (skillIdOverride?: string | void) => {
      const cleanPrompt = prompt.trim()
      if (!cleanPrompt) {
        throw new Error("请先输入简短的画面描述或想法")
      }
      const targetSkillId = (typeof skillIdOverride === "string" ? skillIdOverride : undefined) || selectedSkillId
      return requestJson<{ original_prompt: string; optimized_prompt: string; skill_id?: string }>(
        "/api/llm/optimize-prompt",
        jsonMutation(csrfToken, {
          prompt: cleanPrompt,
          media_type: mediaType,
          workflow_name: workflow?.name,
          skill_id: mediaType === "video" ? targetSkillId : undefined,
          reference_count: references.length,
          workflow_id: workflowId,
        }),
      )
    },

    onSuccess: (data) => {
      setPrompt(data.optimized_prompt)
      messageApi.success("提示词已使用 AI 优化完成")
    },
    onError: (error: Error) => {
      messageApi.warning(error.message || "提示词优化失败")
    },
  })


  const referenceCount = references.length

  const previewReference = referencePreviewIndex === null ? undefined : references[referencePreviewIndex]
  const openReferencePreview = (index: number) => {
    setReferencePreviewIndex(index)
    setReferencePreviewZoom(1)
    setReferencePreviewRotation(0)
    setReferencePreviewFullscreen(false)
  }
  const closeReferencePreview = () => {
    setReferencePreviewIndex(null)
    setReferencePreviewFullscreen(false)
  }
  const moveReferencePreview = (direction: -1 | 1) => {
    setReferencePreviewIndex((index) => index === null ? 0 : (index + direction + references.length) % references.length)
    setReferencePreviewZoom(1)
    setReferencePreviewRotation(0)
  }
  const optionError = Object.keys(optionDefinitions).length
    ? validateOptionValues(optionDefinitions, optionValues, referenceCount)
    : ""
  const canSubmit = Boolean(workflow?.available && prompt.trim() && referenceCount >= workflow.min_references && referenceCount <= workflow.max_references && !optionError && !createMutation.isPending)
  const referenceHint = workflow?.reference_mode === "collection"
    ? `已添加 ${referenceCount} / ${workflow.max_references} 张`
    : workflow?.reference_mode === "keyframes" ? "首帧必填更稳定，尾帧用于锁定结尾" : ""

  const saveImageResult = async (result: ImageResult) => {
    if (!selectedJob) return
    const handle = directoryHandle && directoryState === "granted" ? directoryHandle : await connectDirectory()
    if (!handle) return
    await deliverOutput(selectedJob, result.generationItemId, result.outputIndex, result.output, handle, true)
  }

  const createVideoFromImage = async (result: ImageResult) => {
    if (!selectedJob) return
    const handle = directoryHandle && directoryState === "granted" ? directoryHandle : await connectDirectory()
    if (!handle) {
      setStorageOpen(true)
      setStorageError("生成视频前需要选择可写入的本地目录。")
      return
    }
    let file = await localResourceFile(handle, user.id, result.output.path)
    if (!file && !await deliverOutput(selectedJob, result.generationItemId, result.outputIndex, result.output, handle, true)) return
    file ??= await localResourceFile(handle, user.id, result.output.path)
    if (!file) {
      setStorageOpen(true)
      setStorageError("未能读取原图，请重新授权目录后再试。")
      return
    }
    const asset = newAssets([file])[0]
    const videoWorkflow = (modesQuery.data?.modes ?? []).find((item) => item.id === "minimax-h3-i2v")
      ?? (modesQuery.data?.modes ?? []).find((item) => item.media_type === "video")
    if (!videoWorkflow || !selectedJob) return
    switchMedia("video")
    setWorkflowId(videoWorkflow.id)
    setOptionValues(defaultOptionValues(videoWorkflow))
    setReferences([asset])
    setSelectedJobId(undefined)
    setSource({ jobId: selectedJob.id, generationItemId: result.generationItemId, outputIndex: result.outputIndex })
    setPrompt("")
    messageApi.success("原图已带入视频创作")
    requestAnimationFrame(() => promptRef.current?.focus())
  }

  const resetCreation = () => {
    setWorkspaceView("generate")
    setTaskRailCollapsed(false)
    setPrompt("")
    setNegativePrompt("")
    setReferences((current) => { releaseAssets(current); return [] })
    setSelectedJobId(undefined)
    setIsSelectedPromptExpanded(false)
    setSource(undefined)
  }
  const switchMedia = (nextMedia: "image" | "video") => {
    if (nextMedia === mediaType) return
    draftsRef.current[mediaType] = { workflowId, prompt, negativePrompt, references, optionValues, selectedJobId, source }
    const draft = draftsRef.current[nextMedia]
    const targetWorkflows = (modesQuery.data?.modes ?? []).filter((item) => item.media_type === nextMedia)
    setMediaType(nextMedia)
    restoringDraftRef.current = Boolean(draft)
    setWorkflowId(draft?.workflowId ?? targetWorkflows[0]?.id ?? FALLBACK_WORKFLOW)
    setPrompt(draft?.prompt ?? "")
    setNegativePrompt(draft?.negativePrompt ?? "")
    setReferences(draft?.references ?? [])
    setOptionValues(draft?.optionValues ?? defaultOptionValues(targetWorkflows[0]))
    setSelectedJobId(draft?.selectedJobId)
    setSource(draft?.source)
    setAdvancedOptionsOpen(false)
  }
  const selectWorkflow = (nextWorkflowId: string) => {
    setWorkflowId(nextWorkflowId)
    setOptionValues(defaultOptionValues(workflows.find((item) => item.id === nextWorkflowId)))
    setAdvancedOptionsOpen(false)
    const nextWorkflow = workflows.find((item) => item.id === nextWorkflowId)
    if (nextWorkflow && references.length > nextWorkflow.max_references) {
      setReferences((current) => {
        releaseAssets(current.slice(nextWorkflow.max_references))
        return current.slice(0, nextWorkflow.max_references)
      })
    }
  }
  const appendFiles = (files: FileList | null) => {
    if (!files || !workflow) return
    const incoming = newAssets(files)
    setReferences((current) => {
      const room = workflow.max_references - current.length
      const allowed = incoming.slice(0, Math.max(0, room))
      releaseAssets(incoming.slice(allowed.length))
      return [...current, ...allowed]
    })
  }
  const replaceKeyframe = (index: number, files: FileList | null) => {
    if (!files?.[0]) return
    const next = newAssets([files[0]])[0]
    setReferences((current) => {
      const copy = [...current]
      if (index === 1 && !copy[0]) { releaseAssets([next]); return current }
      if (copy[index]) releaseAssets([copy[index]])
      copy[index] = next
      return copy
    })
  }
  const removeReference = (index: number) => setReferences((current) => {
    if (workflow?.reference_mode === "keyframes" && index === 0) {
      releaseAssets(current)
      return []
    }
    const target = current[index]
    if (target) releaseAssets([target])
    return current.filter((_, itemIndex) => itemIndex !== index)
  })
  const moveReference = (index: number, direction: -1 | 1) => setReferences((current) => {
    const target = index + direction
    if (target < 0 || target >= current.length) return current
    const copy = [...current]
    ;[copy[index], copy[target]] = [copy[target], copy[index]]
    return copy
  })
  const addPictureTag = (index: number) => {
    const token = `<Picture ${index}>`
    const input = promptRef.current
    const start = input?.selectionStart ?? prompt.length
    const end = input?.selectionEnd ?? prompt.length
    const before = prompt.slice(0, start)
    const after = prompt.slice(end)
    const padded = `${before && !/\s$/.test(before) ? " " : ""}${token}${after && !/^\s/.test(after) ? " " : ""}`
    setPrompt(`${before}${padded}${after}`)
    requestAnimationFrame(() => { input?.focus(); input?.setSelectionRange(start + padded.length, start + padded.length) })
  }
  const returnToComposer = useCallback((focusEditor = false) => {
    restoringComposerRef.current = true
    setIsComposerCompact(false)
    requestAnimationFrame(() => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" })
      if (focusEditor) promptRef.current?.focus()
    })
  }, [])
  const submit = (event: FormEvent) => { event.preventDefault(); if (canSubmit && !requiresDirectorySetup) createMutation.mutate() }
  const openRename = (job: Job) => { setRenameTarget(job); setRenameValue(job.title || job.prompt.slice(0, 40)) }
  const togglePinned = (job: Job) => metadataMutation.mutate({ jobId: job.id, pinned: !job.pinned })
  const confirmDelete = (job: Job) => Modal.confirm({
    title: "删除任务？",
    content: "任务记录与该任务的全部轮次将从工作台移除，已保存到本地目录的文件不会删除。",
    okText: "删除",
    cancelText: "取消",
    okButtonProps: { danger: true },
    onOk: () => deleteMutation.mutateAsync(job),
  })
  const reEditRound = async (job: Job, round: JobRound) => {
    const targetWorkflow = (modesQuery.data?.modes ?? []).find((item) => item.id === round.mode)
    if (!targetWorkflow) {
      messageApi.error("这个任务使用的工作流当前不可用，无法带回编辑器。")
      return
    }
    const nextOptions: Record<string, OptionInputValue> = {
      ...defaultOptionValues(targetWorkflow),
      ...Object.fromEntries(Object.entries(round.options ?? {}).map(([name, value]) => [name, typeof value === "boolean" ? value : String(value)])),
    }
    setWorkflowId(targetWorkflow.id)
    setOptionValues(nextOptions)
    setPrompt(round.prompt)
    setNegativePrompt(job.negative_prompt)
    setSource(undefined)
    setAdvancedOptionsOpen(false)
    try {
      const referenceFiles = await Promise.all(round.references.map(async (reference) => {
        const response = await fetch(reference.url)
        if (!response.ok) throw new Error(`参考图 ${reference.index} 无法读取`)
        const blob = await response.blob()
        return new File([blob], `参考图-${reference.index}`, { type: blob.type || "image/png" })
      }))
      const nextReferences = newAssets(referenceFiles)
      setReferences((current) => { releaseAssets(current); return nextReferences })
    } catch {
      setReferences((current) => { releaseAssets(current); return [] })
      messageApi.warning("已带回提示词和参数；原参考图无法读取，请重新添加。")
    }
    setSelectedJobId(undefined)
    setIsSelectedPromptExpanded(false)
    requestAnimationFrame(() => {
      document.getElementById("studio-composer")?.scrollIntoView({ behavior: "smooth", block: "center" })
      promptRef.current?.focus()
    })
  }

  return (
    <div className="studio-light min-h-screen overflow-x-hidden bg-[#f8f9fa] text-[#171a1f]">
      {messageContext}
      <header className="studio-header fixed inset-x-0 top-0 z-50 flex h-14 items-center justify-between border-b border-black/[0.05] bg-white px-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex items-center gap-2 text-[#171a1f]">
            <span className="grid size-7 place-items-center rounded-md border border-[#7655ff] text-[#a28cff]"><Sparkles size={15} /></span>
            <span className="hidden text-[15px] font-semibold sm:inline">ZLY AI Studio</span>
          </div>
          <span className="h-6 w-px bg-black/[0.08]" />
          <h1 className="hidden truncate text-base font-medium lg:block">创作工作台</h1>
        </div>
        <div className="flex items-center gap-2 text-[#b6b6bf]">
          <button type="button" title="本地资源目录" onClick={() => { setStorageOpen((open) => !open); setAccountOpen(false) }} className={`grid size-9 place-items-center rounded-lg border transition sm:flex sm:w-auto sm:gap-2 sm:px-3 ${directoryState === "granted" ? "border-emerald-400/25 bg-emerald-400/[0.07] text-emerald-300" : "border-white/10 bg-white/[0.04] hover:bg-white/[0.08]"}`}><HardDrive size={16} /><span className="hidden text-xs sm:inline">{directoryState === "granted" ? "本地目录" : "设置存储"}</span></button>
          <Tooltip title={mediaType === "image" ? healthQuery.data?.grs?.message : undefined}>
            <span className="hidden h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-xs md:flex"><span className={`size-2 rounded-full ${(mediaType === "image" ? healthQuery.data?.grs?.available : healthQuery.data?.comfy.reachable) ? "bg-emerald-400" : "bg-amber-400"}`} />{mediaType === "image" ? "GRS" : "ComfyUI"}</span>
          </Tooltip>
          <button type="button" title="账号菜单" onClick={() => { setAccountOpen((open) => !open); setStorageOpen(false) }} className="flex size-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/[0.08] sm:w-auto sm:gap-2 sm:px-3"><UserRound size={16} /><span className="hidden max-w-24 truncate text-xs text-[#e1e1e6] sm:inline">{user.display_name}</span></button>
          {storageOpen ? <section className="absolute right-3 top-[60px] w-[min(360px,calc(100vw-24px))] rounded-xl border border-white/10 bg-[#1b1c22] p-4 shadow-[0_20px_50px_rgba(0,0,0,0.45)] sm:right-16">
            <div className="flex items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#7655ff]/15 text-[#a691ff]"><HardDrive size={18} /></span><div><h2 className="text-sm font-medium text-white">员工电脑本地目录</h2><p className="mt-1 text-xs leading-5 text-[#93939d]">生成完成后自动写入授权目录，成功回执后清理服务器暂存。</p></div></div>
            {directoryState === "unsupported" ? <p className="mt-4 rounded-lg bg-amber-400/[0.08] px-3 py-2.5 text-xs leading-5 text-amber-200">当前访问环境不支持目录写入。请使用最新版 Chrome 或 Edge，并通过 HTTPS 或本机 127.0.0.1 访问。</p> : null}
            {storageError ? <p className="mt-4 rounded-lg bg-red-500/10 px-3 py-2.5 text-xs leading-5 text-red-200">{storageError}</p> : null}
            <button type="button" disabled={directoryState === "unsupported"} onClick={() => void connectDirectory()} className="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-[#7047f6] text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"><FolderOpen size={15} />{directoryState === "granted" ? "更换资源目录" : directoryState === "prompt" ? "重新授权目录" : "选择资源目录"}</button>
          </section> : null}
          {accountOpen ? <section className="absolute right-3 top-[60px] w-56 overflow-hidden rounded-xl border border-white/10 bg-[#1b1c22] p-2 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
            <div className="px-2 py-2"><p className="truncate text-sm font-medium text-white">{user.display_name}</p><p className="mt-0.5 truncate text-xs text-[#85858f]">{user.username}</p></div>
            {onOpenAdmin ? <button type="button" onClick={onOpenAdmin} className="flex h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-sm text-[#d6d6dc] hover:bg-white/[0.06]"><Users size={16} />管理设置</button> : null}
            <button type="button" disabled={logoutPending} onClick={onLogout} className="flex h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-sm text-[#d6d6dc] hover:bg-white/[0.06] disabled:opacity-40">{logoutPending ? <LoaderCircle className="animate-spin" size={16} /> : <LogOut size={16} />}退出登录</button>
          </section> : null}
        </div>
      </header>

      {requiresDirectorySetup ? <section role="dialog" aria-modal="true" aria-labelledby="directory-setup-title" className="fixed inset-0 z-[100] grid place-items-center bg-[#0d0e12]/90 px-4 py-6 backdrop-blur-sm">
        <div className="w-full max-w-md border border-white/[0.12] bg-[#1b1c22] p-5 shadow-[0_24px_64px_rgba(0,0,0,0.52)] sm:p-6">
          <span className="grid size-11 place-items-center rounded-lg bg-[#7655ff]/15 text-[#ad9bff]">
            {directoryState === "checking" ? <LoaderCircle className="animate-spin" size={21} /> : <HardDrive size={21} />}
          </span>
          <h2 id="directory-setup-title" className="mt-5 text-lg font-semibold text-white">设置作品存储目录</h2>
          {directoryState === "checking" ? <p className="mt-2 text-sm leading-6 text-[#b4b4be]">正在检查此账号已授权的本地目录。</p> : <p className="mt-2 text-sm leading-6 text-[#b4b4be]">请选择员工电脑上的目录。新作品会自动保存到该目录的 ZLY AI Studio 子文件夹，完成交付后工作台会清理服务器暂存。</p>}
          {directoryState === "unsupported" ? <p className="mt-4 bg-amber-400/[0.08] px-3 py-2.5 text-xs leading-5 text-amber-200">当前访问环境无法授权本地目录。请使用最新版 Chrome 或 Edge，并通过 HTTPS 或本机 127.0.0.1 打开工作台。</p> : null}
          {storageError ? <p className="mt-4 bg-red-500/10 px-3 py-2.5 text-xs leading-5 text-red-200">{storageError}</p> : null}
          <button type="button" autoFocus={directoryState !== "checking"} disabled={directoryState === "checking" || directoryState === "unsupported"} onClick={() => void connectDirectory()} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#7047f6] text-sm font-medium text-white transition hover:bg-[#7c58f8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a795ff] disabled:cursor-not-allowed disabled:opacity-45">
            <FolderOpen size={17} />{directoryState === "prompt" ? "重新授权目录" : "选择存储目录"}
          </button>
          <button type="button" disabled={logoutPending} onClick={onLogout} className="mt-2 flex h-10 w-full items-center justify-center gap-2 rounded-lg text-sm text-[#b4b4be] transition hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a795ff] disabled:opacity-45">
            {logoutPending ? <LoaderCircle className="animate-spin" size={16} /> : <LogOut size={16} />}退出登录
          </button>
        </div>
      </section> : null}

      <div className={`studio-workspace relative mt-14 flex min-h-[calc(100vh-56px)] bg-[#f8f9fa] ${taskRailCollapsed ? "studio-task-rail-collapsed" : ""} ${workspaceView === "assets" ? "studio-asset-view" : ""}`}>
        <aside className="studio-icon-rail fixed bottom-0 left-0 top-14 z-20 hidden w-[76px] flex-col items-center border-r border-black/[0.05] bg-white pt-5 xl:flex">
          <div className="flex flex-col items-center gap-2">
            <button type="button" title="生成" aria-label="生成" onClick={() => { setWorkspaceView("generate"); setTaskRailCollapsed(false) }} className={`studio-global-nav-item ${workspaceView === "generate" ? "studio-global-nav-item-active" : ""}`}><Sparkles size={19} /><span>生成</span></button>
            <button type="button" title="资产" aria-label="资产" onClick={() => { setWorkspaceView("assets"); setTaskRailCollapsed(true) }} className={`studio-global-nav-item ${workspaceView === "assets" ? "studio-global-nav-item-active" : ""}`}><FolderOpen size={19} /><span>资产</span></button>
          </div>
          {workspaceView === "generate" && taskRailCollapsed ? <Tooltip title="展开任务栏" placement="right"><button type="button" title="展开任务栏" aria-label="展开任务栏" onClick={() => setTaskRailCollapsed(false)} className="studio-task-rail-reopen"><PanelLeftOpen size={17} /></button></Tooltip> : null}
        </aside>

        <aside className="studio-task-rail fixed bottom-0 left-0 top-14 z-20 hidden w-[240px] flex-col border-r border-black/[0.05] bg-white xl:left-[76px] lg:flex">
          <div className="border-b border-white/[0.08] px-4 pb-3 pt-4">
            <div className="flex items-center justify-between gap-3">
              <div><p className="text-sm font-medium text-[#171a1f]">开启创作</p><p className="mt-1 text-[11px] text-[#7c8794]">{jobs.length} 个{mediaType === "image" ? "图片" : "视频"}任务</p></div>
              <button type="button" title="收起任务栏" aria-label="收起任务栏" aria-expanded="true" onClick={() => setTaskRailCollapsed(true)} className="studio-task-rail-collapse grid size-8 place-items-center rounded-lg text-[#65707c] hover:bg-black/[0.04] hover:text-[#171a1f]"><PanelLeftClose size={16} /></button>
            </div>
            <button type="button" onClick={resetCreation} className="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-black/[0.06] bg-white text-sm text-[#27303a] transition hover:bg-[#f5f7f9]"><Pencil size={15} />新对话</button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col pt-3">
            <section className="studio-task-section">
              <p className="studio-task-section-title">当前创作</p>
              {selectedJob ? <TaskRail jobs={[selectedJob]} selectedJobId={selectedJob.id} localMediaUrls={localMediaUrls} onSelect={(jobId) => { setSelectedJobId(jobId); setIsSelectedPromptExpanded(false) }} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} scrollMode="content" showEmpty={false} /> : <p className="px-4 pb-3 text-xs text-[#98a2ad]">新对话会从这里开始</p>}
            </section>
            <section className="flex min-h-0 flex-1 flex-col">
              <p className="studio-task-section-title">最近</p>
              <TaskRail jobs={recentJobs} selectedJobId={selectedJob?.id} localMediaUrls={localMediaUrls} onSelect={(jobId) => { setSelectedJobId(jobId); setIsSelectedPromptExpanded(false) }} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} />
            </section>
          </div>
        </aside>

        <div className="absolute left-4 top-4 z-30 flex w-[136px] flex-col gap-2 lg:hidden">
          <button type="button" onClick={resetCreation} className="flex h-9 items-center justify-center gap-2 rounded-[18px] bg-[#7047f6] px-3 text-sm text-white hover:bg-[#7c58f8]"><Plus size={16} />新建任务</button>
          <button type="button" onClick={() => setHistoryOpen((open) => !open)} className={`flex h-9 items-center justify-center gap-2 rounded-[18px] border px-3 text-sm transition ${historyOpen ? "border-white bg-white/10" : "border-[#6947ee] bg-[#5d45aa]/20 hover:bg-[#5d45aa]/35"}`}><ListChecks size={16} />任务列表</button>
        </div>

        {historyOpen && <section className="absolute left-4 top-[106px] z-40 flex h-[420px] w-[min(392px,calc(100vw-32px))] flex-col overflow-hidden rounded-xl border border-black/[0.08] bg-white shadow-[0_16px_36px_rgba(22,31,44,0.16)] lg:hidden">
          <div className="flex items-center justify-between border-b border-black/[0.05] px-4 pb-3 pt-4"><h2 className="text-base font-medium text-[#171a1f]">任务列表</h2><button type="button" onClick={() => setHistoryOpen(false)} title="关闭任务列表" className="grid size-8 place-items-center rounded-lg text-[#65707c] hover:bg-black/[0.05] hover:text-[#171a1f]"><X size={15} /></button></div>
          <TaskRail compact jobs={jobs} selectedJobId={selectedJob?.id} localMediaUrls={localMediaUrls} onSelect={(jobId) => { setSelectedJobId(jobId); setIsSelectedPromptExpanded(false); setHistoryOpen(false) }} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} />
        </section>}

        <main className={`relative mx-auto min-h-[calc(100vh-56px)] w-full min-w-0 max-w-[1180px] px-4 pb-10 pt-[112px] sm:px-8 lg:pt-12 ${workspaceView === "assets" ? "studio-asset-main" : ""}`}>
          {workspaceView === "assets" ? <section className="studio-asset-library" aria-label="资产">
            <div className="studio-asset-toolbar">
              <Tabs
                className="studio-asset-tabs"
                activeKey={assetSection}
                onChange={(key) => setAssetSection(key as "history" | "subject" | "canvas")}
                items={[{ key: "history", label: "生成历史" }, { key: "subject", label: "主体" }, { key: "canvas", label: "画布" }]}
              />
              <div className="studio-asset-actions">
                <Input value={assetSearch} onChange={(event) => setAssetSearch(event.target.value)} allowClear prefix={<Search className="studio-asset-search-icon" size={15} />} placeholder="搜索" aria-label="搜索资产" />
                <button type="button" className="studio-asset-action-button">批量操作</button>
                <button type="button" className="studio-asset-action-button studio-asset-action-primary">去剪映剪辑 <ExternalLink size={14} /></button>
              </div>
            </div>
            <div className="studio-asset-filter-bar">
              <div className="studio-asset-type-filters">
                {[{ key: "all", label: "全部" }, { key: "image", label: "图片" }, { key: "video", label: "视频" }, { key: "audio", label: "音频" }, { key: "document", label: "文档" }].map((filter) => <button key={filter.key} type="button" onClick={() => setAssetMediaFilter(filter.key as AssetMediaFilter)} className={`studio-asset-filter ${assetMediaFilter === filter.key ? "studio-asset-filter-active" : ""}`}>{filter.label}</button>)}
              </div>
              <div className="studio-asset-sort-tools">
                <button type="button" className="studio-asset-sort-button">筛选 <ChevronDown size={14} /></button>
                <button type="button" className="studio-asset-sort-button">时间 <ChevronDown size={14} /></button>
                <button type="button" className="studio-asset-sort-button">排序 <ChevronDown size={14} /></button>
              </div>
            </div>
            {assetGroups.length ? <div className="studio-asset-groups">{assetGroups.map((group) => <section key={`${group.label}-${group.timestamp}`} className="studio-asset-group"><h2>{group.label}</h2><div className="studio-asset-grid">{group.entries.map(({ id, job, output }) => <button key={id} type="button" onClick={() => {
              if (output.kind === "image") setPreviewImage({ src: localMediaUrls[output.path] ?? output.download_url ?? mediaUrl(output.path), alt: output.label })
              else { if (job.media_type !== mediaType) switchMedia(job.media_type); setWorkspaceView("generate"); setTaskRailCollapsed(false); setSelectedJobId(job.id) }
            }} className="studio-asset-media-card group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/35"><div className="studio-asset-media-frame"><MediaTile item={output} localUrl={localMediaUrls[output.path]} />{output.kind === "video" ? <span className="studio-asset-duration">{assetDuration(job, output.kind)}</span> : null}</div></button>)}</div></section>)}</div> : <div className="studio-asset-empty"><FolderOpen size={22} /><p>{assetSection === "history" ? "暂无符合条件的资产" : assetSection === "subject" ? "暂无主体资产" : "暂无画布资产"}</p></div>}
          </section> : <>
          {!selectedJob && <div className="relative z-10 mb-[112px] pt-12 text-center xl:mb-[130px]"><h2 className="text-3xl font-semibold tracking-normal text-[#171a1f] sm:text-4xl">今天想创作什么？</h2><p className="mt-3 text-base text-[#65707c]">输入想法，AI 帮你实现创意</p></div>}

          {selectedJob && <section className="studio-task-stream relative z-10 mb-8" aria-label="任务详情">
            {selectedJob.rounds.map((round) => {
              const roundResults = resultsForRound(round)
              const creativeParameters = round.request_parameters.filter((parameter) => parameter.name !== "prompt" && parameter.visibility !== "internal")
              const runtimeParameters = round.request_parameters.filter((parameter) => parameter.visibility === "internal")
              const roundProgress = Math.max(0, Math.min(100, round.progress ?? 0))
              const canGenerateAgain = selectedJob.status === "succeeded" || selectedJob.status === "partial"
              const canRetryRound = round.status === "partial" || round.status === "failed" || round.status === "interrupted"
              const cover = roundResults[0]?.output
              return <article key={round.id} className="studio-round">
                <header className="studio-round-header flex min-w-0 gap-3">
                  <div className="studio-round-cover grid size-12 shrink-0 place-items-center overflow-hidden rounded-md bg-[#f2f4f6] text-[#7c8794]">
                    {cover ? <MediaTile item={cover} localUrl={localMediaUrls[cover.path]} /> : round.references[0] ? <img src={round.references[0].url} alt="任务参考图" className="h-full w-full object-cover" /> : <Clapperboard size={18} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-start gap-2">
                      <p id={`round-prompt-${round.id}`} className={`min-w-0 flex-1 text-sm leading-5 text-[#1f2933] ${isSelectedPromptExpanded ? "whitespace-pre-wrap break-words" : "line-clamp-2"}`}>{round.prompt}</p>
                      <button type="button" onClick={() => setIsSelectedPromptExpanded((expanded) => !expanded)} aria-controls={`round-prompt-${round.id}`} aria-expanded={isSelectedPromptExpanded} className="shrink-0 text-xs text-[#4d6bfe] hover:text-[#314bc7]">{isSelectedPromptExpanded ? "收起" : "展开"}</button>
                    </div>
                    <p className={`studio-round-status mt-1.5 text-xs ${statusColor[round.status]}`}>第 {round.sequence} 轮 · {statusText[round.status]} · {round.stage}</p>
                  </div>
                </header>

                {(creativeParameters.length > 0 || runtimeParameters.length > 0) && <details className="studio-round-details">
                  <summary>任务详情</summary>
                  <dl className="studio-round-parameter-list">
                    {creativeParameters.map((parameter) => <div key={parameter.name}><dt>{parameter.label}</dt><dd>{parameterValue(parameter)}</dd></div>)}
                    {runtimeParameters.map((parameter) => <div key={parameter.name} className="studio-round-runtime-parameter"><dt>{parameter.label}</dt><dd>{parameterValue(parameter)}</dd></div>)}
                  </dl>
                </details>}

                {round.references.length > 0 && <div className="studio-round-references">{round.references.map((reference) => <button key={reference.index} type="button" onClick={() => setPreviewImage({ src: reference.url, alt: `参考图 ${reference.index}` })} className="group relative h-14 w-20 shrink-0 overflow-hidden rounded-lg border border-black/[0.08] bg-[#f2f4f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/40">
                  <img src={reference.url} alt={`参考图 ${reference.index}`} className="h-full w-full object-cover transition duration-200 group-hover:scale-105" />
                  <span className="studio-reference-thumb-label absolute inset-x-0 bottom-0 px-1.5 py-1 text-left text-[10px]">参考图 {reference.index}</span>
                </button>)}</div>}

                {round.status === "running" && <div className="studio-round-progress flex items-center gap-2">
                  <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-[#e8ecf1]" role="progressbar" aria-label={`第 ${round.sequence} 轮生成进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={roundProgress}><div className="h-full rounded-full bg-[#4d6bfe] transition-[width] duration-500" style={{ width: `${roundProgress}%` }} /></div>
                  <span className="w-9 text-right text-[11px] tabular-nums text-[#65707c]">{roundProgress}%</span>
                </div>}

                {roundResults.length > 0 && <Suspense fallback={<div className="flex min-h-56 items-center justify-center text-sm text-[#65707c]">正在加载结果...</div>}>
                  {mediaType === "image" ? <ImageStudioModule embedded showHeading={false} results={roundResults as ImageResult[]} roundCount={1} pendingSave={(result) => Boolean(pendingDeliveries[`${selectedJob.id}:${result.generationItemId}:${result.outputIndex}`])} isLocallySaved={(result) => Boolean(localMediaUrls[result.output.path])} onSave={(result) => void saveImageResult(result)} onCreateVideo={(result) => void createVideoFromImage(result)} onPreview={(result) => result.src && setPreviewImage({ src: result.src, alt: result.output.label })} /> : <VideoStudioModule embedded showHeading={false} results={roundResults as VideoResult[]} roundCount={1} onSave={(result) => directoryState === "granted" ? void deliverOutput(selectedJob, result.generationItemId, result.outputIndex, result.output) : void connectDirectory()} />}
                </Suspense>}

                <div className="studio-round-actions" aria-label={`第 ${round.sequence} 轮操作`}>
                  <button type="button" onClick={() => void reEditRound(selectedJob, round)} className="studio-round-action"><Pencil size={16} />重新编辑</button>
                  {canGenerateAgain && <button type="button" disabled={createRoundMutation.isPending} onClick={() => createRoundMutation.mutate(selectedJob)} className="studio-round-action">{createRoundMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <RotateCw size={16} />}再次生成</button>}
                  {canRetryRound && mediaType === "image" && <button type="button" disabled={retryFailedMutation.isPending} onClick={() => retryFailedMutation.mutate({ jobId: selectedJob.id, roundId: round.id })} className="studio-round-action">{retryFailedMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <RotateCw size={16} />}重试失败项</button>}
                  {canRetryRound && mediaType === "video" && <button type="button" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedJob.id)} className="studio-round-action">{retryMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <Send size={16} />}重新提交</button>}
                  <Dropdown trigger={["click"]} popupRender={(menu) => <div className="studio-task-menu studio-round-menu">{menu}</div>} menu={{ items: [{ key: "delete", danger: true, icon: <Trash2 size={14} />, label: "删除任务" }], onClick: ({ domEvent }) => { domEvent.stopPropagation(); confirmDelete(selectedJob) } }}>
                    <button type="button" aria-label={`更多操作：第 ${round.sequence} 轮`} title="更多操作" className="studio-round-action studio-round-more"><MoreHorizontal size={18} /></button>
                  </Dropdown>
                </div>
              </article>
            })}
          </section>}

          {isComposerCompact && <button type="button" onClick={() => returnToComposer()} className="studio-return-bottom" title="回到底部"><span>回到底部</span><ChevronDown size={15} /></button>}
          <form id="studio-composer" onSubmit={submit} className={`studio-composer-form relative z-20 mx-auto max-w-[1080px] border border-black/[0.05] bg-white p-4 shadow-[0_16px_36px_rgba(22,31,44,0.10)] sm:rounded-[24px] sm:p-5 lg:sticky lg:bottom-5 ${isComposerCompact ? "studio-composer-collapsed" : ""}`}>
            <div className="absolute -top-8 right-7 flex max-w-[calc(100%-56px)] items-center gap-1.5 text-sm text-[#babac3]">
              <span className="studio-ai-badge grid size-5 shrink-0 place-items-center rounded-full bg-[#7046df] text-[10px] font-semibold text-white">AI</span>
              {mediaType === "image" ? <>
                <span className="whitespace-nowrap">GRS 云端生图</span>
                <Tooltip title={grsBalanceUnavailable ? "余额暂不可用，请稍后重试。" : grsBalanceStale ? "上游余额刷新暂不可用，当前显示上一次查询结果。" : grsBalanceQuery.data?.queried_at ? `最近查询：${formatTime(grsBalanceQuery.data.queried_at)}` : "正在查询上游余额。"}>
                  <span aria-label="GRS 上游余额" className={`flex min-w-0 items-center gap-1 rounded-md border border-white/[0.1] bg-white/[0.045] px-2 py-0.5 text-xs ${grsBalanceStale ? "text-amber-200" : "text-[#d8d8df]"}`}>
                    {grsBalanceQuery.isFetching ? <LoaderCircle className="shrink-0 animate-spin text-[#b6a4ff]" size={13} /> : <WalletCards className="shrink-0 text-[#b6a4ff]" size={13} />}
                    <span className="whitespace-nowrap">余额 {grsBalanceUnavailable ? "暂不可用" : formatGrsBalance(grsBalanceQuery.data?.credits)}</span>
                  </span>
                </Tooltip>
              </> : <>本地推理 <strong className="text-[#f0d567]">GPU</strong></>}
            </div>

            <div className="studio-composer-prompt grid min-h-[142px] grid-cols-1 gap-4 sm:grid-cols-[minmax(102px,154px)_minmax(0,1fr)]">
              <ReferencePanel workflow={workflow} references={references} onAppend={appendFiles} onReplaceKeyframe={replaceKeyframe} onRemove={removeReference} onMove={moveReference} onPreview={openReferencePreview} fileInputRef={fileInputRef} />
              <div className="studio-composer-editor min-w-0 pt-1">
                <div className="studio-composer-editor-meta mb-2 flex items-center justify-between gap-3">
                  <span className="text-xs text-[#aaaab4]">{workflow?.name || "正在加载工作流"}</span>
                  <div className="flex items-center gap-2">
                    {mediaType === "video" && h3Skills.length > 0 ? (
                      <Dropdown
                        placement="bottomRight"
                        trigger={["click", "hover"]}
                        menu={{
                          items: [
                            {
                              key: "header",
                              type: "group",
                              label: <span className="text-[11px] font-semibold text-[#6b7280]">MiniMax H3 官方技能体系</span>,
                            },
                            ...h3Skills.map((skill) => ({
                              key: skill.id,
                              label: (
                                <div className="flex items-start gap-2 py-1 max-w-[280px]">
                                  <span className="text-base shrink-0 select-none leading-none pt-0.5">{skill.icon}</span>
                                  <div className="min-w-0 flex-1">
                                    <div className={`text-xs font-semibold ${selectedSkillId === skill.id ? "text-[#7047f6]" : "text-[#1f2937]"}`}>
                                      {skill.name} {selectedSkillId === skill.id && <span className="text-[10px] text-[#7047f6] ml-1 font-normal">● 当前</span>}
                                    </div>
                                    <div className="text-[11px] text-[#6b7280] leading-tight mt-0.5">{skill.description}</div>
                                  </div>
                                </div>
                              ),
                              onClick: () => {
                                setSelectedSkillId(skill.id)
                                optimizeMutation.mutate(skill.id)
                              },
                            })),
                          ],
                        }}
                      >
                        <button
                          type="button"
                          disabled={optimizeMutation.isPending}
                          onClick={() => optimizeMutation.mutate(selectedSkillId)}
                          title="点击使用当前技能优化，或展开切换 MiniMax H3 官方技能风格"
                          className="flex items-center gap-1 rounded-md border border-[#7655ff]/35 bg-[#7655ff]/15 px-2 py-0.5 text-xs text-[#7047f6] font-medium transition hover:bg-[#7655ff]/25 hover:text-[#5a32df] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {optimizeMutation.isPending ? <LoaderCircle className="animate-spin text-[#7047f6]" size={12} /> : <WandSparkles size={12} className="text-[#7047f6]" />}
                          <span>{activeSkill?.name ? `${activeSkill.icon} ${activeSkill.name}` : "AI 优化"}</span>
                          <ChevronDown size={11} className="opacity-60 text-[#7047f6]" />
                        </button>
                      </Dropdown>
                    ) : (
                      <button
                        type="button"
                        disabled={optimizeMutation.isPending}
                        onClick={() => optimizeMutation.mutate()}
                        title="AI 提示词优化（Midjourney / FLUX 风格增强）"
                        className="flex items-center gap-1 rounded-md border border-[#7655ff]/35 bg-[#7655ff]/15 px-2 py-0.5 text-xs text-[#7047f6] font-medium transition hover:bg-[#7655ff]/25 hover:text-[#5a32df] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {optimizeMutation.isPending ? <LoaderCircle className="animate-spin text-[#7047f6]" size={12} /> : <WandSparkles size={12} className="text-[#7047f6]" />}
                        <span>AI 优化</span>
                      </button>
                    )}

                    <span className="truncate text-[11px] text-[#797982]">{referenceHint}</span>
                  </div>
                </div>
                <textarea ref={promptRef} value={prompt} onFocus={() => { if (isComposerCompact) returnToComposer(true) }} onChange={(event) => setPrompt(event.target.value)} placeholder={workflow?.description || "描述镜头、动作、运镜、音效和氛围"} className="studio-prompt-input h-[106px] w-full resize-none border-0 bg-transparent p-0 text-[15px] leading-6 text-[#d7d7dc] outline-none placeholder:text-[#777780]" />
                {workflow?.reference_mode === "collection" && references.length > 0 && <div className="studio-picture-tags mt-2 flex flex-wrap gap-1.5">{references.map((asset, index) => <button key={asset.id} type="button" onClick={() => addPictureTag(index + 1)} className="rounded-md border border-[#7047ff]/40 bg-[#7047ff]/10 px-2 py-1 text-[11px] text-[#b5a4ff] hover:bg-[#7047ff]/20">&lt;Picture {index + 1}&gt;</button>)}</div>}
              </div>
            </div>


            <div className="studio-composer-toolbar mt-4 flex flex-col gap-3 border-t border-white/[0.08] pt-4 lg:flex-row lg:items-center">
              <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:flex sm:flex-wrap">
                <div className="studio-media-select flex h-9 min-w-0 items-center rounded-lg border border-[#37373b] bg-[#222226] px-1 shadow-[0_6px_16px_rgba(0,0,0,0.12)] sm:w-[140px]">
                  <Select aria-label="选择生成类型" value={mediaType} onChange={(value) => switchMedia(value as "image" | "video")} className="studio-select min-w-0 flex-1" popupClassName="studio-select-popup studio-media-select-popup" options={[{ value: "image", label: <span className="studio-select-option"><ImagePlus size={14} />图片生成</span> }, { value: "video", label: <span className="studio-select-option"><Video size={14} />视频生成</span> }]} />
                </div>
                <div className="studio-control-shell flex h-9 min-w-0 items-center gap-2 rounded-lg border border-[#37373b] bg-[#222226] px-3 shadow-[0_6px_16px_rgba(0,0,0,0.12)] sm:w-[248px]">
                  <Settings2 size={16} className="shrink-0 text-[#947dff]" />
                  <Select aria-label="选择工作流" value={workflowId} onChange={(value) => selectWorkflow(String(value))} className="studio-select min-w-0 flex-1" popupClassName="studio-select-popup studio-workflow-select-popup" options={workflows.map((item) => ({ value: item.id, label: item.name, title: item.description }))} />
                </div>
                {primaryOptionDefinitions.map(([name, definition]) => <OptionControl
                  key={name}
                  name={name}
                  definition={definition}
                  value={optionValues[name] ?? ""}
                  definitions={optionDefinitions}
                  values={optionValues}
                  compact
                  onChange={(optionName, value) => setOptionValues((current) => ({ ...current, [optionName]: value }))}
                />)}
                {workflow?.accepts_image_size && <div className="studio-control-shell flex h-9 min-w-0 items-center gap-2 rounded-lg border border-[#37373b] bg-[#222226] px-3 shadow-[0_6px_16px_rgba(0,0,0,0.12)] sm:w-[172px]"><Maximize2 size={16} className="shrink-0 text-[#947dff]" /><Select aria-label="选择图片尺寸" value={imageSize} onChange={(value) => setImageSize(String(value))} className="studio-select min-w-0 flex-1" popupClassName="studio-select-popup" options={(modesQuery.data?.image_sizes ?? []).map((size) => ({ value: size, label: size }))} /></div>}
                {advancedOptionDefinitions.length > 0 && <button type="button" aria-expanded={advancedOptionsOpen} onClick={() => setAdvancedOptionsOpen((open) => !open)} className="flex h-10 items-center justify-center gap-2 rounded-lg border border-[#37373b] bg-[#222226] px-3 text-sm text-[#d8d8df] transition hover:bg-[#29292f] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7047ff]/45"><SlidersHorizontal size={16} className="text-[#947dff]" />更多设置</button>}
              </div>
              <Tooltip title={!workflow?.available ? workflow?.unavailable_reason : undefined}>
                <button type="submit" disabled={!canSubmit} className="flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-[#7047f6] px-5 text-sm text-white shadow-[0_8px_24px_rgba(83,48,190,0.26)] hover:bg-[#7c58f8] disabled:cursor-not-allowed disabled:bg-[#55555c] disabled:text-[#bdbdc4] lg:w-[154px]">{createMutation.isPending ? <LoaderCircle className="animate-spin" size={17} /> : <Sparkles size={17} />}{mediaType === "image" ? "开始生图" : "开始生成"}</button>
              </Tooltip>
            </div>
            {advancedOptionsOpen && advancedOptionDefinitions.length > 0 && <section aria-label="更多生成设置" className="mt-4 border-t border-white/[0.08] pt-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {advancedOptionDefinitions.map(([name, definition]) => <OptionControl
                  key={name}
                  name={name}
                  definition={definition}
                  value={optionValues[name] ?? ""}
                  definitions={optionDefinitions}
                  values={optionValues}
                  onChange={(optionName, value) => setOptionValues((current) => ({ ...current, [optionName]: value }))}
                />)}
              </div>
            </section>}
            {optionError && <p className="mt-3 text-xs text-amber-200">{optionError}</p>}
            {!workflow?.available && workflow?.unavailable_reason ? <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/[0.06] px-3 py-2 text-xs leading-5 text-amber-200">{workflow.unavailable_reason}</p> : null}
            {mediaType === "video" && workflow?.reference_mode === "collection" && references.length > 3 && <p className="mt-3 text-xs text-amber-200">较多参考图会显著增加显存和耗时，建议先使用 1K 预览。</p>}
            {createMutation.isError && <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-200">{createMutation.error.message}</p>}
          </form>
          </>}

          <Modal
            open={Boolean(renameTarget)}
            title="重命名任务"
            okText="保存"
            cancelText="取消"
            confirmLoading={metadataMutation.isPending}
            onCancel={() => setRenameTarget(null)}
            onOk={() => renameTarget && metadataMutation.mutate({ jobId: renameTarget.id, title: renameValue })}
          >
            <Input autoFocus maxLength={120} value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onPressEnter={() => renameTarget && metadataMutation.mutate({ jobId: renameTarget.id, title: renameValue })} placeholder="输入任务名称" />
          </Modal>

        </main>
        <aside className="fixed bottom-0 right-0 top-14 z-20 hidden w-14 flex-col items-center border-l border-white/[0.06] bg-[#111218] pt-4 xl:hidden"><button type="button" onClick={() => setHistoryOpen(true)} title="任务记录" className="grid size-10 place-items-center rounded-lg bg-white/[0.06] text-[#c5c5ca] hover:bg-white/10 hover:text-white"><ListChecks size={19} /></button><History className="mt-6 text-[#d7d7dc]" size={16} /><span className="mt-2 text-sm leading-5 text-white [writing-mode:vertical-rl]">任务记录</span><span className="mt-3 size-2 rounded-full bg-[#7047ff]" /></aside>
      </div>
      {previewImage && <div role="dialog" aria-modal="true" aria-label={previewImage.alt} onMouseDown={() => setPreviewImage(null)} className="fixed inset-0 z-[100] flex items-center justify-center bg-[#0b0c10]/85 p-4 backdrop-blur-sm">
        <div onMouseDown={(event) => event.stopPropagation()} className="relative flex max-h-[min(88vh,900px)] w-full max-w-5xl items-center justify-center overflow-hidden rounded-2xl border border-white/10 bg-[#15161b] p-3 shadow-[0_28px_90px_rgba(0,0,0,0.55)]">
          <img src={previewImage.src} alt={previewImage.alt} className="max-h-[calc(88vh-24px)] max-w-full rounded-xl object-contain" />
          <button type="button" onClick={() => setPreviewImage(null)} title="关闭预览" className="absolute right-5 top-5 grid size-9 place-items-center rounded-full border border-white/10 bg-black/65 text-white transition hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><X size={17} /></button>
        </div>
      </div>}
      {previewReference && referencePreviewIndex !== null && <div role="dialog" aria-modal="true" aria-label="参考图预览" onMouseDown={closeReferencePreview} className={`fixed inset-0 z-[110] flex items-center justify-center bg-[#090a0e]/90 p-3 backdrop-blur-sm sm:p-5 ${referencePreviewFullscreen ? "p-0" : ""}`}>
        <section onMouseDown={(event) => event.stopPropagation()} className={`grid w-full grid-rows-[auto_minmax(0,1fr)_auto] gap-3 border border-white/10 bg-[#111216] p-3 text-white shadow-[0_28px_90px_rgba(0,0,0,0.55)] sm:rounded-xl sm:p-4 ${referencePreviewFullscreen ? "h-full max-w-none rounded-none border-0" : "h-[90vh] max-w-[92vw]"}`}>
          <header className="flex items-center justify-between gap-3"><div><h2 className="text-base font-medium">图片预览</h2><p className="mt-0.5 text-xs text-[#9898a3]">参考图 {referencePreviewIndex + 1} / {references.length}</p></div><button type="button" aria-label="关闭图片预览" title="关闭预览" onClick={closeReferencePreview} className="grid size-9 place-items-center rounded-full bg-white/[0.07] text-[#d7d7dc] transition hover:bg-white/[0.14] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><X size={17} /></button></header>
          <div className="relative min-h-0 overflow-hidden rounded-lg bg-black/25">
            <img src={previewReference.preview} alt={`参考图 ${referencePreviewIndex + 1} 大图`} className="h-full w-full object-contain transition-transform duration-200" style={{ transform: `scale(${referencePreviewZoom}) rotate(${referencePreviewRotation}deg)` }} />
            {references.length > 1 && <><button type="button" aria-label="查看上一张图片" title="查看上一张图片" onClick={() => moveReferencePreview(-1)} className="absolute left-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-lg border border-white/10 bg-black/65 text-white transition hover:bg-black/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><ChevronLeft size={18} /></button><button type="button" aria-label="查看下一张图片" title="查看下一张图片" onClick={() => moveReferencePreview(1)} className="absolute right-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-lg border border-white/10 bg-black/65 text-white transition hover:bg-black/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><ChevronRight size={18} /></button></>}
            <div className="absolute right-3 top-3 flex items-center gap-1 rounded-lg border border-white/10 bg-black/70 p-1.5 backdrop-blur">
              <button type="button" aria-label="放大图片" title="放大图片" onClick={() => setReferencePreviewZoom((value) => Math.min(3, value + 0.2))} className="grid size-8 place-items-center rounded-md text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><Plus size={16} /></button>
              <button type="button" aria-label="缩小图片" title="缩小图片" onClick={() => setReferencePreviewZoom((value) => Math.max(0.4, value - 0.2))} className="grid size-8 place-items-center rounded-md text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><Minus size={16} /></button>
              <button type="button" title="恢复原始比例" onClick={() => { setReferencePreviewZoom(1); setReferencePreviewRotation(0) }} className="h-8 rounded-md px-2 text-xs text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]">1:1</button>
              <button type="button" aria-label="顺时针旋转图片" title="顺时针旋转图片" onClick={() => setReferencePreviewRotation((value) => value + 90)} className="grid size-8 place-items-center rounded-md text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><RotateCw size={16} /></button>
              <button type="button" aria-label="切换全屏预览" title="全屏预览" onClick={() => setReferencePreviewFullscreen((value) => !value)} className="grid size-8 place-items-center rounded-md text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><Maximize2 size={16} /></button>
              <a href={previewReference.preview} download={previewReference.file.name} aria-label="下载图片" title="下载图片" className="grid size-8 place-items-center rounded-md text-[#e3e3e8] transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff]"><Download size={16} /></a>
            </div>
          </div>
          {references.length > 1 && <div aria-label="参考图缩略图列表" className="flex justify-center gap-3 overflow-x-auto pb-1">
            {references.map((asset, index) => <button key={asset.id} type="button" title={`查看第 ${index + 1} 张参考图`} aria-label={`查看第 ${index + 1} 张参考图`} onClick={() => openReferencePreview(index)} className={`relative h-20 w-16 shrink-0 overflow-hidden rounded-md border-2 bg-[#24252b] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8b6cff] ${referencePreviewIndex === index ? "border-[#8b72ff] shadow-[0_0_0_2px_rgba(112,71,255,0.28)]" : "border-white/15 hover:border-white/40"}`}><img src={asset.preview} alt={`缩略图 ${index + 1}`} className="h-full w-full object-cover" /><span className="absolute left-1 top-1 rounded bg-black/65 px-1 text-[10px] font-semibold text-white">{index + 1}</span></button>)}
          </div>}
        </section>
      </div>}
    </div>
  )
}

function OptionControl({
  name, definition, value, definitions, values, onChange, compact = false,
}: {
  name: string
  definition: OptionDefinition
  value: OptionInputValue
  definitions: Record<string, OptionDefinition>
  values: Record<string, OptionInputValue>
  onChange: (name: string, value: OptionInputValue) => void
  compact?: boolean
}) {
  if (definition.type === "boolean") {
    return <div title={definition.description} className={`studio-control-shell flex min-h-10 items-center justify-between gap-3 rounded-lg border border-[#37373b] bg-[#222226] px-3 text-xs text-[#d8d8df] ${compact ? "w-full sm:w-[172px]" : ""}`}>
      <span className="min-w-0 leading-4">{definition.label}</span>
      <Switch aria-label={definition.label} checked={Boolean(value)} onChange={(checked) => onChange(name, checked)} size="small" />
    </div>
  }
  const selectOptions = definition.ui_options?.map((item) => ({ ...item, value: String(item.value) }))
    ?? definition.enum?.map((item) => ({ value: String(item), label: `${item}${definition.unit ? ` ${definition.unit}` : ""}` }))
    ?? []
  if (definition.ui_control === "visual-settings") {
    const companionNames = definition.ui_companions ?? (definition.ui_companion ? [definition.ui_companion] : [])
    const companions = companionNames.flatMap((companionName) => {
      const companion = definitions[companionName]
      if (!companion) return []
      const companionMinimum = companion.minimum
      const companionMaximum = companion.maximum
      const numericOptionCount = companionMinimum !== undefined && companionMaximum !== undefined
        ? Math.floor((companionMaximum - companionMinimum) / (companion.step ?? 1)) + 1
        : 0
      const numericOptions = (companion.type === "number" || companion.type === "integer")
        && numericOptionCount > 0 && numericOptionCount <= 12
        && companionMinimum !== undefined && companionMaximum !== undefined
        ? Array.from({ length: Math.floor((companionMaximum - companionMinimum) / (companion.step ?? 1)) + 1 }, (_, index) => {
          const optionValue = companionMinimum + index * (companion.step ?? 1)
          return { value: String(optionValue), label: `${optionValue}${companion.unit ? ` ${companion.unit}` : ""}` }
        })
        : []
      const companionOptions = companion.ui_options?.map((item) => ({ ...item, value: String(item.value) }))
        ?? companion.enum?.map((item) => ({ value: String(item), label: `${item}${companion.unit ? ` ${companion.unit}` : ""}` }))
        ?? numericOptions
      return [{ name: companionName, definition: companion, options: companionOptions, value: String(values[companionName] ?? companion.default ?? ""), input: numericOptions.length === 0 && (companion.type === "number" || companion.type === "integer") }]
    })
    const ratioLabel = String(value).match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0] ?? String(value)
    const companionLabels = companions
      .filter(({ input }) => !input)
      .map(({ definition: companion, options, value: companionValue }) => generatedResolutionLabel(companion, companionValue, String(value)) ?? options.find((item) => item.value === companionValue)?.label ?? companionValue)
    return <VisualSettingsControl
      name={name}
      definition={definition}
      value={String(value)}
      options={selectOptions}
      companions={companions}
      onChange={onChange}
      compact={compact}
      triggerLabel={[ratioLabel, ...companionLabels].filter(Boolean).join(" · ")}
    />
  }
  if (definition.ui_control === "duration-slider" && (definition.type === "number" || definition.type === "integer")) {
    return <DurationControl name={name} definition={definition} value={Number(value)} onChange={onChange} compact={compact} />
  }
  if (definition.ui_control === "select" || selectOptions.length) {
    return <div title={definition.description} className={`studio-control-shell ${compact ? "w-full sm:w-[172px]" : "min-w-0"}`}>
      {!compact && <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>}
      <Select
        aria-label={definition.label}
        value={String(value)}
        onChange={(nextValue) => onChange(name, String(nextValue))}
        className="studio-select w-full"
        popupClassName="studio-select-popup"
        options={selectOptions}
      />
    </div>
  }
  if (definition.type === "number" || definition.type === "integer") {
    return <div title={definition.description} className={`studio-control-shell ${compact ? "w-full sm:w-[172px]" : "min-w-0"}`}>
      {!compact && <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>}
      <InputNumber aria-label={definition.label} value={Number(value)} onChange={(nextValue) => { if (nextValue !== null) onChange(name, String(nextValue)) }} min={definition.minimum} max={definition.maximum} step={definition.step} controls className="studio-number w-full" addonAfter={definition.unit} />
    </div>
  }
  return <div title={definition.description} className={`studio-control-shell ${compact ? "w-full sm:w-[172px]" : "min-w-0"}`}>
    {!compact && <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>}
    <Input aria-label={definition.label} value={String(value)} onChange={(event) => onChange(name, event.target.value)} className="studio-input" />
  </div>
}

function AspectRatioIcon({ value }: { value: string }) {
  const parts = value.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0].split(":").map(Number)
  const ratio = parts && parts[0] > 0 && parts[1] > 0 ? parts[0] / parts[1] : 1
  const height = ratio < 1 ? 22 : 14
  const width = Math.min(38, Math.max(10, height * ratio))
  return <span aria-hidden="true" className="block rounded-[3px] border border-current" style={{ width, height }} />
}

function VisualSettingsControl({
  name, definition, value, options, companions, onChange, compact, triggerLabel,
}: {
  name: string
  definition: OptionDefinition
  value: string
  options: { value: string; label: string; hint?: string }[]
  companions: { name: string; definition: OptionDefinition; options: { value: string; label: string; hint?: string }[]; value: string; input?: boolean }[]
  onChange: (name: string, value: OptionInputValue) => void
  compact: boolean
  triggerLabel: string
}) {
  const dimensionCompanions = companions.filter((companion) => companion.input)
  const content = <div className="w-[min(412px,calc(100vw-32px))] p-1.5">
    <section aria-label={definition.label}>
      <p className="mb-2 px-1 text-xs font-medium text-[#d8d8df]">选择{definition.label}</p>
      <div role="radiogroup" aria-label={definition.label} className="studio-aspect-ratio-group">
        {options.map((item) => {
          const selected = item.value === value
          const ratioLabel = item.value.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0] ?? item.label
          return <button key={item.value} type="button" role="radio" aria-checked={selected} onClick={() => onChange(name, item.value)} className={`studio-aspect-choice ${selected ? "studio-aspect-choice-selected" : ""}`}>
            <AspectRatioIcon value={item.value} />
            <span>{ratioLabel}</span>
          </button>
        })}
      </div>
    </section>
    {companions.filter(({ input }) => !input).map(({ name: companionName, definition: companion, options: companionOptions, value: companionValue }) => companionOptions.length > 0 && <section key={companionName} aria-label={companion.label} className="mt-3 pt-1">
      <p className="mb-2 px-1 text-xs font-medium text-[#536471]">选择{companion.label}</p>
      <div role="radiogroup" aria-label={companion.label} className={`studio-segmented-options grid gap-1 ${companionOptions.length <= 2 ? "grid-cols-2" : "grid-cols-3"}`}>
        {companionOptions.map((item) => {
          const outputSize = generatedResolutionLabel(companion, item.value, value)
          return <button key={item.value} type="button" role="radio" aria-checked={item.value === companionValue} aria-label={outputSize ? `${outputSize}，${item.label}` : item.label} onClick={() => onChange(companionName, item.value)} className={`studio-resolution-choice ${outputSize ? "studio-resolution-choice-detailed" : ""} ${item.value === companionValue ? "studio-resolution-choice-selected" : ""}`}>
            <span>{outputSize ?? item.label}</span>
            {outputSize && <small>{item.label}</small>}
          </button>
        })}
      </div>
    </section>)}
    {dimensionCompanions.length > 0 && <section aria-label="尺寸" className="studio-dimension-section mt-3 pt-1">
      <p className="mb-2 px-1 text-xs font-medium text-[#536471]">尺寸</p>
      <div className="studio-dimension-row">
        {dimensionCompanions.map(({ name: dimensionName, definition: dimension, value: dimensionValue }, index) => <Fragment key={dimensionName}>
          {index > 0 && <Link2 aria-hidden="true" size={16} className="studio-dimension-link text-[#607080]" />}
          <label className="studio-dimension-input">
            <span>{index === 0 ? "W" : "H"}</span>
            <InputNumber aria-label={dimension.label} value={Number(dimensionValue)} min={dimension.minimum} max={dimension.maximum} step={dimension.step} controls={false} onChange={(nextValue) => { if (nextValue !== null) onChange(dimensionName, String(nextValue)) }} />
          </label>
        </Fragment>)}
        <span className="studio-dimension-unit">PX</span>
      </div>
    </section>}
  </div>
  return <Popover trigger="click" placement="topLeft" content={content} overlayClassName="studio-parameter-popover">
    <button type="button" aria-label={`设置${definition.label}，当前${triggerLabel}`} className={`studio-parameter-trigger ${compact ? "w-full sm:w-[200px]" : "w-full"}`}>
      <Maximize2 size={16} className="shrink-0 text-[#a995ff]" />
      <span className="min-w-0 flex-1 truncate text-left">{triggerLabel}</span>
      <ChevronDown size={14} className="shrink-0 text-[#85858d]" />
    </button>
  </Popover>
}

function DurationControl({
  name, definition, value, onChange, compact,
}: {
  name: string
  definition: OptionDefinition
  value: number
  onChange: (name: string, value: OptionInputValue) => void
  compact: boolean
}) {
  const minimum = definition.minimum ?? 0
  const maximum = definition.maximum ?? Math.max(minimum + 1, value)
  const step = definition.step ?? 1
  const markValues = Array.from({ length: 5 }, (_, index) => {
    const raw = minimum + ((maximum - minimum) * index) / 4
    return Math.round(raw / step) * step
  })
  const marks = Object.fromEntries(markValues.map((mark) => [mark, <span key={mark}>{mark}</span>]))
  const content = <div className="w-[min(360px,calc(100vw-32px))] p-1.5">
    <p className="mb-4 px-1 text-xs font-medium text-[#d8d8df]">选择视频生成{definition.label}</p>
    <div className="flex items-start gap-4 px-1">
      <Slider aria-label={definition.label} className="studio-duration-slider min-w-0 flex-1" min={minimum} max={maximum} step={step} marks={marks} value={value} onChange={(nextValue) => { if (typeof nextValue === "number") onChange(name, String(nextValue)) }} tooltip={{ formatter: (nextValue) => `${nextValue ?? value}${definition.unit ?? ""}` }} />
      <div className="flex h-10 w-[100px] shrink-0 items-center rounded-lg bg-white/[0.06] px-1">
        <InputNumber aria-label={`手动输入${definition.label}`} value={value} min={minimum} max={maximum} step={step} controls onChange={(nextValue) => { if (nextValue !== null) onChange(name, String(nextValue)) }} className="studio-duration-number w-full" />
        <span className="pr-1 text-xs text-[#94949e]">{definition.unit}</span>
      </div>
    </div>
  </div>
  const displayValue = `${value}${definition.unit ?? ""}`
  return <Popover trigger="click" placement="topLeft" content={content} overlayClassName="studio-parameter-popover">
    <button type="button" aria-label={`设置${definition.label}，当前${displayValue}`} className={`studio-parameter-trigger studio-duration-trigger ${compact ? "w-full sm:w-[76px]" : "w-full"}`}>
      <Clock3 size={16} className="shrink-0 text-[#a995ff]" />
      <span className="min-w-0 flex-1 text-left">{displayValue}</span>
      <ChevronDown size={14} className="shrink-0 text-[#85858d]" />
    </button>
  </Popover>
}

function ReferencePanel({
  workflow, references, onAppend, onReplaceKeyframe, onRemove, onMove, onPreview, fileInputRef,
}: {
  workflow?: Workflow; references: ReferenceAsset[]; onAppend: (files: FileList | null) => void
  onReplaceKeyframe: (index: number, files: FileList | null) => void; onRemove: (index: number) => void
  onMove: (index: number, direction: -1 | 1) => void; onPreview: (index: number) => void
  fileInputRef: React.RefObject<HTMLInputElement | null>
}) {
  const [stackExpanded, setStackExpanded] = useState(false)
  const [hoveredReference, setHoveredReference] = useState<number | null>(null)

  if (!workflow || workflow.reference_mode === "none") return <div className="flex min-h-[106px] flex-col items-center justify-center rounded-xl border border-dashed border-white/[0.12] bg-[#202126]/65 px-3 text-center text-xs leading-5 text-[#85858d]"><FileVideo className="mb-2 text-[#8f78ff]" size={20} /><span>文生视频无需参考图</span></div>
  if (workflow.reference_mode === "keyframes") return <div className="studio-reference-panel flex gap-2">
    {[0, 1].map((index) => {
      const asset = references[index]
      const disabled = index === 1 && !references[0]
      return <label key={index} className={`studio-reference-slot group relative flex h-[106px] min-w-0 flex-1 cursor-pointer items-center justify-center overflow-hidden rounded-xl border transition ${asset ? "border-[#7655ff]/80 bg-[#222329] shadow-[0_8px_22px_rgba(0,0,0,0.2)]" : "border-dashed border-[#565762] bg-[#202126]"} ${disabled ? "cursor-not-allowed opacity-35" : "hover:border-[#9b83ff] hover:bg-[#292a31]"}`}>
        {asset ? <><img src={asset.preview} alt={workflow.reference_labels[index]} className="h-full w-full object-cover transition duration-200 group-hover:scale-105" /><button type="button" onClick={(event) => { event.preventDefault(); onPreview(index) }} className="studio-reference-preview-button absolute inset-0 grid place-items-center bg-black/0 text-white opacity-0 transition group-hover:bg-black/25 group-hover:opacity-100"><Maximize2 size={18} /></button></> : <div className="px-1 text-center"><ImagePlus className="mx-auto mb-1.5 text-[#a18cff]" size={19} /><span className="text-[11px] text-[#d3d3da]">{workflow.reference_labels[index]}</span>{index === 0 && <span className="mt-1 block text-[10px] text-[#777780]">点击上传</span>}</div>}
        {asset && <button type="button" onClick={(event) => { event.preventDefault(); onRemove(index) }} title="移除参考图" className="studio-reference-remove-button absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full border border-white/10 bg-black/65 text-white opacity-0 transition group-hover:opacity-100"><X size={12} /></button>}
        <input type="file" className="hidden" accept="image/*" disabled={disabled} onChange={(event) => onReplaceKeyframe(index, event.target.files)} />
      </label>
    })}
  </div>
  const stackOffset = (index: number) => stackExpanded ? index * 65 : index * 4
  const stackWidth = stackExpanded ? Math.max(71, references.length * 65 + 71) : 112

  return <div
    className="studio-reference-panel relative flex min-h-[106px] items-center overflow-visible"
    onMouseEnter={() => setStackExpanded(true)}
    onMouseLeave={() => { setStackExpanded(false); setHoveredReference(null) }}
    onFocus={() => setStackExpanded(true)}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) { setStackExpanded(false); setHoveredReference(null) } }}
  >
    <div className="relative h-[92px] overflow-visible transition-[width] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]" style={{ width: stackWidth }}>
      {references.map((asset, index) => {
        const hovered = hoveredReference === index
        const rotation = [-5, 7, -4, 6, -7, 4][index % 6]
        return <div
          key={asset.id}
          role="button"
          tabIndex={0}
          aria-label={`预览第 ${index + 1} 张参考图`}
          className={`group absolute left-0 top-2 h-[78px] w-[61px] cursor-pointer rounded-md border border-[#8b72ff]/80 bg-[#222226] shadow-[0_6px_14px_rgba(0,0,0,0.28)] outline-none transition-[transform,box-shadow] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:z-30 hover:shadow-[0_16px_28px_rgba(0,0,0,0.38)] focus-visible:z-30 focus-visible:ring-2 focus-visible:ring-[#a584ff] ${hovered ? "z-30 shadow-[0_16px_28px_rgba(0,0,0,0.38)]" : ""}`}
          style={{ transform: `translate3d(${stackOffset(index)}px, ${hovered ? -8 : index % 2 ? -1 : 1}px, 0) rotate(${rotation}deg) scale(${hovered ? 1.08 : 1})`, zIndex: stackExpanded ? index + 1 : index + 2 }}
          onClick={() => onPreview(index)}
          onMouseEnter={() => setHoveredReference(index)}
          onMouseLeave={() => setHoveredReference((current) => current === index ? null : current)}
          onFocus={() => setHoveredReference(index)}
          onBlur={() => setHoveredReference((current) => current === index ? null : current)}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onPreview(index) } }}
        >
          <img src={asset.preview} alt={`参考图 ${index + 1}`} className="h-full w-full rounded-[5px] object-cover" />
          <span aria-hidden className="studio-reference-index absolute left-1 top-1 flex min-w-[18px] items-center justify-center rounded-full border border-white/30 bg-[#17171f]/80 px-1 text-[10px] font-semibold leading-4 text-white">{index + 1}</span>
          <div className={`absolute inset-x-0 bottom-1 flex justify-center gap-0.5 transition ${stackExpanded ? "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100" : "pointer-events-none opacity-0"}`}>
            <button type="button" disabled={index === 0} onClick={(event) => { event.stopPropagation(); onMove(index, -1) }} title="向前移动" className="studio-reference-move-button grid size-5 place-items-center rounded-md bg-black/75 text-white hover:bg-black disabled:opacity-30"><MoveLeft size={11} /></button>
            <button type="button" disabled={index === references.length - 1} onClick={(event) => { event.stopPropagation(); onMove(index, 1) }} title="向后移动" className="studio-reference-move-button grid size-5 place-items-center rounded-md bg-black/75 text-white hover:bg-black disabled:opacity-30"><MoveRight size={11} /></button>
          </div>
          <button type="button" aria-label={`移除第 ${index + 1} 张参考图`} onClick={(event) => { event.stopPropagation(); onRemove(index) }} title="移除参考图" className={`studio-reference-remove-button absolute -right-2 -top-2 grid size-6 place-items-center rounded-full border border-white/10 bg-[#414148] text-white shadow-lg transition hover:bg-[#5b5b64] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a584ff] ${stackExpanded ? "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100" : "pointer-events-none opacity-0"}`}><X size={13} /></button>
        </div>
      })}
      {references.length < workflow.max_references && <label
        title="添加参考图"
        className="group absolute left-0 top-2 flex h-[78px] w-[61px] cursor-pointer items-center justify-center rounded-md border-2 border-[#4d6bfe] bg-[#edf1ff] text-[#4d6bfe] shadow-[0_10px_22px_rgba(77,107,254,0.14)] transition-[transform,background-color] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-1 hover:bg-[#e2e8ff]"
        style={{ transform: `translate3d(${stackExpanded ? references.length * 65 : references.length ? Math.max(44, references.length * 4 + 38) : 0}px, 0, 0) rotate(-8deg)`, zIndex: stackExpanded ? references.length + 2 : 20 }}
      >
        <Plus className="transition group-hover:scale-110" size={23} /><span className="sr-only">添加参考图</span>
        <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={(event) => onAppend(event.target.files)} />
      </label>}
    </div>
  </div>
}
