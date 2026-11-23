import { describe, expect, it } from "vitest"
import { buildReportCsv, coverage, money, percentage, reportFilename, type CreditUsageReport } from "./credit-report"

const row = {
  key: "llm:assistant_chat",
  label: "助手, \"每轮\"",
  calls: 2,
  credits: 300,
  revenue_cny: 3,
  cost_cny: 1.5,
  costed_calls: 2,
  uncosted_calls: 0,
  actual_cost_calls: 2,
  estimated_cost_calls: 0,
  token_calls: 2,
  tokens: 1200,
  refunds: 0,
  refunded_credits: 0,
  net_credits: 300,
  net_revenue_cny: 3,
  margin_cny: 1.5,
  margin_rate: 0.5,
  coverage: 2,
}

const report: CreditUsageReport = {
  start: "2026-11-01",
  end: "2026-11-20",
  group_by: "price_key",
  scope: "all",
  totals: { ...row, key: "all", label: "合计" },
  rows: [row],
  refunds_grouped: true,
  generated_at: "2026-11-20T00:00:00+00:00",
}

describe("credit report", () => {
  it("formats money, percentage and coverage", () => {
    expect(money(1.23456)).toBe("¥1.2346")
    expect(money(null)).toBe("—")
    expect(percentage(0.5)).toBe("50.0%")
    expect(coverage(2)).toBe("2.00×")
  })

  it("exports totals first, escaped CSV cells and BOM", () => {
    const csv = buildReportCsv(report)
    expect(csv.startsWith("\ufeff")).toBe(true)
    const lines = csv.slice(1).split("\r\n")
    expect(lines[1]).toContain("合计")
    expect(lines[2]).toContain('"助手, ""每轮"""')
    expect(lines[2]).toContain("50.00%")
  })

  it("neutralizes spreadsheet formulas in text cells", () => {
    const dangerous = { ...report, rows: [{ ...row, label: "=HYPERLINK(\"https://example.com\")", key: "+cmd" }] }
    const csv = buildReportCsv(dangerous)
    expect(csv).toContain("'=HYPERLINK")
    expect(csv).toContain("'+cmd")
  })

  it("names the export by date and grouping", () => {
    expect(reportFilename(report)).toBe("积分用量毛利_2026-11-01_2026-11-20_价格条目.csv")
  })
})