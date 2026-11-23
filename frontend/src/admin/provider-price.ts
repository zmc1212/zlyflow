import type { CreditPriceRule } from "../credits/credits"

/** 后端 /api/admin/credits/provider-prices 返回的单个模型价目（元/百万 tokens）。 */
export type ProviderPriceEntry = {
  model: string
  input_per_mtok: number
  cached_input_per_mtok: number
  output_per_mtok: number
  input_credits_per_mtok: number
  cached_input_credits_per_mtok: number
  output_credits_per_mtok: number
  currency: string
  source: "upstream" | "builtin" | string
  source_url?: string | null
  verified_at?: string | null
  note?: string | null
  free: boolean
  off_peak?: {
    enabled: boolean
    discount: number
    timezone: string
    windows: Array<{ start: string; end: string }>
  } | null
}

export type ProviderPriceCatalog = {
  scope: "llm" | "vlm"
  provider: string
  base_url: string
  model: string
  margin: number
  matched: ProviderPriceEntry | null
  entries: ProviderPriceEntry[]
  message?: string | null
}

export type ProviderPriceAppliedItem = {
  scope: string
  rule_key: string
  model: string
  source?: string | null
  unit_credits?: number | null
  status: "applied" | "skipped" | string
  reason?: string | null
}

export type ProviderPriceApplyResult = {
  rules: CreditPriceRule[]
  applied: ProviderPriceAppliedItem[]
  message?: string | null
}

/**
 * 供应商 token 单价 → 平台积分单价。
 * 100 积分 = 1 元，所以每百万 tokens 的积分 = 金额 × 100 × 加价系数，向上取整。
 */
export function creditsForProviderPrice(amountPerMtok: number, margin: number): number {
  if (!Number.isFinite(amountPerMtok) || amountPerMtok < 0) return 0
  if (!Number.isFinite(margin) || margin <= 0) return 0
  return Math.max(0, Math.ceil(Number((amountPerMtok * 100 * margin).toFixed(6))))
}

export const PROVIDER_SOURCE_LABELS: Record<string, string> = {
  upstream: "供应商接口",
  builtin: "内置核验价目",
}

export function providerSourceLabel(source?: string | null): string {
  return PROVIDER_SOURCE_LABELS[source ?? ""] ?? "手工价格"
}
