import { Alert, Button, Collapse, Space, Tabs, Typography } from "antd"
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
  const wholeGroup = groupWriting && job.payload?.prompt_scope === "group"
  const ids = wholeGroup ? group?.beat_ids || [] : [beatId]
  const applied = plan?.applied_candidates?.[job.id] || job.payload?.applied_ids || []
  const legacy = groupWriting && !job.payload?.prompt_scope
  const adopted = ids.length > 0 && ids.every(id => applied.includes(id))
  const staleReason = !adopted && plan && group ? workshopCandidateStaleReason(job, plan, group, sourceChanged) : ""
  const originalAvailable = job.status === "completed" || (["failed", "cancelled"].includes(job.status) && Boolean(group && job.payload?.ai_reviews?.[group.id]))
  const pending = !adopted && !staleReason && !legacy && originalAvailable
  const currentVersion = adopted && ids.every(id => plan?.shot_prompts[id]?.authoring_job_id === job.id && plan.shot_prompts[id]?.authoring_version === plan.shot_prompts[ids[0]]?.authoring_version) ? plan?.shot_prompts[ids[0]]?.authoring_version : undefined
  const canSwitch = Boolean(wholeGroup && currentVersion && !sourceChanged && !busy && !dirty && job.status === "completed")
  const disabled = busy || dirty || Boolean(staleReason) || !originalAvailable || legacy || !ids.length || ids.some(id => !job.payload?.candidates[id] || applied.includes(id))
  const status = adopted ? "已采纳" : staleReason ? "已过期" : legacy ? "旧版参考" : pending ? "待采纳" : job.status === "failed" ? "未通过" : "生成中"
  const scope = wholeGroup ? `整组候选（${ids.length} 镜）` : job.payload?.prompt_scope === "shot_revision" ? "本镜返修候选" : "本镜候选"
  return { wholeGroup, ids, legacy, adopted, staleReason, pending, disabled, currentVersion, canSwitch, label: `${status}${currentVersion ? currentVersion === "reviewed" ? "审校稿" : "原稿" : ""} · ${scope} · ${job.id.slice(-8)}` }
}

type Props = CandidateContext & {
  display?: "all" | "pending" | "history"
  jobs: WorkshopJob[]
  beats: Array<{ id: string; sequence: number }>
  onApply: (job: WorkshopJob, ids: string[], wholeGroup: boolean, version?: "original" | "reviewed") => void
  onReview?: (job: WorkshopJob, ids: string[]) => void
  onRegenerate?: (job: WorkshopJob) => void
}

export function workshopCanRegenerate(job: WorkshopJob): boolean {
  const versions = Object.values(job.payload?.authoring?.contracts || {}).map(contract => contract.version)
  return job.kind === "workshop_prompt" && ["failed", "cancelled", "completed"].includes(job.status)
    && (!versions.length || versions.some(version => ["h3-complete-group-v1", "h3-skill-direct-v1", "h3-skill-direct-v2"].includes(version)))
}

export function workshopPendingCandidateIds(jobs: WorkshopJob[], plan: WorkshopPlan | null | undefined, groupWriting: boolean, sourceChanged: boolean): Set<string> {
  const ids = new Set<string>()
  if (!plan) return ids
  for (const job of jobs) {
    if (job.kind !== "workshop_prompt") continue
    for (const beatId of Object.keys(job.payload?.candidates || {})) {
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
  const candidates = jobs.filter(job => job.kind === "workshop_prompt" && job.payload?.candidates?.[beatId])
    .map(job => ({ job, presentation: workshopCandidatePresentation(job, props) }))
  const pending = candidates.filter(item => item.presentation.pending)
  const history = candidates.filter(item => !item.presentation.pending)
  const rejected = group ? jobs.filter(job => job.kind === "workshop_prompt" && !job.payload?.candidates?.[beatId] && job.payload?.authoring?.writing_history?.some(attempt => attempt.group_id === group.id)) : []
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
      <Space wrap className="workshop-candidate-actions"><Button disabled={presentation.disabled && !(presentation.canSwitch && presentation.currentVersion === "reviewed")} onClick={() => onApply(job, presentation.ids, presentation.wholeGroup)}>
        {presentation.currentVersion === "original" ? "已采用原稿" : presentation.canSwitch ? "切换为原稿（整组）" : presentation.adopted ? "已采用候选" : presentation.wholeGroup ? "采用原稿（整组）" : "采用本镜候选"}
      </Button>
      {group && job.payload?.ai_reviews?.[group.id]?.result?.decision === "revised" && <Button type="primary" disabled={(presentation.disabled && !(presentation.canSwitch && presentation.currentVersion === "original")) || !job.payload?.ai_reviews[group.id].eligible || job.status !== "completed"} onClick={() => onApply(job, presentation.ids, true, "reviewed")}>{presentation.currentVersion === "reviewed" ? "已采用审校稿" : presentation.canSwitch ? "切换为审校稿（整组）" : "采用审校稿（整组）"}</Button>}
      {presentation.wholeGroup && props.onReview && <Button disabled={presentation.disabled} onClick={() => props.onReview?.(job, presentation.ids)}>
        {group && job.payload?.ai_reviews?.[group.id]?.status === "failed" ? "重试审校" : "审校原稿"}
      </Button>}
      </Space>
      {group && job.payload?.ai_reviews?.[group.id] && (() => {
        const review = job.payload?.ai_reviews[group.id]
        const labels: Record<string, string> = { running: "审校中", unchanged: "无需修改", revised: "已生成审校稿", needs_user_resolution: "需用户处理", failed: "审校失败", cancelled: "已取消" }
        return <section aria-label="二次 AI 审校">
          <Alert showIcon type={review.status === "failed" || review.errors.length ? "warning" : "info"} title={labels[review.status] || review.status} description="审校意见不代表成片质量合格；采用后才更新正式稿，不会自动生成视频。" />
          <Typography.Paragraph>审校模型：{review.author?.requested_model || "未记录"}；响应模型：{review.author?.actual_model || "未知"}</Typography.Paragraph>
          {review.original_image_content_verified === false && <Alert type="warning" title="历史原稿没有图像内容哈希，无法核实当时图像内容；本次审校保留实际图像证据。" />}
          <Collapse items={[{ key: "evidence", label: "审校证据与调用用量", children: <>
            <Typography.Paragraph>Skill：{review.skill_version} · {review.skill_sha256}<br />输入：{review.input_sha256}<br />原稿：{review.original_sha256}<br />内容调用：{review.content_call_count ?? "未知"} · 传输重试：{review.transport_retry_count ?? "未知"} · 耗时：{review.elapsed_ms === undefined ? "未知" : `${review.elapsed_ms} ms`}<br />供应商用量：{review.author?.usage ? JSON.stringify(review.author.usage) : "未知"} · 费用：未知</Typography.Paragraph>
            <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{review.system}</Typography.Paragraph>
            <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{review.user}</Typography.Paragraph>
            <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{review.raw}</Typography.Paragraph>
          </> }]} />
          {review.errors.map((error, i) => <Typography.Paragraph type="danger" key={i}>{error}</Typography.Paragraph>)}
          {review.result?.issues.map((issue, i) => <Typography.Paragraph key={i}><strong>{issue.location} · {issue.certainty === "conflict" ? "确定冲突" : "推测风险"}</strong><br />原文：{issue.evidence}<br />{issue.reason}<br />建议：{issue.suggestion}</Typography.Paragraph>)}
          {review.result?.decision === "revised" && <>
            <Tabs items={[
              { key: "reviewed", label: "审校稿", children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{review.result.final_prompt}</Typography.Paragraph> },
              { key: "diff", label: "实际差异与理由", children: <>{review.result.changes.map((change, i) => <Typography.Paragraph key={i}>{change.location}：{change.reason}</Typography.Paragraph>)}<pre style={{ whiteSpace: "pre-wrap" }}>{review.diff}</pre></> },
              { key: "original", label: "原稿", children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{job.payload?.authoring?.writing_history?.filter(item => item.group_id === group.id && !item.errors.length).at(-1)?.raw}</Typography.Paragraph> },
            ]} />
          </>}
        </section>
      })()}
      {group && <WorkshopAuthoringEvidence job={job} group={group} />}
      {regenerate(job)}
      {presentation.ids.map(id => <section className="workshop-candidate-shot" key={id}>
        <Typography.Text strong>镜头 {beats.find(beat => beat.id === id)?.sequence || id}</Typography.Text>
        <Typography.Paragraph>{job.payload?.candidates[id]?.h3_prompt || "本组候选不完整，请重新生成"}</Typography.Paragraph>
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
