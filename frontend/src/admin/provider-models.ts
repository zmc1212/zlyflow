import { filterSearchOptions } from "../search-match"
import type { SearchableOption } from "../search-match"

export type CatalogModel = {
  id: string
  label: string
  free?: boolean | null
  owned_by?: string | null
}

export type CatalogResponse = {
  models: CatalogModel[]
  provider: string
  free_only: boolean
  message?: string | null
}

export type OfficialProviderPreset = {
  key: string
  label: string
  base_url: string
  api_key_url: string
  pricing_url: string
  pricing_verified_at: string
  chat_models: CatalogModel[]
  vision_models: CatalogModel[]
}

export type ProviderPresetsResponse = { presets: OfficialProviderPreset[] }

export type ProviderPreset = {
  value: string
  label: string
  baseUrl: string
  model: string
  docUrl: string
  recommendedModels: { id: string; name: string; free?: boolean | null }[]
}

export function sameProviderEndpoint(left: string, right: string): boolean {
  try {
    const a = new URL(left.trim())
    const b = new URL(right.trim())
    return a.href.replace(/\/+$/, "") === b.href.replace(/\/+$/, "")
  } catch {
    return false
  }
}

export function providerPresetFor(preset: OfficialProviderPreset, purpose: "chat" | "vision"): ProviderPreset {
  const models = purpose === "chat" ? preset.chat_models : preset.vision_models
  return {
    value: preset.key,
    label: preset.label,
    baseUrl: preset.base_url,
    model: models[0]?.id ?? "",
    docUrl: preset.api_key_url,
    recommendedModels: models.map(row => ({ id: row.id, name: row.label, free: row.free })),
  }
}

/** 模型下拉专用：没有命中时留一行提示，而不是静默收起下拉框。 */
export function filterModelOptions<T extends SearchableOption>(
  options: T[],
  query: string,
): (T | (SearchableOption & { disabled: true; hint: true }))[] {
  const text = (query || "").trim()
  const matched = filterSearchOptions(options, text)
  if (matched.length || !text) return matched
  return [{ value: `__no-model-match__${text}`, label: `无匹配模型，继续输入或用「${text}」保存`, disabled: true, hint: true }]
}

export function modelPriceLabel(free: boolean | null): string {
  return free === true ? "免费" : free === false ? "付费" : "价格未知"
}

export function modelPriceTagStyle(free: boolean | null) {
  const status = free === true ? "success" : free === false ? "warning" : null
  return {
    color: status ? `var(--studio-${status})` : "var(--studio-text-secondary)",
    backgroundColor: status ? `var(--studio-${status}-soft)` : "var(--studio-surface-raised)",
    borderColor: "var(--studio-border-strong)",
  }
}

export function resolveModelFree(
  baseUrl: string,
  model: string,
  catalog: CatalogModel[],
  presets: OfficialProviderPreset[],
): boolean | null {
  const catalogFree = catalog.find(row => row.id === model)?.free
  if (typeof catalogFree === "boolean") return catalogFree
  try {
    if (["127.0.0.1", "localhost", "[::1]", "0.0.0.0"].includes(new URL(baseUrl).hostname)) return true
  } catch {
    return null
  }
  const preset = presets.find(row => sameProviderEndpoint(row.base_url, baseUrl))
  const known = [...(preset?.chat_models ?? []), ...(preset?.vision_models ?? [])]
    .find(row => row.id.toLowerCase() === model.trim().toLowerCase())
  return known?.free ?? null
}

export function buildModelOptions(
  baseUrl: string,
  model: string,
  catalog: CatalogModel[],
  preset: ProviderPreset | undefined,
  officialPresets: OfficialProviderPreset[],
): { value: string; label: string }[] {
  const seen = new Set<string>()
  const options: { value: string; label: string }[] = []
  const add = (id: string, label = id) => {
    if (!id || seen.has(id)) return
    seen.add(id)
    const free = resolveModelFree(baseUrl, id, catalog, officialPresets)
    options.push({ value: id, label: `${label} · ${modelPriceLabel(free)}` })
  }
  for (const row of catalog) add(row.id, row.label)
  for (const row of preset?.recommendedModels ?? []) add(row.id, row.name)
  add(model)
  return options
}
