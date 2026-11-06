import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Image, Modal, Spin, message } from "antd"
import { ArrowLeft, ImageUp, RefreshCw, Sparkles, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { imageToolSourceError } from "../generation/image-edit"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

type SourceAsset = { id: string; file: File; preview: string }

export type ImageSourceToolConfig = {
  /** 后端工作流 ID（image-background-remove / image-layer-split）。 */
  workflow: string
  title: string
  tagline: string
  /** 结果说明，例如图层分离产出两张图。 */
  resultNote: string
  loadingTip: string
  successTip: string
}

function assetFrom(file: File): SourceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

/**
 * 单图上传 → 直接提交的图片工具页（图片去背景 / 图层分离共用）。
 * 参数全部由后端托管，页面只负责素材上传与提交。
 */
export default function ImageSourceToolPage({ config, csrfToken }: { config: ImageSourceToolConfig; csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<SourceAsset | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [restoring, setRestoring] = useState(false)
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

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== config.workflow) throw new Error("此任务不是当前工具的工作流")
      const sources = roundReferenceSources(job, round)
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (files.length !== 1) throw new Error("参考素材不完整，请重新上传")
      setSource(assetFrom(files[0]))
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复任务素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, config.workflow])

  const acceptSource = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    setSource(assetFrom(candidate))
  }

  const unavailable = workflowQuery.data && workflowQuery.data.available === false
  const ready = Boolean(source && workflowQuery.data && !unavailable) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!source) {
      message.warning("请上传原图")
      return
    }
    const form = new FormData()
    form.set("mode", config.workflow)
    // 留空由后端 default_prompt 兜底（图片工具不依赖提示词语义）。
    form.set("prompt", "")
    form.append("references", source.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success(config.successTip)
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
        <section className="studio-motion-card" aria-label={`${config.title}创作`}>
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row" data-single>
              <div className="studio-motion-material" data-kind="mask">
                {source ? (
                  <img src={source.preview} alt={`${config.title}原图预览`} onClick={() => setPreviewOpen(true)} />
                ) : (
                  <div className="studio-motion-material-empty">
                    <ImageUp size={22} aria-hidden="true" />
                    <span>原图</span>
                  </div>
                )}
                <div className="studio-motion-material-actions">
                  {source ? (
                    <>
                      <Button size="small" onClick={() => setPreviewOpen(true)}>预览</Button>
                      <Button size="small" danger icon={<Trash2 size={12} />} onClick={() => setSource(null)}>移除</Button>
                    </>
                  ) : (
                    <Button size="small" type="primary" onClick={() => inputRef.current?.click()}>选择文件</Button>
                  )}
                </div>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<ImageUp size={14} />} onClick={() => inputRef.current?.click()}>上传原图</Button>
            </div>
            <p className="studio-motion-selection-help">
              支持 JPG / PNG 等常见图片格式，单张不超过 20 MB。{config.resultNote}
              {restoring ? "正在恢复素材…" : ""}
            </p>
            {unavailable ? <p className="studio-motion-validation" role="alert">{workflowQuery.data?.unavailable_reason || "图片工具暂不可用"}</p> : null}
          </div>

          <div className="studio-motion-settings">
            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">处理在当前连接的 ComfyUI 实例上完成，纯本地免费。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始处理"}
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

      <Modal open={previewOpen} footer={null} title="原图" onCancel={() => setPreviewOpen(false)} width={560} destroyOnHidden>
        {source ? <Image src={source.preview} alt="原图预览" className="w-full" /> : null}
      </Modal>
    </div>
  )
}
