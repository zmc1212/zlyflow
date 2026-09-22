import { useEffect, useMemo, useState } from "react"
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
import {
  applyPromptPreview,
  createPromptPreview,
  director2ErrorDetail,
  generateEpisodeVideo,
  getJob,
  patchDirectorPromptPlan,
  type Director2Asset,
  type Director2Beat,
  type Director2EpisodeDetail,
  type DirectorPromptPlan,
  type PromptPreview,
  type PromptReferenceSlot,
  type PromptSections,
} from "../api"
import { buildVideoJobOptions, type Director2WorkflowMode } from "../director2-video-settings"
import { sumBeatDurationSec } from "../workshop-beat-duration"
import { streamH3PromptJobEvents } from "../workshop-prompt-stream"

type ReferenceCandidate = PromptReferenceSlot & { key: string }

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
      title: "Director 出片方案",
      description: "整集生成公共设定和可独立出片的 Director 段；不会覆盖原 Beat。",
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
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [selectedPartId, setSelectedPartId] = useState("")
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<string[]>([])
  const [generatingSelection, setGeneratingSelection] = useState(false)
  const [editingPlan, setEditingPlan] = useState<DirectorPromptPlan | null>(null)
  const [savingPlan, setSavingPlan] = useState(false)

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
    await streamH3PromptJobEvents(projectId, jobId, (event) => {
      if (event.event === "done" && event.data.preview) {
        streamedPreview = event.data.preview as PromptPreview
      } else if (event.event === "error") {
        streamedError = String(event.data.message || "提示词预览任务失败")
      }
    })
    if (streamedPreview) return streamedPreview

    const job = await getJob(projectId, jobId)
    if (["completed", "succeeded"].includes(job.status)) {
      const result = job.payload?.preview as PromptPreview | undefined
      if (result) return result
      throw new Error("任务已完成，但没有返回提示词预览")
    }
    if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      throw new Error(job.error_message || streamedError || "提示词预览任务失败")
    }
    throw new Error(streamedError || "提示词预览事件流已中断，请到全部任务查看状态")
  }

  async function createPreview() {
    if (profile === "full_reference" && !selectedBeat) {
      message.warning("请先选择一个分镜")
      return
    }
    setCreating(true)
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
      setPreviewJobId(result.job_id)
      message.loading({ content: "正在使用提示词大师模板生成预览…", key: "prompt-preview", duration: 0 })
      const completed = await waitForPreview(result.job_id)
      setPreview(completed)
      message.success({ content: "提示词预览已完成，请确认后保存", key: "prompt-preview" })
    } catch (error) {
      message.error({ content: director2ErrorDetail(error, "提示词预览生成失败"), key: "prompt-preview", duration: 8 })
    } finally {
      setCreating(false)
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
          <Button type="primary" icon={<Sparkles size={14} />} loading={creating} onClick={createPreview}>
            生成预览
          </Button>
        </Space>
      </header>

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
          </Space>
          <Card size="small" title="公共主体定义"><Typography.Paragraph>{savedPlan.common_setting.subject_definitions}</Typography.Paragraph></Card>
          <Collapse
            items={savedPlan.parts.map((part) => ({
              key: part.id,
              label: `Part ${part.index} · ${part.segments.length} 段 · ${Math.round(part.frame_count / 24)} 秒`,
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
                      <SectionsView sections={segment.sections} includeSubject={false} />
                    </Card>
                  ))}
                </div>
              ),
            }))}
          />
          <Button
            icon={<Film size={14} />}
            loading={generatingSelection}
            disabled={savedPlan.status !== "current" || !selectedSegmentIds.length}
            onClick={() => generateSelection(savedPlan)}
          >
            生成选中 Director 段（{selectedSegmentIds.length}）
          </Button>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未保存 Director 出片方案" />
      )}

      <Modal
        open={Boolean(preview)}
        rootClassName="d2-prompt-preview-modal"
        width={920}
        title={preview?.kind === "director_segments" ? "确认 Director 出片方案" : "确认六段式提示词"}
        okText="确认保存"
        cancelText="返回调整"
        confirmLoading={applying}
        onOk={() => applyPreview(false)}
        onCancel={() => setPreview(null)}
      >
        {preview?.kind === "full_reference" ? (
          <SectionsView sections={preview.sections} />
        ) : preview?.kind === "director_segments" ? (
          <div className="director-preview-modal">
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
