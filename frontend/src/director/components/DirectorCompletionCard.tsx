import { AlertTriangle, CheckCircle2 } from "lucide-react"
import { SCRIPT_COMPLETION_FAILED_PREFIX, SCRIPT_COMPLETION_TITLE } from "../action-copy"

export type PlanCompletion = {
  ok: boolean
  failedAgents: string[]
  shotCount: number
}

type Props = {
  completion: PlanCompletion
  failedLabels?: string[]
}

/**
 * Post-generation status card at the end of the creation conversation.
 * 纯状态展示：重跑走各环节的重试入口，进入分镜走成稿工具栏，避免出现
 * 会把整个方案从第一步重跑的「重新生成」和重复的「进入分镜设计」。
 */
export default function DirectorCompletionCard({
  completion, failedLabels = [],
}: Props) {
  const ok = completion.ok
  return (
    <div className={`director-completion-card ${ok ? "is-ok" : "is-warn"}`}>
      {ok ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
      <div className="director-completion-copy">
        <strong>{ok ? SCRIPT_COMPLETION_TITLE : `${SCRIPT_COMPLETION_FAILED_PREFIX}${failedLabels.join("、")}`}</strong>
        <span>{completion.shotCount > 0 ? `已产出 ${completion.shotCount} 个镜头的完整创作方案。` : "创作方案已生成。"}</span>
      </div>
    </div>
  )
}
