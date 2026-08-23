import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Tabs } from "antd"
import { ArrowLeft, Eye, EyeOff, KeyRound, LoaderCircle, LogOut, ShieldCheck, Sparkles, UserPlus, Users } from "lucide-react"
import { ChangeEvent, FormEvent, lazy, Suspense, useState } from "react"
import { AuthStatus, jsonMutation, requestJson, User, UserRole } from "./api"

const roleLabel: Record<UserRole, string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  employee: "员工",
}

const PASSWORD_MIN_LENGTH = 6
const App = lazy(() => import("./App"))
const GrsProviderSettings = lazy(() => import("./admin/GrsProviderSettings"))
const QiniuStorageSettings = lazy(() => import("./admin/QiniuStorageSettings"))
const LlmProviderSettings = lazy(() => import("./admin/LlmProviderSettings"))


export default function Root() {
  const queryClient = useQueryClient()
  const [view, setView] = useState<"studio" | "admin">("studio")
  const authQuery = useQuery({
    queryKey: ["auth"],
    queryFn: () => requestJson<AuthStatus>("/api/auth/status"),
    retry: false,
  })

  const logoutMutation = useMutation({
    mutationFn: () => requestJson<{ ok: boolean }>("/api/auth/logout", jsonMutation(authQuery.data?.csrf_token ?? "")),
    onSuccess: () => {
      queryClient.clear()
      window.location.assign("/")
    },
  })

  if (authQuery.isLoading) return <CenteredStatus label="正在连接工作台" />
  if (authQuery.isError) return <CenteredStatus label="工作台连接失败" detail={authQuery.error.message} />
  const auth = authQuery.data
  if (!auth) return <CenteredStatus label="工作台未返回登录状态" />
  if (auth.setup_required) return <CredentialScreen setup onAuthenticated={(nextAuth) => queryClient.setQueryData(["auth"], nextAuth)} />
  if (!auth.authenticated || !auth.user || !auth.csrf_token) {
    return <CredentialScreen onAuthenticated={(auth) => queryClient.setQueryData(["auth"], auth)} />
  }
  if (auth.user.must_change_password) {
    return <PasswordChangeScreen
      auth={auth}
      onChanged={(nextAuth) => queryClient.setQueryData(["auth"], nextAuth)}
      onLogout={() => logoutMutation.mutate()}
      logoutPending={logoutMutation.isPending}
    />
  }

  const user = auth.user
  const csrfToken = auth.csrf_token
  if (view === "admin" && user.role !== "employee") {
    return <AdminUsers user={user} csrfToken={csrfToken} onBack={() => setView("studio")} />
  }
  return <Suspense fallback={<CenteredStatus label="正在加载创作工作台" />}><App
    user={user}
    csrfToken={csrfToken}
    onOpenAdmin={user.role === "employee" ? undefined : () => setView("admin")}
    onLogout={() => logoutMutation.mutate()}
    logoutPending={logoutMutation.isPending}
  /></Suspense>
}

function CenteredStatus({ label, detail }: { label: string; detail?: string }) {
  return <main className="grid min-h-screen place-items-center bg-[#15161b] px-6 text-[#f5f5f7]">
    <div className="text-center">
      <LoaderCircle className="mx-auto mb-4 animate-spin text-[#927cff]" size={24} />
      <p className="text-sm font-medium">{label}</p>
      {detail ? <p className="mt-2 max-w-md text-xs leading-5 text-[#a0a0aa]">{detail}</p> : null}
    </div>
  </main>
}

function PasswordField({
  id, label, value, onChange, autoComplete, minLength, describedBy, autoFocus = false,
  compact = false, containerClassName = "", light = false,
}: {
  id: string
  label: string
  value: string
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
  autoComplete?: "current-password" | "new-password"
  minLength?: number
  describedBy?: string
  autoFocus?: boolean
  compact?: boolean
  containerClassName?: string
  light?: boolean
}) {
  const [visible, setVisible] = useState(false)
  const toggleLabel = visible ? "隐藏密码" : "显示密码"

  return <div className={containerClassName}>
    <label htmlFor={id} className={light ? "block text-xs font-medium text-[#4b5563]" : compact ? "block text-xs text-[#bcbcc4]" : "block text-sm text-[#d4d4da]"}>{label}</label>
    <div className={`relative ${compact ? "mt-1.5" : "mt-2"}`}>
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        minLength={minLength}
        aria-describedby={describedBy}
        autoFocus={autoFocus}
        className={light
          ? "h-10 w-full rounded-lg border border-black/15 bg-white px-3 pr-12 text-sm text-[#111827] outline-none transition placeholder:text-[#9ca3af] focus:border-[#7047f6] focus:ring-2 focus:ring-[#7047f6]/20"
          : `${compact ? "h-10 bg-[#212228] text-sm" : "h-11 bg-[#202127] text-white"} w-full rounded-lg border border-white/10 px-3 pr-12 outline-none transition focus:border-[#8d75ff] focus:ring-2 focus:ring-[#7655ff]/20`}
      />
      <button
        type="button"
        onClick={() => setVisible((current) => !current)}
        aria-label={toggleLabel}
        aria-pressed={visible}
        title={toggleLabel}
        className={`absolute inset-y-1 right-1 grid aspect-square place-items-center rounded-md transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#927cff] ${light ? "text-[#6b7280] hover:bg-black/[0.05] hover:text-[#111827]" : "text-[#85858f] hover:bg-white/[0.06] hover:text-[#dedee5]"}`}
      >
        {visible ? <EyeOff size={17} /> : <Eye size={17} />}
      </button>
    </div>
  </div>
}

function CredentialScreen({ setup = false, onAuthenticated }: { setup?: boolean; onAuthenticated: (auth: AuthStatus) => void }) {
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [password, setPassword] = useState("")
  const mutation = useMutation({
    mutationFn: () => requestJson<AuthStatus>(setup ? "/api/auth/setup" : "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(setup ? { username, display_name: displayName, password } : { username, password }),
    }),
    onSuccess: onAuthenticated,
  })
  const submit = (event: FormEvent) => { event.preventDefault(); mutation.mutate() }

  return <main className="grid min-h-screen bg-[#15161b] text-[#f5f5f7] lg:grid-cols-[minmax(320px,0.82fr)_minmax(480px,1.18fr)]">
    <section className="flex min-h-[280px] flex-col justify-between border-b border-white/[0.08] bg-[#101116] p-7 lg:min-h-screen lg:border-b-0 lg:border-r lg:p-12">
      <div className="flex items-center gap-3">
        <span className="grid size-9 place-items-center rounded-lg border border-[#7655ff] text-[#aa98ff]"><Sparkles size={18} /></span>
        <span className="text-sm font-semibold">ZLY AI Studio</span>
      </div>
      <div className="max-w-md py-12">
        <p className="text-sm text-[#9e8cff]">ZLY AI Studio｜创作工作台</p>
        <h1 className="mt-3 text-3xl font-semibold leading-tight sm:text-4xl">图片与视频的一站式创作空间</h1>
        <p className="mt-4 max-w-[46ch] text-sm leading-6 text-[#a9a9b2]">任务只对账号本人可见，GRS 图片与本地 ComfyUI 视频结果统一交付到员工授权目录。</p>
      </div>
      <p className="text-xs text-[#71717a]">图片使用受管 GRS，视频使用工作站本机 ComfyUI</p>
    </section>
    <section className="flex items-center justify-center px-6 py-12">
      <form onSubmit={submit} className="w-full max-w-sm">
        <div className="mb-8">
          <span className="grid size-11 place-items-center rounded-xl bg-[#7655ff]/15 text-[#a996ff]"><ShieldCheck size={21} /></span>
          <h2 className="mt-5 text-2xl font-semibold">{setup ? "初始化超级管理员" : "登录工作台"}</h2>
          <p className="mt-2 text-sm text-[#94949e]">{setup ? "首次初始化仅允许在工作站本机完成。" : "使用管理员分配的员工账号。"}</p>
        </div>
        <label className="block text-sm text-[#d4d4da]">账号<input autoFocus value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" className="mt-2 h-11 w-full rounded-lg border border-white/10 bg-[#202127] px-3 text-white outline-none transition focus:border-[#8d75ff] focus:ring-2 focus:ring-[#7655ff]/20" /></label>
        {setup ? <label className="mt-5 block text-sm text-[#d4d4da]">管理员姓名<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" className="mt-2 h-11 w-full rounded-lg border border-white/10 bg-[#202127] px-3 text-white outline-none transition focus:border-[#8d75ff] focus:ring-2 focus:ring-[#7655ff]/20" /></label> : null}
        <PasswordField id="credential-password" label="密码" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={setup ? "new-password" : "current-password"} minLength={setup ? PASSWORD_MIN_LENGTH : 1} describedBy={setup ? "setup-password-hint" : undefined} containerClassName="mt-5" />
        {setup ? <p id="setup-password-hint" className={`mt-2 text-xs ${password && password.length < PASSWORD_MIN_LENGTH ? "text-amber-300" : "text-[#85858f]"}`}>密码至少需要 {PASSWORD_MIN_LENGTH} 个字符</p> : null}
        {mutation.isError ? <p className="mt-4 rounded-lg bg-red-500/10 px-3 py-2.5 text-sm text-red-200">{mutation.error.message}</p> : null}
        <button disabled={mutation.isPending || !username.trim() || !password || (setup && (!displayName.trim() || password.length < PASSWORD_MIN_LENGTH))} className="mt-7 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#7047f6] text-sm font-medium text-white transition hover:bg-[#7c58f8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a795ff] disabled:cursor-not-allowed disabled:opacity-45">
          {mutation.isPending ? <LoaderCircle className="animate-spin" size={17} /> : <KeyRound size={17} />}{setup ? "创建管理员并进入" : "登录"}
        </button>
      </form>
    </section>
  </main>
}

function PasswordChangeScreen({
  auth, onChanged, onLogout, logoutPending,
}: {
  auth: AuthStatus
  onChanged: (auth: AuthStatus) => void
  onLogout: () => void
  logoutPending: boolean
}) {
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const mutation = useMutation({
    mutationFn: () => requestJson<AuthStatus>("/api/auth/password", jsonMutation(auth.csrf_token ?? "", {
      current_password: currentPassword,
      new_password: newPassword,
    })),
    onSuccess: onChanged,
  })
  return <main className="grid min-h-screen place-items-center bg-[#15161b] px-6 text-[#f5f5f7]">
    <form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }} className="w-full max-w-sm">
      <span className="grid size-11 place-items-center rounded-xl bg-amber-400/10 text-amber-300"><KeyRound size={21} /></span>
      <h1 className="mt-5 text-2xl font-semibold">设置你的新密码</h1>
      <p className="mt-2 text-sm leading-6 text-[#9b9ba5]">管理员分配的是初始密码，修改后才能创建任务。</p>
      <PasswordField id="current-password" label="当前密码" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" containerClassName="mt-7" />
      <PasswordField id="new-password" label="新密码" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={PASSWORD_MIN_LENGTH} containerClassName="mt-5" />
      {mutation.isError ? <p className="mt-4 text-sm text-red-300">{mutation.error.message}</p> : null}
      <button disabled={mutation.isPending || !currentPassword || newPassword.length < PASSWORD_MIN_LENGTH} className="mt-7 flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#7047f6] text-sm font-medium disabled:opacity-45">{mutation.isPending ? <LoaderCircle className="animate-spin" size={17} /> : <KeyRound size={17} />}确认修改</button>
      <button type="button" disabled={logoutPending} onClick={onLogout} className="mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-lg text-sm text-[#aaaab3] hover:bg-white/[0.05] disabled:opacity-40">{logoutPending ? <LoaderCircle className="animate-spin" size={16} /> : <LogOut size={16} />}退出登录</button>
    </form>
  </main>
}

function AdminUsers({ user, csrfToken, onBack }: { user: User; csrfToken: string; onBack: () => void }) {
  const queryClient = useQueryClient()
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<UserRole>("employee")
  const [resettingUserId, setResettingUserId] = useState<string>()
  const [resetPassword, setResetPassword] = useState("")
  const [adminTab, setAdminTab] = useState("accounts")
  const usersQuery = useQuery({ queryKey: ["admin-users"], queryFn: () => requestJson<User[]>("/api/admin/users") })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] })
  const createMutation = useMutation({
    mutationFn: () => requestJson<User>("/api/admin/users", jsonMutation(csrfToken, { username, display_name: displayName, password, role })),
    onSuccess: () => { setUsername(""); setDisplayName(""); setPassword(""); setRole("employee"); refresh() },
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: UserRole; is_active?: boolean } }) => requestJson<User>(`/api/admin/users/${id}`, jsonMutation(csrfToken, body, "PATCH")),
    onSuccess: refresh,
  })
  const resetMutation = useMutation({
    mutationFn: (id: string) => requestJson<User>(`/api/admin/users/${id}/reset-password`, jsonMutation(csrfToken, { password: resetPassword })),
    onSuccess: () => { setResettingUserId(undefined); setResetPassword(""); refresh() },
  })

  return <div className="min-h-screen bg-[#f8f9fa] text-[#1f2937]">
    <header className="flex h-[68px] items-center justify-between border-b border-black/[0.06] bg-white px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button onClick={onBack} title="返回创作台" className="grid size-9 place-items-center rounded-lg text-[#4b5563] transition hover:bg-black/[0.04] hover:text-[#111827]">
          <ArrowLeft size={18} />
        </button>
        <span className="h-6 w-px bg-black/[0.08]" />
        <Users size={18} className="text-[#7047f6]" />
        <h1 className="text-base font-semibold text-[#111827]">管理设置</h1>
      </div>
      <div className="text-right">
        <p className="text-sm font-medium text-[#111827]">{user.display_name}</p>
        <p className="text-[11px] text-[#6b7280]">{roleLabel[user.role]}</p>
      </div>
    </header>
    <div className="mx-auto max-w-[1180px] px-5 pt-4 lg:px-8">
      <Tabs
        activeKey={adminTab}
        onChange={setAdminTab}
        items={[
          { key: "accounts", label: "账号管理" },
          ...(user.role === "super_admin"
            ? [
                { key: "providers", label: "AI 供应商" },
                { key: "llm", label: "LLM 大模型" },
                { key: "storage", label: "媒体存储" },
              ]
            : []),
        ]}
      />
    </div>
    {adminTab === "accounts" ? (
      <main className="mx-auto grid max-w-[1180px] gap-8 px-5 py-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:px-8">
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
          </div>
          <div className="overflow-x-auto rounded-lg border border-black/[0.06]">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-black/[0.06] bg-[#f9fafb] text-xs font-medium text-[#6b7280]">
                <tr>
                  <th className="px-4 py-3">员工</th>
                  <th className="px-4 py-3">角色</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">最近登录</th>
                  <th className="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.06]">
                {(usersQuery.data ?? []).map((account) => (
                  <tr key={account.id} className="transition hover:bg-[#f9fafb]">
                    <td className="px-4 py-3">
                      <p className="font-medium text-[#111827]">{account.display_name}</p>
                      <p className="mt-0.5 text-xs text-[#6b7280]">
                        {account.username}
                        {account.must_change_password ? " · 待修改初始密码" : ""}
                      </p>
                    </td>
                    <td className="px-4 py-3">
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
                      <span className={account.is_active ? "font-medium text-emerald-600" : "text-[#9ca3af]"}>
                        {account.is_active ? "已启用" : "已停用"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-[#6b7280]">
                      {account.last_login_at ? new Date(account.last_login_at).toLocaleString("zh-CN", { hour12: false }) : "尚未登录"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => { setResettingUserId(account.id); setResetPassword("") }}
                          className="h-8 rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#7047f6] hover:bg-[#7047f6]/10"
                        >
                          重置密码
                        </button>
                        <button
                          disabled={account.id === user.id || (user.role === "admin" && account.role !== "employee")}
                          onClick={() => updateMutation.mutate({ id: account.id, body: { is_active: !account.is_active } })}
                          className="h-8 rounded-md border border-black/10 bg-white px-2.5 text-xs font-medium text-[#4b5563] hover:bg-[#f3f4f6] disabled:opacity-40"
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
          {(updateMutation.isError || resetMutation.isError) ? <p className="mt-4 text-sm text-red-600">{updateMutation.error?.message ?? resetMutation.error?.message}</p> : null}
        </section>
      </main>
    ) : (
      <Suspense fallback={<CenteredStatus label="正在加载设置" />}>
        {adminTab === "providers" ? (
          <GrsProviderSettings csrfToken={csrfToken} />
        ) : adminTab === "llm" ? (
          <LlmProviderSettings csrfToken={csrfToken} />
        ) : (
          <QiniuStorageSettings csrfToken={csrfToken} />
        )}
      </Suspense>
    )}
  </div>
}


