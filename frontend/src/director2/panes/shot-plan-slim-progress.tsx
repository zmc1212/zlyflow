import { Button, Collapse, Progress } from "antd"
import {
  shotPlanProgressPercent,
  shotPlanSlimProgressLabel,
  type ShotPlanLiveState,
} from "../shot-plan-live"

export default function ShotPlanSlimProgress({
  live,
  onDismiss,
}: {
  live: ShotPlanLiveState
  onDismiss: () => void
}) {
  const reasoning = String(live.reasoning || "").trim()
  return (
    <div className="shot-plan-slim">
      <div className="shot-plan-slim-row">
        <span className="shot-plan-slim-copy">{shotPlanSlimProgressLabel(live)}</span>
        <Button type="text" size="small" onClick={onDismiss}>
          关闭
        </Button>
      </div>
      <Progress
        percent={shotPlanProgressPercent(live)}
        size="small"
        status="active"
        showInfo={false}
      />
      {reasoning ? (
        <Collapse
          ghost
          size="small"
          className="shot-plan-think"
          destroyOnHidden
          items={[{
            key: "think",
            label: "模型思路",
            children: <div className="shot-plan-think-body">{reasoning}</div>,
          }]}
        />
      ) : null}
    </div>
  )
}
