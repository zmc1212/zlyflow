import { useMutation } from "@tanstack/react-query"
import { Alert, Button, Checkbox, Form, Input, Modal, Popconfirm, message } from "antd"
import { ArrowLeft, ArrowRight, KeyRound, LockKeyhole, Mail, ShieldCheck, Sparkles, UserRound, X } from "lucide-react"
import { useEffect, useState } from "react"
import type { AuthStatus } from "../api"
import { ApiRequestError, requestJson } from "../api"
import type { RememberedLogin } from "./remembered-login"
import { clearRememberedLogin, loadRememberedLogin, saveRememberedLogin } from "./remembered-login"
import "./login-modal.css"

type RecoverStep = "email" | "code"
type LoginFormValues = { username: string; password: string; remember: boolean }

function ForgotPasswordForm({ onAuthenticated, onBack }: {
  onAuthenticated: (auth: AuthStatus) => void
  onBack: () => void
}) {
  const [step, setStep] = useState<RecoverStep>("email")
  const [email, setEmail] = useState("")
  const [maskedEmail, setMaskedEmail] = useState("")
  const [code, setCode] = useState("")
  const [newPassword, setNewPassword] = useState("")

  const challenge = useMutation({
    mutationFn: () => requestJson<{ sent: boolean; masked_email: string | null; expires_in_minutes: number }>(
      "/api/auth/password/email-challenge",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim() }) },
    ),
    onSuccess: (data) => {
      setMaskedEmail(data.masked_email || email.trim())
      setStep("code")
    },
  })
  const reset = useMutation({
    mutationFn: () => requestJson<AuthStatus>("/api/auth/password/email-reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim(), code: code.trim(), new_password: newPassword }),
    }),
    onSuccess: (auth) => {
      clearRememberedLogin()
      onAuthenticated(auth)
    },
  })
  const pending = challenge.isPending || reset.isPending
  const error = challenge.error ?? reset.error

  return <section className="studio-login-form-panel">
    <div className="studio-login-brand"><Sparkles size={20} /><span>ZLY AI Studio</span></div>
    <h1 id="studio-recover-title">重置密码</h1>
    <p className="studio-login-description">
      {step === "email" ? "输入账号绑定的邮箱，我们会发送 6 位验证码。" : "输入邮件中的验证码，并设置新密码。"}
    </p>
    <Form layout="vertical" requiredMark={false} onFinish={() => { step === "email" ? challenge.mutate() : reset.mutate() }}>
      {step === "email" ? (
        <Form.Item name="recover-email" label="找回邮箱" rules={[{ required: true, message: "请输入找回邮箱" }]}>
          <Input
            type="email"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="请输入账号绑定的邮箱"
            prefix={<Mail size={16} />}
            disabled={pending}
          />
        </Form.Item>
      ) : (
        <>
          <div className="studio-login-recover-hint">
            <Mail size={14} />
            <span>验证码已发送至 <strong>{maskedEmail}</strong>，15 分钟内有效。</span>
          </div>
          <Form.Item name="recover-code" label="验证码" rules={[{ required: true, message: "请输入 6 位验证码" }]}>
            <Input
              autoComplete="one-time-code"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              placeholder="6 位数字验证码"
              prefix={<KeyRound size={16} />}
              disabled={pending}
            />
          </Form.Item>
          <Form.Item name="recover-new-password" label="新密码" rules={[{ required: true, min: 6, message: "新密码至少 6 位" }]}>
            <Input.Password
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="设置一个新密码（至少 6 位）"
              prefix={<LockKeyhole size={16} />}
              disabled={pending}
            />
          </Form.Item>
        </>
      )}
      {error && <Alert type="error" showIcon role="alert" title={error.message} className="studio-login-error" />}
      <Button type="primary" htmlType="submit" loading={pending} className="studio-login-submit" block>
        {step === "email" ? "发送验证码" : "重置并登录"} {!pending && <ArrowRight size={17} />}
      </Button>
    </Form>
    <div className="studio-login-recover-actions">
      {step === "code" ? (
        <Button type="link" size="small" disabled={pending} onClick={() => challenge.mutate()}>重新发送验证码</Button>
      ) : <span />}
      <Button type="link" size="small" disabled={pending} onClick={onBack} icon={<ArrowLeft size={14} />}>返回登录</Button>
    </div>
    <p className="studio-login-browse-note">忘记邮箱或未绑定邮箱时，请联系管理员重置密码</p>
  </section>
}

export default function LoginModal({ open, onClose, onAuthenticated }: {
  open: boolean
  onClose: () => void
  onAuthenticated: (auth: AuthStatus) => void
}) {
  const [mode, setMode] = useState<"login" | "recover">("login")
  const [form] = Form.useForm<LoginFormValues>()
  const [remembered, setRemembered] = useState<RememberedLogin | null>(null)
  const rememberOn = Form.useWatch("remember", form) ?? false

  const login = useMutation({
    mutationFn: async (values: LoginFormValues) => {
      const auth = await requestJson<AuthStatus>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: values.username.trim(), password: values.password }),
      })
      if (values.remember) {
        if (!await saveRememberedLogin({ username: values.username, password: values.password })) {
          message.warning("此浏览器无法保存账号密码，下次登录仍需手动输入")
        }
      } else {
        clearRememberedLogin()
      }
      return auth
    },
    onSuccess: onAuthenticated,
    onError: (error, values) => {
      // 密码被管理员或自助重置改过后，回填的旧凭据会一直登录失败：识别出来就清掉。
      if (error instanceof ApiRequestError && error.status === 401 && remembered
        && values.username.trim() === remembered.username && values.password === remembered.password) {
        clearRememberedLogin()
        setRemembered(null)
        form.setFieldsValue({ password: "" })
      }
    },
  })

  const forgetRemembered = () => {
    clearRememberedLogin()
    setRemembered(null)
    form.setFieldsValue({ password: "", remember: false })
    message.success("已清除此浏览器保存的账号密码")
  }

  useEffect(() => {
    login.reset()
    setMode("login")
    if (!open) {
      setRemembered(null)
      return
    }
    let active = true
    void loadRememberedLogin().then((value) => { if (active) setRemembered(value) })
    return () => { active = false }
  }, [open, form])

  // 凭据异步解密加载，initialValues 只在表单首次挂载时回放一次，加载完成后必须显式回填。
  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      username: remembered?.username ?? "",
      password: remembered?.password ?? "",
      remember: Boolean(remembered),
    })
  }, [open, remembered, form])

  return <Modal
    open={open}
    onCancel={() => { if (!login.isPending) onClose() }}
    footer={null}
    title={null}
    width={816}
    centered
    keyboard={!login.isPending}
    mask={{ closable: !login.isPending }}
    closable={!login.isPending}
    closeIcon={<X size={18} aria-label="关闭登录窗口" />}
    classNames={{ root: "studio-login-root", container: "studio-login-container" }}
    className="studio-login-modal"
    aria-labelledby={mode === "recover" ? "studio-recover-title" : "studio-login-title"}
    destroyOnHidden
  >
    <div className="studio-login-layout">
      <section className="studio-login-art" aria-label="ZLY AI Studio 影像创作">
        <img src="/auth/cinematic-shore.webp" alt="" />
        <div className="studio-login-art-copy">
          <h2>让灵感，<br />成为下一幕。</h2>
          <p>从一张图，到一个完整的故事。</p>
          <span className="studio-login-art-mark" aria-hidden="true" />
        </div>
      </section>
      {/* 登录表单保持挂载：卸载重挂会被 StrictMode 双调用清掉 store，记住的回填值随之丢失。 */}
      <section className="studio-login-form-panel" style={mode === "login" ? undefined : { display: "none" }}>
        <div className="studio-login-brand"><Sparkles size={20} /><span>ZLY AI Studio</span></div>
        <h1 id="studio-login-title">登录，继续创作</h1>
        <p className="studio-login-description">登录后即可生成并保存你的作品</p>
        <Form<LoginFormValues>
          form={form}
          autoComplete="off"
          layout="vertical"
          requiredMark={false}
          clearOnDestroy
          initialValues={{ username: remembered?.username ?? "", password: remembered?.password ?? "", remember: Boolean(remembered) }}
          onFinish={(values) => login.mutate(values)}
        >
          <Form.Item name="username" label="账号或邮箱" rules={[{ required: true, whitespace: true, message: "请输入账号或邮箱" }]}>
            <Input autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="请输入账号名或绑定邮箱" prefix={<UserRound size={16} />} disabled={login.isPending} />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password autoComplete="new-password" placeholder="请输入密码" prefix={<LockKeyhole size={16} />} disabled={login.isPending} />
          </Form.Item>
          <div className="studio-login-options">
            <Form.Item name="remember" valuePropName="checked" noStyle>
              <Checkbox disabled={login.isPending}>记住账号密码</Checkbox>
            </Form.Item>
            <div className="studio-login-options-actions">
              {remembered && (
                <Popconfirm
                  title="清除已保存的账号密码？"
                  description="清除后下次登录需要重新输入。"
                  okText="清除"
                  cancelText="保留"
                  onConfirm={forgetRemembered}
                >
                  <Button type="link" size="small" disabled={login.isPending}>清除已保存</Button>
                </Popconfirm>
              )}
              <Button type="link" size="small" disabled={login.isPending} onClick={() => setMode("recover")} icon={<KeyRound size={14} />}>忘记密码</Button>
            </div>
          </div>
          {login.isError && <Alert type="error" showIcon role="alert" title={login.error.message} className="studio-login-error" />}
          <Button type="primary" htmlType="submit" loading={login.isPending} className="studio-login-submit" block>
            登录并继续 {!login.isPending && <ArrowRight size={17} />}
          </Button>
        </Form>
        <p className="studio-login-account-note">
          {rememberOn
            ? <><ShieldCheck size={13} />只加密保存在此浏览器，公用设备请勿勾选</>
            : <><LockKeyhole size={13} />账号名或绑定邮箱均可登录</>}
        </p>
        <p className="studio-login-browse-note">关闭窗口可继续浏览</p>
      </section>
      {mode === "recover" && <ForgotPasswordForm onAuthenticated={onAuthenticated} onBack={() => setMode("login")} />}
    </div>
  </Modal>
}
