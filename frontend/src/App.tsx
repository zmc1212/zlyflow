import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, DatePicker, Drawer, Dropdown, Empty, Input, InputNumber, message, Modal, Pagination, Popover, Select, Slider, Switch, Tabs, Tooltip } from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import {
  ArrowUpDown, Check, CheckCircle2, CircleAlert, ChevronDown, ChevronLeft, ChevronRight, Clapperboard, Clock3, FileVideo, Frame,
  Download, ExternalLink, Filter, FolderOpen, Gauge, HardDrive, History, ImagePlus, Link2, ListChecks, LoaderCircle, Maximize2,
  Languages, Minus, MoreHorizontal, MoveLeft, MoveRight, Network, PanelLeftClose, PanelLeftOpen, Pencil, Pin, Plus, RotateCw, Search, Send, Settings2, SlidersHorizontal, Sparkles, CircleStop, Trash2, UserRound, Video, WalletCards, WandSparkles, X,
} from "lucide-react"
import { Fragment, FormEvent, lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { apiErrorMessage, jsonMutation, notifyUnauthorized, requestJson, User } from "./api"
import { generateJobPath, isDirectorLegacyStudioPath, parseGeneratePath, PATHS, studioWorkspaceFromPath, type GenerateMediaType } from "./paths"
import { elapsedCaption, executionCaption, isLiveStatus, jobElapsedMs, useNow } from "./job-elapsed"
import type { ImageResult } from "./media/ImageStudioModule"
import type { VideoResult } from "./media/VideoStudioModule"
import VideoRoundHeader from "./media/VideoRoundHeader"
import { jobUpscaleSourceKey, selectVideoResult, videoResultKey } from "./media/video-result-model"
import {
  activeUpscaleJob,
  canRequestJobUpscale,
  extraUpscaleResults,
  hasOriginalVideo,
  isUpscaleJob,
  upscaleDisabledReason,
  type UpscaleEngine,
} from "./video-upscale"
import JianyingExportModal from "./media/JianyingExportModal"
import type { JianyingMediaItem } from "./media/jianying-draft-builder"
import AddToCanvasModal, { type CanvasInsertAsset } from "./canvas/AddToCanvasModal"
import { formatRefineDuration, refineForceWarning, refinePlan } from "./director2/director2-video-settings"
import { createLocalId } from "./lib/utils"
import { restoreReferenceFiles, roundReferenceSources } from "./reference-assets"
import { cloudThumbnailSrc } from "./media-thumbnails"
import MediaPreviewModal, { type PreviewMediaKind } from "./components/MediaPreviewModal"
import RenameUserModal from "./components/RenameUserModal"
import StudioHeader from "./components/StudioHeader"
import GenerationHomeSections from "./generation/GenerationHomeSections"
import { groupTasksByCreatedAt } from "./task-groups"
import JobErrorNotice from "./director/components/JobErrorNotice"
import { useStudioTheme } from "./ThemeProvider"

/*
 * THESIS: A conversation-first AI studio, not a dashboard of cards.
 * OWN-WORLD: cool white canvas, hairline dividers, compact black text and one periwinkle action color.
 * STORY: scan a task in the left conversation rail, then create or continue in a quiet central canvas.
 * FIRST VIEWPORT: 76px icon rail, 240px task rail, and a Jimeng-style starter canvas (greeting, inline composer, prompt ideas); once a task is open the composer docks to the bottom.
 * FORM: a light operational workspace informed by the observed Jimeng conversation layout.
 */
const ImageStudioModule = lazy(() => import("./media/ImageStudioModule"))
const VideoStudioModule = lazy(() => import("./media/VideoStudioModule"))
const DirectorStudioModule = lazy(() => import("./director/DirectorStudioModule"))
const Director2App = lazy(() => import("./director2/Director2App"))
const DirectorAssetLibrary = lazy(() => import("./director/DirectorAssetLibrary"))
const CanvasWorkspace = lazy(() => import("./canvas/CanvasWorkspace"))

type Status = "queued" | "running" | "awaiting_refine" | "succeeded" | "failed" | "interrupted" | "cancelled" | "partial"
type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null; cloud_url?: string | null; delivered_at?: string | null
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
  created_at: string; updated_at: string; finished_at?: string | null
  elapsed_ms?: number | null; execution_elapsed_ms?: number | null
  media_type: "image" | "video"; title?: string | null; pinned?: boolean
  rounds: JobRound[]
  source?: { job_id: string; generation_item_id?: string | null; output_index?: number | null } | null
}
type GenerationItem = {
  id: string; index: number; executor: string; status: Status; stage: string; progress: number
  outputs: Output[]; error?: string | null
  created_at?: string; updated_at?: string; finished_at?: string | null
  elapsed_ms?: number | null; execution_elapsed_ms?: number | null
}
type JobRound = {
  id: string; sequence: number; mode: string; media_type: "image" | "video"; status: Status; stage: string
  progress: number; prompt: string; display_prompt?: string | null; options?: Record<string, unknown>
  reference_count: number; references: { index: number; url: string }[]
  request_parameters: RequestParameter[]; generation_items: GenerationItem[]; error?: string | null
  created_at?: string; updated_at?: string; finished_at?: string | null
  elapsed_ms?: number | null; execution_elapsed_ms?: number | null
}
type OptimizedPrompt = { english: string; chinese: string; context: string }
type AssetEntry = {
  id: string; job: Job; output: Output; outputIndex: number; generationItemId: string | null
}
type Workflow = {
  id: string; name: string; description: string; reference_mode: "none" | "keyframes" | "collection" | "fixed"
  min_references: number; max_references: number; reference_labels: string[]
  accepts_negative_prompt: boolean; accepts_image_size: boolean; supports_h3_options: boolean
  parameters: WorkflowParameter[]
  media_type: "image" | "video"; executor: string; available: boolean; unavailable_reason?: string | null
  catalog_group?: string; catalog_group_label?: string; catalog_group_order?: number
}
type OptionDefinition = {
  label: string; type: "string" | "number" | "integer" | "boolean"; default: string | number | boolean
  enum?: (string | number)[]; minimum?: number; maximum?: number; step?: number; pattern?: string
  description?: string; unit?: string; ui_group?: ParameterVisibility
  ui_control?: "select" | "visual-settings" | "duration-slider" | "input-number"; ui_companion?: string; ui_companions?: string[]
  ui_options?: { value: string | number; label: string; hint?: string }[]
  megapixels_by_quality?: Record<string, number>
  ui_resolution_preview?: { multiple?: number; max_width?: number; max_height?: number }
  ui_visible_when?: Record<string, string | number | boolean>
  ui_not_less_than?: string
  ui_requires_references_when?: string
}
type WorkflowParameter = { name: string; schema?: { properties?: Record<string, OptionDefinition> } | null }
type OptionInputValue = string | boolean
type ModesPayload = { modes: Workflow[]; image_sizes: string[]; presets: Record<string, string> }
type UpscaleEngineCapability = { id: UpscaleEngine; label: string; available: boolean; reason?: string | null }
type UpscaleCapabilities = { engines: UpscaleEngineCapability[]; default: UpscaleEngine }
type UpscaleEngineOption = { id: UpscaleEngine; label: string; hint?: string; disabled?: boolean }
type GrsBalanceSnapshot = { credits: number | null; queried_at: string | null; refresh_error?: string | null }
type ReferenceAsset = { id: string; file: File; preview: string }

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ""))
    reader.onerror = () => reject(reader.error || new Error("无法读取参考图"))
    reader.readAsDataURL(file)
  })
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("无法解码参考图"))
    image.src = src
  })
}

const OPTIMIZE_IMAGE_MAX_EDGE = 1024

async function optimizeImageUrl(file: File): Promise<string | null> {
  if (!file.type.startsWith("image/")) return null
  const dataUrl = await readFileAsDataUrl(file)
  if (!dataUrl.startsWith("data:image/")) return null
  if (file.type === "image/gif" || file.type === "image/svg+xml") return dataUrl
  try {
    const image = await loadImageElement(dataUrl)
    const edge = Math.max(image.naturalWidth, image.naturalHeight)
    if (!edge) return dataUrl
    const scale = Math.min(1, OPTIMIZE_IMAGE_MAX_EDGE / edge)
    // Small images are already cheap to send; only re-encode when it saves bytes.
    if (scale === 1 && dataUrl.length <= 900_000) return dataUrl
    const canvas = document.createElement("canvas")
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext("2d")
    if (!context) return dataUrl
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const compressed = canvas.toDataURL("image/webp", 0.86)
    return compressed.startsWith("data:image/webp") && compressed.length < dataUrl.length ? compressed : dataUrl
  } catch {
    return dataUrl
  }
}

async function referenceImageUrls(assets: ReferenceAsset[], limit = 8): Promise<string[]> {
  const urls: string[] = []
  for (const asset of assets.slice(0, limit)) {
    try {
      const url = await optimizeImageUrl(asset.file)
      if (url) urls.push(url)
    } catch {
      /* skip unreadable local files */
    }
  }
  return urls
}
type MediaPreview = {
  kind: PreviewMediaKind
  src: string
  title: string
  description?: string
  job?: Job
  aspectRatio?: string
}
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

function jobDisplayPrompt(job: Job): string {
  const rounds = job.rounds ?? []
  return rounds[rounds.length - 1]?.display_prompt?.trim() || job.prompt
}

const FALLBACK_WORKFLOW = "minimax-h3-i2v"
const PROMPT_OPTIMIZE_STORAGE_KEY = "zly-ai-video-studio.prompt-optimize"

function readPromptOptimizePreference() {
  try {
    return window.localStorage.getItem(PROMPT_OPTIMIZE_STORAGE_KEY) === "1"
  } catch {
    return false
  }
}
const api = requestJson
const mediaUrl = (path: string) => `/api/media/${encodeURIComponent(path)}`
const parameterValue = (parameter: RequestParameter) => {
  if (parameter.name === "references") return `${parameter.value} 张`
  if (typeof parameter.value === "boolean") return parameter.value ? "是" : "否"
  if (parameter.unit) return `${parameter.value} ${parameter.unit}`
  return String(parameter.value)
}
const statusText: Record<Status, string> = { queued: "等待队列", running: "生成中", awaiting_refine: "一采预览待确认", succeeded: "已完成", partial: "部分完成", failed: "失败", interrupted: "已中断", cancelled: "已停止" }
const statusColor: Record<Status, string> = {
  queued: "text-amber-600", running: "text-[#4d6bfe]", awaiting_refine: "text-amber-600", succeeded: "text-emerald-600", partial: "text-amber-600", failed: "text-red-600", interrupted: "text-[#6b7280]", cancelled: "text-[#6b7280]",
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

function formatCreatedFull(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false })
}

function formatCreatedShort(value: string, nowMs = Date.now()) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const now = new Date(nowMs)
  const time = date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })
  if (date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()) return time
  if (date.getFullYear() === now.getFullYear()) return `${date.getMonth() + 1}/${date.getDate()} ${time}`
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`
}

type WaitSource = {
  created_at?: string; finished_at?: string | null; elapsed_ms?: number | null
  execution_elapsed_ms?: number | null; status: Status
}

function waitCaption(source: WaitSource, now: number) {
  const live = isLiveStatus(source.status)
  const text = elapsedCaption(jobElapsedMs({
    createdAt: source.created_at,
    finishedAt: source.finished_at,
    elapsedMs: source.elapsed_ms,
    now,
    live,
  }), live)
  return { text, title: executionCaption(source.execution_elapsed_ms) || undefined }
}

function RoundWait({ source }: { source: WaitSource }) {
  const now = useNow(isLiveStatus(source.status))
  const wait = waitCaption(source, now)
  return wait.text ? <span title={wait.title || wait.text} className="studio-round-elapsed tabular-nums">{wait.text}</span> : null
}

function parseLocalDay(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  if (!year || !month || !day) return null
  const date = new Date(year, month - 1, day)
  return Number.isNaN(date.getTime()) ? null : date
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
    id: `${file.name}-${file.lastModified}-${createLocalId()}`,
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

function compactSelectWidth(options: { label?: string }[]) {
  const longest = options.reduce((max, item) => Math.max(max, String(item.label ?? "").length), 0)
  if (longest > 18) return 300
  if (longest > 12) return 240
  return 188
}

function optionVisible(definition: OptionDefinition, values: Record<string, OptionInputValue>) {
  if (!definition.ui_visible_when) return true
  return Object.entries(definition.ui_visible_when).every(([name, expected]) => String(values[name]) === String(expected))
}

function mediaAspectHint(source?: { options?: Record<string, unknown>; request_parameters?: RequestParameter[] }) {
  const fromOptions = source?.options?.aspect_ratio
  if (typeof fromOptions === "string" && fromOptions.trim()) return fromOptions.trim()
  const param = source?.request_parameters?.find((item) => item.name === "aspect_ratio")
  return typeof param?.value === "string" ? param.value : undefined
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
  return Object.fromEntries(Object.entries(definitions).filter(([, definition]) => definition.ui_group !== "internal" && optionVisible(definition, values)).map(([name, definition]) => {
    const value = values[name] ?? (definition.type === "boolean" ? false : "")
    return [name, definition.type === "number" || definition.type === "integer" ? Number(value) : value]
  }))
}

function validateOptionValues(
  definitions: Record<string, OptionDefinition>, values: Record<string, OptionInputValue>, referenceCount: number,
) {
  for (const [name, definition] of Object.entries(definitions)) {
    if (definition.ui_group === "internal") continue
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
  for (const [name, definition] of Object.entries(definitions)) {
    const value = values[name]
    if (value === undefined || String(value).trim() === "") continue
    const otherName = definition.ui_not_less_than
    if (otherName) {
      const other = Number(values[otherName])
      const current = Number(value)
      if (Number.isFinite(current) && Number.isFinite(other) && current < other) {
        return `${definition.label}不能小于 ${definitions[otherName]?.label ?? otherName}`
      }
    }
    const trigger = definition.ui_requires_references_when
    if (trigger !== undefined && String(value) === trigger && referenceCount < 1) {
      return `${definition.label}为 ${trigger} 时至少需要 1 张参考图`
    }
  }
  return ""
}

const VIDEO_PROMPT_IDEAS = [
  { label: "电影感运镜", icon: Clapperboard, prompt: "黄昏的旧城街道，雨后的地面反射霓虹，镜头低角度缓慢推进，电影感浅景深" },
  { label: "人物情绪", icon: UserRound, prompt: "年轻女性在窗边回头，眼神从平静到微笑，柔和侧光，浅景深特写" },
  { label: "产品特写", icon: ImagePlus, prompt: "白色台面上的香水瓶缓慢旋转，水珠滑落，棚拍高光，微距镜头" },
  { label: "自然风光", icon: Frame, prompt: "清晨云海翻涌的山谷，航拍缓慢穿云，金色阳光照亮山脊" },
  { label: "赛博夜景", icon: WandSparkles, prompt: "雨夜霓虹街头，镜头跟随人物穿过人群，青紫色霓虹反光，赛博朋克氛围" },
  { label: "动画分镜", icon: Video, prompt: "手绘动画分镜，少女从站台跑向列车，镜头横移跟随，暖色夕阳" },
]

const IMAGE_PROMPT_IDEAS = [
  { label: "人像写真", icon: UserRound, prompt: "窗边的年轻女性，柔和侧光，浅景深人像摄影，自然肤色，背景虚化" },
  { label: "产品海报", icon: ImagePlus, prompt: "极简白色台面上的香水瓶，硬光棚拍，水珠与倒影，产品广告质感" },
  { label: "场景概念", icon: Frame, prompt: "黄昏的东方古城屋顶群，远处群山与云海，电影概念场景，体积光" },
  { label: "平面插画", icon: Clapperboard, prompt: "扁平风格插画，夏日海边小镇，明亮配色，干净构图，海报比例" },
]

function groupedWorkflowOptions(workflows: Workflow[]) {
  const groups = new Map<string, { label: string; order: number; options: { value: string; label: string; title?: string; disabled?: boolean }[] }>()
  const ungrouped: { value: string; label: string; title?: string; disabled?: boolean }[] = []
  for (const item of workflows) {
    const option = { value: item.id, label: item.name, title: item.description, disabled: !item.available }
    if (!item.catalog_group) {
      ungrouped.push(option)
      continue
    }
    const existing = groups.get(item.catalog_group)
    if (existing) {
      existing.options.push(option)
      continue
    }
    groups.set(item.catalog_group, {
      label: item.catalog_group_label || item.catalog_group,
      order: item.catalog_group_order ?? 100,
      options: [option],
    })
  }
  const grouped = [...groups.values()]
    .sort((left, right) => left.order - right.order || left.label.localeCompare(right.label, "zh-CN"))
    .map((group) => ({ label: group.label, options: group.options }))
  return ungrouped.length ? [...grouped, ...ungrouped] : grouped
}

function outputPreviewSrc(item: Output, allowSameOriginVideo = true): string | undefined {
  if (item.cloud_url) return item.cloud_url
  if (item.kind === "video" && !allowSameOriginVideo) return undefined
  return item.download_url ?? mediaUrl(item.path)
}

function MediaTile({ item, allowSameOriginVideo = true }: { item: Output; allowSameOriginVideo?: boolean }) {
  const src = outputPreviewSrc(item, allowSameOriginVideo)
  if (!src) return <div className="grid h-full w-full place-items-center bg-[#27282e] text-[#898993]">{item.kind === "video" ? <Video size={18} /> : <HardDrive size={18} />}</div>
  const thumbnail = cloudThumbnailSrc(item.kind, item.cloud_url)
  return item.kind === "video"
    ? <video className="h-full w-full object-cover" muted playsInline preload="none" poster={thumbnail ?? undefined} src={src} />
    : <img
        className="h-full w-full object-cover"
        loading="lazy"
        decoding="async"
        src={thumbnail ?? src}
        alt={item.label}
        onError={(event) => {
          const image = event.currentTarget
          if (image.dataset.thumbnailFallback === "1") return
          image.dataset.thumbnailFallback = "1"
          image.src = src
        }}
      />
}

type TaskRowHandlers = {
  onSelect: (jobId: string) => void
  onPinToggle: (job: Job) => void
  onRename: (job: Job) => void
  onDelete: (job: Job) => void
  onCancel: (job: Job) => void
}

const TASK_GROUP_PREVIEW = 5
const TASK_DRAWER_PAGE_SIZE = 20
const ASSET_LOAD_BATCH = 24

function TaskRow({ job, selected = false, onSelect, onPinToggle, onRename, onDelete, onCancel }: TaskRowHandlers & { job: Job; selected?: boolean }) {
  const cover = job.outputs[0]
  const reference = job.references[0]
  const created = formatCreatedShort(job.created_at)
  const createdFull = formatCreatedFull(job.created_at)
  return <div
    role="button"
    tabIndex={0}
    onClick={() => onSelect(job.id)}
    onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(job.id) } }}
    className={`studio-task-card group mb-1 flex h-9 w-full cursor-pointer items-center gap-2 rounded-lg px-2 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/30 ${selected ? "bg-[#eef1ff]" : "hover:bg-black/[0.035]"}`}
  >
    <div className="size-8 shrink-0 overflow-hidden rounded-md bg-[#eef1f4]">
      {cover ? <MediaTile item={cover} allowSameOriginVideo={false} /> : reference ? <img src={reference.url} alt="任务封面" className="h-full w-full object-cover" loading="lazy" /> : <div className="grid h-full w-full place-items-center text-[#a0a8b2]">{job.media_type === "image" ? <ImagePlus size={15} /> : <Video size={15} />}</div>}
    </div>
    <span role="img" aria-label={statusText[job.status]} title={statusText[job.status]} className={`studio-task-state studio-task-state-${job.status}`}>
      {job.status === "succeeded" || job.status === "partial" ? <CheckCircle2 size={13} aria-hidden /> : job.status === "running" ? <LoaderCircle size={13} className="animate-spin" aria-hidden /> : job.status === "cancelled" ? <CircleStop size={13} aria-hidden /> : job.status === "failed" || job.status === "interrupted" ? <CircleAlert size={13} aria-hidden /> : <Clock3 size={13} aria-hidden />}
    </span>
    <p className="min-w-0 flex-1 truncate text-sm leading-[21px] text-[#171a1f]">{job.title || jobDisplayPrompt(job)}</p>
    {created ? <span title={createdFull ? `创作时间 ${createdFull}` : "创作时间"} className="shrink-0 text-[10px] tabular-nums text-[#7c8794]">{created}</span> : null}
    {job.pinned ? <Pin size={12} className="shrink-0 rotate-45 text-[#4d6bfe]" /> : null}
    <Dropdown
      trigger={["click"]}
      popupRender={(menu) => <div className="studio-task-menu">{menu}</div>}
      menu={{
        items: [
          { key: "pin", icon: <Pin size={14} />, label: job.pinned ? "取消置顶" : "置顶" },
          { key: "rename", icon: <Pencil size={14} />, label: "重命名" },
          ...((job.status === "queued" || job.status === "running" || job.status === "awaiting_refine" || job.status === "interrupted") ? [{ key: "cancel", danger: true as const, icon: <CircleStop size={14} />, label: "停止生成" }] : []),
          { type: "divider" as const },
          { key: "delete", danger: true, icon: <Trash2 size={14} />, label: "删除" },
        ],
        onClick: ({ key, domEvent }) => {
          domEvent.stopPropagation()
          if (key === "pin") onPinToggle(job)
          if (key === "rename") onRename(job)
          if (key === "cancel") onCancel(job)
          if (key === "delete") onDelete(job)
        },
      }}
    >
      <button type="button" title="任务操作" aria-label={`任务操作：${job.title || jobDisplayPrompt(job)}`} onClick={(event) => event.stopPropagation()} className="grid size-7 shrink-0 place-items-center rounded-md text-[#65707c] opacity-0 transition hover:bg-white hover:text-[#171a1f] group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/30"><MoreHorizontal size={16} /></button>
    </Dropdown>
  </div>
}

function TaskRowList({ jobs, selectedJobId, showEmpty = true, className = "", onSelect, onPinToggle, onRename, onDelete, onCancel }: TaskRowHandlers & { jobs: Job[]; selectedJobId?: string; showEmpty?: boolean; className?: string }) {
  return <div className={className}>
    {jobs.map((job) => <TaskRow key={job.id} job={job} selected={job.id === selectedJobId} onSelect={onSelect} onPinToggle={onPinToggle} onRename={onRename} onDelete={onDelete} onCancel={onCancel} />)}
    {showEmpty && !jobs.length && <div className="flex min-h-40 flex-col items-center justify-center px-5 text-center text-xs leading-5 text-[#7c8794]"><ListChecks className="mb-2 text-[#a0a8b2]" size={20} />当前类型还没有任务</div>}
  </div>
}

function taskMatchesQuery(job: Job, query: string) {
  return `${job.title || ""}\n${jobDisplayPrompt(job)}\n${job.prompt}`.toLocaleLowerCase().includes(query)
}

function TaskRailHistory({
  jobs, selectedJobId, mediaType, onSelect, onPinToggle, onRename, onDelete, onCancel,
}: TaskRowHandlers & { jobs: Job[]; selectedJobId?: string; mediaType: "image" | "video" }) {
  const [query, setQuery] = useState("")
  const [expandedGroups, setExpandedGroups] = useState<string[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerQuery, setDrawerQuery] = useState("")
  const [drawerPage, setDrawerPage] = useState(1)

  const recentJobs = useMemo(() => (selectedJobId ? jobs.filter((job) => job.id !== selectedJobId) : jobs), [jobs, selectedJobId])
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const searchResults = normalizedQuery ? recentJobs.filter((job) => taskMatchesQuery(job, normalizedQuery)) : null
  const pinnedJobs = useMemo(() => recentJobs.filter((job) => job.pinned), [recentJobs])
  const timeGroups = useMemo(() => groupTasksByCreatedAt(recentJobs.filter((job) => !job.pinned), Date.now()), [recentJobs])

  const toggleGroup = (key: string) => {
    setExpandedGroups((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  }
  const openHistory = () => {
    setDrawerQuery("")
    setDrawerPage(1)
    setDrawerOpen(true)
  }

  const normalizedDrawerQuery = drawerQuery.trim().toLocaleLowerCase()
  const drawerJobs = normalizedDrawerQuery ? jobs.filter((job) => taskMatchesQuery(job, normalizedDrawerQuery)) : jobs
  const drawerPageCount = Math.max(1, Math.ceil(drawerJobs.length / TASK_DRAWER_PAGE_SIZE))
  const activeDrawerPage = Math.min(drawerPage, drawerPageCount)
  const drawerRows = drawerJobs.slice((activeDrawerPage - 1) * TASK_DRAWER_PAGE_SIZE, activeDrawerPage * TASK_DRAWER_PAGE_SIZE)

  const renderGroup = (key: string, label: string, groupedJobs: Job[]) => {
    const expanded = expandedGroups.includes(key)
    const visibleJobs = expanded ? groupedJobs : groupedJobs.slice(0, TASK_GROUP_PREVIEW)
    return <div key={key} className="mb-1">
      <div className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-[11px] font-medium text-[#8a96a3]">
        <span>{label}</span>
        <span className="ml-auto text-[10px] font-normal tabular-nums text-[#a0a8b2]">{groupedJobs.length}</span>
      </div>
      {visibleJobs.map((job) => <TaskRow key={job.id} job={job} selected={job.id === selectedJobId} onSelect={onSelect} onPinToggle={onPinToggle} onRename={onRename} onDelete={onDelete} onCancel={onCancel} />)}
      {groupedJobs.length > TASK_GROUP_PREVIEW
        ? <button type="button" aria-expanded={expanded} onClick={() => toggleGroup(key)} className="mb-1 flex h-7 w-full items-center gap-1.5 rounded-md px-2 text-[11px] text-[#7c8794] transition hover:bg-black/[0.035] hover:text-[#171a1f]">
          <ChevronDown size={13} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
          {expanded ? "收起" : `显示其余 ${groupedJobs.length - TASK_GROUP_PREVIEW} 项`}
        </button>
        : null}
    </div>
  }

  return <section className="flex min-h-0 flex-1 flex-col">
    <p className="studio-task-section-title">最近</p>
    <div className="px-4 pb-2">
      <Input
        allowClear
        value={query}
        onChange={(event) => { setQuery(event.target.value); setExpandedGroups([]) }}
        prefix={<Search size={13} />}
        placeholder="搜索标题或提示词"
        aria-label="搜索最近任务"
        className="studio-task-search"
      />
    </div>
    <div className="studio-task-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-2">
      {searchResults ? <>
        <div className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-[11px] font-medium text-[#8a96a3]">
          <span>搜索结果</span>
          <span className="ml-auto text-[10px] font-normal tabular-nums text-[#a0a8b2]">{searchResults.length}</span>
        </div>
        {searchResults.map((job) => <TaskRow key={job.id} job={job} selected={job.id === selectedJobId} onSelect={onSelect} onPinToggle={onPinToggle} onRename={onRename} onDelete={onDelete} onCancel={onCancel} />)}
        {!searchResults.length && <p className="px-2 py-6 text-center text-xs text-[#7c8794]">没有匹配的任务</p>}
      </> : <>
        {pinnedJobs.length ? renderGroup("pinned", "置顶", pinnedJobs) : null}
        {pinnedJobs.length ? <div className="mx-2 mb-1 border-t border-black/[0.05]" /> : null}
        {timeGroups.map((group) => renderGroup(group.key, group.label, group.tasks))}
        {!recentJobs.length && <div className="flex min-h-40 flex-col items-center justify-center px-5 text-center text-xs leading-5 text-[#7c8794]"><ListChecks className="mb-2 text-[#a0a8b2]" size={20} />当前类型还没有任务</div>}
      </>}
    </div>
    <div className="border-t border-black/[0.05] px-3 py-2">
      <button type="button" onClick={openHistory} className="flex h-8 w-full items-center gap-2 rounded-lg px-2 text-xs text-[#536471] transition hover:bg-black/[0.04] hover:text-[#171a1f]">
        <ListChecks size={15} />
        <span>查看全部任务</span>
        <span className="ml-auto text-[10px] tabular-nums text-[#8a96a3]">{jobs.length}</span>
        <ChevronRight size={14} />
      </button>
    </div>
    <Drawer
      title={<span className="flex items-baseline gap-2">全部任务<span className="text-xs font-normal text-[#7c8794]">{jobs.length} 个{mediaType === "image" ? "图片" : "视频"}任务</span></span>}
      size={480}
      open={drawerOpen}
      onClose={() => setDrawerOpen(false)}
      styles={{ body: { display: "flex", flexDirection: "column", minHeight: 0, padding: 0 } }}
      rootClassName="studio-task-drawer"
    >
      <div className="border-b border-black/[0.05] px-5 py-3">
        <Input
          allowClear
          value={drawerQuery}
          onChange={(event) => { setDrawerQuery(event.target.value); setDrawerPage(1) }}
          prefix={<Search size={14} />}
          placeholder="搜索标题或提示词"
          aria-label="搜索全部任务"
          className="studio-task-search"
        />
      </div>
      <div className="studio-task-scroll min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {drawerRows.map((job) => <TaskRow key={job.id} job={job} selected={job.id === selectedJobId} onSelect={(jobId) => { onSelect(jobId); setDrawerOpen(false) }} onPinToggle={onPinToggle} onRename={onRename} onDelete={onDelete} onCancel={onCancel} />)}
        {!drawerJobs.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的任务" />}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-black/[0.05] px-5 py-3">
        <span className="text-xs text-[#7c8794]">共 {drawerJobs.length} 个</span>
        <Pagination size="small" hideOnSinglePage current={activeDrawerPage} pageSize={TASK_DRAWER_PAGE_SIZE} total={drawerJobs.length} showSizeChanger={false} onChange={setDrawerPage} />
      </div>
    </Drawer>
  </section>
}

function AdminUserFilterSelect({
  value, options, onChange, className,
}: {
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  className?: string
}) {
  return <Select
    aria-label="切换查看用户"
    value={value}
    onChange={onChange}
    className={className}
    options={options}
  />
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
  const location = useLocation()
  const navigate = useNavigate()
  const { mode: themeMode } = useStudioTheme()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const promptRef = useRef<TextAreaRef>(null)
  const workspaceView = studioWorkspaceFromPath(location.pathname)
  const isCanvasHome = workspaceView === "canvas" && /^\/canvas\/?$/.test(location.pathname)
  const generateRoute = parseGeneratePath(location.pathname)
  const lastGeneratePathRef = useRef<string>(PATHS.generateVideo)
  const lastDirectorPathRef = useRef<string>(PATHS.director)
  const lastMediaTypeRef = useRef<GenerateMediaType>("video")
  const directorLegacyStudio = isDirectorLegacyStudioPath(location.pathname)
  if (workspaceView === "generate" && generateRoute) {
    lastGeneratePathRef.current = location.pathname
    lastMediaTypeRef.current = generateRoute.mediaType
  }
  if (workspaceView === "director") lastDirectorPathRef.current = location.pathname
  const mediaType: GenerateMediaType = generateRoute?.mediaType ?? lastMediaTypeRef.current
  const headerUsesGrs = mediaType === "image" && (workspaceView === "generate" || workspaceView === "assets")
  const selectedJobId = workspaceView === "generate" ? generateRoute?.jobId : undefined
  const [workflowId, setWorkflowId] = useState(FALLBACK_WORKFLOW)
  const [prompt, setPrompt] = useState("")
  const [negativePrompt, setNegativePrompt] = useState("")
  const [references, setReferences] = useState<ReferenceAsset[]>([])
  const referencesRef = useRef<ReferenceAsset[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [taskRailCollapsed, setTaskRailCollapsed] = useState(false)
  const [assetSection, setAssetSection] = useState<"history" | "subject" | "canvas">("history")
  const [assetMediaFilter, setAssetMediaFilter] = useState<AssetMediaFilter>("all")
  const [assetSearch, setAssetSearch] = useState("")
  const [isBatchMode, setIsBatchMode] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set())
  const [filterStatus, setFilterStatus] = useState<"all" | "succeeded" | "running" | "failed">("all")
  const [filterRatio, setFilterRatio] = useState<"all" | "16:9" | "9:16" | "1:1">("all")
  const [timeFilter, setTimeFilter] = useState<"all" | "today" | "7days" | "30days" | "month" | "custom">("all")
  const [customDateRange, setCustomDateRange] = useState<[string, string] | null>(null)
  const [customDateModalOpen, setCustomDateModalOpen] = useState(false)
  const [customDateRangeValue, setCustomDateRangeValue] = useState<any>(null)
  const [sortOption, setSortOption] = useState<
    "created_desc" | "created_asc" | "title_asc" | "title_desc" | "prompt_len_desc" | "prompt_len_asc"
  >("created_desc")
  const [assetVisibleLimit, setAssetVisibleLimit] = useState(ASSET_LOAD_BATCH)
  const assetLoadMoreRef = useRef<HTMLDivElement | null>(null)
  const [jianyingModalOpen, setJianyingModalOpen] = useState(false)
  const [jianyingSelectedItems, setJianyingSelectedItems] = useState<JianyingMediaItem[]>([])
  const [canvasInsertAsset, setCanvasInsertAsset] = useState<CanvasInsertAsset | null>(null)
  const [videoVersionByRound, setVideoVersionByRound] = useState<Record<string, string>>({})
  const [videoRoundDetails, setVideoRoundDetails] = useState<{ id: string; runtime: boolean } | null>(null)
  const [isComposerCompact, setIsComposerCompact] = useState(false)
  const [renameTarget, setRenameTarget] = useState<Job | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [source, setSource] = useState<MediaDraft["source"]>()
  const draftsRef = useRef<Partial<Record<"image" | "video", MediaDraft>>>({})
  const restoringDraftRef = useRef(false)
  const pendingMediaDraftRef = useRef<MediaDraft | "empty" | null>(null)
  const liveDraftRef = useRef<MediaDraft | null>(null)
  const prevMediaTypeRef = useRef<GenerateMediaType | null>(null)
  const [isSelectedPromptExpanded, setIsSelectedPromptExpanded] = useState(false)
  const [previewMedia, setPreviewMedia] = useState<MediaPreview | null>(null)
  const [referencePreviewIndex, setReferencePreviewIndex] = useState<number | null>(null)
  const [referencePreviewZoom, setReferencePreviewZoom] = useState(1)
  const [referencePreviewRotation, setReferencePreviewRotation] = useState(0)
  const [referencePreviewFullscreen, setReferencePreviewFullscreen] = useState(false)
  const [optionValues, setOptionValues] = useState<Record<string, OptionInputValue>>({})
  const [advancedOptionsOpen, setAdvancedOptionsOpen] = useState(false)
  const [imageSize, setImageSize] = useState("横版 1280 x 720")
  const [profileOpen, setProfileOpen] = useState(false)
  const [messageApi, messageContext] = message.useMessage()
  const restoringComposerRef = useRef(false)
  const [adminUserFilter, setAdminUserFilter] = useState<string>("all")

  const modesQuery = useQuery({ queryKey: ["modes"], queryFn: async () => {
    const payload = await api<ModesPayload>("/api/modes")
    return { ...payload, modes: payload.modes.map(normalizeWorkflow) }
  } })
  const upscaleCapabilitiesQuery = useQuery({
    queryKey: ["upscale_capabilities"],
    queryFn: () => api<UpscaleCapabilities>("/api/upscale/capabilities"),
    staleTime: 60_000,
  })
  const upscaleEngines = useMemo<UpscaleEngineOption[] | undefined>(() => {
    const caps = upscaleCapabilitiesQuery.data
    if (!caps) return undefined
    return caps.engines.map((engine) => ({
      id: engine.id,
      label: engine.id === "seedvr2" ? "高清增强（SeedVR2）" : "快速超分（RTX）",
      disabled: !engine.available,
      hint: engine.available
        ? engine.id === "seedvr2" ? "生成式重建细节，整段通常需要几分钟" : "秒级完成，主要锐化与去块"
        : engine.reason || "当前 ComfyUI 不可用",
    }))
  }, [upscaleCapabilitiesQuery.data])
  const isAdminViewer = user.role === "admin" || user.role === "super_admin"
  const adminUsersQuery = useQuery({
    queryKey: ["admin_users"],
    queryFn: () => api<User[]>("/api/admin/users"),
    enabled: isAdminViewer,
  })
  // Assets renders from `allJobs`, so it needs an initial fetch but no periodic polling.
  // Director shot/asset progress bars still keep polling on generate + the three leftover studios.
  const jobsEnabled = workspaceView === "generate" || workspaceView === "assets" || directorLegacyStudio
  const jobsPollingEnabled = workspaceView === "generate" || directorLegacyStudio
  const jobsQuery = useQuery({
    queryKey: ["jobs", user.id, adminUserFilter],
    enabled: jobsEnabled,
    queryFn: async () => {
      const search = new URLSearchParams()
      if (isAdminViewer && adminUserFilter !== user.id) {
        search.set("user_id", adminUserFilter)
      }
      const qs = search.toString()
      return (await api<Job[]>(`/api/jobs${qs ? `?${qs}` : ""}`)).map(normalizeJob)
    },
    refetchInterval: (query) => {
      if (!jobsPollingEnabled) return false
      if (query.state.fetchStatus === "fetching") return false
      const jobs = query.state.data as Job[] | undefined
      if (!jobs) return 4000
      const hasActive = jobs.some((job) => job.status === "running" || job.status === "queued" || job.status === "interrupted")
      return hasActive ? 4000 : 15000
    },
  })
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: () => api<{ comfy: { reachable: boolean }; grs: { available: boolean; message?: string | null } }>("/api/health"), refetchInterval: 30000 })
  const workflows = (modesQuery.data?.modes ?? []).filter((item) => item.media_type === mediaType)
  const workflow = workflows.find((item) => item.id === workflowId) ?? workflows[0]
  const promptIdeas = mediaType === "image" ? IMAGE_PROMPT_IDEAS : VIDEO_PROMPT_IDEAS
  const allJobs = jobsQuery.data ?? []
  const jobs = allJobs.filter((job) => job.media_type === mediaType)
  const adminUserOptions = useMemo(() => [
    { value: "all", label: "全部用户" },
    ...(adminUsersQuery.data ?? []).map((account) => ({
      value: account.id,
      label: account.display_name || account.username,
    })),
  ], [adminUsersQuery.data])
  const inspectedUser = (adminUsersQuery.data ?? []).find((account) => account.id === adminUserFilter)
  const inspectedUserLabel = inspectedUser?.display_name || inspectedUser?.username || "该用户"
  const isInspectingOtherUser = isAdminViewer && adminUserFilter !== "all" && adminUserFilter !== user.id
  const changeAdminUserFilter = (value: string) => {
    setAdminUserFilter(value)
    setIsSelectedPromptExpanded(false)
    if (selectedJobId) navigate(generateJobPath(mediaType))
  }
  const imageGenerationActive = mediaType === "image" && jobs.some((job) => job.status === "queued" || job.status === "running")
  const grsBalanceQuery = useQuery({
    queryKey: ["grs-balance"],
    queryFn: () => api<GrsBalanceSnapshot>("/api/providers/grs/balance"),
    enabled: workspaceView === "generate" && mediaType === "image",
    refetchInterval: imageGenerationActive ? 5_000 : 15_000,
  })
  const grsBalanceUnavailable = Boolean(grsBalanceQuery.error || (grsBalanceQuery.data?.refresh_error && grsBalanceQuery.data.credits === null))
  const grsBalanceStale = Boolean(grsBalanceQuery.data?.refresh_error)
  const [selectedSkillId, setSelectedSkillId] = useState<string>("general")
  const [optimizeUndo, setOptimizeUndo] = useState<{ before: string; after: string } | null>(null)
  const [optimizedPrompt, setOptimizedPrompt] = useState<OptimizedPrompt | null>(null)
  const [englishPromptOpen, setEnglishPromptOpen] = useState(false)
  const [roundPromptLanguage, setRoundPromptLanguage] = useState<Record<string, "zh" | "en">>({})
  const [promptOptimizeEnabled, setPromptOptimizeEnabled] = useState(readPromptOptimizePreference)
  const [autoOptimizing, setAutoOptimizing] = useState(false)
  const skillsQuery = useQuery({
    queryKey: ["llm-skills"],
    queryFn: () => requestJson<{ skills: H3Skill[] }>("/api/llm/skills"),
    enabled: Boolean(user),
    staleTime: 1000 * 60 * 10,
  })
  const llmStatusQuery = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => api<{ available: boolean; message?: string | null; model?: string | null }>("/api/llm/status"),
    enabled: Boolean(user),
    staleTime: 1000 * 60,
    retry: false,
  })
  const llmAvailable = llmStatusQuery.data ? llmStatusQuery.data.available : true
  const autoOptimizeActive = promptOptimizeEnabled && llmAvailable
  const optimizationContext = [
    workflowId,
    references.map((asset) => asset.id).join(","),
    selectedSkillId,
    String(optionValues.duration ?? ""),
  ].join("\u0000")
  const reusableOptimized = optimizedPrompt
    && optimizedPrompt.chinese === prompt.trim()
    && optimizedPrompt.context === optimizationContext
    ? optimizedPrompt
    : null
  const togglePromptOptimize = (enabled: boolean) => {
    setPromptOptimizeEnabled(enabled)
    try {
      window.localStorage.setItem(PROMPT_OPTIMIZE_STORAGE_KEY, enabled ? "1" : "0")
    } catch {
      // Private browsing can deny localStorage; keep the in-memory toggle.
    }
  }
  const optimizeToggleTooltip = !llmAvailable
    ? (llmStatusQuery.data?.message || "大模型服务不可用，请先在管理设置 → AI 供应商 → 大模型中配置。")
    : autoOptimizeActive
      ? "已开启：点击生成会先调用语言大模型润色当前提示词。"
      : mediaType === "video"
        ? "开启后，点击生成会先调用语言大模型，按 MiniMax H3 官方规范润色；多参考视频输出官方六段式。"
        : "开启后，点击生成会先调用语言大模型润色当前提示词。"
  const h3Skills = skillsQuery.data?.skills || []
  const activeSkill = h3Skills.find((s) => s.id === selectedSkillId) || h3Skills[0]
  const selectedJobFromList = selectedJobId ? allJobs.find((job) => job.id === selectedJobId) : undefined
  // Deep links to jobs outside the latest list page fall back to the single-job endpoint.
  const jobDetailQuery = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api<Job>(`/api/jobs/${selectedJobId}`).then(normalizeJob),
    enabled: workspaceView === "generate" && Boolean(selectedJobId) && !selectedJobFromList && jobsQuery.isFetched,
    retry: false,
    refetchInterval: (query) => {
      const job = query.state.data as Job | undefined
      if (!job) return false
      const live = isLiveStatus(job.status) || job.rounds.some((round) => isLiveStatus(round.status))
      return live ? 4000 : false
    },
  })
  const selectedJob = selectedJobFromList ?? jobDetailQuery.data
  const selectedJobMediaType = selectedJob?.media_type
  const selectedJobLoading = Boolean(selectedJobId && !selectedJob && (jobsQuery.isLoading || jobDetailQuery.isPending || jobDetailQuery.isFetching))
  const selectedJobMissing = Boolean(selectedJobId && !selectedJob && !selectedJobLoading)
  const isGenerationHome = workspaceView === "generate" && !selectedJobId && !isInspectingOtherUser

  const assetEntries = useMemo<AssetEntry[]>(
    () => workspaceView !== "assets" || assetSection !== "history" ? [] : allJobs.flatMap((job): AssetEntry[] => {
      const roundEntries = job.rounds.flatMap((round) => round.generation_items.flatMap((item) => item.outputs.map((output, outputIndex) => ({
        id: `${item.id}:${outputIndex}`,
        job,
        output,
        outputIndex,
        generationItemId: item.id,
      }))))
      return roundEntries.length ? roundEntries : job.outputs.map((output, outputIndex) => ({
        id: `${job.id}:legacy:${outputIndex}`,
        job,
        output,
        outputIndex,
        generationItemId: null,
      }))
    }),
    [allJobs, workspaceView, assetSection],
  )
  const activeFilterCount = useMemo(() => {
    let count = 0
    if (filterStatus !== "all") count++
    if (filterRatio !== "all") count++
    return count
  }, [filterStatus, filterRatio])

  const visibleAssetEntries = useMemo(() => {
    const query = assetSearch.trim().toLocaleLowerCase()
    const now = new Date()

    const filtered = assetEntries.filter(({ job, output }) => {
      if (assetSection !== "history") return false

      // 1. Media Type Filter (全部/图片/视频/音频/文档)
      const matchesType = assetMediaFilter === "all" || output.kind === assetMediaFilter
      if (!matchesType) return false

      // 2. Search query (label, title, prompt)
      const searchable = `${output.label} ${job.title ?? ""} ${jobDisplayPrompt(job)} ${job.prompt}`.toLocaleLowerCase()
      if (query && !searchable.includes(query)) return false

      // 3. Status Filter (全部/成功/进行中/失败)
      if (filterStatus === "succeeded" && !(job.status === "succeeded" || job.status === "partial")) return false
      if (filterStatus === "running" && !(job.status === "running" || job.status === "queued")) return false
      if (filterStatus === "failed" && !(job.status === "failed" || job.status === "interrupted" || job.status === "cancelled")) return false

      // 4. Ratio Filter (全部/16:9/9:16/1:1)
      if (filterRatio !== "all") {
        const paramStr = (job.request_parameters ?? []).map((p) => String(p.value)).join(" ")
        const allText = `${job.image_size ?? ""} ${output.label} ${paramStr}`.toLowerCase()
        if (filterRatio === "16:9" && !(allText.includes("16:9") || allText.includes("横版") || allText.includes("1280 x 720") || allText.includes("1920 x 1080") || allText.includes("1280*720"))) return false
        if (filterRatio === "9:16" && !(allText.includes("9:16") || allText.includes("竖版") || allText.includes("720 x 1280") || allText.includes("1080 x 1920") || allText.includes("720*1280"))) return false
        if (filterRatio === "1:1" && !(allText.includes("1:1") || allText.includes("方形") || allText.includes("1024 x 1024") || allText.includes("1024*1024"))) return false
      }

      // 5. Time Filter (全部/今天/近7天/近30天/本月/自定义)
      const createdDate = new Date(job.created_at)
      const createdTime = createdDate.getTime()
      if (!Number.isNaN(createdTime)) {
        if (timeFilter === "today") {
          const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
          if (createdTime < todayStart) return false
        } else if (timeFilter === "7days") {
          const sevenDaysAgo = now.getTime() - 7 * 86400 * 1000
          if (createdTime < sevenDaysAgo) return false
        } else if (timeFilter === "30days") {
          const thirtyDaysAgo = now.getTime() - 30 * 86400 * 1000
          if (createdTime < thirtyDaysAgo) return false
        } else if (timeFilter === "month") {
          if (createdDate.getFullYear() !== now.getFullYear() || createdDate.getMonth() !== now.getMonth()) return false
        } else if (timeFilter === "custom" && customDateRange) {
          const startDate = parseLocalDay(customDateRange[0])
          const endDate = parseLocalDay(customDateRange[1])
          if (startDate && endDate) {
            const start = startDate.getTime()
            const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate() + 1).getTime()
            if (createdTime < start || createdTime >= end) return false
          }
        }
      }

      return true
    })

    // 排序
    return filtered.sort((a, b) => {
      const timeA = new Date(a.job.created_at).getTime() || 0
      const timeB = new Date(b.job.created_at).getTime() || 0
      if (sortOption === "created_desc") return timeB - timeA
      if (sortOption === "created_asc") return timeA - timeB
      if (sortOption === "title_asc") {
        const titleA = a.job.title || jobDisplayPrompt(a.job)
        const titleB = b.job.title || jobDisplayPrompt(b.job)
        return titleA.localeCompare(titleB, "zh-CN")
      }
      if (sortOption === "title_desc") {
        const titleA = a.job.title || jobDisplayPrompt(a.job)
        const titleB = b.job.title || jobDisplayPrompt(b.job)
        return titleB.localeCompare(titleA, "zh-CN")
      }
      if (sortOption === "prompt_len_desc") {
        return jobDisplayPrompt(b.job).length - jobDisplayPrompt(a.job).length
      }
      if (sortOption === "prompt_len_asc") {
        return jobDisplayPrompt(a.job).length - jobDisplayPrompt(b.job).length
      }
      return timeB - timeA
    })
  }, [
    assetEntries,
    assetMediaFilter,
    assetSearch,
    assetSection,
    customDateRange,
    filterRatio,
    filterStatus,
    sortOption,
    timeFilter,
  ])

  const loadedAssetEntries = useMemo(
    () => visibleAssetEntries.slice(0, assetVisibleLimit),
    [visibleAssetEntries, assetVisibleLimit],
  )
  const hasMoreAssetEntries = loadedAssetEntries.length < visibleAssetEntries.length

  const assetGroups = useMemo(() => {
    if (sortOption.startsWith("title_") || sortOption.startsWith("prompt_len_")) {
      return [{
        label: sortOption.startsWith("title_") ? "按名称排列" : "按提示词长度排列",
        timestamp: 0,
        entries: loadedAssetEntries,
      }]
    }
    const groups = new Map<string, { label: string; timestamp: number; entries: typeof loadedAssetEntries }>()
    loadedAssetEntries.forEach((entry) => {
      const date = new Date(entry.job.created_at)
      const key = Number.isNaN(date.getTime()) ? "unknown" : `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
      const current = groups.get(key)
      if (current) current.entries.push(entry)
      else groups.set(key, { label: formatAssetDate(entry.job.created_at), timestamp: Number.isNaN(date.getTime()) ? 0 : date.getTime(), entries: [entry] })
    })
    const list = Array.from(groups.values())
    if (sortOption === "created_asc") {
      return list.sort((left, right) => left.timestamp - right.timestamp)
    }
    return list.sort((left, right) => right.timestamp - left.timestamp)
  }, [loadedAssetEntries, sortOption])

  useEffect(() => {
    setAssetVisibleLimit(ASSET_LOAD_BATCH)
  }, [assetSection, assetMediaFilter, assetSearch, filterStatus, filterRatio, timeFilter, customDateRange, sortOption])

  useEffect(() => {
    if (assetSection !== "history" || !hasMoreAssetEntries) return
    const sentinel = assetLoadMoreRef.current
    if (!sentinel || typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setAssetVisibleLimit((current) => current + ASSET_LOAD_BATCH)
        }
      },
      { rootMargin: "480px 0px" },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [assetSection, hasMoreAssetEntries, loadedAssetEntries.length])
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
  const refineHint = useMemo(() => {
    if (String(optionValues.refine_enabled ?? false) !== "true") return null
    const duration = Number(optionValues.duration ?? 5)
    if (!Number.isFinite(duration) || duration <= 0) return null
    const plan = refinePlan(
      String(optionValues.refine_quality ?? "1.0"),
      String(optionValues.refine_quality_mode ?? "auto"),
      duration,
      String(optionValues.aspect_ratio ?? "16:9"),
    )
    return { ...plan, durationLabel: formatRefineDuration(plan.estimatedSeconds) }
  }, [optionValues])
  const resultsForRound = (round: JobRound) => {
    const own = round.generation_items.flatMap((item) => item.outputs.map((output, outputIndex) => ({
      jobId: selectedJob?.id,
      generationItemId: item.id,
      outputIndex,
      output,
      src: outputPreviewSrc(output),
    })))
    const extras = selectedJob ? extraUpscaleResults(selectedJob, allJobs).map((item) => ({
      ...item,
      src: outputPreviewSrc(item.output),
    })) : []
    return [...own, ...extras]
  }

  useEffect(() => {
    if (workflows.length && !workflows.some((item) => item.id === workflowId)) setWorkflowId(workflows[0].id)
  }, [workflowId, workflows])
  useEffect(() => {
    setTaskRailCollapsed(workspaceView !== "generate")
  }, [workspaceView])
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

  const createMutation = useMutation({
    mutationFn: async ({ prompt: submittedPrompt, displayPrompt }: { prompt: string; displayPrompt?: string }) => {
      const form = new FormData()
      form.set("mode", workflowId)
      form.set("prompt", submittedPrompt)
      if (displayPrompt && displayPrompt.trim() && displayPrompt.trim() !== submittedPrompt.trim()) {
        form.set("display_prompt", displayPrompt.trim())
      }
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
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      return payload as Job
    },
    onSuccess: (job) => {
      navigate(generateJobPath(job.media_type, job.id))
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
      navigate(generateJobPath(job.media_type, job.id))
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const confirmRefineMutation = useMutation({
    mutationFn: async (jobId: string) => api<Job>(`/api/jobs/${jobId}/refine/confirm`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      messageApi.success({ content: "已开始二采精修，将复用一采缓存只跑第二遍", duration: 5 })
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const skipRefineMutation = useMutation({
    mutationFn: async (jobId: string) => api<Job>(`/api/jobs/${jobId}/refine/skip`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      messageApi.success("已保留一采预览作为成片")
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const upscaleMutation = useMutation({
    mutationFn: async ({ jobId, engine }: { jobId: string; engine?: UpscaleEngine }) => api<Job>(
      `/api/jobs/${jobId}/upscale`,
      jsonMutation(csrfToken, engine ? { engine } : {}),
    ),
    onSuccess: (_job, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      messageApi.success(variables.engine === "seedvr2" ? "已提交 SeedVR2 高清增强" : "已提交 2x 超分")
      void queryClient.invalidateQueries({ queryKey: ["upscale_capabilities"] })
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const cancelMutation = useMutation({
    mutationFn: async (jobId: string) => api<Job>(`/api/jobs/${jobId}/cancel`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: (job) => {
      navigate(generateJobPath(job.media_type, job.id))
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const createRoundMutation = useMutation({
    mutationFn: async (job: Job) => {
      const form = new FormData()
      form.set("prompt", job.prompt)
      const displayPrompt = job.rounds[job.rounds.length - 1]?.display_prompt?.trim()
      if (displayPrompt && displayPrompt !== job.prompt.trim()) form.set("display_prompt", displayPrompt)
      form.set("negative_prompt", job.negative_prompt)
      const response = await fetch(`/api/jobs/${job.id}/rounds`, { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "创建下一轮失败"))
      return payload as Job
    },
    onSuccess: (job) => { navigate(generateJobPath(job.media_type, job.id)); void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] }) },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const retryFailedMutation = useMutation({
    mutationFn: async ({ jobId, roundId }: { jobId: string; roundId: string }) => api<Job>(`/api/jobs/${jobId}/rounds/${roundId}/retry-failed-items`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] }),
    onError: (error: Error) => messageApi.error(error.message),
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
      if (selectedJobId === id) navigate(generateJobPath(mediaType))
      void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
      messageApi.success("任务已删除")
    },
    onError: (error: Error) => messageApi.error(error.message),
  })

  const requestOptimizedPrompt = async (sourcePrompt: string, skillIdOverride?: string) => {
    const cleanPrompt = sourcePrompt.trim()
    if (!cleanPrompt) {
      throw new Error("请先输入简短的画面描述或想法")
    }
    const targetSkillId = skillIdOverride || selectedSkillId
    const imageUrls = await referenceImageUrls(references)
    const durationSeconds = Number(optionValues.duration)
    return requestJson<{
      original_prompt: string; optimized_prompt: string; optimized_prompt_zh?: string | null; skill_id?: string
    }>(
      "/api/llm/optimize-prompt",
      jsonMutation(csrfToken, {
        prompt: cleanPrompt,
        media_type: mediaType,
        workflow_name: workflow?.name,
        skill_id: mediaType === "video" ? targetSkillId : undefined,
        reference_count: references.length,
        workflow_id: workflowId,
        duration_seconds: mediaType === "video" && Number.isFinite(durationSeconds) && durationSeconds > 0
          ? durationSeconds
          : undefined,
        image_urls: imageUrls.length ? imageUrls : undefined,
      }),
    )
  }

  const optimizeMutation = useMutation({
    mutationFn: async (skillIdOverride?: string | void) => requestOptimizedPrompt(
      prompt,
      typeof skillIdOverride === "string" ? skillIdOverride : undefined,
    ),

    onSuccess: (data) => {
      const english = data.optimized_prompt.trim()
      if (mediaType === "video") {
        const chinese = data.optimized_prompt_zh?.trim() || data.original_prompt.trim()
        setOptimizedPrompt({ english, chinese, context: optimizationContext })
        setOptimizeUndo({ before: data.original_prompt, after: chinese })
        setPrompt(chinese)
        messageApi.success(data.optimized_prompt_zh?.trim()
          ? "提示词已润色，生成时使用英文版；可点击「查看英文」对照"
          : "提示词已润色为英文 H3 格式；中文对照暂不可用，已保留原文")
        return
      }
      setOptimizedPrompt(null)
      setOptimizeUndo({ before: data.original_prompt, after: english })
      setPrompt(english)
      messageApi.success("提示词已润色，可继续修改或直接生成")
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
  const canSubmit = Boolean(!isInspectingOtherUser && workflow?.available && prompt.trim() && referenceCount >= workflow.min_references && referenceCount <= workflow.max_references && !optionError && !createMutation.isPending && !autoOptimizing && !optimizeMutation.isPending)
  const referenceHint = workflow?.reference_mode === "collection"
    ? `已添加 ${referenceCount} / ${workflow.max_references} 张`
    : workflow?.reference_mode === "keyframes" ? "首帧必填更稳定，尾帧用于锁定结尾" : ""

  const downloadOutput = (job: Job, outputIndex: number, output: Output) => {
    const url = output.download_url ?? output.cloud_url
    if (!url) {
      messageApi.warning("资源暂不可下载")
      return
    }
    const extension = output.kind === "image" ? "png" : "mp4"
    const title = (job.title || job.prompt.slice(0, 30) || `asset_${job.id.slice(0, 8)}`).replace(/[\\/:*?"<>|]/g, "_")
    const link = document.createElement("a")
    link.href = url
    link.download = `${title}_${outputIndex + 1}.${extension}`
    link.rel = "noopener"
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  const createVideoFromImage = async (result: ImageResult) => {
    if (!selectedJob) return
    const url = result.output.download_url ?? result.output.cloud_url
    if (!url) {
      messageApi.error("原图暂不可下载，请稍后重试。")
      return
    }
    let file: File
    try {
      const response = await fetch(url)
      if (response.status === 401) notifyUnauthorized()
      if (!response.ok) throw new Error("下载原图失败，请稍后重试。")
      const blob = await response.blob()
      const extension = result.output.path.match(/\.[a-z0-9]{1,10}$/i)?.[0] ?? ".png"
      file = new File([blob], `reference${extension}`, { type: blob.type || "image/png" })
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "下载原图失败，请稍后重试。")
      return
    }
    const asset = newAssets([file])[0]
    const videoWorkflow = (modesQuery.data?.modes ?? []).find((item) => item.id === "minimax-h3-i2v")
      ?? (modesQuery.data?.modes ?? []).find((item) => item.media_type === "video")
    if (!videoWorkflow || !selectedJob) return
    draftsRef.current[mediaType] = currentDraft()
    pendingMediaDraftRef.current = {
      workflowId: videoWorkflow.id,
      prompt: "",
      negativePrompt: "",
      references: [asset],
      optionValues: defaultOptionValues(videoWorkflow),
      source: { jobId: selectedJob.id, generationItemId: result.generationItemId, outputIndex: result.outputIndex },
    }
    navigate(PATHS.generateVideo)
    messageApi.success("原图已带入视频创作")
    requestAnimationFrame(() => promptRef.current?.focus())
  }

  const currentDraft = (): MediaDraft => ({
    workflowId, prompt, negativePrompt, references, optionValues, selectedJobId: selectedJob?.id, source,
  })

  const applyMediaDraft = (draft: MediaDraft | undefined, nextMedia: GenerateMediaType) => {
    const targetWorkflows = (modesQuery.data?.modes ?? []).filter((item) => item.media_type === nextMedia)
    restoringDraftRef.current = Boolean(draft)
    setWorkflowId(draft?.workflowId ?? targetWorkflows[0]?.id ?? FALLBACK_WORKFLOW)
    setPrompt(draft?.prompt ?? "")
    setNegativePrompt(draft?.negativePrompt ?? "")
    setReferences(draft?.references ?? [])
    setOptionValues(draft?.optionValues ?? defaultOptionValues(targetWorkflows[0]))
    setSource(draft?.source)
    setAdvancedOptionsOpen(false)
  }

  const resetCreation = () => {
    setTaskRailCollapsed(false)
    setPrompt("")
    setNegativePrompt("")
    setReferences((current) => { releaseAssets(current); return [] })
    setIsSelectedPromptExpanded(false)
    setSource(undefined)
    if (location.pathname !== generateJobPath(mediaType)) navigate(generateJobPath(mediaType))
  }
  const switchMedia = (nextMedia: GenerateMediaType) => {
    if (nextMedia === mediaType) return
    draftsRef.current[mediaType] = currentDraft()
    const draft = draftsRef.current[nextMedia]
    pendingMediaDraftRef.current = draft ?? "empty"
    navigate(generateJobPath(nextMedia, draft?.selectedJobId))
  }
  const selectJob = (jobId: string) => {
    setIsSelectedPromptExpanded(false)
    const next = generateJobPath(mediaType, jobId)
    if (location.pathname !== next) navigate(next)
  }
  const openGenerateJob = (job: Job) => {
    setTaskRailCollapsed(false)
    setIsSelectedPromptExpanded(false)
    if (job.media_type !== mediaType) {
      draftsRef.current[mediaType] = currentDraft()
      pendingMediaDraftRef.current = draftsRef.current[job.media_type] ?? "empty"
    }
    navigate(generateJobPath(job.media_type, job.id))
  }
  useLayoutEffect(() => {
    if (prevMediaTypeRef.current === mediaType) liveDraftRef.current = currentDraft()
  })
  useEffect(() => {
    if (prevMediaTypeRef.current === null) {
      prevMediaTypeRef.current = mediaType
      return
    }
    if (prevMediaTypeRef.current === mediaType) return
    const leaving = prevMediaTypeRef.current
    prevMediaTypeRef.current = mediaType
    const pending = pendingMediaDraftRef.current
    pendingMediaDraftRef.current = null
    if (pending == null && liveDraftRef.current) draftsRef.current[leaving] = liveDraftRef.current
    const draft = pending === "empty" ? undefined : pending ?? draftsRef.current[mediaType]
    applyMediaDraft(draft, mediaType)
  }, [mediaType])
  useEffect(() => {
    if (workspaceView !== "generate" || !selectedJobId || !selectedJobMediaType || selectedJobMediaType === mediaType) return
    draftsRef.current[mediaType] = currentDraft()
    pendingMediaDraftRef.current = draftsRef.current[selectedJobMediaType] ?? "empty"
    navigate(generateJobPath(selectedJobMediaType, selectedJobId), { replace: true })
  }, [workspaceView, selectedJobId, selectedJobMediaType, mediaType, navigate])
  const lastScrolledJobRef = useRef<string | undefined>(selectedJobId)
  useEffect(() => {
    if (workspaceView !== "generate" || lastScrolledJobRef.current === selectedJobId) return
    lastScrolledJobRef.current = selectedJobId
    if (selectedJobId) window.scrollTo({ top: 0, behavior: "auto" })
  }, [workspaceView, selectedJobId])
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
  const appendFiles = (files: FileList | File[] | null) => {
    if (!files || !workflow || workflow.reference_mode === "none") return
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
    const input = promptRef.current?.resizableTextArea?.textArea
    const start = input?.selectionStart ?? prompt.length
    const end = input?.selectionEnd ?? prompt.length
    const before = prompt.slice(0, start)
    const after = prompt.slice(end)
    const padded = `${before && !/\s$/.test(before) ? " " : ""}${token}${after && !/^\s/.test(after) ? " " : ""}`
    setPrompt(`${before}${padded}${after}`)
    requestAnimationFrame(() => { input?.focus(); input?.setSelectionRange(start + padded.length, start + padded.length) })
  }
  const applyPromptIdea = (idea: string) => {
    setPrompt((current) => current.trim() ? `${current.trimEnd()}\n${idea}` : idea)
    requestAnimationFrame(() => promptRef.current?.focus())
  }
  const returnToComposer = useCallback((focusEditor = false) => {
    restoringComposerRef.current = true
    setIsComposerCompact(false)
    requestAnimationFrame(() => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" })
      if (focusEditor) promptRef.current?.focus()
    })
  }, [])
  const submitTask = async () => {
    if (!canSubmit) return
    const refineWarning = refineForceWarning(
      {
        refine_enabled: String(optionValues.refine_enabled ?? false),
        refine_quality_mode: String(optionValues.refine_quality_mode ?? "auto"),
        refine_quality: String(optionValues.refine_quality ?? "1.0"),
        aspect_ratio: String(optionValues.aspect_ratio ?? "16:9"),
      },
      Number(optionValues.duration ?? 5),
    )
    if (refineWarning) {
      const confirmed = await new Promise<boolean>((resolve) => {
        Modal.confirm({
          title: "强制高清会显著延长出片时间",
          content: refineWarning,
          okText: "仍然提交",
          cancelText: "取消",
          centered: true,
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        })
      })
      if (!confirmed) return
    }
    const originalPrompt = prompt.trim()
    if (!autoOptimizeActive) {
      if (reusableOptimized) {
        createMutation.mutate({ prompt: reusableOptimized.english, displayPrompt: reusableOptimized.chinese })
      } else {
        createMutation.mutate({ prompt: originalPrompt })
      }
      return
    }
    if (reusableOptimized) {
      createMutation.mutate({ prompt: reusableOptimized.english, displayPrompt: reusableOptimized.chinese })
      return
    }
    setAutoOptimizing(true)
    try {
      const data = await requestOptimizedPrompt(originalPrompt)
      const optimized = data.optimized_prompt.trim()
      if (!optimized) {
        messageApi.warning("提示词润色结果为空，已按原文生成")
        createMutation.mutate({ prompt: originalPrompt })
        return
      }
      if (mediaType === "video") {
        const chinese = data.optimized_prompt_zh?.trim() || originalPrompt
        setOptimizedPrompt({ english: optimized, chinese, context: optimizationContext })
        setOptimizeUndo({ before: originalPrompt, after: chinese })
        setPrompt(chinese)
        messageApi.success({
          content: data.optimized_prompt_zh?.trim()
            ? "提示词已按 H3 官方规范润色，生成将使用英文版"
            : "已生成英文 H3 提示词，中文对照暂不可用",
          duration: 2,
        })
        createMutation.mutate({ prompt: optimized, displayPrompt: chinese })
        return
      }
      setOptimizeUndo({ before: originalPrompt, after: optimized })
      setPrompt(optimized)
      messageApi.success({ content: "提示词已自动润色", duration: 2 })
      createMutation.mutate({ prompt: optimized })
    } catch (error) {
      const detail = error instanceof Error ? error.message : "未知错误"
      messageApi.warning(`提示词润色失败，已按原文生成：${detail}`)
      createMutation.mutate({ prompt: originalPrompt })
    } finally {
      setAutoOptimizing(false)
    }
  }
  const copyEnglishPrompt = async () => {
    const value = reusableOptimized?.english || optimizedPrompt?.english
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      messageApi.success("英文提示词已复制")
    } catch {
      messageApi.error("复制失败，请手动选择文本复制")
    }
  }
  const submit = (event: FormEvent) => { event.preventDefault(); void submitTask() }
  const openRename = (job: Job) => { setRenameTarget(job); setRenameValue(job.title || jobDisplayPrompt(job).slice(0, 40)) }
  const togglePinned = (job: Job) => metadataMutation.mutate({ jobId: job.id, pinned: !job.pinned })
  const confirmDelete = (job: Job) => Modal.confirm({
    title: "删除任务？",
    content: "任务记录与该任务的全部轮次将从工作台移除，已保存到本地目录的文件不会删除。",
    okText: "删除",
    cancelText: "取消",
    okButtonProps: { danger: true },
    onOk: () => deleteMutation.mutateAsync(job),
  })
  const confirmCancel = (job: Job) => Modal.confirm({
    title: "停止生成？",
    content: job.media_type === "image"
      ? "工作台将停止等待结果。云端任务可能仍会继续计费，尚未取回的图片不会自动拉取。"
      : "将中断 ComfyUI 当前推理并取消排队。未完成的视频无法续跑，也不会自动重新提交。",
    okText: "停止生成",
    cancelText: "继续生成",
    okButtonProps: { danger: true },
    onOk: () => cancelMutation.mutateAsync(job.id),
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
    const displayPrompt = round.display_prompt?.trim()
    restoringDraftRef.current = targetWorkflow.id !== workflowId
    restoringComposerRef.current = true
    setIsComposerCompact(false)
    setWorkflowId(targetWorkflow.id)
    setOptionValues(nextOptions)
    setPrompt(displayPrompt || round.prompt)
    setNegativePrompt(job.negative_prompt)
    setSource(undefined)
    setAdvancedOptionsOpen(false)
    setOptimizeUndo(null)
    setOptimizedPrompt(null)
    const sources = roundReferenceSources(job, round)
    let restoredReferences: ReferenceAsset[] = []
    try {
      const referenceFiles = await restoreReferenceFiles(sources)
      const nextReferences = newAssets(referenceFiles)
      if (sources.length > 0 && nextReferences.length !== sources.length) {
        throw new Error("参考图未能还原为可上传图片")
      }
      restoredReferences = nextReferences
      setReferences((current) => { releaseAssets(current); return nextReferences })
    } catch {
      setReferences((current) => { releaseAssets(current); return [] })
      messageApi.warning("已带回提示词和参数；原参考图无法读取，请重新添加。")
    }
    if (displayPrompt && displayPrompt !== round.prompt) {
      setOptimizedPrompt({
        english: round.prompt,
        chinese: displayPrompt,
        context: [
          targetWorkflow.id,
          restoredReferences.map((asset) => asset.id).join(","),
          selectedSkillId,
          String(nextOptions.duration ?? ""),
        ].join("\u0000"),
      })
    }
    setIsSelectedPromptExpanded(false)
    const nextPath = generateJobPath(job.media_type)
    if (location.pathname !== nextPath) navigate(nextPath)
    returnToComposer(true)
  }

  const handleToggleBatchMode = () => {
    setIsBatchMode((prev) => {
      if (prev) {
        setSelectedAssetIds(new Set())
      }
      return !prev
    })
  }

  const handleToggleSelectAsset = (id: string) => {
    setSelectedAssetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSelectAll = () => {
    setSelectedAssetIds(new Set(visibleAssetEntries.map((e) => e.id)))
  }

  const handleDeselectAll = () => {
    setSelectedAssetIds(new Set())
  }

  const handleBatchDownload = () => {
    const selectedEntries = visibleAssetEntries.filter((e) => selectedAssetIds.has(e.id))
    if (!selectedEntries.length) {
      messageApi.warning("请先勾选需要下载的资产")
      return
    }

    messageApi.info(`正在准备下载 ${selectedEntries.length} 个资产文件...`)
    selectedEntries.forEach(({ job, output, outputIndex }, index) => {
      const url = output.download_url ?? output.cloud_url ?? mediaUrl(output.path)
      if (!url) return
      setTimeout(() => {
        const ext = output.kind === "image" ? "png" : "mp4"
        const cleanTitle = (job.title || job.prompt.slice(0, 30) || `asset_${job.id.slice(0, 8)}`).replace(/[\\/:*?"<>|]/g, "_")
        const filename = `${cleanTitle}_${outputIndex + 1}.${ext}`
        const a = document.createElement("a")
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      }, index * 250)
    })
  }

  const handleBatchDelete = () => {
    const selectedEntries = visibleAssetEntries.filter((e) => selectedAssetIds.has(e.id))
    if (!selectedEntries.length) {
      messageApi.warning("请先勾选需要删除的资产")
      return
    }
    const uniqueJobIds = Array.from(new Set(selectedEntries.map((e) => e.job.id)))
    const jobsToDelete = uniqueJobIds.map((id) => allJobs.find((j) => j.id === id)).filter(Boolean) as Job[]

    Modal.confirm({
      title: "批量删除资产与任务记录？",
      content: `已选中 ${selectedEntries.length} 个资产项，涉及 ${jobsToDelete.length} 个生成任务。删除后任务记录及全部生成轮次将从工作台移除，已保存到本地磁盘的文件不会被删除。`,
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        const results = await Promise.allSettled(jobsToDelete.map((job) =>
          api<{ id: string }>(`/api/jobs/${job.id}`, jsonMutation(csrfToken, undefined, "DELETE")),
        ))
        const failed = results.filter((result): result is PromiseRejectedResult => result.status === "rejected")
        if (selectedJobId && uniqueJobIds.includes(selectedJobId)) navigate(generateJobPath(mediaType))
        setSelectedAssetIds(new Set())
        void queryClient.invalidateQueries({ queryKey: ["jobs", user.id] })
        if (failed.length) {
          const reason = failed[0].reason instanceof Error ? failed[0].reason.message : "未知错误"
          messageApi.warning(`已删除 ${results.length - failed.length} 个任务，${failed.length} 个失败：${reason}`)
        } else {
          messageApi.success(`已批量删除 ${jobsToDelete.length} 个任务`)
        }
      },
    })
  }

  const handleOpenJianying = (onlySelected = false) => {
    const targetEntries = (onlySelected && selectedAssetIds.size > 0)
      ? visibleAssetEntries.filter((e) => selectedAssetIds.has(e.id))
      : visibleAssetEntries.filter((e) => e.output.kind === "video" || e.output.kind === "image")

    const items: JianyingMediaItem[] = targetEntries.map(({ id, job, output, outputIndex }) => {
      const url = output.download_url ?? output.cloud_url ?? mediaUrl(output.path)
      return {
        id,
        title: job.title || job.prompt.slice(0, 30) || `素材_${outputIndex + 1}`,
        kind: output.kind,
        path: output.path,
        url,
        durationSeconds: output.kind === "image" ? 3.0 : undefined,
      }
    })

    if (!items.length) {
      messageApi.warning("当前没有可用于剪映剪辑的视频或图片资产")
      return
    }

    setJianyingSelectedItems(items)
    setJianyingModalOpen(true)
  }

  const timeLabel = {
    all: "时间",
    today: "今天",
    "7days": "近 7 天",
    "30days": "近 30 天",
    month: "本月",
    custom: "自定义时间",
  }[timeFilter]

  const sortLabel = {
    created_desc: "最新在前",
    created_asc: "最早在前",
    title_asc: "名称 A-Z",
    title_desc: "名称 Z-A",
    prompt_len_desc: "提示词长到短",
    prompt_len_asc: "提示词短到长",
  }[sortOption]

  const filterMenuItems = [
    {
      key: "status_group",
      type: "group" as const,
      label: "生成状态",
      children: [
        { key: "status:all", label: "全部状态", icon: filterStatus === "all" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "status:succeeded", label: "已完成 (成功)", icon: filterStatus === "succeeded" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "status:running", label: "生成中 (排队/运行)", icon: filterStatus === "running" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "status:failed", label: "失败 / 中断 / 已停止", icon: filterStatus === "failed" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
      ],
    },
    { type: "divider" as const },
    {
      key: "ratio_group",
      type: "group" as const,
      label: "画面画幅",
      children: [
        { key: "ratio:all", label: "全部画幅", icon: filterRatio === "all" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "ratio:16:9", label: "16:9 横屏", icon: filterRatio === "16:9" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "ratio:9:16", label: "9:16 竖屏", icon: filterRatio === "9:16" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
        { key: "ratio:1:1", label: "1:1 方形", icon: filterRatio === "1:1" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
      ],
    },
    { type: "divider" as const },
    {
      key: "reset_filter",
      danger: true,
      label: "重置所有筛选",
    },
  ]

  const timeMenuItems = [
    { key: "all", label: "全部时间", icon: timeFilter === "all" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "today", label: "今天", icon: timeFilter === "today" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "7days", label: "近 7 天", icon: timeFilter === "7days" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "30days", label: "近 30 天", icon: timeFilter === "30days" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "month", label: "本月", icon: timeFilter === "month" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { type: "divider" as const },
    { key: "custom", label: "自定义范围...", icon: timeFilter === "custom" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
  ]

  const sortMenuItems = [
    { key: "created_desc", label: "创建时间：最新在前 (默认)", icon: sortOption === "created_desc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "created_asc", label: "创建时间：最早在前", icon: sortOption === "created_asc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { type: "divider" as const },
    { key: "title_asc", label: "任务标题：A → Z", icon: sortOption === "title_asc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "title_desc", label: "任务标题：Z → A", icon: sortOption === "title_desc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { type: "divider" as const },
    { key: "prompt_len_desc", label: "提示词：由长到短", icon: sortOption === "prompt_len_desc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
    { key: "prompt_len_asc", label: "提示词：由短到长", icon: sortOption === "prompt_len_asc" ? <Check size={14} className="text-[#4d6bfe]" /> : null },
  ]

  return (
    <div className={`${themeMode === "light" ? "studio-light" : "studio-dark"} ${workspaceView === "canvas" ? "studio-canvas-shell" : ""} ${isCanvasHome ? "studio-canvas-home-shell" : ""} min-h-screen overflow-x-hidden bg-[#f8f9fa] text-[#171a1f]`}>
      {messageContext}
      {profileOpen ? <RenameUserModal target={user} csrfToken={csrfToken} self onClose={() => setProfileOpen(false)} /> : null}
      <StudioHeader
        user={user}
        provider={headerUsesGrs ? "GRS" : "ComfyUI"}
        providerStatus={healthQuery.isPending ? "checking" : (headerUsesGrs ? healthQuery.data?.grs?.available : healthQuery.data?.comfy?.reachable) ? "online" : "offline"}
        providerMessage={headerUsesGrs ? healthQuery.data?.grs?.message : undefined}
        onOpenMcp={() => navigate(PATHS.mcp)}
        onOpenAdmin={onOpenAdmin}
        onOpenProfile={() => { setProfileOpen(true) }}
        onLogout={onLogout}
        logoutPending={logoutPending}
      />

      <div className={`studio-workspace studio-floating-workspace relative mt-14 flex min-h-[calc(100vh-56px)] bg-[#f8f9fa] ${taskRailCollapsed || workspaceView !== "generate" ? "studio-task-rail-collapsed" : ""} ${workspaceView === "assets" ? "studio-asset-view" : ""} ${workspaceView === "canvas" ? "studio-canvas-view" : ""} ${directorLegacyStudio ? "studio-director-view" : ""} ${workspaceView === "director" && !directorLegacyStudio ? "studio-director2-view" : ""}`}>
        <nav className="studio-mobile-nav" aria-label="工作区导航">
          <NavLink to={lastGeneratePathRef.current} className={() => workspaceView === "generate" ? "is-active" : ""}><Sparkles size={16} />生成</NavLink>
          <NavLink to={lastDirectorPathRef.current} className={() => workspaceView === "director" ? "is-active" : ""}><Clapperboard size={16} />导演台</NavLink>
          <NavLink to={PATHS.canvas} className={() => workspaceView === "canvas" ? "is-active" : ""}><Frame size={16} />画布</NavLink>
          <NavLink to={PATHS.assets} end className={() => workspaceView === "assets" ? "is-active" : ""}><FolderOpen size={16} />资产</NavLink>
        </nav>
        <aside className="studio-icon-rail fixed bottom-0 left-0 top-14 z-20 hidden w-[76px] flex-col items-center border-r border-black/[0.05] bg-white pt-5 xl:flex">
          <div className="flex flex-col items-center gap-2">
            <NavLink to={lastGeneratePathRef.current} title="生成" aria-label="生成" className={() => `studio-global-nav-item ${workspaceView === "generate" ? "studio-global-nav-item-active" : ""}`}><Sparkles size={19} /><span>生成</span></NavLink>
            <NavLink to={lastDirectorPathRef.current} title="导演台" aria-label="导演台" className={() => `studio-global-nav-item ${workspaceView === "director" ? "studio-global-nav-item-active" : ""}`}><Clapperboard size={19} /><span>导演台</span></NavLink>
            <NavLink to={PATHS.canvas} title="画布" aria-label="画布" className={() => `studio-global-nav-item ${workspaceView === "canvas" ? "studio-global-nav-item-active" : ""}`}>{isCanvasHome ? <Network size={23} /> : workspaceView === "canvas" ? <span className="canvas-nine-dots" aria-hidden="true">{Array.from({ length: 9 }, (_, index) => <i key={index} />)}</span> : <Frame size={19} />}<span>画布</span></NavLink>
            <NavLink to={PATHS.assets} end title="资产" aria-label="资产" className={() => `studio-global-nav-item ${workspaceView === "assets" ? "studio-global-nav-item-active" : ""}`}><FolderOpen size={19} /><span>资产</span></NavLink>
          </div>
          {workspaceView === "generate" && taskRailCollapsed ? <Tooltip title="展开任务栏" placement="right"><button type="button" title="展开任务栏" aria-label="展开任务栏" onClick={() => setTaskRailCollapsed(false)} className="studio-task-rail-reopen"><PanelLeftOpen size={17} /></button></Tooltip> : null}
          {isCanvasHome && onOpenAdmin ? <Tooltip title="管理设置" placement="right"><Button type="text" className="canvas-home-nav-settings" aria-label="管理设置" icon={<Settings2 size={22} />} onClick={onOpenAdmin} /></Tooltip> : null}
        </aside>

        <aside className={`studio-task-rail fixed bottom-0 left-0 top-14 z-20 hidden w-[240px] flex-col border-r border-black/[0.05] bg-white xl:left-[76px] ${workspaceView === "generate" ? "lg:flex" : "!hidden"}`}>
          <div className="border-b border-white/[0.08] px-4 pb-3 pt-4">
            <div className="flex items-center justify-between gap-3">
              <div><p className="text-sm font-medium text-[#171a1f]">开启创作</p><p className="mt-1 text-[11px] text-[#7c8794]">{jobs.length} 个{mediaType === "image" ? "图片" : "视频"}任务</p></div>
              <button type="button" title="收起任务栏" aria-label="收起任务栏" aria-expanded="true" onClick={() => setTaskRailCollapsed(true)} className="studio-task-rail-collapse grid size-8 place-items-center rounded-lg text-[#65707c] hover:bg-black/[0.04] hover:text-[#171a1f]"><PanelLeftClose size={16} /></button>
            </div>
            {isAdminViewer ? <AdminUserFilterSelect value={adminUserFilter} options={adminUserOptions} onChange={changeAdminUserFilter} className="studio-task-user-select mt-3 w-full" /> : null}
            {isInspectingOtherUser
              ? <p className="mt-3 text-[11px] leading-5 text-[#7c8794]">正在查看 {inspectedUserLabel} 的生成任务</p>
              : <button type="button" onClick={resetCreation} className="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-black/[0.06] bg-white text-sm text-[#27303a] transition hover:bg-[#f5f7f9]"><Pencil size={15} />新对话</button>}
          </div>
          <div className="flex min-h-0 flex-1 flex-col pt-3">
            {(selectedJob || isInspectingOtherUser) && <section className="studio-task-section">
              <p className="studio-task-section-title">当前创作</p>
              {selectedJob
                ? <div className="px-4 pb-3"><TaskRow job={selectedJob} selected onSelect={selectJob} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} onCancel={confirmCancel} /></div>
                : <p className="px-4 pb-3 text-xs text-[#98a2ad]">{isInspectingOtherUser ? "从最近任务中选择一条查看" : "新对话会从这里开始"}</p>}
            </section>}
            <TaskRailHistory jobs={jobs} selectedJobId={selectedJob?.id} mediaType={mediaType} onSelect={selectJob} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} onCancel={confirmCancel} />
          </div>
        </aside>

        {workspaceView === "generate" && (
          <div className="absolute left-4 top-4 z-30 flex w-[136px] flex-col gap-2 lg:hidden">
            {isInspectingOtherUser ? null : <button type="button" onClick={resetCreation} className="flex h-9 items-center justify-center gap-2 rounded-[18px] bg-[#7047f6] px-3 text-sm text-white hover:bg-[#7c58f8]"><Plus size={16} />新建任务</button>}
            <button type="button" onClick={() => setHistoryOpen((open) => !open)} className={`flex h-9 items-center justify-center gap-2 rounded-[18px] border px-3 text-sm transition ${historyOpen ? "border-white bg-white/10" : "border-[#6947ee] bg-[#5d45aa]/20 hover:bg-[#5d45aa]/35"}`}><ListChecks size={16} />任务列表</button>
          </div>
        )}

        {workspaceView === "generate" && historyOpen && <section className={`absolute left-4 z-40 flex h-[420px] w-[min(392px,calc(100vw-32px))] flex-col overflow-hidden rounded-xl border border-black/[0.08] bg-white shadow-[0_16px_36px_rgba(22,31,44,0.16)] lg:hidden ${isInspectingOtherUser ? "top-[58px]" : "top-[106px]"}`}>
          <div className="flex items-center justify-between border-b border-black/[0.05] px-4 pb-3 pt-4"><h2 className="text-base font-medium text-[#171a1f]">任务列表</h2><button type="button" onClick={() => setHistoryOpen(false)} title="关闭任务列表" className="grid size-8 place-items-center rounded-lg text-[#65707c] hover:bg-black/[0.05] hover:text-[#171a1f]"><X size={15} /></button></div>
          {isAdminViewer ? <div className="border-b border-black/[0.05] px-4 py-2"><AdminUserFilterSelect value={adminUserFilter} options={adminUserOptions} onChange={changeAdminUserFilter} className="w-full" /></div> : null}
          {isInspectingOtherUser ? <p className="border-b border-black/[0.05] px-4 py-2 text-[11px] leading-5 text-[#7c8794]">正在查看 {inspectedUserLabel} 的生成任务</p> : null}
          <TaskRowList className="studio-task-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-4" jobs={jobs} selectedJobId={selectedJob?.id} onSelect={(jobId) => { selectJob(jobId); setHistoryOpen(false) }} onPinToggle={togglePinned} onRename={openRename} onDelete={confirmDelete} onCancel={confirmCancel} />
        </section>}

        <main className={directorLegacyStudio
          ? "director-workspace-main relative flex !h-full !max-h-full !min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden p-0"
          : workspaceView === "director"
          ? "director2-workspace-main relative flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden p-0"
          : workspaceView === "canvas"
          ? "canvas-workspace-main relative flex min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden p-0"
          : `relative mx-auto min-h-[calc(100vh-56px)] w-full min-w-0 max-w-[1180px] px-4 pb-10 pt-[112px] sm:px-8 lg:pt-12 ${workspaceView === "assets" ? "studio-asset-main" : ""} ${workspaceView === "generate" ? "studio-generate-main" : ""} ${workspaceView === "generate" && !selectedJob ? "studio-generate-empty" : ""} ${isGenerationHome ? "studio-generation-home" : ""}`
        }>
          {directorLegacyStudio ? (
            <Suspense fallback={<div className="py-24 text-center text-sm text-[#6b7280]"><LoaderCircle className="mx-auto mb-3 animate-spin text-[#7047f6]" size={24} />正在加载 AI 导演台...</div>}>
              <DirectorStudioModule
                csrfToken={csrfToken}
                allJobs={allJobs}
                onExitDirector={() => navigate(lastGeneratePathRef.current)}
              />
            </Suspense>
          ) : workspaceView === "director" ? (
            <Suspense fallback={<div className="py-24 text-center text-sm text-[#6b7280]"><LoaderCircle className="mx-auto mb-3 animate-spin text-[#7047f6]" size={24} />正在加载导演台...</div>}>
              <Director2App csrfToken={csrfToken} onExitDirector={() => navigate(lastGeneratePathRef.current)} />
            </Suspense>
          ) : workspaceView === "canvas" ? (
            <Suspense fallback={<div className="py-24 text-center text-sm text-[#6b7280]"><LoaderCircle className="mx-auto mb-3 animate-spin text-[#7047f6]" size={24} />正在加载无限画布...</div>}>
              <CanvasWorkspace csrfToken={csrfToken} />
            </Suspense>
          ) : workspaceView === "assets" ? <section className="studio-asset-library" aria-label="资产">

            {isBatchMode && assetSection === "history" && (
              <div className="studio-asset-batch-bar mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#4d6bfe]/30 bg-[#eff4ff] px-4 py-2.5">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-medium text-[#1e40af]">
                    已选择 <strong className="text-sm font-bold text-[#1d4ed8]">{selectedAssetIds.size}</strong> / {visibleAssetEntries.length} 项
                  </span>
                  <button
                    type="button"
                    onClick={selectedAssetIds.size === visibleAssetEntries.length && visibleAssetEntries.length > 0 ? handleDeselectAll : handleSelectAll}
                    className="text-xs font-medium text-[#4d6bfe] hover:underline"
                  >
                    {selectedAssetIds.size === visibleAssetEntries.length && visibleAssetEntries.length > 0 ? "取消全选" : "全选当前"}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={handleBatchDownload}
                    disabled={selectedAssetIds.size === 0}
                    className="studio-asset-batch-btn studio-asset-batch-btn-download"
                  >
                    <Download size={13} /> 批量下载 ({selectedAssetIds.size})
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenJianying(true)}
                    disabled={selectedAssetIds.size === 0}
                    className="studio-asset-batch-btn studio-asset-batch-btn-jianying"
                  >
                    <Clapperboard size={13} /> 导出剪映草稿 ({selectedAssetIds.size})
                  </button>
                  <button
                    type="button"
                    onClick={handleBatchDelete}
                    disabled={selectedAssetIds.size === 0}
                    className="studio-asset-batch-btn studio-asset-batch-btn-delete"
                  >
                    <Trash2 size={13} /> 批量删除
                  </button>
                  <button
                    type="button"
                    onClick={handleToggleBatchMode}
                    className="studio-asset-batch-btn studio-asset-batch-btn-cancel"
                  >
                    <X size={13} /> 退出批量
                  </button>
                </div>
              </div>
            )}

            <div className="studio-asset-toolbar">
              <Tabs
                className="studio-asset-tabs"
                activeKey={assetSection}
                onChange={(key) => setAssetSection(key as "history" | "subject" | "canvas")}
                items={[{ key: "history", label: "生成历史" }, { key: "subject", label: "主体" }, { key: "canvas", label: "画布" }]}
              />
              {assetSection === "history" ? (
              <div className="studio-asset-actions">
                {isAdminViewer && (
                  <AdminUserFilterSelect value={adminUserFilter} options={adminUserOptions} onChange={changeAdminUserFilter} className="w-32" />
                )}
                <Input value={assetSearch} onChange={(event) => setAssetSearch(event.target.value)} allowClear prefix={<Search className="studio-asset-search-icon" size={15} />} placeholder="搜索" aria-label="搜索资产" />
                <button
                  type="button"
                  onClick={handleToggleBatchMode}
                  className={`studio-asset-action-button ${isBatchMode ? "studio-asset-action-button-active" : ""}`}
                >
                  {isBatchMode ? "退出批量" : "批量操作"}
                </button>
                <button
                  type="button"
                  onClick={() => handleOpenJianying(false)}
                  className="studio-asset-action-button studio-asset-action-primary"
                >
                  去剪映剪辑 <ExternalLink size={14} />
                </button>
              </div>
              ) : null}
            </div>
            {assetSection === "subject" ? (
              <Suspense fallback={<div className="py-16 text-center text-sm text-[#6b7280]"><LoaderCircle className="mx-auto mb-3 animate-spin text-[#7047f6]" size={24} />正在加载资产库...</div>}>
                <DirectorAssetLibrary csrfToken={csrfToken} />
              </Suspense>
            ) : (
            <>
            <div className="studio-asset-filter-bar">
              <div className="studio-asset-type-filters">
                {[{ key: "all", label: "全部" }, { key: "image", label: "图片" }, { key: "video", label: "视频" }, { key: "audio", label: "音频" }, { key: "document", label: "文档" }].map((filter) => <button key={filter.key} type="button" onClick={() => setAssetMediaFilter(filter.key as AssetMediaFilter)} className={`studio-asset-filter ${assetMediaFilter === filter.key ? "studio-asset-filter-active" : ""}`}>{filter.label}</button>)}
              </div>
              <div className="studio-asset-sort-tools">
                <Dropdown
                  menu={{
                    items: filterMenuItems,
                    onClick: ({ key }) => {
                      if (key === "reset_filter") {
                        setFilterStatus("all")
                        setFilterRatio("all")
                        messageApi.info("已重置所有筛选条件")
                        return
                      }
                      if (key.startsWith("status:")) setFilterStatus(key.slice(7) as typeof filterStatus)
                      else if (key.startsWith("ratio:")) setFilterRatio(key.slice(6) as typeof filterRatio)
                    },
                  }}
                  trigger={["click"]}
                  placement="bottomRight"
                >
                  <button
                    type="button"
                    className={`studio-asset-sort-button ${activeFilterCount > 0 ? "studio-asset-sort-button-active" : ""}`}
                  >
                    <Filter size={13} />
                    <span>{activeFilterCount > 0 ? `筛选 (${activeFilterCount})` : "筛选"}</span>
                    <ChevronDown size={14} />
                  </button>
                </Dropdown>

                <Dropdown
                  menu={{
                    items: timeMenuItems,
                    onClick: ({ key }) => {
                      if (key === "custom") {
                        setCustomDateModalOpen(true)
                      } else {
                        setTimeFilter(key as typeof timeFilter)
                        setCustomDateRange(null)
                      }
                    },
                  }}
                  trigger={["click"]}
                  placement="bottomRight"
                >
                  <button
                    type="button"
                    className={`studio-asset-sort-button ${timeFilter !== "all" ? "studio-asset-sort-button-active" : ""}`}
                  >
                    <Clock3 size={13} />
                    <span>{timeLabel}</span>
                    <ChevronDown size={14} />
                  </button>
                </Dropdown>

                <Dropdown
                  menu={{
                    items: sortMenuItems,
                    onClick: ({ key }) => setSortOption(key as typeof sortOption),
                  }}
                  trigger={["click"]}
                  placement="bottomRight"
                >
                  <button
                    type="button"
                    className={`studio-asset-sort-button ${sortOption !== "created_desc" ? "studio-asset-sort-button-active" : ""}`}
                  >
                    <ArrowUpDown size={13} />
                    <span>{sortLabel}</span>
                    <ChevronDown size={14} />
                  </button>
                </Dropdown>
              </div>
            </div>
            {assetGroups.length ? (
              <div className="studio-asset-groups">
                {assetGroups.map((group) => (
                  <section key={`${group.label}-${group.timestamp}`} className="studio-asset-group">
                    <h2>{group.label}</h2>
                    <div className="studio-asset-grid">
                      {group.entries.map(({ id, job, output, outputIndex, generationItemId }) => {
                        const isSelected = selectedAssetIds.has(id)
                        return (
                          <div
                            key={id}
                            role="button"
                            tabIndex={0}
                            onClick={() => {
                              if (isBatchMode) {
                                handleToggleSelectAsset(id)
                              } else {
                                setPreviewMedia({
                                  kind: output.kind,
                                  src: outputPreviewSrc(output) ?? "",
                                  title: output.label,
                                  description: job.title || jobDisplayPrompt(job),
                                  job,
                                  aspectRatio: mediaAspectHint(job),
                                })
                              }
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault()
                                if (isBatchMode) handleToggleSelectAsset(id)
                              }
                            }}
                            className={`studio-asset-media-card group relative cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/35 ${
                              isSelected ? "studio-asset-card-selected ring-2 ring-[#4d6bfe]" : ""
                            }`}
                          >
                            <div className="studio-asset-media-frame relative">
                              <MediaTile item={output} allowSameOriginVideo={false} />
                              {output.kind === "video" ? (
                                <span className="studio-asset-duration">{assetDuration(job, output.kind)}</span>
                              ) : null}
                              {!isBatchMode && !isInspectingOtherUser && output.delivery_status !== "expired" ? (
                                <button
                                  type="button"
                                  className="studio-asset-canvas-button"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setCanvasInsertAsset({
                                      jobId: job.id,
                                      generationItemId,
                                      outputIndex,
                                      label: output.label,
                                    })
                                  }}
                                >
                                  <Frame size={13} />加入画布
                                </button>
                              ) : null}
                              {(isBatchMode || isSelected) && (
                                <div
                                  className={`studio-asset-checkbox-wrapper absolute left-2.5 top-2.5 z-20 flex size-5 items-center justify-center rounded transition ${
                                    isSelected
                                      ? "bg-[#4d6bfe] text-white shadow-sm"
                                      : "border border-white/80 bg-black/40 text-transparent hover:bg-black/60"
                                  }`}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleToggleSelectAsset(id)
                                  }}
                                >
                                  <Check size={13} className={isSelected ? "stroke-[3]" : "opacity-0"} />
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                ))}
                {hasMoreAssetEntries ? (
                  <div ref={assetLoadMoreRef} className="studio-asset-load-more">
                    <span>已显示 {loadedAssetEntries.length} / {visibleAssetEntries.length} 项</span>
                    <button
                      type="button"
                      className="studio-asset-action-button"
                      onClick={() => setAssetVisibleLimit((current) => current + ASSET_LOAD_BATCH)}
                    >
                      加载更多
                    </button>
                  </div>
                ) : visibleAssetEntries.length > ASSET_LOAD_BATCH ? (
                  <div className="studio-asset-load-more">
                    <span>已加载全部 {visibleAssetEntries.length} 项</span>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="studio-asset-empty">
                <FolderOpen size={22} />
                <p>
                  {assetSection === "history"
                    ? activeFilterCount > 0 || timeFilter !== "all" || assetSearch
                      ? "没有找到符合当前筛选条件的资产"
                      : "暂无生成历史资产"
                    : "暂无画布资产"}
                </p>
              </div>
            )}
            </>
            )}
          </section> : <>
          {!selectedJob && <div className={`relative z-10 text-center ${isGenerationHome ? "studio-home-heading" : "mb-12 pt-12"}`}>{selectedJobLoading ? <><h2 className="text-3xl font-semibold tracking-normal text-[#171a1f] sm:text-4xl">正在加载任务…</h2><p className="mt-3 text-base text-[#65707c]">正在读取任务详情</p></> : selectedJobMissing ? <><h2 className="text-3xl font-semibold tracking-normal text-[#171a1f] sm:text-4xl">任务不存在或已删除</h2><p className="mt-3 text-base text-[#65707c]">{jobDetailQuery.error?.message ? `${jobDetailQuery.error.message}，请从左侧重新选择任务。` : "请从左侧重新选择任务，或直接开始新的创作。"}</p></> : isInspectingOtherUser ? <><h2 className="text-3xl font-semibold tracking-normal text-[#171a1f] sm:text-4xl">正在查看 {inspectedUserLabel} 的任务</h2><p className="mt-3 text-base text-[#65707c]">从左侧选择一条生成任务查看详情</p></> : <h1>{mediaType === "image" ? "今天，想画点什么？" : "今天，想拍点什么？"}</h1>}</div>}

          {selectedJob && <section className="studio-task-stream relative z-10 mb-8" aria-label="任务详情">
            {selectedJob.rounds.map((round) => {
              const roundResults = resultsForRound(round)
              const creativeParameters = round.request_parameters.filter((parameter) => parameter.name !== "prompt" && parameter.visibility !== "internal")
              const runtimeParameters = round.request_parameters.filter((parameter) => parameter.visibility === "internal")
              const roundProgress = Math.max(0, Math.min(100, round.progress ?? 0))
              const canGenerateAgain = selectedJob.status === "succeeded" || selectedJob.status === "partial"
              const canRetryRound = round.status === "partial" || round.status === "failed" || round.status === "interrupted" || round.status === "cancelled"
              const canCancelRound = round.status === "queued" || round.status === "running" || round.status === "awaiting_refine" || round.status === "interrupted"
              const canRefineRound = round.status === "awaiting_refine"
              const relatedUpscale = activeUpscaleJob(allJobs, selectedJob.id)
              const showUpscale = mediaType === "video" && !isUpscaleJob(selectedJob) && hasOriginalVideo(selectedJob) && !isInspectingOtherUser
              const failedItems = round.generation_items.filter((item) => item.status === "failed" || item.status === "interrupted" || item.status === "cancelled")
              const cover = roundResults[0]?.output
              const roundDisplayPrompt = round.display_prompt?.trim()
              const roundPromptShownInEnglish = roundPromptLanguage[round.id] === "en" || !roundDisplayPrompt
              const roundPromptText = roundPromptShownInEnglish ? round.prompt : roundDisplayPrompt
              const featuredVideo = selectVideoResult(roundResults, videoVersionByRound[round.id])
              const isUpscaleSource = featuredVideo != null && videoResultKey(featuredVideo) === jobUpscaleSourceKey(selectedJob)
              return <article key={round.id} className={`studio-round ${mediaType === "video" ? "studio-video-round" : ""}`}>
                {mediaType === "video" ? <VideoRoundHeader
                  roundId={round.id} sequence={round.sequence} prompt={roundPromptText || ""}
                  expanded={isSelectedPromptExpanded} onExpand={() => setIsSelectedPromptExpanded((expanded) => !expanded)}
                  language={roundDisplayPrompt && roundDisplayPrompt !== round.prompt ? (roundPromptShownInEnglish ? "en" : "zh") : undefined}
                  onLanguageChange={() => setRoundPromptLanguage((current) => ({ ...current, [round.id]: roundPromptShownInEnglish ? "zh" : "en" }))}
                  references={round.references} modelName={modesQuery.data?.modes.find((mode) => mode.id === round.mode)?.name || round.mode}
                  status={round.status} statusLabel={statusText[round.status]} stage={round.stage}
                  parameters={round.request_parameters} formatParameter={parameterValue}
                  elapsed={<RoundWait source={{ created_at: round.created_at || selectedJob.created_at, finished_at: round.finished_at, elapsed_ms: round.elapsed_ms, execution_elapsed_ms: round.execution_elapsed_ms, status: round.status }} />}
                  results={roundResults} selected={featuredVideo}
                  onSelect={(key) => setVideoVersionByRound((current) => ({ ...current, [round.id]: key }))}
                  detailsOpen={videoRoundDetails?.id === round.id} runtimeExpanded={videoRoundDetails?.id === round.id && videoRoundDetails.runtime}
                  onDetailsChange={(open, runtime) => setVideoRoundDetails(open ? { id: round.id, runtime } : null)}
                  onReferencePreview={(index, url) => setPreviewMedia({ kind: "image", src: url, title: `参考图 ${index}` })}
                /> : <header className="studio-round-header flex min-w-0 gap-3">
                  <div className="studio-round-cover grid size-12 shrink-0 place-items-center overflow-hidden rounded-md bg-[#f2f4f6] text-[#7c8794]">
                    {cover ? <MediaTile item={cover} allowSameOriginVideo={false} /> : round.references[0] ? <img src={round.references[0].url} alt="任务参考图" className="h-full w-full object-cover" loading="lazy" /> : <Clapperboard size={18} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-start gap-2">
                      <p id={`round-prompt-${round.id}`} className={`min-w-0 flex-1 text-sm leading-5 text-[#1f2933] ${isSelectedPromptExpanded ? "whitespace-pre-wrap break-words" : "line-clamp-2"}`}>{roundPromptText}</p>
                      {roundDisplayPrompt && roundDisplayPrompt !== round.prompt ? (
                        <button
                          type="button"
                          onClick={() => setRoundPromptLanguage((current) => ({ ...current, [round.id]: roundPromptShownInEnglish ? "zh" : "en" }))}
                          aria-label={roundPromptShownInEnglish ? "查看中文提示词" : "查看英文提示词"}
                          className="shrink-0 text-xs text-[#4d6bfe] hover:text-[#314bc7]"
                        >
                          {roundPromptShownInEnglish ? "中文" : "English"}
                        </button>
                      ) : null}
                      <button type="button" onClick={() => setIsSelectedPromptExpanded((expanded) => !expanded)} aria-controls={`round-prompt-${round.id}`} aria-expanded={isSelectedPromptExpanded} className="shrink-0 text-xs text-[#4d6bfe] hover:text-[#314bc7]">{isSelectedPromptExpanded ? "收起" : "展开"}</button>
                    </div>
                    <p className={`studio-round-status mt-1.5 flex flex-wrap items-center gap-x-2 text-xs ${statusColor[round.status]}`}>
                      <span>第 {round.sequence} 轮 · {statusText[round.status]} · {round.stage}</span>
                      <RoundWait source={{
                        created_at: round.created_at || selectedJob.created_at,
                        finished_at: round.finished_at,
                        elapsed_ms: round.elapsed_ms,
                        execution_elapsed_ms: round.execution_elapsed_ms,
                        status: round.status,
                      }} />
                    </p>
                    {round.error ? <div className="studio-round-error mt-1"><JobErrorNotice error={round.error} hideSummary /></div> : null}
                  </div>
                </header>}
                {mediaType === "video" && ["queued", "running", "awaiting_refine", "interrupted"].includes(round.status) ? <p className="studio-video-live-stage" role="status">{round.stage}</p> : null}
                {mediaType === "video" && round.error ? <div className="studio-round-error"><JobErrorNotice error={round.error} /></div> : null}

                {mediaType !== "video" && (creativeParameters.length > 0 || runtimeParameters.length > 0) && <details className="studio-round-details">
                  <summary>任务详情</summary>
                  <dl className="studio-round-parameter-list">
                    {creativeParameters.map((parameter) => <div key={parameter.name}><dt>{parameter.label}</dt><dd>{parameterValue(parameter)}</dd></div>)}
                    {runtimeParameters.map((parameter) => <div key={parameter.name} className="studio-round-runtime-parameter"><dt>{parameter.label}</dt><dd>{parameterValue(parameter)}</dd></div>)}
                  </dl>
                </details>}

                {mediaType !== "video" && round.references.length > 0 && <div className="studio-round-references">{round.references.map((reference) => <button key={reference.index} type="button" onClick={() => setPreviewMedia({ kind: "image", src: reference.url, title: `参考图 ${reference.index}` })} className="group relative h-14 w-20 shrink-0 overflow-hidden rounded-lg border border-black/[0.08] bg-[#f2f4f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/40">
                  <img src={reference.url} alt={`参考图 ${reference.index}`} className="h-full w-full object-cover transition duration-200 group-hover:scale-105" />
                  <span className="studio-reference-thumb-label absolute inset-x-0 bottom-0 px-1.5 py-1 text-left text-[10px]">参考图 {reference.index}</span>
                </button>)}</div>}

                {round.status === "running" && <div className="studio-round-progress flex items-center gap-2">
                  <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-[#e8ecf1]" role="progressbar" aria-label={`第 ${round.sequence} 轮生成进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={roundProgress}><div className="h-full rounded-full bg-[#4d6bfe] transition-[width] duration-500" style={{ width: `${roundProgress}%` }} /></div>
                  <span className="w-9 text-right text-[11px] tabular-nums text-[#65707c]">{roundProgress}%</span>
                </div>}

                {canRefineRound && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                  <p className="text-xs leading-5 text-amber-800">一采预览已生成，尚未保存为最终成片。确认后会用同一 seed 只跑二采精修；保留一采则直接把预览作为成片。</p>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={confirmRefineMutation.isPending || skipRefineMutation.isPending} onClick={() => confirmRefineMutation.mutate(selectedJob.id)} className="studio-round-action">
                      {confirmRefineMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <Sparkles size={16} />}确认二采
                    </button>
                    <button type="button" disabled={confirmRefineMutation.isPending || skipRefineMutation.isPending} onClick={() => skipRefineMutation.mutate(selectedJob.id)} className="studio-round-action">
                      {skipRefineMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <Check size={16} />}保留一采
                    </button>
                  </div>
                </div>}

                {roundResults.length > 0 && <Suspense fallback={<div className="flex min-h-56 items-center justify-center text-sm text-[#65707c]">正在加载结果...</div>}>
                  {mediaType === "image" ? <ImageStudioModule embedded showHeading={false} results={roundResults as ImageResult[]} roundCount={1} onDownload={(result) => downloadOutput(selectedJob, result.outputIndex, result.output)} onCreateVideo={isInspectingOtherUser ? undefined : (result) => void createVideoFromImage(result)} onPreview={(result) => result.src && setPreviewMedia({ kind: "image", src: result.src, title: result.output.label, description: roundDisplayPrompt || selectedJob.prompt, job: selectedJob, aspectRatio: mediaAspectHint(round) || mediaAspectHint(selectedJob) })} /> : <VideoStudioModule embedded showHeading={false}
                    results={featuredVideo ? [featuredVideo] : []} roundCount={1}
                    aspectRatio={mediaAspectHint(round) || mediaAspectHint(selectedJob)}
                    upscale={showUpscale ? {
                      disabled: !isUpscaleSource || !canRequestJobUpscale(selectedJob, allJobs, isInspectingOtherUser) || upscaleMutation.isPending,
                      pending: upscaleMutation.isPending || Boolean(relatedUpscale),
                      hint: upscaleDisabledReason(selectedJob, allJobs, isInspectingOtherUser) || (!isUpscaleSource ? "超分使用此任务的最新原片，请切换到对应原片版本" : "把此原片放大 2 倍，原片保留"),
                      engines: upscaleEngines,
                      onClick: (engine) => upscaleMutation.mutate({ jobId: selectedJob.id, engine }),
                    } : undefined}
                    upscaleStage={relatedUpscale?.stage}
                    onPreview={(result) => result.src && setPreviewMedia({ kind: "video", src: result.src, title: result.output.label, description: roundDisplayPrompt || selectedJob.prompt, job: allJobs.find((item) => item.id === result.jobId) ?? selectedJob, aspectRatio: mediaAspectHint(round) || mediaAspectHint(selectedJob) })}
                    onDownload={(result) => downloadOutput(allJobs.find((item) => item.id === result.jobId) ?? selectedJob, result.outputIndex, result.output)}
                    onAddToCanvas={isInspectingOtherUser ? undefined : (result) => setCanvasInsertAsset({
                      jobId: result.jobId ?? selectedJob.id, generationItemId: result.generationItemId,
                      outputIndex: result.outputIndex, label: result.output.label,
                    })}
                    onExportJianying={(result) => {
                      setJianyingSelectedItems([{
                        id: videoResultKey(result), title: result.output.label, kind: "video", path: result.output.path,
                        url: result.output.download_url ?? result.output.cloud_url ?? result.src ?? mediaUrl(result.output.path),
                      }])
                      setJianyingModalOpen(true)
                    }}
                    onShowRuntime={() => setVideoRoundDetails({ id: round.id, runtime: true })}
                    onDeleteTask={() => confirmDelete(selectedJob)}
                  />}
                </Suspense>}

                {failedItems.length > 0 && mediaType === "image" && <ul className="mt-3 space-y-2 text-xs leading-5 text-red-600">
                  {failedItems.map((item) => (
                    <li key={item.id}>
                      <span>第 {item.index} 张生成失败</span>
                      {item.error && item.error !== round.error ? <JobErrorNotice error={item.error} hideSummary /> : null}
                    </li>
                  ))}
                </ul>}

                {round.status === "interrupted" && mediaType === "video" && <p className="text-xs leading-5 text-[#4b5563]">ComfyUI 恢复后会按原参数自动重新生成。显存里未完成的推理无法续跑，也可立即手动重新提交。</p>}
                {round.status === "cancelled" && mediaType === "video" && <p className="text-xs leading-5 text-[#4b5563]">已停止生成，不会自动重新提交。未完成的推理无法续跑，需要时可手动重新提交。</p>}
                {round.status === "cancelled" && mediaType === "image" && <p className="text-xs leading-5 text-[#4b5563]">工作台已停止等待。云端任务可能仍会继续计费，尚未取回的图片不会自动拉取。</p>}
                <div className="studio-round-actions" aria-label={`第 ${round.sequence} 轮操作`}>
                  {isInspectingOtherUser ? null : <button type="button" onClick={() => void reEditRound(selectedJob, round)} className="studio-round-action"><Pencil size={16} />重新编辑</button>}
                  {canCancelRound && <button type="button" disabled={cancelMutation.isPending} onClick={() => confirmCancel(selectedJob)} className="studio-round-action studio-round-action-stop">{cancelMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <CircleStop size={16} />}停止生成</button>}
                  {!isInspectingOtherUser && canGenerateAgain && <button type="button" disabled={createRoundMutation.isPending} onClick={() => createRoundMutation.mutate(selectedJob)} className="studio-round-action">{createRoundMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <RotateCw size={16} />}再次生成</button>}
                  {!isInspectingOtherUser && canRetryRound && mediaType === "image" && <button type="button" disabled={retryFailedMutation.isPending} onClick={() => retryFailedMutation.mutate({ jobId: selectedJob.id, roundId: round.id })} className="studio-round-action">{retryFailedMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <RotateCw size={16} />}重试失败项</button>}
                  {!isInspectingOtherUser && canRetryRound && mediaType === "video" && <button type="button" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedJob.id)} className="studio-round-action">{retryMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <Send size={16} />}重新提交</button>}
                  <Dropdown trigger={["click"]} popupRender={(menu) => <div className="studio-task-menu studio-round-menu">{menu}</div>} menu={{ items: [{ key: "delete", danger: true, icon: <Trash2 size={14} />, label: "删除任务" }], onClick: ({ domEvent }) => { domEvent.stopPropagation(); confirmDelete(selectedJob) } }}>
                    <button type="button" aria-label={`更多操作：第 ${round.sequence} 轮`} title="更多操作" className="studio-round-action studio-round-more"><MoreHorizontal size={18} /></button>
                  </Dropdown>
                </div>
              </article>
            })}
          </section>}

          {!isInspectingOtherUser && isComposerCompact && <button type="button" onClick={() => returnToComposer()} className="studio-return-bottom" title="回到底部"><span>回到底部</span><ChevronDown size={15} /></button>}
          {!isInspectingOtherUser && <form
            id="studio-composer"
            data-media-type={mediaType}
            onSubmit={submit}
            onDragOver={(event) => {
              if (!event.dataTransfer.types.includes("Files")) return
              event.preventDefault()
              const canAccept = Boolean(workflow && workflow.reference_mode !== "none" && references.length < workflow.max_references)
              event.dataTransfer.dropEffect = canAccept ? "copy" : "none"
            }}
            onDrop={(event) => {
              if (!event.dataTransfer.files.length) return
              event.preventDefault()
              appendFiles(event.dataTransfer.files)
            }}
            className={`studio-composer-form relative z-20 mx-auto max-w-[1080px] border border-black/[0.05] bg-white p-4 shadow-[0_16px_36px_rgba(22,31,44,0.10)] sm:rounded-[24px] sm:p-5 lg:sticky lg:bottom-5 ${!selectedJob ? "studio-composer-inline" : ""} ${isComposerCompact ? "studio-composer-collapsed" : ""}`}
          >
            <div className="studio-composer-service-meta absolute -top-8 right-7 flex max-w-[calc(100%-56px)] items-center gap-1.5 text-sm text-[#babac3]">
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
                <div className="studio-composer-editor-meta mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                  <div className="studio-composer-workflow-meta flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="truncate text-xs text-[#aaaab4]">{workflow?.name || "正在加载工作流"}</span>
                    {referenceHint ? <span className="studio-composer-hint">{referenceHint}</span> : null}
                    {reusableOptimized && mediaType === "video" ? <span className="studio-composer-hint">中文预览 · 生成用英文</span> : null}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <Dropdown trigger={["click"]} menu={{ items: promptIdeas.map(({ label, icon: Icon, prompt: ideaPrompt }) => ({ key: label, label, icon: <Icon size={14} />, onClick: () => applyPromptIdea(ideaPrompt) })) }}>
                      <Button type="text" size="small" className="studio-prompt-tool" title="提示词灵感">灵感</Button>
                    </Dropdown>
                    <Tooltip title={optimizeToggleTooltip}>
                      <span className={`studio-prompt-optimize ${autoOptimizeActive ? "is-on" : ""}`}>
                        <Sparkles size={12} aria-hidden />
                        <span className="whitespace-nowrap">提示词优化</span>
                        <Switch
                          size="small"
                          checked={autoOptimizeActive}
                          disabled={!llmAvailable || isInspectingOtherUser || autoOptimizing || optimizeMutation.isPending || createMutation.isPending}
                          onChange={togglePromptOptimize}
                          aria-label="生成前自动优化提示词"
                        />
                      </span>
                    </Tooltip>
                    {mediaType === "video" && h3Skills.length > 0 ? (
                      <Dropdown
                        placement="bottomRight"
                        trigger={["click"]}
                        menu={{
                          items: [
                            {
                              key: "header",
                              type: "group",
                              label: <span className="text-[11px] font-semibold text-[#6b7280]">提示词优化风格</span>,
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
                              onClick: () => setSelectedSkillId(skill.id),
                            })),
                          ],
                        }}
                      >
                        <button
                          type="button"
                          disabled={autoOptimizing || optimizeMutation.isPending}
                          title="选择提示词优化风格"
                          className="studio-prompt-tool"
                        >
                          <span className="max-w-[150px] truncate">{activeSkill?.name ? `${activeSkill.icon} ${activeSkill.name}` : "通用风格"}</span>
                          <ChevronDown size={11} className="opacity-60" />
                        </button>
                      </Dropdown>
                    ) : null}
                    <button
                      type="button"
                      disabled={!llmAvailable || isInspectingOtherUser || !prompt.trim() || autoOptimizing || optimizeMutation.isPending || createMutation.isPending}
                      onClick={() => optimizeMutation.mutate()}
                      title={mediaType === "video" ? "立即调用大模型，按 MiniMax H3 官方规范润色当前提示词" : "立即调用大模型润色当前提示词"}
                      className="studio-prompt-polish"
                    >
                      {optimizeMutation.isPending ? <LoaderCircle className="animate-spin" size={12} /> : <WandSparkles size={12} />}
                      <span>{optimizeMutation.isPending ? "润色中" : "立即润色"}</span>
                    </button>
                    {reusableOptimized && mediaType === "video" ? (
                      <button
                        type="button"
                        onClick={() => setEnglishPromptOpen(true)}
                        title="查看本次生成实际提交的英文 H3 提示词"
                        className="studio-prompt-tool"
                      >
                        <Languages size={12} />
                        <span>查看英文</span>
                      </button>
                    ) : null}
                    {optimizeUndo && prompt === optimizeUndo.after && !optimizeMutation.isPending ? (
                      <button
                        type="button"
                        onClick={() => { setPrompt(optimizeUndo.before); setOptimizeUndo(null); setOptimizedPrompt(null) }}
                        className="shrink-0 text-[11px] text-[#797982] transition hover:text-[#b5a4ff]"
                      >
                        撤销优化
                      </button>
                    ) : null}
                  </div>
                </div>
                <Input.TextArea
                  aria-label="创作提示词"
                  ref={promptRef}
                  value={prompt}
                  onFocus={() => { if (isComposerCompact) returnToComposer(true) }}
                  onChange={(event) => setPrompt(event.target.value)}
                  onPaste={(event) => {
                    const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"))
                    if (!files.length || !workflow || workflow.reference_mode === "none") return
                    event.preventDefault()
                    appendFiles(files)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                      event.preventDefault()
                      if (canSubmit) void submitTask()
                    }
                  }}
                  placeholder={isGenerationHome ? (workflow?.reference_mode === "none" ? "描述画面、动作和运镜，让想法成为下一帧…" : "描述一个画面，或上传参考图开始创作…") : workflow?.description || "描述镜头、动作、运镜、音效和氛围"}
                  className="studio-prompt-input h-[106px] w-full resize-none border-0 bg-transparent p-0 text-[15px] leading-6 text-[#d7d7dc] outline-none placeholder:text-[#777780]"
                />
                {isGenerationHome && workflow?.reference_mode !== "none" && !prompt.trim() && <p className="studio-home-upload-hint">支持粘贴图片，或拖入参考图</p>}
                {workflow?.reference_mode === "collection" && references.length > 0 && <div className="studio-picture-tags mt-2 flex flex-wrap gap-1.5">{references.map((asset, index) => <button key={asset.id} type="button" onClick={() => addPictureTag(index + 1)} className="rounded-md border border-[#7047ff]/40 bg-[#7047ff]/10 px-2 py-1 text-[11px] text-[#b5a4ff] hover:bg-[#7047ff]/20">&lt;Picture {index + 1}&gt;</button>)}</div>}
              </div>
            </div>


            <div className="studio-composer-toolbar mt-4 flex flex-col gap-3 border-t border-white/[0.08] pt-4 lg:flex-row lg:items-center">
              <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:flex sm:flex-wrap">
                <div className="studio-media-select flex h-9 min-w-0 items-center rounded-lg border border-[#37373b] bg-[#222226] px-1 shadow-[0_6px_16px_rgba(0,0,0,0.12)] sm:w-[140px]">
                  <Select aria-label="选择生成类型" value={mediaType} onChange={(value) => switchMedia(value as "image" | "video")} className="studio-select min-w-0 flex-1" popupClassName="studio-select-popup studio-media-select-popup" options={[{ value: "image", label: <span className="studio-select-option"><ImagePlus size={14} />图片生成</span> }, { value: "video", label: <span className="studio-select-option"><Video size={14} />视频生成</span> }]} />
                </div>
                <div className="studio-control-shell flex h-9 min-w-0 items-center gap-2 rounded-lg border border-[#37373b] bg-[#222226] px-3 shadow-[0_6px_16px_rgba(0,0,0,0.12)] sm:w-[280px]">
                  <Settings2 size={16} className="shrink-0 text-[#947dff]" />
                  <Select aria-label="选择工作流" value={workflowId} onChange={(value) => selectWorkflow(String(value))} showSearch optionFilterProp="label" className="studio-select min-w-0 flex-1" popupClassName="studio-select-popup studio-workflow-select-popup" options={groupedWorkflowOptions(workflows)} />
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
                {advancedOptionDefinitions.length > 0 && <Button aria-expanded={advancedOptionsOpen} onClick={() => setAdvancedOptionsOpen((open) => !open)} className="studio-more-settings flex h-10 items-center justify-center gap-2 rounded-lg border border-[#37373b] bg-[#222226] px-3 text-sm text-[#d8d8df] transition hover:bg-[#29292f] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7047ff]/45"><SlidersHorizontal size={16} className="text-[#947dff]" />更多设置</Button>}
              </div>
              <Tooltip title={!workflow?.available ? workflow?.unavailable_reason : undefined}>
                <Button htmlType="submit" type="primary" disabled={!canSubmit} className="studio-generate-submit flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl px-5 text-sm lg:w-[154px]">{(createMutation.isPending || autoOptimizing) ? <LoaderCircle className="animate-spin" size={17} /> : <Sparkles size={17} />}{autoOptimizing ? "正在润色…" : mediaType === "image" ? "开始生图" : "开始生成"}</Button>
              </Tooltip>
              {isGenerationHome && <span className="studio-home-submit-shortcut" aria-hidden>Ctrl + Enter</span>}
            </div>
            {refineHint ? (
              <p className="mt-3 text-xs leading-5 text-[#b9b6c9]">
                二采输出 {refineHint.resolutionLabel || `${refineHint.effectiveMegapixels.toFixed(1)} MP`}
                （{refineHint.effectiveMegapixels.toFixed(1)} MP）
                {refineHint.estimatedSeconds
                  ? `，预计全程 ${refineHint.durationLabel}（一采 + 二采）`
                  : "，超出平台安全预算，可能超过 30 分钟并可能因显存不足失败"}
                {refineHint.capped
                  ? `；目标 ${refineHint.requestedMegapixels.toFixed(1)} MP 已按片长自动降档`
                  : refineHint.forced
                    ? "；强制高清将严格按目标输出"
                    : ""}
              </p>
            ) : null}
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
          </form>}

          {isGenerationHome && <GenerationHomeSections
            jobs={allJobs} loading={jobsQuery.isLoading} error={jobsQuery.error?.message}
            onRetry={() => void jobsQuery.refetch()}
            onOpen={(jobId) => { const job = allJobs.find((item) => item.id === jobId); if (job) openGenerateJob(job) }}
            onImageCreate={() => { switchMedia("image"); requestAnimationFrame(() => promptRef.current?.focus()) }}
          />}

          <Modal
            open={englishPromptOpen && Boolean(reusableOptimized)}
            title="英文 H3 提示词"
            width={760}
            okText="复制英文"
            cancelText="关闭"
            onOk={() => void copyEnglishPrompt()}
            onCancel={() => setEnglishPromptOpen(false)}
            destroyOnHidden
          >
            <p className="mb-2 text-xs leading-5 text-[#65707c]">这是生成 MiniMax H3 视频时实际提交的英文提示词；界面默认显示中文对照。</p>
            <Input.TextArea
              value={reusableOptimized?.english || ""}
              readOnly
              autoSize={{ minRows: 8, maxRows: 18 }}
              className="font-mono text-xs"
            />
          </Modal>
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

          <JianyingExportModal
            open={jianyingModalOpen}
            onClose={() => setJianyingModalOpen(false)}
            items={jianyingSelectedItems}
            onRemoveItem={(id) => setJianyingSelectedItems((prev) => prev.filter((item) => item.id !== id))}
          />

          <AddToCanvasModal
            open={Boolean(canvasInsertAsset)}
            csrfToken={csrfToken}
            asset={canvasInsertAsset}
            onClose={() => setCanvasInsertAsset(null)}
          />

          <Modal
            open={customDateModalOpen}
            title="选择自定义时间范围"
            onCancel={() => setCustomDateModalOpen(false)}
            onOk={() => {
              if (customDateRangeValue && customDateRangeValue[0] && customDateRangeValue[1]) {
                setCustomDateRange([
                  customDateRangeValue[0].format("YYYY-MM-DD"),
                  customDateRangeValue[1].format("YYYY-MM-DD"),
                ])
                setTimeFilter("custom")
                setCustomDateModalOpen(false)
              } else {
                messageApi.warning("请选择有效的开始与结束日期")
              }
            }}
            okText="应用筛选"
            cancelText="取消"
            destroyOnHidden
            centered
          >
            <div className="py-4">
              <DatePicker.RangePicker
                className="w-full"
                onChange={(dates) => setCustomDateRangeValue(dates)}
              />
            </div>
          </Modal>

        </main>
        <aside className="fixed bottom-0 right-0 top-14 z-20 hidden w-14 flex-col items-center border-l border-white/[0.06] bg-[#111218] pt-4 xl:hidden"><button type="button" onClick={() => setHistoryOpen(true)} title="任务记录" className="grid size-10 place-items-center rounded-lg bg-white/[0.06] text-[#c5c5ca] hover:bg-white/10 hover:text-white"><ListChecks size={19} /></button><History className="mt-6 text-[#d7d7dc]" size={16} /><span className="mt-2 text-sm leading-5 text-white [writing-mode:vertical-rl]">任务记录</span><span className="mt-3 size-2 rounded-full bg-[#7047ff]" /></aside>
      </div>
      {previewMedia && <MediaPreviewModal
        open
        kind={previewMedia.kind}
        src={previewMedia.src}
        title={previewMedia.title}
        description={previewMedia.description}
        aspectRatio={previewMedia.aspectRatio}
        onClose={() => setPreviewMedia(null)}
        actions={previewMedia.job ? [{
          key: "open-job",
          label: "打开关联任务",
          icon: <ExternalLink size={15} />,
          onClick: () => { openGenerateJob(previewMedia.job!); setPreviewMedia(null) },
        }] : []}
      />}
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
  const compactChrome = "flex h-9 min-w-0 items-center rounded-lg border border-[#37373b] bg-[#222226] shadow-[0_6px_16px_rgba(0,0,0,0.12)]"
  if (definition.type === "boolean") {
    const toggle = <Switch aria-label={definition.label} checked={Boolean(value)} onChange={(checked) => onChange(name, checked)} size="small" />
    if (compact) {
      return <div title={definition.description} className="studio-control-shell flex h-9 w-full min-w-0 items-center justify-between gap-3 rounded-lg border border-[#37373b] bg-[#222226] px-3 text-xs text-[#d8d8df] sm:w-[172px]">
        <span className="min-w-0 leading-4">{definition.label}</span>
        {toggle}
      </div>
    }
    return <div title={definition.description} className="studio-control-shell min-w-0">
      <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>
      <div className="flex min-h-8 items-center">{toggle}</div>
    </div>
  }
  const selectOptions = definition.ui_options?.map((item) => ({ ...item, value: String(item.value) }))
    ?? definition.enum?.map((item) => ({ value: String(item), label: `${item}${definition.unit ? ` ${definition.unit}` : ""}` }))
    ?? []
  if (definition.ui_control === "visual-settings") {
    const companionNames = definition.ui_companions ?? (definition.ui_companion ? [definition.ui_companion] : [])
    const companions = companionNames.flatMap((companionName) => {
      const companion = definitions[companionName]
      if (!companion || !optionVisible(companion, values)) return []
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
  if (definition.ui_control === "select" || (selectOptions.length && definition.ui_control !== "input-number")) {
    return <div title={definition.description} className={`studio-control-shell ${compact ? `${compactChrome} gap-2 px-3 w-full studio-compact-select` : "min-w-0"}`} style={compact ? { "--studio-compact-select-width": `${compactSelectWidth(selectOptions)}px` } as CSSProperties : undefined}>
      {!compact && <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>}
      {compact ? <Gauge size={16} className="shrink-0 text-[#947dff]" /> : null}
      <Select
        aria-label={definition.label}
        value={String(value)}
        onChange={(nextValue) => onChange(name, String(nextValue))}
        className="studio-select min-w-0 w-full flex-1"
        popupClassName="studio-select-popup"
        options={selectOptions}
      />
    </div>
  }
  if (definition.type === "number" || definition.type === "integer") {
    return <div title={definition.description} className={`studio-control-shell ${compact ? `${compactChrome} gap-1 px-2 w-full sm:w-[112px]` : "min-w-0"}`}>
      {!compact && <span className="mb-1.5 block text-[11px] text-[#9898a2]">{definition.label}</span>}
      <InputNumber aria-label={definition.label} value={Number(value)} onChange={(nextValue) => { if (nextValue !== null) onChange(name, String(nextValue)) }} min={definition.minimum} max={definition.maximum} step={definition.step} controls className="studio-number min-w-0 w-full flex-1" addonAfter={!compact ? definition.unit : undefined} />
      {compact && definition.unit ? <span className="studio-toolbar-unit shrink-0 pr-0.5 text-xs text-[#85858d]">{definition.unit}</span> : null}
    </div>
  }
  return <div title={definition.description} className={`studio-control-shell ${compact ? `${compactChrome} px-3 w-full sm:w-[172px]` : "min-w-0"}`}>
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
    <button type="button" aria-label={`设置${definition.label}，当前${displayValue}`} className={`studio-parameter-trigger studio-duration-trigger ${compact ? "w-full sm:w-[92px]" : "w-full"}`}>
      <Clock3 size={16} className="shrink-0 text-[#a995ff]" />
      <span className="min-w-0 flex-1 text-left">{displayValue}</span>
      <ChevronDown size={14} className="shrink-0 text-[#85858d]" />
    </button>
  </Popover>
}

function ReferencePanel({
  workflow, references, onAppend, onReplaceKeyframe, onRemove, onMove, onPreview, fileInputRef,
}: {
  workflow?: Workflow; references: ReferenceAsset[]; onAppend: (files: FileList | File[] | null) => void
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
