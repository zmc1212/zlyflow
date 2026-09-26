import { Alert, Card, Collapse, Descriptions, Space, Tag, Typography } from "antd"
import type { WorkshopGroup, WorkshopJob } from "../workshop-api"

// Business evidence view; controls, disclosure and typography remain native Ant Design.
export default function WorkshopAuthoringEvidence({ job, group }: { job: WorkshopJob; group: WorkshopGroup }) {
  const attempts = job.payload.authoring?.writing_history?.filter(a => a.group_id === group.id) || []
  const latest = attempts.at(-1)
  const review = job.payload.authoring?.reviews?.[group.id] || latest?.review
  const before = job.payload.base_plan?.groups.find(g => g.id === group.id)?.common_prompt ?? group.common_prompt
  const after = job.payload.common_prompt_candidates?.[group.id]
  const contract = job.payload.authoring?.contracts?.[group.id]
  const author = latest?.author
  const rejected = job.payload.authoring?.rejected_groups?.[group.id]
  return <Space direction="vertical" className="workshop-authoring-evidence" style={{ width: "100%", margin: "12px 0" }}>
    <Space wrap>
      <Tag color={review?.structure_status === "passed" && !latest?.errors.length ? "green" : "default"}>结构：{review ? review.structure_status === "passed" && !latest?.errors.length ? "通过" : "未通过" : "无记录"}</Tag>
      <Tag color="gold">内容：{review?.content_status === "rules_clear" ? "规则未见问题 · 人工待核" : review ? "有风险 · 待复核" : "未审查"}</Tag>
      <Tag>成片：未验收</Tag>
    </Space>
    <Typography.Text>请求作者：{author?.requested_model || job.payload.writing_author?.model || "历史任务未记录"}；响应模型：{author?.actual_model || "供应商未返回，不能确认"}</Typography.Text>
    <Space wrap>
      <Tag color={author?.attach_images ? "success" : "default"}>{author?.attach_images === true ? "带图写稿" : author?.attach_images === false ? "纯文本写稿" : "历史任务未记录是否带图"}</Tag>
      <Tag color={author?.fallback_from || author?.vision_status === "failed_text_fallback" ? "warning" : "default"}>{author?.fallback_from || author?.vision_status === "failed_text_fallback" ? "已降级，需复核" : author?.vision_status || author?.fallback_from === null ? "未发生自动降级" : "路由未记录"}</Tag>
    </Space>
    {author?.warning && <Alert type="warning" showIcon message={author.warning} />}
    <Typography.Text type="secondary">供应商：{author?.provider_profile_id || job.payload.writing_author?.profile_id || "未记录"} · 推理：{author?.reasoning_effort || job.payload.writing_author?.reasoning_effort || "未记录"} · 温度：{author?.temperature ?? "未记录"}</Typography.Text>
    {author?.fact_extraction === "vlm" && <Alert type="info" showIcon message="VLM 只提取外观事实，指定作者写稿；这不是满意版原样复现。" />}
    {job.payload.request?.revision_note && <Typography.Paragraph>返修意见：{job.payload.request.revision_note}</Typography.Paragraph>}
    {rejected && <Alert type="warning" showIcon message={`保留第 ${rejected.attempt} 次较好草稿，但仍未通过，不可采纳`} description={<Collapse items={[{ key: "retained", label: "查看保留草稿", children: <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{rejected.raw}</Typography.Paragraph> }]} />} />}
    {after && after !== before && <Alert type="warning" showIcon message="本候选同时修改公共设定，采纳时与全组正文一起生效" description={<Collapse items={[{ key: "common-diff", label: "查看公共设定变更（旧 / 新）", children: <div className="workshop-common-comparison">
      <Card size="small" title="生成前设定"><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{before || "空"}</Typography.Paragraph></Card>
      <Card size="small" title="候选设定"><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{after}</Typography.Paragraph></Card>
    </div> }]} />} />}
    {review && <Collapse items={[{ key: "review", label: `内容检查与人工清单（${review.issues.length} 条提示）`, children: <>
      {review.issues.map((issue, i) => <Alert key={`${issue.code}-${i}`} type={issue.severity === "error" ? "error" : "warning"} showIcon message={`${issue.beat_id}：${issue.suggestion}`} description={<Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>原文证据：{issue.evidence}</Typography.Paragraph>} />)}
      <Typography.Paragraph>仍需人工核对：{review.manual_checks?.join("；")}。文本检查不等于实际中文对白、口型或成片验收。</Typography.Paragraph>
    </> }]} />}
    {attempts.length > 0 && <Collapse items={[{ key: "evidence", label: `写稿与返修证据（${attempts.length} 次）`, children: <>
      <Descriptions size="small" column={1} items={[{ key: "version", label: "合同版本", children: contract?.version || "未记录" },
        { key: "skill", label: "Skill SHA-256", children: contract?.skill_sha256 || latest?.skill_sha256 },
        { key: "source", label: "剧本策略", children: contract?.context_policy === "full_source_no_truncation" ? "完整上下文，未静默裁剪" : "未记录" }]} />
      <Collapse items={attempts.map((attempt, i) => ({ key: String(i), label: `第 ${attempt.attempt} 次 · ${attempt.reason || "执行中"}`, children: <>
        <Typography.Paragraph>请求 ID：{attempt.author?.request_id || "未返回"} · 耗时：{attempt.author?.elapsed_ms ?? "未知"} ms · 推理：{attempt.author?.reasoning_effort || "未记录"}</Typography.Paragraph>
        {attempt.errors.length > 0 && <Alert type="error" message={attempt.errors.join("；")} />}
        <Collapse items={[{ key: "raw", label: "原始完整稿", children: <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{attempt.raw || "未返回正文"}</Typography.Paragraph> },
          { key: "diff", label: "与上一稿的逐行差异", children: <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{attempt.diff || "首次生成"}</pre> },
          { key: "input", label: "本轮完整输入", children: <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap" }}>{contract?.system}{"\n\n"}{attempt.input}</Typography.Paragraph> }]} />
      </> }))} />
    </> }]} />}
  </Space>
}
