import { Button } from "antd"
import { AlertTriangle, CheckCircle2, Clapperboard, RefreshCw } from "lucide-react"
import {
  SCRIPT_COMPLETION_FAILED_PREFIX, SCRIPT_COMPLETION_TITLE, SCRIPT_NEXT_REGENERATE, SCRIPT_NEXT_STORYBOARD,
} from "../action-copy"

export type PlanCompletion = {
  ok: boolean
  failedAgents: string[]
  shotCount: number
}

type Props = {
  completion: PlanCompletion
  failedLabels?: string[]
  onNextStoryboard: () => void
  onRegenerate: () => void
}

/** Post-generation card at the end of the creation conversation with next-step chips. */
export default function DirectorCompletionCard({
  completion, failedLabels = [], onNextStoryboard, onRegenerate,
}: Props) {
  const ok = completion.ok
  return (
    <div className={`director-completion-card ${ok ? "is-ok" : "is-warn"}`}>
      {ok ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
      <div className="director-completion-copy">
        <strong>{ok ? SCRIPT_COMPLETION_TITLE : `${SCRIPT_COMPLETION_FAILED_PREFIX}${failedLabels.join("、")}`}</strong>
        <span>{completion.shotCount > 0 ? `已产出 ${completion.shotCount} 个镜头的完整创作方案。` : "创作方案已生成。"}</span>
      </div>
      <div className="director-completion-actions">
        {completion.shotCount > 0 ? (
          <Button type="primary" icon={<Clapperboard size={14} />} onClick={onNextStoryboard}>
            {SCRIPT_NEXT_STORYBOARD}
          </Button>
        ) : null}
        <Button icon={<RefreshCw size={14} />} onClick={onRegenerate}>{SCRIPT_NEXT_REGENERATE}</Button>
      </div>
    </div>
  )
}
