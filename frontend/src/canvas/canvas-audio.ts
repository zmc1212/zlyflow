/**
 * 画布音频节点：TTS 配音与本地音乐生成的任务提交、轮询与展示文案。
 *
 * 服务端接口：
 * - `GET  /api/canvas/audio/options`：按管理设置里实际生效的 TTS 返回音色目录，并给出音乐服务是否可用。
 * - `POST /api/canvas/audio/tts`：同步合成，返回画布可播放的地址。
 * - `POST /api/music/vibe` / `GET /api/music/jobs/{id}`：本地音乐生成（YuE2）提交与轮询。
 */

export type CanvasAudioMode = "tts" | "music"

export type CanvasAudioVoice = {
  id: string
  label: string
  gender?: string
}

export type CanvasAudioOptions = {
  tts: {
    configured: boolean
    reason: string
    provider: string
    voice: string
    voices: CanvasAudioVoice[]
  }
  music: {
    configured: boolean
  }
}

export type CanvasMusicJob = {
  id: string
  status: string
  progress: number
  result_url: string | null
  error_message: string | null
  duration_seconds: number | null
}

export type CanvasTtsResult = {
  url: string
  bytes?: number
}

export const CANVAS_MUSIC_DURATIONS = [30, 60, 120] as const

export const CANVAS_AUDIO_PROVIDER_LABELS: Record<string, string> = {
  indextts: "IndexTTS",
  mimo: "MiMo TTS",
  siliconflow: "CosyVoice",
  openai: "OpenAI TTS",
  custom: "自定义 TTS",
}

export function canvasAudioModeLabel(mode: CanvasAudioMode): string {
  return mode === "music" ? "音乐生成" : "音频生成"
}

/** 节点标题：用户改过 label 就用 label，否则按模式显示「音频生成 / 音乐生成」。 */
export function canvasAudioTitle(label: string | undefined, mode: CanvasAudioMode): string {
  const text = (label ?? "").trim()
  return text || canvasAudioModeLabel(mode)
}

export function canvasAudioProviderLabel(provider: string | undefined): string {
  return CANVAS_AUDIO_PROVIDER_LABELS[String(provider ?? "").trim()] ?? "TTS"
}

export function canvasMusicDurationLabel(seconds: number | null | undefined): string {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return ""
  if (value < 60) return `${Math.round(value)} 秒`
  const minutes = value / 60
  return Number.isInteger(minutes) ? `${minutes} 分钟` : `${minutes.toFixed(1)} 分钟`
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    const detail = (data as { detail?: unknown } | null)?.detail
    if (typeof detail === "string" && detail.trim()) return detail
  } catch {
    // 非 JSON 响应走 fallback
  }
  return fallback
}

export async function fetchCanvasAudioOptions(signal?: AbortSignal): Promise<CanvasAudioOptions> {
  const response = await fetch("/api/canvas/audio/options", { signal })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音色目录读取失败"))
  return response.json()
}

export async function submitCanvasTts(
  csrfToken: string,
  payload: { text: string; voice?: string | null },
): Promise<CanvasTtsResult> {
  const response = await fetch("/api/canvas/audio/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ text: payload.text, voice: payload.voice || null }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "语音合成失败"))
  return response.json()
}

export async function submitCanvasMusic(
  csrfToken: string,
  payload: { description: string; durationSeconds: number; instrumental: boolean },
): Promise<CanvasMusicJob> {
  const response = await fetch("/api/music/vibe", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      description: payload.description,
      duration_seconds: payload.durationSeconds,
      instrumental: payload.instrumental,
    }),
  })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务提交失败"))
  return response.json()
}

export async function fetchCanvasMusicJob(jobId: string, signal?: AbortSignal): Promise<CanvasMusicJob> {
  const response = await fetch(`/api/music/jobs/${encodeURIComponent(jobId)}`, { signal })
  if (!response.ok) throw new Error(await readErrorDetail(response, "音乐任务状态读取失败"))
  return response.json()
}
