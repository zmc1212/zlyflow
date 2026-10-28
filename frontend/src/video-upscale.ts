export const RTX_VSR_MODE = "nvidia-rtx-vsr"
export const SEEDVR2_MODE = "seedvr2-upscale"
export const UPSCALE_MODES = [RTX_VSR_MODE, SEEDVR2_MODE] as const
export const UPSCALE_OUTPUT_LABEL = "2x 超分"
export const SEEDVR2_OUTPUT_LABEL = "2x 高清增强"
export const UPSCALE_OUTPUT_LABELS = [UPSCALE_OUTPUT_LABEL, SEEDVR2_OUTPUT_LABEL] as const

export type UpscaleEngine = "rtx" | "seedvr2"

export type UpscaleOutputLike = {
  kind: "image" | "video"
  label: string
  path: string
  download_url?: string | null
  delivery_status?: "pending" | "local" | "cloud" | "expired"
}

export type UpscaleJobLike = {
  id: string
  mode: string
  status: string
  stage: string
  source?: { job_id: string } | null
  outputs?: UpscaleOutputLike[]
  rounds?: Array<{
    generation_items: Array<{
      id: string
      outputs: UpscaleOutputLike[]
    }>
  }>
}

export type UpscaleVideoResult = {
  jobId: string
  generationItemId: string
  outputIndex: number
  output: UpscaleOutputLike
}

const LIVE_STATUSES = new Set(["queued", "running", "interrupted"])

export function isUpscaleJob(job: Pick<UpscaleJobLike, "mode"> | null | undefined): boolean {
  return UPSCALE_MODES.some((mode) => job?.mode === mode)
}

export function upscaleJobEngine(job: Pick<UpscaleJobLike, "mode"> | null | undefined): UpscaleEngine | undefined {
  if (job?.mode === SEEDVR2_MODE) return "seedvr2"
  if (job?.mode === RTX_VSR_MODE) return "rtx"
  return undefined
}

export function isUpscaleOutput(output: Pick<UpscaleOutputLike, "label"> | null | undefined): boolean {
  return UPSCALE_OUTPUT_LABELS.some((label) => output?.label === label)
}

export function upscaleOutputLabel(output: Pick<UpscaleOutputLike, "label"> | null | undefined): string {
  if (output?.label === SEEDVR2_OUTPUT_LABEL) return "2× 高清增强"
  if (output?.label === UPSCALE_OUTPUT_LABEL) return "2× 超分"
  return ""
}

export function hasOriginalVideo(job: UpscaleJobLike | null | undefined): boolean {
  if (!job) return false
  const outputs = [
    ...(job.outputs ?? []),
    ...(job.rounds ?? []).flatMap((round) => round.generation_items.flatMap((item) => item.outputs)),
  ]
  return outputs.some((output) => output.kind === "video" && !isUpscaleOutput(output))
}

export function relatedUpscaleJobs(jobs: UpscaleJobLike[], sourceJobId: string): UpscaleJobLike[] {
  return jobs.filter((job) => isUpscaleJob(job) && job.source?.job_id === sourceJobId)
}

export function activeUpscaleJob(jobs: UpscaleJobLike[], sourceJobId: string): UpscaleJobLike | undefined {
  return relatedUpscaleJobs(jobs, sourceJobId).find((job) => LIVE_STATUSES.has(job.status))
}

export function canRequestJobUpscale(
  job: UpscaleJobLike | null | undefined,
  jobs: UpscaleJobLike[],
  inspectingOther = false,
): boolean {
  if (!job || inspectingOther || isUpscaleJob(job)) return false
  if (job.status !== "succeeded") return false
  if (!hasOriginalVideo(job)) return false
  return activeUpscaleJob(jobs, job.id) == null
}

export function upscaleDisabledReason(
  job: UpscaleJobLike | null | undefined,
  jobs: UpscaleJobLike[],
  inspectingOther = false,
): string | undefined {
  if (!job || inspectingOther || isUpscaleJob(job)) return undefined
  if (job.status !== "succeeded") return "成片成功后才能超分"
  if (!hasOriginalVideo(job)) return "没有可超分的原片"
  const active = activeUpscaleJob(jobs, job.id)
  if (active) return active.stage || "超分进行中"
  return undefined
}

export function extraUpscaleResults(sourceJob: UpscaleJobLike, jobs: UpscaleJobLike[]): UpscaleVideoResult[] {
  const already = [
    ...(sourceJob.outputs ?? []),
    ...(sourceJob.rounds ?? []).flatMap((round) => round.generation_items.flatMap((item) => item.outputs)),
  ].some((output) => output.kind === "video" && isUpscaleOutput(output))
  if (already) return []
  const extras: UpscaleVideoResult[] = []
  for (const job of relatedUpscaleJobs(jobs, sourceJob.id)) {
    if (job.status !== "succeeded") continue
    for (const round of job.rounds ?? []) {
      for (const item of round.generation_items) {
        item.outputs.forEach((output, outputIndex) => {
          if (output.kind === "video") {
            extras.push({ jobId: job.id, generationItemId: item.id, outputIndex, output })
          }
        })
      }
    }
  }
  return extras
}
