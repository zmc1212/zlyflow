import { Avatar, Modal, Spin, Tabs } from "antd"
import { ChevronRight } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { fetchCanvasProjectCreditStats, type CanvasProjectCreditStats } from "./canvas-api"
import type { CanvasNode, CanvasProjectDetail } from "./canvas-model"
import { formatCredits } from "../credits/credits"

type ProjectInfoUser = {
  username: string
  display_name: string
  avatar_url?: string | null
}

type CanvasProjectInfoModalProps = {
  open: boolean
  project: CanvasProjectDetail
  user: ProjectInfoUser
  nodes: CanvasNode[]
  csrfToken: string
  onClose: () => void
  onViewCreditDetails: () => void
}

/** 节点分布卡片：与画布节点类型一一对应，未知类型归入「其他」。 */
const CANVAS_NODE_DISTRIBUTION: Array<{ key: string; label: string }> = [
  { key: "image", label: "图片" },
  { key: "video", label: "视频" },
  { key: "audio", label: "音频" },
  { key: "text", label: "文本" },
  { key: "generator", label: "生成" },
  { key: "artboard", label: "画板" },
]

/** 从画布节点收集全部引用过的任务号：生成节点、结果节点溯源与历史运行快照。 */
export function collectCanvasJobIds(nodes: CanvasNode[]): string[] {
  const ids = new Set<string>()
  for (const node of nodes) {
    const data = node.data
    if (!data) continue
    if (data.jobId) ids.add(data.jobId)
    if (data.sourceJobId) ids.add(data.sourceJobId)
    for (const run of [data.sourceRun, data.lastRun, ...(data.runHistory ?? [])]) {
      if (run?.jobId) ids.add(run.jobId)
    }
    for (const version of data.resultHistory ?? []) {
      if (version.jobId) ids.add(version.jobId)
    }
  }
  return [...ids]
}

export function canvasNodeDistribution(nodes: CanvasNode[]): Array<{ label: string; count: number; total: boolean }> {
  const counts = new Map<string, number>()
  for (const node of nodes) {
    const key = CANVAS_NODE_DISTRIBUTION.some((item) => item.key === node.type) ? String(node.type) : "other"
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [
    { label: "全部节点", count: nodes.length, total: true },
    ...CANVAS_NODE_DISTRIBUTION.map((item) => ({ label: item.label, count: counts.get(item.key) ?? 0, total: false })),
    { label: "其他", count: counts.get("other") ?? 0, total: false },
  ]
}

function formatFullTime(value?: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  const pad = (input: number) => String(input).padStart(2, "0")
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function CanvasProjectInfoModal({
  open,
  project,
  user,
  nodes,
  csrfToken,
  onClose,
  onViewCreditDetails,
}: CanvasProjectInfoModalProps) {
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes
  const [stats, setStats] = useState<CanvasProjectCreditStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError, setStatsError] = useState<string | null>(null)

  const distribution = useMemo(() => canvasNodeDistribution(nodes), [nodes])
  const displayName = user.display_name || user.username

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setStats(null)
    setStatsError(null)
    setStatsLoading(true)
    fetchCanvasProjectCreditStats(csrfToken, project.id, collectCanvasJobIds(nodesRef.current))
      .then((payload) => {
        if (!cancelled) setStats(payload)
      })
      .catch((error: unknown) => {
        if (!cancelled) setStatsError(error instanceof Error ? error.message : "积分消耗加载失败")
      })
      .finally(() => {
        if (!cancelled) setStatsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, csrfToken, project.id])

  const basicTab = (
    <div className="canvas-project-info-body">
      <div className="canvas-project-info-meta">
        <div className="canvas-project-info-meta-item">
          <span className="canvas-project-info-meta-label">所有者</span>
          <span className="canvas-project-info-owner">
            <Avatar size={22} src={user.avatar_url || undefined}>
              {Array.from(displayName)[0]?.toUpperCase()}
            </Avatar>
            <strong>{displayName}</strong>
          </span>
        </div>
        <div className="canvas-project-info-meta-item">
          <span className="canvas-project-info-meta-label">创建时间</span>
          <span>{formatFullTime(project.created_at)}</span>
        </div>
        <div className="canvas-project-info-meta-item">
          <span className="canvas-project-info-meta-label">最新修改</span>
          <span>{formatFullTime(project.draft_updated_at ?? project.updated_at)}</span>
        </div>
      </div>
      <div className="canvas-project-info-section-label">节点分布</div>
      <div className="canvas-project-node-grid">
        {distribution.map((item) => (
          <div key={item.label} className={item.total ? "canvas-project-node-card is-total" : "canvas-project-node-card"}>
            <span className="canvas-project-node-card-label">
              {item.label}
              {item.total ? <em className="canvas-project-node-card-tag">全部</em> : null}
            </span>
            <strong className="canvas-project-node-card-count">{item.count}</strong>
          </div>
        ))}
      </div>
    </div>
  )

  const creditsTab = (
    <div className="canvas-project-info-body">
      {statsLoading ? (
        <div className="canvas-project-credit-loading"><Spin /></div>
      ) : statsError ? (
        <div className="canvas-project-credit-empty">{statsError}</div>
      ) : stats ? (
        <>
          <div className="canvas-project-credit-summary">
            <div className="canvas-project-credit-summary-card">
              <span className="canvas-project-credit-summary-label">总消耗积分</span>
              <strong>{formatCredits(stats.total_credits)}</strong>
            </div>
            <div className="canvas-project-credit-summary-card">
              <span className="canvas-project-credit-summary-label">任务数</span>
              <strong>{formatCredits(stats.task_count)}</strong>
            </div>
          </div>
          {stats.groups.length ? (
            <div className="canvas-project-credit-table" role="table" aria-label="积分消耗分组">
              <div className="canvas-project-credit-row is-head" role="row">
                <span>类型</span>
                <span>任务数</span>
                <span>消耗积分</span>
                <span className="canvas-project-credit-ratio-head">占比</span>
              </div>
              {stats.groups.map((group) => (
                <div key={group.type} className="canvas-project-credit-row" role="row">
                  <span>{group.label}</span>
                  <span>{formatCredits(group.task_count)}</span>
                  <span>{formatCredits(group.credits)}</span>
                  <span className="canvas-project-credit-ratio">
                    <i className="canvas-project-credit-bar" style={{ width: `${Math.round(group.ratio * 100)}%` }} aria-hidden="true" />
                    <em>{(group.ratio * 100).toFixed(1)}%</em>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="canvas-project-credit-empty">画布还没有产生积分消耗，生成图片或视频后会在这里汇总</div>
          )}
        </>
      ) : null}
      <button type="button" className="canvas-project-credit-link" onClick={onViewCreditDetails}>
        查看积分明细
        <ChevronRight size={14} aria-hidden="true" />
      </button>
    </div>
  )

  return (
    <Modal
      className="canvas-dialog canvas-project-info-dialog"
      width={640}
      title="项目信息"
      open={open}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
    >
      <Tabs
        className="canvas-project-info-tabs"
        defaultActiveKey="basic"
        items={[
          { key: "basic", label: "基础信息", children: basicTab },
          { key: "credits", label: "积分消耗", children: creditsTab },
        ]}
      />
    </Modal>
  )
}
