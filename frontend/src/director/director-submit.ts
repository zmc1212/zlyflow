export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : ""
      if (!result.startsWith("data:")) {
        reject(new Error("无法将图片转为可保存的预览"))
        return
      }
      resolve(result)
    }
    reader.onerror = () => reject(new Error("无法读取图片"))
    reader.readAsDataURL(file)
  })
}

export async function fileFromUrl(url: string, filename: string): Promise<File> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`无法读取参考图 ${filename}`)
  }
  const blob = await response.blob()
  return new File([blob], filename, { type: blob.type || "image/png" })
}

export async function extractVideoFrame(videoUrl: string, timeSec?: number): Promise<{ file: File; dataUrl: string }> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video")
    video.crossOrigin = "anonymous"
    video.muted = true
    video.playsInline = true
    video.preload = "auto"

    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new Error("抽取尾帧超时"))
    }, 20000)

    const cleanup = () => {
      window.clearTimeout(timeout)
      video.removeAttribute("src")
      video.load()
    }

    const capture = () => {
      try {
        const canvas = document.createElement("canvas")
        canvas.width = video.videoWidth || 1280
        canvas.height = video.videoHeight || 720
        const context = canvas.getContext("2d")
        if (!context) {
          cleanup()
          reject(new Error("无法截取尾帧"))
          return
        }
        context.drawImage(video, 0, 0, canvas.width, canvas.height)
        const dataUrl = canvas.toDataURL("image/png")
        canvas.toBlob((blob) => {
          cleanup()
          if (!blob) {
            reject(new Error("无法编码尾帧"))
            return
          }
          resolve({
            file: new File([blob], "end_frame.png", { type: "image/png" }),
            dataUrl,
          })
        }, "image/png")
      } catch (error) {
        cleanup()
        reject(error instanceof Error ? error : new Error("抽取尾帧失败"))
      }
    }

    video.onerror = () => {
      cleanup()
      reject(new Error("无法读取成片以抽取尾帧"))
    }
    video.onloadedmetadata = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0
      const target = timeSec ?? Math.max(0, duration - 1 / 24)
      if (duration <= 0 || target <= 0) {
        video.onseeked = null
        capture()
        return
      }
      video.currentTime = Math.min(duration, target)
    }
    video.onseeked = capture
    video.src = videoUrl
  })
}

export type DirectorJobSnapshot = {
  id?: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
  outputs?: Array<{ kind?: string; download_url?: string; path?: string }>
}

export type DirectorJobStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"

export function jobVideoUrl(job: DirectorJobSnapshot | null | undefined): string | undefined {
  const output = job?.outputs?.find((item) => item.kind === "video")
  if (!output) return undefined
  return output.download_url || (output.path ? `/api/media/${encodeURIComponent(output.path)}` : undefined)
}

export function shotStatusFromJob(job: DirectorJobSnapshot | null | undefined): DirectorJobStatus {
  const status = job?.status
  if (status === "partial") return jobVideoUrl(job) ? "succeeded" : "running"
  if (status === "succeeded" || status === "failed" || status === "cancelled" || status === "interrupted" || status === "running") {
    return status
  }
  if ((job?.progress ?? 0) > 0) return "running"
  const stage = (job?.stage || "").trim()
  if (stage && stage !== "等待排队") return "running"
  return "queued"
}

export function mergeDirectorStatus(current: DirectorJobStatus | "idle", incoming: DirectorJobStatus): DirectorJobStatus {
  if (current === "running" && incoming === "queued") return "running"
  return incoming
}

export function jobProgressFromJob(job: DirectorJobSnapshot | null | undefined, fallback = 0): number {
  if (shotStatusFromJob(job) === "succeeded") return 100
  const progress = job?.progress
  if (typeof progress === "number" && Number.isFinite(progress)) return Math.max(0, Math.min(100, Math.round(progress)))
  return fallback
}

export async function waitForJobTerminal(
  jobId: string,
  options?: {
    intervalMs?: number
    timeoutMs?: number
    onProgress?: (job: any) => void
  },
): Promise<any> {
  const intervalMs = options?.intervalMs ?? 2000
  const timeoutMs = options?.timeoutMs ?? 30 * 60 * 1000
  const started = Date.now()

  while (Date.now() - started < timeoutMs) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`)
    if (!response.ok) {
      throw new Error("查询分镜任务失败")
    }
    const job = await response.json()
    options?.onProgress?.(job)
    if (job.status === "succeeded" || job.status === "partial") {
      return job
    }
    if (job.status === "failed" || job.status === "interrupted" || job.status === "cancelled") {
      throw new Error(job.error || (job.status === "cancelled" ? "分镜任务已停止" : `分镜任务${job.status === "failed" ? "失败" : "已中断"}`))
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }
  throw new Error("等待分镜任务超时")
}
