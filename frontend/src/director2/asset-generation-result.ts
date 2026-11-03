import type { Director2Asset } from "./api"
import type { AssetIdentity } from "./panes/assets/shared"

function mergeMedia(local: Director2Asset, generated: Director2Asset): Director2Asset {
  const extra = { ...local.extra }
  for (const [key, value] of Object.entries(generated.extra || {})) {
    if (key.endsWith("_url") || key.endsWith("_object_key")) extra[key] = value
  }
  const generatedIdentities = generated.extra?.identities as AssetIdentity[] | undefined
  if (Array.isArray(generatedIdentities)) {
    const identities = (local.extra?.identities || generatedIdentities) as AssetIdentity[]
    extra.identities = identities.map(identity => {
      const result = generatedIdentities.find(item => item.id === identity.id)
      return result ? { ...identity, image_url: result.image_url, ...(result.object_key ? { object_key: result.object_key } : {}) } : identity
    })
  }
  return { ...local, image_url: generated.image_url, extra, updated_at: generated.updated_at }
}

/** A late image result always belongs to the asset that started the request. */
export function reconcileAssetGeneration(assets: Director2Asset[], selected: Director2Asset | null, requestedId: string, result?: Director2Asset) {
  const source = assets.find(asset => asset.id === requestedId)
  if (!result || result.id !== requestedId || !source || source.kind !== result.kind) return null
  return {
    assets: assets.map(asset => asset.id === requestedId ? mergeMedia(asset, result) : asset),
    selected: selected?.id === requestedId ? mergeMedia(selected, result) : selected,
  }
}
