import { useEffect, useMemo, useRef, useState } from "react"
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd"
import { ArrowDown, ArrowUp, Copy, Film, Sparkles } from "lucide-react"
import { ApiRequestError } from "../../api"
import { directorPlanNeedsReview, directorRevisionStopMessage } from "../director-plan-quality"
import {
  applyPromptPreview,
  createPromptPreview,
  director2ErrorDetail,
  generateEpisodeVideo,
  getJob,
  patchDirectorPromptPlan,
  reviseDirectorPromptPlan,
  retryJob,
  type Director2Asset,
  type Director2Beat,
  type Director2EpisodeDetail,
  type Director2Job,
  type DirectorPromptPlan,
  type PromptPreview,
  type PromptReferenceSlot,
  type PromptSections,
} from "../api"
import { buildVideoJobOptions, type Director2WorkflowMode } from "../director2-video-settings"
import { sumBeatDurationSec } from "../workshop-beat-duration"
import { WorkshopPromptLive } from "../WorkshopPromptLive"
import {
  applyPromptStreamEvent,
  emptyPromptLiveState,
  streamH3PromptJobEvents,
  type PromptPreviewFailure,
  type WorkshopPromptLiveState,
} from "../workshop-prompt-stream"

type ReferenceCandidate = PromptReferenceSlot & { key: string }

class PromptPreviewTaskError extends Error {
  failure: PromptPreviewFailure | null

  constructor(messageText: string, failure: PromptPreviewFailure | null = null) {
    super(messageText)
    this.name = "PromptPreviewTaskError"
    this.failure = failure
  }
}

interface PromptAuthoringPanelProps {
  csrfToken: string
  projectId: string
  episode: Director2EpisodeDetail
  selectedBeat: Director2Beat | null
  assets: Director2Asset[]
  workflow: Director2WorkflowMode | undefined
  workflowId: string
  videoOptions: Record<string, string>
  onRefresh: () => Promise<void>
  onVideoJob?: (jobIds: string[]) => void
  selectedUnitId?: string
  jobs?: Director2Job[]
  shotWorkflows?: Director2WorkflowMode[]
  onChooseShotWorkflow?: (id: string) => void
}

export function findActivePromptPreview(jobs: Director2Job[], episodeId: string, profile: string, beatId?: string) {
  return jobs.find(job => job.job_type === "prompt_expansion"
    && ["queued", "preparing", "running", "storing"].includes(job.status)
    && job.payload?.episode_id === episodeId
    && job.payload?.prompt_profile === profile
    && (profile === "director_segments" || job.payload?.beat_id === beatId))
}

const SECTION_LABELS: Array<[keyof PromptSections, string]> = [
  ["subject_definitions", "主体定义"],
  ["summary", "摘要"],
  ["retention_analysis", "保留分析"],
  ["detailed_description", "详细描述"],
  ["overall_soundscape", "整体声景"],
  ["non_diegetic_music", "非叙事配乐"],
]

const EN_SECTION_LABELS: Record<keyof PromptSections, string> = {
  subject_definitions: "subject_definitions",
  summary: "summary",
  retention_analysis: "retention_analysis",
  detailed_description: "detailed_description",
  overall_soundscape: "overall_soundscape",
  non_diegetic_music: "non_diegetic_music",
}

export function assemblePromptSections(
  sections: PromptSections,
  language: string,
  includeSubject = false,
): string {
  return SECTION_LABELS
    .filter(([key]) => includeSubject || key !== "subject_definitions")
    .map(([key, zhLabel]) => `${language.startsWith("en") ? EN_SECTION_LABELS[key] : zhLabel}: ${sections[key] || ""}`)
    .join("\n\n")
}

export function formatDirectorPromptPlanForClipboard(plan: DirectorPromptPlan): string {
  const commonPrompt = plan.common_setting.prompt_text.trim()
    || plan.common_setting.subject_definitions.trim()
  const blocks = ["Director 出片方案", "公共主体定义", commonPrompt]

  for (const part of plan.parts) {
    blocks.push(`Part ${part.index}`)
    for (const segment of part.segments) {
      const segmentPrompt = segment.prompt_text.trim()
        || assemblePromptSections(segment.sections, plan.language)
      blocks.push(`${segment.title} · ${segment.duration_seconds}s`, segmentPrompt)
    }
  }

  return blocks.filter(Boolean).join("\n\n")
}

export function isValidatedPromptPreview(preview: PromptPreview | null | undefined): boolean {
  return Boolean(preview && (preview.kind !== "director_segments" || preview.validation_status === "valid"))
}

function assetImage(asset: Director2Asset): string {
  return String(asset.extra?.master_url || asset.extra?.reference_url || asset.extra?.image_url || asset.image_url || "")
}

export function referenceCandidates(assets: Director2Asset[]): ReferenceCandidate[] {
  const result: ReferenceCandidate[] = []
  for (const asset of assets) {
    const looks = Array.isArray(asset.extra?.identities) ? asset.extra.identities as Array<Record<string, unknown>> : []
    for (const look of looks) {
      const imageUrl = String(look.image_url || "")
      if (!imageUrl || !look.id) continue
      result.push({
        key: `${asset.id}:${String(look.id)}`,
        index: 0,
        token: "",
        asset_id: asset.id,
        look_id: String(look.id),
        image_url: imageUrl,
        kind: asset.kind,
        name: `${asset.name} · ${String(look.name || look.label || "造型")}`,
      })
    }
    const imageUrl = assetImage(asset)
    if (imageUrl) {
      result.push({
        key: asset.id,
        index: 0,
        token: "",
        asset_id: asset.id,
        image_url: imageUrl,
        kind: asset.kind,
        name: asset.name,
      })
    }
  }
  const kindRank: Record<string, number> = { character: 0, scene: 1, prop: 2 }
  return [...result].sort((a, b) => (kindRank[a.kind] ?? 9) - (kindRank[b.kind] ?? 9) || a.name.localeCompare(b.name))
}

export function normalizeSlots(items: ReferenceCandidate[]): PromptReferenceSlot[] {
  return items.map((item, index) => ({
    index: index + 1,
    token: `<Picture ${index + 1}>`,
    asset_id: item.asset_id,
    look_id: item.look_id,
    image_url: item.image_url,
    kind: item.kind,
    name: item.name,
  }))
}

export function promptAuthoringCopy(profile: Director2WorkflowMode["prompt_profile"] | undefined) {
  if (profile === "director_segments") {
    return {
        title: "Director 提示词扩写",
        description: "提示词大师结合本集镜头优化运镜、表演与声音；镜头原文保留，生成段按来源镜头对应展示。",
    }
  }
  return {
    title: "Minimax 六段式提示词",
    description: "针对当前分镜生成严格六段式提示词；预览确认后才会写入。",
  }
}

export function isContinuousDirectorSelection(plan: DirectorPromptPlan, partId: string, segmentIds: string[]): boolean {
  if (!partId || !segmentIds.length) return false
  const part = plan.parts.find((item) => item.id === partId)
  if (!part) return false
  const indexById = new Map(part.segments.map((segment, index) => [segment.id, index]))
  if (segmentIds.some((id) => !indexById.has(id))) return false
  const indexes = [...new Set(segmentIds.map((id) => indexById.get(id)!))].sort((a, b) => a - b)
  return indexes.every((value, index) => index === 0 || value === indexes[index - 1] + 1)
}

function SectionsView({ sections, includeSubject = true }: { sections: PromptSections; includeSubject?: boolean }) {
  return (
    <div className="prompt-authoring-sections">
      {SECTION_LABELS.filter(([key]) => includeSubject || key !== "subject_definitions").map(([key, label]) => {
        const value = sections[key]
        return value ? (
          <section key={key}>
            <strong>{label}</strong>
            <Typography.Paragraph>{value}</Typography.Paragraph>
          </section>
        ) : null
      })}
    </div>
  )
}

export function ShotPromptSummary({ episode, beat, onOpenPlan }: {
  episode: Director2EpisodeDetail; beat: Director2Beat | null; onOpenPlan: () => void;
}) {
  const plan = episode.prompt_authoring?.director_plan
  const segments = plan?.parts.flatMap(part => part.segments).filter(segment => beat && segment.source_beat_ids.includes(beat.id)) || []
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Button onClick={onOpenPlan}>前往制作方案</Button>
    {plan?.status === "stale" && <Alert type="warning" showIcon message="整集方案已过期，请在制作方案中更新。" />}
    {!segments.length && <Empty description="本镜尚无关联提示词，请前往制作方案优化本集提示词。" />}
    {segments.map(segment => <Card key={segment.id} size="small" title={segment.title}>
      <Typography.Paragraph type="secondary">关联镜头 {segment.source_beat_ids.map(id => episode.beats.findIndex(b => b.id === id) + 1).filter(n => n > 0).join("、")}；修改或重做该段会影响全部关联镜头。</Typography.Paragraph>
      <SectionsView sections={segment.sections} includeSubject={false} />
    </Card>)}
  </Space>
}

export default function PromptAuthoringPanel({
  csrfToken,
  projectId,
  episode,
  selectedBeat,
  assets,
  workflow,
  workflowId,
  videoOptions,
  onRefresh,
  onVideoJob,
  selectedUnitId,
  jobs = [],
  shotWorkflows = [],
  onChooseShotWorkflow,
}: PromptAuthoringPanelProps) {
  const profile = workflow?.prompt_profile || "none"
  const candidates = useMemo(() => referenceCandidates(assets), [assets])
  const maxReferences = Number(workflow?.max_references || 0)
  const defaultKeys = useMemo(() => candidates.slice(0, maxReferences).map((item) => item.key), [candidates, maxReferences])
  const [selectedKeys, setSelectedKeys] = useState<string[]>(defaultKeys)
  const [language, setLanguage] = useState<"zh-CN" | "en">("zh-CN")
  const [rewriteMode, setRewriteMode] = useState<"strict" | "expand">(profile === "director_segments" ? "expand" : "strict")
  const preferredSeconds = Math.max(1, Number(workflow?.max_total_frames || 1152) / 24 / Math.max(1, Number(workflow?.max_segments || 6)))
  const recommendedCount = Math.max(2, Math.ceil(sumBeatDurationSec(episode.beats || []) / preferredSeconds))
  const [segmentCount, setSegmentCount] = useState(recommendedCount)
  const [creating, setCreating] = useState(false)
  const [applying, setApplying] = useState(false)
  const [previewJobId, setPreviewJobId] = useState("")
  const [previewLive, setPreviewLive] = useState<WorkshopPromptLiveState>(() => emptyPromptLiveState())
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [selectedPartId, setSelectedPartId] = useState("")
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<string[]>([])
  const [generatingSelection, setGeneratingSelection] = useState(false)
  const [editingPlan, setEditingPlan] = useState<DirectorPromptPlan | null>(null)
  const [savingPlan, setSavingPlan] = useState(false)
  const [expandedParts, setExpandedParts] = useState<string[]>([])
  const [revisionSource, setRevisionSource] = useState<{ plan: DirectorPromptPlan; jobId?: string } | null>(null)
  const [revisionFeedback, setRevisionFeedback] = useState("")
  const [revisionTargets, setRevisionTargets] = useState<string[]>([])
  const lifecycle = useRef(new AbortController())
  const observedJobs = useRef(new Set<string>())

  useEffect(() => {
    const controller = new AbortController()
    lifecycle.current = controller
    message.destroy("prompt-preview")
    return () => {
      controller.abort()
      message.destroy("prompt-preview")
    }
  }, [])

  useEffect(() => {
    if (creating) return
    const active = findActivePromptPreview(jobs, episode.id, profile, selectedBeat?.id)
    if (!active || observedJobs.current.has(active.id)) return
    observedJobs.current.add(active.id)
    const signal = lifecycle.current.signal
    setPreviewJobId(active.id)
    setPreviewLive({ ...emptyPromptLiveState(active.id), message: "正在恢复提示词预览直播" })
    setCreating(true)
    void waitForPreview(active.id).then(completed => {
      if (signal.aborted) return
      setPreview(completed)
      message.success({ content: "提示词预览已完成，请确认后保存", key: "prompt-preview" })
    }).catch(error => {
      if (!signal.aborted) showPreviewFailure(error)
    }).finally(() => {
      if (!signal.aborted) setCreating(false)
    })
  }, [jobs, episode.id, profile, selectedBeat?.id, creating])

  const recentPreview = jobs.find(job => job.job_type === "prompt_expansion"
    && ["completed", "succeeded"].includes(job.status)
    && job.payload?.episode_id === episode.id
    && job.payload?.prompt_profile === profile
    && (profile === "director_segments" || job.payload?.beat_id === selectedBeat?.id))

  useEffect(() => {
    if (creating || previewJobId) return
    const latest = jobs.find(job => job.job_type === "prompt_expansion" && job.payload?.episode_id === episode.id
      && job.payload?.prompt_profile === profile && (profile === "director_segments" || job.payload?.beat_id === selectedBeat?.id))
    if (latest?.status !== "failed") return
    let cancelled = false
    void getJob(projectId, latest.id).then(job => {
      if (cancelled) return
      setPreviewJobId(job.id)
      const failure = job.payload?.failure as PromptPreviewFailure | undefined
      setPreviewLive({ ...emptyPromptLiveState(job.id), failed: true, working: false,
        failure: failure || null, message: failure?.message || job.error_message || "上次提示词优化失败" })
    }).catch(() => { /* Task center remains available if this read fails. */ })
    return () => { cancelled = true }
  }, [jobs, episode.id, profile, selectedBeat?.id, projectId, creating, previewJobId])

  async function openRecentPreview() {
    if (!recentPreview) return
    const signal = lifecycle.current.signal
    setCreating(true)
    setPreviewJobId(recentPreview.id)
    try {
      const job = await getJob(projectId, recentPreview.id)
      if (signal.aborted) return
      const result = job.payload?.preview as PromptPreview | undefined
      if (!result || !isValidatedPromptPreview(result)) throw new Error("此预览未通过最终校验")
      setPreview(result)
    } catch (error) {
      if (!signal.aborted) message.error(director2ErrorDetail(error, "读取预览失败"))
    } finally {
      if (!signal.aborted) setCreating(false)
    }
  }

  useEffect(() => {
    setSelectedKeys(defaultKeys)
    setRewriteMode(profile === "director_segments" ? "expand" : "strict")
  }, [defaultKeys, profile, workflowId])

  useEffect(() => {
    setSegmentCount(recommendedCount)
  }, [episode.id, recommendedCount])

  const selectedCandidates = useMemo(() => {
    const byKey = new Map(candidates.map((item) => [item.key, item]))
    return selectedKeys.flatMap((key) => byKey.get(key) ? [byKey.get(key)!] : [])
  }, [candidates, selectedKeys])
  const slots = useMemo(() => normalizeSlots(selectedCandidates), [selectedCandidates])
  const savedPlan = episode.prompt_authoring?.director_plan
  const visibleParts = savedPlan?.parts.map(part => ({ ...part,
    segments: part.segments.filter(segment => !selectedBeat || segment.source_beat_ids.includes(selectedBeat.id)),
  })).filter(part => part.segments.length) || []
  useEffect(() => {
    setSelectedSegmentIds([])
    setSelectedPartId("")
  }, [selectedBeat?.id, savedPlan?.id, savedPlan?.revision])
  useEffect(() => {
    const part = savedPlan?.parts.find(p => p.segments.some(s => s.id === selectedUnitId))
    if (part) setExpandedParts([part.id])
  }, [selectedUnitId, savedPlan?.id, savedPlan?.revision])
  const savedBeatPrompt = selectedBeat ? episode.prompt_authoring?.full_reference?.[selectedBeat.id] : undefined

  async function copyDirectorPlan(plan: DirectorPromptPlan) {
    try {
      await navigator.clipboard.writeText(formatDirectorPromptPlanForClipboard(plan))
      message.success("Director 出片方案已复制到剪贴板")
    } catch {
      message.error("复制失败，请手动复制方案内容")
    }
  }

  async function waitForPreview(jobId: string): Promise<PromptPreview> {
    let streamedPreview: PromptPreview | undefined
    let streamedError = ""
    let streamedFailure: PromptPreviewFailure | null = null
    let terminalJob: Awaited<ReturnType<typeof getJob>> | null = null
    let stopPolling = false
    const streamAbort = new AbortController()
    const signal = lifecycle.current.signal
    const abort = () => streamAbort.abort()
    signal.addEventListener("abort", abort, { once: true })
    // A server restart can leave an SSE connection open without a terminal
    // event. The persisted job row is authoritative in that case.
    const pollJob = async () => {
      while (!stopPolling) {
        await new Promise((resolve) => setTimeout(resolve, 15_000))
        if (stopPolling || signal.aborted) return
        try {
          const job = await getJob(projectId, jobId)
          if (["completed", "succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) {
            terminalJob = job
            streamAbort.abort()
            return
          }
        } catch {
          // SSE remains the primary source; a transient poll failure is safe.
        }
      }
    }
    void pollJob()
    try {
      do {
      await streamH3PromptJobEvents(projectId, jobId, (event) => {
        if (signal.aborted) return
        setPreviewLive((current) => applyPromptStreamEvent(
          current.jobId === jobId ? current : emptyPromptLiveState(jobId),
          event,
        ))
        if (event.event === "done" && event.data.preview) {
          streamedPreview = event.data.preview as PromptPreview
        } else if (event.event === "error") {
          streamedError = String(event.data.message || "提示词预览任务失败")
          streamedFailure = {
            code: String(event.data.code || "PROMPT_PREVIEW_FAILED"),
            stage: String(event.data.stage || "generation"),
            part_id: event.data.part_id ? String(event.data.part_id) : null,
            segment_ids: Array.isArray(event.data.segment_ids) ? event.data.segment_ids.map(String) : [],
            attempt: Number(event.data.attempt || 0),
            retryable: event.data.retryable !== false,
            message: streamedError,
            detail: event.data.detail ? String(event.data.detail) : undefined,
          }
        }
      }, { signal: streamAbort.signal })
      if (signal.aborted || terminalJob || streamedPreview || streamedFailure) break
      setPreviewLive(current => ({ ...current, working: true, failed: false, message: "连接恢复中，后台任务继续执行…" }))
      await new Promise(resolve => setTimeout(resolve, 5000))
      } while (!signal.aborted && !terminalJob)
    } finally {
      stopPolling = true
      streamAbort.abort()
      signal.removeEventListener("abort", abort)
    }
    if (signal.aborted) throw new DOMException("Preview listener disposed", "AbortError")
    if (streamedPreview) {
      if (isValidatedPromptPreview(streamedPreview)) return streamedPreview
      throw new PromptPreviewTaskError("Director 预览未通过最终校验，不能打开或保存")
    }

    const job = terminalJob || await getJob(projectId, jobId)
    if (["completed", "succeeded"].includes(job.status)) {
      const result = job.payload?.preview as PromptPreview | undefined
      if (result && isValidatedPromptPreview(result)) return result
      if (result?.kind === "director_segments") {
        throw new PromptPreviewTaskError("Director 预览未通过最终校验，不能打开或保存")
      }
      throw new Error("任务已完成，但没有返回提示词预览")
    }
    if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      const payloadFailure = job.payload?.failure as PromptPreviewFailure | undefined
      const failure = payloadFailure || streamedFailure
      throw new PromptPreviewTaskError(
        failure?.message || streamedError || job.error_message || "提示词预览任务失败",
        failure || null,
      )
    }
    throw new PromptPreviewTaskError(streamedError || "提示词预览事件流已中断，请到全部任务查看状态", streamedFailure)
  }

  function showPreviewFailure(error: unknown) {
    const body = error instanceof ApiRequestError ? error.body as { detail?: unknown } : null
    const apiFailure = body?.detail && typeof body.detail === "object" && "code" in body.detail ? body.detail as PromptPreviewFailure : null
    const structured = error instanceof PromptPreviewTaskError ? error.failure : apiFailure
    const detail = structured?.message || director2ErrorDetail(error, "提示词预览生成失败")
    setPreviewLive((current) => ({
      ...current,
      working: false,
      failed: true,
      failure: structured,
      message: detail,
    }))
    if (profile === "director_segments" && structured) {
      message.destroy("prompt-preview")
    } else {
      message.error({ content: detail, key: "prompt-preview", duration: 8 })
    }
  }

  function openRevision(plan: DirectorPromptPlan, jobId?: string) {
    setRevisionSource({ plan, jobId })
    setRevisionFeedback("")
    const issues = plan.creative_review?.issues.map(issue => issue.segment_id).filter(Boolean) || []
    setRevisionTargets([...new Set(issues.length ? issues : plan.parts.flatMap(part => part.segments.map(segment => segment.id)))])
    setPreview(null)
  }

  async function revisePlan(reviewOnly = false) {
    if (!revisionSource) return
    const feedback = revisionFeedback.trim()
    if (!reviewOnly && (!feedback || !revisionTargets.length)) {
      message.warning("请填写修改意见并选择返修段落")
      return
    }
    const source = revisionSource
    const signal = lifecycle.current.signal
    setCreating(true)
    setPreviewLive({ ...emptyPromptLiveState("creating-revision"), message: "正在创建方案返修任务" })
    try {
      const result = await reviseDirectorPromptPlan(csrfToken, projectId, episode.id, {
        base_job_id: source.jobId,
        expected_plan_id: source.plan.id,
        expected_revision: source.plan.revision,
        feedback: reviewOnly ? "" : feedback,
        segment_ids: reviewOnly ? [] : revisionTargets,
      })
      if (signal.aborted) return
      setRevisionSource(null)
      observedJobs.current.add(result.job_id)
      setPreviewJobId(result.job_id)
      setPreviewLive({ ...emptyPromptLiveState(result.job_id), message: "正在按意见返修并复验" })
      const completed = await waitForPreview(result.job_id)
      if (!signal.aborted) {
        setPreview(completed)
        message.success("新版本已生成，请查看问题与修改差异后保存")
      }
    } catch (error) {
      if (!signal.aborted) showPreviewFailure(error)
    } finally {
      if (!signal.aborted) setCreating(false)
    }
  }

  async function createPreview() {
    const signal = lifecycle.current.signal
    if (profile === "full_reference" && !selectedBeat) {
      message.warning("请先选择一个分镜")
      return
    }
    setCreating(true)
    setPreview(null)
    setPreviewLive({
      ...emptyPromptLiveState("creating-preview"),
      message: "正在创建提示词预览任务",
    })
    try {
      const result = await createPromptPreview(csrfToken, projectId, episode.id, {
        workflow_id: workflowId,
        target: profile === "director_segments"
          ? { kind: "director_episode" }
          : { kind: "beat", beat_id: selectedBeat!.id },
        language,
        rewrite_mode: rewriteMode,
        aspect_ratio: videoOptions.aspect_ratio || "16:9",
        target_segment_count: profile === "director_segments" ? segmentCount : undefined,
        reference_slots: slots,
      })
      if (signal.aborted) return
      observedJobs.current.add(result.job_id)
      setPreviewJobId(result.job_id)
      setPreviewLive({ ...emptyPromptLiveState(result.job_id), message: "正在使用提示词大师模板生成预览…" })
      const completed = await waitForPreview(result.job_id)
      setPreview(completed)
      message.success({ content: "提示词预览已完成，请确认后保存", key: "prompt-preview" })
    } catch (error) {
      if (!signal.aborted) showPreviewFailure(error)
    } finally {
      if (!signal.aborted) setCreating(false)
    }
  }

  async function retryFailedPreview() {
    const signal = lifecycle.current.signal
    if (!previewJobId || !previewLive.failure?.retryable) return
    setCreating(true)
    setPreview(null)
    try {
      const result = await retryJob(csrfToken, projectId, previewJobId)
      if (signal.aborted) return
      const nextJobId = String(result.job_id || "")
      if (!nextJobId) throw new Error("重试任务未返回 job_id")
      setPreviewJobId(nextJobId)
      observedJobs.current.add(nextJobId)
      setPreviewLive({ ...emptyPromptLiveState(nextJobId), message: "正在从失败检查点恢复" })
      const completed = await waitForPreview(nextJobId)
      setPreview(completed)
      message.success({ content: "失败部分已修复，预览通过最终校验", key: "prompt-preview" })
    } catch (error) {
      if (!signal.aborted) showPreviewFailure(error)
    } finally {
      if (!signal.aborted) setCreating(false)
    }
  }

  async function applyPreview(overwriteManual = false) {
    if (!preview || !previewJobId) return
    setApplying(true)
    try {
      await applyPromptPreview(csrfToken, projectId, episode.id, previewJobId, {
        expected_source_fingerprint: preview.source_fingerprint,
        overwrite_manual: overwriteManual,
      })
      setPreview(null)
      await onRefresh()
      message.success(preview.kind === "director_segments" ? "Director 出片方案已保存" : "六段式提示词已保存")
    } catch (error) {
      const detail = director2ErrorDetail(error, "保存提示词失败")
      if (!overwriteManual && detail.includes("MANUAL_CONFLICT")) {
        Modal.confirm({
          title: "覆盖手写提示词？",
          content: "当前分镜包含手写稿。确认后才会用本次六段式预览替换它。",
          okText: "确认覆盖",
          cancelText: "保留手写稿",
          onOk: () => applyPreview(true),
        })
      } else {
        message.error({ content: detail, duration: 8 })
      }
    } finally {
      setApplying(false)
    }
  }

  function moveReference(index: number, direction: -1 | 1) {
    const target = index + direction
    if (target < 0 || target >= selectedKeys.length) return
    setSelectedKeys((current) => {
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  function toggleSegment(partId: string, segmentId: string, checked: boolean) {
    if (partId !== selectedPartId) {
      setSelectedPartId(partId)
      setSelectedSegmentIds(checked ? [segmentId] : [])
      return
    }
    setSelectedSegmentIds((current) => checked
      ? [...current, segmentId]
      : current.filter((item) => item !== segmentId))
  }

  async function generateSelection(plan: DirectorPromptPlan) {
    if (!isContinuousDirectorSelection(plan, selectedPartId, selectedSegmentIds)) {
      message.warning("请先在同一 Part 内选择连续的 Director 段")
      return
    }
    setGeneratingSelection(true)
    try {
      const result = await generateEpisodeVideo(csrfToken, projectId, episode.id, buildVideoJobOptions(workflowId, videoOptions, {
        render_scope: "selection",
        director_plan_revision: plan.revision,
        part_id: selectedPartId,
        segment_ids: selectedSegmentIds,
      }))
      onVideoJob?.((result.job_ids?.length ? result.job_ids : [result.job_id]).filter((id): id is string => Boolean(id)))
      message.success("Director 局部生成任务已创建")
    } catch (error) {
      message.error({ content: director2ErrorDetail(error, "Director 局部生成失败"), duration: 8 })
    } finally {
      setGeneratingSelection(false)
    }
  }

  function updateEditingSegment(
    partIndex: number,
    segmentIndex: number,
    patch: Record<string, unknown>,
  ) {
    setEditingPlan((current) => {
      if (!current) return current
      const parts = current.parts.map((part, currentPartIndex) => {
        if (currentPartIndex !== partIndex) return part
        const segments = part.segments.map((segment, currentSegmentIndex) => {
          if (currentSegmentIndex !== segmentIndex) return segment
          return { ...segment, ...patch }
        })
        return {
          ...part,
          segments,
          frame_count: segments.reduce((sum, segment) => sum + Number(segment.frame_count || 0), 0),
        }
      })
      return { ...current, parts }
    })
  }

  async function saveEditingPlan() {
    if (!editingPlan) return
    setSavingPlan(true)
    try {
      await patchDirectorPromptPlan(csrfToken, projectId, episode.id, {
        expected_revision: editingPlan.revision,
        common_setting: editingPlan.common_setting,
        parts: editingPlan.parts,
        reference_slots: editingPlan.reference_slots,
      })
      setEditingPlan(null)
      await onRefresh()
      message.success("Director 出片方案已保存")
    } catch (error) {
      message.error({ content: director2ErrorDetail(error, "保存 Director 方案失败"), duration: 8 })
    } finally {
      setSavingPlan(false)
    }
  }

  if (profile === "none") return null

  const { title, description } = promptAuthoringCopy(profile)

  return (
    <section className="prompt-authoring-panel">
      <header className="prompt-authoring-header">
        <div>
          <Space size={8}><Sparkles size={18} /><strong>{title}</strong></Space>
          <p>{description}</p>
        </div>
        <Space wrap>
          <Select
            value={language}
            onChange={setLanguage}
            options={[{ value: "zh-CN", label: "简体中文" }, { value: "en", label: "English" }]}
            classNames={{ popup: { root: "studio-select-popup" } }}
            style={{ width: 120 }}
          />
          <Select
            value={rewriteMode}
            onChange={setRewriteMode}
            options={profile === "director_segments"
              ? [{ value: "expand", label: "允许补全" }, { value: "strict", label: "严格按剧本" }]
              : [{ value: "strict", label: "严格改写" }, { value: "expand", label: "允许扩写" }]}
            classNames={{ popup: { root: "studio-select-popup" } }}
            style={{ width: 132 }}
          />
          {profile === "director_segments" ? (
            <Space.Compact>
              <Input aria-label="段数标签" value="段数" readOnly tabIndex={-1} style={{ width: 58 }} />
              <InputNumber
                aria-label="Director 段数"
                min={2}
                max={48}
                value={segmentCount}
                onChange={(value) => setSegmentCount(Number(value || 2))}
                style={{ width: 82 }}
              />
            </Space.Compact>
          ) : null}
          <Button type="primary" icon={<Sparkles size={14} />} loading={creating} disabled={!episode.beats.length || Boolean(episode.data?.shot_structure?.legacy_lines)} onClick={createPreview}>
            {profile === "director_segments" ? "AI 优化本集提示词" : "AI 优化本镜提示词"}
          </Button>
          {recentPreview && <Button disabled={creating} onClick={() => void openRecentPreview()}>查看最近预览</Button>}
        </Space>
      </header>
      <Typography.Paragraph type="secondary">
        {profile === "director_segments" ? `作用范围：本集全部 ${episode.beats.length} 个镜头` : selectedBeat ? `当前：镜头 ${episode.beats.findIndex(beat => beat.id === selectedBeat.id) + 1} · ${selectedBeat.heading || selectedBeat.action || "未命名"}` : "请先选择镜头"}
        {profile === "director_segments" ? "。首次扩写覆盖本集以保持连续性；保存后可按关联段局部生成视频。" : ""}
      </Typography.Paragraph>

      {(creating || previewLive.failed) && previewLive.jobId ? (
        <Card
          size="small"
          className="prompt-preview-live-card"
          title="提示词预览直播"
          extra={<Tag color={previewLive.failed ? "error" : "processing"}>{previewLive.failed ? "生成失败" : "实时生成中"}</Tag>}
          role="status"
          aria-live="polite"
          aria-label="提示词预览实时进度"
        >
          <WorkshopPromptLive state={previewLive} showStage={profile === "director_segments"} />
          {previewLive.failure ? (
            <Space direction="vertical" size={10} style={{ width: "100%", marginTop: 12 }}>
              <Typography.Text type="secondary">
                {previewLive.failure.part_id ? `失败位置：${previewLive.failure.part_id}` : `失败阶段：${previewLive.failure.stage}`}
                {previewLive.failure.segment_ids.length ? ` · ${previewLive.failure.segment_ids.join("、")}` : ""}
              </Typography.Text>
              {previewLive.failure.stage === "preflight" ? <Alert type="warning" showIcon title="请先处理以下冲突" description={<span style={{ whiteSpace: "pre-wrap" }}>{previewLive.failure.detail}</span>} /> : null}
              <Space wrap>
                <Button
                  type="primary"
                  disabled={!previewLive.failure.retryable}
                  loading={creating}
                  onClick={() => void retryFailedPreview()}
                >
                  重试失败部分
                </Button>
                <Button disabled={creating} onClick={() => void createPreview()}>重新生成全部</Button>
                {profile === "director_segments" && onChooseShotWorkflow && shotWorkflows.length ? <Select
                  aria-label="改用逐镜生成" placeholder="改用逐镜生成…" disabled={creating}
                  options={shotWorkflows.map(mode => ({ value: mode.id, label: mode.name }))}
                  onChange={onChooseShotWorkflow} style={{ minWidth: 220 }}
                /> : null}
              </Space>
              <Collapse
                ghost
                size="small"
                items={[{
                  key: "technical-detail",
                  label: "技术详情",
                  children: (
                    <Typography.Paragraph copyable style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
                      {JSON.stringify(previewLive.failure, null, 2)}
                    </Typography.Paragraph>
                  ),
                }]}
              />
            </Space>
          ) : null}
        </Card>
      ) : null}

      {maxReferences > 0 ? (
        <div className="prompt-reference-editor">
          <Select
            mode="multiple"
            value={selectedKeys}
            maxCount={maxReferences}
            onChange={setSelectedKeys}
            placeholder="选择参考资产"
            options={candidates.map((item) => ({ value: item.key, label: `${item.kind} · ${item.name}` }))}
            classNames={{ popup: { root: "studio-select-popup" } }}
          />
          <div className="prompt-reference-order">
            {slots.map((slot, index) => (
              <div key={`${slot.asset_id}:${slot.look_id || "base"}`}>
                <Tag>{slot.token}</Tag><span>{slot.name}</span>
                <Space size={2}>
                  <Button size="small" type="text" icon={<ArrowUp size={13} />} disabled={index === 0} onClick={() => moveReference(index, -1)} />
                  <Button size="small" type="text" icon={<ArrowDown size={13} />} disabled={index === slots.length - 1} onClick={() => moveReference(index, 1)} />
                </Space>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {profile === "full_reference" ? (
        savedBeatPrompt ? (
          <Alert
            type={savedBeatPrompt.status === "current" ? "success" : "warning"}
            showIcon
            message={savedBeatPrompt.status === "current" ? "当前分镜已保存六段式提示词" : "已保存提示词已过期，需要重新生成"}
          />
        ) : selectedBeat?.h3_prompt_reference_state === "manual" ? (
          <Alert type="info" showIcon message="当前分镜使用手写提示词；生成预览不会自动覆盖它。" />
        ) : null
      ) : savedPlan ? (
        <div className="director-plan-view">
          {savedPlan.status === "stale" ? <Alert type="warning" showIcon message="Director 方案已过期，禁止直接出片" /> : null}
          <Space wrap>
            <Button
              icon={<Copy size={14} />}
              onClick={() => void copyDirectorPlan(savedPlan)}
            >
              复制整段提示词
            </Button>
            <Button
              disabled={savedPlan.status !== "current"}
              onClick={() => setEditingPlan(JSON.parse(JSON.stringify(savedPlan)) as DirectorPromptPlan)}
            >
              编辑方案
            </Button>
            <Typography.Text type="secondary">版本 {savedPlan.revision}</Typography.Text>
            {savedPlan.director_design ? <Button disabled={creating || savedPlan.status !== "current"} onClick={() => openRevision(savedPlan)}>按意见返修 / 重新审稿</Button> : null}
          </Space>
          <DirectorDesignReview plan={savedPlan} />
          <Card size="small" title="公共主体定义"><Typography.Paragraph>{savedPlan.common_setting.subject_definitions}</Typography.Paragraph></Card>
          <Collapse
            activeKey={expandedParts}
            onChange={keys => setExpandedParts(Array.isArray(keys) ? keys.map(String) : [String(keys)])}
            items={visibleParts.map((part) => ({
              key: part.id,
              label: `生成组 ${part.index} · ${part.segments.length} 段`,
              children: (
                <div className="director-segment-list">
                  {part.segments.map((segment) => (
                    <Card key={segment.id} size="small" title={(
                      <Space>
                        <Checkbox
                          checked={selectedPartId === part.id && selectedSegmentIds.includes(segment.id)}
                          onChange={(event) => toggleSegment(part.id, segment.id, event.target.checked)}
                        />
                        <span>{segment.title}</span>
                        <Tag>{segment.duration_seconds}s</Tag>
                      </Space>
                    )}>
                      <Typography.Paragraph type="secondary">关联镜头：{segment.source_beat_ids.map(id => episode.beats.findIndex(b => b.id === id) + 1).filter(n => n > 0).join("、")}；重做该段会影响全部关联镜头。</Typography.Paragraph>
                      {(!selectedUnitId || selectedUnitId === segment.id) ? <SectionsView sections={segment.sections} includeSubject={false} /> : <Typography.Text type="secondary">在本集生成段中选中此段查看提示词；可勾选连续段重做。</Typography.Text>}
                    </Card>
                  ))}
                </div>
              ),
            }))}
          />
          {!visibleParts.length && <Alert type="info" showIcon message="本集尚无生成段，请优化本集提示词。" />}
          <Button
            icon={<Film size={14} />}
            loading={generatingSelection}
            disabled={savedPlan.status !== "current" || !selectedSegmentIds.length || directorPlanNeedsReview(savedPlan)}
            onClick={() => generateSelection(savedPlan)}
          >
            生成选中 Director 段（{selectedSegmentIds.length}）
          </Button>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击 AI 优化本集提示词，查看扩写结果后保存，即可生成视频。" />
      )}

      <Modal
        open={Boolean(preview)}
        rootClassName="d2-prompt-preview-modal"
        width={920}
        title={preview?.kind === "director_segments" ? "确认 Director 出片方案" : "确认六段式提示词"}
        okText={preview?.kind === "director_segments" && directorPlanNeedsReview(preview) ? "保存待修订方案" : "确认保存"}
        cancelText="返回调整"
        confirmLoading={applying}
        onOk={() => applyPreview(false)}
        onCancel={() => setPreview(null)}
      >
        {preview?.kind === "full_reference" ? (
          <SectionsView sections={preview.sections} />
        ) : preview?.kind === "director_segments" ? (
          <div className="director-preview-modal">
            <DirectorDesignReview plan={preview} />
            <Button disabled={creating} onClick={() => openRevision(preview, previewJobId)}>按意见返修 / 重新审稿</Button>
            <Card size="small" title="公共主体定义"><Typography.Paragraph>{preview.common_setting.subject_definitions}</Typography.Paragraph></Card>
            <Collapse
              defaultActiveKey={preview.parts[0]?.id}
              items={preview.parts.map((part) => ({
                key: part.id,
                label: `Part ${part.index} · ${part.segments.length} 段`,
                children: part.segments.map((segment) => (
                  <Card key={segment.id} size="small" title={`${segment.title} · ${segment.duration_seconds}s`}>
                    <SectionsView sections={segment.sections} includeSubject={false} />
                  </Card>
                )),
              }))}
            />
          </div>
        ) : null}
      </Modal>

      <Modal open={Boolean(revisionSource)} title="Director 方案返修" width={760}
        okText="按意见返修并复验" cancelText="取消" confirmLoading={creating} onOk={() => void revisePlan()}
        cancelButtonProps={{ disabled: creating }} onCancel={() => { if (!creating) setRevisionSource(null) }}>
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Paragraph>保留剧情事实、对白、时长、起止状态和公共设定，只修改所选段落的摄影、表演与正文。新版本需确认保存。</Typography.Paragraph>
          <div style={{ width: "100%" }}>
            <Typography.Text strong>返修段落</Typography.Text>
            <Select aria-label="返修段落" mode="multiple" style={{ width: "100%" }} value={revisionTargets} onChange={setRevisionTargets} disabled={creating}
              options={revisionSource?.plan.parts.flatMap(part => part.segments.map(segment => ({ value: segment.id, label: `Part ${part.index} · ${segment.title}` })))} />
          </div>
          <div style={{ width: "100%" }}>
            <Typography.Text strong>修改意见</Typography.Text>
            <Input.TextArea aria-label="修改意见" value={revisionFeedback} onChange={event => setRevisionFeedback(event.target.value)}
              maxLength={4000} showCount autoSize={{ minRows: 4, maxRows: 10 }} disabled={creating}
              placeholder="例如：第二段只保留一次缓慢推进，删去重复机位描述；纸张声清晰，配乐不要盖过动作声。" />
          </div>
          <Button disabled={creating} onClick={() => void revisePlan(true)}>仅重新审稿并自动修复可处理的问题</Button>
        </Space>
      </Modal>

      <Modal
        open={Boolean(editingPlan)}
        rootClassName="d2-prompt-plan-modal"
        width={1000}
        title={editingPlan ? `编辑 Director 出片方案 · 版本 ${editingPlan.revision}` : "编辑 Director 出片方案"}
        okText="保存新版本"
        cancelText="取消"
        confirmLoading={savingPlan}
        onOk={saveEditingPlan}
        onCancel={() => setEditingPlan(null)}
      >
        {editingPlan ? (
          <div className="director-plan-editor">
            <label>
              <span>公共主体定义</span>
              <Input.TextArea
                autoSize={{ minRows: 3, maxRows: 10 }}
                value={editingPlan.common_setting.subject_definitions}
                onChange={(event) => setEditingPlan({
                  ...editingPlan,
                  common_setting: {
                    ...editingPlan.common_setting,
                    subject_definitions: event.target.value,
                    prompt_text: `${editingPlan.language.startsWith("en") ? "subject_definitions" : "主体定义"}: ${event.target.value}`,
                  },
                })}
              />
            </label>
            <Collapse
              defaultActiveKey={editingPlan.parts[0]?.id}
              items={editingPlan.parts.map((part, partIndex) => ({
                key: part.id,
                label: `Part ${part.index} · ${part.segments.length} 段 · ${Math.round(part.frame_count / 24)} 秒`,
                children: (
                  <div className="director-plan-editor-segments">
                    {part.segments.map((segment, segmentIndex) => (
                      <Card key={segment.id} size="small" title={(
                        <Space wrap>
                          <Input
                            value={segment.title}
                            onChange={(event) => updateEditingSegment(partIndex, segmentIndex, { title: event.target.value })}
                            style={{ width: 220 }}
                          />
                          <Space.Compact>
                            <InputNumber
                              aria-label={`${segment.title}时长`}
                              min={1}
                              max={48}
                              value={segment.duration_seconds}
                              onChange={(value) => {
                                const seconds = Number(value || 1)
                                updateEditingSegment(partIndex, segmentIndex, {
                                  duration_seconds: seconds,
                                  frame_count: Math.max(1, Math.round(seconds * 24)),
                                })
                              }}
                            />
                            <Input aria-label="秒单位" value="秒" readOnly tabIndex={-1} style={{ width: 44, textAlign: "center" }} />
                          </Space.Compact>
                        </Space>
                      )}>
                        {SECTION_LABELS.slice(1).map(([key, label]) => (
                          <label key={key}>
                            <span>{label}</span>
                            <Input.TextArea
                              autoSize={{ minRows: 2, maxRows: 8 }}
                              value={segment.sections[key] || ""}
                              onChange={(event) => {
                                const sections = { ...segment.sections, [key]: event.target.value }
                                updateEditingSegment(partIndex, segmentIndex, {
                                  sections,
                                  prompt_text: assemblePromptSections(sections, editingPlan.language),
                                })
                              }}
                            />
                          </label>
                        ))}
                      </Card>
                    ))}
                  </div>
                ),
              }))}
            />
          </div>
        ) : null}
      </Modal>
    </section>
  )
}

function DirectorDesignReview({ plan }: { plan: DirectorPromptPlan }) {
  if (!plan.director_design) return null
  return <Card size="small" title="为什么这样拍">
    <Typography.Paragraph>{plan.director_design.dramatic_intent}</Typography.Paragraph>
    <Typography.Paragraph>{plan.director_design.visual_strategy}</Typography.Paragraph>
    <Space wrap><Tag color="success">结构校验通过</Tag><Tag>{!plan.creative_review || plan.quality_status === "not_reviewed" ? "当前正文尚未重新审稿" : plan.creative_review.issues.length ? "创作质量待人工审阅" : "自动审稿完成，尚未验证成片"}</Tag></Space>
    {directorPlanNeedsReview(plan) ? <Alert type="warning" showIcon title="当前方案可保存，复验并解决阻断问题后才能出片" /> : null}
    {directorRevisionStopMessage(plan.revision_stop_reason) ? <Alert type="info" showIcon title={directorRevisionStopMessage(plan.revision_stop_reason)} /> : null}
    {plan.target_segment_count && plan.actual_segment_count !== plan.target_segment_count ? <Typography.Paragraph type="secondary">偏好 {plan.target_segment_count} 段；按完整动作与转场规划为 {plan.actual_segment_count} 段。</Typography.Paragraph> : null}
    {plan.director_design.quality_notes?.map((note, i) => <Typography.Paragraph key={i}>{note}</Typography.Paragraph>)}
    {plan.creative_review?.issues.map((issue, i) => <Alert key={issue.id || i} type={issue.severity === "advisory" ? "info" : "warning"} showIcon title={`${issue.severity === "advisory" ? "建议" : "待解决"}${issue.segment_id ? ` · ${issue.segment_id}` : ""}：${issue.evidence}`} description={issue.suggestion} />)}
    {plan.revision_requirements?.length ? <Collapse size="small" items={[{ key: "requirements", label: "已保留的修改意见", children: plan.revision_requirements.map((item, i) => <Typography.Paragraph key={i}>{item.feedback}</Typography.Paragraph>) }]} /> : null}
    {plan.revision_history?.some(round => round.round > 0) ? <Collapse size="small" items={plan.revision_history.filter(round => round.round > 0).map((round, i) => ({
      key: String(i), label: `第 ${round.round} 轮 · ${round.status === "accepted" ? "已采用" : "未采用，保留上一版"} · 解决 ${round.resolved?.length || 0} 项 / 遗留 ${round.remaining?.length || 0} 项 / 新增 ${round.new?.length || 0} 项`,
      children: <>{round.detail && <Typography.Paragraph>{round.detail}</Typography.Paragraph>}{round.changes?.map(change => <Card size="small" key={change.segment_id} title={change.segment_id}>
        <Typography.Text strong>修改前</Typography.Text><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{change.before}</Typography.Paragraph>
        <Typography.Text strong>修改后{round.status !== "accepted" ? "（未采用）" : ""}</Typography.Text><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{change.after}</Typography.Paragraph>
      </Card>)}</>,
    }))} /> : null}
  </Card>
}
