import {
  ApiRequestError,
  jsonMutation,
  notifyUnauthorized,
  requestJson
} from "../../api"
import type { EditAsset, EditDocument } from "./model"

export type EditSnapshot = {
  revision: number
  document: EditDocument
  updated_at?: string | null
  draft_key: string
}
export type ExportJob = {
  id: string
  status: string
  progress: number
  result_url?: string
  error_message?: string
}
export type EditingOperation =
  | "video_arrange"
  | "subtitle_arrange"
  | "audio_subtitle"
  | "subtitle_translate"
  | "dialogue_cut"
  | "quick_cut"
  | "highlight_cut"
  | "hook_cut"
export type HookStrategy =
  | "conflict_3s"
  | "climax_only"
  | "quote_open"
  | "ending_hook"
  | "trailer"
export type UnderstandingStatus =
  | "missing"
  | "queued"
  | "running"
  | "succeeded"
  | "partial"
  | "empty"
  | "failed"
export type UnderstandingShot = {
  index: number
  start: number
  end: number
  duration: number
  status: "succeeded" | "failed"
  description: string
  camera: string
  subjects: { name: string; type: string; description: string }[]
  frames: number
  error?: string | null
}
export type UnderstandingItem = {
  beat_id?: string | null
  asset_id: string
  name: string
  duration: number
  status: "succeeded" | "partial" | "failed"
  description: string
  camera: string
  subjects: { name: string; type: string; description: string }[]
  frames: number
  detected_count?: number
  sampled_count?: number
  shots?: UnderstandingShot[]
  detection_error?: string | null
  error?: string | null
}
export type UnderstandingSummary = {
  video_count: number
  analyzed_count: number
  failed_count: number
  detected_shot_count?: number
  shot_count?: number
  shot_analyzed_count?: number
  shot_failed_count?: number
}
export type MediaUnderstanding = {
  id?: string
  status: UnderstandingStatus
  project_id?: string
  sequence_id?: string
  model?: string | null
  progress?: number
  message?: string
  summary?: UnderstandingSummary
  items?: UnderstandingItem[]
  started_at?: string | null
  finished_at?: string | null
  stale?: boolean
}
export type TranscriptStatus = UnderstandingStatus
export type TranscriptSegment = { id: string; start: number; end: number; text: string }
export type TranscriptSpan = {
  clip_id: string
  timeline_start: number
  timeline_duration: number
  in_point: number
  speed: number
}
export type TranscriptItem = {
  asset_id: string
  beat_id?: string | null
  name: string
  kind: string
  duration: number
  timeline_start?: number | null
  status: "succeeded" | "empty" | "failed" | "skipped"
  segments: TranscriptSegment[]
  segment_count: number
  audio_seconds: number
  language?: string | null
  error?: string | null
  spans: TranscriptSpan[]
}
export type TranscriptSummary = {
  media_count: number
  transcribed_count: number
  failed_count: number
  skipped_count: number
  segment_count: number
  audio_seconds: number
}
export type MediaTranscript = {
  id?: string
  status: TranscriptStatus
  project_id?: string
  sequence_id?: string
  model?: string | null
  progress?: number
  message?: string
  summary?: TranscriptSummary
  items?: TranscriptItem[]
  started_at?: string | null
  finished_at?: string | null
  stale?: boolean
}
export type EditingAction = {
  id: string
  operation: EditingOperation
  title: string
  project_id: string
  sequence_id: string
  base_revision: number
  status: "pending" | "empty" | "succeeded"
  items: {
    asset_id?: string
    beat_id?: string
    segment_id?: string
    clip_id?: string
    name: string
    start?: number
    duration?: number
    action?: "add" | "keep" | "trim" | "update"
    reason?: string
  }[]
  count: number
  skipped_count?: number
  missing_video_count?: number
  append_at?: number
  total_duration: number
  dropped_count?: number
  trimmed_count?: number
  replaced_count?: number
  inaudible_count?: number
  strategy?: HookStrategy
  strategy_title?: string
  principle?: string
  reapplied_from?: string
  understanding?: {
    status: UnderstandingStatus | "stale"
    model?: string | null
    analyzed_count?: number
    shot_count?: number
    shot_analyzed_count?: number
    used_count: number
    shot_used_count?: number
  }
  transcript?: {
    status: TranscriptStatus | "stale"
    model?: string | null
    transcribed_at?: string | null
    transcribed_count?: number
    used_count: number
    segment_count: number
    audio_seconds?: number
  }
  snapshot?: EditSnapshot
}
const base = (project: string) =>
  `/api/projects/${encodeURIComponent(project)}/smart-edit`
export const readEdit = (project: string, sequence: string) =>
  requestJson<EditSnapshot>(`${base(project)}/${encodeURIComponent(sequence)}`)
export const readSources = (project: string, sequence: string) =>
  requestJson<EditAsset[]>(
    `${base(project)}/${encodeURIComponent(sequence)}/sources`
  )
const sequenceBase = (project: string, sequence: string) =>
  `${base(project)}/${encodeURIComponent(sequence)}`
export const readUnderstanding = (project: string, sequence: string) =>
  requestJson<MediaUnderstanding>(`${sequenceBase(project, sequence)}/understanding`)
export const startUnderstanding = (
  token: string,
  project: string,
  sequence: string,
  force = false
) =>
  requestJson<MediaUnderstanding>(
    `${sequenceBase(project, sequence)}/understanding`,
    jsonMutation(token, { force })
  )
export const readTranscript = (project: string, sequence: string) =>
  requestJson<MediaTranscript>(`${sequenceBase(project, sequence)}/transcript`)
export const startTranscript = (
  token: string,
  project: string,
  sequence: string,
  force = false
) =>
  requestJson<MediaTranscript>(
    `${sequenceBase(project, sequence)}/transcript`,
    jsonMutation(token, { force })
  )
const actionBase = (project: string, sequence: string) => `${base(project)}/${encodeURIComponent(sequence)}/actions`
export const previewEditingAction = (
  token: string,
  project: string,
  sequence: string,
  revision: number,
  sessionId?: string,
  operation: EditingOperation = "video_arrange",
  assetIds?: string[],
  strategy?: HookStrategy
) =>
  requestJson<EditingAction>(
    `${actionBase(project, sequence)}/preview`,
    jsonMutation(token, {
      operation,
      revision,
      session_id: sessionId || null,
      ...(assetIds ? { asset_ids: assetIds } : {}),
      ...(strategy ? { strategy } : {})
    })
  )
export const reorderEditingAction = (
  token: string,
  project: string,
  sequence: string,
  id: string,
  assetIds: string[]
) =>
  requestJson<EditingAction>(
    `${actionBase(project, sequence)}/${encodeURIComponent(id)}/reorder`,
    jsonMutation(token, { asset_ids: assetIds })
  )
export const reapplyEditingAction = (
  token: string,
  project: string,
  sequence: string,
  id: string,
  revision: number,
  sessionId?: string
) =>
  requestJson<EditingAction>(
    `${actionBase(project, sequence)}/${encodeURIComponent(id)}/reapply`,
    jsonMutation(token, { revision, session_id: sessionId || null })
  )
export const readEditingAction = (project: string, sequence: string, id: string) =>
  requestJson<EditingAction>(`${actionBase(project, sequence)}/${encodeURIComponent(id)}`)
export const confirmEditingAction = (token: string, project: string, sequence: string, id: string) =>
  requestJson<EditingAction>(`${actionBase(project, sequence)}/${encodeURIComponent(id)}/confirm`, jsonMutation(token))
export const saveEdit = (
  token: string,
  project: string,
  sequence: string,
  revision: number,
  document: EditDocument
) =>
  requestJson<EditSnapshot>(
    `${base(project)}/${encodeURIComponent(sequence)}`,
    jsonMutation(token, { revision, document }, "PUT")
  )
export const exportMp4 = (
  token: string,
  project: string,
  document: EditDocument,
  quality: number
) =>
  requestJson<ExportJob>(
    `${base(project)}/exports/mp4`,
    jsonMutation(token, { document, quality })
  )
export const readExport = (project: string, id: string) =>
  requestJson<ExportJob>(`${base(project)}/exports/${encodeURIComponent(id)}`)
export type LocalImportResult = {
  path: string
  assets: EditAsset[]
  skipped: { name: string; error: string }[]
}
export const importLocalMedia = (
  token: string,
  project: string,
  sequence: string,
  path: string,
  recursive: boolean
) =>
  requestJson<LocalImportResult>(
    `${base(project)}/${encodeURIComponent(sequence)}/import-local`,
    jsonMutation(token, { path, recursive })
  )
export function uploadMedia(
  token: string,
  project: string,
  sequence: string,
  file: File
) {
  const form = new FormData()
  form.set("file", file)
  return requestJson<EditAsset>(
    `${base(project)}/${encodeURIComponent(sequence)}/upload`,
    { method: "POST", headers: { "X-CSRF-Token": token }, body: form }
  )
}
export async function exportBundle(
  token: string,
  project: string,
  document: EditDocument,
  format: string,
  include_media: boolean
) {
  const response = await fetch(
    `${base(project)}/exports/bundle`,
    jsonMutation(token, { document, format, include_media })
  )
  if (response.status === 401) notifyUnauthorized()
  if (!response.ok)
    throw new ApiRequestError(
      response.status,
      await response.json().catch(() => null)
    )
  return response.blob()
}
export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob),
    anchor = window.document.createElement("a")
  anchor.href = url
  anchor.download = name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 20000)
}
