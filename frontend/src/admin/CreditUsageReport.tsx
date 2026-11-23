import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Alert, Button, Card, Input, Segmented, Select, Statistic, Table, Tag, Tooltip } from "antd"
import { Download, RefreshCw } from "lucide-react"
import { requestJson } from "../api"
import {
  buildReportCsv, coverage, money, percentage, reportFilename,
  REPORT_GROUP_LABELS, REPORT_GROUP_OPTIONS, REPORT_SCOPE_OPTIONS,
  type CreditReportGroupBy, type CreditReportScope, type CreditUsageReport, type CreditUsageReportRow,
} from "./credit-report"

const secondaryText = "text-[color:var(--studio-text-secondary)]"
const panelClass = "rounded-2xl border border-[color:var(--studio-border)] bg-[var(--studio-surface)] p-5"

function beijingDate(value: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(value)
}

function shiftDays(day: string, offset: number): string {
  const date = new Date(`${day}T00:00:00+08:00`)
  date.setUTCDate(date.getUTCDate() + offset)
  return beijingDate(date)
}

function downloadCsv(report: CreditUsageReport): void {
  const blob = new Blob([buildReportCsv(report)], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = reportFilename(report)
  anchor.click()
  URL.revokeObjectURL(url)
}

const marginClass = (value: number) => value >= 0 ? "text-[color:var(--studio-success)]" : "text-[color:var(--studio-danger)]"

export default function CreditUsageReport({ active }: { active: boolean }) {
  const today = beijingDate(new Date())
  const [start, setStart] = useState(() => shiftDays(today, -29))
  const [end, setEnd] = useState(today)
  const [groupBy, setGroupBy] = useState<CreditReportGroupBy>("price_key")
  const [scope, setScope] = useState<CreditReportScope>("all")

  const query = useQuery({
    queryKey: ["admin-credit-usage-report", start, end, groupBy, scope],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ start, end, group_by: groupBy, scope })
      return requestJson<CreditUsageReport>(`/api/admin/credits/usage-report?${params}`, { signal })
    },
    placeholderData: keepPreviousData,
    enabled: active,
  })
  const report = query.data
  const totals = report?.totals
  const columns = [
    {
      title: REPORT_GROUP_LABELS[groupBy], width: 260,
      render: (_: unknown, row: CreditUsageReportRow) => (
        <div className="min-w-0">
          <div className="font-medium break-words">{row.label}</div>
          {row.label !== row.key ? <div className={`font-mono text-[11px] break-all ${secondaryText}`}>{row.key}</div> : null}
        </div>
      ),
    },
    { title: "调用", width: 82, align: "right" as const, render: (_: unknown, row: CreditUsageReportRow) => <span className="tabular-nums">{row.calls}</span> },
    {
      title: "扣费积分", width: 132, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => (
        <div className="tabular-nums">
          <div className="font-medium">{row.credits.toLocaleString("zh-CN")}</div>
          <div className={`text-[11px] ${secondaryText}`}>{money(row.revenue_cny, 2)}</div>
        </div>
      ),
    },
    {
      title: "上游成本", width: 150, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => (
        <div className="tabular-nums">
          <div>{money(row.cost_cny)}</div>
          {row.uncosted_calls > 0 ? (
            <Tooltip title="这些调用在流水里没有 cost_cny，毛利会偏高；按 token 结算成功且带真实用量的调用通常有成本。">
              <Tag color="gold" className="!m-0 !text-[10px]">{row.uncosted_calls} 次未覆盖</Tag>
            </Tooltip>
          ) : <div className={`text-[11px] ${secondaryText}`}>{row.costed_calls} 次有成本</div>}
        </div>
      ),
    },
    { title: "净收入", width: 105, align: "right" as const, render: (_: unknown, row: CreditUsageReportRow) => <span className="tabular-nums">{money(row.net_revenue_cny, 2)}</span> },
    {
      title: "毛利", width: 115, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => (
        <span className={`tabular-nums font-medium ${marginClass(row.margin_cny)}`}>{money(row.margin_cny)}</span>
      ),
    },
    {
      title: "毛利率", width: 88, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => <span className="tabular-nums">{percentage(row.margin_rate)}</span>,
    },
    { title: "覆盖率", width: 88, align: "right" as const, render: (_: unknown, row: CreditUsageReportRow) => <span className="tabular-nums">{coverage(row.coverage)}</span> },
    {
      title: "按 token", width: 100, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => (
        <div className="tabular-nums">
          <div>{row.token_calls}</div>
          <div className={`text-[11px] ${secondaryText}`}>{row.tokens.toLocaleString("zh-CN")} tok</div>
        </div>
      ),
    },
    {
      title: "退款", width: 105, align: "right" as const,
      render: (_: unknown, row: CreditUsageReportRow) => row.refunds > 0
        ? <span className="tabular-nums text-[color:var(--studio-danger)]">{row.refunds} 笔 · {row.refunded_credits}</span>
        : <span className={secondaryText}>—</span>,
    },
  ]

  return (
    <div className="grid gap-4" aria-label="用量毛利报表">
      <div className={panelClass}>
        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-1">
            <div className="text-sm font-semibold">用量与毛利</div>
            <div className={`text-xs ${secondaryText}`}>按流水实际扣费与 cost_cny 汇总，100 积分 = 1 元</div>
          </div>
          <Input
            type="date"
            aria-label="报表开始日期"
            className="!w-[145px]"
            value={start}
            max={end}
            onChange={(event) => setStart(event.target.value)}
          />
          <span className={secondaryText}>至</span>
          <Input
            type="date"
            aria-label="报表结束日期"
            className="!w-[145px]"
            value={end}
            min={start}
            max={today}
            onChange={(event) => setEnd(event.target.value)}
          />
          <Segmented
            aria-label="报表分组"
            value={groupBy}
            onChange={(value) => setGroupBy(value as CreditReportGroupBy)}
            options={REPORT_GROUP_OPTIONS}
          />
          <Select
            value={scope}
            onChange={(value) => setScope(value as CreditReportScope)}
            className="min-w-[116px]"
            aria-label="报表钱包范围"
            options={REPORT_SCOPE_OPTIONS}
          />
          <Button className="ml-auto" icon={<RefreshCw size={14} />} loading={query.isFetching} onClick={() => void query.refetch()}>刷新</Button>
          <Button icon={<Download size={14} />} disabled={!report} onClick={() => report && downloadCsv(report)}>导出 CSV</Button>
        </div>
        {query.isError ? <Alert className="mt-3" type="error" showIcon title={query.error.message} /> : null}
        {report && report.totals.uncosted_calls > 0 ? (
          <Alert
            className="mt-3"
            type="warning"
            showIcon
            title={`${report.totals.uncosted_calls} 次调用没有上游成本明细，毛利偏高`}
            description="这些流水可能来自未配置成本参考的条目，或未采集 usage 的按次调用；建议在价格表补齐成本参考后再看毛利。"
          />
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card size="small"><Statistic title="扣费积分" value={totals?.credits ?? 0} suffix="积分" /></Card>
        <Card size="small"><Statistic title="净收入" value={totals?.net_revenue_cny ?? 0} precision={2} prefix="¥" /></Card>
        <Card size="small"><Statistic title="上游成本" value={totals?.cost_cny ?? 0} precision={4} prefix="¥" /></Card>
        <Card size="small">
          <Statistic
            title="毛利 / 毛利率"
            value={totals?.margin_cny ?? 0}
            precision={4}
            prefix="¥"
            suffix={<span className={`text-sm ${marginClass(totals?.margin_cny ?? 0)}`}> · {percentage(totals?.margin_rate)}</span>}
          />
        </Card>
        <Card size="small"><Statistic title="扣费调用" value={totals?.calls ?? 0} suffix="次" /></Card>
        <Card size="small"><Statistic title="按 token 结算" value={totals?.token_calls ?? 0} suffix="次" /></Card>
        <Card size="small"><Statistic title="退款积分" value={totals?.refunded_credits ?? 0} suffix={`/ ${totals?.refunds ?? 0} 笔`} /></Card>
        <Card size="small"><Statistic title="成本覆盖" value={totals?.costed_calls ?? 0} suffix={`/ ${totals?.calls ?? 0} 次`} /></Card>
      </div>

      <div className={panelClass}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold">
            {report ? `${report.start} 至 ${report.end} · ${REPORT_GROUP_LABELS[report.group_by]}` : "报表明细"}
          </div>
          <div className={`text-xs ${secondaryText}`}>
            {report && !report.refunds_grouped ? "退款只计入汇总；切到「按价格条目」可归入对应行。" : "毛利 = 净收入 − 已记录的上游成本"}
          </div>
        </div>
        <Table<CreditUsageReportRow>
          rowKey={(row) => `${row.key}:${row.label}`}
          size="small"
          loading={query.isFetching}
          dataSource={report?.rows ?? []}
          columns={columns}
          pagination={false}
          scroll={{ x: 1280 }}
          locale={{ emptyText: query.isError ? "报表加载失败" : "所选范围内没有扣费流水" }}
          summary={() => report ? (
            <Table.Summary fixed>
              <Table.Summary.Row className="font-medium">
                <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                <Table.Summary.Cell index={1} align="right">{report.totals.calls}</Table.Summary.Cell>
                <Table.Summary.Cell index={2} align="right">{report.totals.credits.toLocaleString("zh-CN")}</Table.Summary.Cell>
                <Table.Summary.Cell index={3} align="right">{money(report.totals.cost_cny)}</Table.Summary.Cell>
                <Table.Summary.Cell index={4} align="right">{money(report.totals.net_revenue_cny, 2)}</Table.Summary.Cell>
                <Table.Summary.Cell index={5} align="right"><span className={marginClass(report.totals.margin_cny)}>{money(report.totals.margin_cny)}</span></Table.Summary.Cell>
                <Table.Summary.Cell index={6} align="right">{percentage(report.totals.margin_rate)}</Table.Summary.Cell>
                <Table.Summary.Cell index={7} align="right">{coverage(report.totals.coverage)}</Table.Summary.Cell>
                <Table.Summary.Cell index={8} align="right">{report.totals.token_calls}</Table.Summary.Cell>
                <Table.Summary.Cell index={9} align="right">{report.totals.refunds} 笔</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          ) : null}
        />
      </div>
    </div>
  )
}