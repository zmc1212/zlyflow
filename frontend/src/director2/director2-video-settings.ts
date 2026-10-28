export const DIRECTOR2_DEFAULT_VIDEO_WORKFLOW = "minimax-h3-director-accel-r2v"
export const DIRECTOR2_VIDEO_SETTINGS_STORAGE_PREFIX = "director2-episode-video-settings:"
export const DIRECTOR2_EPISODE_HIDDEN_OPTIONS = new Set(["duration", "custom_steps"])
export const DIRECTOR2_BOOLEAN_VIDEO_OPTIONS = new Set(["refine_enabled"])

export type Director2OptionVisibility = "primary" | "advanced" | "internal"

export type Director2OptionDefinition = {
  label: string
  type: "string" | "number" | "integer" | "boolean"
  default: string | number | boolean
  enum?: Array<string | number>
  ui_group?: Director2OptionVisibility
  ui_options?: Array<{ value: string | number; label: string; hint?: string }>
  description?: string
  megapixels_by_quality?: Record<string, number>
  ui_resolution_preview?: { multiple?: number; max_width?: number; max_height?: number }
  ui_visible_when?: Record<string, string | number | boolean>
}

export type Director2WorkflowMode = {
  id: string
  name: string
  media_type?: string
  supports_timeline?: boolean
  supports_multi_segment?: boolean
  reference_mode?: string
  max_references?: number
  hidden_from_catalog?: boolean
  catalog_group?: string
  catalog_group_label?: string
  catalog_group_order?: number
  parameters?: Array<{
    name: string
    schema?: { properties?: Record<string, Director2OptionDefinition> } | null
  }>
}

export type EpisodeVideoRenderMode = "episode" | "shot"

export type Director2GenerateVideoResult = {
  job_id?: string
  job_ids?: string[]
  status?: string
  render_mode?: EpisodeVideoRenderMode | string
  render_scope?: string
  submitted?: number
  skipped?: number
  shot_count?: number
}

export type VideoWorkflowSelectOption = { value: string; label: string }
export type VideoWorkflowSelectGroup = { label: string; options: VideoWorkflowSelectOption[] }

export type Director2VideoOptionField = {
  name: string
  definition: Director2OptionDefinition
  ui_group: Exclude<Director2OptionVisibility, "internal">
}

export const DIRECTOR2_VIDEO_FALLBACK_FIELDS: Director2VideoOptionField[] = [
  {
    name: "aspect_ratio",
    ui_group: "primary",
    definition: {
      label: "画面比例",
      type: "string",
      default: "16:9",
      ui_group: "primary",
      ui_options: [
        { value: "16:9", label: "16:9 横屏" },
        { value: "9:16", label: "9:16 竖屏" },
        { value: "1:1", label: "1:1 方形" },
        { value: "4:3", label: "4:3 标准" },
        { value: "3:4", label: "3:4 竖版" },
        { value: "3:2", label: "3:2 摄影" },
        { value: "2:3", label: "2:3 竖版摄影" },
        { value: "21:9", label: "21:9 超宽屏" },
      ],
    },
  },
  {
    name: "weight_profile",
    ui_group: "primary",
    definition: {
      label: "模型体积",
      type: "string",
      default: "full",
      ui_group: "primary",
      ui_options: [
        { value: "full", label: "完整（32 GB）" },
        { value: "pruned", label: "精简（20 GB）" },
      ],
      ui_visible_when: { refine_enabled: false },
    },
  },
  {
    name: "quality",
    ui_group: "advanced",
    definition: {
      label: "分辨率",
      type: "string",
      default: "0.4",
      ui_group: "advanced",
      megapixels_by_quality: {
        "0.2": 0.2, "0.3": 0.3, "0.4": 0.4, "0.5": 0.5, "0.6": 0.6, "0.7": 0.7,
        "0.8": 0.8, "0.9": 0.9, "0.98": 0.98, "1.0": 1.0, "1.2": 1.2, "1.5": 1.5,
        "1.8": 1.8, "2.0": 2.0,
      },
      ui_resolution_preview: { multiple: 32 },
      ui_visible_when: { refine_enabled: false },
      ui_options: [
        { value: "0.2", label: "0.2 MP" }, { value: "0.3", label: "0.3 MP" },
        { value: "0.4", label: "0.4 MP" }, { value: "0.5", label: "0.5 MP" },
        { value: "0.6", label: "0.6 MP" }, { value: "0.7", label: "0.7 MP" },
        { value: "0.8", label: "0.8 MP" }, { value: "0.9", label: "0.9 MP" },
        { value: "0.98", label: "0.98 MP" }, { value: "1.0", label: "1.0 MP" },
        { value: "1.2", label: "1.2 MP" }, { value: "1.5", label: "1.5 MP" },
        { value: "1.8", label: "1.8 MP" }, { value: "2.0", label: "2.0 MP" },
      ],
    },
  },
  {
    name: "speed",
    ui_group: "advanced",
    definition: {
      label: "生成质量",
      type: "string",
      default: "balanced",
      ui_group: "advanced",
      ui_options: [
        { value: "balanced", label: "均衡（20 步）" },
        { value: "quality", label: "精细（25 步）" },
      ],
      ui_visible_when: { refine_enabled: false },
    },
  },
  {
    name: "refine_enabled",
    ui_group: "primary",
    definition: {
      label: "二采精修",
      type: "boolean",
      default: false,
      ui_group: "primary",
      description: "先以 0.4 MP 生成一采，再用 H3 3D latent 放大到目标画质做第二步精修。",
    },
  },
  {
    name: "refine_quality_mode",
    ui_group: "primary",
    definition: {
      label: "清晰度策略",
      type: "string",
      default: "auto",
      ui_group: "primary",
      enum: ["auto", "force"],
      ui_options: [
        { value: "auto", label: "自动（推荐）" },
        { value: "force", label: "强制高清" },
      ],
      ui_visible_when: { refine_enabled: true },
    },
  },
  {
    name: "refine_quality",
    ui_group: "primary",
    definition: {
      label: "目标清晰度",
      type: "string",
      default: "1.0",
      ui_group: "primary",
      enum: ["1.0", "2.0"],
      ui_options: [
        { value: "1.0", label: "高清 1.0 MP" },
        { value: "2.0", label: "超清 2.0 MP" },
      ],
      ui_visible_when: { refine_enabled: true },
    },
  },
]

export function optionSchemaFromMode(mode: Director2WorkflowMode | undefined): Record<string, Director2OptionDefinition> {
  const options = mode?.parameters?.find((item) => item.name === "options")
  return options?.schema?.properties || {}
}

export function videoOptionVisible(
  field: Director2VideoOptionField,
  values: Record<string, string>,
): boolean {
  const condition = field.definition.ui_visible_when
  if (!condition) return true
  return Object.entries(condition).every(([name, expected]) => (
    String(values[name] ?? field.definition.default) === String(expected)
  ))
}

export function visibleVideoOptionFields(mode: Director2WorkflowMode | undefined): Director2VideoOptionField[] {
  const properties = optionSchemaFromMode(mode)
  if (!Object.keys(properties).length) return DIRECTOR2_VIDEO_FALLBACK_FIELDS
  const fields: Director2VideoOptionField[] = []
  for (const [name, definition] of Object.entries(properties)) {
    if (DIRECTOR2_EPISODE_HIDDEN_OPTIONS.has(name)) continue
    const group = definition.ui_group || "internal"
    if (group !== "primary" && group !== "advanced") continue
    fields.push({ name, definition, ui_group: group })
  }
  return fields.length ? fields : DIRECTOR2_VIDEO_FALLBACK_FIELDS
}

export function defaultVideoOptionValues(fields: Director2VideoOptionField[]): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.name, String(field.definition.default)]))
}

export function episodeVideoRenderMode(mode: Director2WorkflowMode | undefined | null): EpisodeVideoRenderMode {
  if (mode?.supports_timeline && mode?.supports_multi_segment) return "episode"
  return "shot"
}

export function videoWorkflowRenderLabel(mode: Director2WorkflowMode): string {
  return episodeVideoRenderMode(mode) === "episode" ? "整集直出" : "逐镜"
}

export function timelineVideoWorkflows(modes: Director2WorkflowMode[]): Director2WorkflowMode[] {
  const listed = modes.filter((mode) => (
    (mode.media_type || "video") === "video"
    && mode.reference_mode === "collection"
    && (mode.max_references ?? 0) >= 3
    && !mode.hidden_from_catalog
  ))
  if (listed.length) return listed
  const fallback = modes.find((mode) => mode.id === DIRECTOR2_DEFAULT_VIDEO_WORKFLOW)
  return fallback ? [fallback] : []
}

export function groupedVideoWorkflowOptions(workflows: Director2WorkflowMode[]): VideoWorkflowSelectGroup[] {
  const groups = new Map<string, { order: number; label: string; options: VideoWorkflowSelectOption[] }>()
  for (const mode of workflows) {
    const groupId = mode.catalog_group || "_ungrouped"
    const existing = groups.get(groupId) || {
      order: mode.catalog_group_order ?? 100,
      label: mode.catalog_group_label || mode.catalog_group || "其它",
      options: [],
    }
    existing.options.push({
      value: mode.id,
      label: `${mode.name}（${videoWorkflowRenderLabel(mode)}）`,
    })
    groups.set(groupId, existing)
  }
  return [...groups.values()]
    .sort((left, right) => left.order - right.order || left.label.localeCompare(right.label, "zh-CN"))
    .map(({ label, options }) => ({ label, options }))
}

export function formatEpisodeVideoSubmitMessage(result: Director2GenerateVideoResult): string {
  if (result.render_mode === "shot") {
    const submitted = result.submitted ?? result.job_ids?.length ?? 0
    const skipped = result.skipped ?? 0
    return `已提交 ${submitted} 镜（跳过 ${skipped} 镜已有成片）`
  }
  return "已创建 1 个整集任务"
}

export function formatSelectedShotSubmitMessage(result: Director2GenerateVideoResult): string {
  if (result.render_mode === "episode") {
    const shots = result.shot_count ?? 1
    return shots > 1 ? `已创建 1 个 Timeline 任务（${shots} 镜）` : "已创建 1 个单镜 Timeline 任务"
  }
  const submitted = result.submitted ?? result.job_ids?.length ?? 0
  const skipped = result.skipped ?? 0
  if (skipped) return `已提交选中的 ${submitted} 镜（跳过 ${skipped} 镜正在生成）`
  return `已提交选中的 ${submitted} 镜`
}

export function selectedShotGenerateExtra(beatIds: string[]): { beat_ids: string[]; force: boolean } {
  return { beat_ids: [...new Set(beatIds.filter(Boolean))], force: true }
}

export function shotVideoActionLabel(hasVideo: boolean, workflowName?: string): string {
  if (hasVideo) return "重新生成本镜"
  const name = String(workflowName || "").trim()
  return name ? `生成本镜（${name}）` : "生成本镜"
}

export function episodeFilmUrl(episode: {
  episode_video_url?: string | null
  data?: Record<string, unknown> | null
} | null | undefined): string {
  const nested = episode?.data && typeof episode.data.episode_video_url === "string"
    ? episode.data.episode_video_url
    : ""
  return String(episode?.episode_video_url || nested || "").trim()
}

export function episodeFilmSource(episode: {
  episode_video_source?: string | null
  data?: Record<string, unknown> | null
} | null | undefined): string {
  const nested = episode?.data && typeof episode.data.episode_video_source === "string"
    ? episode.data.episode_video_source
    : ""
  return String(episode?.episode_video_source || nested || "").trim()
}

export function shotVideoReadyCount(beats: Array<{ video_url?: string | null }> | null | undefined): number {
  return (beats || []).filter((beat) => Boolean(String(beat.video_url || "").trim())).length
}

export function resolutionLabelForMegapixels(
  megapixels: number,
  aspectRatio: string,
  preview?: { multiple?: number; max_width?: number; max_height?: number },
): string | undefined {
  const match = aspectRatio.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0]
  const [aspectWidth, aspectHeight] = match?.split(":").map(Number) ?? []
  if (!megapixels || !aspectWidth || !aspectHeight) return undefined
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

export function generatedResolutionLabel(
  definition: Director2OptionDefinition,
  quality: string,
  aspectRatio: string,
): string | undefined {
  const megapixels = definition.megapixels_by_quality?.[quality]
  if (!megapixels) return undefined
  return resolutionLabelForMegapixels(megapixels, aspectRatio, definition.ui_resolution_preview)
}

export function optionChoices(
  field: Director2VideoOptionField,
  values: Record<string, string>,
): Array<{ value: string; label: string }> {
  const raw = field.definition.ui_options?.length
    ? field.definition.ui_options
    : (field.definition.enum || []).map((value) => ({ value, label: String(value) }))
  return raw.map((item) => {
    const value = String(item.value)
    const pixels = field.name === "quality"
      ? generatedResolutionLabel(field.definition, value, values.aspect_ratio || "16:9")
      : undefined
    return { value, label: pixels ? `${item.label} · ${pixels}` : item.label }
  })
}

export function sanitizeVideoOptionValues(
  fields: Director2VideoOptionField[],
  incoming: Record<string, string> | null | undefined,
): Record<string, string> {
  const defaults = defaultVideoOptionValues(fields)
  if (!incoming) return defaults
  const next = { ...defaults }
  for (const field of fields) {
    const value = incoming[field.name]
    if (value == null || value === "") continue
    if (field.definition.type === "boolean" || DIRECTOR2_BOOLEAN_VIDEO_OPTIONS.has(field.name)) {
      next[field.name] = value === "true" || value === "1" ? "true" : "false"
      continue
    }
    const allowed = optionChoices(field, { ...defaults, ...incoming }).map((item) => item.value)
    if (!allowed.length || allowed.includes(value)) next[field.name] = value
  }
  return next
}

export function loadSavedVideoSettings(projectId: string): Record<string, string> | null {
  try {
    const raw = window.localStorage.getItem(`${DIRECTOR2_VIDEO_SETTINGS_STORAGE_PREFIX}${projectId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Record<string, unknown>
    if (!parsed || typeof parsed !== "object") return null
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    )
  } catch {
    return null
  }
}

export function saveVideoSettings(projectId: string, values: Record<string, string>) {
  try {
    window.localStorage.setItem(`${DIRECTOR2_VIDEO_SETTINGS_STORAGE_PREFIX}${projectId}`, JSON.stringify(values))
  } catch {
    /* ignore quota / private mode */
  }
}

export function playbackAspectRatio(values?: Record<string, string> | null): string {
  const raw = String(values?.aspect_ratio || "").trim()
  return raw || "16:9"
}

// Mirrors backend episode_video_service.PROJECT_VIDEO_RESOLUTION_QUALITIES.
export function videoResolutionQuality(resolution: unknown, refine = false): string | undefined {
  const value = String(resolution ?? "").trim().toLowerCase()
  if (value === "768p" || value === "768") return refine ? "1.0" : "0.98"
  if (value === "2k" || value === "2048") return "2.0"
  return undefined
}

// Mirrors backend workflow_registry.refine_target_megapixels: the 16 GB remote card
// stays fast only while frames × target megapixels stays around 200.
const REFINE_FRAME_MEGAPIXEL_BUDGET = 200
const REFINE_MIN_MEGAPIXELS = 0.4

export function refineFrames(durationSec: number): number {
  const frames = Math.max(5, Math.round(durationSec * 24))
  return frames + ((((5 - frames) % 17) + 17) % 17)
}

export function refineEffectiveMegapixels(
  refineQuality: string | number,
  durationSec: number,
  qualityMode = "auto",
): number {
  const requested = Number(refineQuality) || 1
  if (qualityMode === "force") return Math.floor(requested * 10 + 1e-6) / 10
  const frames = refineFrames(durationSec)
  const budgeted = REFINE_FRAME_MEGAPIXEL_BUDGET / frames
  return Math.max(REFINE_MIN_MEGAPIXELS, Math.floor(Math.min(requested, budgeted) * 10 + 1e-6) / 10)
}

export type RefinePlan = {
  requestedMegapixels: number
  effectiveMegapixels: number
  forced: boolean
  capped: boolean
  overBudget: boolean
  resolutionLabel?: string
  estimatedSeconds?: number
}

// Calibrated from real remote runs: 2 s / 1.0 MP = 174 s, 13 s / 0.6 MP = 674 s.
// The estimate is only offered inside the safe budget; beyond it the card pages.
export function refinePlan(
  refineQuality: string | number,
  qualityMode: string,
  durationSec: number,
  aspectRatio = "16:9",
): RefinePlan {
  const requested = Math.max(0.1, Number(refineQuality) || 1)
  const forced = qualityMode === "force"
  const frames = refineFrames(Math.max(0, durationSec))
  const effective = refineEffectiveMegapixels(requested, durationSec, qualityMode)
  const capped = !forced && effective < requested - 1e-6
  const overBudget = frames * effective > REFINE_FRAME_MEGAPIXEL_BUDGET + 1e-6
  return {
    requestedMegapixels: requested,
    effectiveMegapixels: effective,
    forced,
    capped,
    overBudget,
    resolutionLabel: resolutionLabelForMegapixels(effective, aspectRatio),
    estimatedSeconds: overBudget ? undefined : Math.round(frames * (1.37 + 0.75 * effective) + 52),
  }
}

export function formatRefineDuration(seconds?: number): string | undefined {
  if (!seconds || seconds <= 0) return undefined
  if (seconds < 60) return `${Math.max(10, Math.round(seconds / 10) * 10)} 秒`
  return `约 ${Math.round(seconds / 60)} 分钟`
}

export function refineForceWarning(
  values: Record<string, string>,
  durationSec: number,
): string | undefined {
  if (values.refine_enabled !== "true" || values.refine_quality_mode !== "force") return undefined
  const plan = refinePlan(
    values.refine_quality || "1.0", "force", durationSec, values.aspect_ratio || "16:9",
  )
  if (!plan.overBudget) return undefined
  return `按 ${Math.round(durationSec)} 秒片长强制 ${plan.requestedMegapixels.toFixed(1)} MP 超出平台安全预算（片长×像素约 200）。RTX 4080 16 GB 实测 13 秒 1.0 MP 全程约 37 分钟；更长片长或 2.0 MP 可能超过 1 小时，并有显存不足失败的风险。`
}

export function playbackAspectIsPortrait(aspect?: string | null): boolean {
  const match = String(aspect || "").match(/(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)/i)
  if (!match) return false
  return Number(match[2]) > Number(match[1])
}

export function videoSettingsSummary(
  fields: Director2VideoOptionField[],
  values: Record<string, string>,
  durationSec?: number,
  previewFirstPass = true,
): string {
  const aspect = values.aspect_ratio || "16:9"
  const qualityField = fields.find((item) => item.name === "quality")
  const quality = values.quality || String(qualityField?.definition.default || "0.4")
  const qualityChoice = qualityField ? optionChoices(qualityField, values).find((item) => item.value === quality) : undefined
  const weightField = fields.find((item) => item.name === "weight_profile")
  const weight = values.weight_profile || String(weightField?.definition.default || "full")
  const weightLabel = weightField?.definition.ui_options?.find((item) => String(item.value) === weight)?.label || weight
  const parts = [aspect]
  if (values.refine_enabled === "true") {
    const requested = Number(values.refine_quality || "1.0") || 1
    const mode = values.refine_quality_mode || "auto"
    const effective = durationSec && durationSec > 0
      ? refineEffectiveMegapixels(requested, durationSec, mode)
      : requested
    const capped = mode !== "force" && effective < requested - 1e-6
    let refine = `二采 ${effective.toFixed(1)} MP`
    if (capped) refine += " · 自动降档"
    else if (mode === "force") refine += " · 强制"
    parts.push(previewFirstPass ? `${refine} · 先预览` : refine)
  } else if (qualityChoice) {
    parts.push(qualityChoice.label.split(" · ")[0])
  } else if (quality) {
    parts.push(`${quality} MP`)
  }
  if (values.refine_enabled !== "true" && weightLabel) {
    parts.push(weightLabel.replace(/（.*?）/g, "").trim() || weightLabel)
  }
  return parts.join(" · ")
}

export function buildVideoJobOptions(
  workflowId: string,
  values: Record<string, string>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const options: Record<string, unknown> = { workflow: workflowId }
  for (const [name, value] of Object.entries(values)) {
    options[name] = DIRECTOR2_BOOLEAN_VIDEO_OPTIONS.has(name) ? value === "true" : value
  }
  return { ...options, ...extra }
}

export function beatHasVideo(beat: { video_url?: string | null } | null | undefined): boolean {
  return Boolean(String(beat?.video_url || "").trim())
}

export function beatHasUpscaled(beat: { video_url?: string | null; upscaled_video_url?: string | null } | null | undefined): boolean {
  return Boolean(String(beat?.upscaled_video_url || "").trim())
}

export function beatPlaybackUrl(beat: {
  video_url?: string | null
  upscaled_video_url?: string | null
} | null | undefined): string {
  return String(beat?.upscaled_video_url || beat?.video_url || "").trim()
}

export function beatUpscaleDisabledReason(
  beat: { video_url?: string | null } | null | undefined,
  progress?: { scope?: string | null; stage?: string | null; status?: string | null } | null,
): string | undefined {
  if (!beatHasVideo(beat)) return "成片成功后才能超分"
  if (progress?.scope === "upscale" || progress?.stage === "upscaling" || progress?.status === "upscaling") {
    return "正在 2x 超分"
  }
  if (progress) return "出片进行中"
  return undefined
}

export function jobUpscaledVideoUrl(job: {
  result_url?: string | null
  payload?: Record<string, unknown> | null
} | null | undefined): string {
  const payload = job?.payload || {}
  return String(payload.upscaled_video_url || "").trim()
}

export function jobSourceVideoUrl(job: {
  result_url?: string | null
  payload?: Record<string, unknown> | null
} | null | undefined): string {
  const payload = job?.payload || {}
  const source = String(payload.source_video_url || "").trim()
  if (source) return source
  if (String(payload.render_scope || "") === "upscale") return ""
  return String(job?.result_url || "").trim()
}

export function jobPreviewVideoUrl(job: {
  result_url?: string | null
  payload?: Record<string, unknown> | null
} | null | undefined): string {
  return jobUpscaledVideoUrl(job) || String(job?.result_url || "").trim()
}

const VIDEO_JOB_ACTIVE_STATUSES = new Set([
  "queued",
  "preparing",
  "prompt_generation",
  "uploading",
  "comfy_queued",
  "running",
  "assembling",
  "downloading",
  "upscaling",
])

function jobBeatIds(job: {
  payload?: Record<string, unknown> | null
} | null | undefined): string[] {
  const payload = job?.payload || {}
  const ids = new Set<string>()
  const one = String(payload.beat_id || "").trim()
  if (one) ids.add(one)
  const listed = payload.beat_ids
  if (Array.isArray(listed)) {
    for (const item of listed) {
      const id = String(item || "").trim()
      if (id) ids.add(id)
    }
  }
  return [...ids]
}

export function jobCanShowUpscaleAction(job: {
  job_type?: string
  status?: string
  payload?: Record<string, unknown> | null
} | null | undefined): boolean {
  if (job?.job_type !== "video_generation" || job.status === "awaiting_refine") return false
  return String(job.payload?.render_scope || "") !== "upscale"
}

export function jobCanConfirmRefine(job: {
  job_type?: string
  status?: string
  payload?: Record<string, unknown> | null
} | null | undefined): boolean {
  if (job?.job_type !== "video_generation" || job.status !== "awaiting_refine") return false
  return ["shot", "selection"].includes(String(job.payload?.render_scope || ""))
}

export function jobRefineShotCount(job: {
  payload?: Record<string, unknown> | null
} | null | undefined): number {
  return jobBeatIds(job).length
}

export function jobUpscaleHint(job: {
  payload?: Record<string, unknown> | null
} | null | undefined): string {
  const scope = String(job?.payload?.render_scope || "")
  if (scope === "episode" || scope === "compose") {
    return "提交整段超分：RTX 秒级出片，SeedVR2 分钟级更清晰。过长可能因显存被拒绝，原片仍保留。"
  }
  return "RTX 快速超分（秒级）或 SeedVR2 高清增强（分钟级），原片保留"
}

export function jobUpscaleDisabledReason(
  job: {
    id?: string
    job_type?: string
    status?: string
    result_url?: string | null
    payload?: Record<string, unknown> | null
  } | null | undefined,
  jobs: Array<{
    id?: string
    status?: string
    payload?: Record<string, unknown> | null
  }> = [],
): string | undefined {
  if (!jobCanShowUpscaleAction(job)) return "超分任务本身不能再超分"
  if (job?.status !== "completed" && job?.status !== "succeeded") return "成片成功后才能超分"
  if (!jobSourceVideoUrl(job) && !String(job?.result_url || "").trim()) return "该任务还没有成片"
  const scope = String(job?.payload?.render_scope || "")
  const beatIds = jobBeatIds(job)
  if (scope === "selection" && beatIds.length > 1) return "多镜任务请到剧集工坊逐镜点「超分」"
  const sourceId = String(job?.id || "")
  const inFlight = jobs.some((other) => {
    if (!VIDEO_JOB_ACTIVE_STATUSES.has(String(other.status || ""))) return false
    const payload = other.payload || {}
    if (String(payload.source_job_id || "") === sourceId) return true
    if (String(payload.render_scope || "") !== "upscale") return false
    const otherBeats = jobBeatIds(other)
    return beatIds.length === 1 && otherBeats.includes(beatIds[0])
  })
  if (inFlight) return "正在 2x 超分"
  return undefined
}
