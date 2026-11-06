import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Input, InputNumber, Modal, Select, Spin, Tooltip, message } from "antd"
import {
  ArrowLeft, ChevronDown, Clapperboard, MessageCircle, Mic, RefreshCw,
  Settings2, Sparkles, Upload, Video, WandSparkles,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  digitalHumanAudioError,
  probeMediaDuration,
  type DigitalHumanAudio,
} from "../generation/digital-human"
import {
  LIPSYNC_AUDIO_MAX_SECONDS,
  LIPSYNC_SOURCE_MAX_SECONDS,
  LIPSYNC_SOURCE_MIN_SECONDS,
  LIP_SYNC_WORKFLOW,
  lipsyncSourceDurationError,
  lipsyncVideoError,
  type LipSyncVideo,
} from "../generation/lip-sync"
import {
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  type ToolOptionDefinition,
} from "../generation/motion-transfer"
import { createLocalId } from "../lib/utils"
import { generateJobPath } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import "./lip-sync-tool.css"

const optionIcons: Record<string, typeof WandSparkles> = {
  speed: WandSparkles,
  seed: Settings2,
}

type ToolWorkflow = {
  id: string
  name: string
  description: string
  reference_labels: string[]
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

export default function LipSyncTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const videoInputRef = useRef<HTMLInputElement>(null)
  const audioInputRef = useRef<HTMLInputElement>(null)
  const [video, setVideo] = useState<LipSyncVideo | null>(null)
  const [audio, setAudio] = useState<DigitalHumanAudio | null>(null)
  const [videoPreview, setVideoPreview] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", LIP_SYNC_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${LIP_SYNC_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  const labels = workflowQuery.data?.reference_labels?.length === 2
    ? workflowQuery.data.reference_labels
    : ["原视频", "目标音频"]

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(schema))
  }, [schema])

  useEffect(() => {
    const preview = video?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [video?.preview])

  // 未选择视频时不显示时长错误（undefined 仅在已选但探测失败时才报错）。
  const sourceDurationError = video ? lipsyncSourceDurationError(video.duration) : ""

  const acceptVideo = async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = lipsyncVideoError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    const duration = await probeMediaDuration(candidate)
    const durationProblem = lipsyncSourceDurationError(duration)
    if (durationProblem) {
      message.warning(durationProblem)
      return
    }
    setVideo((current) => {
      if (current) URL.revokeObjectURL(current.preview)
      return { id: createLocalId(), file: candidate, preview: URL.createObjectURL(candidate), duration }
    })
  }

  const acceptAudio = async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = digitalHumanAudioError(candidate, "目标音频")
    if (problem) {
      message.warning(problem)
      return
    }
    const duration = await probeMediaDuration(candidate)
    if (duration !== undefined && duration > LIPSYNC_AUDIO_MAX_SECONDS + 0.2) {
      message.warning(`目标音频 ${duration.toFixed(1)} 秒超出当前约 ${LIPSYNC_AUDIO_MAX_SECONDS} 秒的单次生成上限，请裁剪后重试`)
      return
    }
    setAudio({ id: createLocalId(), file: candidate, duration })
  }

  // 预览/悬浮工具条「对口型」跳转进来时只带原视频，目标音频仍需单独选择。
  const restoring = useMediaHandoffPrefill(params, acceptVideo)
  const ready = Boolean(video && audio && !sourceDurationError && workflowQuery.data) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!video) {
      message.warning("请上传原视频")
      return
    }
    if (!audio) {
      message.warning("请上传目标音频")
      return
    }
    if (sourceDurationError) {
      message.warning(sourceDurationError)
      return
    }
    const form = new FormData()
    form.set("mode", LIP_SYNC_WORKFLOW)
    // 后端要求提示词非空；留空时使用默认场景描述，口型同步不依赖提示词。
    form.set("prompt", prompt.trim() || "真实感人物面对镜头自然说话，画面稳定，光线柔和")
    form.set("options", JSON.stringify(motionToolPayload(values)))
    form.append("references", video.file)
    form.append("references", audio.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("口型同步任务已提交，可在生成页查看进度")
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
    <div className="studio-tools-page studio-motion-tool studio-lip-sync-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>口型同步</h1>
          <p>上传已有视频与目标音频，让人物口型精准匹配新配音</p>
        </div>
        <img className="studio-motion-hero-art" src="/tool-covers/lip-sync.jpg" alt="" aria-hidden="true" />
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取口型同步能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`口型同步能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="口型同步创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-references-tool" aria-label={labels.join("与")}>
              <div className="studio-motion-reference">
                <h3 className="studio-motion-reference-heading"><Clapperboard size={16} aria-hidden="true" />{labels[0]}</h3>
                <label className="studio-motion-reference-stage studio-ls-video-stage">
                  {video ? (
                    <button type="button" className="studio-motion-reference-preview ant-btn" onClick={(event) => { event.preventDefault(); setVideoPreview(true) }}>
                      <video src={video.preview} muted playsInline className="studio-ls-video-thumb" />
                    </button>
                  ) : (
                    <span className="studio-motion-reference-placeholder">
                      <Video aria-hidden="true" />
                      MP4 / MOV / WebM，{LIPSYNC_SOURCE_MIN_SECONDS}-{LIPSYNC_SOURCE_MAX_SECONDS} 秒，点击上传{restoring ? " · 正在读取原视频…" : ""}
                    </span>
                  )}
                  {video ? <span className="studio-motion-reference-label"><span>{video.file.name}{video.duration !== undefined ? ` · ${video.duration.toFixed(1)} 秒` : ""}</span></span> : null}
                  <input type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" className="hidden" onChange={(event) => {
                    const selected = event.target.files?.[0]
                    event.target.value = ""
                    void acceptVideo(selected)
                  }} />
                </label>
              </div>
              <div className="studio-motion-reference">
                <h3 className="studio-motion-reference-heading"><Mic size={16} aria-hidden="true" />{labels[1]}</h3>
                <label className="studio-motion-reference-stage studio-ls-audio-stage">
                  {audio ? (
                    <span className="studio-dh-audio-brief">
                      <Mic aria-hidden="true" />
                      <strong>{audio.file.name}</strong>
                      {audio.duration !== undefined ? <em>{audio.duration.toFixed(1)} 秒 · 口型将与此音频同步</em> : <em>口型将与此音频同步</em>}
                    </span>
                  ) : (
                    <span className="studio-motion-reference-placeholder">
                      <Mic aria-hidden="true" />
                      WAV / MP3，{LIPSYNC_AUDIO_MAX_SECONDS} 秒以内，点击上传
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
              <Button icon={<Upload size={14} />} onClick={() => videoInputRef.current?.click()}>上传原视频</Button>
              <Button icon={<Mic size={14} />} onClick={() => audioInputRef.current?.click()}>上传目标音频</Button>
            </div>
            {sourceDurationError ? <p className="studio-motion-validation" role="alert">{sourceDurationError}</p> : null}
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
              <label className="studio-tool-section-label" htmlFor="lip-sync-tool-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（可选）</span></label>
              <Input.TextArea
                id="lip-sync-tool-prompt"
                aria-label="提示词（可选）"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={"可补充画面与人物描述；口型与身份由原视频自动保持\n\n例如：演播室采访场景，人物上半身特写，正面机位"}
                rows={4}
                maxLength={1500}
              />
            </div>

            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">原视频 {LIPSYNC_SOURCE_MIN_SECONDS}-{LIPSYNC_SOURCE_MAX_SECONDS} 秒、目标音频 {LIPSYNC_AUDIO_MAX_SECONDS} 秒以内；人物身份与背景随原视频保持。</span>
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
          void acceptVideo(selected)
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

      <Modal open={videoPreview} footer={null} title={labels[0]} onCancel={() => setVideoPreview(false)} width={680} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>
    </div>
  )
}
