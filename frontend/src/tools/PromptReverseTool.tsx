import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Input, Segmented, Spin, message } from "antd"
import { ArrowLeft, Copy, ImagePlus, RefreshCw, ScanSearch, Trash2, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { requestJson as api } from "../api"
import type { PromptReverseMediaType, PromptReverseResult } from "../prompt-reverse"
import { filesFromDataTransfer, promptReverseImageError, reversePromptFromImage } from "../prompt-reverse"
import AssetPickerModal from "./AssetPickerModal"

const MEDIA_TYPE_OPTIONS: { value: PromptReverseMediaType; label: string }[] = [
  { value: "video", label: "视频提示词" },
  { value: "image", label: "图片提示词" },
]

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "提示词反推失败"
}

export default function PromptReverseTool({
  csrfToken, onSendToComposer,
}: {
  csrfToken: string
  onSendToComposer: (target: PromptReverseMediaType, result: PromptReverseResult) => void
}) {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState("")
  const [reverseType, setReverseType] = useState<PromptReverseMediaType>("video")
  const [hint, setHint] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<PromptReverseResult | null>(null)
  const [chineseDraft, setChineseDraft] = useState("")
  const [englishDraft, setEnglishDraft] = useState("")
  const [pickerOpen, setPickerOpen] = useState(false)

  const visionQuery = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => api<{ message?: string | null; analysis_vision?: { available: boolean; model?: string | null } }>("/api/llm/status"),
    staleTime: 1000 * 60,
    retry: false,
  })
  const visionAvailable = visionQuery.data ? Boolean(visionQuery.data.analysis_vision?.available) : true

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const image = filesFromDataTransfer(event.clipboardData?.files ?? null)
      if (!image) return
      event.preventDefault()
      acceptFile(image)
    }
    document.addEventListener("paste", onPaste)
    return () => document.removeEventListener("paste", onPaste)
  }, [])

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const acceptFile = (candidate: File) => {
    const problem = promptReverseImageError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(candidate)
    setPreviewUrl(URL.createObjectURL(candidate))
    setError("")
    setResult(null)
  }

  const clearFile = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(null)
    setPreviewUrl("")
    setResult(null)
    setError("")
  }

  const runReverse = async () => {
    if (!file) {
      setError("请先上传或粘贴一张参考图")
      return
    }
    setSubmitting(true)
    setError("")
    try {
      const data = await reversePromptFromImage(csrfToken, file, reverseType, hint)
      setResult(data)
      setChineseDraft(data.chinese_prompt)
      setEnglishDraft(data.english_prompt)
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setSubmitting(false)
    }
  }

  const sendToComposer = () => {
    if (!result) return
    onSendToComposer(reverseType, {
      chinese_prompt: chineseDraft.trim() || result.chinese_prompt,
      english_prompt: englishDraft.trim() || result.english_prompt,
    })
  }

  const copyText = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value)
      message.success(`${label}已复制`)
    } catch {
      message.error("复制失败，请手动选择文本复制")
    }
  }

  return (
    <div className="studio-tools-page">
      <button type="button" className="studio-tool-back" onClick={() => navigate("/tools")}>
        <ArrowLeft size={14} />返回 AI 工具
      </button>

      <header className="studio-tool-hero-v2">
        <span className="studio-tool-hero-v2-art" aria-hidden="true">
          <span className="studio-tool-hero-v2-art-lines"><i /><i /><i /><i /></span>
          <span className="studio-tool-hero-v2-art-icon"><ScanSearch size={26} /></span>
        </span>
        <h1>提示词反推</h1>
        <p>上传图片或视频片段，解析画面与镜头语言，生成可直接复用的中英文创作提示词，为下一次创作提供参考。反推结果可直接填入生成页创作框。</p>
      </header>

      {!visionAvailable ? (
        <Alert
          type="warning"
          showIcon
          message="视觉模型尚未启用"
          description={visionQuery.data?.message || "请在管理设置 → VLM 视觉模型 中配置看图模型后再使用反推。"}
        />
      ) : null}

      {previewUrl ? (
        <section className="studio-tool-preview" aria-label="参考图">
          <img src={previewUrl} alt="参考图预览" />
          <div className="studio-tool-preview-body">
            <p className="studio-tool-preview-name">{file?.name}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={<Upload size={14} />} onClick={() => fileInputRef.current?.click()}>更换图片</Button>
              <Button danger icon={<Trash2 size={14} />} onClick={clearFile}>移除</Button>
            </div>
            <div>
              <label className="studio-tool-section-label">反推目标</label>
              <Segmented
                options={MEDIA_TYPE_OPTIONS}
                value={reverseType}
                onChange={(value) => setReverseType(value as PromptReverseMediaType)}
              />
            </div>
            <div>
              <label className="studio-tool-section-label">补充要求（可选）</label>
              <Input.TextArea
                value={hint}
                onChange={(event) => setHint(event.target.value)}
                placeholder="例如：强调电影感光影、突出人物表情，或排除画面中的文字"
                autoSize={{ minRows: 1, maxRows: 3 }}
                maxLength={200}
                showCount
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="primary" loading={submitting} disabled={!visionAvailable} icon={<ScanSearch size={14} />} onClick={() => void runReverse()}>
                {submitting ? "反推中" : "开始反推"}
              </Button>
              {error ? <span className="text-xs text-[var(--studio-danger)]">{error}</span> : null}
            </div>
          </div>
        </section>
      ) : (
        <button
          type="button"
          className={`studio-tool-upload ${dragOver ? "dragover" : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(event) => {
            if (!event.dataTransfer.types.includes("Files")) return
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            if (!event.dataTransfer.files.length) return
            event.preventDefault()
            setDragOver(false)
            const image = filesFromDataTransfer(event.dataTransfer.files)
            if (image) acceptFile(image)
          }}
        >
          <ImagePlus size={26} className="text-[var(--studio-text-subtle)]" />
          <span className="studio-tool-upload-title">将图片拖到此处，或粘贴（Ctrl+V）</span>
          <span className="studio-tool-upload-actions">
            <Button icon={<Upload size={14} />} onClick={(event) => { event.stopPropagation(); fileInputRef.current?.click() }}>从本地上传</Button>
            <Button icon={<RefreshCw size={14} />} onClick={(event) => { event.stopPropagation(); setPickerOpen(true) }}>从资产选取</Button>
          </span>
          <span className="studio-tool-upload-note">支持 jpg / png / webp / gif，不超过 8MB；先选择反推目标为视频提示词或图片提示词。</span>
          {error ? <Alert type="error" showIcon message={error} className="max-w-[420px]" /> : null}
        </button>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          if (selected) acceptFile(selected)
        }}
      />

      {submitting ? <div className="flex items-center justify-center gap-2 py-6 text-sm text-[var(--studio-text-secondary)]"><Spin size="small" />正在解析画面，通常需要十几秒…</div> : null}

      {result && !submitting ? (
        <section className="studio-tool-result" aria-label="反推结果">
          <div className="studio-tool-result-field">
            <div className="studio-tool-result-head">
              <label className="studio-tool-section-label">中文提示词（填入创作框）</label>
              <Button type="text" size="small" icon={<Copy size={13} />} onClick={() => void copyText(chineseDraft, "中文提示词")}>复制</Button>
            </div>
            <Input.TextArea
              value={chineseDraft}
              onChange={(event) => setChineseDraft(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 9 }}
              variant="borderless"
            />
          </div>
          <div className="studio-tool-result-field">
            <div className="studio-tool-result-head">
              <label className="studio-tool-section-label">英文提示词{reverseType === "video" ? "（生成页润色时会以它为参考）" : ""}</label>
              <Button type="text" size="small" icon={<Copy size={13} />} onClick={() => void copyText(englishDraft, "英文提示词")}>复制</Button>
            </div>
            <Input.TextArea
              value={englishDraft}
              onChange={(event) => setEnglishDraft(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 9 }}
              variant="borderless"
            />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button icon={<RefreshCw size={14} />} onClick={() => setResult(null)}>重新反推</Button>
            <Button type="primary" icon={<ScanSearch size={14} />} onClick={sendToComposer}>填入创作框</Button>
          </div>
        </section>
      ) : null}

      <AssetPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPick={(picked) => acceptFile(picked)}
      />
    </div>
  )
}
