import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Input, InputNumber, Modal, Select, Spin, Switch, Tooltip, message } from "antd"
import {
  ArrowLeft, ChevronDown, ImagePlus, MessageCircle, Mic, RectangleHorizontal, RefreshCw,
  Settings2, Sparkles, Star, Upload, UserRound, WandSparkles,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  AUDIO_MAX_SECONDS,
  DIGITAL_HUMAN_WORKFLOW,
  digitalHumanAudioError,
  digitalHumanImageError,
  probeMediaDuration,
  type DigitalHumanAudio,
} from "../generation/digital-human"
import {
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  type ToolOptionDefinition,
} from "../generation/motion-transfer"
import { createLocalId } from "../lib/utils"
import { generateJobPath } from "../paths"
import AssetPickerModal from "./AssetPickerModal"
import "./digital-human-tool.css"

const optionIcons: Record<string, typeof RectangleHorizontal> = {
  aspect_ratio: RectangleHorizontal,
  speed: WandSparkles,
  weight_profile: Star,
  seed: Settings2,
}

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

type PortraitAsset = { id: string; file: File; preview: string }
type ToolAudio = DigitalHumanAudio & { preview: string }

export default function DigitalHumanTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const portraitInputRef = useRef<HTMLInputElement>(null)
  const audioInputRef = useRef<HTMLInputElement>(null)
  const [portrait, setPortrait] = useState<PortraitAsset | null>(null)
  const [audio, setAudio] = useState<ToolAudio | null>(null)
  const [portraitPreview, setPortraitPreview] = useState(false)
  const [audioPreview, setAudioPreview] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", DIGITAL_HUMAN_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${DIGITAL_HUMAN_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  const labels = workflowQuery.data?.reference_labels?.length === 2
    ? workflowQuery.data.reference_labels
    : ["人物形象图", "口播音频"]

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(schema))
  }, [schema])

  useEffect(() => {
    const preview = portrait?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [portrait?.preview])
  useEffect(() => {
    const preview = audio?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [audio?.preview])

  const acceptPortrait = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = digitalHumanImageError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    setPortrait({ id: createLocalId(), file: candidate, preview: URL.createObjectURL(candidate) })
  }

  const acceptAudio = async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = digitalHumanAudioError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    const duration = await probeMediaDuration(candidate)
    if (duration !== undefined && duration > AUDIO_MAX_SECONDS + 0.2) {
      message.warning(`口播音频 ${duration.toFixed(1)} 秒超出当前约 ${AUDIO_MAX_SECONDS} 秒的单次生成上限，请裁剪后重试`)
      return
    }
    setAudio({ id: createLocalId(), file: candidate, duration, preview: URL.createObjectURL(candidate) })
  }

  const ready = Boolean(portrait && audio && workflowQuery.data) && !submitting

  const submit = async () => {
    if (submissionPending.current) return
    if (!portrait) {
      message.warning("请上传人物形象图")
      return
    }
    if (!audio) {
      message.warning("请上传口播音频")
      return
    }
    const form = new FormData()
    form.set("mode", DIGITAL_HUMAN_WORKFLOW)
    // 后端要求提示词非空；工具页留空时使用默认场景描述，口型同步不依赖提示词。
    form.set("prompt", prompt.trim() || "真实感人物面对镜头自然说话，画面稳定，光线柔和")
    form.set("options", JSON.stringify(motionToolPayload(values)))
    form.append("references", portrait.file)
    form.append("references", audio.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("数字人任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
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
    const Icon = optionIcons[name] ?? Settings2
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
    <div className="studio-tools-page studio-motion-tool studio-digital-human-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>数字人</h1>
          <p>上传人物形象图与口播音频，生成口型同步的说话视频</p>
        </div>
        <img className="studio-motion-hero-art" src="/tool-art/digital-human-portrait.webp" alt="" aria-hidden="true" />
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取数字人能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`数字人能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="数字人创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-references-tool" aria-label={labels.join("与")}>
              <div className="studio-motion-reference">
                <h3 className="studio-motion-reference-heading"><UserRound size={16} aria-hidden="true" />{labels[0]}</h3>
                <label className="studio-motion-reference-stage studio-dh-portrait-stage">
                  {portrait ? (
                    <button type="button" className="studio-motion-reference-preview ant-btn" onClick={(event) => { event.preventDefault(); setPortraitPreview(true) }}>
                      <img src={portrait.preview} alt={`${labels[0]}预览`} />
                    </button>
                  ) : (
                    <span className="studio-motion-reference-placeholder">
                      <ImagePlus aria-hidden="true" />
                      正面清晰人物照，点击上传
                    </span>
                  )}
                  {portrait ? <span className="studio-motion-reference-label"><span>{portrait.file.name}</span></span> : null}
                  <input type="file" accept="image/*" className="hidden" onChange={(event) => {
                    const selected = event.target.files?.[0]
                    event.target.value = ""
                    acceptPortrait(selected)
                  }} />
                </label>
              </div>
              <div className="studio-motion-reference">
                <h3 className="studio-motion-reference-heading"><Mic size={16} aria-hidden="true" />{labels[1]}</h3>
                <label className="studio-motion-reference-stage studio-dh-audio-stage">
                  {audio ? (
                    <button type="button" className="studio-motion-reference-preview ant-btn" onClick={(event) => { event.preventDefault(); setAudioPreview(true) }}>
                      <span className="studio-dh-audio-brief">
                        <Mic aria-hidden="true" />
                        <strong>{audio.file.name}</strong>
                        {audio.duration !== undefined ? <em>{audio.duration.toFixed(1)} 秒 · 口型将与此音频同步</em> : <em>口型将与此音频同步</em>}
                      </span>
                    </button>
                  ) : (
                    <span className="studio-motion-reference-placeholder">
                      <Mic aria-hidden="true" />
                      WAV / MP3，{AUDIO_MAX_SECONDS} 秒以内，点击上传
                    </span>
                  )}
                  <input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.flac" className="hidden" onChange={(event) => {
                    const selected = event.target.files?.[0]
                    event.target.value = ""
                    void acceptAudio(selected)
                  }} />
                </label>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<Upload size={14} />} onClick={() => portraitInputRef.current?.click()}>上传形象图</Button>
              <Button icon={<ImagePlus size={14} />} onClick={() => setPickerOpen(true)}>从资产选取</Button>
              <Button icon={<Mic size={14} />} onClick={() => audioInputRef.current?.click()}>上传口播音频</Button>
            </div>
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
              <label className="studio-tool-section-label" htmlFor="digital-human-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（可选）</span></label>
              <Input.TextArea
                id="digital-human-tool-prompt"
                aria-label="提示词（可选）"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={"描述人物、场景和氛围；人物形象会与口播音频自动同步\n\n例如：一位友好的主持人面对镜头进行科普讲解，演播室背景，柔和灯光"}
                rows={4}
                maxLength={1500}
              />
            </div>

            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">形象图不超过 50 MB；口播音频 {AUDIO_MAX_SECONDS} 秒以内，人物口型与语音精确同步。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始生成"}
              </Button>
            </div>
          </div>
        </section>
      )}
      <img className="studio-motion-watermark" src="/tool-art/digital-human-portrait.webp" alt="" aria-hidden="true" />

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
        ref={audioInputRef}
        type="file"
        accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.flac"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          void acceptAudio(selected)
        }}
      />

      <Modal open={portraitPreview} footer={null} title={labels[0]} onCancel={() => setPortraitPreview(false)} width={560} destroyOnHidden>
        {portrait ? <Image src={portrait.preview} alt="人物形象图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={audioPreview} footer={null} title={labels[1]} onCancel={() => setAudioPreview(false)} width={520} destroyOnHidden>
        {audio ? <audio src={audio.preview} controls className="w-full" /> : null}
      </Modal>

      <AssetPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} onPick={(picked) => acceptPortrait(picked)} />
    </div>
  )
}
