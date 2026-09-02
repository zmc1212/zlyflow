import { jsonMutation, requestJson } from "../api"

export type XiajiDocumentStatus = "uploaded" | "parsing" | "indexed" | "review_required" | "ready" | "failed"

export type XiajiChapter = {
  id: string
  document_id: string
  sequence: number
  title: string
  content: string
  char_count: number
}

export type XiajiDocumentSummary = {
  id: string
  title: string
  filename: string
  source_format: string
  status: XiajiDocumentStatus
  char_count: number
  billed_char_count: number
  chapter_count: number
  estimated_episodes: number
  error: string | null
  created_at: string
  updated_at: string
}

export type XiajiAnalysisCharacter = {
  name: string
  aliases: string[]
  role: string
  is_main: boolean
  gender: string
  age_group: string
  body_type: string
  description: string
  face_prompt: string
}

export type XiajiAnalysisScene = {
  name: string
  scene_type: string
  description: string
}

export type XiajiAnalysisProp = {
  name: string
  aliases: string[]
  prop_type: string
  visual_prompt: string
  owner: string
}

export type XiajiAnalysisEpisode = {
  number: number
  title: string
  content_summary: string
  main_conflict: string
  cliffhanger: string
  key_events: string[]
}

export type XiajiAnalysis = {
  summary: string
  characters: XiajiAnalysisCharacter[]
  scenes: XiajiAnalysisScene[]
  props: XiajiAnalysisProp[]
  episodes: XiajiAnalysisEpisode[]
  model?: string
  logs?: string[]
}

export type XiajiIngestSettings = {
  spine_template?: string
  visual_style?: string
  narration_style?: string
  ethnicity?: string
}

export type XiajiDocumentDetail = XiajiDocumentSummary & {
  original_text: string
  chapters: XiajiChapter[]
  analysis?: XiajiAnalysis | null
  project_id?: string
}

export type XiajiProject = {
  id: string
  name: string
  settings: XiajiIngestSettings
  created_at: string
  updated_at: string
}

function withProjectQuery(path: string, projectId: string, extra?: Record<string, string>) {
  const params = new URLSearchParams({ project_id: projectId, ...extra })
  return `${path}?${params.toString()}`
}

export function listXiajiProjects() {
  return requestJson<XiajiProject[]>("/api/xiaji/projects")
}

export function getXiajiProject(projectId: string) {
  return requestJson<XiajiProject>(`/api/xiaji/projects/${encodeURIComponent(projectId)}`)
}

export function createXiajiProject(csrfToken: string, name: string) {
  return requestJson<XiajiProject>("/api/xiaji/projects", jsonMutation(csrfToken, { name }))
}

export function updateXiajiProject(
  csrfToken: string,
  projectId: string,
  payload: { name?: string; settings?: XiajiIngestSettings },
) {
  return requestJson<XiajiProject>(
    `/api/xiaji/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, payload, "PATCH"),
  )
}

export function deleteXiajiProject(csrfToken: string, projectId: string) {
  return requestJson<{ ok: boolean }>(
    `/api/xiaji/projects/${encodeURIComponent(projectId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export function listXiajiDocuments(projectId: string) {
  return requestJson<XiajiDocumentSummary[]>(withProjectQuery("/api/xiaji/documents", projectId))
}

export function getXiajiDocument(documentId: string) {
  return requestJson<XiajiDocumentDetail>(`/api/xiaji/documents/${encodeURIComponent(documentId)}`)
}

export async function uploadXiajiDocument(
  csrfToken: string,
  projectId: string,
  file: File,
  title?: string,
  settings?: XiajiIngestSettings,
) {
  const body = new FormData()
  body.append("file", file)
  if (title?.trim()) body.append("title", title.trim())
  if (settings?.spine_template) body.append("spine_template", settings.spine_template)
  if (settings?.visual_style) body.append("visual_style", settings.visual_style)
  if (settings?.narration_style) body.append("narration_style", settings.narration_style)
  if (settings?.ethnicity) body.append("ethnicity", settings.ethnicity)
  return requestJson<XiajiDocumentDetail>(withProjectQuery("/api/xiaji/documents", projectId), {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body,
  })
}

export function pasteXiajiDocument(
  csrfToken: string,
  projectId: string,
  text: string,
  title?: string,
  settings?: XiajiIngestSettings,
) {
  return requestJson<XiajiDocumentDetail>(
    withProjectQuery("/api/xiaji/documents/paste", projectId),
    jsonMutation(csrfToken, {
      text,
      title: title?.trim() || "",
      spine_template: settings?.spine_template || "drama",
      visual_style: settings?.visual_style || "",
      narration_style: settings?.narration_style || "",
      ethnicity: settings?.ethnicity || "",
    }),
  )
}

export function saveXiajiChapters(
  csrfToken: string,
  documentId: string,
  chapters: Array<{ id?: string; title: string; content: string }>,
) {
  return requestJson<XiajiDocumentDetail>(
    `/api/xiaji/documents/${encodeURIComponent(documentId)}/chapters`,
    jsonMutation(csrfToken, { chapters }, "PUT"),
  )
}

export function deleteXiajiDocument(csrfToken: string, documentId: string) {
  return requestJson<{ ok: boolean }>(
    `/api/xiaji/documents/${encodeURIComponent(documentId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export type XiajiAssetKind = "character" | "scene" | "prop" | "voice"
export type XiajiAssetStatus = "draft" | "ready" | "generating" | "failed"

export type XiajiVoiceProfile = {
  language: string
  timbre: string
  pitch: string
  speaking_style: string
  sample_line: string
  tts_voice: string
  prompt: string
}

export type XiajiCharacterLook = {
  id: string
  name: string
  appearance_details: string
  image_url?: string
  job_id?: string
  clothing_image_url?: string
  age_group?: string
  body_type?: string
  face_prompt?: string
  aliases?: string
  shot_count?: number
}

export type XiajiVoiceSlot = {
  slot: string
  url: string
  inherited_from_default: boolean
  media_id?: string
}

export type XiajiAsset = {
  id: string
  kind: XiajiAssetKind
  name: string
  status: XiajiAssetStatus
  definition: Record<string, unknown> & {
    aliases?: string[]
    role?: string
    is_main?: boolean
    gender?: string
    age_group?: string
    body_type?: string
    description?: string
    face_prompt?: string
    visual_style?: string
    ethnicity?: string
    looks?: XiajiCharacterLook[]
    voice_profile?: XiajiVoiceProfile
    scene_type?: string
    environment_prompt?: string
    time_of_day?: string
    back_image_url?: string
    panorama_image_url?: string
    scene_jobs?: { master?: string; reverse?: string; panorama?: string }
    custom_bundle_url?: string
    custom_bundle_name?: string
    shot_count?: number
    prop_type?: string
    visual_prompt?: string
    owner?: string
    turnaround_image_url?: string
    detail_image_url?: string
    prop_jobs?: { master?: string; turnaround?: string; detail?: string }
  }
  image_url?: string | null
  image_job_id?: string | null
  error?: string | null
  voice_slots?: XiajiVoiceSlot[]
  updated_at: string
}

export function listXiajiAssets(projectId: string, kind?: XiajiAssetKind) {
  const extra = kind ? { kind } : undefined
  return requestJson<XiajiAsset[]>(withProjectQuery("/api/xiaji/assets", projectId, extra))
}

export function syncXiajiAssets(csrfToken: string, projectId: string, documentId?: string) {
  return requestJson<{
    created: number
    document_id: string | null
    transferred: { characters: number; scenes: number; props: number }
    assets: XiajiAsset[]
  }>(
    withProjectQuery("/api/xiaji/assets/sync", projectId),
    jsonMutation(csrfToken, { document_id: documentId || null }),
  )
}

export function createXiajiAsset(
  csrfToken: string,
  projectId: string,
  payload: { kind: XiajiAssetKind; name: string; definition?: Record<string, unknown> },
) {
  return requestJson<XiajiAsset>(withProjectQuery("/api/xiaji/assets", projectId), jsonMutation(csrfToken, payload))
}

export function updateXiajiAsset(csrfToken: string, assetId: string, payload: { name?: string; definition?: Record<string, unknown> }) {
  return requestJson<XiajiAsset>(
    `/api/xiaji/assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, payload, "PUT"),
  )
}

export function deleteXiajiAsset(csrfToken: string, assetId: string) {
  return requestJson<{ ok: boolean }>(
    `/api/xiaji/assets/${encodeURIComponent(assetId)}`,
    jsonMutation(csrfToken, undefined, "DELETE"),
  )
}

export type XiajiAssetGenerateImagePayload = {
  look_id?: string | null
  style?: string
  ethnicity?: string
  model?: string
  scene_view?: "master" | "reverse" | "panorama"
  prop_view?: "master" | "turnaround" | "detail"
}

export type XiajiAssetGenerateImageResult = {
  ok: boolean
  job_id: string
  status: XiajiAssetStatus
  asset: XiajiAsset
}

export function generateXiajiAssetImage(
  csrfToken: string,
  assetId: string,
  payload: XiajiAssetGenerateImagePayload = {},
) {
  return requestJson<XiajiAssetGenerateImageResult>(
    `/api/xiaji/assets/${encodeURIComponent(assetId)}/generate-image`,
    jsonMutation(csrfToken, {
      look_id: payload.look_id || null,
      style: payload.style || "",
      ethnicity: payload.ethnicity || "",
      model: payload.model || "",
      scene_view: payload.scene_view || null,
      prop_view: payload.prop_view || null,
    }),
  )
}

export async function waitForXiajiImageJob(jobId: string) {
  const started = Date.now()
  const timeoutMs = 30 * 60 * 1000
  while (Date.now() - started < timeoutMs) {
    const job = await requestJson<{ status: string; error?: string | null }>(
      `/api/jobs/${encodeURIComponent(jobId)}`,
    )
    if (job.status === "succeeded" || job.status === "partial") return job
    if (job.status === "failed" || job.status === "interrupted" || job.status === "cancelled") {
      throw new Error(job.error || "生成任务失败")
    }
    await new Promise((resolve) => window.setTimeout(resolve, 2000))
  }
  throw new Error("等待生成任务超时")
}

export async function uploadXiajiAssetImage(csrfToken: string, assetId: string, file: File, lookId?: string, slot?: string) {
  const body = new FormData()
  body.append("file", file)
  if (lookId) body.append("look_id", lookId)
  if (slot) body.append("slot", slot)
  return requestJson<XiajiAsset>(`/api/xiaji/assets/${encodeURIComponent(assetId)}/upload-image`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body,
  })
}

export function defineXiajiVoice(csrfToken: string, assetId: string) {
  return requestJson<XiajiAsset>(
    `/api/xiaji/assets/${encodeURIComponent(assetId)}/define-voice`,
    jsonMutation(csrfToken, {}),
  )
}

export function generateXiajiVoice(csrfToken: string, assetId: string, slot = "default") {
  return requestJson<XiajiAsset>(
    `/api/xiaji/assets/${encodeURIComponent(assetId)}/generate-voice?slot=${encodeURIComponent(slot)}`,
    jsonMutation(csrfToken, {}),
  )
}

export async function uploadXiajiVoice(csrfToken: string, assetId: string, file: File, slot = "default") {
  const body = new FormData()
  body.append("file", file)
  body.append("slot", slot)
  return requestJson<XiajiAsset>(`/api/xiaji/assets/${encodeURIComponent(assetId)}/upload-voice`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body,
  })
}

export type XiajiEpisodeStatus = "draft" | "scripting" | "script_ready" | "sketching" | "sketched"
export type XiajiBeatKind = "scene_heading" | "action" | "dialogue"
export type XiajiBeatStatus = "draft" | "queued" | "generating" | "succeeded" | "failed"

export type XiajiEpisodeLink = {
  id: string
  asset_id: string
  kind: "character" | "scene" | "prop"
  first_seen_line: number
  name?: string
  image_url?: string | null
  sketch_color?: string | null
  sketch_color_name?: string | null
  definition?: Record<string, unknown>
}

export type XiajiBeat = {
  id: string
  episode_id?: string
  sequence: number
  kind: XiajiBeatKind
  heading: string
  speaker: string
  dialogue: string
  action: string
  character_ids: string[]
  scene_id?: string | null
  prop_ids: string[]
  sketch_job_id?: string | null
  sketch_url?: string | null
  sketch_prompt?: string | null
  sketch_model?: string | null
  render_job_id?: string | null
  render_url?: string | null
  render_prompt?: string | null
  render_model?: string | null
  render_status?: XiajiBeatStatus | "draft"
  render_error?: string | null
  video_job_id?: string | null
  video_url?: string | null
  video_prompt?: string | null
  video_model?: string | null
  video_duration?: string | null
  video_status?: XiajiBeatStatus | "draft"
  video_error?: string | null
  status: XiajiBeatStatus
  error?: string | null
}

export type XiajiEpisode = {
  id: string
  project_id: string
  number: number
  title: string
  source_document_id?: string | null
  content_summary: string
  main_conflict: string
  cliffhanger: string
  key_events: string[]
  original_lines: string[]
  status: XiajiEpisodeStatus
  error?: string | null
  links: XiajiEpisodeLink[]
  beats: XiajiBeat[]
  beat_count: number
  character_count: number
  scene_count: number
  prop_count: number
  line_count: number
  sketch_ready?: number
  sketch_failed?: number
  updated_at: string
}

export function listXiajiEpisodes(projectId: string) {
  return requestJson<XiajiEpisode[]>(withProjectQuery("/api/xiaji/episodes", projectId))
}

export function getXiajiEpisode(episodeId: string) {
  return requestJson<XiajiEpisode>(`/api/xiaji/episodes/${encodeURIComponent(episodeId)}`)
}

export function createXiajiEpisodesFromAnalysis(csrfToken: string, projectId: string, force = false) {
  return requestJson<XiajiEpisode[]>(
    withProjectQuery("/api/xiaji/episodes/from-analysis", projectId),
    jsonMutation(csrfToken, { force }),
  )
}

export type XiajiScriptResult = {
  ok: boolean
  status: XiajiEpisodeStatus
  reused?: boolean
  episode: XiajiEpisode
}

export function generateXiajiEpisodeScript(csrfToken: string, episodeId: string, force = false) {
  return requestJson<XiajiScriptResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/generate-script`,
    jsonMutation(csrfToken, { force }),
  )
}

export function saveXiajiEpisodeBeats(csrfToken: string, episodeId: string, beats: XiajiBeat[]) {
  return requestJson<XiajiEpisode>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats`,
    jsonMutation(csrfToken, {
      beats: beats.map((item) => ({
        id: item.id,
        kind: item.kind,
        heading: item.heading,
        speaker: item.speaker,
        dialogue: item.dialogue,
        action: item.action,
        character_ids: item.character_ids,
        scene_id: item.scene_id,
        prop_ids: item.prop_ids,
      })),
    }, "PUT"),
  )
}

export type XiajiSketchResult = {
  ok: boolean
  job_id?: string | null
  job_ids?: string[]
  status?: string
  reused?: boolean
  episode: XiajiEpisode
}

export type XiajiBeatPatch = {
  heading?: string
  speaker?: string
  dialogue?: string
  action?: string
  character_ids?: string[]
  scene_id?: string | null
  prop_ids?: string[]
}

export function patchXiajiBeat(csrfToken: string, episodeId: string, beatId: string, payload: XiajiBeatPatch) {
  return requestJson<XiajiEpisode>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}`,
    jsonMutation(csrfToken, payload, "PATCH"),
  )
}

export async function uploadXiajiBeatSketch(csrfToken: string, episodeId: string, beatId: string, file: File) {
  const body = new FormData()
  body.append("file", file)
  return requestJson<XiajiEpisode>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/upload-sketch`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body,
    },
  )
}

export function generateXiajiBeatSketch(
  csrfToken: string,
  episodeId: string,
  beatId: string,
  force = false,
  sceneView: "front" | "reverse" = "front",
) {
  return requestJson<XiajiSketchResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/generate-sketch`,
    jsonMutation(csrfToken, { force, scene_view: sceneView }),
  )
}

export function generateXiajiEpisodeSketches(csrfToken: string, episodeId: string, force = false) {
  return requestJson<XiajiSketchResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/generate-sketches`,
    jsonMutation(csrfToken, { force }),
  )
}

export type XiajiVideoGeneratePayload = {
  force?: boolean
  family?: string
  duration?: number
  quality?: string
  aspect_ratio?: string
  speed?: string
  custom_steps?: number
  scene_view?: "front" | "reverse"
}

export function generateXiajiBeatRender(
  csrfToken: string,
  episodeId: string,
  beatId: string,
  force = false,
  sceneView: "front" | "reverse" = "front",
) {
  return requestJson<XiajiSketchResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/generate-render`,
    jsonMutation(csrfToken, { force, scene_view: sceneView }),
  )
}

export function generateXiajiBeatVideo(
  csrfToken: string,
  episodeId: string,
  beatId: string,
  payload: XiajiVideoGeneratePayload = {},
) {
  return requestJson<XiajiSketchResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/generate-video`,
    jsonMutation(csrfToken, {
      force: payload.force || false,
      family: payload.family || "",
      duration: payload.duration ?? null,
      quality: payload.quality || "",
      aspect_ratio: payload.aspect_ratio || "",
      speed: payload.speed || "",
      custom_steps: payload.custom_steps ?? null,
      scene_view: payload.scene_view || "front",
    }),
  )
}

export type XiajiOptionProperty = {
  label?: string
  type?: string
  default?: unknown
  enum?: string[]
  minimum?: number
  maximum?: number
  step?: number
  ui_group?: string
  ui_options?: Array<{ value: string; label: string }>
  ui_visible_when?: Record<string, string>
  megapixels_by_quality?: Record<string, number>
  ui_resolution_preview?: { multiple?: number; max_width?: number; max_height?: number }
}

export type XiajiWorkflowParameter = {
  name: string
  label?: string
  schema?: { properties?: Record<string, XiajiOptionProperty> }
}

export type XiajiWorkflowMode = {
  id: string
  name: string
  media_type?: string
  reference_mode?: string
  min_references?: number
  max_references?: number
  catalog_group?: string
  catalog_group_label?: string
  parameters?: XiajiWorkflowParameter[]
}

export const DEFAULT_XIAJI_VIDEO_WORKFLOW = "minimax-h3-lightx2v-r2v"

export function isXiajiShotVideoMode(item: XiajiWorkflowMode) {
  if (item.media_type !== "video") return false
  if (item.reference_mode === "keyframes") return true
  return item.reference_mode === "collection" && (item.max_references ?? 0) >= 3
}

export function listXiajiWorkflowModes() {
  return requestJson<{ modes: XiajiWorkflowMode[] }>("/api/modes")
}
