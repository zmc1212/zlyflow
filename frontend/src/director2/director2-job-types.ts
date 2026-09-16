/** 导演台2「全部任务」按 job_type 切换显示的常量与过滤逻辑。 */

export const DIRECTOR2_JOB_TYPES = [
  "image_generation",
  "video_generation",
  "h3_prompt",
  "ai_pipeline",
] as const

export type Director2JobType = (typeof DIRECTOR2_JOB_TYPES)[number]

export const DIRECTOR2_JOB_TYPE_LABELS: Record<Director2JobType, string> = {
  image_generation: "图片生成",
  video_generation: "视频生成",
  h3_prompt: "H3 提示词",
  ai_pipeline: "AI 生成",
}

export const DIRECTOR2_DEFAULT_JOB_TYPE: Director2JobType = "image_generation"

export type Director2JobTypeSource = {
  job_type?: string | null
  payload?: {
    target_type?: string | null
    h3_prompt?: string | null
    result_prompt?: string | null
  } | null
}

export function isH3PromptJob(job: Director2JobTypeSource | null | undefined): boolean {
  return job?.job_type === "h3_prompt" || job?.payload?.target_type === "h3_prompt"
}

export function h3PromptResultText(job: Director2JobTypeSource | null | undefined): string {
  return String(job?.payload?.h3_prompt || job?.payload?.result_prompt || "").trim()
}

export function videoShotPromptText(shot: {
  prompt?: string | null
  h3_prompt?: string | null
} | null | undefined): string {
  return String(shot?.prompt || shot?.h3_prompt || "").trim()
}

export function isDirector2JobType(value: string | null | undefined): value is Director2JobType {
  return DIRECTOR2_JOB_TYPES.includes(value as Director2JobType)
}

export function director2JobTypeLabel(type: string | null | undefined): string {
  if (isDirector2JobType(type)) return DIRECTOR2_JOB_TYPE_LABELS[type]
  return type || "未知类型"
}

export function filterJobsByType<T extends Director2JobTypeSource>(
  jobs: T[],
  type: Director2JobType,
): T[] {
  return jobs.filter((job) => job.job_type === type)
}

export function countJobsByType(jobs: Director2JobTypeSource[]): Record<Director2JobType, number> {
  const counts = {
    image_generation: 0,
    video_generation: 0,
    h3_prompt: 0,
    ai_pipeline: 0,
  } satisfies Record<Director2JobType, number>
  for (const job of jobs) {
    if (isDirector2JobType(job.job_type)) counts[job.job_type] += 1
  }
  return counts
}

/** 默认 Tab：列表按更新时间倒序时取最新一条所属类型；空列表回落图片生成。 */
export function defaultJobTypeTab(jobs: Director2JobTypeSource[]): Director2JobType {
  const newest = jobs[0]
  if (newest && isDirector2JobType(newest.job_type)) return newest.job_type
  return DIRECTOR2_DEFAULT_JOB_TYPE
}
