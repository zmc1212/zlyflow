/** 资产库左侧列表在一键/单条生图时的行内进度。 */

export type AssetRowGenStatus = "queued" | "generating" | "failed"

export type AssetRowGenState = {
  status: AssetRowGenStatus
  label: string
  percent: number
}

export function seedQueuedAssetRows(
  assetIds: string[],
  label: string,
): Record<string, AssetRowGenState> {
  const next: Record<string, AssetRowGenState> = {}
  const suffix = String(label || "").trim()
  for (const raw of assetIds) {
    const id = String(raw || "").trim()
    if (!id || next[id]) continue
    next[id] = {
      status: "queued",
      label: suffix ? `排队生成${suffix}` : "排队中",
      percent: 0,
    }
  }
  return next
}

export function markAssetRowGenerating(
  prev: Record<string, AssetRowGenState>,
  assetId: string,
  label: string,
): Record<string, AssetRowGenState> {
  const id = String(assetId || "").trim()
  if (!id) return prev
  const current = prev[id]
  const percent = current?.status === "generating" ? Math.max(8, current.percent) : 8
  return {
    ...prev,
    [id]: {
      status: "generating",
      label: String(label || "正在生成").trim() || "正在生成",
      percent,
    },
  }
}

export function markAssetRowFailed(
  prev: Record<string, AssetRowGenState>,
  assetId: string,
  label: string,
): Record<string, AssetRowGenState> {
  const id = String(assetId || "").trim()
  if (!id) return prev
  return {
    ...prev,
    [id]: {
      status: "failed",
      label: String(label || "生成失败").trim() || "生成失败",
      percent: 100,
    },
  }
}

export function clearAssetRow(
  prev: Record<string, AssetRowGenState>,
  assetId: string,
): Record<string, AssetRowGenState> {
  const id = String(assetId || "").trim()
  if (!id || !(id in prev)) return prev
  const next = { ...prev }
  delete next[id]
  return next
}

export function tickAssetRowPercent(percent: number): number {
  const current = Math.max(0, Math.round(Number(percent) || 0))
  if (current >= 92) return 92
  if (current < 8) return 8
  if (current < 28) return current + 6
  if (current < 52) return current + 4
  if (current < 72) return current + 2
  return Math.min(92, current + 1)
}

export function tickGeneratingAssetRows(
  prev: Record<string, AssetRowGenState>,
): Record<string, AssetRowGenState> {
  let changed = false
  const next: Record<string, AssetRowGenState> = {}
  for (const [id, state] of Object.entries(prev)) {
    if (state.status !== "generating") {
      next[id] = state
      continue
    }
    const percent = tickAssetRowPercent(state.percent)
    if (percent !== state.percent) {
      changed = true
      next[id] = { ...state, percent }
    } else {
      next[id] = state
    }
  }
  return changed ? next : prev
}

export function hasGeneratingAssetRow(rows: Record<string, AssetRowGenState>): boolean {
  return Object.values(rows).some((state) => state.status === "generating")
}

export function assetRowProgressPercent(state: AssetRowGenState): number {
  if (state.status === "queued") return 0
  if (state.status === "failed") return 100
  return Math.max(0, Math.min(99, Math.round(state.percent)))
}

export function assetRowProgressStatus(status: AssetRowGenStatus): "normal" | "active" | "exception" {
  if (status === "failed") return "exception"
  if (status === "generating") return "active"
  return "normal"
}

export function assetRowGenDisplayLabel(state: AssetRowGenState): string {
  if (state.status === "queued") return state.label || "排队中"
  if (state.status === "failed") return state.label || "生成失败"
  const pct = Math.max(0, Math.round(state.percent))
  return `${state.label || "正在生成"} ${pct}%`
}

export function hasLaterJobForAsset<T extends { ast: { id: string } }>(
  jobs: T[],
  index: number,
  assetId: string,
): boolean {
  const id = String(assetId || "").trim()
  if (!id) return false
  return jobs.slice(index + 1).some((job) => String(job.ast.id) === id)
}

export function lookBatchProgressLabel(
  jobs: Array<{ ast: { id: string }; ident: { name?: string | null } }>,
  index: number,
): string {
  const job = jobs[index]
  if (!job) return "正在生成设定板"
  const assetId = String(job.ast.id || "")
  const sameIndices: number[] = []
  jobs.forEach((item, itemIndex) => {
    if (String(item.ast.id) === assetId) sameIndices.push(itemIndex)
  })
  const position = sameIndices.indexOf(index) + 1
  const total = sameIndices.length
  const name = String(job.ident.name || "造型").trim() || "造型"
  if (total > 1) return `正在生成设定板 ${position}/${total} · ${name}`
  return `正在生成设定板 · ${name}`
}
