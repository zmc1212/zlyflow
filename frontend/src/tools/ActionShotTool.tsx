import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Input, InputNumber, Modal, Select, Slider, Spin, Tooltip, message } from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import {
  ArrowLeft, ArrowUp, ChevronDown, Clock3, Images, MessageCircle, MonitorUp, Plus, RefreshCw, Settings2, Sparkles, Swords, Trash2, WandSparkles,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  ACTION_SHOT_MAX_REFERENCES,
  ACTION_SHOT_MIN_REFERENCES,
  ACTION_SHOT_WORKFLOW,
  actionShotPromptTemplate,
  actionShotReferenceError,
  actionShotSubmitBlockReason,
  insertActionShotPicture,
  missingActionShotPicture,
  type ActionShotAsset,
} from "../generation/action-shot"
import {
  motionToolDefaults,
  motionToolOptions,
  motionToolPayload,
  type ToolOptionDefinition,
} from "../generation/motion-transfer"
import { createLocalId } from "../lib/utils"
import { promptAutoSize } from "../prompt-autosize"
import { generateJobPath } from "../paths"
import "./motion-transfer-tool.css"
import "./keyframe-narrative-tool.css"
import "./action-shot-tool.css"

type ToolWorkflow = {
  id: string
  name: string
  description: string
  parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } | null }[]
}

const optionIcons = { aspect_ratio: Images, duration: Clock3, quality: MonitorUp, action_intensity: Swords }

function assetFrom(file: File): ActionShotAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

export default function ActionShotTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const promptRef = useRef<TextAreaRef>(null)
  const [references, setReferences] = useState<ActionShotAsset[]>([])
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const [prompt, setPrompt] = useState("")
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const initialized = useRef(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", ACTION_SHOT_WORKFLOW],
    queryFn: () => api<ToolWorkflow>(`/api/modes/${ACTION_SHOT_WORKFLOW}`),
    staleTime: 1000 * 60,
  })
  const schema = workflowQuery.data?.parameters?.find((parameter) => parameter.name === "options")?.schema?.properties
  const controls = useMemo(() => motionToolOptions(schema), [schema])

  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(schema))
  }, [schema])

  useEffect(() => {
    const previews = references.map((reference) => reference.preview)
    return () => { previews.forEach((preview) => URL.revokeObjectURL(preview)) }
  }, [references])

  const acceptReference = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = actionShotReferenceError(candidate, references.length)
    if (problem) {
      message.warning(problem)
      return
    }
    if (references.length >= ACTION_SHOT_MAX_REFERENCES) {
      message.warning(`最多上传 ${ACTION_SHOT_MAX_REFERENCES} 张参考图`)
      return
    }
    setReferences((current) => [...current, assetFrom(candidate)])
  }

  const removeReference = (index: number) => {
    setReferences((current) => current.filter((_, position) => position !== index))
    if (previewIndex === index) setPreviewIndex(null)
  }

  const moveReferenceUp = (index: number) => {
    if (index <= 0) return
    setReferences((current) => {
      const next = [...current]
      ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
      return next
    })
  }

  const promptTextArea = () => promptRef.current?.resizableTextArea?.textArea

  const focusPrompt = (cursor: number) => {
    requestAnimationFrame(() => {
      const input = promptTextArea()
      if (!input) return
      input.focus()
      input.setSelectionRange(cursor, cursor)
    })
  }

  const addPicture = (index: number) => {
    const input = promptTextArea()
    const inserted = insertActionShotPicture(prompt, index, input?.selectionStart ?? prompt.length)
    setPrompt(inserted.prompt)
    focusPrompt(inserted.cursor)
  }

  const applyTemplate = () => {
    const template = actionShotPromptTemplate(references.length)
    setPrompt(template)
    focusPrompt(template.length)
  }

  const pictureHint = missingActionShotPicture(prompt, references.length)
  const submitBlockReason = actionShotSubmitBlockReason({
    referenceCount: references.length,
    prompt,
    pictureHint,
    workflowLoaded: Boolean(workflowQuery.data),
    submitting,
  })
  const ready = !submitBlockReason

  const submit = async () => {
    if (submissionPending.current) return
    if (references.length < ACTION_SHOT_MIN_REFERENCES) {
      message.warning("请至少添加 1 张参考图")
      return
    }
    if (!prompt.trim()) {
      message.warning("请填写打斗动作的提示词")
      return
    }
    if (pictureHint) {
      message.warning(pictureHint)
      return
    }
    const form = new FormData()
    form.set("mode", ACTION_SHOT_WORKFLOW)
    form.set("prompt", prompt.trim())
    form.set("options", JSON.stringify(motionToolPayload(values)))
    // R2V 的 <Picture n> 严格对应用户上传顺序，不能重排。
    references.forEach((reference) => form.append("references", reference.file))
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("打斗镜头任务已提交，可在生成页查看进度")
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
      if (control === "slider") {
        const precision = String(definition.step ?? 1).split(".")[1]?.length ?? 0
        return <div className="studio-motion-slider-field">
          <Slider
            aria-label={definition.label}
            ariaLabelForHandle={definition.label}
            min={definition.minimum}
            max={definition.maximum}
            step={definition.step}
            value={Number(value)}
            onChange={(next) => setValues((current) => ({ ...current, [name]: next }))}
          />
          <output aria-live="polite">{Number(value).toFixed(precision)}</output>
        </div>
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
    <div className="studio-tools-page studio-motion-tool studio-action-shot">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>打斗镜头</h1>
          <p>添加 1-9 张角色与场景参考，用一句话生成连贯的拳脚、兵器或法术打斗，带原生音效</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取打斗镜头能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`打斗镜头能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="打斗镜头创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-keyframe-materials">
              {references.map((reference, index) => (
                <div key={reference.id} className="studio-keyframe-material" data-role={index === 0 ? "opening" : "reference"}>
                  <img src={reference.preview} alt={`参考图 ${index + 1} 预览`} onClick={() => setPreviewIndex(index)} />
                  <span className="studio-keyframe-badge">{`Picture ${index + 1}`}</span>
                  <div className="studio-keyframe-actions">
                    {index > 0 ? <Button size="small" type="text" aria-label={`前移参考图 ${index + 1}`} onClick={() => moveReferenceUp(index)}><ArrowUp size={13} /></Button> : null}
                    <Button size="small" onClick={() => addPicture(index)}>引用</Button>
                    <Button size="small" type="text" danger aria-label={`移除参考图 ${index + 1}`} onClick={() => removeReference(index)}><Trash2 size={13} /></Button>
                  </div>
                </div>
              ))}
              {references.length < ACTION_SHOT_MAX_REFERENCES ? (
                <button
                  type="button"
                  className="studio-keyframe-add"
                  onClick={() => inputRef.current?.click()}
                  aria-label="添加参考图"
                >
                  <Plus size={20} aria-hidden="true" />
                  <span>添加参考图</span>
                  <small>按顺序编号</small>
                </button>
              ) : null}
            </div>
            <p className="studio-motion-selection-help">
              第 1 张放<strong>主动作角色</strong>，第 2 张放对手或同框角色，第 3 张起可放场景与光线参考；
              编号顺序就是提示词里 <code>&lt;Picture n&gt;</code> 的顺序，点卡片上的「引用」即可插入。
            </p>
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
              <div className="studio-action-shot-prompt-head">
                <label className="studio-tool-section-label" htmlFor="action-shot-prompt">
                  <MessageCircle size={19} aria-hidden="true" />提示词 <span>（必填）</span>
                </label>
                <Button type="text" size="small" icon={<WandSparkles size={13} />} onClick={applyTemplate}>
                  填入打斗模板
                </Button>
              </div>
              <Input.TextArea
                id="action-shot-prompt"
                ref={promptRef}
                aria-label="提示词（描述打斗动作与镜头）"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="描述动作节拍与镜头，例如：<Picture 1> 与 <Picture 2> 在雨夜废墟近身格斗，先出拳压制，再侧身闪避反击，最后重击收势；镜头跟随，火光飞溅，打击感强。"
                autoSize={promptAutoSize(5)}
                maxLength={1500}
              />
              {pictureHint && references.length > 0 && prompt.trim() ? <p className="studio-motion-validation" role="alert">{pictureHint}</p> : null}
            </div>

            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">每张参考图不超过 50 MB；时长为 2-10 秒，超过 10 秒远端会拒绝。</span>
              <Tooltip title={submitBlockReason || undefined}>
                <span className="studio-submit-tooltip-wrap">
                  <Button type="primary" size="large" loading={submitting} disabled={!ready} aria-label={submitBlockReason ? `开始生成（${submitBlockReason}）` : "开始生成"} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                    {submitting ? "提交中" : "开始生成"}
                  </Button>
                </span>
              </Tooltip>
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
          acceptReference(selected)
        }}
      />

      <Modal open={previewIndex !== null} footer={null} title={`参考图 ${(previewIndex ?? 0) + 1}`} onCancel={() => setPreviewIndex(null)} width={560} destroyOnHidden>
        {previewIndex !== null && references[previewIndex] ? <Image src={references[previewIndex].preview} alt={`参考图 ${(previewIndex ?? 0) + 1} 预览`} className="w-full" /> : null}
      </Modal>
    </div>
  )
}
