import type { Director2Beat } from "./api"

export function selectedWorkshopBeatIds(beats: Pick<Director2Beat, "id">[], checked: ReadonlySet<string>) {
  return beats.filter(beat => checked.has(beat.id)).map(beat => beat.id)
}

export function workshopBatchDeleteReason(total: number, selected: number, busy: boolean) {
  if (!selected) return "请先选择片段"
  if (selected >= total) return "至少保留 1 个片段"
  if (busy) return "选中片段正在生成，请完成后再删除"
  return ""
}

export function activeBeatAfterDelete(before: Pick<Director2Beat, "id">[], after: Pick<Director2Beat, "id">[], selected: string | null) {
  if (after.some(beat => beat.id === selected)) return selected
  const index = Math.max(0, before.findIndex(beat => beat.id === selected))
  return after[Math.min(index, after.length - 1)]?.id || null
}
