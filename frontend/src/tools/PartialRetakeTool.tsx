import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Switch, Tooltip, message } from "antd"
import { ArrowLeft, ChevronDown, Clock3, Dices, MessageCircle, Paintbrush, RefreshCw, Settings2, Sparkles, Upload, Video, WandSparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  INPAINT_WORKFLOW,
  inpaintDurationError,
  inpaintReferenceError,
  inpaintToolDefaults,
  inpaintToolOptions,
  inpaintToolPayload,
  type InpaintReferenceAsset,
  type ToolOptionDefinition,
} from "../generation/inpaint"
import { generateJobPath } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import { createLocalId } from "../lib/utils"
import { promptAutoSize } from "../prompt-autosize"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

const optionIcons = { inpaint_strength: WandSparkles, duration: Clock3, steps: Dices, seed: Dices }

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

function assetFrom(file: File): InpaintReferenceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

export default function PartialRetakeTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const maskInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [mask, setMask] = useState<InpaintReferenceAsset | null>(null)
  const [video, setVideo] = useState<InpaintReferenceAsset | null>(null)
  const [maskPreview, setMaskPreview] = useState(false)
  const [videoPreview, setVideoPreview] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", INPAINT_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${INPAINT_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => inpaintToolOptions(schema), [schema])
  const labels = workflowQuery.data?.reference_labels?.length === 2
    ? workflowQuery.data.reference_labels
    : ["重绘遮罩图(白色=重绘区)", "原片视频"]

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(inpaintToolDefaults(schema))
  }, [schema])

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId || !schema) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== INPAINT_WORKFLOW) throw new Error("此任务不是当前局部重绘工作流")
      const sources = roundReferenceSources(job, round).map((source) => ({ ...source, kind: source.index === 2 ? "video" as const : "image" as const }))
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (files.length !== 2) throw new Error("参考素材不完整，请重新上传")
      setMask(assetFrom(files[0])); setVideo(assetFrom(files[1]))
      setValues({ ...inpaintToolDefaults(schema), ...round.options })
      setPrompt(round.prompt)
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复局部重绘素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, schema])

  useEffect(() => {
    const preview = mask?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [mask?.preview])
  useEffect(() => {
    const preview = video?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [video?.preview])

  const acceptMask = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = inpaintReferenceError(candidate, "mask")
    if (problem) {
      message.warning(problem)
      return
    }
    setMask(assetFrom(candidate))
  }

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = inpaintReferenceError(candidate, "video")
    if (problem) {
      message.warning(problem)
      return
    }
    setVideo(assetFrom(candidate))
  }

  // 预览/悬浮工具条「局部重拍」跳转进来时只带原片，遮罩仍要在本页涂抹。
  const handoffRestoring = useMediaHandoffPrefill(searchParams, acceptVideo)

  const durationError = inpaintDurationError(video?.duration, values.duration)
  const ready = Boolean(mask && video && prompt.trim() && !durationError && workflowQuery.data) && !submitting && !restoring && !handoffRestoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!mask) {
      message.warning("请上传重绘遮罩图")
      return
    }
    if (!video) {
      message.warning("请上传原片视频")
      return
    }
    if (!prompt.trim()) {
      message.warning("请填写要把遮罩区域替换成什么内容")
      return
    }
    if (durationError) {
      message.warning(durationError)
      return
    }
    const form = new FormData()
    form.set("mode", INPAINT_WORKFLOW)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify(inpaintToolPayload(values)))
    // 后端约定：references[0]=遮罩图，references[1]=原片视频。
    form.append("references", mask.file)
    form.append("references", video.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("局部重绘任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const renderControl = ({ name, definition, control, options }: ReturnType<typeof inpaintToolOptions>[number]) => {
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

  const renderUploadCard = (
    kind: "mask" | "video",
    asset: InpaintReferenceAsset | null,
    onAccept: (file: File | undefined | null) => void,
    onRemove: () => void,
    onPreview: () => void,
  ) => (
    <div className="studio-motion-material" data-kind={kind}>
      {asset ? (
        kind === "mask" ? (
          <img src={asset.preview} alt="重绘遮罩图预览" onClick={onPreview} />
        ) : (
          <video src={asset.preview} muted playsInline
            onLoadedMetadata={(event) => {
              const seconds = event.currentTarget.duration
              setVideo((current) => current && current.id === asset.id
                ? { ...current, duration: Number.isFinite(seconds) ? seconds : undefined }
                : current)
            }}
          />
        )
      ) : (
        <div className="studio-motion-material-empty">
          {kind === "mask" ? <Paintbrush size={22} aria-hidden="true" /> : <Video size={22} aria-hidden="true" />}
          <span>{labels[kind === "mask" ? 0 : 1]}</span>
        </div>
      )}
      <div className="studio-motion-material-actions">
        {asset ? (
          <>
            <Button size="small" onClick={onPreview}>预览</Button>
            <Button size="small" danger onClick={onRemove}>移除</Button>
          </>
        ) : (
          <Button size="small" type="primary" onClick={() => (kind === "mask" ? maskInputRef : videoInputRef).current?.click()}>选择文件</Button>
        )}
      </div>
    </div>
  )

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>视频局部重拍</h1>
          <p>涂选要修复的区域，重绘与原片一致的内容；其余画面逐帧保持原样，音轨不变</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取局部重绘能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`局部重绘能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="局部重绘创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row">
              {renderUploadCard("mask", mask, acceptMask, () => setMask(null), () => setMaskPreview(true))}
              {renderUploadCard("video", video, acceptVideo, () => setVideo(null), () => setVideoPreview(true))}
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<Paintbrush size={14} />} onClick={() => maskInputRef.current?.click()}>上传遮罩图</Button>
              <Button icon={<Video size={14} />} onClick={() => videoInputRef.current?.click()}>上传原片视频</Button>
            </div>
            <p className="studio-motion-selection-help">
              遮罩图用<strong>白色</strong>涂出要修复的区域、<strong>黑色</strong>保留其余部分，尺寸可与原片不同（会自动对齐）；适合去瑕疵、补遮挡、画面清理。
              生成时长取原片开头对应秒数。{restoring ? "正在恢复素材…" : handoffRestoring ? "正在读取原片…" : ""}
            </p>
            {durationError ? <p className="studio-motion-validation" role="alert">{durationError}</p> : null}
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
            <label className="studio-tool-section-label" htmlFor="inpaint-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（必填）</span></label>
            <Input.TextArea
              id="inpaint-tool-prompt"
              aria-label="提示词（描述遮罩区域替换成什么）"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="描述修复目标，例如：清除画面中的路人；把被遮挡的天空补完整；修复晃动的水印区域。"
              autoSize={promptAutoSize(4)}
              maxLength={1500}
            />
          </div>

          <div className="studio-motion-footer">
            <span className="studio-tool-motion-note">素材各不超过 50 MB；遮罩外画面逐帧保持原样，音轨沿用原片。</span>
            <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
              {submitting ? "提交中" : "开始生成"}
            </Button>
          </div>
          </div>
        </section>
      )}

      <input
        ref={maskInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          acceptMask(selected)
        }}
      />
      <input
        ref={videoInputRef}
        type="file"
        accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          acceptVideo(selected)
        }}
      />

      <Modal open={maskPreview} footer={null} title="重绘遮罩图" onCancel={() => setMaskPreview(false)} width={560} destroyOnHidden>
        {mask ? <Image src={mask.preview} alt="重绘遮罩图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={videoPreview} footer={null} title="原片视频" onCancel={() => setVideoPreview(false)} width={640} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>
    </div>
  )
}
