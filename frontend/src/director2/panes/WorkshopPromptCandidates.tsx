import { Alert, Button, Collapse, Typography } from "antd"
import { workshopCandidateStaleReason, type WorkshopGroup, type WorkshopJob, type WorkshopPlan } from "../workshop-api"
import WorkshopAuthoringEvidence from "./WorkshopAuthoringEvidence"

type CandidateContext = {
  beatId: string
  group?: WorkshopGroup
  groupWriting: boolean
  plan: WorkshopPlan | null
  sourceChanged: boolean
  busy: boolean
  dirty: boolean
}

// Presentation only: the mutation and revision guards remain in UnifiedWorkshopPane.
export function workshopCandidatePresentation(job: WorkshopJob, context: CandidateContext) {
  const { beatId, group, groupWriting, plan, sourceChanged, busy, dirty } = context
  const wholeGroup = groupWriting && job.payload.prompt_scope === "group"
  const ids = wholeGroup ? group?.beat_ids || [] : [beatId]
  const applied = plan?.applied_candidates?.[job.id] || job.payload.applied_ids || []
  const legacy = groupWriting && !job.payload.prompt_scope
  const adopted = ids.length > 0 && ids.every(id => applied.includes(id))
  const staleReason = !adopted && plan && group ? workshopCandidateStaleReason(job, plan, group, sourceChanged) : ""
  const pending = !adopted && !staleReason && !legacy && job.status === "completed"
  const disabled = busy || dirty || Boolean(staleReason) || job.status !== "completed" || legacy || !ids.length || ids.some(id => !job.payload.candidates[id] || applied.includes(id))
  const status = adopted ? "已采纳" : staleReason ? "已过期" : legacy ? "旧版参考" : pending ? "待采纳" : job.status === "failed" ? "未通过" : "生成中"
  const scope = wholeGroup ? `整组候选（${ids.length} 镜）` : job.payload.prompt_scope === "shot_revision" ? "本镜返修候选" : "本镜候选"
  return { wholeGroup, ids, legacy, adopted, staleReason, pending, disabled, label: `${status} · ${scope} · ${job.id.slice(-8)}` }
}

type Props = CandidateContext & {
  display?: "all" | "pending" | "history"
  jobs: WorkshopJob[]
  beats: Array<{ id: string; sequence: number }>
  onApply: (job: WorkshopJob, ids: string[], wholeGroup: boolean) => void
  onRegenerate?: (job: WorkshopJob) => void
}

export function workshopCanRegenerate(job: WorkshopJob): boolean {
  const versions = Object.values(job.payload.authoring?.contracts || {}).map(contract => contract.version)
  return job.kind === "workshop_prompt" && ["failed", "cancelled", "completed"].includes(job.status)
    && (!versions.length || versions.some(version => ["h3-complete-group-v1", "h3-skill-direct-v1", "h3-skill-direct-v2"].includes(version)))
}

export function workshopPendingCandidateIds(jobs: WorkshopJob[], plan: WorkshopPlan | null | undefined, groupWriting: boolean, sourceChanged: boolean): Set<string> {
  const ids = new Set<string>()
  if (!plan) return ids
  for (const job of jobs) {
    if (job.kind !== "workshop_prompt") continue
    for (const beatId of Object.keys(job.payload.candidates || {})) {
      const group = plan.groups.find(item => item.beat_ids.includes(beatId))
      if (!group) continue
      const presentation = workshopCandidatePresentation(job, { beatId, group, groupWriting, plan, sourceChanged, busy: false, dirty: false })
      if (presentation.pending && !presentation.disabled) ids.add(beatId)
    }
  }
  return ids
}

export default function WorkshopPromptCandidates(props: Props) {
  const { jobs, beats, beatId, group, onApply, display = "all" } = props
  const candidates = jobs.filter(job => job.kind === "workshop_prompt" && job.payload.candidates?.[beatId])
    .map(job => ({ job, presentation: workshopCandidatePresentation(job, props) }))
  const pending = candidates.filter(item => item.presentation.pending)
  const history = candidates.filter(item => !item.presentation.pending)
  const rejected = group ? jobs.filter(job => job.kind === "workshop_prompt" && !job.payload.candidates?.[beatId] && job.payload.authoring?.writing_history?.some(attempt => attempt.group_id === group.id)) : []
  const historyCount = history.length + rejected.length
  const regenerate = (job: WorkshopJob) => props.onRegenerate && workshopCanRegenerate(job) ? <div>
    <Typography.Paragraph type="secondary">使用当前剧本、素材和写稿设置创建新任务；旧稿与旧任务保留。</Typography.Paragraph>
    <Button disabled={props.busy || props.dirty || props.sourceChanged || !props.plan} onClick={() => props.onRegenerate?.(job)}>按新方式重新生成</Button>
  </div> : null
  const item = ({ job, presentation }: typeof candidates[number]) => ({
    key: job.id,
    label: presentation.label,
    children: <div className="workshop-candidate-content">
      {presentation.legacy && <Alert type="info" title="旧逐镜候选仅供参考，请重新生成整组候选" />}
      {presentation.staleReason && <Alert type="warning" showIcon title={presentation.staleReason} />}
      <Button disabled={presentation.disabled} onClick={() => onApply(job, presentation.ids, presentation.wholeGroup)}>
        {presentation.adopted ? "已采用候选" : presentation.wholeGroup ? "采用整组候选" : "采用本镜候选"}
      </Button>
      {group && <WorkshopAuthoringEvidence job={job} group={group} />}
      {regenerate(job)}
      {presentation.ids.map(id => <section className="workshop-candidate-shot" key={id}>
        <Typography.Text strong>镜头 {beats.find(beat => beat.id === id)?.sequence || id}</Typography.Text>
        <Typography.Paragraph>{job.payload.candidates[id]?.h3_prompt || "本组候选不完整，请重新生成"}</Typography.Paragraph>
      </section>)}
    </div>,
  })

  if ((!pending.length || display === "history") && (!historyCount || display === "pending")) return null
  return <div className="workshop-candidates">
    {display !== "history" && pending.length > 0 && <section aria-label="待采纳提示词候选" className="workshop-pending-candidates">
      <Typography.Text strong>待采纳候选（{pending.length} 份）</Typography.Text>
      <Typography.Text type="secondary">采纳后才会写入正式提示词；不会自动覆盖当前稿件。</Typography.Text>
      <Collapse key={`${beatId}:${pending.map(candidate => candidate.job.id).join(",")}`} defaultActiveKey={[pending[0].job.id]} items={pending.map(item)} />
    </section>}
    {display !== "pending" && historyCount > 0 && <Collapse className="workshop-candidate-history" items={[{
      key: "candidate-history",
      label: `候选与返修历史（${historyCount}）`,
      children: <Collapse items={[...history.map(item), ...rejected.map(job => ({
        key: job.id,
        label: `未通过候选与返修记录 · ${job.id.slice(-8)}（不会覆盖正式稿）`,
        children: group && <><WorkshopAuthoringEvidence job={job} group={group} />{regenerate(job)}</>,
      }))]} />,
    }]} />}
  </div>
}
