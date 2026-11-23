import { MAX_CREDIT_AMOUNT } from "../credits/credits"

export const MAX_VISIBLE_VARIANT_CHIPS = 3

export function isValidCreditPrice(value: number | null | undefined, integer = false): value is number {
  return typeof value === "number" && value >= 0 && value <= MAX_CREDIT_AMOUNT && (!integer || Number.isInteger(value))
}

export function previewCreditConversion(price: number | null, perUnit: number | null, coefficient: number | null): number | null {
  if (!isValidCreditPrice(price) || !isValidCreditPrice(perUnit) || !isValidCreditPrice(coefficient)) return null
  const computed = price * perUnit * coefficient
  return computed <= MAX_CREDIT_AMOUNT ? Math.ceil(Number(computed.toFixed(6))) : null
}

export type BillingMode = "per_call" | "per_token"
export type OffPeakWindow = { start: string; end: string }
export type OffPeakConfig = {
  enabled: boolean
  discount: number
  timezone: string
  windows: OffPeakWindow[]
}

export type CallCostReference = {
  input_per_mtok: number
  cached_input_per_mtok: number
  output_per_mtok: number
  assumed_input_tokens: number
  assumed_cached_tokens: number
  assumed_output_tokens: number
  provider_coefficient: number
  model_prices?: Record<string, Partial<ModelPriceTier>>
  off_peak?: OffPeakConfig
}

export type ModelPriceTier = {
  input_per_mtok: number
  cached_input_per_mtok: number
  output_per_mtok: number
}

export type CallCostPreview = {
  costCny: number
  billedCny: number
  coverage: number | null
  suggestedUnitCredits: number
  tokenCredits: number | null
  status: "below_cost" | "thin" | "healthy" | "unknown"
}

/** 与后端 compute_cost_preview 同口径：典型 tokens × 元/百万 tokens → 单次成本。 */
export function previewCallCost(
  reference: Partial<CallCostReference>,
  unitCredits: number | null,
  options: { billingMode?: BillingMode; billingMargin?: number | null; minCredits?: number | null } = {},
): CallCostPreview | null {
  const inputPrice = Number(reference.input_per_mtok ?? 0)
  const cachedPrice = Number(reference.cached_input_per_mtok ?? 0)
  const outputPrice = Number(reference.output_per_mtok ?? 0)
  const inputTokens = Number(reference.assumed_input_tokens ?? 0)
  const cachedTokens = Math.min(Number(reference.assumed_cached_tokens ?? 0), inputTokens)
  const outputTokens = Number(reference.assumed_output_tokens ?? 0)
  const coefficient = Number(reference.provider_coefficient ?? 1)
  if (![inputPrice, cachedPrice, outputPrice, inputTokens, cachedTokens, outputTokens, coefficient].every(Number.isFinite)) return null
  if (inputPrice < 0 || cachedPrice < 0 || outputPrice < 0 || inputTokens < 0 || cachedTokens < 0 || outputTokens < 0) return null
  if (!inputPrice && !cachedPrice && !outputPrice) return null
  const cost = ((inputTokens - cachedTokens) * inputPrice + cachedTokens * cachedPrice + outputTokens * outputPrice) / 1_000_000
  const billed = Math.max(0, Number(unitCredits ?? 0)) / 100
  const coverage = cost > 0 ? Number((billed / cost).toFixed(4)) : null
  const status: CallCostPreview["status"] = coverage === null
    ? "unknown"
    : coverage < 1 ? "below_cost" : coverage < 1.2 ? "thin" : "healthy"
  const margin = Number(options.billingMargin ?? 1)
  const effectiveCost = cost * coefficient
  const tokenCredits = options.billingMode === "per_token" && effectiveCost > 0 && Number.isFinite(margin) && margin > 0
    ? Math.max(Math.max(0, Math.ceil(Number(options.minCredits ?? 1))),
      Math.ceil(Number((effectiveCost * 100 * margin).toFixed(6))))
    : null
  return {
    costCny: Number(cost.toFixed(6)),
    billedCny: Number(billed.toFixed(6)),
    coverage,
    suggestedUnitCredits: Math.ceil(Number((cost * coefficient * 100).toFixed(6))),
    tokenCredits,
    status,
  }
}

/**
 * 档位名通常带同一模型前缀（如 MiniMax-H3-），表格内只保留能区分的后缀，完整名称留在 tooltip。
 * 只在公共前缀落在分隔符边界时裁剪，避免把 480P / 480P-Hi 这类名字裁成残词。
 */
export const compactVariantLabels = (labels: string[]): string[] => {
  if (labels.length < 2) return labels
  let prefix = labels[0]
  for (const label of labels.slice(1)) {
    let index = 0
    while (index < prefix.length && index < label.length && prefix[index] === label[index]) index += 1
    prefix = prefix.slice(0, index)
  }
  if (prefix.length < 4) return labels
  const cleanCut = /[:\-_\s]$/.test(prefix)
    || labels.every((label) => /[:\-_\s]/.test(label[prefix.length] ?? ""))
  if (!cleanCut) return labels
  return labels.map((label) => label.slice(prefix.length).replace(/^[:\-_\s]+/, "") || label)
}
