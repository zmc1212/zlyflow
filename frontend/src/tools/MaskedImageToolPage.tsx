import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Input, Modal, Spin, message } from "antd"
import { ArrowLeft, Brush, ImageUp, Maximize2, Minimize2, RefreshCw, Sparkles } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { imageToolSourceError } from "../generation/image-edit"
import { generateJobPath } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import { createLocalId } from "../lib/utils"
import ImageMaskPainter, { type MaskPainterTool } from "./ImageMaskPainter"
import "./motion-transfer-tool.css"

type SourceAsset = { id: string; file: File; preview: string; width: number; height: number }

export type MaskedImageToolConfig = {
  workflow: string
  title: string
  /** 编辑弹窗标题（对齐即梦「局部重绘」弹窗）。 */
  modalTitle: string
  tagline: string
  /** 上传后进入编辑器的按钮文案。 */
  editorCta: string
  /** 画笔/橡皮/抓手默认工具。 */
  defaultTool: MaskPainterTool
  /** 提示词输入框的无障碍名称。 */
  promptAria: string
  promptRequired: boolean
  promptPlaceholder: string
  resultNote: string
  loadingTip: string
  successTip: string
  submitLabel: string
}

function probeImage(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const image = new window.Image()
    image.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: image.naturalWidth, height: image.naturalHeight })
    }
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error("图片无法读取"))
    }
    image.src = url
  })
}

/**
 * 「上传原图 → 即梦式编辑弹窗（涂抹遮罩 + 提示词 + 应用）」工具页（图片局部重绘 / 消除笔共用）。
 * 遮罩由内置编辑器生成（白色=编辑区），不需要用户单独上传遮罩图。
 */
export default function MaskedImageToolPage({ config, csrfToken }: { config: MaskedImageToolConfig; csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<SourceAsset | null>(null)
  const [mask, setMask] = useState<File | null>(null)
  const [tool, setTool] = useState<MaskPainterTool>(config.defaultTool)
  const [prompt, setPrompt] = useState("")
  const [promptExpanded, setPromptExpanded] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", config.workflow],
    queryFn: () => api<{ id: string; available?: boolean; unavailable_reason?: string }>(`/api/modes/${config.workflow}`),
    staleTime: 1000 * 60,
  })

  useEffect(() => {
    const preview = source?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [source?.preview])

  const acceptSource = async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    try {
      const size = await probeImage(candidate)
      setPromptExpanded(false)
      setSource({ id: createLocalId(), file: candidate, preview: URL.createObjectURL(candidate), ...size })
      setMask(null)
      setEditorOpen(true)
    } catch {
      message.warning("图片无法读取，请换一张")
    }
  }

  // 预览/悬浮工具条「用这张图继续编辑」跳转进来时，直接把该结果图当作原图素材。
  const restoring = useMediaHandoffPrefill(params, acceptSource)

  const onMaskReady = useCallback((next: File | null) => setMask(next), [])
  const onToolChange = useCallback((next: MaskPainterTool) => setTool(next), [])
  const openEditor = useCallback(() => setEditorOpen(true), [])
  const closeEditor = useCallback(() => { if (!submissionPending.current) setEditorOpen(false) }, [])

  const unavailable = workflowQuery.data && workflowQuery.data.available === false
  const instructionReady = config.promptRequired ? Boolean(prompt.trim()) : true
  const ready = Boolean(source && mask && instructionReady && workflowQuery.data && !unavailable) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!source) {
      message.warning("请上传原图")
      return
    }
    if (!mask) {
      message.warning("请先在图上涂抹要编辑的区域")
      return
    }
    if (!instructionReady) {
      message.warning(config.promptRequired ? "请填写编辑指令" : "提示词不能为空")
      return
    }
    const form = new FormData()
    form.set("mode", config.workflow)
    form.set("prompt", prompt.trim())
    form.append("references", source.file)
    form.append("references", mask)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success(config.successTip)
      setEditorOpen(false)
      navigate(generateJobPath("image", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>{config.title}</h1>
          <p>{config.tagline}</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip={config.loadingTip} /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card studio-masked-card" aria-label={`${config.title}创作`}>
          <div className="studio-masked-panel">
            {restoring && !source ? (
              <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取图片…" /></div>
            ) : source ? (
              <div className="studio-masked-source">
                <button
                  type="button"
                  className="studio-masked-source-thumb"
                  aria-label={`进入编辑：${config.modalTitle}`}
                  onClick={openEditor}
                >
                  <img src={source.preview} alt="已上传原图" draggable={false} />
                  <span className="studio-masked-source-veil"><Brush size={18} aria-hidden="true" />{config.editorCta}</span>
                </button>
                <div className="studio-masked-source-actions">
                  <Button type="primary" icon={<Brush size={15} />} onClick={openEditor}>{config.editorCta}</Button>
                  <Button icon={<ImageUp size={15} />} onClick={() => inputRef.current?.click()}>更换图片</Button>
                </div>
              </div>
            ) : (
              <div
                className={`studio-masked-dropzone${dragOver ? " is-dragover" : ""}`}
                role="button"
                tabIndex={0}
                aria-label="上传原图"
                onClick={() => inputRef.current?.click()}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") inputRef.current?.click()
                }}
                onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragOver(false)
                  void acceptSource(event.dataTransfer.files?.[0])
                }}
              >
                <ImageUp size={26} aria-hidden="true" />
                <strong>上传原图</strong>
                <span>点击选择或拖拽图片到此处</span>
                <span className="studio-masked-hint">支持 JPG / PNG 等常见图片格式，单张不超过 20 MB。{config.resultNote}</span>
              </div>
            )}
            {unavailable ? <p className="studio-motion-validation" role="alert">{workflowQuery.data?.unavailable_reason || "图片工具暂不可用"}</p> : null}
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
          void acceptSource(selected)
        }}
      />

      <Modal
        open={editorOpen}
        title={config.modalTitle}
        width={880}
        centered
        footer={null}
        onCancel={closeEditor}
        styles={{ header: { padding: "14px 20px", borderBottom: "1px solid var(--studio-border)" }, body: { padding: 16 } }}
      >
        {source ? (
          <div className="studio-inpaint-modal">
            <ImageMaskPainter
              key={source.id}
              imageUrl={source.preview}
              naturalSize={{ width: source.width, height: source.height }}
              tool={tool}
              onToolChange={onToolChange}
              onMaskReady={onMaskReady}
            />
            <div className="studio-inpaint-promptbar">
              <Input.TextArea
                aria-label={config.promptAria}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={config.promptPlaceholder}
                maxLength={1500}
                autoSize={promptExpanded ? { minRows: 4, maxRows: 8 } : { minRows: 1, maxRows: 1 }}
              />
              <Button
                type="text"
                className="studio-inpaint-prompt-expand"
                aria-label={promptExpanded ? "收起输入框" : "展开输入框"}
                icon={promptExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                onClick={() => setPromptExpanded((value) => !value)}
              />
            </div>
            <div className="studio-inpaint-footer">
              <span className="studio-inpaint-footer-note">{config.resultNote}</span>
              <Button
                type="primary"
                size="large"
                loading={submitting}
                disabled={!ready}
                icon={<Sparkles size={16} />}
                onClick={() => void submit()}
              >
                {config.submitLabel}
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
