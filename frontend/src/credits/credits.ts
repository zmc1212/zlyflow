// 用户积分体系：类型与请求辅助（锚定 100 积分 = 1 元）。
export type CreditAccount = {
  user_id: string
  balance: number
  total_recharged: number
  total_consumed: number
  updated_at: string
  username?: string | null
  display_name?: string | null
  role?: string | null
  is_active?: boolean | null
  scope?: "user" | "enterprise"
  enterprise?: { id: string; name: string; status: string; code?: string | null } | null
}

export type CreditUsageMeta = {
  model?: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  cached_tokens?: number | null
  total_tokens?: number | null
  cost_cny?: number | null
  cost_basis?: "actual" | "estimated" | string | null
  unit_credits?: number | null
  provider_coefficient?: number | null
}

export type CreditTransactionType = "admin_recharge" | "admin_adjust" | "consume" | "refund"

export type CreditTransaction = {
  id: number
  user_id: string | null
  delta: number
  type: CreditTransactionType
  reason?: string | null
  price_key?: string | null
  ref_type?: string | null
  ref_id?: string | null
  balance_after: number
  actor_user_id?: string | null
  created_at: string
  username?: string | null
  display_name?: string | null
  scope?: "user" | "enterprise"
  enterprise_id?: string | null
  enterprise_name?: string | null
  actor_username?: string | null
  meta?: CreditUsageMeta | null
}

export type CreditEstimate = {
  mode: string
  credits: number
  unit_credits: number
  items: number
  breakdown: string
  input_image_credits: number
  input_image_count: number
  input_image_unit_credits: number
  price_key?: string | null
  balance: number
  sufficient: boolean
}

export type CreditPriceRule = {
  rule_key: string
  scope: "cloud_video" | "grs_image" | "llm" | "vlm" | string
  pricing_kind: "per_second" | "per_item" | "per_call" | string
  unit_credits: number
  unit_by_variant?: Record<string, number> | null
  resolved_unit_by_variant?: Record<string, number> | null
  extra_config?: Record<string, unknown> | null
  cost_preview?: PriceCostPreview | null
  enabled: boolean
  note?: string | null
  updated_at: string
}

export type PriceCostPreview = {
  tokens?: { prompt_tokens?: number; completion_tokens?: number; cached_tokens?: number; total_tokens?: number }
  cost_cny: number
  cost_basis: "actual" | "estimated" | string
  input_per_mtok: number
  cached_input_per_mtok: number
  output_per_mtok: number
  provider_coefficient: number
  unit_credits: number
  billed_cny: number
  coverage: number | null
  suggested_unit_credits: number
  status: "below_cost" | "thin" | "healthy" | "unknown"
  estimated: boolean
}

export type WorkflowBilling = {
  scope: "cloud_video" | "grs_image" | string
  pricing_kind: "per_second" | "per_item" | string
  unit_credits: number
  unit_by_variant?: Record<string, number> | null
  resolved_unit_by_variant?: Record<string, number> | null
  native_unit?: string | null
  native_variant_prices?: Record<string, number> | null
  credits_per_native_unit?: number | null
  provider_coefficient?: number | null
  price_source?: "native" | "manual" | string | null
  summary?: string | null
  enabled: boolean
}

export const CREDIT_TRANSACTION_LABELS: Record<CreditTransactionType, string> = {
  admin_recharge: "充值",
  admin_adjust: "调整",
  consume: "消耗",
  refund: "退款",
}

export const CREDIT_TRANSACTION_COLORS: Record<CreditTransactionType, string> = {
  admin_recharge: "green",
  admin_adjust: "gold",
  consume: "blue",
  refund: "purple",
}

export const MAX_CREDIT_AMOUNT = 2_147_483_647

/** 调用类流水的内部 price_key → 用户可读文案（后端 reason 以 price_key 开头落库，展示层负责改写）。 */
const CREDIT_CALL_KIND_LABELS: Record<string, string> = {
  "llm:assistant_chat": "AI 对话",
  "llm:music_chat": "音乐创作对话",
  "llm:optimize_prompt": "提示词优化",
  "llm:split_script": "剧本拆分",
  "llm:repair_continuity": "连贯性修复",
  "llm:director_clarify": "导演台澄清提问",
  "llm:director_plan": "导演台方案规划",
  "vlm:analyze_subject": "主体识别分析",
  "vlm:reverse_prompt": "图片反推提示词",
}

const CREDIT_CALL_BASIS_LABELS: Record<string, string> = {
  "调用一次": "按次计费",
  "按 token 结算": "按 token 计费",
}

/** 把流水 reason 里的内部键改写成用户可读文案；任务扣费/退款等本身可读的 reason 原样保留。 */
export function friendlyCreditReason(reason?: string | null): string {
  const value = String(reason ?? "").trim()
  if (!value) return ""
  const [lead, ...rest] = value.split(" ")
  const suffix = rest.join(" ").trim()
  const known = CREDIT_CALL_KIND_LABELS[lead]
  if (known) {
    const basis = CREDIT_CALL_BASIS_LABELS[suffix] ?? suffix
    return basis ? `${known}（${basis}）` : known
  }
  if (/^(llm|vlm):/.test(lead)) {
    // 未登记的新调用类型：不外露内部键，按计费方式给通用文案。
    const basis = CREDIT_CALL_BASIS_LABELS[suffix] ?? "按次计费"
    return `AI 调用（${basis}）`
  }
  return value
}

export function formatCredits(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—"
  return Number(value).toLocaleString("zh-CN")
}

export function formatCny(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—"
  const number = Number(value)
  if (number === 0) return "¥0"
  const fixed = number.toFixed(Math.max(2, digits)).replace(/0+$/, "").replace(/\.$/, "")
  return `¥${fixed}`
}

/** 流水里的用量摘要：token 与「≈¥」成本；估算是为了和真实上游账单区分。 */
export function usageMetaSummary(meta?: CreditUsageMeta | null): string {
  if (!meta) return ""
  const parts: string[] = []
  const tokenParts: string[] = []
  if (meta.prompt_tokens != null) tokenParts.push(`输入 ${formatCredits(meta.prompt_tokens)}`)
  if (meta.completion_tokens != null) tokenParts.push(`输出 ${formatCredits(meta.completion_tokens)}`)
  if (meta.cached_tokens) tokenParts.push(`缓存 ${formatCredits(meta.cached_tokens)}`)
  if (tokenParts.length) parts.push(`${tokenParts.join(" · ")} tokens`)
  if (meta.cost_cny != null) {
    parts.push(`≈${formatCny(meta.cost_cny, 6)}${meta.cost_basis === "estimated" ? "（估算）" : ""}`)
  }
  return parts.join(" · ")
}

// 企业管理：类型定义（企业主档 / 企业钱包 / 企业流水 / 成员用量 / 模型访问策略）
export type EnterpriseStatus = "active" | "disabled"

export type Enterprise = {
  id: string
  name: string
  code?: string | null
  parent_id?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  notes?: string | null
  status: EnterpriseStatus
  member_count: number
  balance: number
  total_recharged: number
  total_consumed: number
  created_at: string
  updated_at: string
}

export type EnterpriseModelKind = "video" | "image" | "llm" | "vlm"

export type EnterprisePolicyItem = {
  model_kind: EnterpriseModelKind
  mode: "all" | "whitelist" | "none"
  models: string[]
}

export type EnterprisePolicyCatalogEntry = { key: string; label: string }

export type EnterprisePolicyCatalog = {
  video: EnterprisePolicyCatalogEntry[]
  image: EnterprisePolicyCatalogEntry[]
  llm: EnterprisePolicyCatalogEntry[]
  vlm: EnterprisePolicyCatalogEntry[]
}

export type EnterpriseDetail = {
  enterprise: Enterprise
  policies: EnterprisePolicyItem[]
  catalog: EnterprisePolicyCatalog
}

export type EnterpriseMemberQuotaPeriod = "none" | "monthly" | "total"

export type EnterpriseMember = {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  email?: string | null
  enterprise_id?: string | null
  enterprise_name?: string | null
  created_at: string
  last_login_at?: string | null
  gross_consumed: number
  refunded: number
  net_consumed: number
  tx_count: number
  last_active_at?: string | null
  quota_period: EnterpriseMemberQuotaPeriod
  quota_limit: number
  quota_used: number
  month_consumed: number
}

export type EnterpriseCreditTransaction = {
  id: number
  enterprise_id: string
  user_id?: string | null
  delta: number
  type: CreditTransactionType
  reason?: string | null
  price_key?: string | null
  ref_type?: string | null
  ref_id?: string | null
  balance_after: number
  actor_user_id?: string | null
  created_at: string
  username?: string | null
  display_name?: string | null
  meta?: CreditUsageMeta | null
}

export const ENTERPRISE_KIND_LABELS: Record<EnterpriseModelKind, string> = {
  video: "视频模型",
  image: "生图模型",
  llm: "大语言模型",
  vlm: "视觉理解",
}

export const ENTERPRISE_POLICY_MODE_LABELS: Record<EnterprisePolicyItem["mode"], string> = {
  all: "全部开放",
  whitelist: "仅开放选中",
  none: "全部关闭",
}
