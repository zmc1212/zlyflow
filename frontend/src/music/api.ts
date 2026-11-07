export type MusicJobStatus = "queued" | "running" | "succeeded" | "failed"

export type MusicJobParams = {
  duration_seconds?: number
  output_format?: string
  steps?: number | null
  seed?: number | null
  lm_seed?: number | null
  cot?: string
  adapters?: { id: string; scales?: Record<string, number> }[]
}

export type MusicJob = {
  id: string
  owner_user_id: string
  title: string
  style: string
  lyrics: string
  status: MusicJobStatus
  progress: number
  params: MusicJobParams
  result_url: string | null
  result_format: string | null
  cover_url: string | null
  duration_seconds: number | null
  remote_job_id: string | null
  remote_song_id: string | null
  error_message: string | null
  created_at: string | null
  updated_at: string | null
  completed_at: string | null
}

export type MusicLyricLine = {
  text: string
  start_seconds: number | null
  end_seconds: number | null
}

export type MusicLyrics = {
  status: "idle" | "aligning" | "ready" | "unavailable" | "failed"
  lines: MusicLyricLine[]
  message: string | null
}

export type MusicAdapter = {
  id: string
  name?: string
  title?: string
  scales?: Record<string, number>
  [key: string]: unknown
}

export type MusicRemoteConfig = {
  adapters: MusicAdapter[]
  defaults: unknown
  error: string | null
}

export type MusicStatus = {
  configured: boolean
  base_url: string
  credential_ready: boolean
}

export type MusicJobCreatePayload = {
  title: string
  style: string
  lyrics: string
  duration_seconds: number
  output_format: string
  steps?: number | null
  seed?: number | null
  lm_seed?: number | null
  cot: string
  adapters?: { id: string; scales?: Record<string, number> }[]
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    const detail = data?.detail
    if (typeof detail === "string" && detail.trim()) return detail
  } catch {
    // 非 JSON 响应走 fallback
  }
  return fallback
}

export async function fetchMusicStatus(): Promise<MusicStatus> {
  const response = await fetch("/api/music/status")
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐服务状态查询失败"))
  return response.json()
}

export async function fetchMusicConfig(): Promise<MusicRemoteConfig> {
  const response = await fetch("/api/music/config")
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐服务能力查询失败"))
  return response.json()
}

export async function fetchMusicJobs(): Promise<MusicJob[]> {
  const response = await fetch("/api/music/jobs")
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务列表查询失败"))
  return response.json()
}

export async function fetchMusicLyrics(jobId: string, signal: AbortSignal): Promise<MusicLyrics> {
  const response = await fetch("/api/music/jobs/" + encodeURIComponent(jobId) + "/lyrics", { signal })
  if (!response.ok) throw new Error(await readErrorDetail(response, "歌词状态暂时无法读取"))
  return response.json()
}

export async function alignMusicLyrics(csrfToken: string, jobId: string): Promise<MusicLyrics> {
  const response = await fetch("/api/music/jobs/" + encodeURIComponent(jobId) + "/lyrics", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "暂时无法开始歌词对齐"))
  return response.json()
}

export async function createMusicJob(csrfToken: string, payload: MusicJobCreatePayload): Promise<MusicJob> {
  const response = await fetch("/api/music/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务提交失败"))
  return response.json()
}

export type MusicVibePayload = {
  description: string
  duration_seconds: number
  instrumental: boolean
}

export async function createMusicFromVibe(csrfToken: string, payload: MusicVibePayload): Promise<MusicJob> {
  const response = await fetch("/api/music/vibe", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务提交失败"))
  return response.json()
}

export async function deleteMusicJob(csrfToken: string, jobId: string): Promise<void> {
  const response = await fetch(`/api/music/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务删除失败"))
}

export function adapterLabel(adapter: MusicAdapter): string {
  const name = adapter.name || adapter.title || adapter.id
  return String(name)
}

export function formatMusicDuration(seconds: number | null | undefined): string {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return ""
  const rounded = Math.round(value)
  const minutes = Math.floor(rounded / 60)
  const rest = rounded % 60
  return `${minutes}:${String(rest).padStart(2, "0")}`
}
