import { Button, Modal, Spin, message } from "antd"
import { ArrowLeft, AudioLines, FileAudio2, Sparkles, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  STEM_SPLIT_MODE,
  isStemSplitAudio,
  stemSplitSourceError,
  type StemSplitSourceAsset,
} from "../generation/stem-split"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

function assetFrom(file: File): StemSplitSourceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }

export default function StemSplitTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const sourceInputRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<StemSplitSourceAsset | null>(null)
  const [sourcePreview, setSourcePreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const submissionPending = useRef(false)

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId) return
    let active = true
    setRestoring(true)
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item: SavedRound) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== STEM_SPLIT_MODE) throw new Error("此任务不是当前人声/伴奏分离工作流")
      const sources = roundReferenceSources(job, round)
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (!files.length) throw new Error("待分离素材不完整，请重新上传")
      setSource(assetFrom(files[0]))
    }).catch((error: unknown) => { if (active) message.error(apiErrorMessage(error, "恢复分离素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId])

  useEffect(() => {
    const preview = source?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [source?.preview])

  const acceptSource = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = stemSplitSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    setSource(assetFrom(candidate))
  }

  const ready = Boolean(source) && !submitting && !restoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!source) {
      message.warning("请上传要分离的音频或视频")
      return
    }
    const form = new FormData()
    form.set("mode", STEM_SPLIT_MODE)
    form.set("prompt", "分离人声与伴奏")
    form.set("options", "{}")
    form.append("references", source.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("分离任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const sourceIsAudio = source ? isStemSplitAudio(source.file) : false

  return (
    <div className="studio-tools-page studio-motion-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>人声/伴奏分离</h1>
          <p>上传音频或视频，一键分出干净人声与伴奏两条音轨</p>
        </div>
      </header>

      {restoring ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在恢复分离素材" /></div>
      ) : (
        <section className="studio-motion-card" aria-label="人声/伴奏分离创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row">
              <div className="studio-motion-material" data-kind="video">
                {source ? (
                  sourceIsAudio ? (
                    <div className="grid h-full w-full place-items-center text-[#8a93a6]">
                      <div className="flex flex-col items-center gap-2">
                        <FileAudio2 size={40} aria-hidden="true" />
                        <span className="max-w-[220px] truncate text-xs">{source.file.name}</span>
                      </div>
                    </div>
                  ) : (
                    <video src={source.preview} muted playsInline preload="metadata" />
                  )
                ) : (
                  <div className="studio-motion-material-empty">
                    <AudioLines size={22} aria-hidden="true" />
                    <span>待分离音频或视频</span>
                  </div>
                )}
                <div className="studio-motion-material-actions">
                  {source ? (
                    <>
                      {!sourceIsAudio && <Button size="small" onClick={() => setSourcePreview(true)}>预览</Button>}
                      <Button size="small" danger onClick={() => setSource(null)}>移除</Button>
                    </>
                  ) : (
                    <Button size="small" type="primary" onClick={() => sourceInputRef.current?.click()}>选择文件</Button>
                  )}
                </div>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<Upload size={14} />} onClick={() => sourceInputRef.current?.click()}>上传音频或视频</Button>
            </div>
            <p className="studio-motion-selection-help">
              支持歌曲、口播、视频原声等素材，分离后得到「人声音轨」与「伴奏音轨」两个文件。
              上传视频时会自动抽取其中的音轨。{restoring ? "正在恢复素材…" : ""}
            </p>
          </div>

          <div className="studio-motion-settings">
            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">素材不超过 300 MB；时长越长分离耗时越久。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始分离"}
              </Button>
            </div>
          </div>
        </section>
      )}

      <input
        ref={sourceInputRef}
        type="file"
        accept="audio/*,video/*,.mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.wma,.mp4,.mov,.webm,.mkv,.m4v,.avi"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          acceptSource(selected)
        }}
      />

      <Modal open={sourcePreview} footer={null} title="原片预览" onCancel={() => setSourcePreview(false)} width={640} destroyOnHidden>
        {source && !sourceIsAudio ? <video src={source.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>
    </div>
  )
}
