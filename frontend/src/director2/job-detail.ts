import type { Director2Job } from "./api"
import { jobPreviewVideoUrl, jobSourceVideoUrl, jobUpscaledVideoUrl } from "./director2-video-settings"

// 列表中的 shots / source_shots 仅含 beat_id、video_url，不是完整详情。
export function mergeJobDetail(current: Director2Job, summary: Director2Job): Director2Job {
  if (current.id !== summary.id || current.project_id !== summary.project_id) return summary
  const payload = { ...current.payload, ...summary.payload }
  for (const key of ["shots", "source_shots"] as const) {
    const stored = current.payload?.[key]
    const full = Array.isArray(stored) && stored.length
      ? stored
      : current.payload?.[key === "shots" ? "source_shots" : "shots"]
    const slim = summary.payload?.[key]
    if (!Array.isArray(full) || !Array.isArray(slim)) continue
    payload[key] = slim.map(shot => {
      const detail = full.find(item => shot.beat_id
        ? item.beat_id === shot.beat_id
        : shot.video_url && item.video_url === shot.video_url)
      return { ...detail, ...shot }
    })
  }
  return { ...summary, payload }
}

export function jobDetailVideos(job: Director2Job | null) {
  const resultUrl = jobUpscaledVideoUrl(job) || jobPreviewVideoUrl(job)
  const sourceUrl = jobSourceVideoUrl(job)
  return { resultUrl, sourceUrl: sourceUrl !== resultUrl ? sourceUrl : "" }
}
