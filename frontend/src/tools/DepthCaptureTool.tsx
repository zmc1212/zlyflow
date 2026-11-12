import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Input, InputNumber, Modal, Select, Slider, Spin, Switch, Tooltip, message } from "antd"
import { ArrowLeft, ChevronDown, Clock3, Dices, Layers, MessageCircle, RefreshCw, Settings2, Sparkles, Upload } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  DEPTH_WORKFLOW,
  depthDurationError,
  depthReferenceError,
  depthToolDefaults,
  depthToolOptions,
  depthToolPayload,
  type DepthReferenceAsset,
  type ToolOptionDefinition,
} from "../generation/depth"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { promptAutoSize } from "../prompt-autosize"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

const optionIcons = { control_strength: Layers, duration: Clock3, steps: Dices, seed: Dices }

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

function assetFrom(file: File): DepthReferenceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

const depthCopy = {
  title: "深度捕捉",
  description: "锁定原片的运镜与空间结构，用提示词把画面重塑成新内容",
  help: "上传一段原片，系统自动提取时序深度图锁定运镜与构图，再用提示词重塑画面；生成时长取原片开头对应秒数。",
  placeholder: "描述画面要重塑成什么，例如：把这条街景重塑成雨夜霓虹赛博朋克风格，镜头运动与人物位置保持不变。",
  note: "原片不超过 50 MB；深度结构跟随原片，画面内容与风格按提示词重塑，成片带 AI 生成音轨。",
}

export default function DepthCaptureTool({ csrfToken, workflowId = DEPTH_WORKFLOW, copy }: {
  csrfToken: string
  workflowId?: string
  copy?: Partial<typeof depthCopy>
}) {
  const text = { ...depthCopy, ...copy }
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [video, setVideo] = useState<DepthReferenceAsset | null>(null)
  const [videoPreview, setVideoPreview] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", workflowId],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${workflowId}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => depthToolOptions(schema), [schema])
  const videoLabel = workflowQuery.data?.reference_labels?.[0] ?? "原片视频"

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(depthToolDefaults(schema))
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
      if (!round || round.mode !== workflowId) throw new Error(`此任务不是当前${text.title}工作流`)
      const sources = roundReferenceSources(job, round).map((source) => ({ ...source, kind: "video" as const }))
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (files.length !== 1) throw new Error("参考素材不完整，请重新上传")
      setVideo(assetFrom(files[0]))
      setValues({ ...depthToolDefaults(schema), ...round.options })
      setPrompt(round.prompt)
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, `恢复${text.title}素材失败`)) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, schema, workflowId, text.title])

  useEffect(() => {
    const preview = video?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [video?.preview])

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = depthReferenceError(candidate, "video")
    if (problem) {
      message.warning(problem)
      return
    }
    setVideo(assetFrom(candidate))
  }

  const durationError = depthDurationError(video?.duration, values.duration)
  const ready = Boolean(video && prompt.trim() && !durationError && workflowQuery.data) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!video) {
      message.warning("请上传原片视频")
      return
    }
    if (!prompt.trim()) {
      message.warning("请填写想把画面重塑成什么内容")
      return
    }
    if (durationError) {
      message.warning(durationError)
      return
    }
    const form = new FormData()
    form.set("mode", workflowId)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify(depthToolPayload(values)))
    // 后端约定：references[0]=原片视频。
    form.append("references", video.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success(`${text.title}任务已提交，可在生成页查看进度`)
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const renderControl = ({ name, definition, control, options }: ReturnType<typeof depthToolOptions>[number]) => {
    const value = values[name] ?? definition.default
    const field = (() => {
      if (control === "switch") return <Switch
        aria-label={definition.label}
        checked={Boolean(value)}
        onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
      />
      if (control === "select") {
        return <Select
          aria-label={definition.label}
          value={String(value)}
          onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
          className="w-full"
          options={options}
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

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>{text.title}</h1>
          <p>{text.description}</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip={`正在读取${text.title}能力`} /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`${text.title}能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label={`${text.title}创作`}>
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row">
              <div className="studio-motion-material" data-kind="video">
                {video ? (
                  <video src={video.preview} muted playsInline
                    onLoadedMetadata={(event) => {
                      const seconds = event.currentTarget.duration
                      setVideo((current) => current && current.id === video.id
                        ? { ...current, duration: Number.isFinite(seconds) ? seconds : undefined }
                        : current)
                    }}
                  />
                ) : (
                  <div className="studio-motion-material-empty">
                    <Layers size={22} aria-hidden="true" />
                    <span>{videoLabel}</span>
                  </div>
                )}
                <div className="studio-motion-material-actions">
                  {video ? (
                    <>
                      <Button size="small" onClick={() => setVideoPreview(true)}>预览</Button>
                      <Button size="small" danger onClick={() => setVideo(null)}>移除</Button>
                    </>
                  ) : (
                    <Button size="small" type="primary" onClick={() => videoInputRef.current?.click()}>选择文件</Button>
                  )}
                </div>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<Upload size={14} />} onClick={() => videoInputRef.current?.click()}>上传原片视频</Button>
            </div>
            <p className="studio-motion-selection-help">
              {text.help}{restoring ? "正在恢复素材…" : ""}
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
            <label className="studio-tool-section-label" htmlFor="depth-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（必填）</span></label>
            <Input.TextArea
              id="depth-tool-prompt"
              aria-label="提示词（描述画面要重塑成什么内容与风格）"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={text.placeholder}
              autoSize={promptAutoSize(4)}
              maxLength={workflowId === DEPTH_WORKFLOW ? 1500 : 8000}
            />
          </div>

          <div className="studio-motion-footer">
            <span className="studio-tool-motion-note">{text.note}</span>
            <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
              {submitting ? "提交中" : "开始生成"}
            </Button>
          </div>
          </div>
        </section>
      )}

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

      <Modal open={videoPreview} footer={null} title="原片视频" onCancel={() => setVideoPreview(false)} width={640} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>
    </div>
  )
}
