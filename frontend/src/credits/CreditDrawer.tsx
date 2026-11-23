import { useEffect, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Alert, Button, Drawer, Table, Tag, Tooltip } from "antd"
import { RefreshCw } from "lucide-react"
import { requestJson } from "../api"
import {
  CREDIT_TRANSACTION_LABELS,
  CREDIT_TRANSACTION_COLORS,
  type CreditAccount,
  type CreditTransaction,
  type CreditTransactionType,
  formatCredits,
  friendlyCreditReason,
  usageMetaSummary,
} from "./credits"

const PAGE_SIZE = 20
const balanceCard = "rounded-xl border border-[color:var(--studio-border)] bg-[var(--studio-surface-raised)] px-4 py-3"
const secondaryText = "text-[color:var(--studio-text-secondary)]"

function typeTag(type: CreditTransactionType) {
  return <Tag color={CREDIT_TRANSACTION_COLORS[type]} className="!m-0">{CREDIT_TRANSACTION_LABELS[type] ?? type}</Tag>
}

type Props = {
  open: boolean
  onClose: () => void
}

/** 积分明细抽屉：余额概览 + 消耗/退款/充值流水分页列表。 */
export function CreditDrawer({ open, onClose }: Props) {
  const [page, setPage] = useState(1)
  const accountQuery = useQuery({
    queryKey: ["credits-me"],
    queryFn: () => requestJson<CreditAccount>("/api/credits/me"),
    enabled: open,
  })
  const transactionsQuery = useQuery({
    queryKey: ["credits-transactions", page],
    queryFn: ({ signal }) => requestJson<CreditTransaction[]>(`/api/credits/transactions?limit=${PAGE_SIZE + 1}&offset=${(page - 1) * PAGE_SIZE}`, { signal }),
    placeholderData: keepPreviousData,
    enabled: open,
  })
  useEffect(() => {
    if (!open) setPage(1)
  }, [open])

  const account = accountQuery.data
  const rows = transactionsQuery.data ?? []
  const loadError = accountQuery.error ?? transactionsQuery.error

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="我的积分"
      width={560}
      className="studio-credit-drawer"
      extra={
        <Button
          type="text"
          size="small"
          icon={<RefreshCw size={14} className={transactionsQuery.isFetching ? "animate-spin" : undefined} />}
          onClick={() => { void accountQuery.refetch(); void transactionsQuery.refetch() }}
          aria-label="刷新积分明细"
        />
      }
    >
      <div className="grid grid-cols-3 gap-3">
        <div className={balanceCard}>
          <p className={`text-xs ${secondaryText}`}>{account?.scope === "enterprise" ? "企业钱包余额" : "当前余额"}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{formatCredits(account?.balance)} <span className={`text-xs font-normal ${secondaryText}`}>积分</span></p>
        </div>
        <div className={balanceCard}>
          <p className={`text-xs ${secondaryText}`}>累计充值</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{formatCredits(account?.total_recharged)}</p>
        </div>
        <div className={balanceCard}>
          <p className={`text-xs ${secondaryText}`}>净消耗</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{formatCredits(account?.total_consumed)}</p>
        </div>
      </div>
      <p className={`mt-3 text-xs leading-5 ${secondaryText}`}>
        {account?.scope === "enterprise" && account.enterprise ? (
          <>余额和累计用量由「<strong>{account.enterprise.name}</strong>」成员共享。下方是此账号产生的流水。</>
        ) : (
          <><strong>100 积分 = 1 元</strong>。任务提交时预扣，失败后退回。余额不足时请联系管理员。</>
        )}
      </p>
      {loadError ? <Alert className="mt-3" type="error" showIcon title={loadError.message} /> : null}
      <Table<CreditTransaction>
        className="mt-4"
        size="small"
        // 说明列的 truncate 文本在 auto 布局下会按整行 min-content 撑宽表格，固定布局才能约束在抽屉内。
        tableLayout="fixed"
        rowKey={(record) => `${record.scope ?? "user"}:${record.id}`}
        loading={transactionsQuery.isFetching}
        dataSource={rows.slice(0, PAGE_SIZE)}
        locale={{ emptyText: transactionsQuery.isError ? "流水加载失败" : "暂无积分流水" }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: (page - 1) * PAGE_SIZE + rows.length,
          simple: { readOnly: true },
          hideOnSinglePage: true,
          onChange: (next) => setPage(next),
          showSizeChanger: false,
        }}
        columns={[
          {
            title: "时间",
            width: 150,
            render: (_, record) => <span className="whitespace-nowrap text-xs">{new Date(record.created_at).toLocaleString("zh-CN", { hour12: false })}</span>,
          },
          { title: "类型", width: 76, render: (_, record) => typeTag(record.type) },
          {
            title: "变动",
            width: 90,
            align: "right",
            render: (_, record) => (
              <span className={`tabular-nums font-medium ${record.delta >= 0 ? "text-[color:var(--studio-success)]" : "text-[color:var(--studio-danger)]"}`}>
                {record.delta >= 0 ? "+" : ""}{formatCredits(record.delta)}
              </span>
            ),
          },
          {
            title: "说明",
            render: (_, record) => (
              <Tooltip title={[
                friendlyCreditReason(record.reason),
                record.meta?.model ? `模型 ${record.meta.model}` : null,
              ].filter(Boolean).join(" · ")}>
                <span className="block">
                  <span className="line-clamp-2 text-xs">{friendlyCreditReason(record.reason) || "—"}</span>
                  {record.meta ? <span className={`block truncate text-xs ${secondaryText}`}>{usageMetaSummary(record.meta)}</span> : null}
                  {record.scope === "enterprise" ? <span className={`block truncate text-xs ${secondaryText}`}>{record.enterprise_name || "企业钱包"}</span> : null}
                </span>
              </Tooltip>
            ),
          },
        ]}
      />
    </Drawer>
  )
}
