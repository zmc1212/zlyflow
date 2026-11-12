import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Input } from "antd"
import { Modal } from "antd"
import { useMemo, useState } from "react"
import { AuthStatus, jsonMutation, requestJson, User } from "../api"
import { PasswordField } from "../auth/AuthScreens"

export default function RenameUserModal({
  target, csrfToken, self = false, onClose, onUpdated,
}: {
  target: User
  csrfToken: string
  self?: boolean
  onClose: () => void
  onUpdated?: (user: User) => void
}) {
  const queryClient = useQueryClient()
  const [displayName, setDisplayName] = useState(target.display_name)
  const [email, setEmail] = useState(target.email ?? "")
  const [currentPassword, setCurrentPassword] = useState("")
  const trimmed = displayName.trim()
  const nextEmail = email.trim()
  const emailChanged = nextEmail.toLowerCase() !== (target.email ?? "").toLowerCase()
  const nameChanged = trimmed !== target.display_name
  const canSubmit = useMemo(() => {
    if (!trimmed || (!nameChanged && !emailChanged)) return false
    if (self && emailChanged && !currentPassword) return false
    return true
  }, [trimmed, nameChanged, emailChanged, self, currentPassword])

  const mutation = useMutation({
    mutationFn: async (): Promise<AuthStatus | User> => self
      ? requestJson<AuthStatus>("/api/auth/profile", jsonMutation(csrfToken, {
          display_name: trimmed,
          email: nextEmail,
          ...(emailChanged ? { current_password: currentPassword } : {}),
        }, "PATCH"))
      : requestJson<User>(`/api/admin/users/${target.id}`, jsonMutation(csrfToken, {
          display_name: trimmed,
          email: nextEmail,
        }, "PATCH")),
    onSuccess: (result) => {
      if ("authenticated" in result) {
        queryClient.setQueryData(["auth"], result)
        onUpdated?.(result.user ?? target)
      } else {
        onUpdated?.(result)
      }
      onClose()
    },
  })

  const submit = () => {
    if (!canSubmit || mutation.isPending) return
    mutation.mutate()
  }

  return <Modal
    open
    title={self ? "编辑账号资料" : `编辑「${target.display_name}」的资料`}
    okText="保存"
    cancelText="取消"
    confirmLoading={mutation.isPending}
    okButtonProps={{ disabled: !canSubmit }}
    onOk={submit}
    onCancel={onClose}
    destroyOnHidden
    width={420}
  >
    <label htmlFor="rename-user-input" className="mb-1.5 block text-sm text-[var(--studio-text-secondary)]">姓名</label>
    <Input
      id="rename-user-input"
      value={displayName}
      maxLength={80}
      autoFocus
      onChange={(event) => setDisplayName(event.target.value)}
      onPressEnter={submit}
    />
    <label htmlFor="rename-user-email" className="mb-1.5 mt-4 block text-sm text-[var(--studio-text-secondary)]">找回邮箱</label>
    <Input
      id="rename-user-email"
      type="email"
      autoComplete="off"
      value={email}
      maxLength={255}
      placeholder="忘记密码时接收验证码，留空表示不绑定"
      onChange={(event) => setEmail(event.target.value)}
      onPressEnter={submit}
    />
    <p className="mt-2 text-xs text-[var(--studio-text-muted)]">登录账号不变；邮箱仅用于忘记密码时接收验证码。</p>
    {self && emailChanged ? (
      <PasswordField
        id="rename-user-current-password"
        label="当前密码"
        value={currentPassword}
        onChange={(event) => setCurrentPassword(event.target.value)}
        autoComplete="current-password"
        compact
        containerClassName="mt-4"
      />
    ) : null}
    {mutation.isError ? <p className="mt-2 text-sm text-red-600">{mutation.error.message}</p> : null}
  </Modal>
}
