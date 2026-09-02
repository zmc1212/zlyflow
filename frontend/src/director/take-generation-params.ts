import {
  DIRECTOR_SPEED_OPTIONS,
  DIRECTOR_WEIGHT_OPTIONS,
  DirectorSpeed,
  DirectorWeightProfile,
  ShotTake,
} from "./types"
import { directorRenderPassLabel } from "./prompt-compiler"
import { FALLBACK_DIRECTOR_WORKFLOW_FAMILIES } from "./director-workflows"

export interface ShotTakeGenerationOptions {
  aspect_ratio?: string
  quality?: string
  speed?: string
  weight_profile?: string
  duration?: number
}

export interface TakeGenerationJobLike {
  mode?: string
  options?: Record<string, unknown>
}

export interface TakeGenerationMeta {
  renderPass?: ShotTake["renderPass"]
  workflowId?: string
  videoWorkflowFamily?: string
  options: ShotTakeGenerationOptions
  summary: string
  details: Array<{ label: string; value: string }>
}

const WORKFLOW_FAMILY_LABELS = Object.fromEntries(
  FALLBACK_DIRECTOR_WORKFLOW_FAMILIES.map((item) => [item.id, item.label]),
) as Record<string, string>

function asString(value: unknown): string {
  if (value === null || value === undefined) return ""
  return String(value).trim()
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

export function workflowFamilyLabel(family: string | undefined): string {
  const key = asString(family)
  if (!key) return ""
  return WORKFLOW_FAMILY_LABELS[key] || key
}

export function directorSpeedLabel(speed: string | undefined): string {
  const normalized = asString(speed) as DirectorSpeed
  return DIRECTOR_SPEED_OPTIONS.find((item) => item.value === normalized)?.label || normalized || "—"
}

export function directorWeightLabel(profile: string | undefined): string {
  const normalized = asString(profile) as DirectorWeightProfile
  return DIRECTOR_WEIGHT_OPTIONS.find((item) => item.value === normalized)?.label || normalized || "—"
}

export function resolveTakeGenerationOptions(
  take: Pick<ShotTake, "options">,
  job?: TakeGenerationJobLike | null,
): ShotTakeGenerationOptions {
  const stored = take.options || {}
  const fromJob = job?.options || {}
  return {
    aspect_ratio: asString(stored.aspect_ratio) || asString(fromJob.aspect_ratio) || undefined,
    quality: asString(stored.quality) || asString(fromJob.quality) || undefined,
    speed: asString(stored.speed) || asString(fromJob.speed) || undefined,
    weight_profile: asString(stored.weight_profile) || asString(fromJob.weight_profile) || undefined,
    duration: asNumber(stored.duration) ?? asNumber(fromJob.duration),
  }
}

export function resolveTakeGenerationMeta(
  take: ShotTake,
  job?: TakeGenerationJobLike | null,
): TakeGenerationMeta {
  const options = resolveTakeGenerationOptions(take, job)
  const workflowId = asString(take.workflowId) || asString(job?.mode) || undefined
  const videoWorkflowFamily = asString(take.videoWorkflowFamily) || undefined
  const familyLabel = workflowFamilyLabel(videoWorkflowFamily)
  const renderPass = take.renderPass
  const passLabel = renderPass ? directorRenderPassLabel(renderPass) : ""
  const speedLabel = directorSpeedLabel(options.speed)
  const weightLabel = directorWeightLabel(options.weight_profile)
  const qualityLabel = options.quality ? `${options.quality} MP` : "—"
  const durationLabel = options.duration ? `${options.duration}s` : "—"
  const aspectLabel = options.aspect_ratio || "—"
  const workflowLabel = familyLabel || workflowId || "—"

  const summaryParts = [
    passLabel,
    qualityLabel,
    speedLabel.replace(/\s*\(.*$/, ""),
    weightLabel.replace(/\s*\(.*$/, ""),
    workflowLabel,
  ].filter(Boolean)

  const details: Array<{ label: string; value: string }> = [
    { label: "档位", value: passLabel || "—" },
    { label: "工作流家族", value: workflowLabel },
    { label: "工作流 ID", value: workflowId || "—" },
    { label: "画面比例", value: aspectLabel },
    { label: "分辨率", value: qualityLabel },
    { label: "生成速度", value: speedLabel },
    { label: "模型体积", value: weightLabel },
    { label: "时长", value: durationLabel },
    { label: "任务 ID", value: asString(take.jobId) || asString(take.id) || "—" },
  ]

  return {
    renderPass,
    workflowId,
    videoWorkflowFamily,
    options,
    summary: summaryParts.join(" · "),
    details,
  }
}

export function takeGenerationDiff(
  left: TakeGenerationMeta,
  right: TakeGenerationMeta,
): string[] {
  const changed: string[] = []
  for (const item of left.details) {
    const other = right.details.find((entry) => entry.label === item.label)
    if (!other || other.value !== item.value) {
      changed.push(item.label)
    }
  }
  return changed
}
