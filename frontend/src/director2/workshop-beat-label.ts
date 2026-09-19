export const TAKE_ROLE_LABELS: Record<string, string> = {
  lipsync: "口型",
  inner_hold: "内心覆盖",
  push_close: "近景定性",
}

export type WorkshopBeatLabelSource = {
  sequence?: number | string | null
  story_shot?: number | string | null
  take_role?: string | null
  parent_beat_id?: string | null
}

export function workshopStoryShot(beat: WorkshopBeatLabelSource | null | undefined): number {
  const value = Number(beat?.story_shot || beat?.sequence || 0)
  return Number.isFinite(value) && value > 0 ? value : 1
}

export function workshopTakeRoleLabel(role: string | null | undefined): string {
  const key = String(role || "").trim()
  return TAKE_ROLE_LABELS[key] || ""
}

export function workshopBeatLabel(beat: WorkshopBeatLabelSource | null | undefined): string {
  const story = workshopStoryShot(beat)
  const role = workshopTakeRoleLabel(beat?.take_role)
  return role ? `镜头${story} · ${role}` : `镜头${story}`
}

export function workshopBeatHasSplitTakes<T extends WorkshopBeatLabelSource & { id?: string }>(
  beat: T | null | undefined,
  beats: T[] | null | undefined,
): boolean {
  if (!beat) return false
  if (String(beat.take_role || "").trim() || String(beat.parent_beat_id || "").trim()) return true
  const beatId = String(beat.id || "")
  if (!beatId) return false
  return (beats || []).some((item) => String(item.parent_beat_id || "") === beatId)
}
