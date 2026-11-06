export const MOTION_TRANSFER_WORKFLOW = "scail2-replacement"
/** 骨架 ControlNet 版（SDPose 驱动，单人）。 */
export const MOTION_SKELETON_WORKFLOW = "minimax-h3-motion-transfer"
/** 多人参考视频版（动作视频直接进 <Video 1>，1-6 角色）。 */
export const MOTION_REF_VIDEO_WORKFLOW = "minimax-h3-motion-ref-video"
/** 工具中心「动作迁移」统一入口支持的迁移方式；展示元数据一律取自注册表，不在前端硬编码。 */
export const MOTION_TOOL_WORKFLOWS: readonly string[] = [MOTION_TRANSFER_WORKFLOW, MOTION_SKELETON_WORKFLOW, MOTION_REF_VIDEO_WORKFLOW]

/** 动作迁移族的图片槽上限:由 reference_slots 声明(多人版 1-6);未声明时沿用单人版 1 图。 */
export function motionImageLimit(wf?: { accepts_video_reference?: boolean; reference_slots?: string[] } | null): number {
  if (!wf?.accepts_video_reference) return 0
  const slots = wf.reference_slots ?? []
  if (!slots.length || slots[slots.length - 1] !== "video") return 1
  return Math.max(1, slots.filter((slot) => slot === "image").length)
}

export type SubjectPoint = { x: number; y: number; exclude: boolean; subject?: number }

export function hasSubject(points: SubjectPoint[], subject = 0): boolean {
  return points.some((point) => !point.exclude && (point.subject ?? 0) === subject)
}

export function hasSubjects(points: SubjectPoint[], count: number): boolean {
  return Array.from({ length: count }, (_, subject) => subject).every((subject) => hasSubject(points, subject))
}

export function subjectPointAt(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }, exclude = false): SubjectPoint | null {
  if (!rect.width || !rect.height) return null
  const x = (clientX - rect.left) / rect.width
  const y = (clientY - rect.top) / rect.height
  return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? { x, y, exclude } : null
}
export const REFERENCE_MAX_BYTES = 50 * 1024 * 1024

export type MotionReferenceAsset = {
  id: string
  file: File
  preview: string
  duration?: number
}

export function motionReferenceError(file: Pick<File, "type" | "name" | "size">, kind: "image" | "video"): string {
  const label = kind === "image" ? "角色形象图" : "动作参考视频"
  if (!file.size) return `${label}不能为空文件`
  if (file.size > REFERENCE_MAX_BYTES) return `${label}不能超过 50 MB`
  if (kind === "image") return file.type.startsWith("image/") ? "" : "角色形象图必须是图片文件"
  const extensionMatches = /\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("video/")
  return extensionMatches && typeMatches ? "" : "请上传 MP4 / MOV / WebM 等动作参考视频"
}

export function motionDurationError(seconds: number | undefined, duration: unknown, limits?: { min_source_seconds?: number; max_source_seconds?: number }): string {
  if (duration === "full" && seconds !== undefined && Number.isFinite(seconds)) {
    if (limits?.min_source_seconds && seconds < limits.min_source_seconds) return `完整原片至少需要 ${limits.min_source_seconds} 秒`
    if (limits?.max_source_seconds && seconds > limits.max_source_seconds) return `完整原片不能超过 ${limits.max_source_seconds} 秒`
    return ""
  }
  const required = Number.parseFloat(String(duration))
  if (seconds === undefined || !Number.isFinite(seconds) || !Number.isFinite(required)) return ""
  return seconds + 0.1 < required
    ? `动作视频只有 ${seconds.toFixed(1)} 秒，请选择更短的生成时长或更换视频`
    : ""
}

export type ToolOptionDefinition = {
  label: string
  type: "string" | "number" | "integer" | "boolean"
  default: string | number | boolean
  enum?: (string | number)[]
  minimum?: number
  maximum?: number
  step?: number
  description?: string
  min_source_seconds?: number
  max_source_seconds?: number
  ui_group?: "primary" | "advanced" | "internal"
  ui_options?: { value: string | number; label: string; hint?: string }[]
}

export type ToolOptionControl = {
  name: string
  definition: ToolOptionDefinition
  control: "select" | "slider" | "number" | "switch"
  options: { value: string; label: string }[]
}

/** Derive the tool-page controls from the registry schema; the backend stays the only rule source. */
export function motionToolOptions(
  properties: Record<string, ToolOptionDefinition> | undefined | null,
): ToolOptionControl[] {
  if (!properties) return []
  return Object.entries(properties)
    .filter(([, definition]) => definition.ui_group === "primary" || definition.ui_group === "advanced")
    .map(([name, definition]) => {
      const options = (definition.ui_options ?? definition.enum?.map((value) => ({ value, label: String(value) })) ?? [])
        .map((item) => ({ value: String(item.value), label: String(item.label) }))
      let control: ToolOptionControl["control"] = "number"
      if (options.length) control = "select"
      else if (definition.type === "boolean") control = "switch"
      else if (
        typeof definition.minimum === "number" && typeof definition.maximum === "number"
        && (definition.maximum - definition.minimum) / (definition.step || 1) <= 40
      ) control = "slider"
      return { name, definition, control, options }
    })
}

export function motionToolDefaults(
  properties: Record<string, ToolOptionDefinition> | undefined | null,
): Record<string, string | number | boolean> {
  if (!properties) return {}
  return Object.fromEntries(
    Object.entries(properties)
      .filter(([, definition]) => definition.ui_group === "primary" || definition.ui_group === "advanced")
      .map(([name, definition]) => [name, definition.default]),
  )
}

/** Serialize composer-style values back into the options JSON accepted by POST /api/jobs. */
export function motionToolPayload(values: Record<string, string | number | boolean>): Record<string, string | number | boolean> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== "" && value !== undefined))
}
