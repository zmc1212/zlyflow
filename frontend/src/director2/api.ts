// AI Media Studio API 封装 —— 逐函数复刻自 dev0914 z-admin/src/api/projects.js
// 区别仅在于：axios → 工作台统一 requestJson/jsonMutation（携带会话与 CSRF）。
import { ApiRequestError, jsonMutation, requestJson } from "../api"

export type Director2Project = {
  id: string
  name: string
  description: string | null
  cover_url: string | null
  status: string
  settings: Record<string, unknown> | null
  extra: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type Director2Document = {
  id: string
  project_id: string
  filename: string
  file_size: number
  input_mode: string
  status: string
  spine_template: string
  visual_style: string
  raw_text: string | null
  analysis: Record<string, unknown> | null
  shot_plan_job_id?: string | null
  aspect_hint?: {
    suggested?: string
    hits?: string[]
    conflicts?: string[]
    explicit?: string[]
    source?: string
  } | null
  needs_shot_plan?: boolean
  project_name?: string | null
  created_at: string
  updated_at: string
}

export type Director2Asset = {
  id: string
  project_id: string
  kind: string
  name: string
  role: string | null
  description: string | null
  visual_prompt: string | null
  image_url: string | null
  voice_id: string | null
  extra: Record<string, any>
  created_at: string
  updated_at: string
}

export type Director2Episode = {
  id: string
  project_id: string
  episode_num: number
  title: string
  status: string
  script_text: string | null
  data_json?: string | null
  shots_count: number
  created_at: string
  updated_at: string
}

export type Director2Job = {
  id: string
  project_id: string
  job_type: string
  title: string
  status: string
  progress: number
  result_url: string | null
  error_message: string | null
  payload: Record<string, any>
  payload_json?: string | null
  completed_at?: string | null
  created_at: string
  updated_at: string
}

export type Director2CreationMode = "agent" | "manual"
export type Director2AiStage = "clarify" | "script" | "assets" | "episodes" | "storyboard"
export type Director2AiStatus = "idle" | "clarifying" | "queued" | "running" | "awaiting_review" | "revising" | "succeeded" | "failed" | "cancelled"
export type Director2ClarificationQuestion = {
  id?: string
  question: string
  why?: string
  options?: Array<{ label: string; value: string; recommended?: boolean }>
  allowCustom?: boolean
}
export type Director2StageClarification = {
  id?: string
  question?: string
  answer?: string
  value?: string
  label?: string
  agent?: string
  [key: string]: unknown
}
export type Director2AiOperation = {
  script_development_document_id?: string | null
  script_development_version?: number | null
  id: string
  project_id: string
  kind: "clarify" | "pipeline"
  status: Director2AiStatus
  progress: number
  current_stage: Director2AiStage | null
  /** 当前暂停等待确认的阶段；仅 `awaiting_review` / `revising` 时有值。 */
  awaiting_stage?: Director2AiStage | null
  request: Record<string, unknown>
  /** 各阶段「不满意」后再答的选项；旧任务可能缺失或为空对象。 */
  stage_clarifications?: Partial<Record<string, Director2StageClarification[]>>
  result: {
    questions?: Director2ClarificationQuestion[]
    completed_stages?: Director2AiStage[]
    failed_stage?: Director2AiStage
    message?: string
    /** 终态任务保留的 Recipe 快照，用于刷新后查看并继续编辑已生成内容。 */
    recipe?: Record<string, any>
  }
  error?: string | null
  cancel_requested: boolean
  created_at: string
  updated_at: string
}

function detailOf(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    const detail = (error.body as any)?.detail
    if (typeof detail === "string" && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as any
      if (first?.msg) return String(first.msg)
    }
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

export { detailOf as director2ErrorDetail }

export function listProjects(): Promise<Director2Project[]> {
  return requestJson<Director2Project[]>("/api/projects")
}

export type Director2SkillPack = {
  id: string
  name: string
  summary?: string
  author?: string
  cover?: string
  surfaces: string[]
  visual_lock: string
  workshop_shot: string[]
  packing_overrides: Record<string, boolean>
  confirm_format: Record<string, unknown>
}

export function listSkillPacks(): Promise<{ packs: Director2SkillPack[] }> {
  return requestJson<{ packs: Director2SkillPack[] }>("/api/skill-packs")
}

export function createProject(csrfToken: string, data: { name: string; description?: string; cover_url?: string | null; settings?: Record<string, unknown> | null; extra?: Record<string, unknown> | null }): Promise<Director2Project> {
  return requestJson<Director2Project>("/api/projects", jsonMutation(csrfToken, data, "POST"))
}

export function getProject(id: string): Promise<Director2Project> {
  return requestJson<Director2Project>(`/api/projects/${encodeURIComponent(id)}`)
}

export function updateProject(csrfToken: string, id: string, data: Record<string, unknown>): Promise<Director2Project> {
  return requestJson<Director2Project>(`/api/projects/${encodeURIComponent(id)}`, jsonMutation(csrfToken, data, "PUT"))
}

export function deleteProject(csrfToken: string, id: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/api/projects/${encodeURIComponent(id)}`, jsonMutation(csrfToken, undefined, "DELETE"))
}

// --- 内容库 Documents ---
export function listDocuments(projectId: string): Promise<Director2Document[]> {
  return requestJson<Director2Document[]>(`/api/projects/${encodeURIComponent(projectId)}/documents`)
}

export function createDocument(csrfToken: string, projectId: string, data: { filename: string; raw_text: string; spine_template?: string; visual_style?: string; input_mode?: string }): Promise<Director2Document> {
  return requestJson<Director2Document>(
    `/api/projects/${encodeURIComponent(projectId)}/documents`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function enqueueDocumentShotPlan(
  csrfToken: string,
  projectId: string,
  docId: string,
  aspectRatio?: string,
  force = false,
  episodeNum?: number,
): Promise<{ job_id: string; document_id?: string; status?: string; duplicate?: boolean }> {
  const body: Record<string, unknown> = {}
  if (aspectRatio) body.aspect_ratio = aspectRatio
  if (force) body.force = true
  if (episodeNum != null) body.episode_num = episodeNum
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/shot-plan`,
    jsonMutation(csrfToken, Object.keys(body).length ? body : undefined),
  )
}

export function deleteDocument(csrfToken: string, projectId: string, docId: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export function transferAssetsFromDoc(csrfToken: string, projectId: string, docId: string): Promise<Record<string, any>> {
  return requestJson<Record<string, any>>(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/transfer-assets`,
    jsonMutation(csrfToken),
  )
}

export function transferEpisodesFromDoc(
  csrfToken: string,
  projectId: string,
  docId: string,
  mode: "overwrite" | "append" = "overwrite",
): Promise<Record<string, any>> {
  return requestJson<Record<string, any>>(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/transfer-episodes`,
    jsonMutation(csrfToken, { mode }),
  )
}

// --- 资产库 Assets ---
export function listAssets(projectId: string, kind?: string | null): Promise<Director2Asset[]> {
  const url = kind
    ? `/api/projects/${encodeURIComponent(projectId)}/assets?kind=${encodeURIComponent(kind)}`
    : `/api/projects/${encodeURIComponent(projectId)}/assets`
  return requestJson<Director2Asset[]>(url)
}

export function createAsset(csrfToken: string, projectId: string, data: Record<string, unknown>): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateCharacterContent(csrfToken: string, projectId: string, data: { requirement: string; name?: string; role?: string }): Promise<{ description: string; visual_prompt: string; model: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/assets/generate-character-content`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function updateAsset(csrfToken: string, projectId: string, assetId: string, data: Record<string, unknown>): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, data, "PUT"),
  )
}

export function deleteAsset(csrfToken: string, projectId: string, assetId: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export function generateAssetImage(csrfToken: string, projectId: string, assetId: string, data: Record<string, unknown> = {}): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/generate`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function uploadAssetSourceReference(
  csrfToken: string,
  projectId: string,
  assetId: string,
  file: File,
): Promise<Director2Asset> {
  const form = new FormData()
  form.set("file", file)
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/references`,
    { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } },
  )
}

export function deleteAssetSourceReference(
  csrfToken: string,
  projectId: string,
  assetId: string,
  refId: string,
): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/references/${encodeURIComponent(refId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export function inferAssetPromptsFromReferences(
  csrfToken: string,
  projectId: string,
  assetId: string,
): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/infer-prompts`,
    jsonMutation(csrfToken, undefined, "POST"),
  )
}

export function uploadAssetVoice(
  csrfToken: string,
  projectId: string,
  assetId: string,
  file: File,
): Promise<Director2Asset> {
  const form = new FormData()
  form.set("file", file)
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice`,
    { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } },
  )
}

export function applyAssetVoicePreset(
  csrfToken: string,
  projectId: string,
  assetId: string,
  presetId: string,
): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice/preset`,
    jsonMutation(csrfToken, { preset_id: presetId }, "POST"),
  )
}

export type VoiceBankPreset = {
  id: string
  file: string
  label: string
  gender: string
  role: string
  group: string
  group_order: number
  default_emotion: string
  description: string
  audio_url: string
}

export function listVoiceBank(): Promise<{ voices: VoiceBankPreset[] }> {
  return requestJson<{ voices: VoiceBankPreset[] }>("/api/voice-bank")
}

export function deleteAssetVoice(
  csrfToken: string,
  projectId: string,
  assetId: string,
): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export function previewAssetVoice(
  csrfToken: string,
  projectId: string,
  assetId: string,
  data: Record<string, unknown> = {},
): Promise<{ asset: Director2Asset; preview_url: string; duration_sec: number }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice/preview`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export type VoiceExtractSource = {
  episode_id: string
  episode_num: number
  title: string
  beat_id: string
  seq: string
  line_preview: string
  duration_sec: number
  video_url: string
}

export function listVoiceExtractSources(
  projectId: string,
  assetId: string,
): Promise<{ sources: VoiceExtractSource[] }> {
  return requestJson<{ sources: VoiceExtractSource[] }>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice/extract-sources`,
  )
}

export function extractAssetVoiceFromShot(
  csrfToken: string,
  projectId: string,
  assetId: string,
  data: { episode_id: string; beat_id: string; start_sec: number; end_sec: number },
): Promise<Director2Asset> {
  return requestJson<Director2Asset>(
    `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/voice/extract`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

// --- 剧集工坊 Episodes ---
export function listEpisodes(projectId: string): Promise<Director2Episode[]> {
  return requestJson<Director2Episode[]>(`/api/projects/${encodeURIComponent(projectId)}/episodes`)
}

export function createEpisode(csrfToken: string, projectId: string, data: Record<string, unknown>): Promise<Director2Episode> {
  return requestJson<Director2Episode>(
    `/api/projects/${encodeURIComponent(projectId)}/episodes`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function updateEpisode(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<Director2Episode> {
  return requestJson<Director2Episode>(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`,
    jsonMutation(csrfToken, data, "PUT"),
  )
}

export function deleteEpisode(csrfToken: string, projectId: string, epId: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export type Director2EpisodeDetail = {
  production?: import("./production").ProductionState
  id: string
  project_id: string
  number: number
  title: string
  status: string
  script_text: string
  content_summary: string
  shots_count: number
  beat_count: number
  character_count: number
  scene_count: number
  prop_count: number
  line_count: number
  original_lines: string[]
  beats: Director2Beat[]
  links: Array<{ id: string; asset_id: string; kind: string; name: string; image_url: string }>
  data: Record<string, any>
  episode_video_url?: string | null
  episode_video_source?: string | null
  episode_video_job_id?: string | null
  prompt_authoring?: PromptAuthoringState
}

export type ActionPrevisPlan = {
  version: 1
  fps: number
  frame_count: number
  actors: Array<{ id: "A" | "B"; label: string; start: number[]; facing_deg: number }>
  beats: Array<{ id: string; start: number; end: number; description: string; actions: Array<{ actor: "A" | "B"; type: string }>;
    contact: null | { frame: number; actor: "A" | "B"; target_actor: "A" | "B"; bone: string; target_bone: string } }>
  shots: Array<{ id: string; start: number; end: number; size: string; angle: string; move: string; subject: string; lens_mm: number }>
}

export function createActionPrevis(csrfToken: string, projectId: string, episodeId: string, beatId: string,
  description: string, images: File[], video?: File | null): Promise<{ job_id: string; status: string }> {
  const form = new FormData()
  form.set("description", description)
  images.forEach(file => form.append("images", file))
  if (video) form.set("video", video)
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/action-previs`,
    { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
}

export function latestActionPrevis(projectId: string, episodeId: string, beatId: string): Promise<Director2Job | null> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/action-previs/latest`)
}

export function getActionPrevis(projectId: string, jobId: string): Promise<Director2Job> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/action-previs/${encodeURIComponent(jobId)}`)
}

export function reviseActionPrevis(csrfToken: string, projectId: string, jobId: string, plan: ActionPrevisPlan, expectedRevision: number): Promise<Director2Job> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/action-previs/${encodeURIComponent(jobId)}/plan`,
    jsonMutation(csrfToken, { plan, expected_revision: expectedRevision }, "PUT"))
}

export function actionPrevisCommand(csrfToken: string, projectId: string, jobId: string, command: "render" | "cancel" | "retry", expectedRevision?: number): Promise<Director2Job> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/action-previs/${encodeURIComponent(jobId)}/${command}`,
    jsonMutation(csrfToken, command === "render" ? { expected_revision: expectedRevision } : {}, "POST"))
}

export type PromptReferenceSlot = {
  index: number
  token: string
  asset_id: string
  look_id?: string | null
  image_url: string
  kind: string
  name: string
}

export type PromptSections = {
  subject_definitions?: string
  summary: string
  retention_analysis: string
  detailed_description: string
  overall_soundscape: string
  non_diegetic_music: string
}

export type FullReferencePromptRecord = {
  kind: "full_reference"
  template_version: string
  workflow_id?: string
  language: "zh-CN" | "en"
  source_fingerprint: string
  reference_slots: PromptReferenceSlot[]
  beat_id: string
  sections: PromptSections
  prompt_text: string
  status: "current" | "stale"
  rewrite_mode?: "strict" | "expand"
  aspect_ratio?: string
}

export type DirectorPromptSegment = {
  id: string
  index: number
  title: string
  frame_count: number
  duration_seconds: number
  source_beat_ids: string[]
  source_units?: Array<{
    id: string
    source_beat_id: string
    source_shot_number: number
    generated_shot_number: number
    chunk_index: number
    chunk_count: number
    start_sec: number
    end_sec: number
    duration_seconds: number
    event_ids?: string[]
    dialogue_ids?: string[]
    event_refs?: Array<{ id: string; text: string }>
    dialogue_refs?: Array<{ id: string; text: string }>
    required_events: string[]
    dialogue_owner: string[]
    start_state: string
    handoff_state: string
  }>
  shots: Array<{ shot_number: number; source_beat_id?: string | null }>
  sections: PromptSections
  prompt_text: string
  /** Final H3 body. v6 plans keep this separate from Director metadata. */
  h3_prompt?: string
  manual_h3_prompt?: boolean
  continuity_from_prev: boolean
  video_url?: string
}

export type DirectorPromptPart = {
  source_group_id?: string
  source_beat_ids?: string[]
  reference_slots?: PromptReferenceSlot[]
  render_mode?: "director" | "shot"
  workflow_id?: string | null
  render_blocker?: string | null
  execution_options?: Record<string, unknown>
  id: string
  index: number
  frame_count: number
  handoff_from_previous_part?: string | {
    segment_id: string
    state: string
    description_tail: string
  }
  segments: DirectorPromptSegment[]
  renders?: Array<{ job_id: string; segment_ids: string[]; url: string; created_at: string }>
}

export type DirectorPromptPlan = {
  max_shots_per_group?: number
  group_setting_source?: "episode" | "project" | "system"
  source_groups?: Array<{ id: string; scene_key: string; beat_ids: string[]; frame_count: number }>
  director_design?: { dramatic_intent?: string; visual_strategy?: string; quality_notes?: string[] }
  creative_review?: { issues: Array<{ id?: string; segment_id: string; evidence: string; suggestion: string; severity?: "blocking" | "advisory"; repair_scope?: "creative" | "planning" }> }
  quality_version?: number
  revision_stop_reason?: string
  revision_requirements?: Array<{ feedback: string; segment_ids: string[] }>
  revision_parent?: { id: string; revision: number }
  revision_history?: Array<{ round: number; status: string; detail?: string; resolved?: string[]; remaining?: string[]; new?: string[]; changes?: Array<{ segment_id: string; before: string; after: string }> }>
  quality_status?: string
  actual_segment_count?: number
  kind: "director_segments"
  id: string
  revision: number
  schema_version?: number
  planning_strategy?: "atomic_units" | string
  unit_planner_version?: string
  template_version: string
  workflow_id: string
  language: "zh-CN" | "en"
  rewrite_mode?: "strict" | "expand"
  aspect_ratio?: string
  target_segment_count?: number
  source_fingerprint: string
  source_facts?: Record<string, {
    events: Array<{ id: string; text: string }>
    dialogues: Array<{ id: string; text: string }>
  }>
  reference_slots: PromptReferenceSlot[]
  common_setting: { subject_definitions: string; prompt_text: string }
  /** v6 normalized group contract. v4/v5 callers continue to use parts. */
  common_prompt?: string
  groups?: Array<{
    id: string
    source_beat_ids?: string[]
    common_prompt?: string
    reference_slots?: PromptReferenceSlot[]
    shots: Array<{
      id?: string
      beat_id: string
      h3_prompt: string
      duration_seconds: number
      continuity_from_prev?: boolean
      video_takes?: Array<{ job_id?: string; url?: string; created_at?: string }>
    }>
  }>
  parts: DirectorPromptPart[]
  status: "current" | "stale"
  validation_status?: "pending" | "valid" | "invalid"
  invalid_reason?: string
}

export type PromptPreview = FullReferencePromptRecord | DirectorPromptPlan

export type PromptAuthoringState = {
  schema_version?: number
  full_reference?: Record<string, FullReferencePromptRecord>
  director_plan?: DirectorPromptPlan
}

export type Director2Beat = {
  workshop_writing_refs?: string[]
  id: string
  sequence: number
  kind?: string
  heading?: string
  speaker?: string
  dialogue?: string
  action?: string
  camera?: string
  characters?: string[]
  character_ids?: string[]
  character_look_id?: string | null
  character_look_ids?: Record<string, string>
  scene?: string
  scene_id?: string | null
  props?: string[]
  prop_ids?: string[]
  visual_prompt?: string
  sketch_prompt?: string
  sketch_url?: string | null
  sketch_job_id?: string | null
  render_url?: string | null
  render_prompt?: string
  render_job_id?: string | null
  render_status?: string
  video_url?: string | null
  upscaled_video_url?: string | null
  upscale_scale?: number | null
  video_take_id?: string | null
  video_takes?: Array<{
    id?: string
    job_id?: string
    url?: string
    created_at?: string
    scope?: string
    upscaled_url?: string
  }>
  video_prompt_zh?: string
  video_duration?: string
  status?: string
  h3_prompt?: string | null
  h3_prompt_source?: "manual" | "generated" | string | null
  h3_reference_policy?: string | null
  h3_prompt_context_fingerprint?: string | null
  h3_prompt_reference_state?: "current" | "stale" | "manual" | "invalid" | "missing" | string | null
  h3_prompt_reference_reason?: string | null
  parent_beat_id?: string | null
  take_role?: string | null
  story_shot?: number | null
  merge_as_one?: boolean | null
  take_source?: Record<string, unknown> | null
  dialogue_turns?: Array<{ speaker?: string; text?: string; character_id?: string }>
  visible_text?: string | null
  triptych_url?: string | null
  triptych_panels?: { start?: string; mid?: string; end?: string } | null
  triptych_job_id?: string | null
  triptych_status?: string | null
  triptych_look_ids?: Record<string, string> | null
  timestamped_zh_prompt?: string | null
  vision_status?: string | null
  vision_model?: string | null
  vision_image_count?: number | null
  vision_source?: string | null
}

export function getEpisodeDetail(projectId: string, epId: string): Promise<Director2EpisodeDetail> {
  return requestJson<Director2EpisodeDetail>(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`,
  )
}

export function restoreScriptShots(csrfToken: string, projectId: string, ep: Director2EpisodeDetail): Promise<Director2EpisodeDetail> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(ep.id)}/restore-script-shots`,
    jsonMutation(csrfToken, { script_text: ep.script_text, beat_ids: ep.beats.map(b => b.id) }, "POST"))
}

export function updateEpisodeBeat(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown>): Promise<{ status: string; beat: Director2Beat }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}`,
    jsonMutation(csrfToken, data, "PUT"),
  )
}

export function generateBeatSketch(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown> = {}): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-sketch`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateBeatRender(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown> = {}): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-render`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateBeatTriptych(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown> = {}): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-triptych`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateBeatImagesBatch(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-images`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function createPromptPreview(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<{ job_id: string; status: string; duplicate?: boolean; source_fingerprint?: string; recommended_segment_count?: number }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/prompt-previews`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function applyPromptPreview(csrfToken: string, projectId: string, epId: string, jobId: string, data: Record<string, unknown>): Promise<{ status: string; prompt_authoring: PromptAuthoringState }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/prompt-previews/${encodeURIComponent(jobId)}/apply`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function reviseDirectorPromptPlan(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<{ job_id: string; status: string }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/prompt-revisions`, jsonMutation(csrfToken, data, "POST"))
}

export function patchDirectorPromptPlan(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<DirectorPromptPlan> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/prompt-plan`,
    jsonMutation(csrfToken, data, "PATCH"),
  )
}

export function generateEpisodeVideo(
  csrfToken: string,
  projectId: string,
  epId: string,
  data: Record<string, unknown> = {},
): Promise<import("./director2-video-settings").Director2GenerateVideoResult> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-video`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateBeatVideo(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown> = {}): Promise<{ job_id: string; status: string; render_scope?: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/generate-video`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function upscaleBeatVideo(csrfToken: string, projectId: string, epId: string, beatId: string, data: Record<string, unknown> = {}): Promise<{ job_id: string; status: string; render_scope?: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/upscale`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function adoptBeatVideoTake(
  csrfToken: string,
  projectId: string,
  epId: string,
  beatId: string,
  data: { url?: string; job_id?: string },
): Promise<{ status: string; beat: Director2Beat }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/beats/${encodeURIComponent(beatId)}/video-takes/adopt`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function composeEpisodeVideo(
  csrfToken: string,
  projectId: string,
  epId: string,
  data: Record<string, unknown> = {},
): Promise<{ job_id: string; status: string; render_scope?: string; render_mode?: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/compose`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function getEpisodeProduction(projectId: string, episodeId: string, mode: import("./production").ProductionMode): Promise<import("./production").ProductionState> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(episodeId)}/production?mode=${mode}`)
}

export function updateEpisodeProduction(csrfToken: string, projectId: string, episodeId: string, action: "mode" | "adopt" | "audio", data: Record<string, unknown>): Promise<import("./production").ProductionState> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(episodeId)}/production/${action}`, jsonMutation(csrfToken, data, "PATCH"))
}

export function getEpisodeDubbing(projectId: string, epId: string): Promise<import("./dubbing-track").DubbingTrack> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/dubbing`)
}

export function syncEpisodeDubbing(
  csrfToken: string,
  projectId: string,
  epId: string,
): Promise<import("./dubbing-track").DubbingTrack> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/dubbing/sync`,
    jsonMutation(csrfToken, undefined, "POST"),
  )
}

export function patchDubbingLine(
  csrfToken: string,
  projectId: string,
  epId: string,
  lineId: string,
  data: Record<string, unknown>,
): Promise<import("./dubbing-track").DubbingTrack> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/dubbing/lines/${encodeURIComponent(lineId)}`,
    jsonMutation(csrfToken, data, "PATCH"),
  )
}

export function generateEpisodeDubbing(
  csrfToken: string,
  projectId: string,
  epId: string,
  data: { line_id?: string; line_ids?: string[] } = {},
): Promise<import("./dubbing-track").DubbingGenerateResult> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/dubbing/generate`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

// --- 全部任务 Jobs ---
export function listJobs(projectId: string): Promise<Director2Job[]> {
  return requestJson<Director2Job[]>(`/api/projects/${encodeURIComponent(projectId)}/jobs`)
}

export function getJob(projectId: string, jobId: string): Promise<Director2Job> {
  return requestJson<Director2Job>(
    `/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}`,
  )
}

export function createJob(csrfToken: string, projectId: string, data: Record<string, unknown>): Promise<Director2Job> {
  return requestJson<Director2Job>(
    `/api/projects/${encodeURIComponent(projectId)}/jobs`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function retryJob(csrfToken: string, projectId: string, jobId: string): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/retry`,
    jsonMutation(csrfToken),
  )
}

export function upscaleProjectVideoJob(
  csrfToken: string,
  projectId: string,
  jobId: string,
  data: Record<string, unknown> = {},
): Promise<{ job_id: string; status: string; render_scope?: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/upscale`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function createAiOperation(csrfToken: string, projectId: string, data: Record<string, unknown>): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function getAiOperation(projectId: string, operationId: string): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}`,
  )
}

export function getActiveAiOperation(projectId: string): Promise<Director2AiOperation | null> {
  return requestJson<Director2AiOperation | null>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/active`,
  )
}

export function cancelAiOperation(csrfToken: string, projectId: string, operationId: string): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/cancel`,
    jsonMutation(csrfToken, undefined, "POST"),
  )
}

export function retryAiOperation(
  csrfToken: string,
  projectId: string,
  operationId: string,
  stage?: Director2AiStage,
): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/retry`,
    jsonMutation(csrfToken, stage ? { stage } : {}, "POST"),
  )
}

export function advanceAiOperation(csrfToken: string, projectId: string, operationId: string): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/advance`,
    jsonMutation(csrfToken, undefined, "POST"),
  )
}

export function reviseAiOperation(csrfToken: string, projectId: string, operationId: string, feedback: string): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/revise`,
    jsonMutation(csrfToken, { feedback }, "POST"),
  )
}

export function rerunAiStage(
  csrfToken: string,
  projectId: string,
  operationId: string,
  clarifications: Array<{ id?: string; question: string; answer: string; label?: string }>,
): Promise<Director2AiOperation> {
  return requestJson<Director2AiOperation>(
    `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/rerun`,
    jsonMutation(csrfToken, { clarifications }, "POST"),
  )
}

export function aiOperationEventsUrl(projectId: string, operationId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/ai/operations/${encodeURIComponent(operationId)}/events`
}

export function listVideoWorkflowModes(): Promise<{ modes: import("./director2-video-settings").Director2WorkflowMode[] }> {
  return requestJson("/api/modes")
}
