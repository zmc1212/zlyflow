import { parseMediaAspect } from "../lib/utils"
import { cloudThumbnailSrc } from "../media-thumbnails"

export type HomeOutput = {
  kind: "image" | "video"
  path: string
  label: string
  cloud_url?: string | null
  download_url?: string | null
  delivery_status?: string
}

type HomeRound = {
  prompt?: string
  display_prompt?: string | null
  options?: Record<string, unknown>
  request_parameters?: { name: string; value: unknown }[]
  generation_items: { outputs: HomeOutput[] }[]
}

export type HomeJob = {
  id: string
  title?: string | null
  prompt: string
  media_type: "image" | "video"
  created_at: string
  options?: Record<string, unknown>
  request_parameters?: { name: string; value: unknown }[]
  outputs: HomeOutput[]
  rounds?: HomeRound[]
}

export type RecentCreation = {
  id: string
  jobId: string
  title: string
  kind: "image" | "video"
  createdAt: string
  output: HomeOutput
  src: string
  thumbnail: string | null
  aspectRatio?: number
  duration?: string
}

function durationLabel(value: unknown): string | undefined {
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return undefined
  const rounded = Math.round(seconds)
  return `${String(Math.floor(rounded / 60)).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`
}

/** One real, available result per task; a later empty/failed round keeps its previous result. */
export function recentCreations(jobs: readonly HomeJob[], limit = 12): RecentCreation[] {
  const entries: RecentCreation[] = []
  for (const job of jobs) {
    const rounds = [...(job.rounds ?? [])].reverse()
    const candidates = [
      ...rounds.flatMap((round) => round.generation_items.flatMap((item) =>
        item.outputs.map((output) => ({ output, source: round })))),
      ...job.outputs.map((output) => ({ output, source: job })),
    ]
    const chosen = candidates.find(({ output }) => output.delivery_status !== "expired"
      && Boolean(output.cloud_url || output.download_url || output.path))
    if (!chosen) continue
    const { output, source } = chosen
    const ratioValue = source.options?.aspect_ratio
      ?? source.request_parameters?.find((parameter) => parameter.name === "aspect_ratio")?.value
      ?? job.options?.aspect_ratio
    const aspect = parseMediaAspect(typeof ratioValue === "string" ? ratioValue : undefined)
    const duration = source.options?.duration_seconds ?? source.options?.duration
      ?? source.request_parameters?.find((parameter) => parameter.name === "duration")?.value
      ?? job.options?.duration_seconds ?? job.options?.duration
    const title = job.title?.trim() || ("display_prompt" in source ? source.display_prompt?.trim() : "")
      || source.prompt?.trim() || job.prompt.trim() || (job.media_type === "video" ? "未命名视频" : "未命名图片")
    entries.push({
      id: `${job.id}:${output.path}`,
      jobId: job.id,
      title,
      kind: output.kind,
      createdAt: job.created_at,
      output,
      src: output.cloud_url || output.download_url || `/api/media/${encodeURIComponent(output.path)}`,
      thumbnail: cloudThumbnailSrc(output.kind, output.cloud_url),
      aspectRatio: aspect ? aspect.width / aspect.height : undefined,
      duration: output.kind === "video" ? durationLabel(duration) : undefined,
    })
  }
  return entries.sort((a, b) => {
    const aTime = Date.parse(a.createdAt)
    const bTime = Date.parse(b.createdAt)
    return (Number.isFinite(bTime) ? bTime : 0) - (Number.isFinite(aTime) ? aTime : 0)
  }).slice(0, Math.max(0, limit))
}
