import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Spin, message } from "antd"
import { ArrowLeft, ImageUp, RefreshCw, Sparkles } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { IMAGE_OUTPAINT_WORKFLOW, imageToolSourceError } from "../generation/image-edit"
import { generateJobPath } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import { createLocalId } from "../lib/utils"
import ImageOutpaintEditor, { type OutpaintEditorPayload } from "./ImageOutpaintEditor"
import "./image-outpaint-tool.css"
import "./motion-transfer-tool.css"

type SourceAsset = { id: string; file: File; preview: string; width: number; height: number }

function assetFrom(file: File, onReady: (asset: SourceAsset) => void, onFail: () => void): SourceAsset {
  const preview = URL.createObjectURL(file)
  const asset: SourceAsset = { id: createLocalId(), file, preview, width: 0, height: 0 }
  const image = new window.Image()
  image.onload = () => {
    asset.width = image.naturalWidth
    asset.height = image.naturalHeight
    onReady(asset)
  }
  image.onerror = () => {
    URL.revokeObjectURL(preview)
    onFail()
  }
  image.src = preview
  return asset
}

/** 图片扩图：上传原图后进入即梦式编辑器，拖拽扩展范围或选倍数/画幅，模型向四周自然延伸。 */
export default function ImageOutpaintTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<SourceAsset | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const submissionPending = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", IMAGE_OUTPAINT_WORKFLOW],
    queryFn: () => api<{ id: string; available?: boolean; unavailable_reason?: string }>(`/api/modes/${IMAGE_OUTPAINT_WORKFLOW}`),
    staleTime: 1000 * 60,
  })

  useEffect(() => {
    const preview = source?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [source?.preview])

  const acceptSource = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    assetFrom(
      candidate,
      (asset) => {
        setSource(asset)
        setEditorOpen(true)
      },
      () => message.warning("图片无法读取，请更换文件"),
    )
  }

  const unavailable = workflowQuery.data && workflowQuery.data.available === false
  // 预览/悬浮工具条「扩图」跳转进来时，直接把该结果图当作原图并打开编辑器。
  const restoring = useMediaHandoffPrefill(params, acceptSource)

  const submit = async (payload: OutpaintEditorPayload) => {
    if (submissionPending.current || !source) return
    const form = new FormData()
    form.set("mode", IMAGE_OUTPAINT_WORKFLOW)
    form.set("prompt", payload.prompt)
    form.set("options", JSON.stringify({
      target_width: payload.targetWidth,
      target_height: payload.targetHeight,
      target_offset_x: payload.offsetX,
      target_offset_y: payload.offsetY,
    }))
    form.append("references", source.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const body = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(body, "提交任务失败"))
      message.success("扩图任务已提交，可在生成页查看进度")
      setEditorOpen(false)
      navigate(generateJobPath("image", body.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  return (
    <div className="studio-tools-page studio-motion-tool studio-outpaint-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>图片扩图</h1>
          <p>拖拽扩展范围或选择倍数 / 预设画幅，画面向四周自然延伸，原区域保持不变</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取图片扩图能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-motion-card" aria-label="图片扩图创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row" data-single>
              <div className="studio-motion-material" data-kind="mask">
                {source ? (
                  <img
                    src={source.preview}
                    alt="原图预览"
                    role="button"
                    aria-label="调整扩图范围"
                    onClick={() => setEditorOpen(true)}
                  />
                ) : (
                  <div className="studio-motion-material-empty">
                    <ImageUp size={22} aria-hidden="true" />
                    <span>原图</span>
                  </div>
                )}
                <div className="studio-motion-material-actions">
                  {source ? (
                    <>
                      <Button size="small" type="primary" onClick={() => setEditorOpen(true)}>调整扩图范围</Button>
                      <Button size="small" danger onClick={() => setSource(null)}>移除</Button>
                    </>
                  ) : (
                    <Button size="small" type="primary" onClick={() => inputRef.current?.click()}>选择文件</Button>
                  )}
                </div>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<ImageUp size={14} />} onClick={() => inputRef.current?.click()}>
                {source ? "更换原图" : "上传原图"}
              </Button>
            </div>
            <p className="studio-motion-selection-help">
              支持 JPG / PNG 等常见图片格式，单张不超过 20 MB。上传后在扩图编辑器中拖拽白框或选择倍数、
              画幅比例，扩展区域由模型补全，原区域像素与原图完全一致。{restoring ? "正在恢复素材…" : ""}
            </p>
            {unavailable ? <p className="studio-motion-validation" role="alert">{workflowQuery.data?.unavailable_reason || "图片工具暂不可用"}</p> : null}
          </div>

          <div className="studio-motion-settings">
            <div className="studio-tool-motion-options" />
            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">扩展区域按画布范围生成，原区域像素与原图完全一致。</span>
              <Button
                type="primary"
                size="large"
                icon={<Sparkles size={19} />}
                disabled={!source || Boolean(unavailable) || restoring}
                onClick={() => setEditorOpen(true)}
              >
                开始扩图
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
          acceptSource(selected)
        }}
      />

      {source && source.width > 0 ? (
        <ImageOutpaintEditor
          source={{ preview: source.preview, width: source.width, height: source.height }}
          submitting={submitting}
          onApply={(payload) => void submit(payload)}
          onCancel={() => setEditorOpen(false)}
        />
      ) : null}
    </div>
  )
}
