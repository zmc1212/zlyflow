import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Avatar, Button, Input, Modal, Upload } from "antd"
import { Upload as UploadIcon } from "lucide-react"
import { useMemo, useState } from "react"
import { AuthStatus, jsonMutation, requestJson, User } from "../api"
import { PasswordField } from "../auth/AuthScreens"

const MAX_AVATAR_BYTES = 5 * 1024 * 1024

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
  const [avatarValidationError, setAvatarValidationError] = useState<string | null>(null)
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

  const avatarUpload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData()
      body.append("file", file)
      return requestJson<AuthStatus>("/api/auth/avatar", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        body,
      })
    },
    onSuccess: (result) => {
      queryClient.setQueryData(["auth"], result)
      if (result.user) onUpdated?.(result.user)
    },
  })
  const uploading = avatarUpload.isPending
  const avatarError = avatarValidationError ?? avatarUpload.error?.message

  const submit = () => {
    if (!canSubmit || mutation.isPending || uploading) return
    mutation.mutate()
  }

  return <Modal
    open
    title={self ? "编辑账号资料" : `编辑「${target.display_name}」的资料`}
    okText="保存"
    cancelText="取消"
    confirmLoading={mutation.isPending}
    okButtonProps={{ disabled: !canSubmit || uploading }}
    cancelButtonProps={{ disabled: uploading }}
    closable={!uploading}
    keyboard={!uploading}
    onOk={submit}
    onCancel={() => { if (!uploading) onClose() }}
    destroyOnHidden
    width={420}
  >
    {self ? <div className="mb-5 flex items-center gap-3 border-b pb-4">
      <Avatar size={52} className="shrink-0 !bg-[var(--studio-primary-soft)] !text-[var(--studio-accent-text)]" src={target.avatar_url || undefined}>
        {Array.from(target.display_name || target.username)[0]}
      </Avatar>
      <div className="min-w-0">
        <Upload
          accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
          disabled={uploading || mutation.isPending}
          showUploadList={false}
          beforeUpload={(file) => {
            avatarUpload.reset()
            setAvatarValidationError(null)
            if (file.size > MAX_AVATAR_BYTES) setAvatarValidationError("头像文件不能超过 5 MB")
            else avatarUpload.mutate(file)
            return Upload.LIST_IGNORE
          }}
        >
          <Button size="small" icon={<UploadIcon size={14} />} loading={uploading}>{target.avatar_url ? "更换头像" : "上传头像"}</Button>
        </Upload>
        {avatarError ? <p className="mb-0 mt-1 text-xs text-[var(--studio-danger)]" role="alert">{avatarError}</p> : (
          <p className="mb-0 mt-1 text-xs text-[var(--studio-text-muted)]" role="status">
            {avatarUpload.isSuccess ? "头像已更新" : "支持 JPG、PNG、WebP，最大 5 MB，上传后立即保存。"}
          </p>
        )}
      </div>
    </div> : null}
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
    {mutation.isError ? <p className="mt-2 text-sm text-[var(--studio-danger)]">{mutation.error.message}</p> : null}
  </Modal>
}
