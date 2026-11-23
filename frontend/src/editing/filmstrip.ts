/**
 * 即梦式胶片带：为时间线片段抽取视频帧（图片直接用原图平铺）。
 *
 * - `assetFrames(url)`：正方形帧数组（暗帧自动避让一次），供迷你节点按宽平铺。
 * - 附带 `strip`：全部帧横向拼接成一张长条 dataURL，供全屏时间线做 repeat-x 背景。
 * 结果按 url 模块级缓存；拿不到帧时返回空数组/空串，调用方回落纯色片段块。
 */

const FRAME_SIDE = 96
const FRAME_COUNT = 10
const CAPTURE_TIMEOUT_MS = 15000

export type FilmstripResult = { frames: string[]; strip: string }

const frameCache = new Map<string, Promise<FilmstripResult>>()

export function assetFrames(url: string): Promise<FilmstripResult> {
  if (!url) return Promise.resolve({ frames: [], strip: "" })
  const cached = frameCache.get(url)
  if (cached) return cached
  const job = captureVideoFrames(url)
  frameCache.set(url, job)
  return job
}

/** 静态图：单帧循环平铺，无抽帧开销。 */
export function imageFrames(asset: { thumbnail?: string | null; url: string }): FilmstripResult {
  const url = asset.thumbnail || asset.url
  return url ? { frames: [url], strip: "" } : { frames: [], strip: "" }
}

function captureVideoFrames(url: string): Promise<FilmstripResult> {
  return new Promise((resolve) => {
    const video = document.createElement("video")
    video.crossOrigin = "anonymous"
    video.muted = true
    video.preload = "auto"
    let settled = false
    let frames: string[] = []
    const canvas = document.createElement("canvas")
    canvas.width = FRAME_SIDE * FRAME_COUNT
    canvas.height = FRAME_SIDE
    const paint = canvas.getContext("2d")
    let stamps: number[] = []
    let index = 0
    let darkRetries = 0

    const finish = (result: FilmstripResult) => {
      if (settled) return
      settled = true
      resolve(result)
    }
    const stripOf = () => {
      try {
        if (!frames.length || !paint) return ""
        // 捕获中断时尾部槽位重复最后一帧，避免长条出现黑尾
        const drawn = frames.length
        for (let i = drawn; i < stamps.length; i++) {
          paint.drawImage(canvas, (drawn - 1) * FRAME_SIDE, 0, FRAME_SIDE, FRAME_SIDE, i * FRAME_SIDE, 0, FRAME_SIDE, FRAME_SIDE)
        }
        return canvas.toDataURL("image/jpeg", 0.6)
      } catch {
        return ""
      }
    }
    const fail = () => finish({ frames: [], strip: "" })

    if (!paint) {
      fail()
      return
    }
    window.setTimeout(() => finish({ frames, strip: stripOf() }), CAPTURE_TIMEOUT_MS)

    const grab = () => {
      if (index >= stamps.length) return finish({ frames, strip: stripOf() })
      video.currentTime = stamps[index]
    }

    video.onseeked = () => {
      try {
        const vw = video.videoWidth
        const vh = video.videoHeight
        if (!vw || !vh) throw new Error("no frame")
        const slot = index * FRAME_SIDE
        const side = Math.min(vw, vh)
        paint.drawImage(video, (vw - side) / 2, (vh - side) / 2, side, side, slot, 0, FRAME_SIDE, FRAME_SIDE)
        // 暗帧避让：开帧近黑时向后挪一点重试一次，避免整条胶片从黑场开始
        const sample = paint.getImageData(slot + FRAME_SIDE / 2, FRAME_SIDE / 2, 1, 1).data
        if ((sample[0] + sample[1] + sample[2]) / 3 < 8 && darkRetries < 1) {
          darkRetries += 1
          video.currentTime = Math.min((stamps[0] || 0) + 0.6, stamps[stamps.length - 1] || 1)
          return
        }
        frames.push(cropFrame(paint.canvas, slot))
        if (!frames[frames.length - 1]) {
          // 画布被跨域污染：丢弃空帧，交付已到手的帧走纯色兜底
          frames.pop()
          finish({ frames, strip: "" })
          return
        }
        index += 1
        grab()
      } catch {
        // 跨域污染或取帧失败：交付已到手的帧
        finish({ frames, strip: stripOf() })
      }
    }
    video.onerror = () => {
      // 七牛视频已带 CORS；个别源不支持时退回无 crossOrigin 再试一次
      if (video.hasAttribute("crossorigin")) {
        video.removeAttribute("crossorigin")
        video.load()
        return
      }
      fail()
    }
    video.onloadedmetadata = () => {
      const duration = video.duration
      if (!Number.isFinite(duration) || duration <= 0) return fail()
      const start = Math.min(0.05 * duration, 0.5)
      const end = Math.max(start + 0.1, 0.95 * duration)
      stamps = Array.from({ length: FRAME_COUNT }, (_, i) => start + ((end - start) * (i + 0.5)) / FRAME_COUNT)
      grab()
    }
    video.src = url
  })
}

/** 从长条画布上裁出第 slot 格作为独立帧 dataURL（迷你节点按帧平铺用）。 */
function cropFrame(source: HTMLCanvasElement, slot: number): string {
  const frame = document.createElement("canvas")
  frame.width = FRAME_SIDE
  frame.height = FRAME_SIDE
  const ctx = frame.getContext("2d")
  if (!ctx) return ""
  ctx.drawImage(source, slot, 0, FRAME_SIDE, FRAME_SIDE, 0, 0, FRAME_SIDE, FRAME_SIDE)
  try {
    return frame.toDataURL("image/jpeg", 0.6)
  } catch {
    return ""
  }
}
