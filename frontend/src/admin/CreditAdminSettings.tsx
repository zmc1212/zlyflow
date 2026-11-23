import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Alert, Button, Input, Segmented, Select, Space, Table, Tag, Tooltip } from "antd"
import { Coins, RefreshCw } from "lucide-react"
import { requestJson } from "../api"
import {
  CREDIT_TRANSACTION_COLORS, CREDIT_TRANSACTION_LABELS, formatCredits, usageMetaSummary,
  type CreditAccount, type CreditTransaction,
} from "../credits/credits"
import { CreditAdjustmentModal, type CreditAdjustmentTarget } from "./CreditAdjustmentModal"
import CreditPricingSettings from "./CreditPricingSettings"
import CreditUsageReport from "./CreditUsageReport"

const PAGE_SIZE = 20
const TRANSACTION_TYPES = [
  { value: "", label: "所有类型" },
  ...Object.entries(CREDIT_TRANSACTION_LABELS).map(([value, label]) => ({ value, label })),
]
const WALLET_SCOPES = [
  { value: "all", label: "所有钱包" },
  { value: "user", label: "个人钱包" },
  { value: "enterprise", label: "企业钱包" },
]
const panelClass = "rounded-2xl border border-[color:var(--studio-border)] bg-[var(--studio-surface)] p-5"
const secondaryText = "text-[color:var(--studio-text-secondary)]"

function pageParams(page: number, filters: Record<string, string>) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE + 1), offset: String((page - 1) * PAGE_SIZE) })
  for (const [name, value] of Object.entries(filters)) if (value) params.set(name, value)
  return params
}

function pagination(page: number, entries: number, onChange: (page: number) => void) {
  return {
    current: page,
    pageSize: PAGE_SIZE,
    total: (page - 1) * PAGE_SIZE + entries,
    simple: { readOnly: true },
    hideOnSinglePage: true,
    showSizeChanger: false,
    onChange,
  }
}

const accountName = (account: CreditAccount) => account.display_name || account.username || account.user_id

export default function CreditAdminSettings({ csrfToken }: { csrfToken: string }) {
  const [section, setSection] = useState<"accounts" | "prices" | "transactions" | "report">("accounts")
  const [accountSearch, setAccountSearch] = useState("")
  const [accountPage, setAccountPage] = useState(1)
  const [adjustTarget, setAdjustTarget] = useState<CreditAdjustmentTarget | null>(null)
  const [transactionSearch, setTransactionSearch] = useState("")
  const [transactionType, setTransactionType] = useState("")
  const [transactionScope, setTransactionScope] = useState("all")
  const [transactionUser, setTransactionUser] = useState<{ id: string; label: string } | null>(null)
  const [transactionPage, setTransactionPage] = useState(1)

  const accountsQuery = useQuery({
    queryKey: ["admin-credit-accounts", accountSearch, accountPage],
    queryFn: ({ signal }) => requestJson<CreditAccount[]>(`/api/admin/credits/accounts?${pageParams(accountPage, { query: accountSearch })}`, { signal }),
    placeholderData: keepPreviousData,
    enabled: section === "accounts",
  })
  const transactionsQuery = useQuery({
    queryKey: ["admin-credit-transactions", transactionScope, transactionType, transactionUser?.id, transactionSearch, transactionPage],
    queryFn: ({ signal }) => requestJson<CreditTransaction[]>(`/api/admin/credits/transactions?${pageParams(transactionPage, {
      scope: transactionScope, type: transactionType, user_id: transactionUser?.id ?? "", query: transactionSearch,
    })}`, { signal }),
    placeholderData: keepPreviousData,
    enabled: section === "transactions",
  })

  const openAdjustment = (account: CreditAccount) => {
    const enterprise = account.enterprise
    setAdjustTarget(enterprise
      ? { id: enterprise.id, name: enterprise.name, balance: account.balance, scope: "enterprise" }
      : { id: account.user_id, name: accountName(account), balance: account.balance, scope: "user" })
  }

  const openAccountActivity = (account: CreditAccount) => {
    setTransactionUser({ id: account.user_id, label: accountName(account) })
    setTransactionScope("all")
    setTransactionType("")
    setTransactionSearch("")
    setTransactionPage(1)
    setSection("transactions")
  }

  const accounts = accountsQuery.data ?? []
  const transactions = transactionsQuery.data ?? []

  return (
    <main className="mx-auto max-w-[1680px] px-5 py-6 pb-10 text-[color:var(--studio-text)] lg:px-8">
      <header className="mb-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-[var(--studio-primary-soft)] text-[color:var(--studio-accent-text)]"><Coins size={20} /></span>
          <div>
            <h2 className="text-lg font-semibold">积分管理</h2>
            <p className={`text-xs ${secondaryText}`}>100 积分 = 1 元</p>
          </div>
        </div>
        <Segmented
          aria-label="积分管理功能"
          value={section}
          onChange={setSection}
          options={[
            { value: "accounts", label: "账户与充值" },
            { value: "prices", label: "价格表" },
            { value: "transactions", label: "积分流水" },
            { value: "report", label: "用量毛利" },
          ]}
        />
      </header>

      {section === "accounts" ? (
        <section className={panelClass} aria-label="账户与充值">
          <div className="mb-4 flex items-center justify-between gap-2">
            <Input.Search
              allowClear
              maxLength={128}
              placeholder="搜索用户名、昵称或企业"
              className="!w-[310px]"
              aria-label="搜索积分账户"
              defaultValue={accountSearch}
              onSearch={(value) => { setAccountSearch(value.trim()); setAccountPage(1) }}
            />
            <Button icon={<RefreshCw size={14} />} loading={accountsQuery.isFetching} onClick={() => void accountsQuery.refetch()}>刷新</Button>
          </div>
          {accountsQuery.isError ? <Alert className="mb-3" type="error" showIcon title={accountsQuery.error.message} /> : null}
          <Table<CreditAccount>
            rowKey="user_id"
            size="middle"
            loading={accountsQuery.isFetching}
            dataSource={accounts.slice(0, PAGE_SIZE)}
            locale={{ emptyText: accountsQuery.isError ? "账户加载失败" : "没有匹配的账号" }}
            pagination={pagination(accountPage, accounts.length, setAccountPage)}
            scroll={{ x: 1000 }}
            columns={[
              {
                title: "账号", width: 220,
                render: (_, record) => (
                  <div>
                    <div className="font-medium break-words">{accountName(record)}</div>
                    <div className={`flex flex-wrap items-center gap-1.5 text-xs ${secondaryText}`}>
                      {record.username || record.user_id}
                      {record.role === "super_admin" ? <Tag className="!m-0">免扣费</Tag> : null}
                      {record.is_active === false ? <Tag className="!m-0">已停用</Tag> : null}
                    </div>
                  </div>
                ),
              },
              {
                title: "结算钱包", width: 220,
                render: (_, record) => record.enterprise ? (
                  <div>
                    <div className="break-words">{record.enterprise.name}</div>
                    <div className={`text-xs ${secondaryText}`}>企业钱包 · 成员共享</div>
                  </div>
                ) : <span className={secondaryText}>个人钱包</span>,
              },
              {
                title: "钱包余额", align: "right", width: 110,
                render: (_, record) => <span className="tabular-nums font-semibold">{formatCredits(record.balance)}</span>,
              },
              {
                title: "累计充值", align: "right", width: 110,
                render: (_, record) => <span className="tabular-nums">{formatCredits(record.total_recharged)}</span>,
              },
              {
                title: "净消耗", align: "right", width: 110,
                render: (_, record) => <span className="tabular-nums">{formatCredits(record.total_consumed)}</span>,
              },
              {
                title: "操作", width: 225,
                render: (_, record) => (
                  <Space size={2}>
                    <Button type="link" size="small" onClick={() => openAdjustment(record)}>
                      {record.enterprise ? "调整企业积分" : "调整个人积分"}
                    </Button>
                    <Button type="link" size="small" onClick={() => openAccountActivity(record)}>查看流水</Button>
                  </Space>
                ),
              },
            ]}
          />
        </section>
      ) : null}

      <section className={panelClass} hidden={section !== "prices"} aria-label="价格表">
        <CreditPricingSettings csrfToken={csrfToken} active={section === "prices"} />
      </section>

      <section className={panelClass} hidden={section !== "report"} aria-label="用量毛利报表">
        <CreditUsageReport active={section === "report"} />
      </section>

      {section === "transactions" ? (
        <section className={panelClass} aria-label="积分流水">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input.Search
              key={transactionUser?.id ?? "all"}
              allowClear
              maxLength={128}
              placeholder="搜索账号、企业或任务 ID"
              className="!w-[290px]"
              aria-label="搜索积分流水"
              defaultValue={transactionSearch}
              onSearch={(value) => { setTransactionSearch(value.trim()); setTransactionPage(1) }}
            />
            <Select
              value={transactionScope}
              onChange={(value) => { setTransactionScope(value); setTransactionPage(1) }}
              className="min-w-[120px]"
              aria-label="按钱包筛选流水"
              options={WALLET_SCOPES}
            />
            <Select
              value={transactionType}
              onChange={(value) => { setTransactionType(value); setTransactionPage(1) }}
              className="min-w-[110px]"
              aria-label="按类型筛选流水"
              options={TRANSACTION_TYPES}
            />
            {transactionUser ? (
              <Tag closable onClose={() => { setTransactionUser(null); setTransactionPage(1) }}>
                账号 {transactionUser.label}
              </Tag>
            ) : null}
            <Button className="ml-auto" icon={<RefreshCw size={14} />} loading={transactionsQuery.isFetching} onClick={() => void transactionsQuery.refetch()}>刷新</Button>
          </div>
          {transactionsQuery.isError ? <Alert className="mb-3" type="error" showIcon title={transactionsQuery.error.message} /> : null}
          <Table<CreditTransaction>
            rowKey={(record) => `${record.scope ?? "user"}:${record.id}`}
            size="small"
            loading={transactionsQuery.isFetching}
            dataSource={transactions.slice(0, PAGE_SIZE)}
            locale={{ emptyText: transactionsQuery.isError ? "流水加载失败" : "没有匹配的流水" }}
            pagination={pagination(transactionPage, transactions.length, setTransactionPage)}
            scroll={{ x: 1080 }}
            columns={[
              { title: "时间", width: 162, render: (_, record) => <span className="whitespace-nowrap text-xs">{new Date(record.created_at).toLocaleString("zh-CN", { hour12: false })}</span> },
              {
                title: "钱包 / 账号", width: 205,
                render: (_, record) => {
                  const user = record.display_name || record.username || record.user_id
                  const enterprise = record.scope === "enterprise"
                  return (
                    <div className="break-words">
                      <div className="font-medium">{enterprise ? record.enterprise_name || record.enterprise_id || "企业钱包" : user || "—"}</div>
                      <div className={`text-xs ${secondaryText}`}>{enterprise ? `企业${user ? ` · ${user}` : ""}` : "个人钱包"}</div>
                    </div>
                  )
                },
              },
              { title: "类型", width: 84, render: (_, record) => <Tag color={CREDIT_TRANSACTION_COLORS[record.type]}>{CREDIT_TRANSACTION_LABELS[record.type] ?? record.type}</Tag> },
              {
                title: "变动", width: 90, align: "right",
                render: (_, record) => (
                  <span className={`tabular-nums font-medium ${record.delta >= 0 ? "text-[color:var(--studio-success)]" : "text-[color:var(--studio-danger)]"}`}>
                    {record.delta >= 0 ? "+" : ""}{formatCredits(record.delta)}
                  </span>
                ),
              },
              { title: "变动后余额", width: 112, align: "right", render: (_, record) => <span className="tabular-nums">{formatCredits(record.balance_after)}</span> },
              { title: "操作人", width: 110, render: (_, record) => <span className="break-words">{record.actor_username || (record.actor_user_id ? <Tooltip title={record.actor_user_id}>账号已失效</Tooltip> : "系统")}</span> },
              {
                title: "说明 / 关联", width: 280,
                render: (_, record) => {
                  const ref = record.ref_type === "admin_credit_change" ? null : record.ref_id
                  return (
                    <div className="text-xs">
                      <Tooltip title={record.reason}><span className="line-clamp-2">{record.reason || "—"}</span></Tooltip>
                      {record.meta ? <span className={`block truncate ${secondaryText}`}>{usageMetaSummary(record.meta)}</span> : null}
                      {ref || record.price_key ? <Tooltip title={[record.price_key, ref].filter(Boolean).join(" · ")}><span className={`block truncate ${secondaryText}`}>{ref || record.price_key}</span></Tooltip> : null}
                    </div>
                  )
                },
              },
            ]}
          />
        </section>
      ) : null}

      {adjustTarget ? <CreditAdjustmentModal target={adjustTarget} csrfToken={csrfToken} onClose={() => setAdjustTarget(null)} /> : null}
    </main>
  )
}
