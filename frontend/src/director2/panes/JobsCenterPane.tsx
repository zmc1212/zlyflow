// 全部任务面板 —— 逐行复刻自 dev0914 z-admin/src/views/project/JobsCenterPane.vue
// Vue → React 对应：ref→useState、onMounted/onUnmounted→useEffect（静默轮询与清理保留）；
// a-table bodyCell 自定义渲染 → columns render；a-* 组件 → antd 同名组件；
// 写操作（重试）首参补 csrfToken；轮询经最新闭包 trampoline 读取最新 props/state（等价 Vue 响应式读取）。
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { Alert, Button, Collapse, Input, Modal, Progress, Segmented, Select, Space, Table, Tabs, Tag, Tooltip, message } from "antd"
import type { TableProps } from "antd"
import { RefreshCw, ExternalLink, Copy, ListChecks, Search } from "lucide-react"
import { director2ErrorDetail, confirmProjectVideoRefine, listJobs, retryJob, skipProjectVideoRefine, upscaleProjectVideoJob, type Director2Job } from "../api"
import {
  DIRECTOR2_DEFAULT_JOB_TYPE,
  DIRECTOR2_JOB_TYPES,
  countJobsByType,
  defaultJobTypeTab,
  director2JobTypeLabel,
  filterJobsByType,
  h3PromptResultText,
  isH3PromptJob,
  isShotPlanJob,
  isTtsJob,
  shotPlanDocumentId,
  videoShotPromptText,
  type Director2JobType,
} from "../director2-job-types"
import { director2ContentLibraryDocPath, director2WorkshopEpisodePath } from "../paths"
import { jobCanConfirmRefine, jobCanShowUpscaleAction, jobPreviewVideoUrl, jobRefineShotCount, jobSourceVideoUrl, jobUpscaleDisabledReason, jobUpscaleHint, jobUpscaledVideoUrl, smartClarifyConfirmText } from "../director2-video-settings"
import { useMediaPreview, type OpenMediaPreviewInput } from "../media-preview"
import MediaPreviewModal, { type MediaPreviewAction } from "../../components/MediaPreviewModal"
import "./jobs-center.css"

const ACTIVE_JOB_STATUSES = new Set([
  "queued", "pending", "preparing", "prompt_generation", "uploading", "comfy_queued", "running",
])
const ACTIVE_POLL_MS = 1000
const IDLE_POLL_MS = 5000
const HIDDEN_POLL_MS = 15000

function sameJobSummary(left: Director2Job, right: Director2Job): boolean {
  return left.status === right.status
    && left.progress === right.progress
    && left.updated_at === right.updated_at
    && left.result_url === right.result_url
    && left.error_message === right.error_message
}

function sameJobList(previous: Director2Job[], next: Director2Job[]): boolean {
  return previous.length === next.length
    && previous.every((job, index) => job.id === next[index].id && sameJobSummary(job, next[index]))
}

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
  const navigate = useNavigate()
  const { openMediaPreview, openMediaPreviewList } = useMediaPreview()
  const [jobs, setJobs] = useState<Director2Job[]>([])
  const [loading, setLoading] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedJob, setSelectedJob] = useState<Director2Job | null>(null)
  const [activeJobType, setActiveJobType] = useState<Director2JobType>(DIRECTOR2_DEFAULT_JOB_TYPE)
  const [page, setPage] = useState(1)
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [upscalingJobId, setUpscalingJobId] = useState<string | null>(null)
  const [refineAction, setRefineAction] = useState<{ jobId: string; action: "confirm" | "skip" } | null>(null)
  // 详情弹层复用视频预览弹窗时，右侧可在「成片 / 原片」之间切换
  const [detailVideoSource, setDetailVideoSource] = useState<"preview" | "source">("preview")
  const hasInitializedTab = useRef(false)
  const requestInFlight = useRef(false)
  const requestSequence = useRef(0)
  const activeProjectRef = useRef(projectId)
  const jobsRef = useRef<Director2Job[]>([])

  useEffect(() => {
    jobsRef.current = jobs
  }, [jobs])

  // 与 Vue 实例级可变量（selectedJob）对应的同步 ref，供异步续体（fetchJobs 轮询）读取最新值
  const selectedJobRef = useRef<Director2Job | null>(null)

  function applySelectedJob(job: Director2Job | null) {
    selectedJobRef.current = job
    setSelectedJob(job)
  }

  const typeCounts = useMemo(() => countJobsByType(jobs), [jobs])
  const typeJobs = useMemo(() => filterJobsByType(jobs, activeJobType), [jobs, activeJobType])
  const filteredJobs = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase()
    return typeJobs.filter((job) => {
      const matchesText = !query || `${job.title} ${job.id}`.toLocaleLowerCase().includes(query)
      const matchesStatus = statusFilter === "all"
        || (statusFilter === "active" && ["queued", "pending", "preparing", "prompt_generation", "uploading", "comfy_queued", "running"].includes(job.status))
        || (statusFilter === "completed" && ["completed", "succeeded"].includes(job.status))
        || (statusFilter === "cancelled" && ["cancelled", "canceled", "interrupted"].includes(job.status))
        || job.status === statusFilter
      return matchesText && matchesStatus
    })
  }, [typeJobs, searchQuery, statusFilter])
  const hasFilters = Boolean(searchQuery.trim()) || statusFilter !== "all"

  // 当前筛选列表里可预览的结果集合；预览层支持在其中切换上一个 / 下一个
  const openResultPreview = useCallback((record: Director2Job) => {
    const inputs: OpenMediaPreviewInput[] = []
    let startIndex = 0
    filteredJobs.forEach((job) => {
      const url = isVideoJob(job) ? jobPreviewVideoUrl(job) : isTtsJob(job) ? undefined : String(job.result_url || "").trim() || undefined
      if (!url) return
      if (job.id === record.id) startIndex = inputs.length
      const upscaled = isVideoJob(job) && Boolean(jobUpscaledVideoUrl(job))
      inputs.push({
        src: url,
        kind: isVideoJob(job) ? "video" : "image",
        title: upscaled ? `${job.title || "生成结果"} · 超清` : job.title || "生成结果",
      })
    })
    if (!inputs.length) return
    openMediaPreviewList(inputs, startIndex)
  }, [filteredJobs, openMediaPreviewList])

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(filteredJobs.length / 20))
    if (page > lastPage) setPage(lastPage)
  }, [filteredJobs.length, page])

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
      render: (_, record) => {
        const previewUrl = isVideoJob(record) ? jobPreviewVideoUrl(record) : record.result_url
        const upscaled = isVideoJob(record) && Boolean(jobUpscaledVideoUrl(record))
        return previewUrl ? (
          isTtsJob(record) ? (
            <audio src={record.result_url || undefined} className="result-thumb" preload="metadata" controls />
          ) : (
          <button
            type="button"
            className="result-thumb-btn"
            aria-label={upscaled ? "预览超清结果" : "预览结果"}
            onClick={() => openResultPreview(record)}
          >
            {isVideoJob(record) ? (
              <>
                <video src={previewUrl} className="result-thumb" muted preload="metadata" />
                {record.status === "awaiting_refine" ? <Tag color="gold" className="result-upscale-tag">一采</Tag> : null}
                {upscaled ? <Tag color="purple" className="result-upscale-tag">超清</Tag> : null}
              </>
            ) : (
              <img src={record.result_url || undefined} className="result-thumb" alt="结果图" />
            )}
          </button>
          )
        ) : isH3PromptJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
          <Tag color="cyan">提示词就绪</Tag>
        ) : isShotPlanJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
          <Tag color="purple">镜头已规划</Tag>
        ) : isTtsJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
          <Tag color="green">配音就绪</Tag>
        ) : isShotPlanJob(record) && ["queued", "preparing", "running"].includes(record.status) ? (
          <Tag color="processing">规划中</Tag>
        ) : (
          <span className="text-muted">—</span>
        )
      }
    },
    { title: "创建时间", dataIndex: "created_at", width: 160 },
    {
      title: "操作",
      key: "action",
      width: 340,
      render: (_, record) => (
        <Space>
          <Button size="small" type="primary" ghost onClick={() => openDetail(record)}>
            查看详情
          </Button>
          {jobCanShowUpscaleAction(record) ? (
            <Tooltip title={jobUpscaleDisabledReason(record, jobs) || jobUpscaleHint(record)}>
              <span>
                <Button
                  size="small"
                  disabled={Boolean(jobUpscaleDisabledReason(record, jobs)) || upscalingJobId === record.id}
                  loading={upscalingJobId === record.id}
                  onClick={() => confirmSmartClarifyJob(record)}
                >
                  智能超清
                </Button>
              </span>
            </Tooltip>
          ) : null}
          {isShotPlanJob(record) && shotPlanDocumentId(record) ? (
            <Button size="small" type="link" onClick={() => openContentDocument(record)}>
              打开文档
            </Button>
          ) : null}
          {isTtsJob(record) && record.payload?.episode_id ? (
            <Button size="small" type="link" onClick={() => openWorkshopDubbing(record)}>
              打开配音
            </Button>
          ) : null}
          {jobCanConfirmRefine(record) ? (
            <>
              <Button
                size="small"
                type="primary"
                loading={refineAction?.jobId === record.id && refineAction.action === "confirm"}
                disabled={Boolean(refineAction)}
                onClick={() => void handleRefineDecision(record, "confirm")}
              >
                确认二采
              </Button>
              <Button
                size="small"
                loading={refineAction?.jobId === record.id && refineAction.action === "skip"}
                disabled={Boolean(refineAction)}
                onClick={() => void handleRefineDecision(record, "skip")}
              >
                保留一采
              </Button>
            </>
          ) : null}
          {record.status === "failed" && record.job_type !== "smart_edit_export" && record.job_type !== "asset_extraction" ? (
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
      comfy_queued: { color: "cyan", text: "视频服务排队" },
      running: { color: "processing", text: "执行中" },
      awaiting_refine: { color: "gold", text: "一采预览待确认" },
      succeeded: { color: "green", text: "已完成" },
      completed: { color: "green", text: "已完成" },
      failed: { color: "red", text: "失败" },
      cancelled: { color: "default", text: "已取消" },
      canceled: { color: "default", text: "已取消" },
      interrupted: { color: "default", text: "已中断" },
    }
    return map[s] || { color: "default", text: s }
  }

  function getJobTypeText(type: string): string {
    return director2JobTypeLabel(type)
  }

  function handleJobTypeChange(key: string) {
    hasInitializedTab.current = true
    setActiveJobType(key as Director2JobType)
    setPage(1)
  }

  function isVideoJob(job: Director2Job | null): boolean {
    return job?.job_type === "video_generation" || job?.job_type === "smart_edit_export"
  }

  function copyH3Prompt(text: string) {
    if (!text) return
    navigator.clipboard.writeText(text)
      .then(() => message.success("H3 提示词已复制到剪贴板"))
      .catch(() => message.error("复制失败"))
  }

  function openWorkshopDubbing(job: Director2Job) {
    const episodeId = String(job.payload?.episode_id || "").trim()
    if (!episodeId) {
      message.warning("该配音任务没有关联分集")
      return
    }
    navigate(director2WorkshopEpisodePath(projectId, episodeId, "dubbing"))
  }

  function openContentDocument(job: Director2Job) {
    const docId = shotPlanDocumentId(job)
    if (!docId) {
      message.warning("该任务没有关联内容库文档")
      return
    }
    navigate(director2ContentLibraryDocPath(projectId, docId))
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
    setDetailVideoSource("preview")
    setDetailVisible(true)
  }

  // 视频生成的详情统一复用预览弹层：左舞台、右参数；无成片时左舞台显示生成中占位。
  function usesPreviewDetail(job: Director2Job): boolean {
    return job.job_type === "video_generation"
  }

  function videoAspectHint(job: Director2Job): string {
    const raw = String(job.payload?.aspect_ratio || "").trim().toLowerCase()
    if (raw === "landscape") return "16:9"
    if (raw === "portrait") return "9:16"
    if (raw === "square") return "1:1"
    if (/^\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?$/.test(raw)) return raw
    return "16:9"
  }

  function videoAspectLabel(job: Director2Job): string {
    const raw = String(job.payload?.aspect_ratio || "").trim().toLowerCase()
    if (raw === "landscape") return "16:9 横屏"
    if (raw === "portrait") return "9:16 竖屏"
    if (raw === "16:9") return "16:9 横屏"
    if (raw === "9:16") return "9:16 竖屏"
    if (raw === "square") return "1:1 方形"
    if (raw === "adaptive") return "自适应"
    return videoAspectHint(job)
  }

  function renderVideoStagePlaceholder(job: Director2Job): ReactNode {
    const failed = job.status === "failed"
    const finished = isFinishedJob(job.status)
    const statusText = getStatusTag(job.status).text
    return (
      <div className={`job-detail-stage${failed ? " is-failed" : ""}`}>
        <span className="job-detail-stage-orbit" aria-hidden="true">
          <span className="job-detail-stage-dot" />
        </span>
        <div className="job-detail-stage-copy">
          <strong>{failed ? "生成失败" : finished ? "没有可播放的成片" : `${statusText} ${job.progress}%`}</strong>
          <span>
            {failed
              ? "云端没有返回成片，可在任务列表重试。"
              : finished
                ? "任务已完成，但没有返回视频文件。"
                : "云端正在生成，完成后会自动加载成片。"}
          </span>
        </div>
        {failed || finished ? null : (
          <div className="job-detail-stage-progress">
            <Progress percent={job.progress} showInfo={false} size="small" strokeColor="var(--studio-primary)" />
          </div>
        )}
      </div>
    )
  }

  function isFinishedJob(status: string): boolean {
    return ["completed", "succeeded", "failed", "cancelled", "canceled", "interrupted"].includes(status)
  }

  function runtimeStageLabel(stage: unknown): string {
    const raw = String(stage || "").trim()
    const labels: Record<string, string> = {
      queued: "排队中",
      pending: "等待中",
      preparing: "准备数据",
      prompt_generation: "生成提示词",
      uploading: "上传素材",
      comfy_queued: "视频服务排队",
      running: "生成中",
      assembling: "合成中",
      downloading: "下载成片",
      upscaling: "智能超清中",
      awaiting_refine: "一采预览待确认",
      succeeded: "已完成",
      completed: "已完成",
      failed: "失败",
      cancelled: "已取消",
      canceled: "已取消",
      interrupted: "已中断",
    }
    return labels[raw] || raw
  }

  // 创作参数直接展示，Comfy Prompt / 步数 / 队列序号等技术字段收进「运行参数」折叠区。
  function renderVideoDetailMeta(job: Director2Job): ReactNode {
    const payload = job.payload || {}
    const shots = videoShots(job)
    const attempts = llmAttempts(job)
    const finished = isFinishedJob(job.status)
    const statusTag = getStatusTag(job.status)
    const previewUrl = jobPreviewVideoUrl(job)
    const sourceUrl = jobSourceVideoUrl(job)
    const hasSourceVersion = Boolean(previewUrl && sourceUrl && sourceUrl !== previewUrl)
    const duration = Number(payload.total_duration_seconds || 0)
    const shotCount = Number(payload.shot_count || shots.length || 0)
    const spec = [
      shotCount ? `${shotCount} 镜` : "",
      duration ? `${duration} 秒` : "",
      payload.fps ? `${payload.fps} fps` : "",
    ].filter(Boolean).join(" · ")
    const episodeLabel = payload.episode_number
      ? `第 ${payload.episode_number} 集${payload.episode_title ? ` · ${payload.episode_title}` : ""}`
      : (payload.episode_title || "—")

    const runtimeRows: Array<[string, string]> = []
    if (payload.width && payload.height) runtimeRows.push(["输出分辨率", `${payload.width} × ${payload.height} px`])
    if (payload.quality) runtimeRows.push(["目标画质", `${payload.quality} MP`])
    if (payload.steps) {
      runtimeRows.push(["生成质量", `${payload.steps} 步${payload.weight_profile === "full" ? " · 完整权重" : payload.weight_profile ? " · 精简权重" : ""}`])
    }
    if (payload.audio_mode) runtimeRows.push(["音频模式", String(payload.audio_mode)])
    if (payload.prompt_id) runtimeRows.push(["Prompt ID", String(payload.prompt_id)])
    if (payload.queue_number != null) runtimeRows.push(["队列序号", String(payload.queue_number)])
    if (payload.runtime_stage && !finished) runtimeRows.push(["运行阶段", runtimeStageLabel(payload.runtime_stage)])
    if (payload.workflow) runtimeRows.push(["工作流", String(payload.workflow)])
    runtimeRows.push(["任务 ID", job.id])

    const collapseItems: Array<{ key: string; label: string; children: ReactNode }> = [
      {
        key: "runtime",
        label: "运行参数",
        children: (
          <div className="job-detail-grid">
            {runtimeRows.map(([key, value]) => (
              <div key={key} className="job-detail-fact"><span>{key}</span><b>{value}</b></div>
            ))}
          </div>
        ),
      },
    ]
    if (shots.length) {
      collapseItems.push({
        key: "shots",
        label: `镜头与提示词 (${shots.length})`,
        children: (
          <>
            {payload.prompt_source === "workshop_material" ? (
              <div className="job-detail-note">复用剧集工坊已保存的 H3 提示词</div>
            ) : payload.prompt_source === "configured_llm" ? (
              <div className="job-detail-note">任务内重新生成（工坊提示词未通过出片校验）</div>
            ) : payload.prompt_source === "program_preview" ? (
              <div className="job-detail-note">本次任务使用程序装箱预览，提示词未保存到镜头</div>
            ) : null}
            <div className="job-shot-list">
              {shots.map((shot) => {
                const promptText = videoShotPromptText(shot)
                const references = shot.reference_urls || []
                return (
                  <section key={shot.beat_id} className="job-shot">
                    <div className="job-shot-head">Beat {shot.sequence}{shot.heading || shot.scene ? ` · ${shot.heading || shot.scene}` : ""}</div>
                    {references.length ? (
                      <div className="job-shot-refs">
                        {references.map((url, idx) => (
                          <a key={url} href={url} target="_blank" rel="noreferrer" title={`Picture ${idx + 1} · ${videoReferenceLabel(shot, idx)}`}>
                            <img src={url} alt={`Picture ${idx + 1}`} />
                          </a>
                        ))}
                      </div>
                    ) : null}
                    {promptText ? (
                      <details className="job-shot-prompt">
                        <summary>MiniMax H3 Ref2VA Prompt</summary>
                        <pre>{promptText}</pre>
                      </details>
                    ) : (
                      <div className="job-detail-empty">提示词尚未生成</div>
                    )}
                  </section>
                )
              })}
            </div>
          </>
        ),
      })
    }
    if (attempts.length) {
      collapseItems.push({
        key: "attempts",
        label: `提示词生成记录 (${attempts.length})`,
        children: (
          <div className="job-shot-list">
            {attempts.map((attempt, idx) => (
              <details key={`${attempt.beat_id}-${attempt.attempt}-${idx}`} className="job-shot-prompt">
                <summary>
                  Beat {attempt.sequence} · 第 {attempt.attempt} 次 · {attempt.status === "passed" ? "通过" : "失败"}
                </summary>
                {attempt.errors?.length ? <div className="job-detail-note">{attempt.errors.join("\n")}</div> : null}
                <pre>{attempt.raw_response || "无原始响应"}</pre>
              </details>
            ))}
          </div>
        ),
      })
    }
    if (payload.director_report) {
      collapseItems.push({
        key: "director",
        label: "MiniMax H3 Director 报告",
        children: <pre className="job-shot-director">{payload.director_report}</pre>,
      })
    }
    if (job.error_message) {
      collapseItems.push({
        key: "error",
        label: "错误信息",
        children: <div className="job-detail-error">{job.error_message}</div>,
      })
    }

    return (
      <div className="job-detail-meta">
        <div className="job-detail-status">
          <Tag color={statusTag.color}>{statusTag.text}</Tag>
          <span>创建 {job.created_at}</span>
          {job.completed_at && finished ? <span>· 完成 {job.completed_at}</span> : null}
        </div>
        {!finished || job.progress < 100 ? (
          <div className="job-detail-progress">
            <Progress percent={job.progress} size="small" showInfo={false} status={job.status === "failed" ? "exception" : "active"} />
          </div>
        ) : null}
        {hasSourceVersion ? (
          <Segmented
            block
            size="small"
            value={detailVideoSource}
            onChange={(value) => setDetailVideoSource(value === "source" ? "source" : "preview")}
            options={[{ label: "成片", value: "preview" }, { label: "原片", value: "source" }]}
          />
        ) : null}
        {jobCanConfirmRefine(job) ? (
          <div className="job-detail-refine-note">
            一采预览已生成，尚未写入本镜成片。确认二采会复用同一 seed 只跑精修{jobRefineShotCount(job) > 1 ? `（共 ${jobRefineShotCount(job)} 镜）` : ""}；保留一采则直接把当前预览作为成片。
          </div>
        ) : null}
        <div className="job-detail-facts">
          <div className="job-detail-fact"><span>分集</span><b>{episodeLabel}</b></div>
          {spec ? <div className="job-detail-fact"><span>生成规格</span><b>{spec}</b></div> : null}
          <div className="job-detail-fact"><span>画面比例</span><b>{videoAspectLabel(job)}</b></div>
        </div>
        <Collapse ghost size="small" items={collapseItems} />
      </div>
    )
  }

  function videoDetailActions(job: Director2Job): MediaPreviewAction[] {
    const actions: MediaPreviewAction[] = []
    if (jobCanConfirmRefine(job)) {
      actions.push({
        key: "confirm-refine",
        label: "确认二采",
        type: "primary",
        disabled: Boolean(refineAction),
        onClick: () => void handleRefineDecision(job, "confirm"),
      })
      actions.push({
        key: "keep-preview",
        label: "保留一采",
        disabled: Boolean(refineAction),
        onClick: () => void handleRefineDecision(job, "skip"),
      })
    }
    if (jobCanShowUpscaleAction(job) && jobPreviewVideoUrl(job)) {
      const reason = jobUpscaleDisabledReason(job, jobs)
      actions.push({
        key: "upscale",
        label: "智能超清",
        disabled: Boolean(reason) || upscalingJobId === job.id,
        hint: reason || jobUpscaleHint(job),
        onClick: () => confirmSmartClarifyJob(job),
      })
    }
    return actions
  }

  async function fetchJobs(silent = false): Promise<Director2Job[] | undefined> {
    if (requestInFlight.current) return undefined
    requestInFlight.current = true
    const sequence = ++requestSequence.current
    if (!silent) setLoading(true)
    try {
      const res = await listJobs(projectId)
      if (sequence !== requestSequence.current || activeProjectRef.current !== projectId) return undefined
      const list = res || []
      setJobs((previous) => (sameJobList(previous, list) ? previous : list))
      if (!hasInitializedTab.current) {
        hasInitializedTab.current = true
        setActiveJobType(defaultJobTypeTab(list))
        setPage(1)
      }
      const selected = selectedJobRef.current
      if (selected) {
        const found = list.find((job) => job.id === selected.id)
        if (found && sameJobSummary(selected, found)) {
          // Reuse the previous object so polling an unchanged selection does not re-render the detail.
        } else if (found) {
          applySelectedJob(found)
        }
      }
      return list
    } catch {
      if (!silent && sequence === requestSequence.current) message.error("加载任务列表失败")
      return undefined
    } finally {
      if (sequence === requestSequence.current) {
        requestInFlight.current = false
        if (!silent) setLoading(false)
      }
    }
  }

  async function handleRetry(id: string) {
    try {
      await retryJob(csrfToken, projectId, id)
      message.success("任务已重新启动")
      await fetchJobs()
    } catch (err) {
      // 已下线的镜头生图（草图 / 渲染图 / 三联关键帧）在后端给出中文原因，需要原样转达
      message.error({ content: director2ErrorDetail(err, "重试失败"), key: "jobRetry", duration: 10 })
    }
  }

  function jobClarifyDurationSec(job: Director2Job): number {
    const payload = job.payload || {}
    const shots = (payload.source_shots || payload.shots || []) as Array<Record<string, unknown>>
    const total = shots.reduce((sum, shot) => sum + Number(shot.duration_sec ?? shot.video_duration ?? 0), 0)
    return total || Number(payload.duration_per_beat ?? 0)
  }

  async function handleUpscaleJob(job: Director2Job) {
    const reason = jobUpscaleDisabledReason(job, jobs)
    if (reason) {
      message.warning(reason)
      return
    }
    setUpscalingJobId(job.id)
    try {
      message.loading({ content: "正在提交智能超清...", key: "jobUpscale" })
      const res = await upscaleProjectVideoJob(csrfToken, projectId, job.id, {})
      message.success({ content: `智能超清任务已进入队列：${res.job_id}`, key: "jobUpscale", duration: 6 })
      await fetchJobs(true)
    } catch (err) {
      message.error({ content: director2ErrorDetail(err, "智能超清任务创建失败"), key: "jobUpscale", duration: 10 })
    } finally {
      setUpscalingJobId(null)
    }
  }

  function confirmSmartClarifyJob(job: Director2Job) {
    const reason = jobUpscaleDisabledReason(job, jobs)
    if (reason) {
      message.warning(reason)
      return
    }
    // 后端按本镜任务快照里的清晰度策略跑二采，所以预估也读同一份 payload，不受当前生成设置影响。
    const payload = job.payload || {}
    Modal.confirm({
      title: `智能超清 ${job.title || "本镜成片"}`,
      content: smartClarifyConfirmText(
        jobClarifyDurationSec(job),
        String(payload.aspect_ratio || "16:9"),
        String(payload.refine_quality || "1.0"),
        String(payload.refine_quality_mode || "auto"),
      ),
      okText: "开始超清",
      cancelText: "取消",
      centered: true,
      // 任务详情复用预览弹层（zIndex 1100），确认框需要再高一层才不会被盖住。
      zIndex: 1150,
      onOk: () => void handleUpscaleJob(job),
    })
  }

  async function handleRefineDecision(job: Director2Job, action: "confirm" | "skip") {
    if (!jobCanConfirmRefine(job)) {
      message.warning("当前任务没有待确认的一采预览")
      return
    }
    setRefineAction({ jobId: job.id, action })
    try {
      if (action === "confirm") {
        message.loading({ content: "正在提交二采精修...", key: "jobRefine" })
        await confirmProjectVideoRefine(csrfToken, projectId, job.id)
        message.success({ content: "已开始二采精修，将复用一采缓存只跑第二遍", key: "jobRefine", duration: 6 })
      } else {
        await skipProjectVideoRefine(csrfToken, projectId, job.id)
        message.success("已保留一采预览作为成片")
      }
      await fetchJobs(true)
    } catch (err) {
      message.error({ content: director2ErrorDetail(err, action === "confirm" ? "确认二采失败" : "保留一采失败"), key: "jobRefine", duration: 10 })
    } finally {
      setRefineAction(null)
    }
  }

  // 最新闭包 trampoline：轮询读取最新渲染的 fetchJobs（等价 Vue 闭包读响应式值）
  const fetchJobsRef = useRef(fetchJobs)
  useEffect(() => {
    fetchJobsRef.current = fetchJobs
  })

  useEffect(() => {
    hasInitializedTab.current = false
    activeProjectRef.current = projectId
    requestInFlight.current = false
    requestSequence.current += 1
    setActiveJobType(DIRECTOR2_DEFAULT_JOB_TYPE)
    setPage(1)
    setSearchQuery("")
    setStatusFilter("all")
    let cancelled = false
    let pollTimer = 0

    function schedule(list?: Director2Job[]) {
      if (cancelled) return
      const hasActive = (list ?? jobsRef.current).some((job) => ACTIVE_JOB_STATUSES.has(job.status))
      pollTimer = window.setTimeout(poll, hasActive ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    }

    async function poll() {
      if (cancelled) return
      if (document.visibilityState === "hidden") {
        pollTimer = window.setTimeout(poll, HIDDEN_POLL_MS)
        return
      }
      const list = await fetchJobsRef.current(true)
      schedule(list)
    }

    function handleVisibility() {
      if (cancelled || document.visibilityState !== "visible") return
      window.clearTimeout(pollTimer)
      void poll()
    }

    document.addEventListener("visibilitychange", handleVisibility)
    void fetchJobs().then((list) => schedule(list))
    return () => {
      cancelled = true
      requestSequence.current += 1
      requestInFlight.current = false
      window.clearTimeout(pollTimer)
      document.removeEventListener("visibilitychange", handleVisibility)
    }
    // 对应原版 onMounted + onUnmounted；projectId 变化时重新拉列表并重置默认 Tab
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // 视频生成任务有可播放结果时，详情直接复用共用预览弹层；参数在右侧栏展示。
  const previewDetailJob = detailVisible && selectedJob && usesPreviewDetail(selectedJob) ? selectedJob : null
  const previewDetailSourceUrl = previewDetailJob ? jobSourceVideoUrl(previewDetailJob) : ""
  const previewDetailUrl = previewDetailJob
    ? (detailVideoSource === "source" && previewDetailSourceUrl ? previewDetailSourceUrl : jobPreviewVideoUrl(previewDetailJob))
    : ""

  return (
    <div className="d2-jobs-center jobs-pane">
      <div className="sub-pane-header">
        <div>
          <h2 className="sub-pane-title">全部任务</h2>
          <p className="sub-pane-subtitle">
            监控项目下生图、视频、H3 提示词、镜头规划、AI 生成与配音任务。
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
        <div className="jobs-filter-bar">
          <Input
            className="jobs-search"
            aria-label="搜索任务"
            placeholder="搜索任务名称或 ID"
            prefix={<Search size={15} />}
            allowClear
            value={searchQuery}
            onChange={(event) => { setSearchQuery(event.target.value); setPage(1) }}
          />
          <Select
            aria-label="任务状态"
            value={statusFilter}
            onChange={(value) => { setStatusFilter(value); setPage(1) }}
            options={[
              { value: "all", label: "全部状态" },
              { value: "active", label: "进行中" },
              { value: "awaiting_refine", label: "一采预览待确认" },
              { value: "completed", label: "已完成" },
              { value: "failed", label: "失败" },
              { value: "cancelled", label: "已取消 / 已中断" },
            ]}
          />
          {hasFilters ? <Button type="text" onClick={() => { setSearchQuery(""); setStatusFilter("all"); setPage(1) }}>重置筛选</Button> : null}
          <span className="jobs-count" aria-live="polite">{hasFilters ? `找到 ${filteredJobs.length} / ${typeJobs.length} 个任务` : `共 ${typeJobs.length} 个任务`}</span>
        </div>
        <Table
          loading={loading}
          dataSource={filteredJobs}
          columns={columns}
          rowKey="id"
          pagination={{
            pageSize: 20,
            current: page,
            onChange: (nextPage) => setPage(nextPage),
            hideOnSinglePage: true,
            showSizeChanger: false,
          }}
          scroll={{ x: 980 }}
          size="middle"
          locale={{ emptyText: (
            <div className="jobs-empty-state">
              <ListChecks size={36} />
              <strong>{hasFilters ? "没有找到匹配的任务" : `暂无${director2JobTypeLabel(activeJobType)}任务`}</strong>
              <p>{hasFilters ? "试试其他关键词，或重置筛选查看当前类型的任务。" : "在内容库或工坊开始制作后，可在这里查看进度与结果。"}</p>
              {hasFilters ? <Button onClick={() => { setSearchQuery(""); setStatusFilter("all"); setPage(1) }}>重置筛选</Button> : null}
            </div>
          ) }}
        />
      </div>

      {/* 任务详情弹窗：视频生成有结果时改用共用预览弹层（左视频 / 右参数） */}
      <Modal
        open={detailVisible && !previewDetailJob}
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
                {selectedJob.completed_at ? (
                  <div className="detail-row">
                    <span className="detail-key">完成时间</span>
                    <span className="detail-val">{selectedJob.completed_at}</span>
                  </div>
                ) : null}
                <div className="detail-row">
                  <span className="detail-key">执行进度</span>
                  <span className="detail-val">
                    <Progress percent={selectedJob.progress} size="small" style={{ width: 200 }} />
                  </span>
                </div>
              </div>
            </div>

            {isTtsJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title">配音参数</div>
                <div className="detail-grid">
                  <div className="detail-row">
                    <span className="detail-key">范围</span>
                    <span className="detail-val">{selectedJob.payload?.scope === "line" ? "单句" : "本集批量"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">台词</span>
                    <span className="detail-val">{(selectedJob.payload?.line_ids || []).length || 0} 句</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">成功 / 失败</span>
                    <span className="detail-val">
                      {(selectedJob.payload?.completed_ids || []).length || 0} / {(selectedJob.payload?.failed_ids || []).length || 0}
                    </span>
                  </div>
                </div>
                {selectedJob.payload?.episode_id ? (
                  <Button size="small" type="link" onClick={() => openWorkshopDubbing(selectedJob)}>
                    打开工坊配音轨
                  </Button>
                ) : null}
              </div>
            ) : null}

            {selectedJob.job_type === "smart_edit_export" && <div className="detail-section"><div className="detail-section-title">剪辑导出参数</div><div className="detail-grid"><div className="detail-row"><span className="detail-key">剪辑名称</span><span className="detail-val">{selectedJob.payload?.name || selectedJob.title}</span></div><div className="detail-row"><span className="detail-key">输出规格</span><span className="detail-val">{selectedJob.payload?.aspect_ratio} · {selectedJob.payload?.quality}P · {selectedJob.payload?.fps} fps</span></div><div className="detail-row"><span className="detail-key">片段数量</span><span className="detail-val">{selectedJob.payload?.clip_count}</span></div></div></div>}
            {isShotPlanJob(selectedJob) ? (
              <div className="detail-section">
                <div className="detail-section-title">分集与镜头</div>
                <div className="detail-grid">
                  <div className="detail-row">
                    <span className="detail-key">内容库文档</span>
                    <span className="detail-val">{selectedJob.payload?.filename || shotPlanDocumentId(selectedJob) || "—"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">规划进度</span>
                    <span className="detail-val">
                      {Number(selectedJob.payload?.planned_episodes || selectedJob.payload?.episodes_done?.length || 0)}
                      {" / "}
                      {Number(selectedJob.payload?.episode_total || 0)} 集
                      {Number(selectedJob.payload?.failed_episodes || 0) ? `，失败 ${selectedJob.payload.failed_episodes} 集` : ""}
                    </span>
                  </div>
                </div>
                {shotPlanDocumentId(selectedJob) ? (
                  <Button type="primary" ghost onClick={() => openContentDocument(selectedJob)}>
                    打开内容库文档
                  </Button>
                ) : (
                  <div className="text-muted">任务没有关联文档，无法跳回内容库。</div>
                )}
              </div>
            ) : null}

            {selectedJob.job_type === "asset_extraction" ? (
              <div className="detail-section">
                <div className="detail-section-title">资产拆解结果</div>
                <div className="detail-grid">
                  <div className="detail-row">
                    <span className="detail-key">内容库文档</span>
                    <span className="detail-val">{selectedJob.payload?.filename || shotPlanDocumentId(selectedJob) || "—"}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">已写入</span>
                    <span className="detail-val">
                      角色 {Number(selectedJob.payload?.transferred?.characters || 0)} · 场景 {Number(selectedJob.payload?.transferred?.scenes || 0)} · 道具 {Number(selectedJob.payload?.transferred?.props || 0)}
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-key">跳过</span>
                    <span className="detail-val">
                      {Number(selectedJob.payload?.skipped_count || 0)} 项
                      {Array.isArray(selectedJob.payload?.skipped) && selectedJob.payload.skipped.length
                        ? `：${selectedJob.payload.skipped.slice(0, 6).map((item: { name?: string }) => item?.name).filter(Boolean).join("、")}`
                        : ""}
                    </span>
                  </div>
                </div>
                {shotPlanDocumentId(selectedJob) ? (
                  <Button type="primary" ghost onClick={() => openContentDocument(selectedJob)}>
                    打开内容库文档
                  </Button>
                ) : null}
              </div>
            ) : null}

            {/* 调用参数 */}
            {!isVideoJob(selectedJob) && !isH3PromptJob(selectedJob) && !isShotPlanJob(selectedJob) && !isTtsJob(selectedJob) && selectedJob.job_type !== "asset_extraction" && selectedJob.payload && Object.keys(selectedJob.payload).length ? (
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
            {!isVideoJob(selectedJob) && !isShotPlanJob(selectedJob) && selectedJob.job_type !== "asset_extraction" ? (
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
            {!isH3PromptJob(selectedJob) && !isShotPlanJob(selectedJob) && !isTtsJob(selectedJob) && (selectedJob.payload?.prompt || selectedJob.payload?.clean_prompt) ? (
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
            {!isVideoJob(selectedJob) && !isH3PromptJob(selectedJob) && !isShotPlanJob(selectedJob) && !isTtsJob(selectedJob) && selectedJob.job_type !== "asset_extraction" ? (
              <div className="detail-section">
                <div className="detail-section-title">📤 提交给图片服务的完整参数</div>
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

            {/* 结果：视频生成统一在共用预览弹层里查看；此处只保留剪辑导出与图片 / 配音结果 */}
            {selectedJob.job_type === "smart_edit_export" && selectedJob.result_url ? (
              <div className="detail-section">
                <div className="detail-section-title">🖼️ 生成结果</div>
                <div className="result-preview">
                  <video src={selectedJob.result_url} className="result-video" controls preload="metadata" />
                  <button
                    type="button"
                    className="result-open-link"
                    onClick={() => openMediaPreview({
                      src: selectedJob.result_url,
                      kind: "video",
                      title: selectedJob.title || "生成结果",
                    })}
                  >
                    <ExternalLink size={13} /> 预览原文件
                  </button>
                </div>
              </div>
            ) : selectedJob.result_url && selectedJob.job_type !== "video_generation" ? (
              <div className="detail-section">
                <div className="detail-section-title">🖼️ 生成结果</div>
                <div className="result-preview">
                  {isTtsJob(selectedJob) ? (
                    <audio src={selectedJob.result_url} className="result-video" controls preload="metadata" />
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
                  {isTtsJob(selectedJob) ? null : (
                  <button
                    type="button"
                    className="result-open-link"
                    onClick={() => openMediaPreview({
                      src: selectedJob.result_url,
                      kind: "image",
                      title: selectedJob.title || "生成结果",
                    })}
                  >
                    <ExternalLink size={13} /> 预览原文件
                  </button>
                  )}
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

      {previewDetailJob ? (
        <MediaPreviewModal
          open
          kind="video"
          src={previewDetailUrl}
          title={detailVideoSource === "source" ? `${previewDetailJob.title || "视频任务"} · 原片` : previewDetailJob.title || "视频任务"}
          description={`任务 ${previewDetailJob.id}`}
          headingLabel="任务详情"
          aspectRatio={videoAspectHint(previewDetailJob)}
          downloadName={`${previewDetailJob.title || "video"}.mp4`}
          meta={renderVideoDetailMeta(previewDetailJob)}
          actions={videoDetailActions(previewDetailJob)}
          placeholder={renderVideoStagePlaceholder(previewDetailJob)}
          onClose={() => setDetailVisible(false)}
        />
      ) : null}
    </div>
  )
}
