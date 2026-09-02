import { useMemo, useState } from "react"
import { Button, Tag } from "antd"
import type { ShotTake } from "../types"
import {
  resolveTakeGenerationMeta,
  takeGenerationDiff,
  type TakeGenerationJobLike,
} from "../take-generation-params"
import { directorRenderPassLabel } from "../prompt-compiler"

type TakeGenerationParamsProps = {
  take: ShotTake
  job?: TakeGenerationJobLike | null
  compareTake?: ShotTake | null
  compareJob?: TakeGenerationJobLike | null
  compact?: boolean
}

export default function TakeGenerationParams({
  take,
  job,
  compareTake,
  compareJob,
  compact = false,
}: TakeGenerationParamsProps) {
  const [expanded, setExpanded] = useState(false)
  const meta = useMemo(() => resolveTakeGenerationMeta(take, job), [take, job])
  const compareMeta = useMemo(
    () => (compareTake ? resolveTakeGenerationMeta(compareTake, compareJob) : null),
    [compareTake, compareJob],
  )
  const diffLabels = useMemo(
    () => (compareMeta ? new Set(takeGenerationDiff(meta, compareMeta)) : null),
    [compareMeta, meta],
  )

  if (!meta.summary && !meta.workflowId && !Object.keys(meta.options).length) {
    return (
      <p className="director-take-params is-empty">
        {take.jobId ? "历史 Take，参数未记录；可在创作页任务详情查看。" : "尚无生成参数"}
      </p>
    )
  }

  return (
    <div className={`director-take-params${compact ? " is-compact" : ""}`}>
      <div className="director-take-params-summary">
        {compact && take.renderPass ? (
          <Tag className="!m-0">{directorRenderPassLabel(take.renderPass)}</Tag>
        ) : null}
        <span className="director-take-params-line">{meta.summary}</span>
        {!compact ? (
          <Button type="link" size="small" className="director-take-params-toggle" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起参数" : "查看参数"}
          </Button>
        ) : null}
      </div>
      {expanded && !compact ? (
        <dl className="director-take-params-details">
          {meta.details.map((item) => (
            <div
              key={item.label}
              className={`director-take-params-row${diffLabels?.has(item.label) ? " is-diff" : ""}`}
            >
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
          {take.promptSnapshot ? (
            <div className="director-take-params-prompt">
              <dt>提示词快照</dt>
              <dd>
                <pre>{take.promptSnapshot}</pre>
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  )
}
