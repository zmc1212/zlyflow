import type { Director2Asset } from "./api"
import { assetImageSlots, assetSlotBlocker, assetSlotImage, assetSlotPrompt, type AssetCanvasTarget } from "./asset-canvas-model"

export type AssetGenerationItem = {
  assetId: string
  target: AssetCanvasTarget
  label: string
  payload: Record<string, unknown>
}

/** Selection is always scoped to the visible category/search results. */
export function visibleAssetSelection(assets: Director2Asset[], selectedIds: readonly string[]) {
  const selected = new Set(selectedIds)
  return assets.filter(asset => selected.has(asset.id)).map(asset => asset.id)
}

/** Fill missing production images only; secondary/historical media is never regenerated. */
export function planAssetGeneration(assets: Director2Asset[], selectedIds: readonly string[]) {
  const selected = new Set(selectedIds)
  const items: AssetGenerationItem[] = []
  const blocked: { assetId: string; label: string; reason: string }[] = []
  for (const asset of assets) {
    if (!selected.has(asset.id)) continue
    for (const { target, title } of assetImageSlots(asset)) {
      if (assetSlotImage(asset, target).trim()) continue
      const label = asset.kind === "character" ? `${asset.name} · ${title}` : asset.name
      const reason = assetSlotBlocker(asset, target)
      if (reason) { blocked.push({ assetId: asset.id, label, reason }); continue }
      items.push({
        assetId: asset.id, target, label,
        payload: { target_type: target.type, ...(target.identityId ? { identity_id: target.identityId } : {}), prompt: assetSlotPrompt(asset, target), aspect_ratio: "16:9" },
      })
    }
  }
  return { items, blocked }
}
