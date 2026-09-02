import {
  ensureRecipeAssetRendition,
  recipeApprovableAssetVersion,
  recipeApprovedAssetVersion,
  recipeAssetVersionRuntimeStatus,
  type RecipeAssetJobStatusSource,
  type RecipeAssetRendition,
} from "./recipe-model"

export interface SimpleAssetStageCounts {
  total: number
  approved: number
  approvable: number
  idle: number
  running: number
}

type SimpleAssetLike = {
  imageUrl?: string | null
  plate?: RecipeAssetRendition
  turnaround?: RecipeAssetRendition
}

export function simpleAssetStageCounts(
  items: SimpleAssetLike[],
  renditionKey: "plate" | "turnaround",
  jobs?: RecipeAssetJobStatusSource[],
): SimpleAssetStageCounts {
  const counts: SimpleAssetStageCounts = {
    total: items.length,
    approved: 0,
    approvable: 0,
    idle: 0,
    running: 0,
  }
  for (const item of items) {
    const rendition = ensureRecipeAssetRendition(renditionKey === "plate" ? item.plate : item.turnaround)
    if (item.imageUrl || recipeApprovedAssetVersion(rendition)) {
      counts.approved += 1
      continue
    }
    if (recipeApprovableAssetVersion(rendition, jobs)) {
      counts.approvable += 1
      continue
    }
    const active = rendition.versions.at(-1)
    const status = recipeAssetVersionRuntimeStatus(active, jobs)
    if (status === "queued" || status === "running") {
      counts.running += 1
      continue
    }
    counts.idle += 1
  }
  return counts
}

export function formatSimpleAssetStageSummary(counts: SimpleAssetStageCounts, noun: string): string {
  if (!counts.total) return `暂无${noun}`
  const parts: string[] = []
  if (counts.approved) parts.push(`${counts.approved} 已批准`)
  if (counts.approvable) parts.push(`${counts.approvable} 待批准`)
  if (counts.running) parts.push(`${counts.running} 生成中`)
  if (counts.idle) parts.push(`${counts.idle} 待生成`)
  return parts.join(" · ")
}

export type SimpleAssetCardTone = "idle" | "running" | "pending" | "ready" | "failed"

export function simpleAssetCardTone(
  approved: boolean,
  approvable: boolean,
  generating: boolean,
  status: string,
): SimpleAssetCardTone {
  if (approved) return "ready"
  if (generating || status === "queued" || status === "running") return "running"
  if (approvable) return "pending"
  if (status === "failed" || status === "interrupted" || status === "cancelled") return "failed"
  return "idle"
}

export const SIMPLE_ASSET_CARD_STATUS_LABELS: Record<SimpleAssetCardTone, string> = {
  idle: "待生成",
  running: "生成中",
  pending: "待批准",
  ready: "已批准",
  failed: "生成失败",
}
