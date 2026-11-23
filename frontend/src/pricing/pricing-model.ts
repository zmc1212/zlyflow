// 云端视频价格页数据模型与试算：价格/档位全部来自 /api/pricing，前端不硬编码金额。
export type PricingResolution = {
  value: string
  label: string
  credits_per_second: number
  native_price_per_second?: number | null
  credits_5s: number
  credits_10s: number
}

export type PricingModel = {
  key: string
  label: string
  tagline: string
  description: string
  resolutions: PricingResolution[]
  input_image_native_price?: number | null
  input_image_credits: number
}

export type PricingProvider = {
  key: string
  label: string
  subtitle: string
  description: string
  available: boolean
  unavailable_reason?: string | null
  workflow_ids: string[]
  modes: string[]
  models: PricingModel[]
  input_image_free_quota: number
  notes: string[]
}

export type PricingPolicy = {
  anchor: string
  settlement: string
  local: string
}

/** 生图价格条目：模型列表来自图片服务目录，单价为 grs_image:global 实际生效平台积分。 */
export type PricingImageModel = {
  key: string
  label: string
  description: string
  credits_per_image: number
  is_default: boolean
}

export type PricingImageGeneration = {
  pricing_kind: "per_item"
  models: PricingImageModel[]
}

/** AI 大模型按次价格条目：per_call 为固定单价，per_token 为典型用量估算价。 */
export type PricingAiCall = {
  key: string
  scope: "llm" | "vlm"
  kind: string
  label: string
  description: string
  unit_credits: number
  billing_mode: "per_call" | "per_token"
  /** 按 token 条目的上游单价（元/百万 tokens），用于解释积分来源。 */
  input_per_mtok?: number | null
  cached_input_per_mtok?: number | null
  output_per_mtok?: number | null
  billing_margin?: number | null
  price_source?: string
}

export type PricingAiCalls = {
  items: PricingAiCall[]
}

export type PricingCatalog = {
  credits_per_yuan: number
  billing_policy: PricingPolicy
  providers: PricingProvider[]
  image_generation?: PricingImageGeneration
  ai_calls?: PricingAiCalls
}

export type PricingQuote = {
  secondsCredits: number
  inputImageCredits: number
  inputImageCount: number
  totalCredits: number
  yuan: number
}

/** 积分 → 人民币；锚点为 0 或非法时返回 0，避免除零。 */
export function creditsToYuan(credits: number, creditsPerYuan = 100): number {
  const value = Number(credits) || 0
  const anchor = Number(creditsPerYuan) || 0
  return anchor > 0 ? value / anchor : 0
}

/** 预估 = 时长 × 每秒积分 + 超出免费额度的参考图 × 图片单价。 */
export function quotePricing(
  model: PricingModel,
  resolution: PricingResolution,
  durationSeconds: number,
  referenceCount: number,
  freeQuota: number,
  creditsPerYuan = 100,
): PricingQuote {
  const seconds = Math.max(0, Math.round(Number(durationSeconds) || 0))
  const references = Math.max(0, Math.round(Number(referenceCount) || 0))
  const secondsCredits = seconds * Math.max(0, resolution.credits_per_second)
  const inputImageCount = Math.max(0, references - Math.max(0, freeQuota))
  const inputImageCredits = inputImageCount * Math.max(0, model.input_image_credits)
  const totalCredits = secondsCredits + inputImageCredits
  return {
    secondsCredits,
    inputImageCredits,
    inputImageCount,
    totalCredits,
    yuan: creditsPerYuan > 0 ? totalCredits / creditsPerYuan : 0,
  }
}

/**
 * 上游时长约束：GRS MiniMax-H3 1-15 秒（1080p 最长 10 秒）；
 * GRS Agnes 2.5 固定 4-12 秒；GRS Wan 3.0 2-30 秒；MiniMax 官方 4-15 秒（H3-Max 起步 5 秒）。
 */
export function durationBounds(providerKey: string, modelKey: string, resolutionValue: string) {
  if (providerKey === "grs") {
    return { min: 1, max: resolutionValue === "1080p" ? 10 : 15 }
  }
  if (providerKey === "grs-agnes") {
    return { min: 4, max: 12 }
  }
  if (providerKey === "grs-wan") {
    return { min: 2, max: 30 }
  }
  return { min: modelKey === "MiniMax-H3-Max" ? 5 : 4, max: 15 }
}
