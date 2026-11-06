export const KEYFRAME_WORKFLOW = "minimax-h3-keyframe"

export const KEYFRAME_REFERENCE_MAX_BYTES = 50 * 1024 * 1024
export const KEYFRAME_MIN = 2
export const KEYFRAME_MAX = 4

export type KeyframeReferenceAsset = {
  id: string
  file: File
  preview: string
}

/** 关键帧锚点：seconds 为画面出现时间(秒)；end=true 表示锚定到结尾帧。 */
export type KeyframeAnchor = { seconds: number; end: boolean }

export function keyframeReferenceError(file: Pick<File, "type" | "name" | "size">, label: string): string {
  if (!file.size) return `${label}不能为空文件`
  if (file.size > KEYFRAME_REFERENCE_MAX_BYTES) return `${label}不能超过 50 MB`
  return file.type.startsWith("image/") ? "" : `${label}必须是图片文件`
}

export function keyframeDurationSeconds(duration: unknown): number {
  const value = Number.parseFloat(String(duration ?? ""))
  return Number.isFinite(value) && value > 0 ? value : 5
}

/** 均匀分布参考值：第 2~N 张在 (0, duration] 内均分（仅供手动模式预填）。 */
export function evenAnchorSeconds(keyframeCount: number, durationSeconds: number): number[] {
  const slots = Math.max(1, keyframeCount - 1)
  const last = durationSeconds
  return Array.from({ length: slots }, (_, index) => {
    const raw = (last * (index + 1)) / slots
    return Math.round(raw * 10) / 10
  })
}

export function keyframeAnchorError(anchors: KeyframeAnchor[], durationSeconds: number): string {
  let previous = 0
  for (const anchor of anchors) {
    const current = anchor.end ? Number.POSITIVE_INFINITY : anchor.seconds
    if (!anchor.end && (!Number.isFinite(anchor.seconds) || anchor.seconds <= 0)) {
      return "锚点时间必须大于 0；开场关键帧固定在第 0 帧，无需单独指定"
    }
    if (!anchor.end && anchor.seconds > durationSeconds) {
      return `锚点时间不能超过 ${durationSeconds} 秒(当前生成时长)`
    }
    if (current <= previous) {
      return "锚点时间必须按关键帧顺序依次增大，且不能重复"
    }
    previous = current
  }
  return ""
}

/** 序列化成后端 anchor_seconds 选项；空数组表示均匀分布。 */
export function serializeKeyframeAnchors(anchors: KeyframeAnchor[]): string {
  return anchors.map((anchor) => (anchor.end ? "-1" : String(anchor.seconds))).join(",")
}

export {
  motionToolOptions as keyframeToolOptions,
  motionToolDefaults as keyframeToolDefaults,
  motionToolPayload as keyframeToolPayload,
  type ToolOptionDefinition,
} from "./motion-transfer"
