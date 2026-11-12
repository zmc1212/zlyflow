import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, InputNumber, Select, Switch, message } from "antd"
import { CheckCircle2, KeyRound, Mail } from "lucide-react"
import { useEffect, useState } from "react"
import { jsonMutation, requestJson } from "../api"
import { CopyFieldButton } from "./FieldCopy"

type MailConfig = {
  enabled: boolean
  host: string
  port: number
  security: "ssl" | "starttls" | "none"
  username: string
  from_address: string
  from_name: string
  has_password: boolean
  credential_ready: boolean
  configured: boolean
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
}

const SECURITY_OPTIONS = [
  { value: "ssl", label: "SSL / TLS（隐式加密，通常 465）" },
  { value: "starttls", label: "STARTTLS（先明文再升级，通常 587）" },
  { value: "none", label: "不加密（仅内网测试）" },
]

/** 「邮件服务」页：配置用于「忘记密码」发验证码的 SMTP 发件服务器。 */
export default function MailProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ["mail-provider"],
    queryFn: () => requestJson<MailConfig>("/api/admin/providers/mail"),
  })
  const [enabled, setEnabled] = useState(false)
  const [host, setHost] = useState("")
  const [port, setPort] = useState<number | null>(465)
  const [security, setSecurity] = useState<MailConfig["security"]>("ssl")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [fromAddress, setFromAddress] = useState("")
  const [fromName, setFromName] = useState("")

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setHost(query.data.host)
    setPort(query.data.port)
    setSecurity(query.data.security)
    setUsername(query.data.username)
    setFromAddress(query.data.from_address)
    setFromName(query.data.from_name)
  }, [query.data])

  const body = () => ({
    enabled,
    host: host.trim(),
    port: port ?? 465,
    security,
    username: username.trim(),
    password: password || null,
    from_address: fromAddress.trim(),
    from_name: fromName.trim() || "ZLY AI Studio",
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["mail-provider"] })
  const save = useMutation({
    mutationFn: () => requestJson<MailConfig>("/api/admin/providers/mail", jsonMutation(csrfToken, body(), "PUT")),
    onSuccess: () => {
      setPassword("")
      refresh()
      message.success("邮件服务配置已保存")
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<MailConfig>("/api/admin/providers/mail/test", jsonMutation(csrfToken, body())),
    onSuccess: () => {
      refresh()
      message.success("SMTP 连接成功")
    },
  })
  const error = save.error ?? test.error ?? query.error

  return (
    <main className="studio-admin-panel max-w-[1180px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Mail size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">邮件服务（SMTP）</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            员工在登录页「忘记密码」时，工作台会向账号绑定的邮箱发送一次性验证码。此处置入发件服务器后该功能才可用；测试连接只建立连接并登录，不会真正发送邮件。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。SMTP 登录密码将无法加密保存。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-5 rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用邮件服务</p>
              <p className="mt-1 text-[11px] text-[#6b7280]">关闭后「忘记密码」将提示联系管理员重置。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">SMTP 服务器地址</label>
              <Input
                className="mt-1.5"
                value={host}
                onChange={(event) => setHost(event.target.value)}
                placeholder="smtp.example.com"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">端口</label>
              <InputNumber
                className="mt-1.5 w-full"
                min={1}
                max={65535}
                value={port}
                onChange={(value) => setPort(value)}
                placeholder="465"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">连接加密方式</label>
            <Select
              className="mt-1.5 w-full"
              value={security}
              onChange={(value) => setSecurity(value)}
              options={SECURITY_OPTIONS}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">登录账号</label>
              <Input
                className="mt-1.5"
                autoComplete="off"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="通常与发件邮箱相同；留空表示匿名中继"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">登录密码 / 授权码</label>
              <Input.Password
                className="mt-1.5"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
                suffix={
                  <CopyFieldButton
                    label="SMTP 密码"
                    value={password}
                    csrfToken={csrfToken}
                    provider="mail"
                    field="password"
                  />
                }
                placeholder={query.data?.has_password ? "已保存，留空表示不修改" : "SMTP 授权码，例如 QQ/163 邮箱生成的授权码"}
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">发件人邮箱</label>
              <Input
                className="mt-1.5"
                value={fromAddress}
                onChange={(event) => setFromAddress(event.target.value)}
                placeholder="noreply@example.com"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#4b5563]">发件人名称</label>
              <Input
                className="mt-1.5"
                value={fromName}
                onChange={(event) => setFromName(event.target.value)}
                placeholder="ZLY AI Studio"
              />
            </div>
          </div>
          {error ? <Alert type="error" showIcon message={error.message} /> : null}
          <div className="studio-admin-actions">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>保存配置</Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>测试连接</Button>
          </div>
        </div>

        <aside className="flex flex-col justify-between rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">服务状态</p>
            <p className={`mt-3 text-sm font-semibold ${query.data?.configured ? "text-emerald-600" : "text-amber-600"}`}>
              {query.data?.configured ? "● 已启用" : "● 未启用或未配置完整"}
            </p>
            <dl className="mt-6 space-y-4 text-xs">
              <div>
                <dt className="text-[#6b7280]">服务器</dt>
                <dd className="mt-1 font-medium text-[#111827] break-all">
                  {query.data?.host ? `${query.data.host}:${query.data.port}` : "未配置"}
                </dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">发件人</dt>
                <dd className="mt-1 font-medium text-[#111827] break-all">{query.data?.from_address || "未配置"}</dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">登录密码</dt>
                <dd className="mt-1 font-medium text-[#111827]">{query.data?.has_password ? "已保存（不回显）" : "未保存"}</dd>
              </div>
              <div>
                <dt className="text-[#6b7280]">最近连通性测试</dt>
                <dd className="mt-1 font-medium text-[#111827]">
                  {query.data?.last_test_status
                    ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                    : "尚未测试"}
                </dd>
                {query.data?.last_test_message ? (
                  <dd className="mt-1 break-all text-[11px] text-[#6b7280]">{query.data.last_test_message}</dd>
                ) : null}
              </div>
            </dl>
          </div>
          <div className="mt-6 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.04] p-4 text-xs leading-5 text-[#4b5563]">
            <p className="mt-1.5 text-[11px] leading-4 text-[#6b7280]">
              企业邮箱通常需要单独生成「SMTP 授权码」作为密码。验证码邮件默认 15 分钟内有效。
            </p>
          </div>
        </aside>
      </section>
    </main>
  )
}
