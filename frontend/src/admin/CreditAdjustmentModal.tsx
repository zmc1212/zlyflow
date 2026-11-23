import { useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Alert, Input, InputNumber, Modal, Segmented, message } from "antd"
import { ApiRequestError, jsonMutation, requestJson } from "../api"
import { formatCredits, MAX_CREDIT_AMOUNT } from "../credits/credits"

export type CreditAdjustmentTarget = {
  id: string
  name: string
  balance: number
  scope: "user" | "enterprise"
}

export function CreditAdjustmentModal({ target, csrfToken, onClose }: {
  target: CreditAdjustmentTarget
  csrfToken: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [operation, setOperation] = useState<"recharge" | "deduct">("recharge")
  const [amount, setAmount] = useState<number | null>(null)
  const [reason, setReason] = useState("")
  const requestRef = useRef<{ delta: number; reason: string; id: string } | null>(null)
  const enterprise = target.scope === "enterprise"
  const mutation = useMutation({
    mutationFn: (change: { delta: number; reason: string; request_id: string }) => {
      const path = enterprise ? `/api/admin/enterprises/${encodeURIComponent(target.id)}/credits` : "/api/admin/credits/adjust"
      const body = enterprise ? change : { ...change, user_id: target.id }
      return requestJson<{ balance: number }>(path, jsonMutation(csrfToken, body))
    },
    onSuccess: (wallet) => {
      message.success(`积分已更新，当前余额 ${formatCredits(wallet.balance)}`)
      for (const key of ["admin-credit-accounts", "admin-credit-transactions", "credits-me", "credits-transactions", "credits-estimate"]) {
        void queryClient.invalidateQueries({ queryKey: [key] })
      }
      if (enterprise) {
        void queryClient.invalidateQueries({ queryKey: ["admin-enterprises"] })
        void queryClient.invalidateQueries({ queryKey: ["admin-enterprise-detail", target.id] })
        void queryClient.invalidateQueries({ queryKey: ["admin-enterprise-transactions", target.id] })
      }
      onClose()
    },
    onError: (error) => {
      if (error instanceof ApiRequestError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: ["admin-credit-accounts"] })
      }
    },
  })

  const delta = (amount ?? 0) * (operation === "recharge" ? 1 : -1)
  const nextBalance = target.balance + delta
  const exceedsBalance = operation === "deduct" && delta !== 0 && nextBalance < 0
  const exceedsLimit = nextBalance > MAX_CREDIT_AMOUNT
  const canSubmit = Number.isInteger(delta) && delta !== 0 && Math.abs(delta) <= MAX_CREDIT_AMOUNT
    && !exceedsBalance && !exceedsLimit && reason.trim().length > 0

  const submit = () => {
    if (!canSubmit || mutation.isPending) return
    const trimmedReason = reason.trim()
    let request = requestRef.current
    if (!request || request.delta !== delta || request.reason !== trimmedReason) {
      // getRandomValues is also available when the workbench is opened over LAN HTTP.
      const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("")
      request = { delta, reason: trimmedReason, id }
      requestRef.current = request
    }
    mutation.mutate({ delta, reason: trimmedReason, request_id: request.id })
  }

  return (
    <Modal
      open
      title={enterprise ? "调整企业积分" : "调整个人积分"}
      onCancel={onClose}
      onOk={submit}
      okText={operation === "recharge" ? "确认充值" : "确认扣减"}
      cancelText="取消"
      okButtonProps={{ disabled: !canSubmit, danger: operation === "deduct" }}
      cancelButtonProps={{ disabled: mutation.isPending }}
      closable={!mutation.isPending}
      keyboard={!mutation.isPending}
      mask={{ closable: !mutation.isPending }}
      confirmLoading={mutation.isPending}
    >
      <div className="grid gap-4 pt-2">
        <div className="rounded-xl border border-[color:var(--studio-border)] bg-[var(--studio-surface-raised)] px-4 py-3">
          <p className="text-xs text-[color:var(--studio-text-muted)]">{enterprise ? "企业钱包 · 成员共享" : "个人钱包"}</p>
          <p className="mt-1 break-words font-medium text-[color:var(--studio-text)]">{target.name}</p>
          <p className="mt-2 text-sm text-[color:var(--studio-text-secondary)]">
            当前 {formatCredits(target.balance)} 积分
            {delta && !exceedsBalance && !exceedsLimit ? ` → 调整后 ${formatCredits(nextBalance)} 积分` : ""}
          </p>
        </div>
        <Segmented
          block
          aria-label="调整方式"
          disabled={mutation.isPending}
          value={operation}
          onChange={setOperation}
          options={[{ value: "recharge", label: "充值" }, { value: "deduct", label: "扣减" }]}
        />
        <label className="grid gap-1.5">
          <span>数量（积分）</span>
          <InputNumber
            className="!w-full"
            min={1}
            max={MAX_CREDIT_AMOUNT}
            precision={0}
            disabled={mutation.isPending}
            value={amount}
            onChange={setAmount}
            placeholder="输入整积分"
            status={exceedsBalance || exceedsLimit ? "error" : undefined}
          />
        </label>
        {exceedsBalance ? <Alert type="error" showIcon title="扣减积分不能超过当前余额" /> : null}
        {exceedsLimit ? <Alert type="error" showIcon title="调整后积分超出账户可记录范围" /> : null}
        <label className="grid gap-1.5">
          <span>原因（必填，写入流水）</span>
          <Input.TextArea
            rows={2}
            maxLength={200}
            disabled={mutation.isPending}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="例如：11 月额度发放"
          />
        </label>
        {mutation.isError ? <Alert type="error" showIcon title={mutation.error.message} /> : null}
      </div>
    </Modal>
  )
}
