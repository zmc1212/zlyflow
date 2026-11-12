import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Tabs, message } from "antd"
import { ArrowLeft, LoaderCircle, UserPlus, Users } from "lucide-react"
import { lazy, Suspense, useState } from "react"
import { Navigate, useNavigate, useParams } from "react-router-dom"
import { jsonMutation, requestJson, User, UserRole } from "../api"
import { CenteredStatus, PASSWORD_MIN_LENGTH, PasswordField } from "../auth/AuthScreens"
import RenameUserModal from "../components/RenameUserModal"
import ThemeToggle from "../components/ThemeToggle"
import { adminTabPath, canAccessAdminTab, isAdminTab, PATHS } from "../paths"

const GrsProviderSettings = lazy(() => import("./GrsProviderSettings"))
const ComfyProviderSettings = lazy(() => import("./ComfyProviderSettings"))
const QiniuStorageSettings = lazy(() => import("./QiniuStorageSettings"))
const LlmProviderSettings = lazy(() => import("./LlmProviderSettings"))
const VlmProviderSettings = lazy(() => import("./VlmProviderSettings"))
const TtsProviderSettings = lazy(() => import("./TtsProviderSettings"))
const MusicProviderSettings = lazy(() => import("./MusicProviderSettings"))
const CloudVideoProviderSettings = lazy(() => import("./CloudVideoProviderSettings"))
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
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<UserRole>("employee")
  const [renamingAccount, setRenamingAccount] = useState<User>()
  const [resettingUserId, setResettingUserId] = useState<string>()
  const [resetPassword, setResetPassword] = useState("")
  const usersQuery = useQuery({ queryKey: ["admin-users"], queryFn: () => requestJson<User[]>("/api/admin/users") })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] })
  const createMutation = useMutation({
    mutationFn: () => requestJson<User>("/api/admin/users", jsonMutation(csrfToken, { username, display_name: displayName, password, role, email: email.trim() || null })),
    onSuccess: () => { setUsername(""); setDisplayName(""); setEmail(""); setPassword(""); setRole("employee"); refresh() },
  })
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
      <main className="mx-auto grid max-w-[1680px] items-start gap-6 px-5 py-6 pb-10 lg:grid-cols-[340px_minmax(0,1fr)] lg:px-8 2xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <div className="mb-6">
            <span className="grid size-10 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
              <UserPlus size={19} />
            </span>
            <h2 className="mt-4 text-base font-semibold text-[#111827]">分配新账号</h2>
            <p className="mt-1 text-xs text-[#6b7280]">员工首次登录后必须修改初始密码。</p>
          </div>
          <form onSubmit={(event) => { event.preventDefault(); createMutation.mutate() }} className="space-y-4">
            <label className="block text-xs font-medium text-[#4b5563]">
              登录账号
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-lg border border-black/15 bg-white px-3 text-sm text-[#111827] outline-none transition focus:border-[#7047f6] focus:ring-2 focus:ring-[#7047f6]/20"
              />
            </label>
            <label className="block text-xs font-medium text-[#4b5563]">
              员工姓名
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-lg border border-black/15 bg-white px-3 text-sm text-[#111827] outline-none transition focus:border-[#7047f6] focus:ring-2 focus:ring-[#7047f6]/20"
              />
            </label>
            <label className="block text-xs font-medium text-[#4b5563]">
              找回邮箱（可选）
              <input
                type="email"
                autoComplete="off"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="用于忘记密码时接收验证码"
                className="mt-1.5 h-10 w-full rounded-lg border border-black/15 bg-white px-3 text-sm text-[#111827] outline-none transition focus:border-[#7047f6] focus:ring-2 focus:ring-[#7047f6]/20"
              />
            </label>
            <PasswordField id="create-user-password" label="初始密码" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" minLength={PASSWORD_MIN_LENGTH} compact light />
            <label className="block text-xs font-medium text-[#4b5563]">
              角色
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as UserRole)}
                className="mt-1.5 h-10 w-full rounded-lg border border-black/15 bg-white px-3 text-sm text-[#111827] outline-none transition focus:border-[#7047f6] focus:ring-2 focus:ring-[#7047f6]/20"
              >
                <option value="employee">员工</option>
                {user.role === "super_admin" ? (
                  <>
                    <option value="admin">管理员</option>
                    <option value="super_admin">超级管理员</option>
                  </>
                ) : null}
              </select>
            </label>
            {createMutation.isError ? <p className="text-xs text-red-600">{createMutation.error.message}</p> : null}
            <button
              disabled={createMutation.isPending || !username || !displayName || password.length < PASSWORD_MIN_LENGTH}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-[#7047f6] text-sm font-medium text-white transition hover:bg-[#7c58f8] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {createMutation.isPending ? <LoaderCircle className="animate-spin" size={16} /> : <UserPlus size={16} />}
              创建账号
            </button>
          </form>
        </section>

        <section className="min-w-0 rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-end justify-between">
            <div>
              <h2 className="text-base font-semibold text-[#111827]">员工账号</h2>
              <p className="mt-1 text-xs text-[#6b7280]">共 {usersQuery.data?.length ?? 0} 个账号</p>
            </div>
            <button
              type="button"
              onClick={refresh}
              className="h-8 rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#4b5563] hover:bg-[#f3f4f6]"
            >
              刷新状态
            </button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-black/[0.06]">
            <table className="w-full min-w-[940px] table-fixed text-left text-sm">
              <colgroup>
                <col />
                <col className="w-[130px]" />
                <col className="w-[150px]" />
                <col className="w-[180px]" />
                <col className="w-[340px]" />
              </colgroup>
              <thead className="border-b border-black/[0.06] bg-[#f9fafb] text-xs font-medium text-[#6b7280]">
                <tr>
                  <th className="whitespace-nowrap px-4 py-3">员工</th>
                  <th className="whitespace-nowrap px-4 py-3">角色</th>
                  <th className="whitespace-nowrap px-4 py-3">状态</th>
                  <th className="whitespace-nowrap px-4 py-3">最近登录</th>
                  <th className="whitespace-nowrap px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.06]">
                {(usersQuery.data ?? []).map((account) => (
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
                      <select
                        disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee")}
                        value={account.role}
                        onChange={(event) => updateMutation.mutate({ id: account.id, body: { role: event.target.value as UserRole } })}
                        className="h-8 rounded-md border border-black/15 bg-white px-2 text-xs text-[#111827] disabled:opacity-50"
                      >
                        <option value="employee">员工</option>
                        {user.role === "super_admin" ? (
                          <>
                            <option value="admin">管理员</option>
                            <option value="super_admin">超级管理员</option>
                          </>
                        ) : null}
                      </select>
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
                        <button
                          type="button"
                          onClick={() => setRenamingAccount(account)}
                          className="h-8 whitespace-nowrap rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#4b5563] hover:bg-[#f3f4f6]"
                        >
                          编辑资料
                        </button>
                        <button
                          type="button"
                          onClick={() => { setResettingUserId(account.id); setResetPassword("") }}
                          className="h-8 whitespace-nowrap rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#7047f6] hover:bg-[#7047f6]/10"
                        >
                          重置密码
                        </button>
                        {account.login_blocked ? (
                          <button
                            type="button"
                            disabled={unlockMutation.isPending}
                            onClick={() => unlockMutation.mutate(account.id)}
                            className="h-8 whitespace-nowrap rounded-md border border-amber-500/30 bg-amber-50 px-2.5 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-40"
                          >
                            解除登录限制
                          </button>
                        ) : null}
                        <button
                          type="button"
                          disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee")}
                          onClick={() => updateMutation.mutate({ id: account.id, body: { is_active: !account.is_active } })}
                          className="h-8 whitespace-nowrap rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#4b5563] hover:bg-[#f3f4f6] disabled:opacity-40"
                        >
                          {account.is_active ? "停用" : "启用"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {usersQuery.isLoading ? <p className="py-12 text-center text-sm text-[#6b7280]">正在读取账号</p> : null}
          </div>
          {resettingUserId ? (
            <form onSubmit={(event) => { event.preventDefault(); resetMutation.mutate(resettingUserId) }} className="mt-5 flex flex-col gap-3 border-t border-black/[0.06] pt-5 sm:flex-row sm:items-end">
              <PasswordField id="reset-user-password" label="新的初始密码" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} autoComplete="new-password" minLength={PASSWORD_MIN_LENGTH} autoFocus compact light containerClassName="min-w-0 flex-1" />
              <button disabled={resetPassword.length < PASSWORD_MIN_LENGTH || resetMutation.isPending} className="h-10 rounded-lg bg-[#7047f6] px-4 text-sm font-medium text-white hover:bg-[#7c58f8] disabled:opacity-40">
                确认重置
              </button>
              <button type="button" onClick={() => setResettingUserId(undefined)} className="h-10 rounded-lg border border-black/10 bg-white px-4 text-sm text-[#4b5563] hover:bg-[#f3f4f6]">
                取消
              </button>
            </form>
          ) : null}
          {(updateMutation.isError || resetMutation.isError || unlockMutation.isError) ? <p className="mt-4 text-sm text-red-600">{updateMutation.error?.message ?? resetMutation.error?.message ?? unlockMutation.error?.message}</p> : null}
        </section>
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
        {tab === "providers" ? (
          <>
            <ComfyProviderSettings csrfToken={csrfToken} />
            <GrsProviderSettings csrfToken={csrfToken} />
            <MusicProviderSettings csrfToken={csrfToken} />
            <CloudVideoProviderSettings csrfToken={csrfToken} />
          </>
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
