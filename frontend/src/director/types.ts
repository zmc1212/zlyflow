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
  { tier: "fast", quality: "0.4", label: "0.4 MP（预览档）" },
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
  { value: "fast", label: "4 步 + LoRA", steps: 4 },
  { value: "balanced", label: "8 步 + LoRA", steps: 8 },
  { value: "quality", label: "20 步", steps: 20 },
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

export function buildFormattedShotPrompt(shot: DirectorShot): string {
  const scaleText = CAMERA_SCALE_LABELS[shot.camera.scale]?.label.split(" ")[0] ?? "中景"
  const movementText = CAMERA_MOVEMENT_LABELS[shot.camera.movement]?.label.split(" ")[0] ?? "前推"
  const angleText = CAMERA_ANGLE_LABELS[shot.camera.angle]?.label ?? "平视"
  const lightingText = CAMERA_LIGHTING_LABELS[shot.camera.lighting]?.label ?? "电影级柔光"
  const speedText = CAMERA_SPEED_LABELS[shot.camera.speed]?.label ?? "平稳"

  const cameraPrefix = `【${scaleText}，${angleText}，镜头${movementText}，${speedText}，${lightingText}】`
  let result = shot.prompt.trim()
  if (!result.startsWith("【")) {
    result = `${cameraPrefix} ${result}`
  }
  if (shot.dialogue?.trim()) {
    result += `\n[台词对白: ${shot.dialogue.trim()}]`
  }
  if (shot.soundscape?.trim()) {
    result += `\n[音效: ${shot.soundscape.trim()}]`
  } else if (shot.camera.sfx?.trim()) {
    result += `\n[环境音效: ${shot.camera.sfx.trim()}]`
  }
  return result
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
}

export interface RecipeLocation {
  id: string
  name: string
  description: string
  promptText: string
  imageJobId?: string | null
  imageUrl?: string | null
}

export interface RecipeShot {
  id: string
  shotNumber: number
  title: string
  description: string
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
}

export interface RecipeProject {
  kind: "director_recipe"
  script: RecipeScript
  artStyle: RecipeArtStyle | null
  characters: RecipeCharacter[]
  locations: RecipeLocation[]
  scenes: RecipeScene[]
  agentStatus: RecipeAgentStatus[]
  globalMusic: string
  globalSoundscape: string
  aspectRatio: string
  canvasTier: CanvasTier
  previewQuality: DirectorQuality
  previewSpeed: DirectorSpeed
  finalQuality: DirectorQuality
  finalSpeed: DirectorSpeed
  width: number
  height: number
  fps: number
  refsMode: "refs_off" | "refs_on"
  manualPromptOverrideEnabled: boolean
  manualPromptOverrideText: string
}

export interface BatchRunItem {
  id: string
  title: string
  script: string
  jobId?: string | null
  status: DirectorShot["status"]
  outputVideoUrl?: string | null
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
  keywords: string[]
}

export interface DirectorArtStyleCatalog {
  categories: DirectorArtStyleCategory[]
  styles: DirectorArtStyle[]
  count: number
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

export function createEmptyBatch(theme: string = ""): BatchRunPayload {
  return {
    kind: "batch_run",
    theme,
    count: 3,
    aspectRatio: "9:16",
    durationSec: 8,
    artStyle: null,
    items: [],
  }
}

export function recipeShotsToPlayer(shots: RecipeShot[]): DirectorShot[] {
  return shots.map((shot, index) => ({
    id: shot.id,
    shotNumber: shot.shotNumber || index + 1,
    title: shot.title,
    startSec: 0,
    durationSec: shot.durationSec,
    prompt: shot.compiledPrompt || shot.description,
    dialogue: shot.dialogue,
    camera: defaultCameraDirection(),
    referencedSubjectIds: [],
    takes: [],
    activeTakeIndex: 0,
    jobId: shot.jobId || undefined,
    status: shot.status,
    progress: shot.progress || 0,
    outputVideoUrl: shot.outputVideoUrl || undefined,
    retakeCount: 0,
  }))
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
      { id: "research", status: "pending", error: null },
      { id: "script", status: "pending", error: null },
      { id: "art_style", status: "pending", error: null },
      { id: "storyboard", status: "pending", error: null },
      { id: "characters", status: "pending", error: null },
      { id: "locations", status: "pending", error: null },
      { id: "voice", status: "pending", error: null },
      { id: "music", status: "pending", error: null },
      { id: "media", status: "pending", error: null },
    ],
    globalMusic: "",
    globalSoundscape: "电影级空间环境声",
    aspectRatio: "16:9",
    canvasTier: "native",
    previewQuality: "0.4",
    previewSpeed: "fast",
    finalQuality: "1.0",
    finalSpeed: "balanced",
    width: 1344,
    height: 768,
    fps: 24,
    refsMode: "refs_on",
    manualPromptOverrideEnabled: false,
    manualPromptOverrideText: "",
  }
}

