export const DIRECTOR2_DEFAULT_VIDEO_WORKFLOW = "minimax-h3-director-accel-r2v"
export const DIRECTOR2_VIDEO_SETTINGS_STORAGE_PREFIX = "director2-episode-video-settings:"
export const DIRECTOR2_EPISODE_HIDDEN_OPTIONS = new Set(["duration", "custom_steps"])

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
  return parts.join(" · ")
}

export function buildVideoJobOptions(
  workflowId: string,
  values: Record<string, string>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    workflow: workflowId,
    ...values,
    ...extra,
  }
}
