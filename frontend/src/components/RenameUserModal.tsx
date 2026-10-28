import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Input, Modal } from "antd"
import { useState } from "react"
import { AuthStatus, jsonMutation, requestJson, User } from "../api"

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
  const trimmed = displayName.trim()
  const mutation = useMutation({
    mutationFn: async (): Promise<AuthStatus | User> => self
      ? requestJson<AuthStatus>("/api/auth/profile", jsonMutation(csrfToken, { display_name: trimmed }, "PATCH"))
      : requestJson<User>(`/api/admin/users/${target.id}`, jsonMutation(csrfToken, { display_name: trimmed }, "PATCH")),
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
    if (!trimmed || trimmed === target.display_name || mutation.isPending) return
    mutation.mutate()
  }

  return <Modal
    open
    title={self ? "修改姓名" : `修改「${target.display_name}」的姓名`}
    okText="保存"
    cancelText="取消"
    confirmLoading={mutation.isPending}
    okButtonProps={{ disabled: !trimmed || trimmed === target.display_name }}
    onOk={submit}
    onCancel={onClose}
    destroyOnHidden
    width={400}
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
    <p className="mt-2 text-xs text-[var(--studio-text-muted)]">登录账号不变，新姓名会立即显示在账号菜单中。</p>
    {mutation.isError ? <p className="mt-2 text-sm text-red-600">{mutation.error.message}</p> : null}
  </Modal>
}
