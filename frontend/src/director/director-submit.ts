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
  outputs?: Array<{ kind?: string; download_url?: string; cloud_url?: string; path?: string }>
}

export type DirectorJobStatus = "queued" | "running" | "succeeded" | "failed" | "interrupted" | "cancelled"

export function jobVideoUrl(job: DirectorJobSnapshot | null | undefined): string | undefined {
  const output = job?.outputs?.find((item) => item.kind === "video")
  if (!output) return undefined
  return output.download_url || (output.path ? `/api/media/${encodeURIComponent(output.path)}` : undefined)
}

export function jobImageUrl(job: DirectorJobSnapshot | null | undefined): string | undefined {
  const output = job?.outputs?.find((item) => item.kind === "image") || job?.outputs?.[0]
  if (!output) return undefined
  return output.download_url || output.cloud_url || (output.path ? `/api/media/${encodeURIComponent(output.path)}` : undefined)
}

function looksLikeTechnicalJobError(text: string): boolean {
  const lower = text.toLowerCase()
  return (
    lower.includes("traceback")
    || lower.includes("exception_type")
    || lower.includes("exception_message")
    || lower.includes("execution_error")
    || text.includes("node_type")
    || /\.py[:\"'\s,]/.test(text)
    || /(?:[A-Za-z]:\\|\/comfyui\/)/i.test(text)
    || (text.includes("{") && text.includes("}") && text.length > 160)
  )
}

export function summarizeJobError(raw: string | null | undefined): { summary: string; detail: string } {
  const detail = String(raw || "").trim()
  if (!detail) return { summary: "", detail: "" }
  const compact = detail.replace(/\s+/g, " ")
  const lower = compact.toLowerCase()
  if (
    compact.includes("余额不足") || compact.includes("欠费") || compact.includes("额度不足") || compact.includes("魔粒不足")
    || lower.includes("insufficient") && (lower.includes("balance") || lower.includes("quota") || lower.includes("credit"))
    || lower.includes("arrear") || lower.includes("payment required") || lower.includes("exceeded your current quota")
  ) {
    return { summary: "大模型上游余额不足，请充值后再试。", detail }
  }
  if (
    lower.includes("outofmemory")
    || lower.includes("out of memory")
    || compact.includes("exceed allowed memory")
  ) {
    return { summary: "显存不足。请把分辨率改到 0.4 MP 后再生成。", detail }
  }
  if (compact.includes("ComfyUI 推理失败") || compact.includes("ComfyUI 报错") || lower.includes("execution_error")) {
    return { summary: "ComfyUI 推理失败。可查看详情排查。", detail }
  }
  if (looksLikeTechnicalJobError(compact)) {
    return { summary: "生成失败，可查看详情排查。", detail }
  }
  const firstLine = detail.split(/\r?\n/, 1)[0].trim()
  if (detail.length <= 120) return { summary: firstLine, detail }
  const clipped = firstLine.slice(0, 72).trimEnd()
  return { summary: `${clipped}…`, detail }
}

export function jobStoredImageUrl(job: DirectorJobSnapshot | null | undefined): string | undefined {
  const output = job?.outputs?.find((item) => item.kind === "image") || job?.outputs?.[0]
  if (!output) return undefined
  return output.cloud_url || output.download_url || (output.path ? `/api/media/${encodeURIComponent(output.path)}` : undefined)
}

export function assetPreviewUrl(
  job: DirectorJobSnapshot | null | undefined,
  imageUrl?: string | null,
  imageJobId?: string | null,
): string | undefined {
  const fromJob = jobImageUrl(job)
  if (fromJob) return fromJob
  if (imageUrl && imageUrl.startsWith("/api/")) return imageUrl
  if (imageJobId && (imageUrl || shotStatusFromJob(job) === "succeeded")) {
    return `/api/jobs/${imageJobId}/outputs/0/download`
  }
  return imageUrl || undefined
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

export function shotHasActiveRender(shot: {
  status?: string
  jobId?: string | null
  stillJobId?: string | null
}): boolean {
  if (shot.status === "running" || shot.status === "interrupted") return true
  if (shot.status === "queued" && Boolean(shot.jobId || shot.stillJobId)) return true
  return false
}

export function jobProgressFromJob(job: DirectorJobSnapshot | null | undefined, fallback = 0): number {
  if (shotStatusFromJob(job) === "succeeded") return 100
  const progress = job?.progress
  if (typeof progress === "number" && Number.isFinite(progress)) return Math.max(0, Math.min(100, Math.round(progress)))
  return fallback
}

export type AssetGenerationState = {
  status: "idle" | DirectorJobStatus
  progress: number
  generating: boolean
  label: string
  error?: string | null
}

function isPrepareStage(stage: string): boolean {
  return /切换工作流|正在准备|正在上传|正在提交文生|正在加载/.test(stage)
}

function runningProgressLabel(
  job: DirectorJobSnapshot | null | undefined,
  runningLabel: string,
  progress: number,
): string {
  const stage = (job?.stage || "").trim()
  if (!stage || stage === "等待排队" || isPrepareStage(stage)) return `${runningLabel} ${progress}%`
  return `${stage} ${progress}%`
}

function mediaGenerationState(
  job: DirectorJobSnapshot | null | undefined,
  resultUrl?: string | null,
  jobId?: string | null,
  noun = "生成",
  runningLabel?: string,
  fallback?: { status?: string; progress?: number },
): AssetGenerationState {
  const fromJob = job ? shotStatusFromJob(job) : null
  const fallbackStatus = fallback?.status
  const fromFallback = (
    fallbackStatus === "queued"
    || fallbackStatus === "running"
    || fallbackStatus === "failed"
    || fallbackStatus === "interrupted"
    || fallbackStatus === "cancelled"
  ) ? fallbackStatus : null
  const orphanedQueued = fromFallback === "queued" && !jobId && !resultUrl
  const jobStatus = fromJob || (orphanedQueued ? null : fromFallback) || (jobId && !resultUrl ? "queued" : null)
  if (jobStatus === "failed" || jobStatus === "interrupted" || jobStatus === "cancelled") {
    const label = jobStatus === "failed" ? `${noun}失败` : jobStatus === "cancelled" ? "已取消" : "已中断"
    return {
      status: jobStatus,
      progress: job ? jobProgressFromJob(job, 0) : 0,
      generating: false,
      label,
      error: job?.error || null,
    }
  }
  if (jobStatus === "queued" || jobStatus === "running") {
    const stage = (job?.stage || "").trim()
    const preparing = jobStatus === "running" && isPrepareStage(stage)
    const raw = job
      ? jobProgressFromJob(job, 0)
      : Math.max(0, Math.min(100, Math.round(fallback?.progress ?? 0)))
    const progress = jobStatus === "running" && !preparing ? Math.max(raw, 8) : raw
    const liveLabel = runningLabel || `${noun}生成中`
    return {
      status: jobStatus,
      progress,
      generating: true,
      label: jobStatus === "queued" ? `排队等待${noun}` : runningProgressLabel(job, liveLabel, progress),
    }
  }
  if (resultUrl) {
    return { status: "succeeded", progress: 100, generating: false, label: "" }
  }
  if (jobId) {
    return { status: "queued", progress: 0, generating: true, label: `排队等待${noun}` }
  }
  return { status: "idle", progress: 0, generating: false, label: "" }
}

export function assetGenerationState(
  job: DirectorJobSnapshot | null | undefined,
  imageUrl?: string | null,
  imageJobId?: string | null,
  kind: "character" | "location" = "character",
): AssetGenerationState {
  const noun = kind === "location" ? "场景图" : "定妆"
  return mediaGenerationState(job, imageUrl, imageJobId, noun)
}

export function shotGenerationState(
  job: DirectorJobSnapshot | null | undefined,
  outputVideoUrl?: string | null,
  jobId?: string | null,
  fallback?: { status?: string; progress?: number },
): AssetGenerationState {
  return mediaGenerationState(job, outputVideoUrl, jobId, "出片", "生成中", fallback)
}

export function overlaySubmittingState(
  state: AssetGenerationState,
  submitting: boolean,
  label: string,
): AssetGenerationState {
  if (!submitting) return state
  return {
    status: "queued",
    progress: Math.max(state.progress, 6),
    generating: true,
    label,
  }
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
      const fallback = job.status === "cancelled" ? "分镜任务已停止" : `分镜任务${job.status === "failed" ? "失败" : "已中断"}`
      throw new Error(summarizeJobError(job.error).summary || fallback)
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }
  throw new Error("等待分镜任务超时")
}
