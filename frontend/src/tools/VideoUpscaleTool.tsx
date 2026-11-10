import { Button, Modal, Radio, Spin, message } from "antd"
import { ArrowLeft, MonitorUp, Sparkles, Upload, Video } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  UPSCALE_ENGINE_LABEL,
  UPSCALE_ENGINE_RELAYVSR,
  UPSCALE_ENGINE_RTX,
  UPSCALE_ENGINE_SEEDVR2,
  upscaleSourceError,
  type UpscaleEngine,
  type UpscaleSourceAsset,
} from "../generation/upscale"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import "./motion-transfer-tool.css"

function assetFrom(file: File): UpscaleSourceAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

type SavedRound = { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>; reference_count: number; references: ReferenceSource[] }

const ENGINE_PROMPT: Record<UpscaleEngine, string> = {
  [UPSCALE_ENGINE_RTX]: "2x 超分",
  [UPSCALE_ENGINE_SEEDVR2]: "SeedVR2 高清增强",
  [UPSCALE_ENGINE_RELAYVSR]: "RelayVSR 2x 细节超分",
}

export default function VideoUpscaleTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<UpscaleSourceAsset | null>(null)
  const [sourcePreview, setSourcePreview] = useState(false)
  const [engine, setEngine] = useState<UpscaleEngine>(UPSCALE_ENGINE_RTX)
  const [submitting, setSubmitting] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const submissionPending = useRef(false)

  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")
  useEffect(() => {
    if (!restoreJobId) return
    const mode = restoreRoundId?.startsWith("seedvr2")
      ? UPSCALE_ENGINE_SEEDVR2
      : restoreRoundId?.startsWith("relayvsr") ? UPSCALE_ENGINE_RELAYVSR : undefined
    if (mode) setEngine(mode)
    let active = true
    setRestoring(true)
void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item: SavedRound) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || ![UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2, UPSCALE_ENGINE_RELAYVSR].includes(round.mode as UpscaleEngine)) throw new Error("此任务不是当前视频超分工作流")
      const sources = roundReferenceSources(job, round).map((source) => ({ ...source, kind: "video" as const }))
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (!files.length) throw new Error("原片素材不完整，请重新上传")
      setSource(assetFrom(files[0]))
    }).catch((error: unknown) => { if (active) message.error(apiErrorMessage(error, "恢复超分素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId])

  useEffect(() => {
    const preview = source?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [source?.preview])

  const acceptVideo = (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = upscaleSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    setSource(assetFrom(candidate))
  }

  // 预览/悬浮工具条「视频超清」跳转进来时，直接把这条成片当作要超分的原片。
  const handoffRestoring = useMediaHandoffPrefill(searchParams, acceptVideo)

  const ready = Boolean(source) && !submitting && !restoring && !handoffRestoring

  const submit = async () => {
    if (submissionPending.current) return
    if (!source) {
      message.warning("请上传要超分的原片视频")
      return
    }
    const form = new FormData()
    form.set("mode", engine)
    form.set("prompt", ENGINE_PROMPT[engine])
    form.set("options", "{}")
    form.append("references", source.file)
    submissionPending.current = true
    setSubmitting(true)
    try {
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("超分任务已提交，可在生成页查看进度")
      navigate(generateJobPath("video", payload.id))
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
          <h1>视频超分</h1>
          <p>低清视频一键放大 2 倍，RTX 快速增强、RelayVSR 细节重建或 SeedVR2 补回细节</p>
        </div>
      </header>

      {restoring || handoffRestoring ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip={restoring ? "正在恢复超分素材" : "正在读取原片"} /></div>
      ) : (
        <section className="studio-motion-card" aria-label="视频超分创作">
          <div className="studio-tool-motion-materials">
            <div className="studio-motion-material-row">
              <div className="studio-motion-material" data-kind="video">
                {source ? (
                  <video src={source.preview} muted playsInline
                    onLoadedMetadata={(event) => {
                      const seconds = event.currentTarget.duration
                      setSource((current) => current
                        ? { ...current, duration: Number.isFinite(seconds) ? seconds : undefined }
                        : current)
                    }}
                  />
                ) : (
                  <div className="studio-motion-material-empty">
                    <MonitorUp size={22} aria-hidden="true" />
                    <span>原片视频</span>
                  </div>
                )}
                <div className="studio-motion-material-actions">
                  {source ? (
                    <>
                      <Button size="small" onClick={() => setSourcePreview(true)}>预览</Button>
                      <Button size="small" danger onClick={() => setSource(null)}>移除</Button>
                    </>
                  ) : (
                    <Button size="small" type="primary" onClick={() => videoInputRef.current?.click()}>选择文件</Button>
                  )}
                </div>
              </div>
              <div className="studio-motion-material" data-kind="engine">
                <div className="studio-motion-material-empty" style={{ gap: 10 }}>
                  <MonitorUp size={22} aria-hidden="true" />
                  <span style={{ fontSize: 14 }}>增强引擎</span>
                </div>
                <div className="studio-motion-material-actions" style={{ padding: "8px 12px 12px" }}>
                  <Radio.Group
                    aria-label="增强引擎"
                    value={engine}
                    onChange={(event) => setEngine(event.target.value as UpscaleEngine)}
                    options={[
                      { value: UPSCALE_ENGINE_RTX, label: UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_RTX] },
                      { value: UPSCALE_ENGINE_RELAYVSR, label: UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_RELAYVSR] },
                      { value: UPSCALE_ENGINE_SEEDVR2, label: UPSCALE_ENGINE_LABEL[UPSCALE_ENGINE_SEEDVR2] },
                    ]}
                  />
                </div>
              </div>
            </div>
            <div className="studio-motion-upload-actions">
              <Button icon={<Upload size={14} />} onClick={() => videoInputRef.current?.click()}>上传原片视频</Button>
            </div>
            <p className="studio-motion-selection-help">
              RTX 引擎秒级完成固定 2x 放大；RelayVSR 用分块重建细节，480p 约一分钟、1080p 可能因显存不足被拒；
              SeedVR2 生成式增强较慢但能补回细节。输出分辨率跟随原片 2 倍，音轨保持不变。{restoring ? "正在恢复素材…" : ""}
            </p>
          </div>

          <div className="studio-motion-settings">
            <div className="studio-motion-footer">
              <span className="studio-tool-motion-note">原片不超过 500 MB；超分倍率固定 2x。</span>
              <Button type="primary" size="large" loading={submitting} disabled={!ready} icon={<Sparkles size={19} />} onClick={() => void submit()}>
                {submitting ? "提交中" : "开始增强"}
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
          acceptVideo(selected)
        }}
      />

      <Modal open={sourcePreview} footer={null} title="原片视频" onCancel={() => setSourcePreview(false)} width={640} destroyOnHidden>
        {source ? <video src={source.preview} controls autoPlay className="w-full rounded-lg" /> : null}
      </Modal>
    </div>
  )
}
