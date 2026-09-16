// 全部任务面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/JobsCenterPane.vue
// Vue → React 对应：ref→useState、onMounted/onUnmounted→useEffect（1 秒静默轮询与清理保留）；
// a-table bodyCell 自定义渲染 → columns render；a-* 组件 → antd 同名组件；
// 写操作（重试）首参补 csrfToken；轮询经最新闭包 trampoline 读取最新 props/state（等价 Vue 响应式读取）。
import { useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Modal, Progress, Space, Table, Tabs, Tag, message } from "antd"
import type { TableProps } from "antd"
import { RefreshCw, ExternalLink, Copy } from "lucide-react"
import { listJobs, retryJob, type Director2Job } from "../api"
import {
  DIRECTOR2_DEFAULT_JOB_TYPE,
  DIRECTOR2_JOB_TYPES,
  countJobsByType,
  defaultJobTypeTab,
  director2JobTypeLabel,
  filterJobsByType,
  h3PromptResultText,
  isH3PromptJob,
  videoShotPromptText,
  type Director2JobType,
} from "../director2-job-types"
import { useMediaPreview } from "../media-preview"
import "./jobs-center.css"

interface JobsCenterPaneProps {
  csrfToken: string
  projectId: string
}

// 视频任务镜头 payload（原版为 JS 未标注，按模板取值字段补全）
type VideoShotPayload = {
  beat_id?: string
  sequence?: number
  heading?: string
  scene?: string
  reference_urls?: string[]
  prompt?: string
  h3_prompt?: string
  character_references?: Array<{ character_name?: string; look_id?: string }>
}

// LLM 提示词生成尝试记录 payload
type LlmAttemptPayload = {
  beat_id?: string
  attempt?: number
  sequence?: number
  status?: string
  errors?: string[]
  raw_response?: string
}

type StatusTag = { color: string; text: string }

export default function JobsCenterPane({ csrfToken, projectId }: JobsCenterPaneProps) {
  const { openMediaPreview } = useMediaPreview()
  const [jobs, setJobs] = useState<Director2Job[]>([])
  const [loading, setLoading] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedJob, setSelectedJob] = useState<Director2Job | null>(null)
  const [activeJobType, setActiveJobType] = useState<Director2JobType>(DIRECTOR2_DEFAULT_JOB_TYPE)
  const [page, setPage] = useState(1)
  const hasInitializedTab = useRef(false)

  // 与 Vue 实例级可变量（selectedJob）对应的同步 ref，供异步续体（fetchJobs 轮询）读取最新值
  const selectedJobRef = useRef<Director2Job | null>(null)

  function applySelectedJob(job: Director2Job | null) {
    selectedJobRef.current = job
    setSelectedJob(job)
  }

  const typeCounts = useMemo(() => countJobsByType(jobs), [jobs])
  const filteredJobs = useMemo(() => filterJobsByType(jobs, activeJobType), [jobs, activeJobType])

  const columns: TableProps<Director2Job>["columns"] = [
    {
      title: "任务名称 / ID",
      key: "title",
      width: 280,
      render: (_, record) => (
        <div className="job-title-cell">
          <span className="job-name">{record.title}</span>
          <span className="job-id">{record.id}</span>
        </div>
      ),
    },
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_, record) => (
        <Tag color={getStatusTag(record.status).color}>{getStatusTag(record.status).text}</Tag>
      ),
    },
    {
      title: "进度",
      key: "progress",
      width: 180,
      render: (_, record) => (
        <Progress
          percent={record.progress}
          size="small"
          status={record.status === "failed" ? "exception" : record.progress === 100 ? "success" : "active"}
        />
      ),
    },
    {
      title: "结果",
      key: "result",
      width: 80,
      render: (_, record) =>
        record.result_url ? (
          <button
            type="button"
            className="result-thumb-btn"
            aria-label="预览结果"
            onClick={() => openMediaPreview({
              src: record.result_url,
              kind: record.job_type === "video_generation" ? "video" : "image",
              title: record.title || "生成结果",
            })}
          >
            {record.job_type === "video_generation" ? (
              <video src={record.result_url} className="result-thumb" muted preload="metadata" />
            ) : (
              <img src={record.result_url} className="result-thumb" alt="结果图" />
            )}
          </button>
        ) : isH3PromptJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
          <Tag color="cyan">提示词就绪</Tag>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    { title: "创建时间", dataIndex: "created_at", width: 160 },
    {
      title: "操作",
      key: "action",
      width: 140,
      render: (_, record) => (
        <Space>
          <Button size="small" type="primary" ghost onClick={() => openDetail(record)}>
            查看详情
          </Button>
          {record.status === "failed" ? (
            <Button size="small" type="link" onClick={() => handleRetry(record.id)}>
              重试
            </Button>
          ) : null}
        </Space>
      ),
    },
  ]

  function getStatusTag(s: string): StatusTag {
    const map: Record<string, StatusTag> = {
      queued: { color: "default", text: "排队中" },
      preparing: { color: "processing", text: "准备数据" },
      prompt_generation: { color: "processing", text: "生成提示词" },
      uploading: { color: "processing", text: "上传素材" },
      comfy_queued: { color: "cyan", text: "ComfyUI 排队" },
      running: { color: "processing", text: "执行中" },
      succeeded: { color: "green", text: "已完成" },
      completed: { color: "green", text: "已完成" },
      failed: { color: "red", text: "失败" },
    }
    return map[s] || { color: "default", text: s }
  }

  function getJobTypeText(type: string): string {
    return director2JobTypeLabel(type)
  }

  function handleJobTypeChange(key: string) {
    setActiveJobType(key as Director2JobType)
    setPage(1)
  }

  function isVideoJob(job: Director2Job | null): boolean {
    return job?.job_type === "video_generation"
  }

  function copyH3Prompt(text: string) {
    if (!text) return
    navigator.clipboard.writeText(text)
      .then(() => message.success("H3 提示词已复制到剪贴板"))
      .catch(() => message.error("复制失败"))
  }

  function videoShots(job: Director2Job): VideoShotPayload[] {
    const shots = job?.payload?.shots?.length ? job.payload.shots : job?.payload?.source_shots
    return (Array.isArray(shots) ? shots : []) as VideoShotPayload[]
  }

  function llmAttempts(job: Director2Job): LlmAttemptPayload[] {
    return (Array.isArray(job?.payload?.llm_attempts) ? job.payload.llm_attempts : []) as LlmAttemptPayload[]
  }

  function videoReferenceLabel(shot: VideoShotPayload, index: number): string {
    const characters = Array.isArray(shot?.character_references) ? shot.character_references : []
    if (index < characters.length) {
      const character = characters[index]
      return `${character.character_name || "角色"}造型${character.look_id ? ` (${character.look_id})` : ""}`
    }
    return "场景"
  }

  function referenceUrls(job: Director2Job): string[] {
    const p = job?.payload || {}
    const list = p.reference_urls || p.request_body?.images || p.images || []
    return ((Array.isArray(list) ? list : []) as unknown[]).filter(
      (u): u is string => typeof u === "string" && /^https?:\/\//.test(u) && !u.startsWith("data:"),
    )
  }

  function formatRequestBody(job: Director2Job): string {
    const p = job?.payload || {}
    const refs = referenceUrls(job)
    const body =
      p.request_body && typeof p.request_body === "object"
        ? { ...p.request_body, images: refs.length ? refs : p.request_body.images || [] }
        : {
            model: p.model,
            prompt: p.clean_prompt || p.prompt,
            images: refs,
            aspectRatio: p.aspect_ratio,
            imageSize: p.image_size || "1K",
            replyType: p.reply_type || "async",
          }
    return JSON.stringify(body, null, 2)
  }

  function openDetail(job: Director2Job) {
    applySelectedJob(job)
    setDetailVisible(true)
  }

  async function fetchJobs(silent = false) {
    if (!silent) setLoading(true)
    try {
      const res = await listJobs(projectId)
      const list = res || []
      setJobs(list)
      if (!hasInitializedTab.current) {
        hasInitializedTab.current = true
        setActiveJobType(defaultJobTypeTab(list))
        setPage(1)
      }
      if (selectedJobRef.current) {
        const found = list.find((job) => job.id === selectedJobRef.current?.id) || selectedJobRef.current
        applySelectedJob(found)
      }
    } catch {
      if (!silent) message.error("加载任务列表失败")
    } finally {
      if (!silent) setLoading(false)
    }
  }

  async function handleRetry(id: string) {
    try {
      await retryJob(csrfToken, projectId, id)
      message.success("任务已重新启动")
      await fetchJobs()
    } catch {
      message.error("重试失败")
    }
  }

  // 最新闭包 trampoline：1 秒静默轮询读取最新渲染的 fetchJobs（等价 Vue 闭包读响应式值）
  const fetchJobsRef = useRef(fetchJobs)
  useEffect(() => {
    fetchJobsRef.current = fetchJobs
  })

  useEffect(() => {
    hasInitializedTab.current = false
    setActiveJobType(DIRECTOR2_DEFAULT_JOB_TYPE)
    setPage(1)
    fetchJobs()
    const pollTimer = window.setInterval(() => fetchJobsRef.current(true), 1000)
    return () => {
      window.clearInterval(pollTimer)
    }
    // 对应原版 onMounted + onUnmounted；projectId 变化时重新拉列表并重置默认 Tab
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  return (
    <div className="d2-jobs-center jobs-pane">
      <div className="sub-pane-header">
        <div>
          <h2 className="sub-pane-title">全部任务</h2>
          <p className="sub-pane-subtitle">
            监控项目下所有异步生图、大模型剧本分析、分镜渲染与视频合成任务的执行进度。
          </p>
        </div>

        <Button loading={loading} icon={<RefreshCw size={15} />} onClick={() => fetchJobs()}>
          刷新任务
        </Button>
      </div>

      {/* 按任务类型切换；无「全部」Tab */}
      <div className="jobs-table-card">
        <Tabs
          className="jobs-type-tabs"
          activeKey={activeJobType}
          onChange={handleJobTypeChange}
          items={DIRECTOR2_JOB_TYPES.map((type) => ({
            key: type,
            label: `${director2JobTypeLabel(type)} (${typeCounts[type]})`,
          }))}
        />
        <Table
          loading={loading}
          dataSource={filteredJobs}
          columns={columns}
          rowKey="id"
          pagination={{
            pageSize: 20,
            current: page,
            onChange: (nextPage) => setPage(nextPage),
          }}
          size="middle"
          locale={{ emptyText: `暂无${director2JobTypeLabel(activeJobType)}任务` }}
        />
      </div>

      {/* 任务详情弹窗 */}
      <Modal
        open={detailVisible}
        title="任务详情"
        width="860px"
        footer={null}
        destroyOnHidden
        onCancel={() => setDetailVisible(false)}
        className="d2-jobs-center"
      >
        {selectedJob ? (
          <div className="detail-modal-body">
            {/* 顶部状态栏 */}
            <div className="detail-status-bar">
              <div className="detail-title-block">
                <span className="detail-job-name">{selectedJob.title}</span>
                <Tag color={getStatusTag(selectedJob.status).color} style={{ marginLeft: 8 }}>
                  {getStatusTag(selectedJob.status).text}
                </Tag>
              </div>
              <span className="detail-job-id">{selectedJob.id}</span>
            </div>

            {/* 基本信息 */}
            <div className="detail-section">
              <div className="detail-section-title">📋 基本信息</div>
              <div className="detail-grid">
                <div className="detail-row">
                  <span className="detail-key">任务类型</span>
                  <span className="detail-val">
                    <Tag color="blue">{getJobTypeText(selectedJob.job_type)}</Tag>
                  </span>
                </div>
                <div className="detail-row">
                  <span className="detail-key">创建时间</span>
                  <span className="detail-val">{selectedJob.created_at}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-key">完成时间</span>
                  <span className="detail-val">{selectedJob.completed_at || selectedJob.updated_at}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-key">执行进度</span>
                  <span className="detail-val">
                    <Progress percent={selectedJob.progress} size="small" style={{ width: 200 }} />
                  </span>
                </div>
              </div>
            </div>

            {isVideoJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title">视频生成参数</div>
                <div className="detail-grid">
                  <div className="detail-row">
                    <span className="detail-key">分集</span>
                    <span className="detail-val">
                      第 {selectedJob.payload?.episode_number} 集 · {selectedJob.payload?.episode_title}
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">生成规格</span>
                    <span className="detail-val">
                      {selectedJob.payload?.shot_count} 镜 × 8 秒 · {selectedJob.payload?.total_duration_seconds} 秒 ·{" "}
                      {selectedJob.payload?.fps} fps
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">输出分辨率</span>
                    <span className="detail-val">
                      {selectedJob.payload?.width} × {selectedJob.payload?.height} px
                      {selectedJob.payload?.quality ? ` · ${selectedJob.payload.quality} MP` : ""}
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">画面比例</span>
                    <span className="detail-val">{selectedJob.payload?.aspect_ratio || "16:9"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">生成质量</span>
                    <span className="detail-val">
                      {selectedJob.payload?.steps || "—"} 步
                      {selectedJob.payload?.weight_profile === "full" ? " · 完整权重" : " · 精简权重"}
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">音频模式</span>
                    <span className="detail-val">{selectedJob.payload?.audio_mode}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">Comfy Prompt</span>
                    <span className="detail-val mono">{selectedJob.payload?.prompt_id || "尚未提交"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">队列序号</span>
                    <span className="detail-val">{selectedJob.payload?.queue_number ?? "—"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">当前阶段</span>
                    <span className="detail-val">{selectedJob.payload?.runtime_stage || selectedJob.status}</span>
                  </div>
                </div>
              </div>
            ) : null}

            {isVideoJob(selectedJob) && videoShots(selectedJob).length ? (
              <div className="detail-section">
                <div className="detail-section-title">镜头参考图与 H3 提示词</div>
                {selectedJob.payload?.prompt_source === "workshop_material" ? (
                  <div className="text-muted">复用剧集工坊已保存的 H3 提示词</div>
                ) : selectedJob.payload?.prompt_source === "configured_llm" ? (
                  <div className="text-muted">任务内重新生成（工坊提示词未通过出片校验）</div>
                ) : null}
                <div className="video-shot-list">
                  {videoShots(selectedJob).map((shot) => {
                    const promptText = videoShotPromptText(shot)
                    return (
                    <section key={shot.beat_id} className="video-shot-item">
                      <div className="video-shot-head">
                        Beat {shot.sequence} · {shot.heading || shot.scene}
                      </div>
                      <div className="video-ref-grid">
                        {(shot.reference_urls || []).map((url, idx) => (
                          <div key={url} className="video-ref-item">
                            <button
                              type="button"
                              className="preview-media-btn"
                              onClick={() => openMediaPreview({
                                src: url,
                                title: `Picture ${idx + 1} · ${videoReferenceLabel(shot, idx)}`,
                              })}
                            >
                              <img src={url} alt={`Picture ${idx + 1}`} />
                            </button>
                            <span>
                              Picture {idx + 1} · {videoReferenceLabel(shot, idx)}
                            </span>
                          </div>
                        ))}
                      </div>
                      {promptText ? (
                        <div className="prompt-block">
                          <div className="prompt-label">MiniMax H3 Ref2VA Prompt</div>
                          <pre className="prompt-text">{promptText}</pre>
                        </div>
                      ) : (
                        <div className="text-muted">提示词尚未生成</div>
                      )}
                    </section>
                    )
                  })}
                </div>
              </div>
            ) : null}

            {isVideoJob(selectedJob) && llmAttempts(selectedJob).length ? (
              <div className="detail-section">
                <div className="detail-section-title">LLM 提示词生成记录</div>
                <div className="attempt-list">
                  {llmAttempts(selectedJob).map((attempt, idx) => (
                    <details key={`${attempt.beat_id}-${attempt.attempt}-${idx}`} className="attempt-item">
                      <summary>
                        Beat {attempt.sequence} · 第 {attempt.attempt} 次
                        <Tag color={attempt.status === "passed" ? "green" : "red"}>
                          {attempt.status === "passed" ? "通过" : "失败"}
                        </Tag>
                      </summary>
                      {attempt.errors?.length ? (
                        <div className="attempt-errors">{attempt.errors.join("\n")}</div>
                      ) : null}
                      <pre className="prompt-text">{attempt.raw_response || "无原始响应"}</pre>
                    </details>
                  ))}
                </div>
              </div>
            ) : null}

            {isVideoJob(selectedJob) && selectedJob.payload?.director_report ? (
              <div className="detail-section">
                <div className="detail-section-title">MiniMax H3 Director 报告</div>
                <div className="prompt-block">
                  <pre className="prompt-text">{selectedJob.payload.director_report}</pre>
                </div>
              </div>
            ) : null}

            {/* 调用参数 */}
            {!isVideoJob(selectedJob) && selectedJob.payload && Object.keys(selectedJob.payload).length ? (
              <div className="detail-section">
                <div className="detail-section-title">⚙️ 调用参数</div>
                <div className="detail-grid">
                  <div className="detail-row">
                    <span className="detail-key">调用模型</span>
                    <span className="detail-val model-tag">{selectedJob.payload.model || "—"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">API 接口</span>
                    <span className="detail-val mono">{selectedJob.payload.api_endpoint || "—"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">目标类型</span>
                    <span className="detail-val">
                      <Tag>{selectedJob.payload.target_type || "—"}</Tag>
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">宽高比</span>
                    <span className="detail-val">{selectedJob.payload.aspect_ratio || "—"}</span>
                  </div>
                  {selectedJob.payload.image_size ? (
                    <div className="detail-row">
                      <span className="detail-key">imageSize</span>
                      <span className="detail-val">{selectedJob.payload.image_size}</span>
                    </div>
                  ) : null}
                  <div className="detail-row">
                    <span className="detail-key">replyType</span>
                    <span className="detail-val">
                      {selectedJob.payload.reply_type || selectedJob.payload.request_body?.replyType || "async"}
                    </span>
                  </div>
                  {selectedJob.payload.visual_style ? (
                    <div className="detail-row">
                      <span className="detail-key">画风 visual_style</span>
                      <span className="detail-val">{selectedJob.payload.visual_style}</span>
                    </div>
                  ) : null}
                  {selectedJob.payload.art_style_id ? (
                    <div className="detail-row">
                      <span className="detail-key">art_style_id</span>
                      <span className="detail-val">{selectedJob.payload.art_style_id}</span>
                    </div>
                  ) : null}
                  {selectedJob.payload.ethnicity ? (
                    <div className="detail-row">
                      <span className="detail-key">族裔</span>
                      <span className="detail-val">{selectedJob.payload.ethnicity}</span>
                    </div>
                  ) : null}
                  <div className="detail-row">
                    <span className="detail-key">输出分辨率</span>
                    <span className="detail-val">
                      {selectedJob.payload.width || "—"} × {selectedJob.payload.height || "—"} px
                    </span>
                  </div>
                  {selectedJob.payload.asset_name ? (
                    <div className="detail-row">
                      <span className="detail-key">关联资产</span>
                      <span className="detail-val">
                        {selectedJob.payload.asset_name}{" "}
                        <span className="text-muted">{selectedJob.payload.asset_id}</span>
                      </span>
                    </div>
                  ) : null}
                  {selectedJob.payload.identity_id ? (
                    <div className="detail-row">
                      <span className="detail-key">造型 ID</span>
                      <span className="detail-val mono">{selectedJob.payload.identity_id}</span>
                    </div>
                  ) : null}
                  <div className="detail-row">
                    <span className="detail-key">参考图数量</span>
                    <span className="detail-val">{referenceUrls(selectedJob).length}</span>
                  </div>
                </div>
              </div>
            ) : null}

            {/* 参考图 */}
            {!isVideoJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title">🖼 传入参考图 (images)</div>
                {referenceUrls(selectedJob).length ? (
                  <div className="ref-grid">
                    {referenceUrls(selectedJob).map((url, idx) => (
                      <div key={url + idx} className="ref-item">
                        <button
                          type="button"
                          className="preview-media-btn"
                          onClick={() => openMediaPreview({
                            src: url,
                            title: `参考图 ${idx + 1}`,
                            description: idx === 0 && selectedJob.payload?.identity_anchor ? "身份锚点" : undefined,
                          })}
                        >
                          <img src={url} className="ref-thumb" alt={`参考图 ${idx + 1}`} />
                        </button>
                        <div className="ref-meta">
                          <span className="prompt-label">
                            REFERENCE {idx + 1}
                            {idx === 0 && selectedJob.payload?.identity_anchor ? " · 身份锚点" : ""}
                          </span>
                          <span className="url-link">{url}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted ref-empty">
                    本次请求未传入参考图（images 为空）。造型图应对齐 source1，把头像作为 REFERENCE 1。
                  </div>
                )}
              </div>
            ) : null}

            {isH3PromptJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title is-split">
                  <span>🎬 生成的 MiniMax H3 视频生成提示词</span>
                  {h3PromptResultText(selectedJob) ? (
                    <Button type="link" size="small" icon={<Copy size={13} />} onClick={() => copyH3Prompt(h3PromptResultText(selectedJob))}>
                      复制提示词
                    </Button>
                  ) : null}
                </div>
                {h3PromptResultText(selectedJob) ? (
                  <div className="prompt-block">
                    <pre className="prompt-text">{h3PromptResultText(selectedJob)}</pre>
                  </div>
                ) : (
                  <div className="text-muted">提示词尚未生成</div>
                )}
              </div>
            ) : null}

            {/* Prompt */}
            {!isH3PromptJob(selectedJob) && (selectedJob.payload?.prompt || selectedJob.payload?.clean_prompt) ? (
              <div className="detail-section">
                <div className="detail-section-title">✍️ 生图提示词 (Prompt)</div>
                {selectedJob.payload?.prompt ? (
                  <div className="prompt-block">
                    <div className="prompt-label">原始 Prompt</div>
                    <pre className="prompt-text">{selectedJob.payload.prompt}</pre>
                  </div>
                ) : null}
                {selectedJob.payload?.clean_prompt ? (
                  <div className="prompt-block" style={{ marginTop: 10 }}>
                    <div className="prompt-label">发送给 API 的完整 Prompt</div>
                    <pre className="prompt-text">{selectedJob.payload.clean_prompt}</pre>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* GRS 请求体 */}
            {!isVideoJob(selectedJob) && !isH3PromptJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title">📤 提交给 GRS 的完整参数</div>
                <div className="prompt-block">
                  <div className="prompt-label">POST /v1/api/generate JSON（images 为参考图 URL，实际上传为 data URI）</div>
                  <pre className="prompt-text">{formatRequestBody(selectedJob)}</pre>
                </div>
              </div>
            ) : null}

            {/* 完整请求 URL */}
            {selectedJob.payload?.api_url ? (
              <div className="detail-section">
                <div className="detail-section-title">🔗 完整请求 URL</div>
                <div className="url-block">
                  <a href={selectedJob.payload.api_url} target="_blank" className="url-link">
                    {selectedJob.payload.api_url}
                  </a>
                </div>
              </div>
            ) : null}

            {/* 结果图片 */}
            {selectedJob.result_url ? (
              <div className="detail-section">
                <div className="detail-section-title">🖼️ 生成结果</div>
                <div className="result-preview">
                  {isVideoJob(selectedJob) ? (
                    <video src={selectedJob.result_url} className="result-video" controls preload="metadata" />
                  ) : (
                    <img
                      src={selectedJob.result_url}
                      className="result-img"
                      alt="生成结果"
                      onClick={() => openMediaPreview({
                        src: selectedJob.result_url,
                        title: selectedJob.title || "生成结果",
                      })}
                    />
                  )}
                  <button
                    type="button"
                    className="result-open-link"
                    onClick={() => openMediaPreview({
                      src: selectedJob.result_url,
                      kind: isVideoJob(selectedJob) ? "video" : "image",
                      title: selectedJob.title || "生成结果",
                    })}
                  >
                    <ExternalLink size={13} /> 预览原文件
                  </button>
                </div>
              </div>
            ) : null}

            {/* 错误信息 */}
            {selectedJob.error_message ? (
              <div className="detail-section">
                <div className="detail-section-title">❌ 错误信息</div>
                <Alert type="error" showIcon message={selectedJob.error_message} />
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
