import { useEffect, useRef, useState } from "react"
import { Alert, Button, Space, Tag, Tooltip } from "antd"
import { Check, Coins, FilePenLine, Link2, ListPlus, PenLine, Play, Replace, Sparkles, Trash2, Upload } from "lucide-react"
import { canvasAssistantMutate, describeOp, formatOptionChips, OP_LABELS, type CanvasAssistantOp, type CanvasProposal } from "./api"

// 画布方案卡与导演台的产物卡/媒体审批卡同构：assistant-deliverable 容器 + ops 清单。
// 注意：不能用裸 tone-orange 类名——index.css 里有导演台海报 mockup 的全局
// .tone-orange 渐变背景，会类名冲突涂满整行；submit/delete 行用 tone-submit。

const OP_ICONS: Record<CanvasAssistantOp["op"], typeof Sparkles> = {
  create_text: PenLine,
  create_generator: Sparkles,
  connect: Link2,
  update_generator: Replace,
  update_text: FilePenLine,
  submit: Play,
  insert_library_item: Upload,
  delete_node: Trash2,
}

const OP_TONE: Partial<Record<CanvasAssistantOp["op"], string>> = { submit: "tone-submit", delete_node: "tone-submit" }

export function ProposalSummaryChips({ proposal }: { proposal: CanvasProposal }) {
  const counts = proposal.summary?.counts || {}
  const chips: { label: string; tone?: string }[] = []
  if (counts.create_generator) chips.push({ label: `${counts.create_generator} 个生成节点` })
  if (counts.create_text) chips.push({ label: `${counts.create_text} 个文字节点` })
  if (counts.insert_library_item) chips.push({ label: `${counts.insert_library_item} 个素材` })
  if (counts.connect) chips.push({ label: `${counts.connect} 条连线` })
  if (counts.update_generator) chips.push({ label: `${counts.update_generator} 处更新` })
  if (counts.delete_node) chips.push({ label: `${counts.delete_node} 个删除`, tone: "orange" })
  if (counts.submit) chips.push({ label: `${counts.submit} 个生成任务`, tone: "orange" })
  const credit = proposal.summary?.credit_estimate
  return <div className="canvas-assistant-proposal-chips">
    {chips.map(chip => <span key={chip.label} className={`canvas-assistant-chip${chip.tone ? ` tone-${chip.tone}` : ""}`}>{chip.label}</span>)}
    {!!credit && <Tooltip title="按工作流平台标价估算，实际以提交时预估为准">
      <span className="canvas-assistant-chip tone-orange"><Coins size={11} />约 {credit} 积分</span>
    </Tooltip>}
  </div>
}

export function ProposalOpsList({ ops, modes, describeNode }: { ops: CanvasAssistantOp[]; modes: { id: string; name: string }[]; describeNode?: (ref: string) => string }) {
  const workflowName = (id: string | null | undefined) => (id ? modes.find(mode => mode.id === id)?.name || id : "")
  return <ul className="canvas-assistant-proposal-ops">{ops.map((op, index) => {
    const Icon = OP_ICONS[op.op] || ListPlus
    const tone = OP_TONE[op.op]
    // create_generator/update_generator 结构化排版：操作名+工作流、参数 chips、提示词摘要分行；
    // 其余操作保持单行描述。长提示词两行截断，避免 ops 清单变成不可扫读的长文块。
    const structuredParams = op.op === "create_generator" || op.op === "update_generator" ? formatOptionChips(op.option_values) : []
    const structuredPrompt = (op.op === "create_generator" || op.op === "update_generator") && op.prompt ? op.prompt.slice(0, 120)
      : op.op === "update_text" && (op.text || op.label) ? `新内容：${(op.text || op.label || "").slice(0, 120)}` : ""
    const workflowLabel = op.op === "create_generator" ? workflowName(op.workflow_id)
      : op.op === "update_generator" && op.workflow_id ? `换用 ${workflowName(op.workflow_id)}` : ""
    const targetLabel = op.op === "submit" && describeNode ? describeNode(op.ref || "") : ""
    const refsLabel = op.op === "create_generator" && op.connect_from?.length ? `连入 ${op.connect_from.length} 个节点（提示词/参考）` : ""
    const fallbackDesc = structuredParams.length || structuredPrompt || workflowLabel || refsLabel ? ""
      : describeOp(op, modes, describeNode)
    return <li key={`${op.ref}-${index}`} className={`canvas-assistant-proposal-op${tone ? ` ${tone}` : ""}`}>
      <span className="canvas-assistant-proposal-op-icon"><Icon size={13} /></span>
      <span className="canvas-assistant-proposal-op-body">
        <span className="canvas-assistant-proposal-op-label">
          {OP_LABELS[op.op]}
          {targetLabel && <em className="canvas-assistant-proposal-op-target">{targetLabel}</em>}
          {!targetLabel && workflowLabel && <em className="canvas-assistant-proposal-op-target">{workflowLabel}</em>}
        </span>
        {!!structuredParams.length && <span className="canvas-assistant-proposal-op-params">
          {structuredParams.map(chip => <i key={`${chip.label}-${chip.value}`} className="canvas-assistant-chip">{chip.label} {chip.value}</i>)}
          {refsLabel && <i className="canvas-assistant-chip tone-connect">{refsLabel}</i>}
        </span>}
        {structuredPrompt && <span className="canvas-assistant-proposal-op-prompt">{structuredPrompt}</span>}
        {fallbackDesc && <span className="canvas-assistant-proposal-op-desc">{fallbackDesc}</span>}
      </span>
    </li>
  })}</ul>
}

/** 画布操作方案卡：展示将执行的操作清单，用户点「应用到画布」后由前端 bridge 逐条执行。 */
export default function CanvasProposalCard({ proposal, modes, csrfToken, apply, describeNode, checkNodes, superseded, onSettled }: {
  proposal: CanvasProposal
  modes: { id: string; name: string }[]
  csrfToken: string
  apply: (ops: CanvasAssistantOp[]) => Promise<{ applied: number; failed: { op_index?: number; error: string }[]; created_node_ids?: string[]; removed_node_ids?: string[] }>
  describeNode?: (ref: string) => string
  /** 查询这些节点 ID 中已不在画布上的部分；用于撤销/删除后提示卡片与画布状态不一致。 */
  checkNodes?: (nodeIds: string[]) => string[]
  superseded?: boolean
  onSettled?: (proposal: CanvasProposal) => void
}) {
  const [busy, setBusy] = useState<"apply" | "dismiss" | null>(null)
  const [result, setResult] = useState<CanvasProposal["apply_result"] | null>(proposal.apply_result ?? null)
  // 应用时对画布的实际改动（后端 apply_result.detail 也持久化一份，刷新后仍可对比）：
  // created 撤销后消失，removed 撤销后重现——两类都要检测才能覆盖纯删除方案。
  const [trackedIds, setTrackedIds] = useState<{ created: string[]; removed: string[] }>(() => ({
    created: proposal.apply_result?.created_node_ids ?? [],
    removed: proposal.apply_result?.removed_node_ids ?? [],
  }))
  const [reverted, setReverted] = useState<"all" | "partial" | null>(null)
  const revertedRef = useRef<"all" | "partial" | null>(null)
  const settled = proposal.status !== "awaiting_approval" || !!result
  const failed = result?.failed || []

  // 撤销/删除兜底：已应用的方案卡每 2s 对一次画布现状，整组节点与画布不一致时给出重新应用入口，
  // 部分不一致时提示状态偏差（D3：Ctrl+Z 后画布已变但卡片仍显示「已应用」）。
  useEffect(() => {
    if (!checkNodes || !result || !result.applied_ops) return
    if (!trackedIds.created.length && !trackedIds.removed.length) return
    const tick = () => {
      const createdMissing = trackedIds.created.length ? checkNodes(trackedIds.created).length : 0
      const removedPresent = trackedIds.removed.length ? trackedIds.removed.length - checkNodes(trackedIds.removed).length : 0
      const createdReverted = !trackedIds.created.length || createdMissing >= trackedIds.created.length
      const removedReverted = !trackedIds.removed.length || removedPresent >= trackedIds.removed.length
      let next: "all" | "partial" | null = null
      if (createdReverted && removedReverted) next = "all"
      else if (createdMissing > 0 || removedPresent > 0) next = "partial"
      if (next !== revertedRef.current) {
        revertedRef.current = next
        setReverted(next)
      }
    }
    tick()
    const timer = window.setInterval(tick, 2000)
    return () => window.clearInterval(timer)
  }, [checkNodes, trackedIds, result])

  async function report(resultValue: string, detail: Record<string, unknown>) {
    try {
      await canvasAssistantMutate(csrfToken, `/proposals/${proposal.id}/apply-result`, { result: resultValue, detail })
    } catch { /* 状态上报失败不阻塞 UI，下次加载会话时仍可看到本地结果。 */ }
    onSettled?.(proposal)
  }

  async function applyOps(force = false) {
    if (busy || (settled && !force)) return
    setBusy("apply")
    try {
      const outcome = await apply(proposal.ops || [])
      const next = {
        applied_ops: outcome.applied,
        failed: outcome.failed,
        created_node_ids: outcome.created_node_ids ?? [],
        removed_node_ids: outcome.removed_node_ids ?? [],
      }
      setResult(next)
      setTrackedIds({ created: next.created_node_ids, removed: next.removed_node_ids })
      revertedRef.current = null
      setReverted(null)
      await report(outcome.failed.length ? "partial" : "applied", next)
    } catch (error) {
      const next = { applied_ops: 0, failed: [{ error: error instanceof Error ? error.message : String(error) }], created_node_ids: [], removed_node_ids: [] }
      setResult(next)
      setTrackedIds({ created: [], removed: [] })
      await report("failed", next)
    } finally { setBusy(null) }
  }

  async function dismiss() {
    if (busy || settled) return
    setBusy("dismiss")
    try { setResult({ applied_ops: 0, failed: [], created_node_ids: [], removed_node_ids: [] }); await report("dismissed", {}) }
    finally { setBusy(null) }
  }

  const appliedLabel = result?.applied_ops ? `已应用 ${result.applied_ops} 项` : "已忽略"
  const statusTag = result
    ? failed.length === 0
      ? reverted === "all"
        ? <Tag className="canvas-assistant-status-tag tone-orange">已应用 {result.applied_ops} 项 · 已被画布撤销</Tag>
        : <Tag className="canvas-assistant-status-tag tone-green" icon={<Check size={11} />}>{appliedLabel}</Tag>
      : <Tag className="canvas-assistant-status-tag tone-orange">应用 {result.applied_ops} 项 · {failed.length} 项失败{reverted === "all" ? " · 已被画布撤销" : ""}</Tag>
    : proposal.status === "dismissed"
      ? <Tag className="canvas-assistant-status-tag">已忽略</Tag>
      : <Tag className="canvas-assistant-status-tag">待确认</Tag>

  return <section className={`assistant-deliverable canvas-assistant-proposal${settled ? " is-settled" : ""}`} aria-label="画布操作方案">
    <div><Sparkles size={17} /><strong>{proposal.title}</strong>{statusTag}</div>
    {superseded && !settled && <div className="canvas-assistant-superseded-hint">画布上已有更新的待确认方案，请先处理新方案，或忽略本卡避免重复创建节点。</div>}
    {reverted === "partial" && <div className="canvas-assistant-superseded-hint">本方案应用的节点有一部分已被撤销或删除，卡片状态可能与画布不一致。</div>}
    <ProposalSummaryChips proposal={proposal} />
    <ProposalOpsList ops={proposal.ops || []} modes={modes} describeNode={describeNode} />
    {!!failed.length && <Alert type="warning" title={`应用时有 ${failed.length} 项未成功`} description={<ul className="canvas-assistant-proposal-failures">{failed.map((item, index) => <li key={index}>{item.error}</li>)}</ul>} />}
    {!settled && <Space style={{ marginTop: 10 }}>
      <Button size="small" type="text" disabled={busy !== null} onClick={dismiss}>忽略</Button>
      <Button size="small" type="primary" loading={busy === "apply"} disabled={busy !== null} onClick={() => void applyOps()}>应用到画布</Button>
    </Space>}
    {reverted === "all" && <Space style={{ marginTop: 10 }}>
      <Button size="small" type="primary" loading={busy === "apply"} disabled={busy !== null} onClick={() => void applyOps(true)}>重新应用到画布</Button>
    </Space>}
  </section>
}
