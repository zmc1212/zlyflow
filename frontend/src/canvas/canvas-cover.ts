import type { CanvasNodeData } from "./canvas-model"

export const CANVAS_COVER_MAX_EDGE = 320
export const CANVAS_COVER_QUALITY = 0.66
export const CANVAS_COVER_MAX_DATA_URL = 64_000
export const CANVAS_COVER_CAPTURE_TIMEOUT = 10_000
export const CANVAS_COVER_FILE_MAX_BYTES = 16 * 1024 * 1024
export const CANVAS_COVER_CROP_MAX_ZOOM = 4

const COVER_PATTERN = /^data:image\/(?:jpeg|webp|png);base64,[A-Za-z0-9+/]+={0,2}$/
const COVER_REQUESTS_LIMIT = 40

export type CanvasCoverCapture = {
  cover: string
  time: number
  width: number
  height: number
}

export type CanvasCoverCropAspect = "original" | "16:9" | "9:16" | "1:1"

/** 源图坐标中的裁切区域，单位与图片自然像素一致。 */
export type CanvasCoverCropRect = {
  x: number
  y: number
  width: number
  height: number
}

export type CanvasCoverFocus = {
  x: number
  y: number
}

export function normalizeCanvasCover(value: unknown): string | null {
  if (typeof value !== "string") return null
  const cover = value.trim()
  if (!cover || cover.length > CANVAS_COVER_MAX_DATA_URL) return null
  return COVER_PATTERN.test(cover) ? cover : null
}

/** 只有封面来源与当前视频地址一致时才使用，避免换素材后显示旧封面。 */
export function readCanvasCover(data: CanvasNodeData): string | null {
  const cover = normalizeCanvasCover(data.cover)
  if (!cover) return null
  const url = typeof data.url === "string" ? data.url.trim() : ""
  const source = typeof data.coverSource === "string" ? data.coverSource.trim() : ""
  return url && source === url ? cover : null
}

export function canvasCoverCaptureTime(duration: number): number {
  if (!Number.isFinite(duration) || duration <= 0) return 0
  if (duration <= 0.25) return 0
  const target = Math.min(Math.max(duration * 0.1, 0.1), 1.5)
  return Math.min(target, Math.max(0, duration - 0.05))
}

/** 把用户输入的取帧秒数收敛到视频可播放范围内；非法输入回落到 0。 */
export function clampCanvasCoverTime(time: number, duration: number): number {
  if (!Number.isFinite(time) || time <= 0) return 0
  if (!Number.isFinite(duration) || duration <= 0) return 0
  return Math.min(time, Math.max(0, duration - 0.05))
}

export function canvasCoverFrameSize(
  width: number,
  height: number,
  maxEdge = CANVAS_COVER_MAX_EDGE,
): { width: number; height: number } | null {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null
  const scale = Math.min(1, maxEdge / Math.max(width, height))
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  }
}

export function canvasCoverSummary(cover: string, time: unknown): string {
  const kilobytes = Math.max(1, Math.round(cover.length / 1024))
  const seconds = typeof time === "number" && Number.isFinite(time) && time > 0
    ? `取帧 ${time.toFixed(1)} 秒 · `
    : ""
  return `${seconds}${kilobytes} KB`
}

/** 预设比例的宽高比；原始比例按图片实际尺寸回退，非法尺寸返回 16:9。 */
export function canvasCoverAspectRatio(
  aspect: CanvasCoverCropAspect,
  width: number,
  height: number,
): number {
  if (aspect === "16:9") return 16 / 9
  if (aspect === "9:16") return 9 / 16
  if (aspect === "1:1") return 1
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    return width / height
  }
  return 16 / 9
}

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/**
 * 按比例在源图中取最大可用裁切框，再按 zoom 与焦点缩小；
 * 焦点是裁切框中心在图片上的归一化位置，超出边界时自动贴边。
 */
export function canvasCoverCropRect(
  imageWidth: number,
  imageHeight: number,
  aspectRatio: number,
  zoom: number,
  focus: CanvasCoverFocus,
): CanvasCoverCropRect | null {
  if (!Number.isFinite(imageWidth) || !Number.isFinite(imageHeight) || imageWidth <= 0 || imageHeight <= 0) {
    return null
  }
  if (!Number.isFinite(aspectRatio) || aspectRatio <= 0) return null
  const imageAspect = imageWidth / imageHeight
  let width = imageWidth
  let height = imageHeight
  if (imageAspect > aspectRatio) width = imageHeight * aspectRatio
  else height = imageWidth / aspectRatio
  // 比例正好相等时浮点除法可能略大于图片高度，先夹回源图范围。
  width = Math.min(width, imageWidth)
  height = Math.min(height, imageHeight)
  const zoomFactor = Number.isFinite(zoom)
    ? Math.min(CANVAS_COVER_CROP_MAX_ZOOM, Math.max(1, zoom))
    : 1
  width /= zoomFactor
  height /= zoomFactor
  const fx = clampUnit(Number.isFinite(focus.x) ? focus.x : 0.5)
  const fy = clampUnit(Number.isFinite(focus.y) ? focus.y : 0.5)
  const x = Math.min(Math.max(fx * imageWidth - width / 2, 0), imageWidth - width)
  const y = Math.min(Math.max(fy * imageHeight - height / 2, 0), imageHeight - height)
  return { x, y, width, height }
}

/** 裁切框中心换算回归一化焦点，供拖拽前读取当前视野。 */
export function canvasCoverCropFocus(
  crop: CanvasCoverCropRect,
  imageWidth: number,
  imageHeight: number,
): CanvasCoverFocus | null {
  if (
    !Number.isFinite(imageWidth) || !Number.isFinite(imageHeight) || imageWidth <= 0 || imageHeight <= 0
    || !Number.isFinite(crop.x) || !Number.isFinite(crop.y)
    || !Number.isFinite(crop.width) || !Number.isFinite(crop.height)
    || crop.width <= 0 || crop.height <= 0
  ) {
    return null
  }
  return {
    x: (crop.x + crop.width / 2) / imageWidth,
    y: (crop.y + crop.height / 2) / imageHeight,
  }
}

/**
 * 舞台按裁切框等比显示图片：向右拖动图片等于裁切框左移，返回新的归一化焦点。
 * 屏幕位移经 stageWidth / crop.width 换算回源图像素。
 */
export function moveCanvasCoverCropFocus(
  imageWidth: number,
  imageHeight: number,
  crop: CanvasCoverCropRect,
  stageWidth: number,
  stageHeight: number,
  deltaX: number,
  deltaY: number,
): CanvasCoverFocus | null {
  const focus = canvasCoverCropFocus(crop, imageWidth, imageHeight)
  if (!focus) return null
  if (
    !Number.isFinite(stageWidth) || !Number.isFinite(stageHeight) || stageWidth <= 0 || stageHeight <= 0
    || !Number.isFinite(deltaX) || !Number.isFinite(deltaY)
  ) {
    return null
  }
  const scaleX = stageWidth / crop.width
  const scaleY = stageHeight / crop.height
  return {
    x: clampUnit(focus.x - deltaX / scaleX / imageWidth),
    y: clampUnit(focus.y - deltaY / scaleY / imageHeight),
  }
}

function resolveCoverCrop(
  imageWidth: number,
  imageHeight: number,
  crop?: CanvasCoverCropRect,
): CanvasCoverCropRect | null {
  if (!crop) return null
  if (
    !Number.isFinite(crop.x) || !Number.isFinite(crop.y)
    || !Number.isFinite(crop.width) || !Number.isFinite(crop.height)
    || crop.width <= 0 || crop.height <= 0
  ) {
    return null
  }
  const x = Math.min(Math.max(crop.x, 0), imageWidth)
  const y = Math.min(Math.max(crop.y, 0), imageHeight)
  const width = Math.min(crop.width, imageWidth - x)
  const height = Math.min(crop.height, imageHeight - y)
  return width > 0 && height > 0 ? { x, y, width, height } : null
}

export function captureCanvasCoverFromVideo(video: HTMLVideoElement): CanvasCoverCapture | null {
  if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) return null
  for (const attempt of [
    { maxEdge: CANVAS_COVER_MAX_EDGE, quality: CANVAS_COVER_QUALITY },
    { maxEdge: 240, quality: 0.55 },
  ]) {
    const size = canvasCoverFrameSize(video.videoWidth, video.videoHeight, attempt.maxEdge)
    if (!size) return null
    const canvas = document.createElement("canvas")
    canvas.width = size.width
    canvas.height = size.height
    const context = canvas.getContext("2d")
    if (!context) return null
    try {
      context.drawImage(video, 0, 0, size.width, size.height)
      const cover = normalizeCanvasCover(canvas.toDataURL("image/jpeg", attempt.quality))
      if (cover) {
        return {
          cover,
          time: Number.isFinite(video.currentTime) ? video.currentTime : 0,
          width: size.width,
          height: size.height,
        }
      }
    } catch {
      // 跨域视频未开启 CORS 时画布会被污染，无法导出帧，保留原有占位。
      return null
    }
  }
  return null
}

const coverRequests = new Map<string, Promise<CanvasCoverCapture | null>>()

/**
 * 通过离屏 video 取帧，避免影响节点上的播放元素；同一地址+时间在一次会话内只请求一次。
 * 传入 time 时按指定秒数取帧，否则取开头附近代表帧；跨域地址需目标服务器允许 CORS。
 */
export function requestCanvasCoverCapture(url: string, time?: number): Promise<CanvasCoverCapture | null> {
  const target = url.trim()
  if (!target) return Promise.resolve(null)
  const requested = typeof time === "number" && Number.isFinite(time) && time >= 0
    ? Math.round(time * 100) / 100
    : undefined
  const key = requested === undefined ? target : `${target}#${requested}`
  const cached = coverRequests.get(key)
  if (cached) return cached
  const request = captureCanvasCoverFromUrl(target, requested)
  coverRequests.set(key, request)
  if (coverRequests.size > COVER_REQUESTS_LIMIT) {
    const oldest = coverRequests.keys().next().value
    if (oldest) coverRequests.delete(oldest)
  }
  return request
}

/** 清除地址的取帧缓存（含指定时间点），让下一次自动取帧重新请求视频。 */
export function forgetCanvasCoverCapture(url: string): void {
  const target = url.trim()
  if (!target) return
  for (const key of [...coverRequests.keys()]) {
    if (key === target || key.startsWith(`${target}#`)) coverRequests.delete(key)
  }
}

/** 把本地图片按可选裁切区域压缩成与自动取帧一致的封面；失败或超限返回 null。 */
export function canvasCoverFromFile(
  file: File,
  crop?: CanvasCoverCropRect,
): Promise<CanvasCoverCapture | null> {
  if (typeof document === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return Promise.resolve(null)
  }
  if (!file.type.startsWith("image/") || file.size <= 0 || file.size > CANVAS_COVER_FILE_MAX_BYTES) {
    return Promise.resolve(null)
  }
  return new Promise((resolve) => {
    const objectUrl = URL.createObjectURL(file)
    const image = new Image()
    let settled = false
    const finish = (value: CanvasCoverCapture | null) => {
      if (settled) return
      settled = true
      image.onload = null
      image.onerror = null
      URL.revokeObjectURL(objectUrl)
      resolve(value)
    }
    image.onload = () => {
      const source = resolveCoverCrop(image.naturalWidth, image.naturalHeight, crop)
      const sourceWidth = source?.width ?? image.naturalWidth
      const sourceHeight = source?.height ?? image.naturalHeight
      for (const attempt of [
        { maxEdge: CANVAS_COVER_MAX_EDGE, quality: CANVAS_COVER_QUALITY },
        { maxEdge: 240, quality: 0.55 },
        { maxEdge: 200, quality: 0.45 },
      ]) {
        const size = canvasCoverFrameSize(sourceWidth, sourceHeight, attempt.maxEdge)
        if (!size) {
          finish(null)
          return
        }
        const canvas = document.createElement("canvas")
        canvas.width = size.width
        canvas.height = size.height
        const context = canvas.getContext("2d")
        if (!context) {
          finish(null)
          return
        }
        try {
          if (source) {
            context.drawImage(image, source.x, source.y, source.width, source.height, 0, 0, size.width, size.height)
          } else {
            context.drawImage(image, 0, 0, size.width, size.height)
          }
          const cover = normalizeCanvasCover(canvas.toDataURL("image/jpeg", attempt.quality))
          if (cover) {
            finish({ cover, time: 0, width: size.width, height: size.height })
            return
          }
        } catch {
          finish(null)
          return
        }
      }
      finish(null)
    }
    image.onerror = () => finish(null)
    image.src = objectUrl
  })
}

function captureCanvasCoverFromUrl(url: string, requestedTime?: number): Promise<CanvasCoverCapture | null> {
  if (typeof document === "undefined") return Promise.resolve(null)
  return new Promise((resolve) => {
    const video = document.createElement("video")
    video.crossOrigin = "anonymous"
    video.muted = true
    video.playsInline = true
    video.preload = "metadata"
    video.style.cssText = "position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none"
    let settled = false
    let captureTime = 0
    let timer = 0

    const finish = (value: CanvasCoverCapture | null) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      video.removeEventListener("loadedmetadata", onLoadedMetadata)
      video.removeEventListener("loadeddata", onLoadedData)
      video.removeEventListener("seeked", tryCapture)
      video.removeEventListener("error", onError)
      video.pause()
      video.removeAttribute("src")
      video.load()
      video.remove()
      resolve(value)
    }

    const tryCapture = () => {
      const capture = captureCanvasCoverFromVideo(video)
      if (capture) finish(capture)
    }

    const onLoadedMetadata = () => {
      captureTime = requestedTime === undefined
        ? canvasCoverCaptureTime(video.duration)
        : clampCanvasCoverTime(requestedTime, video.duration)
      if (captureTime > 0 && Math.abs(video.currentTime - captureTime) > 0.01) {
        video.currentTime = captureTime
      }
    }
    const onLoadedData = () => {
      if (captureTime <= 0) tryCapture()
    }
    const onError = () => finish(null)

    timer = window.setTimeout(() => {
      tryCapture()
      finish(null)
    }, CANVAS_COVER_CAPTURE_TIMEOUT)
    video.addEventListener("loadedmetadata", onLoadedMetadata)
    video.addEventListener("loadeddata", onLoadedData)
    video.addEventListener("seeked", tryCapture)
    video.addEventListener("error", onError)
    video.src = url
    document.body.appendChild(video)
  })
}
