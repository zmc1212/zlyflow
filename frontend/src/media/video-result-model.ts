import { isUpscaleOutput, upscaleOutputLabel } from "../video-upscale"

export type VideoResult = {
  generationItemId: string
  outputIndex: number
  output: {
    kind: "image" | "video"
    path: string
    label: string
    delivery_status?: "pending" | "local" | "cloud" | "expired"
    download_url?: string | null
    cloud_url?: string | null
  }
  src?: string
  jobId?: string
}

// A version belongs to one output, including outputs from a related upscale job.
export function videoResultKey(result: VideoResult): string {
  return JSON.stringify([result.jobId, result.generationItemId, result.outputIndex, result.output.path])
}

export function selectVideoResult(results: VideoResult[], selectedKey?: string): VideoResult | undefined {
  const videos = results.filter((result) => result.output.kind === "video")
  return videos.find((result) => videoResultKey(result) === selectedKey)
    ?? videos.find((result) => isUpscaleOutput(result.output))
    ?? videos[0]
}

export function videoVersions(results: VideoResult[]) {
  let original = 0
  return results.filter((result) => result.output.kind === "video").map((result) => {
    const upscaleLabel = upscaleOutputLabel(result.output)
    return {
      key: videoResultKey(result), result,
      label: upscaleLabel || `原片 ${++original}`,
      detail: upscaleLabel ? "" : result.output.label,
    }
  })
}

// The existing job-level upscale endpoint uses the latest generation item's
// first original output. Other versions must not appear to upscale themselves.
export function jobUpscaleSourceKey(job: {
  id: string
  rounds: { generation_items: { id: string; outputs: VideoResult["output"][] }[] }[]
}): string | undefined {
  for (const round of [...job.rounds].reverse()) {
    for (const item of [...round.generation_items].reverse()) {
      const outputIndex = item.outputs.findIndex((output) => output.kind === "video" && !isUpscaleOutput(output))
      if (outputIndex >= 0) return videoResultKey({ jobId: job.id, generationItemId: item.id, outputIndex, output: item.outputs[outputIndex] })
    }
  }
  return undefined
}

export function videoDeliveryLabel(result: VideoResult): string {
  switch (result.output.delivery_status) {
    case "expired": return "云端文件已过期"
    case "local": return "已保存到员工电脑"
    case "pending": return "等待交付"
    default: return "已存入云端"
  }
}

export function formatVideoTime(seconds: number): string {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`
}
