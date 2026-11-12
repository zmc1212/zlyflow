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
  chat_id: string | null
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

export type FeaturedMusic = {
  id: string
  job_id: string
  owner_user_id: string | null
  title: string
  summary: string
  style: string
  lyrics: string
  result_url: string
  cover_url: string | null
  duration_seconds: number | null
  result_format: string | null
  sort_order: number
  published_at: string | null
  updated_at: string | null
}

export type FeaturedMusicPublishPayload = {
  job_id: string
  title?: string
  summary?: string
  cover_url?: string
  sort_order?: number
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

/** 音乐任务列表；管理员可传 user_id（"all" 或指定账号 id）查看其他用户数据。 */
export async function fetchMusicJobs(userId?: string | null): Promise<MusicJob[]> {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : ""
  const response = await fetch(`/api/music/jobs${query}`)
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务列表查询失败"))
  return response.json()
}

export async function fetchFeaturedMusic(): Promise<FeaturedMusic[]> {
  const response = await fetch("/api/featured-music")
  if (!response.ok) throw new Error(await readErrorDetail(response, "精选音乐列表查询失败"))
  return response.json()
}

export async function publishFeaturedMusic(csrfToken: string, payload: FeaturedMusicPublishPayload): Promise<FeaturedMusic> {
  const response = await fetch("/api/admin/featured-music", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "发布精选音乐失败"))
  return response.json()
}

export async function unpublishFeaturedMusic(csrfToken: string, featuredId: string): Promise<void> {
  const response = await fetch(`/api/admin/featured-music/${encodeURIComponent(featuredId)}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "取消精选音乐失败"))
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

export async function retryMusicJob(csrfToken: string, jobId: string): Promise<MusicJob> {
  const response = await fetch(`/api/music/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务重试失败"))
  return response.json()
}

export async function deleteMusicJob(csrfToken: string, jobId: string): Promise<void> {
  const response = await fetch(`/api/music/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务删除失败"))
}

export type MusicChatProposal = {
  changed: boolean
  title: string
  style: string
  lyrics: string
  duration_seconds: number
}

export type MusicChatMessage = {
  id: string
  chat_id: string
  role: "user" | "assistant"
  content: string
  proposal: MusicChatProposal | null
  job_id: string | null
  created_at: string | null
}

export type MusicChat = {
  id: string
  owner_user_id: string
  title: string
  anchor_job_id: string | null
  created_at: string | null
  updated_at: string | null
}

export type MusicChatDetail = MusicChat & {
  messages: MusicChatMessage[]
  anchor_job: MusicJob | null
}

export async function createMusicChat(csrfToken: string, anchorJobId?: string | null): Promise<MusicChat> {
  const response = await fetch("/api/music/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ anchor_job_id: anchorJobId || null }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "对话创建失败"))
  return response.json()
}

/** 音乐对话列表；管理员可传 user_id（"all" 或指定账号 id）查看其他用户数据。 */
export async function fetchMusicChats(userId?: string | null): Promise<MusicChat[]> {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : ""
  const response = await fetch(`/api/music/chats${query}`)
  if (!response.ok) throw new Error(await readErrorDetail(response, "对话列表查询失败"))
  return response.json()
}

export async function fetchMusicChat(chatId: string): Promise<MusicChatDetail> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}`)
  if (!response.ok) throw new Error(await readErrorDetail(response, "对话内容加载失败"))
  return response.json()
}

export async function sendMusicChatMessage(
  csrfToken: string, chatId: string, content: string,
  options?: { duration_seconds?: number; instrumental?: boolean },
): Promise<MusicChatDetail> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      content,
      duration_seconds: options?.duration_seconds ?? null,
      instrumental: options?.instrumental ?? null,
    }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐助手暂时没有接上，请重试"))
  return response.json()
}

export type MusicChatStreamHandlers = {
  onUserMessage?: (message: MusicChatMessage) => void
  onDelta?: (text: string) => void
  onDone?: (payload: { user_message: MusicChatMessage; assistant_message: MusicChatMessage }) => void
}

/** 流式对话轮：SSE（user_message → delta* → done/error），delta 是 reply 字段的增量文本；error 事件以异常抛出。 */
export async function streamMusicChatMessage(
  csrfToken: string, chatId: string, content: string,
  options: { duration_seconds?: number; instrumental?: boolean },
  handlers: MusicChatStreamHandlers,
): Promise<void> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      content,
      duration_seconds: options.duration_seconds ?? null,
      instrumental: options.instrumental ?? null,
    }),
  })
  if (!response.ok || !response.body) throw new Error(await readErrorDetail(response, "音乐助手暂时没有接上，请重试"))
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  const dispatch = (frame: string) => {
    let event = "message"
    const dataLines: string[] = []
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim()
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    let payload: Record<string, unknown>
    try { payload = JSON.parse(dataLines.join("\n")) } catch { return }
    if (event === "user_message") handlers.onUserMessage?.(payload.message as MusicChatMessage)
    else if (event === "delta") handlers.onDelta?.(String(payload.text ?? ""))
    else if (event === "done") handlers.onDone?.(payload as { user_message: MusicChatMessage; assistant_message: MusicChatMessage })
    else if (event === "error") throw new Error(String(payload.message ?? "音乐助手暂时没有接上，请重试"))
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index: number
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      dispatch(frame)
    }
  }
  if (buffer.trim()) dispatch(buffer)
}

export async function generateMusicChatProposal(csrfToken: string, chatId: string, messageId: string): Promise<MusicJob> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ message_id: messageId }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "提案生成任务提交失败"))
  return response.json()
}

export async function renameMusicChat(csrfToken: string, chatId: string, title: string): Promise<MusicChat> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ title }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "对话重命名失败"))
  return response.json()
}

export async function deleteMusicChat(csrfToken: string, chatId: string): Promise<void> {
  const response = await fetch(`/api/music/chats/${encodeURIComponent(chatId)}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "对话删除失败"))
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
