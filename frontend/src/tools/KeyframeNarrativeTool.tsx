import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Switch, Tooltip, message } from "antd"
import {
  ArrowLeft, ArrowUp, ChevronDown, Clock3, Dices, Images, MessageCircle, Plus, RefreshCw, Settings2, Sparkles, Trash2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  KEYFRAME_MAX,
  KEYFRAME_MIN,
  KEYFRAME_WORKFLOW,
  evenAnchorSeconds,
  keyframeAnchorError,
  keyframeDurationSeconds,
  keyframeReferenceError,
  keyframeToolDefaults,
  keyframeToolOptions,
  keyframeToolPayload,
  serializeKeyframeAnchors,
  type KeyframeAnchor,
  type KeyframeReferenceAsset,
  type ToolOptionDefinition,
} from "../generation/keyframe"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"
import "./keyframe-narrative-tool.css"

const optionIcons = { aspect_ratio: Images, duration: Clock3, steps: Dices, seed: Dices }

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

function assetFrom(file: File): KeyframeReferenceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

/** 手动锚点反序列化:"-1" 为结尾，其余为秒数；数量不符时回退均匀分布。 */
function anchorsFromOption(raw: unknown, guideCount: number, durationSeconds: number): KeyframeAnchor[] {
  const parts = String(raw ?? "").split(",").map((part) => part.trim()).filter(Boolean)
  if (parts.length !== guideCount) return []
  const anchors: KeyframeAnchor[] = []
  for (const part of parts) {
    const value = Number(part)
    if (!Number.isFinite(value)) return []
    anchors.push(value < 0 ? { seconds: 0, end: true } : { seconds: value, end: false })
  }
  return keyframeAnchorError(anchors, durationSeconds) ? [] : anchors
}

export default function KeyframeNarrativeTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const [keyframes, setKeyframes] = useState<KeyframeReferenceAsset[]>([])
  const [anchors, setAnchors] = useState<KeyframeAnchor[]>([])
  const [manualAnchor, setManualAnchor] = useState(false)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", KEYFRAME_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${KEYFRAME_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  // anchor_seconds 由每张关键帧卡片上的时间选择器接管，不走通用控件渲染。
  const controls = useMemo(
    () => keyframeToolOptions(schema).filter(({ name }) => name !== "anchor_seconds"),
    [schema],
  )
  const durationSeconds = keyframeDurationSeconds(values.duration)

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(keyframeToolDefaults(schema))
  }, [schema])

  const resizeAnchors = (list: KeyframeAnchor[], guideCount: number): KeyframeAnchor[] => {
    const even = evenAnchorSeconds(guideCount + 1, durationSeconds)
    return Array.from({ length: guideCount }, (_, index) =>
      list[index] ?? { seconds: even[index] ?? durationSeconds, end: index === guideCount - 1 })
  }

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId || !schema) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== KEYFRAME_WORKFLOW) throw new Error("此任务不是当前关键帧叙事工作流")
      const files = await restoreReferenceFiles(roundReferenceSources(job, round).map((source) => ({ ...source, kind: "image" as const })))
      if (!active) return
      if (files.length < KEYFRAME_MIN || files.length > KEYFRAME_MAX) throw new Error("参考素材不完整，请重新上传")
      const nextDefaults = keyframeToolDefaults(schema)
      setValues({ ...nextDefaults, ...round.options, anchor_seconds: "" })
      setPrompt(round.prompt)
      const nextKeyframes = files.slice(0, KEYFRAME_MAX).map(assetFrom)
      setKeyframes(nextKeyframes)
      const guideCount = nextKeyframes.length - 1
      const restored = anchorsFromOption(round.options.anchor_seconds, guideCount, keyframeDurationSeconds(round.options.duration ?? nextDefaults.duration))
      if (restored.length === guideCount) {
        setAnchors(restored)
        setManualAnchor(true)
      } else {
        setAnchors([])
        setManualAnchor(false)
      }
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复关键帧叙事素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, schema])

  useEffect(() => {
    const previews = keyframes.map((keyframe) => keyframe.preview)
    return () => { previews.forEach((preview) => URL.revokeObjectURL(preview)) }
  }, [keyframes])

  const acceptKeyframe = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = keyframeReferenceError(candidate, `关键帧 ${keyframes.length + 1}`)
    if (problem) {
      message.warning(problem)
      return
    }
    if (keyframes.length >= KEYFRAME_MAX) {
      message.warning(`最多上传 ${KEYFRAME_MAX} 张关键帧`)
      return
    }
    const next = [...keyframes, assetFrom(candidate)]
    setKeyframes(next)
    setAnchors(resizeAnchors(anchors, next.length - 1))
  }

  const removeKeyframe = (index: number) => {
    const next = keyframes.filter((_, position) => position !== index)
    const nextAnchors = index === 0 ? anchors.slice(1) : anchors.filter((_, slot) => slot !== index - 1)
    setKeyframes(next)
    setAnchors(resizeAnchors(nextAnchors, next.length - 1))
    if (previewIndex === index) setPreviewIndex(null)
  }

  const moveKeyframeUp = (index: number) => {
    if (index <= 0) return
    const next = [...keyframes]
    ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
    let nextAnchors: KeyframeAnchor[]
    if (index === 1) {
      // 原开场图变为关键帧 2，需要在首位补一个新锚点；原锚点随其画面落到开场被丢弃。
      const even = evenAnchorSeconds(next.length, durationSeconds)
      nextAnchors = [{ seconds: even[0] ?? durationSeconds, end: false }, ...anchors.slice(1)]
    } else {
      nextAnchors = [...anchors]
      ;[nextAnchors[index - 2], nextAnchors[index - 1]] = [nextAnchors[index - 1], nextAnchors[index - 2]]
    }
    setKeyframes(next)
    setAnchors(nextAnchors)
  }

  const updateAnchor = (slot: number, patch: Partial<KeyframeAnchor>) => {
    setAnchors((current) => current.map((anchor, index) => index === slot ? { ...anchor, ...patch } : anchor))
  }

  const anchorError = manualAnchor ? keyframeAnchorError(anchors, durationSeconds) : ""
  const anchorSeconds = manualAnchor ? serializeKeyframeAnchors(anchors) : ""
  const ready = Boolean(
    keyframes.length >= KEYFRAME_MIN && prompt.trim() && !anchorError && workflowQuery.data,
  ) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (keyframes.length < KEYFRAME_MIN) {
      message.warning(`请至少上传 ${KEYFRAME_MIN} 张关键帧`)
      return
    }
    if (!prompt.trim()) {
      message.warning("请填写关键帧之间的叙事描述")
      return
    }
    if (anchorError) {
      message.warning(anchorError)
      return
    }
    const form = new FormData()
    form.set("mode", KEYFRAME_WORKFLOW)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify({ ...keyframeToolPayload(values), anchor_seconds: anchorSeconds }))
    // 后端约定：references 按叙事顺序排列，references[0] 锚定开场首帧。
    keyframes.forEach((keyframe) => form.append("references", keyframe.file))
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("关键帧叙事任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const renderControl = ({ name, definition, control, options }: ReturnType<typeof keyframeToolOptions>[number]) => {
    const value = values[name] ?? definition.default
    const field = (() => {
      if (control === "select") {
        return <Select
          aria-label={definition.label}
          value={String(value)}
          onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
          className="w-full"
          options={options}
        />
      }
      if (control === "switch") {
        return <Switch
          aria-label={definition.label}
          checked={Boolean(value)}
          onChange={(checked) => setValues((current) => ({ ...current, [name]: checked }))}
        />
      }
      if (control === "slider") {
        const precision = String(definition.step ?? 1).split(".")[1]?.length ?? 0
        return <div className="studio-motion-slider-field"><Slider
          aria-label={definition.label}
          ariaLabelForHandle={definition.label}
          min={definition.minimum}
          max={definition.maximum}
          step={definition.step}
          value={Number(value)}
          onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
        /><output aria-live="polite">{Number(value).toFixed(precision)}</output></div>
      }
      return <InputNumber
        aria-label={definition.label}
        min={definition.minimum}
        max={definition.maximum}
        step={definition.step}
        value={Number(value)}
        onChange={(next) => { if (next !== null) setValues((current) => ({ ...current, [name]: next })) }}
        className="w-full"
      />
    })()
    const Icon = optionIcons[name as keyof typeof optionIcons] ?? Settings2
    return <div key={name} className="studio-tool-motion-option" data-control={control}>
      <label className="studio-tool-section-label">
        <Icon size={19} aria-hidden="true" />
        {definition.description
          ? <Tooltip title={definition.description}><span className="cursor-help">{definition.label}</span></Tooltip>
          : definition.label}
      </label>
      {field}
    </div>
  }

  const renderKeyframeCard = (asset: KeyframeReferenceAsset, index: number) => {
    const isOpening = index === 0
    const slot = index - 1
    const anchor = anchors[slot]
    const isLast = index === keyframes.length - 1
    return (
      <div key={asset.id} className="studio-keyframe-material" data-role={isOpening ? "opening" : "guide"}>
        <img src={asset.preview} alt={`关键帧 ${index + 1} 预览`} onClick={() => setPreviewIndex(index)} />
        <span className="studio-keyframe-badge">{isOpening ? "开场" : `第 ${index + 1} 张`}</span>
        <div className="studio-keyframe-actions">
          {!isOpening ? <Button size="small" type="text" aria-label={`前移关键帧 ${index + 1}`} disabled={restoring} onClick={() => moveKeyframeUp(index)}><ArrowUp size={13} /></Button> : null}
          <Button size="small" onClick={() => setPreviewIndex(index)}>预览</Button>
          <Button size="small" type="text" danger aria-label={`移除关键帧 ${index + 1}`} disabled={restoring} onClick={() => removeKeyframe(index)}><Trash2 size={13} /></Button>
        </div>
        {!isOpening && anchor ? (
          <div className="studio-keyframe-anchor">
            <InputNumber
              size="small"
              aria-label={`关键帧 ${index + 1} 锚点时间`}
              min={0.1}
              max={durationSeconds}
              step={0.1}
              value={anchor.end ? undefined : anchor.seconds}
              disabled={!manualAnchor || anchor.end}
              onChange={(next) => { if (next !== null) updateAnchor(slot, { seconds: Number(next) }) }}
            />
            <span>秒</span>
            {isLast ? (
              <label className="studio-keyframe-anchor-end">
                <Switch
                  size="small"
                  aria-label={`关键帧 ${index + 1} 锚定到结尾`}
                  checked={anchor.end}
                  disabled={!manualAnchor}
                  onChange={(checked) => updateAnchor(slot, { end: checked })}
                />
                结尾
              </label>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>关键帧叙事</h1>
          <p>上传 2-4 张关键帧，画面依次贯穿每个故事节拍，音画一体</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取关键帧叙事能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`关键帧叙事能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="关键帧叙事创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-keyframe-materials">
              {keyframes.map(renderKeyframeCard)}
              {keyframes.length < KEYFRAME_MAX ? (
                <button
                  type="button"
                  className="studio-keyframe-add"
                  disabled={restoring}
                  onClick={() => inputRef.current?.click()}
                  aria-label="添加关键帧"
                >
                  <Plus size={20} aria-hidden="true" />
                  <span>添加关键帧</span>
                  <small>按叙事顺序</small>
                </button>
              ) : null}
            </div>
            <div className="studio-keyframe-anchor-mode">
              <Switch
                aria-label="自定义锚点时间"
                checked={manualAnchor}
                disabled={keyframes.length < KEYFRAME_MIN || restoring}
                onChange={setManualAnchor}
              />
              <span>自定义锚点时间</span>
              <small>{manualAnchor
                ? "为每张关键帧指定画面出现时间"
                : "关闭时按顺序均匀分布：开场首帧到结尾末帧"}</small>
            </div>
            <p className="studio-motion-selection-help">
              第一张为<strong>开场画面</strong>（拉伸铺满画布）；其余关键帧按锚点时间出现在画面中
              （自动居中裁切对齐画布），模型生成它们之间的叙事过渡。{restoring ? "正在恢复素材…" : ""}
            </p>
            {anchorError ? <p className="studio-motion-validation" role="alert">{anchorError}</p> : null}
          </div>

          <div className="studio-motion-settings">
            <div className="studio-tool-motion-options">
              {controls.filter(({ definition }) => definition.ui_group === "primary" || advancedOpen).map(renderControl)}
            </div>
            {controls.some(({ definition }) => definition.ui_group === "advanced") ? <Button
              type="text" className="studio-motion-more" aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((open) => !open)}
              icon={<Settings2 size={14} />}
            >更多设置<ChevronDown size={14} className={advancedOpen ? "is-open" : ""} /></Button> : null}

            <div className="studio-motion-prompt">
              <label className="studio-tool-section-label" htmlFor="keyframe-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（必填）</span></label>
              <Input.TextArea
                id="keyframe-tool-prompt"
                aria-label="提示词（描述关键帧之间的叙事过渡）"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="描述关键帧之间的叙事与过渡，例如：清晨的薄雾中，小船缓缓驶过湖面，最终停在山脚下的渡口，运镜平缓，电影感打光。"
                rows={4}
                maxLength={1500}
              />
            </div>

            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">每张关键帧不超过 50 MB；音画由模型一体生成。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始生成"}
              </Button>
            </div>
          </div>
        </section>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          acceptKeyframe(selected)
        }}
      />

      <Modal open={previewIndex !== null} footer={null} title={`关键帧 ${(previewIndex ?? 0) + 1}`} onCancel={() => setPreviewIndex(null)} width={560} destroyOnHidden>
        {previewIndex !== null && keyframes[previewIndex] ? <Image src={keyframes[previewIndex].preview} alt={`关键帧 ${(previewIndex ?? 0) + 1} 预览`} className="w-full" /> : null}
      </Modal>
    </div>
  )
}
