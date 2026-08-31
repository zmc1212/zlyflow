import { useMutation } from "@tanstack/react-query"
import { Eye, EyeOff, KeyRound, LoaderCircle, LogOut, ShieldCheck, Sparkles } from "lucide-react"
import { ChangeEvent, FormEvent, useState } from "react"
import { AuthStatus, jsonMutation, requestJson } from "../api"
import ThemeToggle from "../components/ThemeToggle"

export const PASSWORD_MIN_LENGTH = 6

export function CenteredStatus({ label, detail }: { label: string; detail?: string }) {
  return <main className="studio-auth-screen relative grid min-h-screen place-items-center px-6">
    <ThemeToggle className="studio-auth-theme-toggle" />
    <div className="text-center">
      <LoaderCircle className="studio-auth-accent mx-auto mb-4 animate-spin" size={24} />
      <p className="text-sm font-medium">{label}</p>
      {detail ? <p className="studio-auth-muted mt-2 max-w-md text-xs leading-5">{detail}</p> : null}
    </div>
  </main>
}

export function PasswordField({
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
    <label htmlFor={id} className={`studio-field-label block ${light ? "text-xs font-medium" : compact ? "text-xs" : "text-sm"}`}>{label}</label>
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
        className={`studio-plain-input ${compact || light ? "h-10 text-sm" : "h-11"} w-full rounded-lg border px-3 pr-12 outline-none transition`}
      />
      <button
        type="button"
        onClick={() => setVisible((current) => !current)}
        aria-label={toggleLabel}
        aria-pressed={visible}
        title={toggleLabel}
        className="studio-password-visibility absolute inset-y-1 right-1 grid aspect-square place-items-center rounded-md transition focus-visible:outline-none focus-visible:ring-2"
      >
        {visible ? <EyeOff size={17} /> : <Eye size={17} />}
      </button>
    </div>
  </div>
}

export function CredentialScreen({ setup = false, onAuthenticated }: { setup?: boolean; onAuthenticated: (auth: AuthStatus) => void }) {
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

  return <main className="studio-auth-screen relative grid min-h-screen lg:grid-cols-[minmax(320px,0.82fr)_minmax(480px,1.18fr)]">
    <ThemeToggle className="studio-auth-theme-toggle" />
    <section className="studio-auth-brand-panel flex min-h-[280px] flex-col justify-between border-b p-7 lg:min-h-screen lg:border-b-0 lg:border-r lg:p-12">
      <div className="flex items-center gap-3">
        <span className="studio-auth-brand-mark grid size-9 place-items-center rounded-lg border"><Sparkles size={18} /></span>
        <span className="text-sm font-semibold">ZLY AI Studio</span>
      </div>
      <div className="max-w-md py-12">
        <p className="studio-auth-accent text-sm">ZLY AI Studio｜创作工作台</p>
        <h1 className="mt-3 text-3xl font-semibold leading-tight sm:text-4xl">图片与视频的一站式创作空间</h1>
        <p className="studio-auth-muted mt-4 max-w-[46ch] text-sm leading-6">任务只对账号本人可见，GRS 图片与本地 ComfyUI 视频结果统一交付到员工授权目录。</p>
      </div>
      <p className="studio-auth-subtle text-xs">图片使用受管 GRS，视频使用工作站本机 ComfyUI</p>
    </section>
    <section className="flex items-center justify-center px-6 py-12">
      <form onSubmit={submit} className="w-full max-w-sm">
        <div className="mb-8">
          <span className="studio-auth-icon grid size-11 place-items-center rounded-xl"><ShieldCheck size={21} /></span>
          <h2 className="mt-5 text-2xl font-semibold">{setup ? "初始化超级管理员" : "登录工作台"}</h2>
          <p className="studio-auth-muted mt-2 text-sm">{setup ? "首次初始化仅允许在工作站本机完成。" : "使用管理员分配的员工账号。"}</p>
        </div>
        <label className="studio-field-label block text-sm">账号<input autoFocus value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" className="studio-plain-input mt-2 h-11 w-full rounded-lg border px-3 outline-none transition" /></label>
        {setup ? <label className="studio-field-label mt-5 block text-sm">管理员姓名<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" className="studio-plain-input mt-2 h-11 w-full rounded-lg border px-3 outline-none transition" /></label> : null}
        <PasswordField id="credential-password" label="密码" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={setup ? "new-password" : "current-password"} minLength={setup ? PASSWORD_MIN_LENGTH : 1} describedBy={setup ? "setup-password-hint" : undefined} containerClassName="mt-5" />
        {setup ? <p id="setup-password-hint" className={`mt-2 text-xs ${password && password.length < PASSWORD_MIN_LENGTH ? "studio-auth-warning-text" : "studio-auth-subtle"}`}>密码至少需要 {PASSWORD_MIN_LENGTH} 个字符</p> : null}
        {mutation.isError ? <p className="studio-auth-error mt-4 rounded-lg px-3 py-2.5 text-sm">{mutation.error.message}</p> : null}
        <button disabled={mutation.isPending || !username.trim() || !password || (setup && (!displayName.trim() || password.length < PASSWORD_MIN_LENGTH))} className="studio-primary-button mt-7 flex h-11 w-full items-center justify-center gap-2 rounded-lg text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-45">
          {mutation.isPending ? <LoaderCircle className="animate-spin" size={17} /> : <KeyRound size={17} />}{setup ? "创建管理员并进入" : "登录"}
        </button>
      </form>
    </section>
  </main>
}

export function PasswordChangeScreen({
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
  return <main className="studio-auth-screen relative grid min-h-screen place-items-center px-6">
    <ThemeToggle className="studio-auth-theme-toggle" />
    <form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }} className="w-full max-w-sm">
      <span className="studio-auth-warning-icon grid size-11 place-items-center rounded-xl"><KeyRound size={21} /></span>
      <h1 className="mt-5 text-2xl font-semibold">设置你的新密码</h1>
      <p className="studio-auth-muted mt-2 text-sm leading-6">管理员分配的是初始密码，修改后才能创建任务。</p>
      <PasswordField id="current-password" label="当前密码" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" containerClassName="mt-7" />
      <PasswordField id="new-password" label="新密码" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={PASSWORD_MIN_LENGTH} containerClassName="mt-5" />
      {mutation.isError ? <p className="studio-auth-error mt-4 rounded-lg px-3 py-2.5 text-sm">{mutation.error.message}</p> : null}
      <button disabled={mutation.isPending || !currentPassword || newPassword.length < PASSWORD_MIN_LENGTH} className="studio-primary-button mt-7 flex h-11 w-full items-center justify-center gap-2 rounded-lg text-sm font-medium disabled:opacity-45">{mutation.isPending ? <LoaderCircle className="animate-spin" size={17} /> : <KeyRound size={17} />}确认修改</button>
      <button type="button" disabled={logoutPending} onClick={onLogout} className="studio-auth-secondary mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-lg text-sm disabled:opacity-40">{logoutPending ? <LoaderCircle className="animate-spin" size={16} /> : <LogOut size={16} />}退出登录</button>
    </form>
  </main>
}
