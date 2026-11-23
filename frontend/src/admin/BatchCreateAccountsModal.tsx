import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, InputNumber, Modal, Table, TreeSelect, message } from "antd"
import { Copy, Download } from "lucide-react"
import { useMemo, useState } from "react"
import { apiErrorMessage, jsonMutation, requestJson } from "../api"
import { PASSWORD_MIN_LENGTH } from "../auth/AuthScreens"
import type { Enterprise } from "../credits/credits"
import { buildEnterpriseSelectTree, ENTERPRISE_SELECT_POPUP_CLASS } from "./enterprise-tree"

type BatchCreatedUser = {
  id: string
  username: string
  display_name: string
  enterprise_id?: string | null
}

type BatchCreateResult = {
  enterprise_id: string
  count: number
  first_username: string
  last_username: string
  users: BatchCreatedUser[]
}

/**
 * 企业批量开号：选择企业、账号前缀与数量，统一初始密码创建员工账号。
 * 创建成功后明文密码只在当前弹窗展示一次，支持复制与 CSV 下载。
 */
export default function BatchCreateAccountsModal({
  csrfToken,
  enterprises,
  defaultEnterpriseId,
  onClose,
}: {
  csrfToken: string
  enterprises: Enterprise[]
  defaultEnterpriseId?: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [enterpriseId, setEnterpriseId] = useState<string | undefined>(defaultEnterpriseId)
  const [usernamePrefix, setUsernamePrefix] = useState("")
  const [startIndex, setStartIndex] = useState(1)
  const [count, setCount] = useState(100)
  const [displayNamePrefix, setDisplayNamePrefix] = useState("员工")
  const [password, setPassword] = useState("")
  const [result, setResult] = useState<BatchCreateResult | null>(null)

  const enterpriseTree = useMemo(() => buildEnterpriseSelectTree(enterprises), [enterprises])
  const selectedEnterprise = useMemo(
    () => enterprises.find((enterprise) => enterprise.id === enterpriseId),
    [enterprises, enterpriseId],
  )
  const prefixValid = /^[A-Za-z0-9._-]+$/.test(usernamePrefix.trim())
  const countValid = count >= 1 && count <= 200
  const startValid = startIndex >= 1
  const enterpriseActive = selectedEnterprise?.status === "active"
  const canSubmit = Boolean(enterpriseId) && enterpriseActive && prefixValid && countValid
    && startValid && Boolean(displayNamePrefix.trim()) && password.length >= PASSWORD_MIN_LENGTH

  const width = countValid && startValid ? Math.max(3, String(startIndex + count - 1).length) : 3
  const firstUsername = prefixValid && startValid
    ? `${usernamePrefix.trim().toLowerCase()}${String(startIndex).padStart(width, "0")}`
    : ""
  const lastUsername = prefixValid && countValid && startValid
    ? `${usernamePrefix.trim().toLowerCase()}${String(startIndex + count - 1).padStart(width, "0")}`
    : ""

  const createMutation = useMutation({
    mutationFn: () => requestJson<BatchCreateResult>("/api/admin/users/batch", jsonMutation(csrfToken, {
      enterprise_id: enterpriseId,
      username_prefix: usernamePrefix.trim().toLowerCase(),
      start_index: startIndex,
      count,
      display_name_prefix: displayNamePrefix.trim(),
      password,
    })),
    onSuccess: (created) => {
      setResult(created)
      message.success(`已创建 ${created.count} 个员工账号`)
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const copyAll = async () => {
    if (!result) return
    const text = result.users.map((entry) => `${entry.username}\t${password}`).join("\n")
    try {
      await navigator.clipboard.writeText(text)
      message.success("已复制账号与初始密码")
    } catch {
      message.error("复制失败，请手动选择文本或下载 CSV")
    }
  }

  const downloadCsv = () => {
    if (!result) return
    const enterpriseName = enterprises.find((entry) => entry.id === result.enterprise_id)?.name ?? "企业"
    const escape = (value: string) => `"${value.replace(/"/g, '""')}"`
    const rows = [
      ["登录账号", "姓名", "初始密码", "所属企业"],
      ...result.users.map((entry) => [entry.username, entry.display_name, password, enterpriseName]),
    ]
    const csv = "\ufeff" + rows.map((row) => row.map(escape).join(",")).join("\r\n")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")
    link.href = url
    link.download = `${enterpriseName}-批量账号-${stamp}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const resultColumns = [
    { title: "登录账号", dataIndex: "username", width: 200 },
    { title: "姓名", dataIndex: "display_name" },
  ]

  return (
    <Modal
      open
      title={result ? "批量创建完成" : "批量新增企业账号"}
      width={result ? 720 : 560}
      okText={result ? "完成" : "创建账号"}
      cancelText={result ? undefined : "取消"}
      confirmLoading={createMutation.isPending}
      okButtonProps={{ disabled: result ? false : !canSubmit }}
      cancelButtonProps={{ style: result ? { display: "none" } : undefined }}
      onOk={() => {
        if (result) {
          onClose()
          return
        }
        if (canSubmit && !createMutation.isPending) createMutation.mutate()
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      {result ? (
        <div className="grid gap-4">
          <Alert
            type="warning"
            showIcon
            message="初始密码只在此处展示一次，请立即复制或下载 CSV"
            description={`企业「${enterprises.find((entry) => entry.id === result.enterprise_id)?.name ?? "未知企业"}」· ${result.count} 个账号 · ${result.first_username} ~ ${result.last_username}`}
          />
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-black/[0.08] bg-[#f9fafb] px-3 py-2">
            <span className="text-xs text-[#6b7280]">统一初始密码</span>
            <code className="text-sm font-semibold text-[#111827]">{password}</code>
            <span className="ml-auto text-xs text-[#9ca3af]">成员首次登录后需修改</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={<Copy size={14} />} onClick={() => void copyAll()}>复制账号密码</Button>
            <Button icon={<Download size={14} />} onClick={downloadCsv}>下载 CSV</Button>
          </div>
          <Table<BatchCreatedUser>
            rowKey="id"
            size="small"
            dataSource={result.users}
            columns={resultColumns}
            pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
            scroll={{ y: 320 }}
          />
        </div>
      ) : (
        <div className="grid gap-4">
          <p className="text-xs leading-5 text-[var(--studio-text-muted)]">
            按「账号前缀 + 连续序号」批量创建员工账号，角色固定为员工，首次登录必须修改初始密码。
          </p>
          <label className="grid gap-1.5">
            <span className="text-sm text-[#374151]">所属企业（必填）</span>
            <TreeSelect
              value={enterpriseId}
              onChange={(value) => setEnterpriseId(value)}
              showSearch
              treeNodeFilterProp="title"
              treeDefaultExpandAll
              placeholder="选择要批量开号的企业"
              aria-label="选择所属企业"
              classNames={ENTERPRISE_SELECT_POPUP_CLASS}
              treeData={enterpriseTree}
              notFoundContent="暂无可用企业，请先在企业管理中登记"
            />
            {selectedEnterprise && !enterpriseActive ? (
              <span className="text-xs text-amber-600">该企业已停用，无法批量创建账号</span>
            ) : null}
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5">
              <span className="text-sm text-[#374151]">登录账号前缀</span>
              <Input
                value={usernamePrefix}
                maxLength={40}
                autoComplete="off"
                placeholder="例如 xh"
                onChange={(event) => setUsernamePrefix(event.target.value)}
              />
            </label>
            <label className="grid gap-1.5">
              <span className="text-sm text-[#374151]">姓名前缀</span>
              <Input
                value={displayNamePrefix}
                maxLength={40}
                placeholder="例如 员工"
                onChange={(event) => setDisplayNamePrefix(event.target.value)}
              />
            </label>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5">
              <span className="text-sm text-[#374151]">起始序号</span>
              <InputNumber
                value={startIndex}
                min={1}
                max={999999}
                precision={0}
                className="w-full"
                onChange={(value) => setStartIndex(Number(value ?? 1))}
              />
            </label>
            <label className="grid gap-1.5">
              <span className="text-sm text-[#374151]">创建数量（最多 200）</span>
              <InputNumber
                value={count}
                min={1}
                max={200}
                precision={0}
                className="w-full"
                onChange={(value) => setCount(Number(value ?? 1))}
              />
            </label>
          </div>
          <label className="grid gap-1.5">
            <span className="text-sm text-[#374151]">统一初始密码</span>
            <Input.Password
              value={password}
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              placeholder={`至少 ${PASSWORD_MIN_LENGTH} 位，成员首次登录后需修改`}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="rounded-lg border border-black/[0.08] bg-[#f9fafb] px-3 py-2 text-xs text-[#4b5563]">
            {firstUsername && lastUsername
              ? <>将创建 <code className="font-semibold text-[#111827]">{firstUsername}</code> ~ <code className="font-semibold text-[#111827]">{lastUsername}</code>，共 {count} 个员工账号。</>
              : "填写账号前缀后这里会显示将要创建的账号范围。"}
          </div>
          {createMutation.isError ? (
            <p className="text-sm text-red-600">{apiErrorMessage(null, createMutation.error.message)}</p>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
