import { DIRECTOR2_VIDEO_FALLBACK_FIELDS } from "./director2-video-settings"

export const DEFAULT_WORKSHOP_ASPECT = "9:16"
export const WORKSHOP_ASPECT_KEY = "workshop_aspect_ratio"

export type WorkshopAspectHint = {
  suggested?: string
  hits?: string[]
  conflicts?: string[]
  explicit?: string[]
  source?: string
}

export type WorkshopAspectOption = {
  value: string
  label: string
}

const fallbackAspectField = DIRECTOR2_VIDEO_FALLBACK_FIELDS.find((field) => field.name === "aspect_ratio")

export const WORKSHOP_ASPECT_OPTIONS: WorkshopAspectOption[] = (
  fallbackAspectField?.definition.ui_options || [
    { value: "9:16", label: "9:16 竖屏" },
    { value: "16:9", label: "16:9 横屏" },
    { value: "1:1", label: "1:1 方形" },
  ]
).map((item) => ({ value: String(item.value), label: item.label }))

export function workshopAspectFromExtra(extra: unknown): string {
  if (!extra || typeof extra !== "object") return ""
  const record = extra as Record<string, unknown>
  const nested = record.extra
  const source = nested && typeof nested === "object" ? nested as Record<string, unknown> : record
  return String(source[WORKSHOP_ASPECT_KEY] || "").replace(/\s+/g, "").replace("：", ":").trim()
}

export function videoSettingsWithWorkshopAspect(
  saved: Record<string, string> | null | undefined,
  extra: unknown,
): Record<string, string> | null {
  const aspect = workshopAspectFromExtra(extra)
  if (!aspect) return saved ?? null
  return { ...(saved || {}), aspect_ratio: aspect }
}

export function uniqueAspectHits(hint: WorkshopAspectHint | null | undefined): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const token of hint?.hits || []) {
    const text = String(token || "").trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

export function aspectConfirmDescription(hint: WorkshopAspectHint | null | undefined, aspect?: string): string {
  const hits = uniqueAspectHits(hint)
  const conflicts = (hint?.conflicts || []).filter(Boolean)
  const chosen = String(aspect || hint?.suggested || DEFAULT_WORKSHOP_ASPECT).trim() || DEFAULT_WORKSHOP_ASPECT
  const suffix = "请确认成片画幅。后续镜头规划、H3 写稿和出片都按这个。"
  if (conflicts.length >= 2) {
    return `剧本原文同时提到了 ${conflicts.join(" 和 ")}，${suffix}`
  }
  if (hits.length) {
    return `剧本原文提到了 ${hits.join("、")}，建议 ${chosen}。${suffix}`
  }
  return `剧本没有写明画幅，建议用 ${chosen}。${suffix}`
}

export function isAwaitingAspectDocument(doc: { status?: string | null } | null | undefined): boolean {
  return String(doc?.status || "") === "awaiting_aspect"
}

export function documentNeedsAspectConfirm(doc: {
  status?: string | null
  shot_plan_job_id?: string | null
  needs_shot_plan?: boolean
} | null | undefined): boolean {
  if (!doc) return false
  if (isAwaitingAspectDocument(doc)) return true
  return Boolean(doc.needs_shot_plan) && !doc.shot_plan_job_id
}
