import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Switch, Tooltip, message } from "antd"
import { ArrowLeft, ImagePlus, PersonStanding, RefreshCw, ScanSearch, Upload } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  MOTION_TRANSFER_WORKFLOW,
  motionDurationError,
  motionReferenceError,
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  type MotionReferenceAsset,
  type ToolOptionDefinition,
} from "../generation/motion-transfer"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import MotionTransferReferences from "../generation/MotionTransferReferences"
import AssetPickerModal from "./AssetPickerModal"

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

function assetFrom(file: File): MotionReferenceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

export default function MotionTransferTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const portraitInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [portrait, setPortrait] = useState<MotionReferenceAsset | null>(null)
  const [video, setVideo] = useState<MotionReferenceAsset | null>(null)
  const [portraitPreview, setPortraitPreview] = useState(false)
  const [videoPreview, setVideoPreview] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const initialized = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", MOTION_TRANSFER_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${MOTION_TRANSFER_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  const labels = workflowQuery.data?.reference_labels?.length === 2
    ? workflowQuery.data.reference_labels
    : ["角色形象图", "动作参考视频"]

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(schema))
  }, [schema])

  useEffect(() => () => {
    if (portrait) URL.revokeObjectURL(portrait.preview)
    if (video) URL.revokeObjectURL(video.preview)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const acceptPortrait = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "image")
    if (problem) {
      message.warning(problem)
      return
    }
    setPortrait((current) => {
      if (current) URL.revokeObjectURL(current.preview)
      return assetFrom(candidate)
    })
  }

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "video")
    if (problem) {
      message.warning(problem)
      return
    }
    setVideo((current) => {
      if (current) URL.revokeObjectURL(current.preview)
      return assetFrom(candidate)
    })
  }

  const durationError = motionDurationError(video?.duration, values.duration)
  const ready = Boolean(portrait && video && !durationError && workflowQuery.data) && !submitting

  const submit = async () => {
    if (!portrait) {
      message.warning("请上传角色形象图")
      return
    }
    if (!video) {
      message.warning("请上传动作参考视频")
      return
    }
    if (durationError) {
      message.warning(durationError)
      return
    }
    const form = new FormData()
    form.set("mode", MOTION_TRANSFER_WORKFLOW)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify(motionToolPayload(values)))
    form.append("references", portrait.file)
    form.append("references", video.file)
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("动作迁移任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      setSubmitting(false)
    }
  }

  const renderControl = ({ name, definition, control, options }: ReturnType<typeof motionToolOptions>[number]) => {
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
        return <Slider
          aria-label={definition.label}
          min={definition.minimum}
          max={definition.maximum}
          step={definition.step}
          value={Number(value)}
          onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
        />
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
    const seedNote = name === "seed" ? <span className="studio-tool-motion-note">0 表示每次随机</span> : null
    return <div key={name} className="studio-tool-motion-option">
      <label className="studio-tool-section-label">
        {definition.description
          ? <Tooltip title={definition.description}><span className="cursor-help">{definition.label}</span></Tooltip>
          : definition.label}
      </label>
      {field}
      {seedNote}
    </div>
  }

  return (
    <div className="studio-tools-page">
      <button type="button" className="studio-tool-back" onClick={() => navigate("/tools")}>
        <ArrowLeft size={14} />返回 AI 工具
      </button>

      <header className="studio-tool-hero-v2">
        <span className="studio-tool-hero-v2-art" aria-hidden="true">
          <span className="studio-tool-hero-v2-art-lines"><i /><i /><i /><i /></span>
          <span className="studio-tool-hero-v2-art-icon"><PersonStanding size={26} /></span>
        </span>
        <h1>动作迁移</h1>
        <p>上传一张角色形象图和一段动作参考视频，把视频里的舞蹈 / 肢体动作迁移到角色身上：SDPose 全身骨架锁定动作，角色图锁定身份，输出带原生音频的成片。提示词可留空。</p>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取动作迁移能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`动作迁移能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`} />
      ) : (
        <section className="studio-tool-card" aria-label="动作迁移创作">
          <div className="studio-tool-motion-materials">
            <MotionTransferReferences
              labels={labels}
              portrait={portrait ?? undefined}
              motion={video}
              onPickPortrait={(files) => acceptPortrait(files?.[0])}
              onPickMotion={(files) => acceptVideo(files?.[0])}
              onRemovePortrait={() => setPortrait((current) => { if (current) URL.revokeObjectURL(current.preview); return null })}
              onRemoveMotion={() => setVideo((current) => { if (current) URL.revokeObjectURL(current.preview); return null })}
              onPreviewPortrait={() => setPortraitPreview(true)}
              onPreviewMotion={() => setVideoPreview(true)}
              onMotionDuration={(id, duration) => {
                const seconds = Number.isFinite(duration) ? duration : undefined
                setVideo((current) => current?.id === id ? { ...current, duration: seconds } : current)
              }}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={<Upload size={14} />} onClick={() => portraitInputRef.current?.click()}>上传形象图</Button>
              <Button icon={<ImagePlus size={14} />} onClick={() => setPickerOpen(true)}>从资产选取</Button>
              <Button icon={<RefreshCw size={14} />} onClick={() => videoInputRef.current?.click()}>上传动作视频</Button>
              {durationError ? <span className="text-xs text-[var(--studio-danger)]" role="alert">{durationError}</span> : null}
            </div>
          </div>

          <div className="studio-tool-motion-options">
            {controls.map(renderControl)}
          </div>

          <div>
            <label className="studio-tool-section-label">提示词（可选）</label>
            <Input.TextArea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="描述角色、场景和氛围；留空将按内置提示词完整复刻参考视频的动作"
              autoSize={{ minRows: 2, maxRows: 6 }}
              maxLength={1500}
              showCount
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="studio-tool-motion-note">素材各不超过 50 MB；平台只截取开头片段并对齐到 24fps，输出音轨由模型生成。</span>
            <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<ScanSearch size={15} />} onClick={() => void submit()}>
              {submitting ? "提交中" : "开始生成"}
            </Button>
          </div>
        </section>
      )}

      <input
        ref={portraitInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          acceptPortrait(selected)
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

      <Modal open={portraitPreview} footer={null} title="角色形象图" onCancel={() => setPortraitPreview(false)} width={560} destroyOnHidden>
        {portrait ? <Image src={portrait.preview} alt="角色形象图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={videoPreview} footer={null} title="动作参考视频" onCancel={() => setVideoPreview(false)} width={640} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>

      <AssetPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} onPick={(picked) => acceptPortrait(picked)} />
    </div>
  )
}
