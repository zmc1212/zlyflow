import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Alert, Button, Card, Col, Empty, Input, InputNumber, Popconfirm, Progress, Row, Segmented,
  Slider, Space, Switch, Tag, Typography, Upload, message,
} from "antd"
import { ArrowLeft, Film, Play, RefreshCw, Upload as UploadIcon, Wand2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import ThemeToggle from "../components/ThemeToggle"
import JobErrorNotice from "./components/JobErrorNotice"
import { DirectorMobileHeader } from "./DirectorMobileChrome"
import {
  getDirectorProject, createReplicationOperation, updateDirectorProjectRecord,
  uploadReplicationSourceVideo,
} from "./director-api"
import { requestJson } from "../api"
import { isReplicationPayload, normalizeReplicationPayload, REPLICATION_SHOT_STATUS_LABEL } from "./replication-model"
import type { ReplicationPayload, ReplicationShot } from "./replication-model"
import { streamDirectorOperationEvents } from "./director-operation-stream"
import { jobProgressFromJob, jobVideoUrl, shotStatusFromJob } from "./director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"

type JobLike = {
  id: string
  status?: string
  progress?: number
  error?: string | null
  outputs?: Array<{ kind?: string; download_url?: string; path?: string }>
}

const ANALYZE_HINT = "拉片会把参考片按镜头切分，逐镜反推英文提示词并提取深度视频；随后可用 Wan VACE 保留原片运镜与构图，重塑画面内容。"

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds * 10) / 10)
  const minutes = Math.floor(total / 60)
  const rest = total - minutes * 60
  return minutes > 0 ? `${minutes}分${rest.toFixed(1)}秒` : `${rest.toFixed(1)}秒`
}

function mergeShotWithJob(shot: ReplicationShot, job: JobLike | undefined): ReplicationShot {
  if (!job) return shot
  const status = shotStatusFromJob(job)
  const take = shot.takes.length ? shot.takes[shot.takes.length - 1] : null
  return {
    ...shot,
    status: status === "running" || status === "queued" || status === "succeeded" || status === "failed" ? status : shot.status,
    progress: jobProgressFromJob(job, shot.progress),
    error: job.error || shot.error,
    takes: take ? [
      ...shot.takes.slice(0, -1),
      { ...take, videoUrl: jobVideoUrl(job) || take.videoUrl, progress: jobProgressFromJob(job, take.progress) },
    ] : shot.takes,
  }
}

interface DirectorReplicationStudioProps {
  projectId: string
  csrfToken: string
  allJobs: JobLike[]
  onBack: () => void
  onExitDirector?: () => void
}

export default function DirectorReplicationStudio({
  projectId, csrfToken, allJobs, onBack, onExitDirector,
}: DirectorReplicationStudioProps) {
  const queryClient = useQueryClient()
  const [payload, setPayload] = useState<ReplicationPayload>(() => normalizeReplicationPayload(null))
  const [revision, setRevision] = useState(1)
  const [operationId, setOperationId] = useState<string | null>(null)
  const [statusLine, setStatusLine] = useState<{ progress: number; message?: string } | null>(null)
  const [starting, setStarting] = useState(false)
  const [depthPreviewId, setDepthPreviewId] = useState<string | null>(null)
  const saveTimerRef = useRef<number | null>(null)
  const dirtyRef = useRef(false)
  const revisionRef = useRef(1)

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: operationId ? 1500 : false,
  })
  const llmStatusQuery = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => requestJson<{
      available: boolean
      supports_vision: boolean
      model?: string | null
      analysis_vision?: { available?: boolean; model?: string | null }
    }>("/api/llm/status"),
    staleTime: 60_000,
  })

  useEffect(() => {
    const row = projectQuery.data
    if (!row) return
    if (isReplicationPayload(row.payload)) {
      setPayload(normalizeReplicationPayload(row.payload))
      revisionRef.current = row.content_revision
      setRevision(row.content_revision)
    }
  }, [projectQuery.data])

  // 操作结束后做一次最终刷新，保证拉片产物完整落地。
  useEffect(() => {
    if (!operationId || !projectQuery.isSuccess) return
    const opStatus = statusLine?.progress === 100 ? "done" : null
    if (opStatus === "done") void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
  }, [operationId, projectQuery.isSuccess, queryClient, projectId, statusLine?.progress])

  // 订阅操作事件流，直播分析进度。
  useEffect(() => {
    if (!operationId) return
    const controller = new AbortController()
    let cancelled = false
    void streamDirectorOperationEvents(operationId, (event) => {
      if (event.event === "status") {
        setStatusLine({ progress: event.data.progress ?? 0, message: event.data.message })
      } else if (event.event === "done") {
        setStatusLine({ progress: 100, message: "操作完成" })
        void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      } else if (event.event === "cancelled" || event.event === "error") {
        setStatusLine((current) => ({ progress: current?.progress ?? 0, message: event.data.message || "操作失败" }))
        void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      }
    }, { signal: controller.signal, shouldContinue: () => !cancelled })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [operationId, queryClient, projectId])

  async function persist(current: ReplicationPayload): Promise<boolean> {
    try {
      const saved = await updateDirectorProjectRecord(projectId, { payload: current }, csrfToken)
      revisionRef.current = saved.content_revision
      setRevision(saved.content_revision)
      return true
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败，请刷新后重试")
      return false
    }
  }

  function queueSave(updater: (current: ReplicationPayload) => ReplicationPayload) {
    dirtyRef.current = true
    setPayload((current) => {
      const next = updater(current)
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = window.setTimeout(() => {
        if (!dirtyRef.current) return
        dirtyRef.current = false
        void persist(next)
      }, 800)
      return next
    })
  }

  const analysis = payload.analysis
  const settings = payload.renderSettings
  const shots = useMemo(
    () => payload.shots.map((shot) => mergeShotWithJob(shot, allJobs.find((entry) => entry.id === shot.jobId))),
    [payload.shots, allJobs],
  )
  const readyShots = shots.filter((shot) => shot.promptText.trim())
  const hasSource = Boolean(payload.sourceVideo?.url)
  const analyzing = analysis.status === "running" || Boolean(operationId)

  async function customUpload(options: {
    file: unknown
    onSuccess?: (body?: unknown) => void
    onError?: (error: Error) => void
  }) {
    const file = options.file as File
    try {
      const row = await uploadReplicationSourceVideo(projectId, { file }, csrfToken)
      if (isReplicationPayload(row.payload)) {
        setPayload(normalizeReplicationPayload(row.payload))
        revisionRef.current = row.content_revision
        setRevision(row.content_revision)
      }
      options.onSuccess?.()
      message.success("参考片已上传，可以开始拉片")
    } catch (error) {
      options.onError?.(error instanceof Error ? error : new Error("上传失败"))
      message.error(error instanceof Error ? error.message : "上传参考片失败")
    }
  }

  async function startAnalysis() {
    setStarting(true)
    try {
      if (dirtyRef.current) {
        dirtyRef.current = false
        if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
        if (!(await persist(payload))) return
      }
      const operation = await createReplicationOperation(projectId, {
        kind: "analyze_reference_video",
        analysis_mode: analysis.mode,
        segment_seconds: analysis.segmentSeconds,
        scene_threshold: analysis.sceneThreshold,
      }, csrfToken)
      setOperationId(operation.id)
      setStatusLine({ progress: operation.progress, message: "正在准备拉片…" })
      message.info("拉片已开始：切分镜头 → 提取深度 → 逐镜反推提示词")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "拉片启动失败")
    } finally {
      setStarting(false)
    }
  }

  async function startReplication(shotIds?: string[]) {
    const ids = shotIds ?? readyShots.map((shot) => shot.id)
    if (!ids.length) {
      message.warning("没有可转绘的镜头：请先填写镜头提示词")
      return
    }
    setStarting(true)
    try {
      if (dirtyRef.current) {
        dirtyRef.current = false
        if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
        if (!(await persist(payload))) return
      }
      const operation = await createReplicationOperation(projectId, {
        kind: "replicate_shots",
        shot_ids: ids,
      }, csrfToken)
      setOperationId(operation.id)
      setStatusLine({ progress: operation.progress, message: `已提交 ${ids.length} 个复刻任务` })
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(`已提交 ${ids.length} 个镜头进入复刻队列`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "转绘提交失败")
    } finally {
      setStarting(false)
    }
  }

  const mobileTitle = payload.title || "参考片复刻"

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden flex-col">
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[{ key: "studio", label: "创作工作台", onClick: onExitDirector }]}
      />
      <header className="director-topbar">
        <button type="button" className="director-back-library" onClick={onBack}><ArrowLeft size={16} />返回</button>
        <div className="director-project-heading">
          <Typography.Title level={4} style={{ margin: 0 }}>参考片复刻</Typography.Title>
        </div>
        <Space>
          <ThemeToggle />
          <Button onClick={onExitDirector}>创作工作台</Button>
        </Space>
      </header>

      <div className="director-batch-scroll">
        <div className="replication-layout">
          <div className="replication-side">
            <Card title="参考片" size="small">
              {!hasSource ? (
                <Upload.Dragger
                  accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                  showUploadList={false}
                  customRequest={(options) => { void customUpload(options) }}
                >
                  <p className="ant-upload-drag-icon"><UploadIcon size={28} /></p>
                  <p className="ant-upload-text">点击或拖入参考片</p>
                  <p className="ant-upload-hint">支持 mp4 / mov / webm，最大 2GB。仅用于分镜学习与参考复刻，发布合规责任由使用者承担。</p>
                </Upload.Dragger>
              ) : (
                <div className="replication-source">
                  <video src={payload.sourceVideo!.url!} controls playsInline className="director-shot-video" />
                  <p className="replication-note">
                    {payload.sourceVideo!.width}×{payload.sourceVideo!.height}
                    {" · "}{formatTime(payload.sourceVideo!.durationSec)}
                    {" · "}{payload.shots.length} 镜
                  </p>
                  <Upload
                    accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                    showUploadList={false}
                    customRequest={(options) => { void customUpload(options) }}
                  >
                    <Button size="small" icon={<RefreshCw size={13} />}>更换参考片</Button>
                  </Upload>
                </div>
              )}
            </Card>

            <Card title="拉片设置" size="small">
              <Space direction="vertical" style={{ width: "100%" }} size={10}>
                <Segmented
                  value={analysis.mode}
                  disabled={analyzing}
                  onChange={(value) => queueSave((current) => ({
                    ...current,
                    analysis: { ...current.analysis, mode: value as "smart" | "fixed" },
                  }))}
                  options={[
                    { label: "智能分镜", value: "smart" },
                    { label: "固定分段", value: "fixed" },
                  ]}
                />
                {analysis.mode === "fixed" ? (
                  <label className="replication-field">
                    每段秒数
                    <InputNumber
                      min={3}
                      max={30}
                      value={analysis.segmentSeconds}
                      disabled={analyzing}
                      onChange={(value) => queueSave((current) => ({
                        ...current,
                        analysis: { ...current.analysis, segmentSeconds: Number(value) || 15 },
                      }))}
                    />
                  </label>
                ) : (
                  <label className="replication-field">
                    切镜灵敏度 {analysis.sceneThreshold.toFixed(2)}
                    <Slider
                      min={0.1}
                      max={0.8}
                      step={0.05}
                      value={analysis.sceneThreshold}
                      disabled={analyzing}
                      onChange={(value) => queueSave((current) => ({
                        ...current,
                        analysis: { ...current.analysis, sceneThreshold: value },
                      }))}
                    />
                  </label>
                )}
                <label className="replication-field">
                  目标风格（可选）
                  <Input
                    placeholder="例如：吉卜力动画 / 赛博朋克 / 水墨"
                    value={settings.artStyle}
                    onChange={(event) => queueSave((current) => ({
                      ...current,
                      renderSettings: { ...current.renderSettings, artStyle: event.target.value },
                    }))}
                  />
                </label>
                <label className="replication-field">
                  深度控制强度 {settings.vaceStrength.toFixed(2)}
                  <Slider
                    min={0.1}
                    max={1}
                    step={0.05}
                    value={settings.vaceStrength}
                    onChange={(value) => queueSave((current) => ({
                      ...current,
                      renderSettings: { ...current.renderSettings, vaceStrength: value },
                    }))}
                  />
                </label>
                <label className="replication-field">
                  采样步数
                  <InputNumber
                    min={4}
                    max={60}
                    value={settings.steps}
                    onChange={(value) => queueSave((current) => ({
                      ...current,
                      renderSettings: { ...current.renderSettings, steps: Number(value) || 30 },
                    }))}
                  />
                </label>
                <Button
                  type="primary"
                  icon={<Wand2 size={15} />}
                  disabled={!hasSource}
                  loading={starting || analyzing}
                  onClick={() => { void startAnalysis() }}
                >
                  {payload.shots.length ? "重新拉片" : "开始拉片"}
                </Button>
                <p className="replication-note">{ANALYZE_HINT}</p>
                {analyzing && statusLine ? (
                  <div className="replication-progress">
                    <Progress
                      percent={Math.max(0, Math.min(100, Math.round(statusLine.progress)))}
                      size="small"
                      showInfo={false}
                    />
                    <Typography.Text type="secondary">{statusLine.message || "处理中…"}</Typography.Text>
                  </div>
                ) : null}
                {analysis.status === "failed" && analysis.error ? (
                  <Alert type="error" showIcon message="拉片失败" description={analysis.error} />
                ) : null}
                {!analyzing && llmStatusQuery.data && !(llmStatusQuery.data.analysis_vision?.available ?? llmStatusQuery.data.supports_vision) ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="未检测到视觉模型"
                    description="尚未启用独立视觉模型，拉片仍可切分镜头与提取深度，但提示词需要手动填写。请到管理设置 → VLM 视觉模型 配置带 VL 的模型。"
                  />
                ) : null}
              </Space>
            </Card>
          </div>

          <div className="replication-list">
            <div className="replication-toolbar">
              <Typography.Text type="secondary">
                {shots.length ? `${shots.length} 镜 · ${readyShots.length} 镜可转绘` : "拉片完成后这里会展示逐镜结果"}
              </Typography.Text>
              <Button
                type="primary"
                size="small"
                disabled={!readyShots.length}
                loading={starting}
                onClick={() => { void startReplication() }}
              >
                批量转绘（{readyShots.length}）
              </Button>
            </div>
            {!shots.length && !analyzing ? (
              <Card className="replication-empty">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={<span className="replication-note">上传参考片并点击「开始拉片」，AI 会逐镜给出提示词与深度视频。</span>}
                />
              </Card>
            ) : null}
            {shots.map((shot) => {
              const latestTake = shot.takes.length ? shot.takes[shot.takes.length - 1] : null
              const replicatedUrl = latestTake?.videoUrl || null
              const failed = isDirectorFailedStatus(shot.status)
              return (
                <Card
                  key={shot.id}
                  className="director-shot-card"
                  title={`镜头 ${shot.shotNumber} · ${formatTime(shot.timeStart)} – ${formatTime(shot.timeEnd)}`}
                  extra={<Tag color={directorStatusColor(shot.status)}>{REPLICATION_SHOT_STATUS_LABEL[shot.status] || directorStatusLabel(shot.status)}</Tag>}
                >
                  <Row gutter={12}>
                    <Col xs={24} md={12}>
                      <p className="director-shot-desc">原片片段</p>
                      {shot.segmentUrl ? (
                        <video src={shot.segmentUrl} controls playsInline className="director-shot-video" />
                      ) : (
                        <p className="replication-note">片段生成中…</p>
                      )}
                      {shot.depthUrl ? (
                        depthPreviewId === shot.id ? (
                          <video src={shot.depthUrl} controls playsInline className="director-shot-video" />
                        ) : (
                          <Button size="small" icon={<Play size={13} />} onClick={() => setDepthPreviewId(shot.id)}>查看深度视频</Button>
                        )
                      ) : null}
                    </Col>
                    <Col xs={24} md={12}>
                      <p className="director-shot-desc">复刻成片</p>
                      {replicatedUrl ? (
                        <video src={replicatedUrl} controls playsInline className="director-shot-video" />
                      ) : (
                        <p className="replication-note">{shot.jobId ? `任务 ${shot.jobId}` : "尚未转绘"}</p>
                      )}
                      <JobErrorNotice error={shot.error} />
                    </Col>
                  </Row>
                  {shot.keyframeUrls.length ? (
                    <div className="replication-keyframes">
                      {shot.keyframeUrls.map((url) => (
                        <img key={url} src={url} alt={`镜头 ${shot.shotNumber} 关键帧`} />
                      ))}
                    </div>
                  ) : null}
                  <Input.TextArea
                    autoSize={{ minRows: 2, maxRows: 6 }}
                    placeholder="镜头提示词（英文 H3 散文；拉片后可人工修改）"
                    value={shot.promptText}
                    onChange={(event) => queueSave((current) => ({
                      ...current,
                      shots: current.shots.map((item) => (
                        item.id === shot.id ? { ...item, promptText: event.target.value } : item
                      )),
                    }))}
                  />
                  <div className="replication-shot-actions">
                    <label className="replication-field is-inline">
                      <Switch
                        size="small"
                        checked={shot.keepFirstFrame}
                        onChange={(checked) => queueSave((current) => ({
                          ...current,
                          shots: current.shots.map((item) => (
                            item.id === shot.id ? { ...item, keepFirstFrame: checked } : item
                          )),
                        }))}
                      />
                      保留原片首帧
                    </label>
                    {failed ? (
                      <Popconfirm
                        title="重新提交这个镜头的转绘？"
                        okText="提交"
                        cancelText="取消"
                        onConfirm={() => { void startReplication([shot.id]) }}
                      >
                        <Button size="small" icon={<RefreshCw size={13} />}>重试这一镜</Button>
                      </Popconfirm>
                    ) : null}
                    <Button
                      size="small"
                      disabled={!shot.promptText.trim()}
                      onClick={() => { void startReplication([shot.id]) }}
                    >
                      仅转绘此镜
                    </Button>
                  </div>
                  {shot.cameraNote ? (
                    <p className="replication-note">运镜：{shot.cameraNote}</p>
                  ) : null}
                  {shot.analysisNote ? (
                    <p className="director-shot-desc">{shot.analysisNote}</p>
                  ) : null}
                </Card>
              )
            })}
          </div>
        </div>
      </div>
      <div className="replication-footer">
        <Film size={14} />
        <span>本地 Wan2.1 VACE 1.3B 深度复刻 · 任务与创作台共用同一执行队列</span>
      </div>
    </div>
  )
}
