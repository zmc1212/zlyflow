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
export type RecipeAssetVersionStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"

export interface RecipeAssetVersion {
  id: string
  jobId?: string | null
  imageUrl?: string | null
  status: RecipeAssetVersionStatus
  promptSnapshot: string
  workflowId?: string | null
  options: Record<string, unknown>
  createdAt: string
  autoApprove?: boolean
}

export interface RecipeAssetRendition {
  versions: RecipeAssetVersion[]
  activeVersionId?: string | null
  approvedVersionId?: string | null
}

export interface RecipeCharacterIdentitySpec {
  ageRange: string
  regionalAppearance: string
  faceFeatures: string
  hair: string
  skinTone: string
  bodyBuild: string
  distinguishingMarks: string
  immutableAccessories: string
  avoidChanges: string
}

export interface RecipeCharacterLook {
  id: string
  name: string
  appearanceDetails: string
  promptText: string
  status: "draft" | "approved"
  sheet: RecipeAssetRendition
}

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
  role: string
  gender: RecipeGender
  type: RecipeCharacterType
  identitySpec: RecipeCharacterIdentitySpec
  specStatus: "draft" | "approved"
  aiAssumptions: string[]
  portrait: RecipeAssetRendition
  looks: RecipeCharacterLook[]
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
  plate: RecipeAssetRendition
  imageJobId?: string | null
  imageUrl?: string | null
  libraryAssetId?: string | null
}

export interface RecipeProp {
  id: string
  name: string
  description: string
  promptText: string
  turnaround: RecipeAssetRendition
  imageJobId?: string | null
  imageUrl?: string | null
  libraryAssetId?: string | null
}

export interface RecipeCharacterBinding {
  characterId: string
  lookId: string
}

export interface RecipeShot {
  id: string
  shotNumber: number
  title: string
  description: string
  promptText?: string
  dialogue: string
  characterNames: string[]
  characterBindings: RecipeCharacterBinding[]
  locationName: string
  locationId?: string | null
  propIds: string[]
  propNames: string[]
  assetBindingMode?: "legacy" | "stable"
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
  timingNote?: string
  /** English opening state compiled into the independent H3 clip. */
  continuityIn?: string
  /** English final-frame state compiled into the independent H3 clip. */
  continuityOut?: string
  /** Chinese cut note for the editor; not sent to H3. */
  transitionNote?: string
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
  assetSchemaVersion: 2
  script: RecipeScript
  artStyle: RecipeArtStyle | null
  characters: RecipeCharacter[]
  props: RecipeProp[]
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

export function emptyRecipeAssetRendition(): RecipeAssetRendition {
  return { versions: [] }
}

export function emptyRecipeIdentitySpec(): RecipeCharacterIdentitySpec {
  return {
    ageRange: "",
    regionalAppearance: "",
    faceFeatures: "",
    hair: "",
    skinTone: "",
    bodyBuild: "",
    distinguishingMarks: "",
    immutableAccessories: "",
    avoidChanges: "",
  }
}

export function ensureRecipeAssetRendition(rendition: RecipeAssetRendition | undefined | null): RecipeAssetRendition {
  return rendition && Array.isArray(rendition.versions) ? rendition : emptyRecipeAssetRendition()
}

function ensureCharacterLook(look: RecipeCharacterLook | undefined, index: number, character: RecipeCharacter): RecipeCharacterLook {
  const item = look || {
    id: index === 0 ? "look-default" : `look-${index + 1}`,
    name: index === 0 ? "基础造型" : `造型 ${index + 1}`,
    appearanceDetails: character.description || "",
    promptText: character.promptText || "",
    status: "draft" as const,
    sheet: emptyRecipeAssetRendition(),
  }
  return { ...item, sheet: ensureRecipeAssetRendition(item.sheet) }
}

export function ensureRecipeCharacter(character: RecipeCharacter): RecipeCharacter {
  const looks = character.looks?.length
    ? character.looks.map((look, index) => ensureCharacterLook(look, index, character))
    : [ensureCharacterLook(undefined, 0, character)]
  return {
    ...character,
    identitySpec: { ...emptyRecipeIdentitySpec(), ...(character.identitySpec || {}) },
    specStatus: character.specStatus === "approved" ? "approved" : "draft",
    aiAssumptions: character.aiAssumptions || [],
    portrait: ensureRecipeAssetRendition(character.portrait),
    looks,
  }
}

export function ensureRecipeLocation(location: RecipeLocation): RecipeLocation {
  return { ...location, plate: ensureRecipeAssetRendition(location.plate) }
}

export function ensureRecipeProp(prop: RecipeProp): RecipeProp {
  return { ...prop, turnaround: ensureRecipeAssetRendition(prop.turnaround) }
}

export function ensureRecipeAssetSchema(recipe: RecipeProject): RecipeProject {
  return {
    ...recipe,
    characters: (recipe.characters || []).map(ensureRecipeCharacter),
    locations: (recipe.locations || []).map(ensureRecipeLocation),
    props: (recipe.props || []).map(ensureRecipeProp),
  }
}

export function createEmptyRecipeCharacter(overrides: Partial<RecipeCharacter> = {}): RecipeCharacter {
  return ensureRecipeCharacter({
    id: "char-1",
    name: "角色",
    description: "",
    promptText: "",
    role: "",
    gender: "unspecified",
    type: "character",
    identitySpec: emptyRecipeIdentitySpec(),
    specStatus: "draft",
    aiAssumptions: [],
    portrait: emptyRecipeAssetRendition(),
    looks: [],
    ...overrides,
  })
}

export function createEmptyRecipeLocation(overrides: Partial<RecipeLocation> = {}): RecipeLocation {
  return ensureRecipeLocation({
    id: "loc-1",
    name: "场景",
    description: "",
    promptText: "",
    plate: emptyRecipeAssetRendition(),
    ...overrides,
  })
}

export function recipeRenditionVersion(
  rendition: RecipeAssetRendition | undefined,
  versionId: string | null | undefined,
): RecipeAssetVersion | undefined {
  if (!versionId) return undefined
  return rendition?.versions.find((version) => version.id === versionId)
}

export function recipeActiveAssetVersion(rendition: RecipeAssetRendition | undefined): RecipeAssetVersion | undefined {
  return recipeRenditionVersion(rendition, rendition?.activeVersionId)
}

export function recipeApprovedAssetVersion(rendition: RecipeAssetRendition | undefined): RecipeAssetVersion | undefined {
  return recipeRenditionVersion(rendition, rendition?.approvedVersionId)
}

export type RecipeAssetJobStatusSource = { id: string; status?: string }

export function recipeAssetVersionRuntimeStatus(
  version: RecipeAssetVersion | undefined,
  jobs?: RecipeAssetJobStatusSource[],
): string {
  if (!version) return "idle"
  const job = version.jobId ? jobs?.find((item) => item.id === version.jobId) : undefined
  return job?.status || version.status || "idle"
}

/** Latest succeeded candidate that is not yet the approved version. */
export function recipeApprovableAssetVersion(
  rendition: RecipeAssetRendition | undefined,
  jobs?: RecipeAssetJobStatusSource[],
): RecipeAssetVersion | undefined {
  if (!rendition?.versions?.length) return undefined

  const pick = (version: RecipeAssetVersion | undefined): RecipeAssetVersion | undefined => {
    if (!version || version.id === rendition.approvedVersionId) return undefined
    const status = recipeAssetVersionRuntimeStatus(version, jobs)
    if (status === "succeeded" && version.imageUrl) return version
    return undefined
  }

  const activePick = pick(recipeActiveAssetVersion(rendition))
  if (activePick) return activePick

  for (let index = rendition.versions.length - 1; index >= 0; index -= 1) {
    const candidate = pick(rendition.versions[index])
    if (candidate) return candidate
  }
  return undefined
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

export const FAILED_RECIPE_TAKE_STATUSES = new Set(["failed", "interrupted", "cancelled", "stopped"])

export function recipeShotTakeIsUsable(take: ShotTake | undefined): boolean {
  if (!take || FAILED_RECIPE_TAKE_STATUSES.has(take.status)) return false
  return Boolean(take.videoUrl || take.outputPath) || take.status === "succeeded"
}

export function recipeShotPreferredTake(shot: RecipeShot): ShotTake | undefined {
  const takes = shot.takes || []
  const approved = takes.find((take) => (take.id || take.jobId) === shot.approvedTakeId)
  if (recipeShotTakeIsUsable(approved)) return approved
  return [...takes].reverse().find(recipeShotTakeIsUsable)
}

export function shotIsMuxable(shot: RecipeShot): boolean {
  const take = recipeShotPreferredTake(shot)
  if (take) return true
  if (FAILED_RECIPE_TAKE_STATUSES.has(shot.status)) return false
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
