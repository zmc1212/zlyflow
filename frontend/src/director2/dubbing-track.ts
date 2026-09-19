import { emotionLabel } from "./voice-profile"

export const DUBBING_LINE_KINDS = ["spoken", "inner", "narration"] as const
export type DubbingLineKind = (typeof DUBBING_LINE_KINDS)[number]

export const DUBBING_LINE_STATUSES = ["idle", "queued", "running", "ready", "failed"] as const
export type DubbingLineStatus = (typeof DUBBING_LINE_STATUSES)[number]

export const DUBBING_MIX_MODES = ["overlay", "replace"] as const
export type DubbingMixMode = (typeof DUBBING_MIX_MODES)[number]

export type DubbingLine = {
  id: string
  beat_id: string
  seq: string
  character_id: string
  speaker: string
  text: string
  kind: DubbingLineKind | string
  emotion: string
  emo_alpha: number
  duration_factor: number
  mix: DubbingMixMode | string
  status: DubbingLineStatus | string
  audio_url: string
  duration_sec: number
  job_id: string
  error?: string
}

export type DubbingCharacterCard = {
  id: string
  name: string
  role: string
  voice_id: string
  bound: boolean
  voice: {
    preset_id?: string
    ref_audio_url?: string
    preview_url?: string
    default_emotion?: string
    emo_alpha?: number
    duration_factor?: number
  }
}

export type DubbingTrack = {
  episode_id: string
  project_id: string
  lines: DubbingLine[]
  characters: DubbingCharacterCard[]
  total: number
  ready: number
  unbound_count: number
  line?: DubbingLine
  skill_pack_id?: string
  requires_narration?: boolean
  compose_blocked?: boolean
  compose_block_reason?: string
  missing_narration?: Array<{ id: string; seq: string; text: string }>
}

export type DubbingGenerateResult = {
  job_id: string
  episode_id: string
  status: string
  line_ids: string[]
  duplicate?: boolean
}

export function lineKindLabel(kind: string | null | undefined): string {
  if (kind === "inner") return "内心"
  if (kind === "narration") return "旁白"
  return "开口"
}

export function lineStatusLabel(status: string | null | undefined): string {
  if (status === "queued") return "排队"
  if (status === "running") return "生成中"
  if (status === "ready") return "已就绪"
  if (status === "failed") return "失败"
  return "未生成"
}

export function lineMixLabel(mix: string | null | undefined): string {
  return mix === "replace" ? "替换片内对白" : "叠到成片"
}

export function lineEmotionLabel(emotion: string | null | undefined): string {
  return emotionLabel(emotion)
}

export function isActiveDubbingStatus(status: string | null | undefined): boolean {
  return status === "queued" || status === "running"
}

export function speakerColor(name: string): string {
  const text = String(name || "")
  let hash = 0
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) | 0
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue} 62% 42%)`
}

export function formatLineDuration(sec: number | null | undefined): string {
  const value = Number(sec || 0)
  if (!Number.isFinite(value) || value <= 0) return "—"
  return `${value.toFixed(value >= 10 ? 0 : 1)} 秒`
}

export function lineContributesTts(line: Pick<DubbingLine, "kind" | "mix" | "status" | "audio_url"> | null | undefined): boolean {
  if (!line || line.status !== "ready" || !String(line.audio_url || "").trim()) return false
  if (line.mix === "replace") return true
  return line.kind === "inner" || line.kind === "narration"
}

export function mixDirectorHint(kind: string | null | undefined, mix: string | null | undefined): string {
  const replace = mix === "replace"
  if (kind === "inner" || kind === "narration") {
    return replace
      ? "成片时静音该镜原声，只留这句内心/旁白。"
      : "内心/旁白会叠到成片，人物保持闭嘴。"
  }
  return replace
    ? "成片时静音该镜 H3 口型声，铺这句 TTS。"
    : "开口句默认保留 H3 口型声，不会叠这句 TTS。"
}

export const WORKSHOP_TAB_KEYS = ["shots", "script", "dubbing", "compose"] as const
export type WorkshopTabKey = (typeof WORKSHOP_TAB_KEYS)[number]

export function parseWorkshopTab(value: string | null | undefined): WorkshopTabKey | "" {
  return WORKSHOP_TAB_KEYS.includes(value as WorkshopTabKey) ? (value as WorkshopTabKey) : ""
}
