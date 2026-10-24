import { Alert, Button, Collapse, Tag, Typography } from "antd"
import { ExternalLink, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"
import { ApiRequestError } from "../api"
import {
  canvasJobOutputsExpired,
  canvasJobStatusColor,
  canvasJobStatusLabel,
  fetchCanvasJob,
  type CanvasJob,
} from "./canvas-generation"
import { formatCanvasTime, type CanvasMediaKind, type CanvasRunSnapshot } from "./canvas-model"

type CanvasSourceJobState = {
  loading: boolean
  job: CanvasJob | null
  missing: boolean
  error: string | null
}

export function useCanvasSourceJob(jobId: string | null | undefined, statusHint?: string | null) {
  const [state, setState] = useState<CanvasSourceJobState>({
    loading: Boolean(jobId),
    job: null,
    missing: false,
    error: null,
  })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!jobId) {
      setState({ loading: false, job: null, missing: false, error: null })
      return
    }
    let cancelled = false
    setState((previous) => ({ ...previous, loading: true, error: null }))
    fetchCanvasJob(jobId)
      .then((job) => {
        if (!cancelled) setState({ loading: false, job, missing: false, error: null })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof ApiRequestError && error.status === 404) {
          setState({ loading: false, job: null, missing: true, error: null })
          return
        }
        setState({
          loading: false,
          job: null,
          missing: false,
          error: error instanceof Error ? error.message : "无法读取任务状态",
        })
      })
    return () => {
      cancelled = true
    }
  }, [attempt, jobId, statusHint])

  return { ...state, refresh: () => setAttempt((value) => value + 1) }
}

export function CanvasRunTrace({
  title = "来源任务",
  jobId,
  snapshot,
  mediaKind,
  statusHint,
  onOpenJob,
}: {
  title?: string
  jobId: string | null | undefined
  snapshot: CanvasRunSnapshot | null
  mediaKind: CanvasMediaKind
  statusHint?: string | null
  onOpenJob: (jobId: string, kind?: CanvasMediaKind) => void
}) {
  const source = useCanvasSourceJob(jobId, statusHint)
  if (!jobId && !snapshot) return null
  const expired = source.job ? canvasJobOutputsExpired(source.job) : false

  return (
    <section className="canvas-inspector-section canvas-run-trace">
      <div className="canvas-panel-section-head">
        <h4 className="canvas-inspector-section-title">{title}</h4>
        {jobId ? (
          <Button
            size="small"
            type="text"
            icon={<RefreshCw size={13} />}
            loading={source.loading}
            onClick={source.refresh}
          >
            刷新状态
          </Button>
        ) : null}
      </div>

      {jobId ? (
        <div className="canvas-run-job-row">
          {source.loading ? (
            <Tag>核对中</Tag>
          ) : source.missing ? (
            <Tag color="warning">任务已删除</Tag>
          ) : source.job ? (
            <Tag color={canvasJobStatusColor(source.job.status)}>{canvasJobStatusLabel(source.job.status)}</Tag>
          ) : (
            <Tag color="warning">无法核对</Tag>
          )}
          <Typography.Text code copyable={{ text: jobId }} ellipsis>{jobId}</Typography.Text>
        </div>
      ) : (
        <p className="canvas-inspector-empty">未关联生成任务</p>
      )}

      {source.missing ? (
        <Alert
          type="warning"
          showIcon
          title="来源任务已删除"
          description="任务记录已从服务器删除，画布上的结果仍会保留；生成参数无法再从任务回读。"
        />
      ) : null}
      {expired ? (
        <Alert
          type="warning"
          showIcon
          title="结果产物已过期"
          description="任务记录仍在，但服务器上的结果产物已过期或仅临时保留，重新下载或作为参考图提交可能失败。"
        />
      ) : null}
      {source.error ? (
        <Alert
          type="warning"
          showIcon
          title="无法核对来源任务"
          description={source.error}
          action={<Button size="small" onClick={source.refresh}>重试</Button>}
        />
      ) : null}

      {jobId ? (
        <div className="canvas-inspector-actions">
          <Button icon={<ExternalLink size={14} />} onClick={() => onOpenJob(jobId, mediaKind)}>
            在任务详情中打开
          </Button>
        </div>
      ) : null}

      {snapshot ? (
        <Collapse
          ghost
          size="small"
          className="canvas-run-snapshot"
          items={[{
            key: "run",
            label: `运行参数 · ${snapshot.workflowName}`,
            children: (
              <div className="canvas-run-snapshot-body">
                <dl className="canvas-inspector-meta">
                  <dt>工作流</dt>
                  <dd>{snapshot.workflowName}</dd>
                  <dt>提交时间</dt>
                  <dd>{snapshot.submittedAt ? formatCanvasTime(new Date(snapshot.submittedAt).toISOString()) : "未知"}</dd>
                  <dt>参考图</dt>
                  <dd>{snapshot.referenceCount} 张</dd>
                  <dt>创作参数</dt>
                  <dd>{snapshot.parameterSummary.length ? snapshot.parameterSummary.join(" · ") : "默认参数"}</dd>
                </dl>
                <div className="canvas-inspector-field">
                  <span className="canvas-inspector-field-label">提交时提示词</span>
                  <div className="canvas-run-prompt">{snapshot.prompt || "（无提示词）"}</div>
                </div>
                {Object.keys(snapshot.optionValues).length ? (
                  <div className="canvas-inspector-field">
                    <span className="canvas-inspector-field-label">提交参数（原样）</span>
                    <div className="canvas-run-options">
                      {Object.entries(snapshot.optionValues).map(([name, value]) => (
                        <span key={name}>
                          <code>{name}</code>
                          {String(value)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ),
          }]}
        />
      ) : null}

      {!snapshot && jobId ? (
        <p className="canvas-inspector-hint">该结果由旧版本画布创建，未保存提交时的参数快照。</p>
      ) : null}
    </section>
  )
}
