import { AlertTriangle, CheckCircle2 } from "lucide-react"
import { Button } from "antd"
import {
  SCRIPT_COMPLETION_FAILED_PREFIX, SCRIPT_COMPLETION_RETRY_HINT, SCRIPT_COMPLETION_RETRY_PREFIX, SCRIPT_COMPLETION_TITLE,
} from "../action-copy"

export type PlanCompletion = {
  ok: boolean
  failedAgents: string[]
  shotCount: number
}

type Props = {
  completion: PlanCompletion
  failedLabels?: string[]
  /** 提供后在每个失败环节旁显示「重试」按钮；重试沿用已有产出继续（分镜为续跑，不重拆）。 */
  onRetryAgent?: (agentId: string) => void
}

/**
 * Post-generation status card at the end of the creation conversation.
 * 纯状态展示 + 失败环节的「重试」入口：重跑走各环节的重试入口，进入分镜走成稿工具栏，避免出现
 * 会把整个方案从第一步重跑的「重新生成」和重复的「进入分镜设计」。
 */
export default function DirectorCompletionCard({
  completion, failedLabels = [], onRetryAgent,
}: Props) {
  const ok = completion.ok
  return (
    <div className={`director-completion-card ${ok ? "is-ok" : "is-warn"}`}>
      {ok ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
      <div className="director-completion-copy">
        <strong>{ok ? SCRIPT_COMPLETION_TITLE : `${SCRIPT_COMPLETION_FAILED_PREFIX}${failedLabels.join("、")}`}</strong>
        <span>{completion.shotCount > 0 ? `已产出 ${completion.shotCount} 个镜头的完整创作方案。` : "创作方案已生成。"}</span>
      </div>
      {!ok && onRetryAgent && completion.failedAgents.length ? (
        <div className="director-completion-actions">
          {completion.failedAgents.map((agentId, index) => (
            <Button
              key={agentId}
              size="small"
              title={SCRIPT_COMPLETION_RETRY_HINT}
              onClick={() => onRetryAgent(agentId)}
            >
              {SCRIPT_COMPLETION_RETRY_PREFIX}{failedLabels[index] || agentId}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
