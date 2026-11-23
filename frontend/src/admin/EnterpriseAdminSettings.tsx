import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Checkbox, Drawer, Input, Modal, Segmented, Select, Switch, Table, Tabs, Tag, Tooltip, TreeSelect, message,
} from "antd"
import { Building2, RefreshCw } from "lucide-react"
import { apiErrorMessage, jsonMutation, requestJson, type User } from "../api"
import {
  type Enterprise,
  type EnterpriseCreditTransaction,
  type EnterpriseDetail,
  type EnterpriseMember,
  type EnterpriseModelKind,
  type EnterprisePolicyItem,
  ENTERPRISE_KIND_LABELS,
  ENTERPRISE_POLICY_MODE_LABELS,
  formatCredits,
} from "../credits/credits"
import { CreditAdjustmentModal } from "./CreditAdjustmentModal"
import MemberQuotaModal from "./MemberQuotaModal"
import EnterpriseTreePanel, { type EnterpriseTreePanelNode } from "./EnterpriseTreePanel"
import {
  ACCOUNT_SCOPE_ALL,
  ENTERPRISE_GROUP_NODE_KEY,
  ENTERPRISE_SELECT_POPUP_CLASS,
  buildEnterpriseSelectTree,
  buildEnterpriseTree,
  collectSubtreeIds,
  enterprisePath,
  enterpriseScopeKey,
  filterEnterprises,
  parseAccountScopeKey,
  rollupMemberCounts,
} from "./enterprise-tree"

const MODEL_KINDS: EnterpriseModelKind[] = ["video", "image", "llm", "vlm"]

const KIND_HINTS: Record<EnterpriseModelKind, string> = {
  video: "文生视频 / 图生视频 / 多参考视频与视频工具工作流，按工作流 ID 勾选。",
  image: "生图与图片编辑工作流（含云端生图），按工作流 ID 勾选。",
  llm: "大语言能力按功能开放：写稿、拆解、导演台、助手与音乐对话等。",
  vlm: "视觉理解能力按功能开放：看图分析、图片反推提示词等。",
}

const TRANSACTION_TYPES = [
  { value: "", label: "全部" },
  { value: "admin_recharge", label: "充值" },
  { value: "admin_adjust", label: "调整" },
  { value: "consume", label: "消耗" },
  { value: "refund", label: "退款" },
]

const ROLE_LABELS: Record<string, string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  employee: "员工",
}

type PolicyDraft = Record<EnterpriseModelKind, EnterprisePolicyItem>

function normalizePolicies(policies: EnterprisePolicyItem[]): PolicyDraft {
  const draft = {} as PolicyDraft
  for (const kind of MODEL_KINDS) {
    const configured = policies.find((item) => item.model_kind === kind)
    draft[kind] = {
      model_kind: kind,
      mode: configured?.mode ?? "all",
      models: configured?.models ?? [],
    }
  }
  return draft
}

/** 管理端企业管理：企业入驻登记、成员分配、企业钱包充值与成员用量、模型访问策略。 */
export default function EnterpriseAdminSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const [scopeKey, setScopeKey] = useState<string>(ACCOUNT_SCOPE_ALL)
  const [createOpen, setCreateOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerTab, setDrawerTab] = useState("members")

  // 新增企业表单
  const [newName, setNewName] = useState("")
  const [newCode, setNewCode] = useState("")
  const [newParentId, setNewParentId] = useState<string | undefined>()
  const [newContact, setNewContact] = useState("")
  const [newPhone, setNewPhone] = useState("")
  const [newNotes, setNewNotes] = useState("")

  // 企业详情编辑
  const [editName, setEditName] = useState("")
  const [editCode, setEditCode] = useState("")
  const [editParentId, setEditParentId] = useState<string | undefined>()
  const [editContact, setEditContact] = useState("")
  const [editPhone, setEditPhone] = useState("")
  const [editNotes, setEditNotes] = useState("")
  const [editStatus, setEditStatus] = useState<boolean>(true)

  // 充值 / 绑定 / 策略
  const [rechargeTarget, setRechargeTarget] = useState<Enterprise | null>(null)
  const [bindUserId, setBindUserId] = useState<string | undefined>()
  const [quotaTarget, setQuotaTarget] = useState<EnterpriseMember | null>(null)
  const [policyDrafts, setPolicyDrafts] = useState<PolicyDraft | null>(null)
  const [transactionType, setTransactionType] = useState("")

  const enterprisesQuery = useQuery({
    queryKey: ["admin-enterprises"],
    queryFn: () => requestJson<Enterprise[]>("/api/admin/enterprises"),
  })
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => requestJson<User[]>("/api/admin/users"),
  })
  const detailQuery = useQuery({
    queryKey: ["admin-enterprise-detail", detailId],
    queryFn: () => requestJson<EnterpriseDetail>(`/api/admin/enterprises/${detailId}`),
    enabled: detailId !== null,
  })
  const membersQuery = useQuery({
    queryKey: ["admin-enterprise-members", detailId],
    queryFn: () => requestJson<EnterpriseMember[]>(`/api/admin/enterprises/${detailId}/members`),
    enabled: detailId !== null,
  })
  const transactionsQuery = useQuery({
    queryKey: ["admin-enterprise-transactions", detailId, transactionType],
    queryFn: () => requestJson<EnterpriseCreditTransaction[]>(
      `/api/admin/enterprises/${detailId}/credits/transactions?limit=100${transactionType ? `&type=${transactionType}` : ""}`,
    ),
    enabled: detailId !== null && drawerTab === "credits",
  })

  const enterprises = useMemo(() => enterprisesQuery.data ?? [], [enterprisesQuery.data])
  const scope = parseAccountScopeKey(scopeKey)
  const visibleEnterprises = useMemo(
    () => filterEnterprises(enterprises, scope, search),
    [enterprises, scopeKey, search],
  )
  const memberTotals = useMemo(() => rollupMemberCounts(enterprises).total, [enterprises])
  const enterpriseSelectTree = useMemo(() => buildEnterpriseSelectTree(enterprises), [enterprises])
  const editParentTree = useMemo(
    () => (detailId ? buildEnterpriseSelectTree(enterprises, { excludeIds: collectSubtreeIds(enterprises, detailId) }) : []),
    [enterprises, detailId],
  )
  const enterpriseTreeNodes = useMemo<EnterpriseTreePanelNode[]>(() => {
    const convert = (node: ReturnType<typeof buildEnterpriseTree>[number]): EnterpriseTreePanelNode => ({
      key: enterpriseScopeKey(node.enterprise.id),
      label: enterprisePath(enterprises, node.enterprise.id),
      title: (
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={`truncate ${node.enterprise.status === "active" ? "text-[#1f2937]" : "text-[#9ca3af]"}`}>{node.enterprise.name}</span>
          <span className="shrink-0 text-[11px] tabular-nums text-[#9ca3af]">{memberTotals.get(node.enterprise.id) ?? 0}</span>
          {node.enterprise.status === "active" ? null : (
            <Tag bordered={false} className="!m-0 !px-1 !text-[10px] !leading-4">停用</Tag>
          )}
        </span>
      ),
      children: node.children.map(convert),
    })
    const roots = buildEnterpriseTree(enterprises)
    return [
      {
        key: ACCOUNT_SCOPE_ALL,
        label: "全部企业",
        title: <span className="flex items-center gap-2 text-[#1f2937]">全部企业<span className="text-[11px] tabular-nums text-[#9ca3af]">{enterprises.length}</span></span>,
      },
      ...(roots.length
        ? [{
            key: ENTERPRISE_GROUP_NODE_KEY,
            label: "企业架构",
            selectable: false,
            title: <span className="flex items-center gap-2 text-xs font-medium text-[#6b7280]">企业架构<span className="text-[11px] tabular-nums text-[#9ca3af]">{enterprises.length}</span></span>,
            children: roots.map(convert),
          }]
        : []),
    ]
  }, [enterprises, memberTotals])
  const scopeLabel = scope.kind === "enterprise"
    ? (enterprisePath(enterprises, scope.id) || "未知企业（可能已被删除）")
    : "全部企业"

  useEffect(() => {
    const detail = detailQuery.data
    if (!detail) return
    setPolicyDrafts(normalizePolicies(detail.policies))
    setEditName(detail.enterprise.name)
    setEditCode(detail.enterprise.code ?? "")
    setEditParentId(detail.enterprise.parent_id ?? undefined)
    setEditContact(detail.enterprise.contact_name ?? "")
    setEditPhone(detail.enterprise.contact_phone ?? "")
    setEditNotes(detail.enterprise.notes ?? "")
    setEditStatus(detail.enterprise.status === "active")
  }, [detailQuery.data])

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
    queryClient.invalidateQueries({ queryKey: ["admin-enterprise-detail", detailId] })
    queryClient.invalidateQueries({ queryKey: ["admin-enterprise-members", detailId] })
    queryClient.invalidateQueries({ queryKey: ["admin-enterprise-transactions", detailId] })
    queryClient.invalidateQueries({ queryKey: ["admin-users"] })
  }

  const createMutation = useMutation({
    mutationFn: () => requestJson<Enterprise>("/api/admin/enterprises", jsonMutation(csrfToken, {
      name: newName.trim(),
      code: newCode.trim() || null,
      parent_id: newParentId ?? null,
      contact_name: newContact.trim() || null,
      contact_phone: newPhone.trim() || null,
      notes: newNotes.trim() || null,
    }, "POST")),
    onSuccess: (enterprise) => {
      message.success(`企业「${enterprise.name}」已创建，可在详情中分配账号与充值`)
      setCreateOpen(false)
      setNewName(""); setNewCode(""); setNewParentId(undefined); setNewContact(""); setNewPhone(""); setNewNotes("")
      queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const updateMutation = useMutation({
    mutationFn: () => requestJson<Enterprise>(`/api/admin/enterprises/${detailId}`, jsonMutation(csrfToken, {
      name: editName.trim(),
      code: editCode.trim() || null,
      parent_id: editParentId ?? null,
      contact_name: editContact.trim() || null,
      contact_phone: editPhone.trim() || null,
      notes: editNotes.trim() || null,
      status: editStatus ? "active" : "disabled",
    }, "PATCH")),
    onSuccess: () => {
      message.success("企业资料已保存")
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const toggleStatusMutation = useMutation({
    mutationFn: (enterprise: Enterprise) => requestJson<Enterprise>(
      `/api/admin/enterprises/${enterprise.id}`,
      jsonMutation(csrfToken, { status: enterprise.status === "active" ? "disabled" : "active" }, "PATCH"),
    ),
    onSuccess: (updated) => {
      message.success(updated.status === "active" ? "企业已启用" : "企业已停用，成员将无法继续分配与消费")
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const deleteMutation = useMutation({
    mutationFn: (enterprise: Enterprise) => requestJson<void>(
      `/api/admin/enterprises/${enterprise.id}`,
      jsonMutation(csrfToken, undefined, "DELETE"),
    ),
    onSuccess: () => {
      message.success("企业已删除")
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const bindMutation = useMutation({
    mutationFn: (userId: string) => requestJson<EnterpriseMember>(
      `/api/admin/enterprises/${detailId}/members`,
      jsonMutation(csrfToken, { user_id: userId }, "POST"),
    ),
    onSuccess: (member) => {
      message.success(`已把「${member.display_name}」分配到当前企业`)
      setBindUserId(undefined)
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const unbindMutation = useMutation({
    mutationFn: (userId: string) => requestJson<User>(
      `/api/admin/enterprises/${detailId}/members/${userId}`,
      jsonMutation(csrfToken, undefined, "DELETE"),
    ),
    onSuccess: () => {
      message.success("已移出企业，该账号恢复个人钱包结算")
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const policiesMutation = useMutation({
    mutationFn: () => {
      if (!policyDrafts) throw new Error("策略尚未加载")
      return requestJson<EnterpriseDetail>(
        `/api/admin/enterprises/${detailId}/policies`,
        jsonMutation(csrfToken, { policies: MODEL_KINDS.map((kind) => policyDrafts[kind]) }, "PUT"),
      )
    },
    onSuccess: () => {
      message.success("模型访问策略已保存，立即对该企业成员生效")
      refreshAll()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const memberIds = useMemo(
    () => new Set((membersQuery.data ?? []).map((item) => item.id)),
    [membersQuery.data],
  )
  const bindOptions = useMemo(() => (usersQuery.data ?? [])
    .filter((account) => !memberIds.has(account.id) && account.role === "employee")
    .map((account) => ({
      value: account.id,
      label: `${account.display_name}（${account.username}${account.enterprise_name ? ` · 现属 ${account.enterprise_name}` : ""}）`,
    })), [usersQuery.data, memberIds])

  const dirtyPolicies = useMemo(() => {
    if (!policyDrafts || !detailQuery.data) return false
    const configured = normalizePolicies(detailQuery.data.policies)
    return MODEL_KINDS.some((kind) => {
      const a = policyDrafts[kind]
      const b = configured[kind]
      return a.mode !== b.mode || a.models.length !== b.models.length || a.models.some((key) => !b.models.includes(key))
    })
  }, [policyDrafts, detailQuery.data])

  const enterpriseColumns = [
    {
      title: "企业",
      render: (_: unknown, record: Enterprise) => (
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#111827]">{record.name}</p>
          <p className="truncate text-xs text-[#6b7280]">{record.code || "未设编码"}{record.contact_name ? ` · ${record.contact_name}` : ""}</p>
          {record.parent_id ? (
            <p className="truncate text-[11px] text-[#9ca3af]" title={enterprisePath(enterprises, record.parent_id)}>
              上级：{enterprisePath(enterprises, record.parent_id)}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      title: "状态",
      width: 90,
      render: (_: unknown, record: Enterprise) => (
        <Tag color={record.status === "active" ? "green" : "default"} className="!m-0">
          {record.status === "active" ? "正常" : "已停用"}
        </Tag>
      ),
    },
    {
      title: "成员数",
      width: 100,
      align: "right" as const,
      render: (_: unknown, record: Enterprise) => {
        const total = memberTotals.get(record.id) ?? record.member_count
        return (
          <Tooltip title={total !== record.member_count ? "直属成员数 / 含下级企业合计" : "直属成员数"}>
            <span className="tabular-nums text-[#374151]">
              {record.member_count}{total !== record.member_count ? <span className="text-[#9ca3af]"> / {total}</span> : null}
            </span>
          </Tooltip>
        )
      },
    },
    {
      title: "企业余额",
      width: 110,
      align: "right" as const,
      render: (_: unknown, record: Enterprise) => <span className="tabular-nums font-semibold text-[#111827]">{formatCredits(record.balance)}</span>,
    },
    { title: "累计充值", width: 100, align: "right" as const, render: (_: unknown, record: Enterprise) => <span className="tabular-nums text-[#374151]">{formatCredits(record.total_recharged)}</span> },
    { title: "累计消耗", width: 100, align: "right" as const, render: (_: unknown, record: Enterprise) => <span className="tabular-nums text-[#374151]">{formatCredits(record.total_consumed)}</span> },
    {
      title: "操作",
      width: 260,
      render: (_: unknown, record: Enterprise) => (
        <div className="flex flex-wrap gap-2">
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => { setDetailId(record.id); setDrawerTab("members") }}
          >
            详情
          </Button>
          <Button size="small" onClick={() => setRechargeTarget(record)}>充值</Button>
          <Button
            size="small"
            danger={record.status === "active"}
            onClick={() => toggleStatusMutation.mutate(record)}
          >
            {record.status === "active" ? "停用" : "启用"}
          </Button>
          {record.member_count === 0 && record.balance === 0 && record.total_consumed === 0 && record.total_recharged === 0 ? (
            <Tooltip title="仅无成员且无钱包流水的企业可删除">
              <Button size="small" danger disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(record)}>删除</Button>
            </Tooltip>
          ) : null}
        </div>
      ),
    },
  ]

  const memberColumns = [
    {
      title: "成员",
      render: (_: unknown, record: EnterpriseMember) => (
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#111827]">{record.display_name}</p>
          <p className="truncate text-xs text-[#6b7280]">{record.username}{record.email ? ` · ${record.email}` : ""}</p>
        </div>
      ),
    },
    { title: "角色", width: 100, render: (_: unknown, record: EnterpriseMember) => <span className="text-sm">{ROLE_LABELS[record.role] ?? record.role}</span> },
    {
      title: "状态",
      width: 80,
      render: (_: unknown, record: EnterpriseMember) => (
        <span className={record.is_active ? "font-medium text-emerald-600" : "text-[#9ca3af]"}>
          {record.is_active ? "已启用" : "已停用"}
        </span>
      ),
    },
    { title: "总消耗", width: 90, align: "right" as const, render: (_: unknown, record: EnterpriseMember) => <span className="tabular-nums text-[#374151]">{formatCredits(record.gross_consumed)}</span> },
    { title: "退款", width: 90, align: "right" as const, render: (_: unknown, record: EnterpriseMember) => <span className="tabular-nums text-[#374151]">{formatCredits(record.refunded)}</span> },
    {
      title: "净消耗",
      width: 100,
      align: "right" as const,
      render: (_: unknown, record: EnterpriseMember) => <span className="tabular-nums font-semibold text-[#111827]">{formatCredits(record.net_consumed)}</span>,
    },
    {
      title: "额度",
      width: 150,
      render: (_: unknown, record: EnterpriseMember) => {
        if (record.quota_period === "none" || record.quota_limit <= 0) {
          return <span className="text-xs text-[#9ca3af]">不限制</span>
        }
        const label = record.quota_period === "monthly" ? "每月" : "累计"
        const exhausted = record.quota_used >= record.quota_limit
        return (
          <Tooltip title={`${label}额度 ${formatCredits(record.quota_limit)} 积分，已用 ${formatCredits(record.quota_used)} 积分`}>
            <div className="min-w-0">
              <p className={`truncate text-xs font-medium ${exhausted ? "text-red-600" : "text-[#374151]"}`}>
                {label} {formatCredits(record.quota_limit)}
              </p>
              <p className="truncate text-[11px] text-[#9ca3af]">
                {exhausted ? "额度已用尽" : `已用 ${formatCredits(record.quota_used)}`}
              </p>
            </div>
          </Tooltip>
        )
      },
    },
    {
      title: "最近活动",
      width: 150,
      render: (_: unknown, record: EnterpriseMember) => (
        <span className="whitespace-nowrap text-xs text-[#6b7280]">
          {record.last_active_at ? new Date(record.last_active_at).toLocaleString("zh-CN", { hour12: false }) : "—"}
        </span>
      ),
    },
    {
      title: "操作",
      width: 140,
      render: (_: unknown, record: EnterpriseMember) => (
        <div className="flex flex-wrap gap-2">
          <Button size="small" onClick={() => setQuotaTarget(record)}>额度</Button>
          <Button size="small" disabled={unbindMutation.isPending} onClick={() => unbindMutation.mutate(record.id)}>移出</Button>
        </div>
      ),
    },
  ]

  const transactionColumns = [
    { title: "时间", width: 160, render: (_: unknown, record: EnterpriseCreditTransaction) => <span className="whitespace-nowrap text-xs">{new Date(record.created_at).toLocaleString("zh-CN", { hour12: false })}</span> },
    {
      title: "成员",
      width: 130,
      render: (_: unknown, record: EnterpriseCreditTransaction) => (
        <span className="truncate text-sm">{record.display_name || record.username || "—"}</span>
      ),
    },
    {
      title: "类型",
      width: 84,
      render: (_: unknown, record: EnterpriseCreditTransaction) => {
        const item = TRANSACTION_TYPES.find((entry) => entry.value === record.type)
        return <Tag color={record.type === "consume" ? "blue" : record.type === "refund" ? "purple" : record.type === "admin_recharge" ? "green" : "gold"} className="!m-0">{item?.label ?? record.type}</Tag>
      },
    },
    {
      title: "变动",
      width: 90,
      align: "right" as const,
      render: (_: unknown, record: EnterpriseCreditTransaction) => (
        <span className={`tabular-nums font-medium ${record.delta >= 0 ? "text-emerald-600" : "text-red-600"}`}>
          {record.delta >= 0 ? "+" : ""}{formatCredits(record.delta)}
        </span>
      ),
    },
    { title: "余额", width: 90, align: "right" as const, render: (_: unknown, record: EnterpriseCreditTransaction) => <span className="tabular-nums text-[#374151]">{formatCredits(record.balance_after)}</span> },
    {
      title: "说明",
      render: (_: unknown, record: EnterpriseCreditTransaction) => (
        <Tooltip title={record.price_key ? `${record.price_key}${record.ref_id ? ` · ${record.ref_type || ""} ${record.ref_id}` : ""}` : undefined}>
          <span className="line-clamp-2 text-xs text-[#374151]">{record.reason || "—"}</span>
        </Tooltip>
      ),
    },
  ]

  return (
    <main className="mx-auto max-w-[1680px] px-5 py-6 pb-10 lg:px-8">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="grid size-10 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]"><Building2 size={19} /></span>
          <div>
            <h2 className="text-base font-semibold text-[#111827]">企业管理</h2>
            <p className="text-xs text-[#6b7280]">集团-子公司层级 · 企业入驻与账号归属 · 钱包充值与成员用量 · 按企业开放视频 / 生图 / 大语言 / 视觉理解模型</p>
          </div>
        </div>
        <Button
          type="primary"
          onClick={() => {
            setNewParentId(scope.kind === "enterprise" ? scope.id : undefined)
            setCreateOpen(true)
          }}
        >
          新增企业
        </Button>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[300px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)]">
        <EnterpriseTreePanel
          title="企业架构"
          subtitle="选中集团可查看其下全部企业；父节点成员数为含下级合计"
          searchPlaceholder="搜索企业名称 / 编码"
          searchValue={search}
          onSearchChange={setSearch}
          selectedKey={scopeKey}
          onSelect={setScopeKey}
          nodes={enterpriseTreeNodes}
          loading={enterprisesQuery.isLoading}
        />

        <section className="min-w-0 rounded-2xl border border-black/[0.06] bg-white p-5 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-[#111827]" title={scopeLabel}>{scopeLabel}</h3>
              <p className="mt-0.5 text-xs text-[#6b7280]">
                当前范围 {visibleEnterprises.length} 家 · 全部 {enterprises.length} 家{search.trim() ? ` · 关键词「${search.trim()}」` : ""}
              </p>
            </div>
            <Button
              type="text"
              size="small"
              className="ml-auto"
              icon={<RefreshCw size={14} className={enterprisesQuery.isFetching ? "animate-spin" : undefined} />}
              onClick={() => void enterprisesQuery.refetch()}
              aria-label="刷新企业列表"
            />
          </div>
          <Table<Enterprise>
            rowKey="id"
            size="middle"
            loading={enterprisesQuery.isLoading}
            dataSource={visibleEnterprises}
            columns={enterpriseColumns}
            pagination={{ hideOnSinglePage: true, showSizeChanger: false }}
            locale={{ emptyText: "当前范围没有企业；可在左上角切换「全部企业」或新增企业" }}
          />
        </section>
      </div>

      <Drawer
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        width={1040}
        title={detailQuery.data ? `企业管理 · ${enterprisePath(enterprises, detailQuery.data.enterprise.id)}` : "企业详情"}
        loading={detailQuery.isLoading && detailId !== null}
      >
        {detailQuery.data ? (
          <Tabs
            activeKey={drawerTab}
            onChange={(key) => setDrawerTab(key)}
            items={[
              { key: "members", label: "成员与用量" },
              { key: "credits", label: "积分与流水" },
              { key: "policies", label: "模型权限" },
              { key: "profile", label: "基本信息" },
            ]}
          />
        ) : null}

        {detailQuery.data && drawerTab === "members" ? (
          <div className="mt-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Select
                value={bindUserId}
                onChange={(value) => setBindUserId(value)}
                showSearch
                optionFilterProp="label"
                allowClear
                placeholder="选择要分配到该企业的员工账号"
                className="min-w-[320px]"
                aria-label="选择要分配的账号"
                options={bindOptions}
                disabled={detailQuery.data.enterprise.status !== "active"}
              />
              <Button
                type="primary"
                disabled={!bindUserId || bindMutation.isPending || detailQuery.data.enterprise.status !== "active"}
                loading={bindMutation.isPending}
                onClick={() => bindUserId && bindMutation.mutate(bindUserId)}
              >
                分配到企业
              </Button>
              {detailQuery.data.enterprise.status !== "active" ? (
                <span className="text-xs text-amber-600">企业已停用，无法分配账号</span>
              ) : null}
              <span className="ml-auto text-xs text-[#6b7280]">共 {membersQuery.data?.length ?? 0} 名成员 · 用量口径：企业钱包消费流水按使用人归集</span>
            </div>
            <Table<EnterpriseMember>
              rowKey="id"
              size="small"
              loading={membersQuery.isLoading}
              dataSource={membersQuery.data ?? []}
              columns={memberColumns}
              pagination={{ hideOnSinglePage: true, showSizeChanger: false }}
            />
          </div>
        ) : null}

        {detailQuery.data && drawerTab === "credits" ? (
          <div className="mt-4">
            <div className="mb-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-black/[0.06] bg-[#f9fafb] p-4">
                <p className="text-xs text-[#6b7280]">企业钱包余额</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-[#111827]">{formatCredits(detailQuery.data.enterprise.balance)}</p>
              </div>
              <div className="rounded-xl border border-black/[0.06] bg-[#f9fafb] p-4">
                <p className="text-xs text-[#6b7280]">累计充值</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-[#111827]">{formatCredits(detailQuery.data.enterprise.total_recharged)}</p>
              </div>
              <div className="rounded-xl border border-black/[0.06] bg-[#f9fafb] p-4">
                <p className="text-xs text-[#6b7280]">累计消耗（退款回减）</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-[#111827]">{formatCredits(detailQuery.data.enterprise.total_consumed)}</p>
              </div>
            </div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Button
                type="primary"
                ghost
                onClick={() => setRechargeTarget(detailQuery.data.enterprise)}
              >
                企业充值 / 调整
              </Button>
              <Select
                value={transactionType}
                onChange={(value) => setTransactionType(String(value))}
                className="min-w-[120px]"
                aria-label="按类型筛选企业流水"
                options={TRANSACTION_TYPES}
              />
              <Button
                type="text"
                size="small"
                icon={<RefreshCw size={14} className={transactionsQuery.isFetching ? "animate-spin" : undefined} />}
                onClick={() => void transactionsQuery.refetch()}
                aria-label="刷新企业流水"
              />
              <span className="ml-auto text-xs text-[#6b7280]">最近 {transactionsQuery.data?.length ?? 0} 条（每页上限 100）</span>
            </div>
            <Table<EnterpriseCreditTransaction>
              rowKey="id"
              size="small"
              loading={transactionsQuery.isLoading}
              dataSource={transactionsQuery.data ?? []}
              columns={transactionColumns}
              pagination={{ hideOnSinglePage: true, showSizeChanger: false, pageSize: 50 }}
            />
          </div>
        ) : null}

        {detailQuery.data && drawerTab === "policies" && policyDrafts ? (
          <div className="mt-4">
            <p className="mb-4 text-xs leading-5 text-[#6b7280]">
              未配置的类型默认全部开放；配置为「仅开放选中」后，该企业成员在创作台与导演台只能使用勾选的模型，
              任务提交与 LLM 调用双重拦截。「全部关闭」直接禁用该类能力。
            </p>
            <div className="space-y-4">
              {MODEL_KINDS.map((kind) => {
                const draft = policyDrafts[kind]
                const catalog = detailQuery.data.catalog[kind] ?? []
                return (
                  <section key={kind} className="rounded-xl border border-black/[0.06] p-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <h3 className="text-sm font-semibold text-[#111827]">{ENTERPRISE_KIND_LABELS[kind]}</h3>
                      <Segmented
                        value={draft.mode}
                        onChange={(value) => setPolicyDrafts((current) => current && ({
                          ...current,
                          [kind]: { ...current[kind], mode: String(value) as EnterprisePolicyItem["mode"] },
                        }))}
                        options={(["all", "whitelist", "none"] as const).map((mode) => ({
                          value: mode,
                          label: ENTERPRISE_POLICY_MODE_LABELS[mode],
                        }))}
                      />
                      <span className="text-xs text-[#6b7280]">{KIND_HINTS[kind]}</span>
                      {draft.mode === "whitelist" ? (
                        <span className="ml-auto text-xs text-[#6b7280]">已勾选 {draft.models.length} / {catalog.length}</span>
                      ) : null}
                    </div>
                    {draft.mode === "whitelist" ? (
                      <div className="mt-3 max-h-56 overflow-y-auto rounded-lg border border-black/[0.08] bg-[#f9fafb] p-3">
                        <Checkbox.Group
                          className="grid grid-cols-1 gap-1.5 md:grid-cols-2 xl:grid-cols-3"
                          value={draft.models}
                          onChange={(values) => setPolicyDrafts((current) => current && ({
                            ...current,
                            [kind]: { ...current[kind], models: values.map(String) },
                          }))}
                          options={catalog.map((entry) => ({ value: entry.key, label: `${entry.label}（${entry.key}）` }))}
                        />
                      </div>
                    ) : null}
                  </section>
                )
              })}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Button
                type="primary"
                loading={policiesMutation.isPending}
                disabled={!dirtyPolicies}
                onClick={() => policiesMutation.mutate()}
              >
                保存模型权限
              </Button>
              {dirtyPolicies ? <span className="text-xs text-amber-600">有未保存的修改</span> : <span className="text-xs text-[#6b7280]">与当前生效配置一致</span>}
              <Button type="text" disabled={!dirtyPolicies} onClick={() => setPolicyDrafts(normalizePolicies(detailQuery.data!.policies))}>放弃修改</Button>
            </div>
          </div>
        ) : null}

        {detailQuery.data && drawerTab === "profile" ? (
          <div className="mt-4 max-w-[560px] space-y-4">
            <label className="block text-xs font-medium text-[#4b5563]">
              企业名称
              <Input value={editName} onChange={(event) => setEditName(event.target.value)} className="mt-1.5" />
            </label>
            <label className="block text-xs font-medium text-[#4b5563]">
              企业编码
              <Input value={editCode} onChange={(event) => setEditCode(event.target.value)} className="mt-1.5" placeholder="可选，唯一" />
            </label>
            <label className="block text-xs font-medium text-[#4b5563]">
              上级企业
              <TreeSelect
                value={editParentId}
                onChange={(value) => setEditParentId(value)}
                allowClear
                showSearch
                treeNodeFilterProp="title"
                treeDefaultExpandAll
                treeData={editParentTree}
                placeholder="顶级企业（无上级）"
                className="mt-1.5 w-full"
                aria-label="选择上级企业"
                classNames={ENTERPRISE_SELECT_POPUP_CLASS}
              />
              <span className="mt-1 block text-[11px] font-normal leading-4 text-[#9ca3af]">
                仅影响组织层级与账号归属筛选，不改变企业钱包与模型权限；自身与下级企业不可选。
              </span>
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-xs font-medium text-[#4b5563]">
                联系人
                <Input value={editContact} onChange={(event) => setEditContact(event.target.value)} className="mt-1.5" />
              </label>
              <label className="block text-xs font-medium text-[#4b5563]">
                联系电话
                <Input value={editPhone} onChange={(event) => setEditPhone(event.target.value)} className="mt-1.5" />
              </label>
            </div>
            <label className="block text-xs font-medium text-[#4b5563]">
              备注
              <Input.TextArea value={editNotes} onChange={(event) => setEditNotes(event.target.value)} rows={3} maxLength={500} className="mt-1.5" />
            </label>
            <div className="flex items-center gap-2">
              <Switch checked={editStatus} onChange={(checked) => setEditStatus(checked)} />
              <span className="text-sm text-[#374151]">{editStatus ? "正常（允许分配账号与消费）" : "已停用（冻结分配与消费）"}</span>
            </div>
            <Button type="primary" loading={updateMutation.isPending} disabled={!editName.trim()} onClick={() => updateMutation.mutate()}>
              保存企业资料
            </Button>
          </div>
        ) : null}
      </Drawer>

      <Modal
        open={createOpen}
        title="新增企业（入驻登记）"
        onCancel={() => setCreateOpen(false)}
        onOk={() => {
          if (!newName.trim()) { message.warning("请填写企业名称"); return }
          createMutation.mutate()
        }}
        okText="创建企业"
        confirmLoading={createMutation.isPending}
        destroyOnHidden
      >
        <div className="grid gap-3">
          <label className="grid gap-1">
            <span className="text-sm text-[#374151]">企业名称（必填）</span>
            <Input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="例如：星河传媒" />
          </label>
          <label className="grid gap-1">
            <span className="text-sm text-[#374151]">企业编码</span>
            <Input value={newCode} onChange={(event) => setNewCode(event.target.value)} placeholder="可选，唯一，用于检索与对外对账" />
          </label>
          <label className="grid gap-1">
            <span className="text-sm text-[#374151]">上级企业</span>
            <TreeSelect
              value={newParentId}
              onChange={(value) => setNewParentId(value)}
              allowClear
              showSearch
              treeNodeFilterProp="title"
              treeDefaultExpandAll
              treeData={enterpriseSelectTree}
              placeholder="不选则为顶级企业（集团）"
              aria-label="选择上级企业"
              classNames={ENTERPRISE_SELECT_POPUP_CLASS}
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1">
              <span className="text-sm text-[#374151]">联系人</span>
              <Input value={newContact} onChange={(event) => setNewContact(event.target.value)} />
            </label>
            <label className="grid gap-1">
              <span className="text-sm text-[#374151]">联系电话</span>
              <Input value={newPhone} onChange={(event) => setNewPhone(event.target.value)} />
            </label>
          </div>
          <label className="grid gap-1">
            <span className="text-sm text-[#374151]">备注</span>
            <Input.TextArea value={newNotes} onChange={(event) => setNewNotes(event.target.value)} rows={2} maxLength={500} placeholder="合作内容、结算方式等" />
          </label>
        </div>
      </Modal>

      {rechargeTarget ? (
        <CreditAdjustmentModal
          target={{ id: rechargeTarget.id, name: rechargeTarget.name, balance: rechargeTarget.balance, scope: "enterprise" }}
          csrfToken={csrfToken}
          onClose={() => setRechargeTarget(null)}
        />
      ) : null}
      {quotaTarget && detailQuery.data ? (
        <MemberQuotaModal
          csrfToken={csrfToken}
          enterpriseId={detailQuery.data.enterprise.id}
          enterpriseName={detailQuery.data.enterprise.name}
          enterpriseBalance={detailQuery.data.enterprise.balance}
          member={quotaTarget}
          onClose={() => setQuotaTarget(null)}
        />
      ) : null}
    </main>
  )
}
