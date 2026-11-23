import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Input, Modal, Select, TreeSelect, message } from "antd"
import { useMemo, useState } from "react"
import { apiErrorMessage, jsonMutation, requestJson, type User, type UserRole } from "../api"
import { PASSWORD_MIN_LENGTH } from "../auth/AuthScreens"
import type { Enterprise } from "../credits/credits"
import { buildEnterpriseSelectTree, ENTERPRISE_SELECT_POPUP_CLASS } from "./enterprise-tree"

/**
 * 账号管理的“新增账号”弹窗：把原先常驻左栏底部的创建表单改为按钮触发的弹层，
 * 避免用户必须滚动页面才能看到创建入口。
 */
export default function CreateAccountModal({
  csrfToken,
  actor,
  enterprises,
  defaultEnterpriseId,
  onClose,
}: {
  csrfToken: string
  actor: User
  enterprises: Enterprise[]
  defaultEnterpriseId?: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [username, setUsername] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<UserRole>("employee")
  const [enterpriseId, setEnterpriseId] = useState<string | undefined>(defaultEnterpriseId)
  const enterpriseTree = useMemo(() => buildEnterpriseSelectTree(enterprises), [enterprises])
  const roleOptions = useMemo(
    () => [
      { value: "employee" as UserRole, label: "员工" },
      ...(actor.role === "super_admin"
        ? [
            { value: "admin" as UserRole, label: "管理员" },
            { value: "super_admin" as UserRole, label: "超级管理员" },
          ]
        : []),
    ],
    [actor.role],
  )
  const canSubmit = Boolean(username.trim()) && Boolean(displayName.trim()) && password.length >= PASSWORD_MIN_LENGTH

  const createMutation = useMutation({
    mutationFn: () => requestJson<User>("/api/admin/users", jsonMutation(csrfToken, {
      username: username.trim(),
      display_name: displayName.trim(),
      password,
      role,
      email: email.trim() || null,
      enterprise_id: enterpriseId || null,
    })),
    onSuccess: (created) => {
      message.success(`已创建账号「${created.display_name}」`)
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
      onClose()
    },
  })

  const submit = () => {
    if (!canSubmit || createMutation.isPending) return
    createMutation.mutate()
  }

  return <Modal
    open
    title="新增账号"
    okText="创建账号"
    cancelText="取消"
    confirmLoading={createMutation.isPending}
    okButtonProps={{ disabled: !canSubmit }}
    onOk={submit}
    onCancel={onClose}
    destroyOnHidden
    width={480}
  >
    <p className="mb-4 text-xs text-[var(--studio-text-muted)]">员工首次登录后必须修改初始密码。</p>
    <div className="grid gap-4">
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">登录账号</span>
        <Input
          value={username}
          autoFocus
          maxLength={64}
          autoComplete="off"
          placeholder="用于登录的唯一账号，例如 zhangsan"
          onChange={(event) => setUsername(event.target.value)}
          onPressEnter={submit}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">员工姓名</span>
        <Input
          value={displayName}
          maxLength={80}
          placeholder="显示在任务与审核记录中的姓名"
          onChange={(event) => setDisplayName(event.target.value)}
          onPressEnter={submit}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">找回邮箱（可选）</span>
        <Input
          type="email"
          autoComplete="off"
          maxLength={255}
          value={email}
          placeholder="用于忘记密码时接收验证码"
          onChange={(event) => setEmail(event.target.value)}
          onPressEnter={submit}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">初始密码</span>
        <Input.Password
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          value={password}
          placeholder={`至少 ${PASSWORD_MIN_LENGTH} 位，员工首次登录后需修改`}
          onChange={(event) => setPassword(event.target.value)}
          onPressEnter={submit}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">角色</span>
        <Select
          value={role}
          onChange={(value) => setRole(value)}
          options={roleOptions}
          aria-label="选择角色"
        />
      </label>
      <label className="grid gap-1.5">
        <span className="text-sm text-[#374151]">所属企业（可选）</span>
        <TreeSelect
          value={enterpriseId}
          onChange={(value) => setEnterpriseId(value)}
          allowClear
          showSearch
          treeNodeFilterProp="title"
          treeDefaultExpandAll
          placeholder="留空表示平台内部账号"
          aria-label="选择所属企业"
          classNames={ENTERPRISE_SELECT_POPUP_CLASS}
          treeData={enterpriseTree}
          notFoundContent="暂无可用企业，请先在企业管理中登记"
        />
      </label>
    </div>
    {createMutation.isError ? (
      <p className="mt-3 text-sm text-red-600">{apiErrorMessage(null, createMutation.error.message)}</p>
    ) : null}
  </Modal>
}
