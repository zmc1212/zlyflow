export const DIRECTOR2_DEFAULT_VIDEO_WORKFLOW = "minimax-h3-director-accel-r2v"
export const DIRECTOR2_VIDEO_SETTINGS_STORAGE_PREFIX = "director2-episode-video-settings:"
export const DIRECTOR2_EPISODE_HIDDEN_OPTIONS = new Set(["duration", "custom_steps"])
export const DIRECTOR2_BOOLEAN_VIDEO_OPTIONS = new Set<string>()

export type Director2OptionVisibility = "primary" | "advanced" | "internal"

export type Director2OptionDefinition = {
  label: string
  type: "string" | "number" | "integer" | "boolean"
  default: string | number | boolean
  enum?: Array<string | number>
  ui_group?: Director2OptionVisibility
  ui_visible_when?: Record<string, string | number | boolean>
  ui_options?: Array<{ value: string | number; label: string; hint?: string }>
  description?: string
  megapixels_by_quality?: Record<string, number>
  ui_resolution_preview?: { multiple?: number; max_width?: number; max_height?: number }
}

export type Director2WorkflowMode = {
  id: string
  name: string
  media_type?: string
  supports_timeline?: boolean
  supports_multi_segment?: boolean
  prompt_profile?: "full_reference" | "director_segments" | "none"
  prompt_template_version?: string | null
  max_segments?: number | null
  max_total_frames?: number | null
  reference_mode?: string
  min_references?: number
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
  blocked?: Array<{ part_id: string; reason: string }>
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
      default: "pruned",
      ui_group: "primary",
      ui_options: [
        { value: "pruned", label: "精简（20 GB）" },
        { value: "full", label: "完整（32 GB）" },
      ],
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
    },
  },
  {
    name: "upscale_after",
    ui_group: "advanced",
    definition: {
      label: "出片后超分",
      type: "string",
      default: "off",
      enum: ["off", "2", "4"],
      ui_group: "advanced",
      ui_options: [
        { value: "off", label: "关闭" },
        { value: "2", label: "2x（推荐）" },
        { value: "4", label: "4x" },
      ],
      description: "逐镜成片成功后卸载 H3，再用本机 RTX 一次放大到目标倍数。整集直出和拼接片不会自动超分。",
    },
  },
]

export function optionSchemaFromMode(mode: Director2WorkflowMode | undefined): Record<string, Director2OptionDefinition> {
  const options = mode?.parameters?.find((item) => item.name === "options")
  return options?.schema?.properties || {}
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
  if (result.render_scope === "episode" && result.job_ids && result.render_mode === "episode" && result.blocked) {
    return `已提交 ${result.submitted ?? result.job_ids.length} 个生成组，跳过 ${result.skipped ?? 0} 组${result.blocked?.length ? `，${result.blocked.length} 组待处理` : ""}`
  }
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

export function generatedResolutionLabel(
  definition: Director2OptionDefinition,
  quality: string,
  aspectRatio: string,
): string | undefined {
  const megapixels = definition.megapixels_by_quality?.[quality]
  const match = aspectRatio.match(/(?:\d+(?:\.\d+)?|\.\d+)\s*:\s*(?:\d+(?:\.\d+)?|\.\d+)/)?.[0]
  const [aspectWidth, aspectHeight] = match?.split(":").map(Number) ?? []
  if (!megapixels || !aspectWidth || !aspectHeight) return undefined
  const multiple = definition.ui_resolution_preview?.multiple ?? 32
  const ratio = aspectWidth / aspectHeight
  let width = Math.round(Math.sqrt(megapixels * 1024 * 1024 * ratio) / multiple) * multiple
  let height = Math.round(Math.sqrt((megapixels * 1024 * 1024) / ratio) / multiple) * multiple
  const maxWidth = ratio >= 1 ? definition.ui_resolution_preview?.max_width : definition.ui_resolution_preview?.max_height
  const maxHeight = ratio >= 1 ? definition.ui_resolution_preview?.max_height : definition.ui_resolution_preview?.max_width
  if (maxWidth && maxHeight && (width > maxWidth || height > maxHeight)) {
    const scale = Math.min(maxWidth / width, maxHeight / height)
    width = Math.max(multiple, Math.round((width * scale) / multiple) * multiple)
    height = Math.max(multiple, Math.round((height * scale) / multiple) * multiple)
  }
  return `${width} × ${height}`
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

export function videoOptionVisible(field: Director2VideoOptionField, values: Record<string, string>): boolean {
  return Object.entries(field.definition.ui_visible_when || {}).every(([name, expected]) => String(values[name]) === String(expected))
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
    const allowed = optionChoices(field, { ...defaults, ...incoming }).map((item) => item.value)
    if (field.name === "upscale_after") {
      if (value === "true" || value === "1") next[field.name] = "2"
      else if (value === "false" || value === "0") next[field.name] = "off"
      else if (!allowed.length || allowed.includes(value)) next[field.name] = value
      continue
    }
    if (field.definition.type === "boolean" || DIRECTOR2_BOOLEAN_VIDEO_OPTIONS.has(field.name)) {
      next[field.name] = value === "true" || value === "1" ? "true" : "false"
      continue
    }
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

export function playbackAspectIsPortrait(aspect?: string | null): boolean {
  const match = String(aspect || "").match(/(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)/i)
  if (!match) return false
  return Number(match[2]) > Number(match[1])
}

export function videoSettingsSummary(fields: Director2VideoOptionField[], values: Record<string, string>): string {
  const aspect = values.aspect_ratio || "16:9"
  const qualityField = fields.find((item) => item.name === "quality")
  const quality = values.quality || String(qualityField?.definition.default || "0.4")
  const qualityChoice = qualityField ? optionChoices(qualityField, values).find((item) => item.value === quality) : undefined
  const weightField = fields.find((item) => item.name === "weight_profile")
  const weight = values.weight_profile || String(weightField?.definition.default || "pruned")
  const weightLabel = weightField?.definition.ui_options?.find((item) => String(item.value) === weight)?.label || weight
  const parts = [aspect]
  if (qualityChoice) parts.push(qualityChoice.label.split(" · ")[0])
  else if (quality) parts.push(`${quality} MP`)
  if (weightLabel) parts.push(weightLabel.replace(/（.*?）/g, "").trim() || weightLabel)
  if (values.upscale_after === "4") parts.push("4x 超分")
  else if (values.upscale_after === "2" || values.upscale_after === "true") parts.push("2x 超分")
  return parts.join(" · ")
}

export function buildVideoJobOptions(
  workflowId: string,
  values: Record<string, string>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const options: Record<string, unknown> = { workflow: workflowId }
  for (const [name, value] of Object.entries(values)) {
    if (name === "upscale_after") {
      options[name] = value === "true" ? "2" : value === "false" ? "off" : value
      continue
    }
    options[name] = DIRECTOR2_BOOLEAN_VIDEO_OPTIONS.has(name) ? value === "true" : value
  }
  return { ...options, ...extra }
}

export type BeatVideoTake = {
  id: string
  job_id?: string
  url: string
  created_at?: string
  scope?: "shot" | "selection"
  upscaled_url?: string
}

export type BeatVideoTakeInput = {
  id?: string
  job_id?: string
  url?: string
  created_at?: string
  scope?: string
  upscaled_url?: string
}

export type BeatFilmSource = {
  id?: string
  video_url?: string | null
  upscaled_video_url?: string | null
  video_take_id?: string | null
  video_takes?: BeatVideoTakeInput[] | null
}

export type Director2VideoJobLike = {
  id?: string
  job_type?: string
  status?: string
  result_url?: string | null
  created_at?: string
  payload?: Record<string, unknown> | null
}

const SHOT_TAKE_SCOPES = new Set(["shot", "selection"])
const EXCLUDED_TAKE_SCOPES = new Set(["episode", "compose", "upscale"])
const SUCCESS_VIDEO_STATUSES = new Set(["completed", "succeeded"])

export function beatHasVideo(beat: { video_url?: string | null } | null | undefined): boolean {
  return Boolean(String(beat?.video_url || "").trim())
}

export function takePlaybackUrl(take: BeatVideoTake | null | undefined): string {
  return String(take?.upscaled_url || take?.url || "").trim()
}

export function beatHasFilmTakes(
  beat: BeatFilmSource | null | undefined,
  jobs: Director2VideoJobLike[] | null | undefined,
  episodeId: string,
): boolean {
  return collectBeatVideoTakes(beat, jobs, episodeId).length > 0
}

export function beatHasUpscaled(beat: {
  video_url?: string | null
  upscaled_video_url?: string | null
} | null | undefined): boolean {
  return Boolean(String(beat?.upscaled_video_url || "").trim())
}

export function beatUpscaleLabel(beat: {
  upscaled_video_url?: string | null
  upscale_scale?: number | string | null
} | null | undefined): string {
  if (!beatHasUpscaled(beat)) return ""
  if (beat?.upscale_scale === 4 || beat?.upscale_scale === "4") return "4x"
  return "2x"
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
    return "正在超分"
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
  return String(job?.result_url || "").trim()
}

export function jobUpscaleScale(job: {
  payload?: Record<string, unknown> | null
} | null | undefined): 2 | 4 | undefined {
  const payload = job?.payload || {}
  if (payload.upscale_scale === 4 || payload.upscale_scale === "4") return 4
  if (payload.upscale_scale === 2 || payload.upscale_scale === "2") return 2
  if (jobUpscaledVideoUrl(job) || String(payload.render_scope || "") === "upscale") return 2
  return undefined
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
  payload?: Record<string, unknown> | null
} | null | undefined): boolean {
  if (job?.job_type !== "video_generation") return false
  return String(job.payload?.render_scope || "") !== "upscale"
}

export function jobUpscaleHint(job: {
  payload?: Record<string, unknown> | null
} | null | undefined): string {
  const scope = String(job?.payload?.render_scope || "")
  if (scope === "episode" || scope === "compose") {
    return "点开后选 2x 或 4x。整段过长可能因显存被拒绝，原片仍保留。"
  }
  return "点开后选 2x 或 4x，用当前连接的 ComfyUI 做 RTX 超分，原片保留"
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
  if (inFlight) return "正在超分"
  return undefined
}

function jobMentionsBeat(payload: Record<string, unknown>, beatId: string): boolean {
  if (String(payload.beat_id || "").trim() === beatId) return true
  const listed = payload.beat_ids
  if (Array.isArray(listed) && listed.some((item) => String(item || "").trim() === beatId)) return true
  for (const key of ["source_shots", "shots"] as const) {
    const shots = payload[key]
    if (!Array.isArray(shots)) continue
    if (shots.some((shot) => shot && typeof shot === "object" && String((shot as { beat_id?: unknown }).beat_id || "").trim() === beatId)) {
      return true
    }
  }
  return false
}

function localTakeId(url: string, beatId = ""): string {
  let hash = 0
  const seed = `${beatId}|${url}`
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) | 0
  }
  return `take-local-${(hash >>> 0).toString(16)}`
}

function jobShotVideoUrl(job: Director2VideoJobLike, beatId: string): string {
  const payload = job.payload || {}
  const scope = String(payload.render_scope || "")
  if (EXCLUDED_TAKE_SCOPES.has(scope)) return ""
  if (!jobMentionsBeat(payload, beatId)) return ""
  const shots = Array.isArray(payload.shots) ? payload.shots : []
  const matched = shots.find((shot) => (
    shot && typeof shot === "object" && String((shot as { beat_id?: unknown }).beat_id || "").trim() === beatId
  )) as { video_url?: unknown } | undefined
  const shotUrl = String(matched?.video_url || "").trim()
  if (shotUrl) return shotUrl
  const splitUrls = Array.isArray(payload.shot_video_urls) ? payload.shot_video_urls : []
  if (splitUrls.length) {
    const sources = Array.isArray(payload.source_shots) ? payload.source_shots : shots
    const order = (sources.length ? sources : []).map((shot) => (
      shot && typeof shot === "object" ? String((shot as { beat_id?: unknown }).beat_id || "").trim() : ""
    )).filter(Boolean)
    const listed = Array.isArray(payload.beat_ids)
      ? payload.beat_ids.map((item) => String(item || "").trim()).filter(Boolean)
      : []
    const ids = order.includes(beatId) ? order : listed
    const index = ids.indexOf(beatId)
    if (index >= 0 && splitUrls[index]) return String(splitUrls[index] || "").trim()
  }
  const mentioned = [
    String(payload.beat_id || "").trim(),
    ...(Array.isArray(payload.beat_ids) ? payload.beat_ids.map((item) => String(item || "").trim()) : []),
    ...shots.map((shot) => (
      shot && typeof shot === "object" ? String((shot as { beat_id?: unknown }).beat_id || "").trim() : ""
    )),
  ].filter(Boolean)
  const unique = new Set(mentioned)
  if (unique.size <= 1) return jobSourceVideoUrl(job)
  return ""
}

function earlierStamp(left?: string, right?: string): string {
  const a = String(left || "").trim()
  const b = String(right || "").trim()
  if (a && b) return a < b ? a : b
  return a || b
}

export function collectBeatVideoTakes(
  beat: BeatFilmSource | null | undefined,
  jobs: Director2VideoJobLike[] | null | undefined,
  episodeId: string,
): BeatVideoTake[] {
  const beatId = String(beat?.id || "").trim()
  const episode = String(episodeId || "").trim()
  const merged = new Map<string, BeatVideoTake>()

  const upsert = (incoming: BeatVideoTake) => {
    const url = String(incoming.url || "").trim()
    if (!url) return
    const current = merged.get(url)
    if (!current) {
      merged.set(url, { ...incoming, url })
      return
    }
    merged.set(url, {
      ...current,
      id: current.id || incoming.id,
      job_id: current.job_id || incoming.job_id,
      created_at: earlierStamp(current.created_at, incoming.created_at),
      scope: current.scope || incoming.scope,
      upscaled_url: incoming.upscaled_url || current.upscaled_url,
    })
  }

  for (const item of beat?.video_takes || []) {
    const url = String(item?.url || "").trim()
    const scope = String(item?.scope || "shot")
    if (!url || (scope && !SHOT_TAKE_SCOPES.has(scope))) continue
    upsert({
      id: String(item.id || "").trim() || localTakeId(url, beatId),
      job_id: String(item.job_id || "").trim() || undefined,
      url,
      created_at: String(item.created_at || "").trim() || undefined,
      scope: scope === "selection" ? "selection" : "shot",
      upscaled_url: String(item.upscaled_url || "").trim() || undefined,
    })
  }

  const adopted = String(beat?.video_url || "").trim()
  const adoptedUpscaled = String(beat?.upscaled_video_url || "").trim()
  if (adopted) {
    upsert({
      id: String(beat?.video_take_id || "").trim() || localTakeId(adopted, beatId),
      url: adopted,
      scope: "shot",
      upscaled_url: adoptedUpscaled || undefined,
    })
  }

  for (const job of jobs || []) {
    if (job.job_type && job.job_type !== "video_generation") continue
    const payload = job.payload || {}
    if (String(payload.episode_id || "") !== episode) continue
    const scope = String(payload.render_scope || "")
    if (scope === "upscale") {
      const source = String(payload.source_video_url || "").trim()
      const upscaled = String(payload.upscaled_video_url || job.result_url || "").trim()
      const current = source ? merged.get(source) : undefined
      if (current && upscaled) current.upscaled_url = upscaled
      continue
    }
    if (!SUCCESS_VIDEO_STATUSES.has(String(job.status || ""))) continue
    if (!beatId || !jobMentionsBeat(payload, beatId)) continue
    const url = jobShotVideoUrl(job, beatId)
    if (!url) continue
    upsert({
      id: job.id ? `take-${job.id}-${beatId}` : localTakeId(url, beatId),
      job_id: job.id,
      url,
      created_at: String(job.created_at || "").trim() || undefined,
      scope: scope === "selection" ? "selection" : "shot",
    })
  }

  if (adopted && adoptedUpscaled) {
    const current = merged.get(adopted)
    if (current && !current.upscaled_url) current.upscaled_url = adoptedUpscaled
  }

  return [...merged.values()].sort((left, right) => {
    const leftAt = left.created_at || ""
    const rightAt = right.created_at || ""
    if (leftAt !== rightAt) {
      if (!leftAt) return -1
      if (!rightAt) return 1
      return leftAt.localeCompare(rightAt)
    }
    return left.url.localeCompare(right.url)
  })
}
