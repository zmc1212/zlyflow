import type {
  CameraDirection,
  CanvasTier,
  DirectorQuality,
  DirectorShot,
  DirectorSpeed,
  DirectorWeightProfile,
  ShotTake,
} from "./types"

export type DirectorPayloadKind = "timeline" | "director_recipe" | "batch_run"
export type RecipeAgentId =
  | "research"
  | "script"
  | "art_style"
  | "storyboard"
  | "characters"
  | "locations"
  | "voice"
  | "music"
  | "media"
export type RecipeAgentRunStatus = "pending" | "running" | "completed" | "failed"
export type RecipeCharacterType = "character" | "object"
export type RecipeGender = "" | "male" | "female" | "nonbinary" | "unspecified"

export interface RecipeScript {
  title: string
  summary: string
  fullStory: string
}

export interface RecipeArtStyle {
  id: string
  name: string
  name_en?: string
  promptPrefix: string
  imageUrl?: string | null
}

export interface RecipeCharacter {
  id: string
  name: string
  description: string
  promptText: string
  gender: RecipeGender
  type: RecipeCharacterType
  imageJobId?: string | null
  imageUrl?: string | null
  libraryAssetId?: string | null
  voiceId?: string | null
  voicePreviewUrl?: string | null
}

export interface RecipeLocation {
  id: string
  name: string
  description: string
  promptText: string
  imageJobId?: string | null
  imageUrl?: string | null
  libraryAssetId?: string | null
}

export interface RecipeShot {
  id: string
  shotNumber: number
  title: string
  description: string
  promptText?: string
  dialogue: string
  characterNames: string[]
  locationName: string
  durationSec: number
  compiledPrompt: string
  jobId?: string | null
  status: DirectorShot["status"]
  outputVideoUrl?: string | null
  outputPath?: string | null
  progress?: number
  takes: ShotTake[]
  camera?: CameraDirection
  soundscape?: string
  soundscapeEn?: string
  error?: string | null
  firstFrameUrl?: string | null
  firstFramePath?: string | null
  firstFrameJobId?: string | null
  endFrameUrl?: string | null
  endFramePath?: string | null
  endFrameJobId?: string | null
  stillUrl?: string | null
  stillJobId?: string | null
  stillStatus?: DirectorShot["status"] | null
  usePreviousEndFrame?: boolean
  approvedTakeId?: string | null
  activeTakeIndex?: number
  speakerName?: string | null
  voiceId?: string | null
  ttsStatus?: DirectorShot["status"] | "idle"
  ttsUrl?: string | null
  ttsPath?: string | null
  ttsError?: string | null
}

export interface RecipeScene {
  id: string
  sceneNumber: number
  title: string
  description: string
  locationName: string
  shots: RecipeShot[]
}

export interface RecipeAgentStatus {
  id: RecipeAgentId
  status: RecipeAgentRunStatus
  error?: string | null
  message?: string | null
}

export interface RecipePipelineRun {
  agents: RecipeAgentId[]
  active: boolean
}

export interface RecipeAudioMix {
  bgmUrl?: string | null
  bgmPath?: string | null
  bgmVolume: number
  bgmFadeInSec: number
  bgmFadeOutSec: number
}

export interface RecipeSubtitleStyle {
  enabled: boolean
  position: "top" | "center" | "bottom"
  fontSize: number
  strokeWidth: number
  textColor: string
  strokeColor: string
}

export interface RecipeExportState {
  muxStatus: "idle" | "queued" | "running" | "succeeded" | "failed"
  muxUrl?: string | null
  muxPath?: string | null
  muxDurationSec?: number | null
  muxError?: string | null
  muxAt?: string | null
  burnSubtitles?: boolean
}

export interface RecipeProject {
  kind: "director_recipe"
  script: RecipeScript
  artStyle: RecipeArtStyle | null
  characters: RecipeCharacter[]
  locations: RecipeLocation[]
  scenes: RecipeScene[]
  agentStatus: RecipeAgentStatus[]
  pipelineRun?: RecipePipelineRun
  globalMusic: string
  globalSoundscape: string
  aspectRatio: string
  canvasTier: CanvasTier
  previewQuality: DirectorQuality
  previewSpeed: DirectorSpeed
  finalQuality: DirectorQuality
  finalSpeed: DirectorSpeed
  weightProfile: DirectorWeightProfile
  videoWorkflowFamily: string
  width: number
  height: number
  fps: number
  refsMode: "refs_off" | "refs_on"
  manualPromptOverrideEnabled: boolean
  manualPromptOverrideText: string
  audio?: RecipeAudioMix
  subtitles?: RecipeSubtitleStyle
  export?: RecipeExportState
}

export interface BatchRunItem {
  id: string
  title: string
  description?: string
  script: string
  jobId?: string | null
  status: DirectorShot["status"]
  outputVideoUrl?: string | null
  error?: string | null
}

export interface BatchRunPayload {
  kind: "batch_run"
  theme: string
  count: number
  aspectRatio: string
  durationSec: number
  artStyle: RecipeArtStyle | null
  items: BatchRunItem[]
  agentStatus?: RecipeAgentStatus[]
  videoWorkflowFamily?: string
  weightProfile?: DirectorWeightProfile
}

export interface DirectorArtStyleCategory {
  id: string
  name_zh: string
  name_en: string
}

export interface DirectorArtStyle {
  id: string
  name_zh: string
  name_en: string
  category: string
  category_name_zh: string
  category_name_en: string
  description: string
  promptPrefix: string
  imageUrl?: string | null
  keywords: string[]
}

export interface DirectorArtStyleCatalog {
  categories: DirectorArtStyleCategory[]
  styles: DirectorArtStyle[]
  count: number
}

export const TTS_VOICE_OPTIONS = [
  { id: "alloy", label: "Alloy（中性）" },
  { id: "echo", label: "Echo（男声）" },
  { id: "fable", label: "Fable（叙事）" },
  { id: "onyx", label: "Onyx（低沉男声）" },
  { id: "nova", label: "Nova（女声）" },
  { id: "shimmer", label: "Shimmer（柔和女声）" },
] as const

export function defaultRecipeAudio(): RecipeAudioMix {
  return { bgmUrl: null, bgmVolume: 0.25, bgmFadeInSec: 1, bgmFadeOutSec: 2 }
}

export function defaultRecipeSubtitles(): RecipeSubtitleStyle {
  return {
    enabled: false,
    position: "bottom",
    fontSize: 28,
    strokeWidth: 2,
    textColor: "#ffffff",
    strokeColor: "#000000",
  }
}

export function defaultRecipeExport(): RecipeExportState {
  return { muxStatus: "idle", muxUrl: null, muxDurationSec: null, muxError: null, muxAt: null, burnSubtitles: false }
}

export function recipeAudio(recipe: RecipeProject): RecipeAudioMix {
  return { ...defaultRecipeAudio(), ...recipe.audio }
}

export function recipeSubtitles(recipe: RecipeProject): RecipeSubtitleStyle {
  return { ...defaultRecipeSubtitles(), ...recipe.subtitles }
}

export function recipeExportState(recipe: RecipeProject): RecipeExportState {
  return { ...defaultRecipeExport(), ...recipe.export }
}

function activeTake(shot: RecipeShot) {
  const takes = shot.takes || []
  const approved = takes.find((take) => (take.id || take.jobId) === shot.approvedTakeId)
  return approved || takes[shot.activeTakeIndex || 0] || takes[takes.length - 1]
}

export function shotIsMuxable(shot: RecipeShot): boolean {
  const failed = new Set(["failed", "interrupted", "cancelled", "stopped"])
  if (failed.has(shot.status)) return false
  const take = activeTake(shot)
  if (take) return !failed.has(take.status) && (Boolean(take.videoUrl) || take.status === "succeeded")
  return shot.status === "succeeded" && Boolean(shot.outputVideoUrl || shot.jobId)
}

export function artStylePreviewUrl(style: { id: string; imageUrl?: string | null }): string {
  const url = (style.imageUrl || "").trim()
  if (url.startsWith("/api/director/art-styles/") && url.endsWith("/preview")) return url
  return `/api/director/art-styles/${encodeURIComponent(style.id)}/preview`
}

export function recipeArtStyleFromCatalog(style: DirectorArtStyle): RecipeArtStyle {
  return {
    id: style.id,
    name: style.name_zh,
    name_en: style.name_en,
    promptPrefix: style.promptPrefix,
    imageUrl: artStylePreviewUrl(style),
  }
}

export function isRecipePayload(payload: unknown): payload is RecipeProject {
  return Boolean(payload && typeof payload === "object" && (payload as { kind?: string }).kind === "director_recipe")
}

export function isBatchRunPayload(payload: unknown): payload is BatchRunPayload {
  return Boolean(payload && typeof payload === "object" && (payload as { kind?: string }).kind === "batch_run")
}

export function flattenRecipeShots(recipe: RecipeProject): RecipeShot[] {
  return (recipe.scenes || []).flatMap((scene) => scene.shots || [])
}

export function isPlaceholderRecipeBoard(items: RecipeShot[], goal: string, fullStory: string): boolean {
  if (!items.length) return true
  if (items.length > 1) return false
  const shot = items[0]
  const description = (shot.description || "").trim()
  const prompt = (shot.promptText || "").trim()
  const idea = goal.trim()
  const story = fullStory.trim()
  const titleIsDummy = !shot.title || shot.title === "主镜头" || shot.title === "开场"
  const descriptionIsIdea = !description || description === idea || description === story
  const noPrompt = !prompt || prompt === description || prompt === idea
  return titleIsDummy && descriptionIsIdea && noPrompt
}
