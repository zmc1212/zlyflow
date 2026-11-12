import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Tooltip, message } from "antd"
import { ArrowLeft, ChevronDown, Clock3, ImagePlus, MessageCircle, RefreshCw, Settings2, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
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
import { promptAutoSize } from "../prompt-autosize"
import MotionTransferReferences from "../generation/MotionTransferReferences"
import AssetPickerModal from "./AssetPickerModal"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

/** 换头工具唯一工作流；展示元数据与参数一律取自注册表，不在前端硬编码。 */
export const FACE_SWAP_WORKFLOW = "minimax-h3-face-swap"

const optionIcons: Record<string, typeof Clock3> = { duration: Clock3 }

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

function optionSchemaOf(workflow: ToolWorkflow | undefined): Record<string, ToolOptionDefinition> | null | undefined {
  return workflow?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
}

export default function FaceSwapTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [portrait, setPortrait] = useState<MotionReferenceAsset | null>(null)
  const [video, setVideo] = useState<MotionReferenceAsset | null>(null)
  const [portraitPreview, setPortraitPreview] = useState(false)
  const [videoPreview, setVideoPreview] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["face-swap-workflow"],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${FACE_SWAP_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const workflow = workflowQuery.data
  const schema = optionSchemaOf(workflow)
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  const labels = workflow?.reference_labels?.length === 2 ? workflow.reference_labels : ["角色形象图", "原片视频"]

  useEffect(() => {
    if (!workflow || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(optionSchemaOf(workflow)))
  }, [workflow])

  // 从生成页任务行「重新编辑」进入：恢复两份素材、参数与提示词。
  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId || !workflow) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== FACE_SWAP_WORKFLOW) throw new Error("此任务不属于角色替换工具支持的工作流")
      const sources = roundReferenceSources(job, round)
      const files = await restoreReferenceFiles(sources.map((source) => ({
        ...source,
        kind: source.kind ?? (source.index === sources.length ? "video" as const : "image" as const),
      })))
      if (!active) return
      if (files.length !== 2) throw new Error("参考素材不完整，请重新上传")
      setPortrait(assetFrom(files[0]))
      setVideo(assetFrom(files[1]))
      initialized.current = true
      setValues({ ...motionToolDefaults(optionSchemaOf(workflow)), ...round.options })
      setPrompt(round.prompt)
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复角色替换素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, workflow])

  useEffect(() => {
    const preview = portrait?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [portrait?.preview])
  useEffect(() => {
    const preview = video?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [video?.preview])

  const acceptPortrait = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "image")
    if (problem) { message.warning(problem); return }
    setPortrait(assetFrom(candidate))
  }

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = motionReferenceError(candidate, "video")
    if (problem) { message.warning(problem); return }
    setVideo(assetFrom(candidate))
  }

  const durationError = motionDurationError(video?.duration, values.duration, schema?.duration)
  const ready = Boolean(portrait && video && workflow) && !durationError && !submitting && !restoring

  const setOption = (name: string, next: string | number | boolean) => {
    setValues((current) => ({ ...current, [name]: next }))
  }

  const submit = async () => {
    if (submissionPending.current) return
    if (!portrait) { message.warning("请上传角色形象图"); return }
    if (!video) { message.warning("请上传原片视频"); return }
    if (durationError) { message.warning(durationError); return }
    const form = new FormData()
    form.set("mode", FACE_SWAP_WORKFLOW)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify(motionToolPayload(values)))
    form.append("references", portrait.file)
    form.append("references", video.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("角色替换任务已提交，可在生成页查看进度")
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
        return <Select aria-label={definition.label} value={String(value)} onChange={(next) => setOption(name, next)} className="w-full" options={options} />
      }
      if (control === "slider") {
        const precision = String(definition.step ?? 1).split(".")[1]?.length ?? 0
        return <div className="studio-motion-slider-field"><Slider
          aria-label={definition.label} ariaLabelForHandle={definition.label}
          min={definition.minimum} max={definition.maximum} step={definition.step}
          value={Number(value)} onChange={(next) => setOption(name, next)}
        /><output aria-live="polite">{Number(value).toFixed(precision)}</output></div>
      }
      return <InputNumber
        aria-label={definition.label}
        min={definition.minimum} max={definition.maximum} step={definition.step}
        value={Number(value)}
        onChange={(next) => { if (next !== null) setOption(name, next) }}
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
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>角色替换</h1>
          <p>把原片里主要人物的脸换成角色形象图的身份，逐帧贴合动作、表情与口型，保留原片背景运镜与声音</p>
        </div>
        <img className="studio-motion-hero-art" src="/tool-art/motion-transfer-pose.webp" alt="" aria-hidden="true" />
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取角色替换能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`角色替换能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="角色替换创作">
          <div className="studio-tool-motion-materials">
            <MotionTransferReferences
              variant="tool"
              labels={labels}
              portrait={portrait ?? undefined}
              motion={video}
              onPickPortrait={(files) => acceptPortrait(files?.[0])}
              onPickMotion={(files) => acceptVideo(files?.[0])}
              onRemovePortrait={() => setPortrait(null)}
              onRemoveMotion={() => setVideo(null)}
              onPreviewPortrait={() => setPortraitPreview(true)}
              onPreviewMotion={() => setVideoPreview(true)}
              onMotionDuration={(id, duration) => {
                const seconds = Number.isFinite(duration) ? duration : undefined
                setVideo((current) => current?.id === id ? { ...current, duration: seconds } : current)
              }}
            />
            <div className="studio-motion-upload-actions">
              <Button icon={<ImagePlus size={14} />} onClick={() => setPickerOpen(true)}>从资产选取形象图</Button>
            </div>
            <p className="studio-motion-selection-help">
              上传一张清晰的正面角色形象图和一段原片视频；平台会在远端自动从形象图裁出纯脸特写再替换，避免半身背景干扰。{restoring ? "正在恢复素材…" : ""}
            </p>
            {durationError ? <p className="studio-motion-validation" role="alert">{durationError}</p> : null}
          </div>

          <div className="studio-motion-settings">
            <Alert type="info" showIcon title="换头修脸试用" description="当前为单人替换：默认锁定画面中最大的一张脸，替换开头对应时长内的人脸，音轨沿用原片。" />
            <div className="studio-tool-motion-options">
              {controls.filter(({ definition }) => definition.ui_group === "primary" || advancedOpen).map(renderControl)}
            </div>
            {controls.some(({ definition }) => definition.ui_group === "advanced") ? <Button
              type="text" className="studio-motion-more" aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((open) => !open)}
              icon={<Settings2 size={14} />}
            >更多设置<ChevronDown size={14} className={advancedOpen ? "is-open" : ""} /></Button> : null}

            <div className="studio-motion-prompt">
              <label className="studio-tool-section-label" htmlFor="face-swap-prompt"><MessageCircle size={19} aria-hidden="true" />提示词 <span>（可选）</span></label>
              <Input.TextArea
                id="face-swap-prompt"
                aria-label="提示词（可选）"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="可补充换脸要求，例如只换脸保留原片发型服装、锁定某个人物等；留空使用内置换脸指令。"
                autoSize={promptAutoSize(4)}
                maxLength={1500}
              />
            </div>

            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">素材各不超过 50 MB；画面比例与原片一致，时长按所选替换时长截取开头片段。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始替换"}
              </Button>
            </div>
          </div>
        </section>
      )}
      <img className="studio-motion-watermark" src="/tool-art/motion-transfer-pose.webp" alt="" aria-hidden="true" />

      <Modal open={portraitPreview} footer={null} title="角色形象图" onCancel={() => setPortraitPreview(false)} width={560} destroyOnHidden>
        {portrait ? <Image src={portrait.preview} alt="角色形象图预览" className="w-full" /> : null}
      </Modal>
      <Modal open={videoPreview} footer={null} title="原片视频" onCancel={() => setVideoPreview(false)} width={640} destroyOnHidden>
        {video ? <video src={video.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>

      <AssetPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} onPick={(picked) => acceptPortrait(picked)} />
    </div>
  )
}
