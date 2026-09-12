import { ApiRequestError, jsonMutation, notifyUnauthorized, requestJson } from "../api"

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
  art_style_id?: string
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

export type XiajiUserArtStyle = {
  art_style_id: string
  art_style: { id: string; name: string; name_en?: string; promptPrefix?: string; imageUrl?: string | null } | null
}

export function getXiajiUserArtStyle() {
  return requestJson<XiajiUserArtStyle>("/api/xiaji/art-style")
}

export function saveXiajiUserArtStyle(csrfToken: string, artStyleId: string) {
  return requestJson<XiajiUserArtStyle>(
    "/api/xiaji/art-style",
    jsonMutation(csrfToken, { art_style_id: artStyleId }, "PUT"),
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
  replace = false,
) {
  const body = new FormData()
  body.append("file", file)
  if (title?.trim()) body.append("title", title.trim())
  if (settings?.spine_template) body.append("spine_template", settings.spine_template)
  if (settings?.art_style_id) body.append("art_style_id", settings.art_style_id)
  if (settings?.visual_style) body.append("visual_style", settings.visual_style)
  if (settings?.narration_style) body.append("narration_style", settings.narration_style)
  if (settings?.ethnicity) body.append("ethnicity", settings.ethnicity)
  if (replace) body.append("replace", "true")
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
  replace = false,
) {
  return requestJson<XiajiDocumentDetail>(
    withProjectQuery("/api/xiaji/documents/paste", projectId),
    jsonMutation(csrfToken, {
      text,
      title: title?.trim() || "",
      spine_template: settings?.spine_template || "drama",
      art_style_id: settings?.art_style_id || "",
      visual_style: settings?.visual_style || "",
      narration_style: settings?.narration_style || "",
      ethnicity: settings?.ethnicity || "",
      replace,
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

export type XiajiAssetMedia = {
  id: string
  media_kind: string
  slot: string
  job_id?: string | null
  url?: string | null
  job_status?: string | null
  job_error?: string | null
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
    art_style_id?: string
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
  media?: XiajiAssetMedia[]
  updated_at: string
}

export function xiajiMediaSlotItem(asset: XiajiAsset, mediaKind: string, slot: string) {
  return (asset.media || []).find(
    (item) => item.media_kind === mediaKind && (item.slot || mediaKind) === slot,
  )
}

const TERMINAL_JOB_STATUS = new Set(["succeeded", "partial", "failed", "interrupted", "cancelled"])

export function xiajiMediaSlotPending(asset: XiajiAsset, mediaKind: string, slot: string) {
  const match = xiajiMediaSlotItem(asset, mediaKind, slot)
  if (!match?.job_id || match.url) return false
  return !TERMINAL_JOB_STATUS.has(String(match.job_status || ""))
}

export function xiajiMediaSlotError(asset: XiajiAsset, mediaKind: string, slot: string) {
  const match = xiajiMediaSlotItem(asset, mediaKind, slot)
  if (match?.url) return ""
  return String(match?.job_error || "").trim()
}

export function xiajiAssetNeedsJobPoll(asset: XiajiAsset) {
  if (asset.status === "generating") return true
  const extra = { ...(asset.definition.scene_jobs || {}), ...(asset.definition.prop_jobs || {}) }
  if (Object.values(extra).some((id) => Boolean(id))) return true
  return (asset.media || []).some(
    (item) => Boolean(item.job_id && !item.url && !TERMINAL_JOB_STATUS.has(String(item.job_status || ""))),
  )
}

export function xiajiSlotImageUrl(asset: XiajiAsset, mediaKind: string, slot: string) {
  const match = (asset.media || []).find(
    (item) => item.media_kind === mediaKind && (item.slot || mediaKind) === slot && Boolean(item.url),
  )
  return match?.url || ""
}

export type XiajiProjectJob = {
  id: string
  job_id: string
  source: string
  target: string
  slot: string
  slot_label: string
  bound_url?: string
  title: string
  status: string
  mode?: string | null
  prompt: string
  system_prompt?: string
  error?: string | null
  progress: number
  preview_url?: string
  outputs?: { kind?: string; cloud_url?: string | null; download_url?: string | null }[]
  llm_output?: unknown
  job_created_at?: string | null
  job_updated_at?: string | null
  missing?: boolean
  reference_count?: number
  references?: { index: number; url: string; label?: string }[]
  options?: Record<string, unknown>
  negative_prompt?: string
  image_size?: string | null
  parameters?: { name: string; label: string; value: unknown }[]
}

export function listXiajiProjectJobs(projectId: string) {
  return requestJson<XiajiProjectJob[]>(withProjectQuery("/api/xiaji/jobs", projectId))
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
  art_style_id?: string
  visual_style?: string
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
      style: payload.art_style_id || payload.style || "",
      art_style_id: payload.art_style_id || payload.style || "",
      visual_style: payload.visual_style || "",
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
  const failed = new Set(["failed", "interrupted", "cancelled", "error", "failure", "timeout", "stopped", "canceled"])
  while (Date.now() - started < timeoutMs) {
    let job: { status: string; error?: string | null }
    try {
      job = await requestJson<{ status: string; error?: string | null }>(
        `/api/jobs/${encodeURIComponent(jobId)}`,
      )
    } catch (error) {
      if (error instanceof ApiRequestError && (error.status === 404 || error.status === 410)) {
        throw new Error(error.message || "任务不存在或已失败")
      }
      throw error
    }
    if (job.status === "succeeded" || job.status === "partial") return job
    if (failed.has(job.status)) {
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
  video_prompt_zh?: string | null
  video_prompt_job_id?: string | null
  video_pictures?: Array<{
    index: number
    tag: string
    role: string
    material?: string
    name?: string
    label_zh?: string
    label_en?: string
    detail_zh?: string
    detail_en?: string
  }>
  video_model?: string | null
  video_duration?: string | null
  video_status?: XiajiBeatStatus | "draft"
  video_error?: string | null
  video_in_frame_url?: string | null
  video_in_frame_sec?: string | null
  video_in_source_job_id?: string | null
  video_in_frame_manual?: string | null
  audio_url?: string | null
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
  compose_status?: "idle" | "composing" | "succeeded" | "failed"
  compose_url?: string | null
  compose_error?: string | null
  compose_resolution?: string | null
  compose_add_subtitles?: boolean
  compose_duration_sec?: number | null
  compose_at?: string | null
  compose_filename?: string
  compose_progress?: number
  compose_ready?: boolean
  compose_blockers?: Array<{ beat_id: string; sequence: number; stages: string[] }>
  updated_at: string
}

export function xiajiBeatSlotBusy(status?: string | null) {
  return status === "queued" || status === "generating"
}

export function xiajiBeatCanMakeVideo(beat?: XiajiBeat | null) {
  if (!beat) return false
  if (beat.kind === "scene_heading" && !beat.action && !beat.heading) return false
  return true
}

export function xiajiPreviousVideoBeat(episode: XiajiEpisode | null | undefined, beat: XiajiBeat | null | undefined) {
  if (!episode || !beat) return null
  let previous: XiajiBeat | null = null
  for (const item of episode.beats || []) {
    if ((item.sequence || 0) >= (beat.sequence || 0)) break
    if (xiajiBeatCanMakeVideo(item)) previous = item
  }
  return previous
}

export function xiajiEpisodeHasActiveJobs(episode?: XiajiEpisode | null) {
  if (!episode) return false
  if (episode.status === "scripting") return true
  if (episode.compose_status === "composing") return true
  return (episode.beats || []).some(
    (item) =>
      xiajiBeatSlotBusy(item.status) || xiajiBeatSlotBusy(item.render_status) || xiajiBeatSlotBusy(item.video_status),
  )
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
  video_prompt_zh?: string
  video_duration?: string
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

export async function uploadXiajiBeatInFrame(
  csrfToken: string,
  episodeId: string,
  beatId: string,
  file: File,
  payload: { sec?: number | null; manual?: boolean; sourceJobId?: string | null } = {},
) {
  const body = new FormData()
  body.append("file", file)
  if (payload.sec != null && Number.isFinite(payload.sec)) body.append("sec", String(payload.sec))
  if (payload.manual) body.append("manual", "1")
  if (payload.sourceJobId) body.append("source_job_id", payload.sourceJobId)
  return requestJson<XiajiEpisode>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/upload-in-frame`,
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
      duration: payload.duration ?? 5,
      quality: payload.quality || "",
      aspect_ratio: payload.aspect_ratio || "",
      speed: payload.speed || "",
      custom_steps: payload.custom_steps ?? null,
      scene_view: payload.scene_view || "front",
    }),
  )
}

export function generateXiajiBeatVideoPrompt(
  csrfToken: string,
  episodeId: string,
  beatId: string,
  payload: Pick<XiajiVideoGeneratePayload, "force" | "family" | "duration" | "scene_view"> = {},
) {
  return requestJson<{
    ok: boolean
    episode: XiajiEpisode
    prompt_zh?: string | null
    prompt_en?: string | null
    pictures?: XiajiBeat["video_pictures"]
  }>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/beats/${encodeURIComponent(beatId)}/video-prompt`,
    jsonMutation(csrfToken, {
      force: payload.force || false,
      family: payload.family || "",
      duration: payload.duration ?? 5,
      scene_view: payload.scene_view || "front",
    }),
  )
}

export type XiajiAutoRun = {
  id: string
  status: string
  progress: number
  video_params?: Record<string, unknown>
  cursor?: { beat_id?: string; sequence?: number; step?: string; index?: number; total?: number } | null
  error?: string | null
  step_label?: string
  message?: string
}

export type XiajiAutoRunResult = { ok: boolean; run: XiajiAutoRun | null }

export function startXiajiEpisodeAutoRun(csrfToken: string, episodeId: string, payload: XiajiVideoGeneratePayload = {}) {
  return requestJson<XiajiAutoRunResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/auto-run`,
    jsonMutation(csrfToken, {
      family: payload.family || "",
      duration: payload.duration ?? 5,
      quality: payload.quality || "",
      aspect_ratio: payload.aspect_ratio || "16:9",
      speed: payload.speed || "",
      custom_steps: payload.custom_steps ?? null,
      scene_view: payload.scene_view || "front",
    }),
  )
}

export function getXiajiEpisodeAutoRun(episodeId: string) {
  return requestJson<XiajiAutoRunResult>(`/api/xiaji/episodes/${encodeURIComponent(episodeId)}/auto-run`)
}

export type XiajiComposeResult = { ok: boolean; status: string; reused?: boolean; job_id?: string | null; episode: XiajiEpisode }

export function composeXiajiEpisode(
  csrfToken: string,
  episodeId: string,
  payload: { resolution?: string; add_subtitles?: boolean; force?: boolean } = {},
) {
  return requestJson<XiajiComposeResult>(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/compose`,
    jsonMutation(csrfToken, {
      resolution: payload.resolution || "1280x720",
      add_subtitles: payload.add_subtitles !== false,
      force: payload.force || false,
    }),
  )
}

async function downloadXiajiBlob(path: string, filename: string, init?: RequestInit) {
  const response = await fetch(path, init)
  if (response.status === 401) notifyUnauthorized()
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? ""
    if (contentType.includes("application/json")) {
      const body = await response.json().catch(() => null)
      throw new ApiRequestError(response.status, body)
    }
    const text = await response.text().catch(() => "")
    throw new ApiRequestError(response.status, text.trim() || `请求失败（HTTP ${response.status}）`)
  }
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 2000)
}

export function downloadXiajiEpisodeVideo(episodeId: string, filename: string) {
  return downloadXiajiBlob(`/api/xiaji/episodes/${encodeURIComponent(episodeId)}/export/video`, filename)
}

export function downloadXiajiEpisodeSrt(episodeId: string, filename: string) {
  return downloadXiajiBlob(`/api/xiaji/episodes/${encodeURIComponent(episodeId)}/export/srt`, filename)
}

export function downloadXiajiEpisodeZip(csrfToken: string, episodeId: string, filename: string) {
  return downloadXiajiBlob(
    `/api/xiaji/episodes/${encodeURIComponent(episodeId)}/export/zip`,
    filename,
    jsonMutation(csrfToken, {}, "POST"),
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
