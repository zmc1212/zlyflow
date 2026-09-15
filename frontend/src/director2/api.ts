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

export function createProject(csrfToken: string, data: { name: string; description?: string; cover_url?: string | null; settings?: Record<string, unknown> | null }): Promise<Director2Project> {
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

export function transferEpisodesFromDoc(csrfToken: string, projectId: string, docId: string): Promise<Record<string, any>> {
  return requestJson<Record<string, any>>(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId)}/transfer-episodes`,
    jsonMutation(csrfToken),
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
}

export type Director2Beat = {
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
  video_prompt_zh?: string
  video_duration?: string
  status?: string
}

export function getEpisodeDetail(projectId: string, epId: string): Promise<Director2EpisodeDetail> {
  return requestJson<Director2EpisodeDetail>(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}`,
  )
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

export function generateBeatImagesBatch(csrfToken: string, projectId: string, epId: string, data: Record<string, unknown>): Promise<Record<string, any>> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-images`,
    jsonMutation(csrfToken, data, "POST"),
  )
}

export function generateEpisodeVideo(csrfToken: string, projectId: string, epId: string): Promise<{ job_id: string; status: string }> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/episodes/${encodeURIComponent(epId)}/generate-video`,
    jsonMutation(csrfToken),
  )
}

// --- 全部任务 Jobs ---
export function listJobs(projectId: string): Promise<Director2Job[]> {
  return requestJson<Director2Job[]>(`/api/projects/${encodeURIComponent(projectId)}/jobs`)
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
