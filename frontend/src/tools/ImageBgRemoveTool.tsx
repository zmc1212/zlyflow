import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Spin, message } from "antd"
import { ArrowLeft, FolderOpen, ImageUp } from "lucide-react"
import { useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { IMAGE_BACKGROUND_REMOVE_WORKFLOW, imageToolSourceError } from "../generation/image-edit"
import { PATHS } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import AssetPickerModal from "./AssetPickerModal"
import "./image-bg-remove.css"
import "./motion-transfer-tool.css"
import "./tools.css"

/**
 * 图片去背景落地页（对照即梦交互）：上传 / 从资产选取后直接创建任务，
 * 并跳转到画布编辑器（ImageBgRemoveEditor）等待 SAM3 结果与手动修正。
 */
export default function ImageBgRemoveTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", IMAGE_BACKGROUND_REMOVE_WORKFLOW],
    queryFn: () => api<{ id: string; available?: boolean; unavailable_reason?: string }>(
      `/api/modes/${IMAGE_BACKGROUND_REMOVE_WORKFLOW}`,
    ),
    staleTime: 1000 * 60,
  })

  const unavailable = workflowQuery.data && workflowQuery.data.available === false

  const startFrom = async (candidate: File | undefined | null) => {
    if (!candidate || submittingRef.current || unavailable) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    submittingRef.current = true
    setSubmitting(true)
    try {
      const form = new FormData()
      form.set("mode", IMAGE_BACKGROUND_REMOVE_WORKFLOW)
      // 留空由后端 default_prompt 兜底（主体描述交给画布阶段按需修正）。
      form.set("prompt", "")
      form.append("references", candidate)
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "创建去背景任务失败"))
      navigate(`${PATHS.toolImageBgRemoveEditor}?job=${encodeURIComponent(payload.id)}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建去背景任务失败")
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  // 预览/悬浮工具条「抠图」跳转进来时：本页没有待提交态，读到素材即建任务进画布。
  const restoring = useMediaHandoffPrefill(params, startFrom)

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate(PATHS.tools)}>
          返回 AI 工具
        </Button>
      </header>

      <section className="bgremove-landing" aria-label="图片去背景">
        <div className="bgremove-visual" aria-hidden="true">
          <svg viewBox="0 0 460 230" role="img">
            <defs>
              <linearGradient id="bgremove-sky" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#7fd6d0" />
                <stop offset="1" stopColor="#4aa8b8" />
              </linearGradient>
              <pattern id="bgremove-checker" width="20" height="20" patternUnits="userSpaceOnUse">
                <rect width="20" height="20" fill="#2a2d34" />
                <rect width="10" height="10" fill="#3a3f47" />
                <rect x="10" y="10" width="10" height="10" fill="#3a3f47" />
              </pattern>
              <clipPath id="bgremove-left"><rect x="0" y="0" width="230" height="230" /></clipPath>
              <clipPath id="bgremove-right"><rect x="230" y="0" width="230" height="230" /></clipPath>
            </defs>
            <rect width="460" height="230" fill="url(#bgremove-checker)" />
            <g clipPath="url(#bgremove-left)">
              <rect width="230" height="230" fill="url(#bgremove-sky)" />
              <circle cx="64" cy="56" r="22" fill="#ffe9a8" />
              <path d="M0 148 Q 52 106 110 134 T 230 140 L230 230 L0 230 Z" fill="#2f5d6b" />
              <path d="M0 178 Q 70 146 150 170 T 230 176 L230 230 L0 230 Z" fill="#22434f" />
            </g>
            <g clipPath="url(#bgremove-right)">
              <path d="M230 148 Q 282 106 340 134 T 460 140 L460 230 L230 230 Z" fill="#2f5d6b" />
              <path d="M230 178 Q 300 146 380 170 T 460 176 L460 230 L230 230 Z" fill="#22434f" />
            </g>
            <rect x="228" y="0" width="4" height="230" fill="#f4f6f8" opacity="0.9" />
          </svg>
        </div>
        <div className="bgremove-hero-copy">
          <h1>图片去背景</h1>
          <p>上传图片，自动去掉主体周围的背景，提取需要的人物或物品；可在画布里用画笔修正边缘，方便后续组合与编辑。</p>
        </div>
        <div
          className={`bgremove-drop${dragActive ? " is-active" : ""}`}
          onDragOver={(event) => { event.preventDefault(); setDragActive(true) }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragActive(false)
            void startFrom(event.dataTransfer.files?.[0])
          }}
        >
          <span className="bgremove-drop-hint">将文件拖至此处添加</span>
          <div className="bgremove-drop-actions">
            <Button icon={<ImageUp size={14} />} onClick={() => inputRef.current?.click()} disabled={Boolean(unavailable) || restoring}>
              从本地上传
            </Button>
            <Button icon={<FolderOpen size={14} />} onClick={() => setPickerOpen(true)} disabled={Boolean(unavailable) || restoring}>
              从资产选取
            </Button>
          </div>
          <p className="bgremove-note">支持 JPG / PNG 等常见图片格式，单张不超过 20 MB；提交后自动进入画布等待识别结果。</p>
          {restoring || submitting ? (
            <div className="bgremove-drop-overlay"><Spin tip={restoring ? "正在读取图片…" : "正在创建画布任务…"} /></div>
          ) : null}
        </div>
        {unavailable ? (
          <Alert
            className="bgremove-alert"
            type="warning"
            showIcon
            message={workflowQuery.data?.unavailable_reason || "图片去背景暂不可用"}
          />
        ) : null}
        {workflowQuery.isError ? (
          <Alert
            className="bgremove-alert"
            type="error"
            showIcon
            message={`能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}
          />
        ) : null}
      </section>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          void startFrom(selected)
        }}
      />

      <AssetPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} onPick={(file) => void startFrom(file)} />
    </div>
  )
}
