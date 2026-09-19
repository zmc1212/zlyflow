export const INDEXTTS_EMOTIONS = [
  { id: "calm", label: "平静" },
  { id: "happy", label: "开心" },
  { id: "angry", label: "愤怒" },
  { id: "sad", label: "悲伤" },
  { id: "afraid", label: "害怕" },
  { id: "disgusted", label: "厌恶" },
  { id: "melancholic", label: "忧郁" },
  { id: "surprised", label: "惊讶" },
] as const

export type IndexTtsEmotion = (typeof INDEXTTS_EMOTIONS)[number]["id"]

export const MAX_VOICE_AUDIO_BYTES = 20 * 1024 * 1024

export const VOICE_AUDIO_ACCEPT = "audio/wav,audio/mpeg,audio/mp4,audio/flac,audio/ogg,audio/aac,.wav,.mp3,.m4a,.flac,.ogg,.aac"

export type VoiceExtractSourceMeta = {
  kind: "shot"
  episode_id: string
  beat_id: string
  start_sec: number
  end_sec: number
}

export type CharacterVoiceProfile = {
  preset_id: string
  ref_audio_url: string
  preview_url: string
  default_emotion: string
  emo_alpha: number
  duration_factor: number
  source: VoiceExtractSourceMeta | null
}

function voiceSourceOf(raw: unknown): VoiceExtractSourceMeta | null {
  if (!raw || typeof raw !== "object") return null
  const source = raw as Record<string, unknown>
  const episodeId = String(source.episode_id || "").trim()
  const beatId = String(source.beat_id || "").trim()
  const start = Number(source.start_sec)
  const end = Number(source.end_sec)
  if (String(source.kind || "").trim() !== "shot" || !episodeId || !beatId) return null
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return { kind: "shot", episode_id: episodeId, beat_id: beatId, start_sec: start, end_sec: end }
}

export function emptyVoiceProfile(): CharacterVoiceProfile {
  return {
    preset_id: "",
    ref_audio_url: "",
    preview_url: "",
    default_emotion: "calm",
    emo_alpha: 0.8,
    duration_factor: 1,
    source: null,
  }
}

export function voiceOf(extra: Record<string, unknown> | null | undefined): CharacterVoiceProfile {
  const raw = extra && typeof extra === "object" ? extra.voice : null
  const base = emptyVoiceProfile()
  if (!raw || typeof raw !== "object") return base
  const voice = raw as Record<string, unknown>
  const emotion = String(voice.default_emotion || "").trim().toLowerCase()
  const known = INDEXTTS_EMOTIONS.some((item) => item.id === emotion)
  const emoAlpha = Number(voice.emo_alpha)
  const duration = Number(voice.duration_factor)
  return {
    preset_id: String(voice.preset_id || "").trim(),
    ref_audio_url: String(voice.ref_audio_url || "").trim(),
    preview_url: String(voice.preview_url || "").trim(),
    default_emotion: known ? emotion : "calm",
    emo_alpha: Number.isFinite(emoAlpha) ? Math.min(1, Math.max(0, emoAlpha)) : 0.8,
    duration_factor: Number.isFinite(duration) ? Math.min(2, Math.max(0.5, duration)) : 1,
    source: voiceSourceOf(voice.source),
  }
}

export function hasRefAudio(extra: Record<string, unknown> | null | undefined): boolean {
  const voice = voiceOf(extra)
  return Boolean(voice.ref_audio_url || voice.preset_id)
}

export function emotionLabel(id: string | null | undefined): string {
  const key = String(id || "").trim().toLowerCase()
  return INDEXTTS_EMOTIONS.find((item) => item.id === key)?.label || "平静"
}

export function isVoiceAudioFile(file: Pick<File, "name" | "type">): boolean {
  if (file.type.startsWith("audio/")) return true
  return /\.(wav|mp3|m4a|flac|ogg|aac)$/i.test(file.name)
}
