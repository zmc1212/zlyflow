export type CreditReportGroupBy = "price_key" | "model" | "user" | "enterprise" | "day"
export type CreditReportScope = "user" | "enterprise" | "all"

export type CreditUsageReportRow = {
  key: string
  label: string
  calls: number
  credits: number
  revenue_cny: number
  cost_cny: number
  costed_calls: number
  uncosted_calls: number
  actual_cost_calls: number
  estimated_cost_calls: number
  token_calls: number
  tokens: number
  refunds: number
  refunded_credits: number
  net_credits: number
  net_revenue_cny: number
  margin_cny: number
  margin_rate: number | null
  coverage: number | null
}

export type CreditUsageReport = {
  start: string
  end: string
  group_by: CreditReportGroupBy
  scope: CreditReportScope
  totals: CreditUsageReportRow
  rows: CreditUsageReportRow[]
  refunds_grouped: boolean
  generated_at: string
}

export const REPORT_GROUP_OPTIONS: Array<{ value: CreditReportGroupBy; label: string }> = [
  { value: "price_key", label: "按价格条目" },
  { value: "model", label: "按模型" },
  { value: "user", label: "按账号" },
  { value: "enterprise", label: "按企业" },
  { value: "day", label: "按日期" },
]

export const REPORT_SCOPE_OPTIONS: Array<{ value: CreditReportScope; label: string }> = [
  { value: "all", label: "所有钱包" },
  { value: "user", label: "个人钱包" },
  { value: "enterprise", label: "企业钱包" },
]

export const REPORT_GROUP_LABELS: Record<CreditReportGroupBy, string> = {
  price_key: "价格条目",
  model: "模型",
  user: "账号",
  enterprise: "企业",
  day: "日期",
}

export function money(value: number | null | undefined, digits = 4): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—"
  return `¥${value.toFixed(digits)}`
}

export function percentage(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—"
  return `${(value * 100).toFixed(1)}%`
}

export function coverage(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—"
  return `${value.toFixed(2)}×`
}

function csvCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** 文本列防 CSV 公式注入；数字列不经过这里，避免把负毛利误加引号。 */
function csvText(value: string | null | undefined): string {
  const text = value ?? ""
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text
}

/** 导出当前报表为 CSV；含汇总行，金额保留 6 位小数，便于财务复核。 */
export function buildReportCsv(report: CreditUsageReport): string {
  const headers = [
    "分组", "键", "调用次数", "扣费积分", "收入(元)", "上游成本(元)", "成本覆盖调用", "未覆盖调用",
    "按真实成本调用", "按估算成本调用", "按 token 结算", "tokens", "退款笔数", "退款积分",
    "净积分", "净收入(元)", "毛利(元)", "毛利率", "覆盖率",
  ]
  const line = (row: CreditUsageReportRow) => [
    csvText(row.label), csvText(row.key), row.calls, row.credits, row.revenue_cny.toFixed(6), row.cost_cny.toFixed(6),
    row.costed_calls, row.uncosted_calls, row.actual_cost_calls, row.estimated_cost_calls,
    row.token_calls, row.tokens, row.refunds, row.refunded_credits, row.net_credits,
    row.net_revenue_cny.toFixed(6), row.margin_cny.toFixed(6),
    row.margin_rate === null ? "" : (row.margin_rate * 100).toFixed(2) + "%",
    row.coverage === null ? "" : row.coverage.toFixed(4),
  ].map(csvCell).join(",")
  const lines = [
    headers.map(csvCell).join(","),
    line({ ...report.totals, label: "合计", key: "all" }),
    ...report.rows.map(line),
  ]
  return "\ufeff" + lines.join("\r\n")
}

export function reportFilename(report: CreditUsageReport): string {
  return `积分用量毛利_${report.start}_${report.end}_${REPORT_GROUP_LABELS[report.group_by]}.csv`
}