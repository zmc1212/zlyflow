import {
  buildFormattedShotPrompt,
  CanvasTier,
  CompiledPromptInfo,
  DIRECTOR_SPEED_OPTIONS,
  DirectorQuality,
  DirectorShot,
  DirectorSpeed,
  SubjectSlot,
  TimelineProject,
} from "./types"

export const H3_MIN_DURATION_SEC = 2
export const H3_MAX_DURATION_SEC = 15
export const H3_MAX_REFERENCE_IMAGES = 9
export const H3_FPS = 24
export const H3_WORD_COUNT_WARN = 500

export type DirectorWorkflowId = "minimax-h3-t2v" | "minimax-h3-i2v" | "minimax-h3-r2v"
export type DirectorRenderPass = "preview" | "final"
export type RegistryQuality = DirectorQuality
export type ReferenceRole = "first_frame" | "last_frame" | "subject"
export type { DirectorSpeed }

export const DIRECTOR_PREVIEW_QUALITY: RegistryQuality = "0.4"
export const DIRECTOR_PREVIEW_SPEED: DirectorSpeed = "fast"
export const DIRECTOR_FINAL_QUALITY: RegistryQuality = "1.0"
export const DIRECTOR_FINAL_SPEED: DirectorSpeed = "balanced"
export const DIRECTOR_QUALITIES: RegistryQuality[] = ["0.4", "0.7", "1.0", "2.0"]
export const DIRECTOR_SPEEDS: DirectorSpeed[] = ["fast", "balanced", "quality"]

export interface ReferencePlanItem {
  pictureIndex: number
  role: ReferenceRole
  label: string
  slotId?: string
  slotIndex?: number
  hasImage: boolean
}

export interface ReferencePlan {
  items: ReferencePlanItem[]
  workflowId: DirectorWorkflowId
  warnings: string[]
  errors: string[]
}

export interface ShotSubmission {
  workflowId: DirectorWorkflowId
  prompt: string
  durationSec: number
  aspectRatio: string
  quality: RegistryQuality
  speed: DirectorSpeed
  renderPass: DirectorRenderPass
  plan: ReferencePlan
  wordCount: number
  totalFrames: number
  totalDurationSec: number
  warnings: string[]
  errors: string[]
  isOverride: boolean
  isClip: boolean
  clipAllowed: boolean
}

export function snapH3DurationSec(value: number): number {
  if (!Number.isFinite(value)) return H3_MIN_DURATION_SEC
  return Math.min(H3_MAX_DURATION_SEC, Math.max(H3_MIN_DURATION_SEC, Math.round(value)))
}

export function h3AlignedFrames(durationSec: number, fps: number = H3_FPS): number {
  const frames = Math.max(5, Math.round(snapH3DurationSec(durationSec) * fps))
  return frames + ((((5 - frames) % 17) + 17) % 17)
}

export function registryQualityForCanvas(tier: CanvasTier | string | undefined): RegistryQuality {
  if (tier === "fast") return "0.4"
  if (tier === "past_native") return "2.0"
  return "1.0"
}

export function normalizeDirectorQuality(value: string | undefined, fallback: RegistryQuality): RegistryQuality {
  return DIRECTOR_QUALITIES.includes(value as RegistryQuality) ? (value as RegistryQuality) : fallback
}

export function normalizeDirectorSpeed(value: string | undefined, fallback: DirectorSpeed): DirectorSpeed {
  return DIRECTOR_SPEEDS.includes(value as DirectorSpeed) ? (value as DirectorSpeed) : fallback
}

export function directorSpeedSteps(speed: DirectorSpeed | string | undefined): number {
  return DIRECTOR_SPEED_OPTIONS.find((item) => item.value === speed)?.steps || 8
}

export function directorSpeedLabel(speed: DirectorSpeed | string | undefined): string {
  return DIRECTOR_SPEED_OPTIONS.find((item) => item.value === speed)?.label || "8 步 + LoRA"
}

type DirectorJobSource = Pick<TimelineProject, "canvasTier" | "previewQuality" | "previewSpeed" | "finalQuality" | "finalSpeed">

function isDirectorJobSource(value: unknown): value is DirectorJobSource {
  return Boolean(value && typeof value === "object")
}

export function directorJobOptions(
  pass: DirectorRenderPass | string | undefined,
  canvasOrProject?: CanvasTier | string | DirectorJobSource,
): { quality: RegistryQuality; speed: DirectorSpeed; renderPass: DirectorRenderPass } {
  const project = isDirectorJobSource(canvasOrProject) ? canvasOrProject : undefined
  const canvasTier = project?.canvasTier || (typeof canvasOrProject === "string" ? canvasOrProject : undefined)
  const renderPass: DirectorRenderPass = pass === "preview" ? "preview" : "final"
  if (renderPass === "preview") {
    return {
      quality: normalizeDirectorQuality(project?.previewQuality, DIRECTOR_PREVIEW_QUALITY),
      speed: normalizeDirectorSpeed(project?.previewSpeed, DIRECTOR_PREVIEW_SPEED),
      renderPass,
    }
  }
  return {
    quality: normalizeDirectorQuality(project?.finalQuality, registryQualityForCanvas(canvasTier)),
    speed: normalizeDirectorSpeed(project?.finalSpeed, DIRECTOR_FINAL_SPEED),
    renderPass,
  }
}

export function directorRenderPassLabel(pass?: DirectorRenderPass | string): string {
  return pass === "preview" ? "预览" : "成片"
}

export function pictureTag(index: number): string {
  return `<Picture ${index}>`
}

export function sumShotDurationSec(shots: DirectorShot[] | undefined): number {
  return (shots || []).reduce((total, shot) => total + snapH3DurationSec(shot.durationSec || 5), 0)
}

export function clipDurationSec(shots: DirectorShot[] | undefined): { durationSec: number; allowed: boolean } {
  const durationSec = sumShotDurationSec(shots)
  return {
    durationSec,
    allowed: durationSec >= H3_MIN_DURATION_SEC && durationSec <= H3_MAX_DURATION_SEC,
  }
}

function slotHasImage(slot: SubjectSlot): boolean {
  return Boolean(slot.file || slot.previewUrl)
}

function shotHasFirstFrame(shot: DirectorShot | undefined): boolean {
  return Boolean(shot?.firstFrameFile || shot?.firstFrameUrl)
}

function shotHasLastFrame(shot: DirectorShot | undefined): boolean {
  return Boolean(shot?.endFrameFile || shot?.endFrameUrl)
}

export function activeSubjectSlots(project: TimelineProject): SubjectSlot[] {
  if (project.refsMode !== "refs_on") return []
  return (project.subjectSlots || [])
    .filter(slotHasImage)
    .slice()
    .sort((left, right) => left.slotIndex - right.slotIndex)
}

function emptyPlan(workflowId: DirectorWorkflowId = "minimax-h3-t2v"): ReferencePlan {
  return { items: [], workflowId, warnings: [], errors: [] }
}

function routeWorkflow(subjectCount: number, hasFirst: boolean, hasLast: boolean): DirectorWorkflowId {
  if (subjectCount > 0) return "minimax-h3-r2v"
  if (hasFirst || hasLast) return "minimax-h3-i2v"
  return "minimax-h3-t2v"
}

export function buildReferencePlan(project: TimelineProject, shot: DirectorShot): ReferencePlan {
  const warnings: string[] = []
  const errors: string[] = []
  const subjects = activeSubjectSlots(project)
  const items: ReferencePlanItem[] = []
  let pictureIndex = 1

  if (shotHasFirstFrame(shot)) {
    items.push({
      pictureIndex,
      role: "first_frame",
      label: `首帧 → ${pictureTag(pictureIndex)}`,
      hasImage: true,
    })
    pictureIndex += 1
  }

  if (subjects.length === 0 && shotHasLastFrame(shot)) {
    items.push({
      pictureIndex,
      role: "last_frame",
      label: `尾帧 → ${pictureTag(pictureIndex)}`,
      hasImage: true,
    })
    pictureIndex += 1
  }

  for (const slot of subjects) {
    items.push({
      pictureIndex,
      role: "subject",
      label: `${slot.id} → ${pictureTag(pictureIndex)}`,
      slotId: slot.id,
      slotIndex: slot.slotIndex,
      hasImage: true,
    })
    pictureIndex += 1
  }

  if (items.length > H3_MAX_REFERENCE_IMAGES) {
    errors.push(`参考图总数 (${items.length}) 超过 MiniMax H3 上限 ${H3_MAX_REFERENCE_IMAGES} 张`)
  }

  return {
    items,
    workflowId: routeWorkflow(subjects.length, shotHasFirstFrame(shot), shotHasLastFrame(shot)),
    warnings,
    errors,
  }
}

export function buildClipReferencePlan(project: TimelineProject): ReferencePlan {
  const shots = project.shots || []
  if (!shots.length) return emptyPlan()
  const first = shots[0]
  const last = shots[shots.length - 1]
  const synthetic: DirectorShot = {
    ...first,
    endFrameFile: last.endFrameFile,
    endFrameUrl: last.endFrameUrl,
  }
  return buildReferencePlan(project, synthetic)
}

export function replaceRefTags(text: string, plan: ReferencePlan): string {
  let result = text
  for (const item of plan.items) {
    if (item.role !== "subject" || !item.slotId) continue
    const tag = pictureTag(item.pictureIndex)
    result = result.split(item.slotId).join(tag)
  }
  return result
}

function buildSubjectDefinitions(project: TimelineProject, plan: ReferencePlan): string {
  const lines: string[] = []
  const slots = project.subjectSlots || []
  for (const item of plan.items) {
    if (item.role !== "subject" || !item.slotId) continue
    const slot = slots.find((candidate) => candidate.id === item.slotId)
    if (!slot) continue
    const description = slot.description?.trim() ? ` ${slot.description.trim()}` : ""
    lines.push(
      `<Subject ${slot.slotIndex}> (${slot.id}) is the ${slot.kind}${description} shown in ${pictureTag(item.pictureIndex)} [retention: ${slot.retention}].`,
    )
  }
  if (!lines.length) return ""
  return `[Subject definitions]:\n${lines.join("\n")}`
}

export function compileShotPrompt(project: TimelineProject, shot: DirectorShot, plan: ReferencePlan): string {
  const sections: string[] = []
  if (plan.workflowId === "minimax-h3-r2v") {
    const definitions = buildSubjectDefinitions(project, plan)
    if (definitions) sections.push(definitions)
  }

  let body = replaceRefTags(buildFormattedShotPrompt(shot), plan)
  const firstFrame = plan.items.find((item) => item.role === "first_frame")
  if (firstFrame && plan.workflowId === "minimax-h3-r2v") {
    body += `\n(begins from ${pictureTag(firstFrame.pictureIndex)})`
  }
  sections.push(body)
  return sections.join("\n\n").trim()
}

function taskTypeLabel(workflowId: DirectorWorkflowId): string {
  if (workflowId === "minimax-h3-r2v") return "Reference-to-Video (Ref2VA)"
  if (workflowId === "minimax-h3-i2v") return "Image-to-Video (I2VA)"
  return "Text-to-Video (T2VA)"
}

export function compileClipPrompt(project: TimelineProject): {
  allowed: boolean
  prompt: string
  durationSec: number
  plan: ReferencePlan
  warnings: string[]
  errors: string[]
} {
  const shots = project.shots || []
  const warnings: string[] = []
  const errors: string[] = []
  const { durationSec, allowed } = clipDurationSec(shots)

  if (!shots.length) {
    errors.push("没有可编译的分镜")
    return { allowed: false, prompt: "", durationSec: H3_MIN_DURATION_SEC, plan: emptyPlan(), warnings, errors }
  }
  if (!allowed) {
    errors.push(`选中分镜合计 ${durationSec}s，整段提交必须在 ${H3_MIN_DURATION_SEC}–${H3_MAX_DURATION_SEC} 秒；请改为逐镜接龙`)
    return { allowed: false, prompt: "", durationSec, plan: emptyPlan(), warnings, errors }
  }

  const plan = buildClipReferencePlan(project)
  errors.push(...plan.errors)
  warnings.push(...plan.warnings)

  const sections: string[] = []
  sections.push(`[task type]: ${taskTypeLabel(plan.workflowId)}`)
  if (project.globalSoundscape?.trim()) {
    sections.push(`[overall_soundscape]: ${project.globalSoundscape.trim()}`)
  }
  if (project.globalMusic?.trim()) {
    sections.push(`[non_diegetic_music]: ${project.globalMusic.trim()}`)
  }
  const definitions = buildSubjectDefinitions(project, plan)
  if (definitions) sections.push(definitions)

  let cursor = 0
  const shotBlocks = shots.map((shot, index) => {
    const duration = snapH3DurationSec(shot.durationSec || 5)
    const start = cursor
    const end = cursor + duration
    cursor = end
    let header = `[Shot ${index + 1}] (${start.toFixed(1)}s - ${end.toFixed(1)}s`
    const firstFrame = plan.items.find((item) => item.role === "first_frame")
    if (index === 0 && firstFrame) {
      header += `, begins from ${pictureTag(firstFrame.pictureIndex)}`
    } else if (shot.usePreviousEndFrame) {
      header += `, corresponds to previous keyframe`
    }
    header += "):"
    const body = replaceRefTags(buildFormattedShotPrompt(shot), plan)
    return `${header} ${body}`
  })
  sections.push(`[Timeline sequence]:\n${shotBlocks.join("\n\n")}`)

  const prompt = sections.join("\n\n").trim()
  const wordCount = countWords(prompt)
  if (wordCount > H3_WORD_COUNT_WARN) {
    warnings.push(`提示词总词数 (${wordCount} words) 超过官方推荐的 ${H3_WORD_COUNT_WARN} 词上限，建议精简分镜描述。`)
  }

  return { allowed: errors.length === 0, prompt, durationSec, plan, warnings, errors }
}

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

function submissionFromPrompt(
  project: TimelineProject,
  prompt: string,
  plan: ReferencePlan,
  durationSec: number,
  extras: {
    isOverride: boolean
    isClip: boolean
    clipAllowed: boolean
    renderPass?: DirectorRenderPass
    warnings?: string[]
    errors?: string[]
  },
): ShotSubmission {
  const warnings = [...plan.warnings, ...(extras.warnings || [])]
  const errors = [...plan.errors, ...(extras.errors || [])]
  const wordCount = countWords(prompt)
  if (wordCount > H3_WORD_COUNT_WARN) {
    warnings.push(`提示词总词数 (${wordCount} words) 超过官方推荐的 ${H3_WORD_COUNT_WARN} 词上限，建议精简分镜描述。`)
  }
  const job = directorJobOptions(extras.renderPass, project)
  return {
    workflowId: plan.workflowId,
    prompt,
    durationSec,
    aspectRatio: project.aspectRatio || "16:9",
    quality: job.quality,
    speed: job.speed,
    renderPass: job.renderPass,
    plan,
    wordCount,
    totalFrames: h3AlignedFrames(durationSec, project.fps || H3_FPS),
    totalDurationSec: durationSec,
    warnings: [...new Set(warnings)],
    errors: [...new Set(errors)],
    isOverride: extras.isOverride,
    isClip: extras.isClip,
    clipAllowed: extras.clipAllowed,
  }
}

export function resolveShotSubmission(
  project: TimelineProject,
  shot: DirectorShot,
  renderPass: DirectorRenderPass = "final",
): ShotSubmission {
  const plan = buildReferencePlan(project, shot)
  const durationSec = snapH3DurationSec(shot.durationSec || 5)
  const overrideText = project.manualPromptOverrideEnabled ? project.manualPromptOverrideText.trim() : ""
  const prompt = overrideText || compileShotPrompt(project, shot, plan)
  const clip = clipDurationSec(project.shots)
  return submissionFromPrompt(project, prompt, plan, durationSec, {
    isOverride: Boolean(overrideText),
    isClip: false,
    clipAllowed: clip.allowed,
    renderPass,
  })
}

export function resolveClipSubmission(
  project: TimelineProject,
  renderPass: DirectorRenderPass = "final",
): ShotSubmission {
  const compiled = compileClipPrompt(project)
  const overrideText = project.manualPromptOverrideEnabled ? project.manualPromptOverrideText.trim() : ""
  const prompt = compiled.allowed && overrideText ? overrideText : compiled.prompt
  return submissionFromPrompt(project, prompt, compiled.plan, compiled.durationSec || H3_MIN_DURATION_SEC, {
    isOverride: Boolean(compiled.allowed && overrideText),
    isClip: true,
    clipAllowed: compiled.allowed,
    renderPass,
    warnings: compiled.warnings,
    errors: compiled.errors,
  })
}

export function compileDirectorPrompt(project: TimelineProject): CompiledPromptInfo {
  const timelineDuration = sumShotDurationSec(project.shots)
  const clip = compileClipPrompt(project)
  const prompt = clip.allowed ? clip.prompt : clip.prompt || (project.shots || []).map((shot) => compileShotPrompt(project, shot, buildReferencePlan(project, shot))).join("\n\n")
  const warnings = [...clip.warnings]
  if (!clip.allowed) {
    warnings.push(...clip.errors)
  }
  const wordCount = countWords(prompt)
  return {
    rawPrompt: prompt,
    wordCount,
    totalDurationSec: timelineDuration,
    totalFrames: h3AlignedFrames(clip.allowed ? clip.durationSec : Math.min(H3_MAX_DURATION_SEC, Math.max(H3_MIN_DURATION_SEC, timelineDuration))),
    referenceTally: {
      images: clip.plan.items.length,
      videos: 0,
      audios: project.globalMusic ? 1 : 0,
      total: clip.plan.items.length + (project.globalMusic ? 1 : 0),
    },
    warnings,
    isWithinTargetWordCount: wordCount >= 100 && wordCount <= H3_WORD_COUNT_WARN,
  }
}
