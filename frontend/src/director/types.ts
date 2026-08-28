export type CameraScale = "ELS" | "WS" | "MS" | "CU" | "ECU"
export type CameraMovement =
  | "zoom_in"
  | "zoom_out"
  | "pan_left"
  | "pan_right"
  | "tilt_up"
  | "tilt_down"
  | "orbit"
  | "tracking"
  | "static"

export type CameraAngle = "eye_level" | "low_angle" | "high_angle" | "dutch" | "pov"
export type CameraSpeed = "smooth" | "dynamic" | "slow"
export type CameraLighting = "cinematic_soft" | "cyberpunk" | "golden_hour" | "dramatic_low_key" | "studio"

export interface CameraDirection {
  scale: CameraScale
  movement: CameraMovement
  angle: CameraAngle
  speed: CameraSpeed
  lighting: CameraLighting
  sfx: string
}

export type SubjectSlotKind = "character" | "scene" | "prop" | "style" | "action"
export type SubjectSlotRetention = "fully_preserved" | "strong" | "weak"

export interface SubjectSlot {
  id: string // e.g. "@ref1" ... "@ref9"
  slotIndex: number // 1..9
  name: string
  kind: SubjectSlotKind
  retention: SubjectSlotRetention
  description: string
  file?: File
  previewUrl?: string
  analyzing?: boolean
}

// 兼容旧接口
export interface CastAsset {
  id: string
  name: string
  pictureIndex: number
  preview: string
  file?: File
}

export interface ShotTake {
  id: string
  takeNumber: number
  jobId?: string
  videoUrl?: string
  coverUrl?: string
  outputPath?: string
  status: "idle" | "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"
  progress: number
  error?: string
  createdAt: string
  promptSnapshot?: string
  renderPass?: "preview" | "final"
}

export interface DirectorShot {
  id: string
  shotNumber: number
  title: string
  startSec: number
  durationSec: number
  prompt: string
  dialogue?: string
  soundscape?: string
  camera: CameraDirection
  firstFrameUrl?: string
  firstFrameFile?: File
  endFrameUrl?: string
  endFrameFile?: File
  usePreviousEndFrame?: boolean
  referencedSubjectIds: string[]
  referencedCastIds?: string[]
  takes: ShotTake[]
  activeTakeIndex: number
  jobId?: string
  status: "idle" | "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"
  progress: number
  outputVideoUrl?: string
  outputPath?: string
  error?: string
  retakeCount: number
}

export type CanvasTier = "native" | "fast" | "past_native" | "custom_mp"
export type DirectorQuality = "0.4" | "0.7" | "1.0" | "2.0"
export type DirectorSpeed = "fast" | "balanced" | "quality"
export type DirectorWeightProfile = "full" | "pruned"

export interface CanvasPreset {
  ratio: string
  tier: CanvasTier
  label: string
  width: number
  height: number
  mp: number
}

export interface TimelineProject {
  id: string
  title: string
  summary?: string
  sourceScript?: string
  styleVibe?: string
  requestedShotCount?: number
  aspectRatio: string
  canvasTier: CanvasTier
  previewQuality: DirectorQuality
  previewSpeed: DirectorSpeed
  finalQuality: DirectorQuality
  finalSpeed: DirectorSpeed
  weightProfile?: DirectorWeightProfile
  videoWorkflowFamily?: string
  width: number
  height: number
  fps: number
  refsMode: "refs_off" | "refs_on"
  globalSoundscape: string
  globalMusic: string
  subjectSlots: SubjectSlot[]
  globalCast?: CastAsset[]
  duration?: number
  shots: DirectorShot[]
  manualPromptOverrideEnabled: boolean
  manualPromptOverrideText: string
  createdAt: string
  updatedAt: string
}

export type DirectorProject = TimelineProject

export const SUBJECT_KIND_LABELS: Record<SubjectSlotKind, { label: string; desc: string }> = {
  character: { label: "人物主角 (Character)", desc: "角色外貌、服饰、面部五官" },
  scene: { label: "场景环境 (Scene)", desc: "地理空间、室内外建筑与氛围" },
  prop: { label: "道具物件 (Prop)", desc: "关键载具、武器、特定物品" },
  style: { label: "艺术风格 (Style)", desc: "特定画风、渲染材质、调色质感" },
  action: { label: "动作姿态 (Action)", desc: "特定动作轨迹与体态表达" },
}

export const SUBJECT_RETENTION_LABELS: Record<SubjectSlotRetention, { label: string; desc: string }> = {
  fully_preserved: { label: "完全保留 (100%)", desc: "严格继承面容与细节特征" },
  strong: { label: "强参考 (80%)", desc: "高度贴合主体特征，允许轻微动态变形" },
  weak: { label: "弱参考 (50%)", desc: "仅参考构图/轮廓/概念" },
}

export const CAMERA_SCALE_LABELS: Record<CameraScale, { label: string; desc: string }> = {
  ELS: { label: "大远景 (ELS)", desc: "展示宏大地理环境与世界观" },
  WS: { label: "全景 (WS)", desc: "展示完整人物身段与周围空间" },
  MS: { label: "中景 (MS)", desc: "半身构图，突出人物动作与对话" },
  CU: { label: "特写 (CU)", desc: "面部或关键物体细节，情绪传达" },
  ECU: { label: "大特写 (ECU)", desc: "眼睛、微表情或局部微观细节" },
}

export const CAMERA_MOVEMENT_LABELS: Record<CameraMovement, { label: string; desc: string }> = {
  zoom_in: { label: "前推 (Push In)", desc: "镜头平稳缓慢向前推进聚焦" },
  zoom_out: { label: "后拉 (Pull Out)", desc: "镜头由局部后拉展现广阔全貌" },
  pan_left: { label: "左移 (Pan Left)", desc: "镜头向左平移扫视" },
  pan_right: { label: "右移 (Pan Right)", desc: "镜头向右平移扫视" },
  tilt_up: { label: "仰拍运镜 (Tilt Up)", desc: "镜头由低向高扬起，展现气势" },
  tilt_down: { label: "俯拍运镜 (Tilt Down)", desc: "镜头由高向低俯瞰降落" },
  orbit: { label: "环绕旋转 (Orbit)", desc: "围绕主体 360 度圆弧旋转拍摄" },
  tracking: { label: "跟拍跟随 (Tracking)", desc: "平稳跟随主体运动移动" },
  static: { label: "定焦静止 (Static)", desc: "固定机位，专注主体内部动态" },
}

export const CAMERA_ANGLE_LABELS: Record<CameraAngle, { label: string; desc: string }> = {
  eye_level: { label: "平视视平线", desc: "自然真实客观视角" },
  low_angle: { label: "低机位仰角", desc: "强化主体威严与压迫感" },
  high_angle: { label: "高机位俯视", desc: "上帝视角，突出渺小或全局" },
  dutch: { label: "倾斜荷兰角", desc: "画面倾斜，营造紧张悬疑感" },
  pov: { label: "第一人称主观", desc: "身临其境的主观视角" },
}

export const CAMERA_SPEED_LABELS: Record<CameraSpeed, { label: string; desc: string }> = {
  smooth: { label: "平稳电影感", desc: "专业滑轨/斯坦尼康平稳运镜" },
  dynamic: { label: "激烈快动态", desc: "动作紧凑，张力强" },
  slow: { label: "柔和微动", desc: "细腻沉浸，呼吸感微动" },
}

export const CAMERA_LIGHTING_LABELS: Record<CameraLighting, { label: string; desc: string }> = {
  cinematic_soft: { label: "电影级柔光", desc: "自然漫反射，高空间层次感" },
  cyberpunk: { label: "赛博霓虹", desc: "高饱和冷暖对比，科幻质感" },
  golden_hour: { label: "黄金时段逆光", desc: "日落暖金轮廓光，温暖通透" },
  dramatic_low_key: { label: "低调戏剧性", desc: "暗调高反差，悬疑神秘" },
  studio: { label: "纯净影棚布光", desc: "商业广告级通透高光" },
}

export const H3_CANVAS_PRESETS: CanvasPreset[] = [
  // Native tier (768px 短边基准)
  { ratio: "21:9", tier: "native", label: "21:9 宽银幕 (1344×576)", width: 1344, height: 576, mp: 0.77 },
  { ratio: "16:9", tier: "native", label: "16:9 标清电影 (1344×768)", width: 1344, height: 768, mp: 1.03 },
  { ratio: "4:3", tier: "native", label: "4:3 复古全景 (1024×768)", width: 1024, height: 768, mp: 0.79 },
  { ratio: "1:1", tier: "native", label: "1:1 正方形 (992×992)", width: 992, height: 992, mp: 0.98 },
  { ratio: "3:4", tier: "native", label: "3:4 社交人像 (768×1024)", width: 768, height: 1024, mp: 0.79 },
  { ratio: "9:16", tier: "native", label: "9:16 竖屏短剧 (768×1344)", width: 768, height: 1344, mp: 1.03 },
  // Fast tier (480px 快速测试)
  { ratio: "16:9", tier: "fast", label: "16:9 极速预览 (864×480)", width: 864, height: 480, mp: 0.41 },
  { ratio: "9:16", tier: "fast", label: "9:16 极速竖屏 (480×864)", width: 480, height: 864, mp: 0.41 },
  { ratio: "1:1", tier: "fast", label: "1:1 极速正方 (640×640)", width: 640, height: 640, mp: 0.41 },
  // Past native
  { ratio: "16:9", tier: "past_native", label: "16:9 高清电影 (1920×1088 - Past Native)", width: 1920, height: 1088, mp: 2.09 },
  { ratio: "9:16", tier: "past_native", label: "9:16 高清竖屏 (1088×1920 - Past Native)", width: 1088, height: 1920, mp: 2.09 },
]

export const DIRECTOR_FINAL_CANVAS_OPTIONS: Array<{ tier: CanvasTier; quality: DirectorQuality; label: string }> = [
  { tier: "fast", quality: "0.4", label: "0.4 MP（16GB 推荐）" },
  { tier: "native", quality: "1.0", label: "1.0 MP（成片）" },
  { tier: "past_native", quality: "2.0", label: "2.0 MP（高清）" },
]

export const DIRECTOR_QUALITY_OPTIONS: Array<{ value: DirectorQuality; label: string }> = [
  { value: "0.4", label: "0.4 MP" },
  { value: "0.7", label: "0.7 MP" },
  { value: "1.0", label: "1.0 MP" },
  { value: "2.0", label: "2.0 MP" },
]

export const DIRECTOR_SPEED_OPTIONS: Array<{ value: DirectorSpeed; label: string; steps: number }> = [
  { value: "fast", label: "快速（4 步）", steps: 4 },
  { value: "balanced", label: "均衡（8 步）", steps: 8 },
  { value: "quality", label: "高质量（20 步）", steps: 20 },
]

export const DIRECTOR_WEIGHT_OPTIONS: Array<{ value: DirectorWeightProfile; label: string }> = [
  { value: "full", label: "完整（32 GB）" },
  { value: "pruned", label: "精简（20 GB）" },
]

export function canvasTierForQuality(quality: DirectorQuality | string | undefined): CanvasTier {
  if (quality === "0.4") return "fast"
  if (quality === "2.0") return "past_native"
  return "native"
}

export function applyCanvasTier(project: TimelineProject, tier: CanvasTier): TimelineProject {
  const preset = H3_CANVAS_PRESETS.find((item) => item.ratio === project.aspectRatio && item.tier === tier)
  return {
    ...project,
    canvasTier: tier,
    ...(preset ? { width: preset.width, height: preset.height } : {}),
  }
}

export function applyDirectorFinalQuality(project: TimelineProject, quality: DirectorQuality): TimelineProject {
  return applyCanvasTier({ ...project, finalQuality: quality }, canvasTierForQuality(quality))
}

export function recipeCanvasPreset(
  recipe: Pick<RecipeProject, "aspectRatio" | "finalQuality" | "canvasTier">,
): CanvasPreset | undefined {
  const tier = canvasTierForQuality(recipe.finalQuality) || recipe.canvasTier
  return H3_CANVAS_PRESETS.find((item) => item.ratio === recipe.aspectRatio && item.tier === tier)
}

export function applyRecipeOutputSettings(
  recipe: RecipeProject,
  patch: Partial<Pick<RecipeProject, "aspectRatio" | "finalQuality" | "finalSpeed" | "weightProfile" | "videoWorkflowFamily">>,
): RecipeProject {
  const next = { ...recipe, ...patch }
  const tier = canvasTierForQuality(next.finalQuality)
  const preset = recipeCanvasPreset(next) || H3_CANVAS_PRESETS.find((item) => item.ratio === next.aspectRatio && item.tier === "native")
  return {
    ...next,
    canvasTier: tier,
    ...(preset ? { width: preset.width, height: preset.height } : {}),
  }
}

export function defaultCameraDirection(): CameraDirection {
  return {
    scale: "MS",
    movement: "zoom_in",
    angle: "eye_level",
    speed: "smooth",
    lighting: "cinematic_soft",
    sfx: "",
  }
}

export function createInitialSubjectSlots(): SubjectSlot[] {
  return Array.from({ length: 9 }, (_, index) => ({
    id: `@ref${index + 1}`,
    slotIndex: index + 1,
    name: `主体 ${index + 1}`,
    kind: index === 0 ? "character" : index === 1 ? "scene" : "prop",
    retention: "fully_preserved",
    description: "",
  }))
}

export function createEmptyShot(shotNumber: number, startSec: number = 0, durationSec: number = 5): DirectorShot {
  return {
    id: `shot-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    shotNumber,
    title: `分镜 ${shotNumber}`,
    startSec,
    durationSec,
    prompt: "",
    dialogue: "",
    soundscape: "",
    camera: defaultCameraDirection(),
    referencedSubjectIds: [],
    takes: [],
    activeTakeIndex: 0,
    status: "idle",
    progress: 0,
    retakeCount: 0,
  }
}

export function createEmptyProject(title: string = "未命名分镜工程"): TimelineProject {
  const shot1 = createEmptyShot(1, 0, 5)
  return {
    id: `proj-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    title,
    summary: "",
    sourceScript: "",
    styleVibe: undefined,
    requestedShotCount: undefined,
    aspectRatio: "16:9",
    canvasTier: "native",
    previewQuality: "0.4",
    previewSpeed: "fast",
    finalQuality: "1.0",
    finalSpeed: "balanced",
    weightProfile: "full",
    videoWorkflowFamily: "official_h3",
    width: 1344,
    height: 768,
    fps: 24,
    refsMode: "refs_on",
    globalSoundscape: "电影级空间环境声",
    globalMusic: "",
    subjectSlots: createInitialSubjectSlots(),
    shots: [shot1],
    manualPromptOverrideEnabled: false,
    manualPromptOverrideText: "",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
}

export function createInitialProject(title: string = "新导演工程"): TimelineProject {
  return createEmptyProject(title)
}

export function projectHasGeneratedTakes(project: TimelineProject): boolean {
  return (project.shots || []).some((shot) => {
    if (shot.outputVideoUrl || shot.status === "succeeded") return true
    return (shot.takes || []).some((take) => take.status === "succeeded" || Boolean(take.videoUrl))
  })
}

const H3_SCALE_PHRASES: Record<CameraScale, string> = {
  ELS: "an extreme long shot",
  WS: "a wide shot",
  MS: "a medium shot",
  CU: "a close-up",
  ECU: "an extreme close-up",
}
const H3_ANGLE_PHRASES: Record<CameraAngle, string> = {
  eye_level: "eye-level",
  low_angle: "low-angle",
  high_angle: "high-angle",
  dutch: "dutch-angle",
  pov: "POV",
}
const H3_LIGHTING_PHRASES: Record<CameraLighting, string> = {
  cinematic_soft: "soft cinematic lighting",
  cyberpunk: "neon cyberpunk lighting",
  golden_hour: "golden-hour backlight",
  dramatic_low_key: "dramatic low-key lighting",
  studio: "clean studio lighting",
}
const H3_CAMERA_ACTIONS: Record<CameraMovement, string> = {
  zoom_in: "pushes in",
  zoom_out: "pulls out",
  pan_left: "pans left",
  pan_right: "pans right",
  tilt_up: "tilts up",
  tilt_down: "tilts down",
  orbit: "moves in an arc shot around the subject",
  tracking: "follows with a tracking shot",
  static: "holds a static shot",
}

function hasCjk(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text)
}

export function userFacingCopy(...candidates: Array<string | null | undefined>): string {
  const texts = candidates.map((item) => (item || "").trim()).filter(Boolean)
  return texts.find((item) => hasCjk(item)) || texts[0] || ""
}

function hasCameraProse(text: string): boolean {
  const lowered = text.toLowerCase()
  return lowered.includes("the camera") || lowered.includes("a static shot") || lowered.includes("tracking shot")
}

function hasScaleProse(text: string): boolean {
  const lowered = text.toLowerCase()
  return ["extreme long shot", "wide shot", "medium-wide", "medium shot", "close-up", "extreme close-up", "close up", "establishing shot"]
    .some((marker) => lowered.includes(marker))
}

export function h3CameraSentence(camera: CameraDirection): string {
  const movement = camera.movement || "zoom_in"
  const action = H3_CAMERA_ACTIONS[movement] || H3_CAMERA_ACTIONS.zoom_in
  if (movement === "static") return "The camera holds a static shot."
  const amplitude = camera.speed === "dynamic" ? "with large amplitude" : "with small amplitude"
  const tempo = camera.speed === "dynamic" ? "at fast speed" : "at slow speed"
  return `The camera ${action} ${amplitude} ${tempo}.`
}

export function buildFormattedShotPrompt(shot: DirectorShot): string {
  let visual = (shot.prompt || "").trim()
  const camera = shot.camera || defaultCameraDirection()
  if (visual && !hasScaleProse(visual)) {
    visual = `${H3_SCALE_PHRASES[camera.scale] || H3_SCALE_PHRASES.MS} at ${H3_ANGLE_PHRASES[camera.angle] || H3_ANGLE_PHRASES.eye_level} frames the scene. ${visual}`.trim()
  }
  if (visual && !hasCameraProse(visual)) {
    visual = `${visual.replace(/[. ]+$/, "")}. ${h3CameraSentence(camera)}`.trim()
  }
  const lighting = H3_LIGHTING_PHRASES[camera.lighting]
  if (lighting && !visual.toLowerCase().includes(lighting.toLowerCase())) {
    visual = `${visual.replace(/[. ]+$/, "")}. ${lighting.charAt(0).toUpperCase()}${lighting.slice(1)}.`
  }
  const dialogue = shot.dialogue?.trim()
  if (dialogue && !visual.includes("<d>")) {
    const tag = hasCjk(dialogue) ? "Chinese" : "English"
    visual = `${visual.replace(/[. ]+$/, "")}. the on-screen speaker (S1) says: <d>[${tag}] ${dialogue}</d>`
  }
  return visual.trim()
}

export interface CompiledPromptInfo {
  rawPrompt: string
  wordCount: number
  totalDurationSec: number
  totalFrames: number
  referenceTally: {
    images: number
    videos: number
    audios: number
    total: number
  }
  warnings: string[]
  isWithinTargetWordCount: boolean
}

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
  progress?: number
  takes: ShotTake[]
  camera?: CameraDirection
  soundscape?: string
  soundscapeEn?: string
  error?: string | null
  firstFrameUrl?: string | null
  firstFrameJobId?: string | null
  endFrameUrl?: string | null
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
  muxDurationSec?: number | null
  muxError?: string | null
  muxAt?: string | null
  burnSubtitles?: boolean
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

const MUX_FAILED_STATUSES = new Set(["failed", "interrupted", "cancelled", "stopped"])

export function shotIsMuxable(shot: RecipeShot): boolean {
  if (MUX_FAILED_STATUSES.has(shot.status)) return false
  const takes = shot.takes || []
  const approved = takes.find((take) => (take.id || take.jobId) === shot.approvedTakeId)
  const take = approved || takes[shot.activeTakeIndex || 0] || takes[takes.length - 1]
  if (take) {
    if (MUX_FAILED_STATUSES.has(take.status)) return false
    return Boolean(take.videoUrl) || take.status === "succeeded"
  }
  return shot.status === "succeeded" && Boolean(shot.outputVideoUrl || shot.jobId)
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

export function artStylePreviewUrl(style: { id: string; imageUrl?: string | null }): string {
  const url = (style.imageUrl || "").trim()
  if (url.startsWith("/api/director/art-styles/") && url.endsWith("/preview")) {
    return url
  }
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

export function isPlaceholderRecipeBoard(shots: RecipeShot[], goal: string, fullStory: string): boolean {
  if (!shots.length) return true
  if (shots.length > 1) return false
  const shot = shots[0]
  const description = (shot.description || "").trim()
  const prompt = (shot.promptText || "").trim()
  const idea = goal.trim()
  const story = fullStory.trim()
  const titleIsDummy = !shot.title || shot.title === "主镜头" || shot.title === "开场"
  const descriptionIsIdea = !description || description === idea || description === story
  const noPrompt = !prompt || prompt === description || prompt === idea
  return titleIsDummy && descriptionIsIdea && noPrompt
}

export const FEATURED_ART_STYLE_CATEGORIES = [
  "cinematic", "commercial", "anime", "3d", "illustration", "realistic",
] as const

export function featuredArtStyles(styles: DirectorArtStyle[]): DirectorArtStyle[] {
  const picked: DirectorArtStyle[] = []
  for (const category of FEATURED_ART_STYLE_CATEGORIES) {
    const first = styles.find((item) => item.category === category)
    if (first) picked.push(first)
  }
  return picked
}

export function recipePackedPlates(recipe: RecipeProject, shot: RecipeShot): Array<{
  name: string
  kind: "character" | "location"
  imageUrl?: string | null
}> {
  const named = new Set((shot.characterNames || []).map((name) => name.trim()).filter(Boolean))
  let characters = recipe.characters.filter((item) => item.imageUrl || item.imageJobId)
  if (named.size) {
    characters = characters.filter((item) => named.has(item.name))
  }
  let locations = recipe.locations.filter((item) => item.imageUrl || item.imageJobId)
  if (shot.locationName.trim()) {
    const matched = locations.filter((item) => item.name === shot.locationName)
    if (matched.length) locations = matched
  }
  return [
    ...characters.map((item) => ({ name: item.name, kind: "character" as const, imageUrl: item.imageUrl })),
    ...locations.map((item) => ({ name: item.name, kind: "location" as const, imageUrl: item.imageUrl })),
  ].slice(0, 9)
}

export const RECIPE_AGENT_LABELS: Record<RecipeAgentId, string> = {
  research: "研究",
  script: "脚本",
  art_style: "美术风格",
  storyboard: "分镜",
  characters: "角色",
  locations: "场景",
  voice: "配音",
  music: "配乐",
  media: "媒体",
}

export const RECIPE_AGENT_ORDER: RecipeAgentId[] = [
  "research", "script", "art_style", "storyboard", "characters", "locations", "voice", "music", "media",
]

export const RECIPE_AGENT_RUNNING_MESSAGES: Record<RecipeAgentId, string> = {
  research: "正在核对故事设定",
  script: "正在根据创意写剧本",
  art_style: "正在选择美术风格",
  storyboard: "正在读剧本",
  characters: "正在从分镜抽出人物",
  locations: "正在从分镜抽出场景",
  voice: "正在配置配音",
  music: "正在配置配乐",
  media: "正在编译出片参数",
}

export function estimateStoryboardSkeletonCount(story: string, goal: string = ""): number {
  const text = (story || goal || "").trim()
  const sceneMarks = text.match(/第[一二三四五六七八九十百\d]+场/g)
  if (sceneMarks?.length) {
    return Math.min(24, Math.max(8, sceneMarks.length * 2))
  }
  if (text.length < 80) return 8
  return Math.min(24, Math.max(8, Math.round(text.length / 90)))
}

export function recipePipelineProgress(
  agentStatus: RecipeAgentStatus[],
  pipelineRun: RecipePipelineRun | undefined,
  agentOrder: RecipeAgentId[] = RECIPE_AGENT_ORDER,
): {
  percent: number
  runningId: RecipeAgentId | null
  completed: number
  total: number
  stage: string | null
  subset: boolean
} {
  const runAgents = pipelineRun?.active && pipelineRun.agents.length ? pipelineRun.agents : agentOrder
  const subset = Boolean(pipelineRun?.active && pipelineRun.agents.length && pipelineRun.agents.length < agentOrder.length)
  const statuses = runAgents.map((id) => agentStatus.find((item) => item.id === id))
  const completed = statuses.filter((item) => item?.status === "completed").length
  const running = statuses.find((item) => item?.status === "running")
  const total = runAgents.length || agentOrder.length
  const runningId = running?.id || null
  return {
    percent: Math.round(((completed + (runningId ? 0.5 : 0)) / total) * 100),
    runningId,
    completed: pipelineRun?.active ? completed : agentStatus.filter((item) => item.status === "completed").length,
    total: pipelineRun?.active ? total : agentOrder.length,
    stage: running?.message || null,
    subset,
  }
}

export function createEmptyBatch(theme: string = ""): BatchRunPayload {
  return {
    kind: "batch_run",
    theme,
    count: 3,
    aspectRatio: "9:16",
    durationSec: 8,
    artStyle: null,
    items: [],
    videoWorkflowFamily: "official_h3",
    weightProfile: "full",
  }
}

export function recipeShotsToPlayer(shots: RecipeShot[]): DirectorShot[] {
  return shots.map((shot, index) => ({
    id: shot.id,
    shotNumber: shot.shotNumber || index + 1,
    title: shot.title,
    startSec: 0,
    durationSec: shot.durationSec,
    prompt: userFacingCopy(shot.description, shot.title),
    dialogue: shot.dialogue,
    camera: shot.camera || defaultCameraDirection(),
    referencedSubjectIds: [],
    takes: shot.takes || [],
    activeTakeIndex: shot.activeTakeIndex || 0,
    jobId: shot.jobId || undefined,
    status: shot.status,
    progress: shot.progress || 0,
    outputVideoUrl: shot.outputVideoUrl || undefined,
    firstFrameUrl: shot.firstFrameUrl || undefined,
    endFrameUrl: shot.endFrameUrl || undefined,
    usePreviousEndFrame: shot.usePreviousEndFrame,
    retakeCount: shot.takes?.length || 0,
  }))
}

export interface DirectorLibraryAsset {
  id: string
  kind: "character" | "scene" | "prop"
  name: string
  description: string
  promptText: string
  gender: string
  imageUrl?: string | null
  imageJobId?: string | null
  sourceProjectId?: string | null
  created_at: string
  updated_at: string
}

export const DIRECTOR_LIBRARY_KIND_LABELS: Record<DirectorLibraryAsset["kind"], string> = {
  character: "人物",
  scene: "场景",
  prop: "道具",
}

export function createEmptyRecipe(title: string = ""): RecipeProject {
  return {
    kind: "director_recipe",
    script: { title, summary: "", fullStory: "" },
    artStyle: null,
    characters: [],
    locations: [],
    scenes: [],
    agentStatus: [
      { id: "research", status: "pending", error: null, message: null },
      { id: "script", status: "pending", error: null, message: null },
      { id: "art_style", status: "pending", error: null, message: null },
      { id: "storyboard", status: "pending", error: null, message: null },
      { id: "characters", status: "pending", error: null, message: null },
      { id: "locations", status: "pending", error: null, message: null },
      { id: "voice", status: "pending", error: null, message: null },
      { id: "music", status: "pending", error: null, message: null },
      { id: "media", status: "pending", error: null, message: null },
    ],
    pipelineRun: { agents: [], active: false },
    globalMusic: "",
    globalSoundscape: "电影级空间环境声",
    aspectRatio: "16:9",
    canvasTier: "native",
    previewQuality: "0.4",
    previewSpeed: "fast",
    finalQuality: "1.0",
    finalSpeed: "balanced",
    weightProfile: "full",
    videoWorkflowFamily: "official_h3",
    width: 1344,
    height: 768,
    fps: 24,
    refsMode: "refs_on",
    manualPromptOverrideEnabled: false,
    manualPromptOverrideText: "",
    audio: defaultRecipeAudio(),
    subtitles: defaultRecipeSubtitles(),
    export: defaultRecipeExport(),
  }
}
