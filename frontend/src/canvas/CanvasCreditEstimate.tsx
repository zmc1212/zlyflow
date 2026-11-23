// 发送按钮左侧的积分预估：与生成页 studio-submit-cost 同语义（云端/生图计费工作流才显示），
// 参数变化后防抖查询 /api/credits/estimate，精确数值以提交实扣为准。
import { useQuery } from "@tanstack/react-query"
import { Coins } from "lucide-react"
import { useEffect, useState } from "react"
import { Tooltip } from "antd"
import { requestJson } from "../api"
import { formatCredits, type CreditEstimate } from "../credits/credits"
import type { CanvasOptionValue, CanvasWorkflowMode } from "./canvas-generation"

export function CanvasCreditEstimate({ mode, values, referenceCount, authenticated = true }: {
  mode: CanvasWorkflowMode | null
  values: Record<string, CanvasOptionValue>
  referenceCount: number
  /** 游客（未登录）不预估：estimate 接口需要登录态。 */
  authenticated?: boolean
}) {
  const serialized = JSON.stringify(values ?? {})
  const [debouncedKey, setDebouncedKey] = useState(serialized)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKey(serialized), 450)
    return () => clearTimeout(timer)
  }, [serialized])
  const estimateQuery = useQuery({
    queryKey: ["canvas-credits-estimate", mode?.id ?? "", debouncedKey, referenceCount],
    queryFn: () => requestJson<CreditEstimate>("/api/credits/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: mode?.id,
        options: JSON.parse(debouncedKey || "{}"),
        reference_count: referenceCount,
      }),
    }),
    enabled: Boolean(authenticated) && Boolean(mode?.billing?.enabled) && Boolean(debouncedKey),
    staleTime: 1000 * 10,
  })
  if (!authenticated || !mode?.billing?.enabled) return null
  const insufficient = Boolean(estimateQuery.data && !estimateQuery.data.sufficient)
  const balanceText = estimateQuery.data
    ? insufficient
      ? `余额不足（当前 ${formatCredits(estimateQuery.data.balance)} 积分），请联系管理员充值`
      : `余额 ${formatCredits(estimateQuery.data.balance)} 积分`
    : ""
  return (
    <Tooltip title={estimateQuery.data
      ? `${estimateQuery.data.breakdown || "以提交时实扣为准"} · ${balanceText}`
      : "按当前参数预估本次积分消耗"}>
      <span aria-label="本次预计消耗积分" className={`canvas-composer-cost${insufficient ? " is-warning" : ""}`}>
        <Coins size={12} aria-hidden />
        {estimateQuery.isLoading
          ? "预估中…"
          : estimateQuery.data && estimateQuery.data.credits > 0
            ? `${formatCredits(estimateQuery.data.credits)} 积分`
            : "免费"}
      </span>
    </Tooltip>
  )
}
