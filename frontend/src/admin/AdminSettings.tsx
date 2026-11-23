import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Input, Select, Tabs, Tag, TreeSelect, message } from "antd"
import { ArrowLeft, Search, UserPlus, Users } from "lucide-react"
import { lazy, Suspense, useMemo, useState } from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"
import { apiErrorMessage, jsonMutation, requestJson, User, UserRole } from "../api"
import { CenteredStatus, PASSWORD_MIN_LENGTH } from "../auth/AuthScreens"
import RenameUserModal from "../components/RenameUserModal"
import ThemeToggle from "../components/ThemeToggle"
import type { Enterprise } from "../credits/credits"
import { adminTabPath, canAccessAdminTab, isAdminTab, PATHS } from "../paths"
import CreateAccountModal from "./CreateAccountModal"
import BatchCreateAccountsModal from "./BatchCreateAccountsModal"
import EnterpriseTreePanel, { type EnterpriseTreePanelNode } from "./EnterpriseTreePanel"
import {
  ACCOUNT_SCOPE_ALL,
  ACCOUNT_SCOPE_UNASSIGNED,
  ENTERPRISE_GROUP_NODE_KEY,
  buildEnterpriseSelectTree,
  buildEnterpriseTree,
  enterprisePath,
  enterpriseScopeKey,
  filterAccounts,
  parseAccountScopeKey,
  rollupMemberCounts,
  ENTERPRISE_SELECT_POPUP_CLASS,
} from "./enterprise-tree"

const ProviderSettings = lazy(() => import("./ProviderSettings"))
const CreditAdminSettings = lazy(() => import("./CreditAdminSettings"))
const EnterpriseAdminSettings = lazy(() => import("./EnterpriseAdminSettings"))
const QiniuStorageSettings = lazy(() => import("./QiniuStorageSettings"))
const LlmProviderSettings = lazy(() => import("./LlmProviderSettings"))
const VlmProviderSettings = lazy(() => import("./VlmProviderSettings"))
const TtsProviderSettings = lazy(() => import("./TtsProviderSettings"))
const MailProviderSettings = lazy(() => import("./MailProviderSettings"))

const roleLabel: Record<UserRole, string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  employee: "员工",
}

function lockMinutesLeft(seconds?: number) {
  return Math.max(1, Math.ceil((seconds ?? 0) / 60))
}

export default function AdminSettings({ user, csrfToken }: { user: User; csrfToken: string }) {
  const { tab } = useParams<{ tab: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [batchCreateOpen, setBatchCreateOpen] = useState(false)
  const [renamingAccount, setRenamingAccount] = useState<User>()
  const [resettingUserId, setResettingUserId] = useState<string>()
  const [resetPassword, setResetPassword] = useState("")
  const [accountSearch, setAccountSearch] = useState("")
  const [scopeKey, setScopeKey] = useState<string>(ACCOUNT_SCOPE_ALL)
  const usersQuery = useQuery({ queryKey: ["admin-users"], queryFn: () => requestJson<User[]>("/api/admin/users") })
  const enterprisesQuery = useQuery({
    queryKey: ["admin-enterprises"],
    queryFn: () => requestJson<Enterprise[]>("/api/admin/enterprises"),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] })
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: UserRole; is_active?: boolean } }) => requestJson<User>(`/api/admin/users/${id}`, jsonMutation(csrfToken, body, "PATCH")),
    onSuccess: refresh,
  })
  const resetMutation = useMutation({
    mutationFn: (id: string) => requestJson<User>(`/api/admin/users/${id}/reset-password`, jsonMutation(csrfToken, { password: resetPassword })),
    onSuccess: () => { setResettingUserId(undefined); setResetPassword(""); refresh() },
  })
  const unlockMutation = useMutation({
    mutationFn: (id: string) => requestJson<{ ok: boolean; cleared: number; login_blocked_seconds: number }>(`/api/admin/users/${id}/unlock-login`, jsonMutation(csrfToken, {})),
    onSuccess: (result) => {
      refresh()
      if (result.cleared > 0) message.success("已解除登录失败限制，该账号可以立即重试登录")
      else message.info("该账号当前没有登录限制")
    },
  })
  const assignEnterpriseMutation = useMutation({
    mutationFn: ({ id, enterpriseId }: { id: string; enterpriseId: string | null }) =>
      requestJson<User>(`/api/admin/users/${id}`, jsonMutation(csrfToken, { enterprise_id: enterpriseId }, "PATCH")),
    onSuccess: (updated) => {
      message.success(updated.enterprise_name
        ? `已将「${updated.display_name}」归属到 ${updated.enterprise_name}`
        : `已将「${updated.display_name}」调整为平台内部账号`)
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const enterprises = useMemo(() => enterprisesQuery.data ?? [], [enterprisesQuery.data])
  const accounts = useMemo(() => usersQuery.data ?? [], [usersQuery.data])
  const accountScope = parseAccountScopeKey(scopeKey)
  const scopedAccounts = useMemo(
    () => filterAccounts(accounts, enterprises, accountScope, accountSearch),
    [accounts, enterprises, scopeKey, accountSearch],
  )
  const accountCountByEnterprise = useMemo(() => {
    const direct = new Map<string, number>()
    for (const account of accounts) {
      if (!account.enterprise_id) continue
      direct.set(account.enterprise_id, (direct.get(account.enterprise_id) ?? 0) + 1)
    }
    return rollupMemberCounts(enterprises.map((enterprise) => ({ ...enterprise, member_count: direct.get(enterprise.id) ?? 0 }))).total
  }, [accounts, enterprises])
  const unassignedCount = useMemo(() => accounts.filter((account) => !account.enterprise_id).length, [accounts])
  const enterpriseSelectTree = useMemo(() => buildEnterpriseSelectTree(enterprises), [enterprises])
  const roleOptions = useMemo(
    () => [
      { value: "employee" as UserRole, label: "员工" },
      ...(user.role === "super_admin"
        ? [
            { value: "admin" as UserRole, label: "管理员" },
            { value: "super_admin" as UserRole, label: "超级管理员" },
          ]
        : []),
    ],
    [user.role],
  )
  const accountTreeNodes = useMemo<EnterpriseTreePanelNode[]>(() => {
    const convert = (node: ReturnType<typeof buildEnterpriseTree>[number]): EnterpriseTreePanelNode => ({
      key: enterpriseScopeKey(node.enterprise.id),
      label: enterprisePath(enterprises, node.enterprise.id),
      title: (
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={`truncate ${node.enterprise.status === "active" ? "text-[#1f2937]" : "text-[#9ca3af]"}`}>{node.enterprise.name}</span>
          <span className="shrink-0 text-[11px] tabular-nums text-[#9ca3af]">{accountCountByEnterprise.get(node.enterprise.id) ?? 0}</span>
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
        label: "全部账号",
        title: <span className="flex items-center gap-2 text-[#1f2937]">全部账号<span className="text-[11px] tabular-nums text-[#9ca3af]">{accounts.length}</span></span>,
      },
      {
        key: ACCOUNT_SCOPE_UNASSIGNED,
        label: "平台内部 未分配",
        title: <span className="flex items-center gap-2 text-[#1f2937]">平台内部 / 未分配<span className="text-[11px] tabular-nums text-[#9ca3af]">{unassignedCount}</span></span>,
      },
      ...(roots.length
        ? [{
            key: ENTERPRISE_GROUP_NODE_KEY,
            label: "企业架构",
            selectable: false,
            title: <span className="flex items-center gap-2 font-medium text-[#6b7280]">企业架构<span className="text-[11px] tabular-nums text-[#9ca3af]">{enterprises.length}</span></span>,
            children: roots.map(convert),
          }]
        : []),
    ]
  }, [enterprises, accounts, accountCountByEnterprise, unassignedCount])
  const scopeLabel = accountScope.kind === "enterprise"
    ? (enterprisePath(enterprises, accountScope.id) || "未知企业（可能已被删除）")
    : accountScope.kind === "unassigned" ? "平台内部 / 未分配" : "全部账号"

  if (!tab || !isAdminTab(tab) || !canAccessAdminTab(user.role, tab)) {
    return <Navigate to={PATHS.adminAccounts} replace />
  }

  return <div className="studio-admin-shell min-h-screen bg-[#f8f9fa] text-[#1f2937]">
    <header className="flex h-[68px] items-center justify-between border-b border-black/[0.06] bg-white px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => navigate(PATHS.generateVideo)} title="返回创作台" className="grid size-9 place-items-center rounded-lg text-[#4b5563] transition hover:bg-black/[0.04] hover:text-[#111827]">
          <ArrowLeft size={18} />
        </button>
        <span className="h-6 w-px bg-black/[0.08]" />
        <Users size={18} className="text-[#7047f6]" />
        <h1 className="text-base font-semibold text-[#111827]">管理设置</h1>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <div className="text-right">
          <p className="text-sm font-medium text-[#111827]">{user.display_name}</p>
          <p className="text-[11px] text-[#6b7280]">{roleLabel[user.role]}</p>
        </div>
      </div>
    </header>
    <div className="mx-auto max-w-[1680px] px-5 pt-4 lg:px-8">
      <Tabs
        activeKey={tab}
        onChange={(key) => { if (isAdminTab(key) && canAccessAdminTab(user.role, key)) navigate(adminTabPath(key)) }}
        items={[
          { key: "accounts", label: "账号管理" },
          { key: "enterprises", label: "企业管理" },
          { key: "credits", label: "积分管理" },
          ...(user.role === "super_admin"
            ? [
                { key: "providers", label: "AI 供应商" },
                { key: "llm", label: "LLM 大模型" },
                { key: "vlm", label: "VLM 视觉模型" },
                { key: "tts", label: "TTS 语音合成" },
                { key: "storage", label: "媒体存储" },
                { key: "mail", label: "邮件服务" },
              ]
            : []),
        ]}
      />
    </div>
    {tab === "accounts" ? (
      <main className="mx-auto max-w-[1680px] px-5 py-6 pb-10 lg:px-8">
        <div className="grid items-start gap-6 lg:grid-cols-[300px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
        <EnterpriseTreePanel
          title="企业架构"
          subtitle="按企业层级筛选账号；父节点含全部下级企业成员"
          searchPlaceholder="搜索企业名称"
          selectedKey={scopeKey}
          onSelect={setScopeKey}
          nodes={accountTreeNodes}
          loading={enterprisesQuery.isLoading}
        />
        </div>

        <section className="min-w-0 rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-[#111827]">{scopeLabel}</h2>
              <p className="mt-1 text-xs text-[#6b7280]">
                当前范围 {scopedAccounts.length} 个账号 · 全部 {accounts.length} 个，其中平台内部 {unassignedCount} 个
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Input
                allowClear
                value={accountSearch}
                onChange={(event) => setAccountSearch(event.target.value)}
                prefix={<Search size={13} className="text-[#9ca3af]" />}
                placeholder="搜索姓名 / 账号 / 邮箱 / 企业"
                className="w-[240px]"
                aria-label="搜索账号"
              />
              <Button onClick={refresh} className="shrink-0">
                刷新状态
              </Button>
              <Button
                icon={<Users size={14} />}
                onClick={() => setBatchCreateOpen(true)}
                className="shrink-0"
              >
                批量新增
              </Button>
              <Button
                type="primary"
                icon={<UserPlus size={14} />}
                onClick={() => setCreateOpen(true)}
                className="shrink-0"
              >
                新增账号
              </Button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border border-black/[0.06]">
            <table className="w-full min-w-[1160px] table-fixed text-left text-sm">
              <colgroup>
                <col />
                <col className="w-[150px]" />
                <col className="w-[190px]" />
                <col className="w-[150px]" />
                <col className="w-[180px]" />
                <col className="w-[340px]" />
              </colgroup>
              <thead className="border-b border-black/[0.06] bg-[#f9fafb] text-xs font-medium text-[#6b7280]">
                <tr>
                  <th className="whitespace-nowrap px-4 py-3">员工</th>
                  <th className="whitespace-nowrap px-4 py-3">角色</th>
                  <th className="whitespace-nowrap px-4 py-3">所属企业</th>
                  <th className="whitespace-nowrap px-4 py-3">状态</th>
                  <th className="whitespace-nowrap px-4 py-3">最近登录</th>
                  <th className="whitespace-nowrap px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.06]">
                {scopedAccounts.map((account) => (
                  <tr key={account.id} className="transition hover:bg-[#f9fafb]">
                    <td className="px-4 py-3">
                      <p className="truncate font-medium text-[#111827]" title={account.display_name}>{account.display_name}</p>
                      <p className="mt-0.5 truncate text-xs text-[#6b7280]" title={account.username}>
                        {account.username}
                        {account.must_change_password ? " · 待修改初始密码" : ""}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-[#9ca3af]" title={account.email || undefined}>{account.email || "未绑定找回邮箱"}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <Select
                        size="small"
                        className="w-full"
                        value={account.role}
                        disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee")}
                        onChange={(value) => updateMutation.mutate({ id: account.id, body: { role: value } })}
                        options={roleOptions}
                        aria-label={`设置 ${account.display_name} 的角色`}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <TreeSelect
                        value={account.enterprise_id ?? undefined}
                        onChange={(value) => assignEnterpriseMutation.mutate({ id: account.id, enterpriseId: value ?? null })}
                        treeData={enterpriseSelectTree}
                        treeDefaultExpandAll
                        showSearch
                        treeNodeFilterProp="title"
                        allowClear
                        size="small"
                        placeholder="平台内部"
                        className="w-full"
                        classNames={ENTERPRISE_SELECT_POPUP_CLASS}
                        aria-label={`设置 ${account.display_name} 的所属企业`}
                        disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee") || assignEnterpriseMutation.isPending}
                        popupMatchSelectWidth={260}
                        title={account.enterprise_name ? enterprisePath(enterprises, account.enterprise_id ?? "") : "平台内部"}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`whitespace-nowrap ${account.is_active ? "font-medium text-emerald-600" : "text-[#9ca3af]"}`}>
                        {account.is_active ? "已启用" : "已停用"}
                      </span>
                      {account.login_blocked ? (
                        <div className="mt-1 text-xs font-medium text-amber-600">
                          <p className="whitespace-nowrap">登录锁定</p>
                          <p className="whitespace-nowrap">剩余 {lockMinutesLeft(account.login_blocked_seconds)} 分钟</p>
                        </div>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs tabular-nums text-[#6b7280]">
                      {account.last_login_at ? new Date(account.last_login_at).toLocaleString("zh-CN", { hour12: false }) : "尚未登录"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button size="small" onClick={() => setRenamingAccount(account)}>
                          编辑资料
                        </Button>
                        <Button
                          size="small"
                          className="!text-[#7047f6]"
                          onClick={() => { setResettingUserId(account.id); setResetPassword("") }}
                        >
                          重置密码
                        </Button>
                        {account.login_blocked ? (
                          <Button
                            size="small"
                            disabled={unlockMutation.isPending}
                            className="!border-amber-500/40 !text-amber-700"
                            onClick={() => unlockMutation.mutate(account.id)}
                          >
                            解除登录限制
                          </Button>
                        ) : null}
                        <Button
                          size="small"
                          disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee")}
                          onClick={() => updateMutation.mutate({ id: account.id, body: { is_active: !account.is_active } })}
                        >
                          {account.is_active ? "停用" : "启用"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!usersQuery.isLoading && scopedAccounts.length === 0 ? (
              <p className="py-12 text-center text-sm text-[#6b7280]">
                {accounts.length === 0
                  ? "还没有账号，点右上角「新增账号」创建第一个账号"
                  : "当前企业范围 / 搜索条件下没有账号，可切换到「全部账号」"}
              </p>
            ) : null}
            {usersQuery.isLoading ? <p className="py-12 text-center text-sm text-[#6b7280]">正在读取账号</p> : null}
          </div>
          {resettingUserId ? (
            <form onSubmit={(event) => { event.preventDefault(); resetMutation.mutate(resettingUserId) }} className="mt-5 flex flex-col gap-3 border-t border-black/[0.06] pt-5 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1">
                <label htmlFor="reset-user-password" className="mb-1.5 block text-xs font-medium text-[#4b5563]">新的初始密码</label>
                <Input.Password
                  id="reset-user-password"
                  value={resetPassword}
                  onChange={(event) => setResetPassword(event.target.value)}
                  autoComplete="new-password"
                  minLength={PASSWORD_MIN_LENGTH}
                  autoFocus
                  placeholder={`至少 ${PASSWORD_MIN_LENGTH} 位，员工下次登录需修改`}
                />
              </div>
              <Button type="primary" htmlType="submit" disabled={resetPassword.length < PASSWORD_MIN_LENGTH || resetMutation.isPending}>
                确认重置
              </Button>
              <Button onClick={() => setResettingUserId(undefined)}>
                取消
              </Button>
            </form>
          ) : null}
          {(updateMutation.isError || resetMutation.isError || unlockMutation.isError || assignEnterpriseMutation.isError) ? <p className="mt-4 text-sm text-red-600">{updateMutation.error?.message ?? resetMutation.error?.message ?? unlockMutation.error?.message ?? assignEnterpriseMutation.error?.message}</p> : null}
        </section>
        </div>
        {createOpen ? (
          <CreateAccountModal
            csrfToken={csrfToken}
            actor={user}
            enterprises={enterprises}
            defaultEnterpriseId={accountScope.kind === "enterprise" ? accountScope.id : undefined}
            onClose={() => setCreateOpen(false)}
          />
        ) : null}
        {batchCreateOpen ? (
          <BatchCreateAccountsModal
            csrfToken={csrfToken}
            enterprises={enterprises}
            defaultEnterpriseId={accountScope.kind === "enterprise" ? accountScope.id : undefined}
            onClose={() => setBatchCreateOpen(false)}
          />
        ) : null}
        {renamingAccount ? (
          <RenameUserModal
            target={renamingAccount}
            csrfToken={csrfToken}
            self={renamingAccount.id === user.id}
            onClose={() => setRenamingAccount(undefined)}
            onUpdated={refresh}
          />
        ) : null}
      </main>
    ) : (
      <Suspense fallback={<CenteredStatus label="正在加载设置" />}>
        {tab === "credits" ? (
          <CreditAdminSettings csrfToken={csrfToken} />
        ) : tab === "enterprises" ? (
          <EnterpriseAdminSettings csrfToken={csrfToken} />
        ) : tab === "providers" ? (
          <ProviderSettings csrfToken={csrfToken} />
        ) : tab === "llm" ? (
          <LlmProviderSettings csrfToken={csrfToken} />
        ) : tab === "vlm" ? (
          <VlmProviderSettings csrfToken={csrfToken} />
        ) : tab === "tts" ? (
          <TtsProviderSettings csrfToken={csrfToken} />
        ) : tab === "mail" ? (
          <MailProviderSettings csrfToken={csrfToken} />
        ) : (
          <QiniuStorageSettings csrfToken={csrfToken} />
        )}
      </Suspense>
    )}
  </div>
}
