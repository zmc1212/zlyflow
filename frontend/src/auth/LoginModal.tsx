import { useMutation } from "@tanstack/react-query"
import { Alert, Button, Form, Input, Modal } from "antd"
import { ArrowRight, LockKeyhole, Sparkles, UserRound, X } from "lucide-react"
import { useEffect } from "react"
import type { AuthStatus } from "../api"
import { requestJson } from "../api"
import "./login-modal.css"

export default function LoginModal({ open, onClose, onAuthenticated }: {
  open: boolean
  onClose: () => void
  onAuthenticated: (auth: AuthStatus) => void
}) {
  const login = useMutation({
    mutationFn: (values: { username: string; password: string }) => requestJson<AuthStatus>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: values.username.trim(), password: values.password }),
    }),
    onSuccess: onAuthenticated,
  })
  useEffect(() => {
    login.reset()
  }, [open])

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
    aria-labelledby="studio-login-title"
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
      <section className="studio-login-form-panel">
        <div className="studio-login-brand"><Sparkles size={20} /><span>ZLY AI Studio</span></div>
        <h1 id="studio-login-title">登录，继续创作</h1>
        <p className="studio-login-description">登录后即可生成并保存你的作品</p>
        <Form<{ username: string; password: string }> key={open ? "open" : "closed"} autoComplete="off" layout="vertical" requiredMark={false} clearOnDestroy onFinish={(values) => login.mutate(values)}>
          <Form.Item name="username" label="账号" rules={[{ required: true, whitespace: true, message: "请输入你的账号" }]}>
            <Input autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="请输入你的账号" prefix={<UserRound size={16} />} disabled={login.isPending} />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password autoComplete="new-password" placeholder="请输入密码" prefix={<LockKeyhole size={16} />} disabled={login.isPending} />
          </Form.Item>
          {login.isError && <Alert type="error" showIcon role="alert" title={login.error.message} className="studio-login-error" />}
          <Button type="primary" htmlType="submit" loading={login.isPending} className="studio-login-submit" block>
            登录并继续 {!login.isPending && <ArrowRight size={17} />}
          </Button>
        </Form>
        <p className="studio-login-account-note"><LockKeyhole size={13} />请使用管理员分配的账号登录</p>
        <p className="studio-login-browse-note">关闭窗口可继续浏览</p>
      </section>
    </div>
  </Modal>
}
