import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Alert, InputNumber, Modal, Segmented, message } from "antd"
import { useState } from "react"
import { apiErrorMessage, jsonMutation, requestJson } from "../api"
import {
  MAX_CREDIT_AMOUNT,
  formatCredits,
  type EnterpriseMember,
  type EnterpriseMemberQuotaPeriod,
} from "../credits/credits"

const PERIOD_OPTIONS: { value: EnterpriseMemberQuotaPeriod; label: string }[] = [
  { value: "none", label: "不限制" },
  { value: "monthly", label: "每月" },
  { value: "total", label: "累计" },
]

/**
 * 企业成员额度设置：只限制该成员消费企业钱包的上限，不改变企业总余额。
 * 用量由企业积分流水实时聚合，退款自动回冲。
 */
export default function MemberQuotaModal({
  csrfToken,
  enterpriseId,
  enterpriseName,
  enterpriseBalance,
  member,
  onClose,
}: {
  csrfToken: string
  enterpriseId: string
  enterpriseName: string
  enterpriseBalance: number
  member: EnterpriseMember
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState<EnterpriseMemberQuotaPeriod>(member.quota_period)
  const [creditLimit, setCreditLimit] = useState<number>(member.quota_limit || 1000)

  const saveMutation = useMutation({
    mutationFn: () => requestJson<{
      user_id: string
      enterprise_id: string
      quota_period: EnterpriseMemberQuotaPeriod
      quota_limit: number
      quota_used: number
      month_consumed: number
    }>(`/api/admin/enterprises/${enterpriseId}/members/${member.id}/quota`, jsonMutation(csrfToken, {
      period,
      credit_limit: period === "none" ? 0 : Math.max(1, Math.floor(creditLimit)),
    }, "PUT")),
    onSuccess: () => {
      message.success(`已更新「${member.display_name}」的额度设置`)
      queryClient.invalidateQueries({ queryKey: ["admin-enterprise-members", enterpriseId] })
      onClose()
    },
    onError: (error: Error) => message.error(apiErrorMessage(null, error.message)),
  })

  const limitValid = period === "none" || (creditLimit >= 1 && creditLimit <= MAX_CREDIT_AMOUNT)

  return (
    <Modal
      open
      title={`成员额度 · ${member.display_name}`}
      okText="保存额度"
      cancelText="取消"
      confirmLoading={saveMutation.isPending}
      okButtonProps={{ disabled: !limitValid }}
      onOk={() => {
        if (limitValid && !saveMutation.isPending) saveMutation.mutate()
      }}
      onCancel={onClose}
      destroyOnHidden
      width={520}
    >
      <div className="grid gap-4">
        <Alert
          type="info"
          showIcon
          message="额度只限制成员消费，不改变企业钱包余额"
          description="按企业积分流水实时统计，退款自动回冲；额度用尽后该成员提交任务或调用大模型会被拒绝。"
        />
        <div className="grid gap-2 rounded-lg border border-black/[0.08] bg-[#f9fafb] p-3 text-xs text-[#4b5563]">
          <p>企业：<span className="font-medium text-[#111827]">{enterpriseName}</span></p>
          <p>企业余额：<span className="font-medium tabular-nums text-[#111827]">{formatCredits(enterpriseBalance)}</span> 积分</p>
          <p>本月已用：<span className="font-medium tabular-nums text-[#111827]">{formatCredits(member.month_consumed)}</span> 积分 · 累计净消耗：<span className="font-medium tabular-nums text-[#111827]">{formatCredits(member.net_consumed)}</span> 积分</p>
        </div>
        <label className="grid gap-1.5">
          <span className="text-sm text-[#374151]">额度周期</span>
          <Segmented
            value={period}
            onChange={(value) => setPeriod(String(value) as EnterpriseMemberQuotaPeriod)}
            options={PERIOD_OPTIONS}
            aria-label="选择额度周期"
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-sm text-[#374151]">额度上限（积分）</span>
          <InputNumber
            value={period === "none" ? 0 : creditLimit}
            min={1}
            max={MAX_CREDIT_AMOUNT}
            precision={0}
            disabled={period === "none"}
            className="w-full"
            addonAfter="积分"
            onChange={(value) => setCreditLimit(Number(value ?? 0))}
          />
          <span className="text-[11px] leading-4 text-[#9ca3af]">
            100 积分 = 1 元；每月额度按北京时间自然月重置，累计额度统计加入该企业后的全部净消耗。
          </span>
        </label>
        {saveMutation.isError ? (
          <p className="text-sm text-red-600">{apiErrorMessage(null, saveMutation.error.message)}</p>
        ) : null}
      </div>
    </Modal>
  )
}
