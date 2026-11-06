import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Empty, Select, Spin, Switch, message } from "antd"
import { ArrowLeft, RefreshCw, ScanFace, Sparkles, Upload, Video } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { FACE_RESTORE_WORKFLOW, facePoint, faceRestoreReferences, faceVideoError,
  type FacePoint, type FaceRestoreJob, type FaceSourceLocator } from "../generation/face-restore"
import { motionToolDefaults, motionToolOptions, type MotionReferenceAsset, type ToolOptionDefinition } from "../generation/motion-transfer"
import { createLocalId } from "../lib/utils"
import { generateJobPath, PATHS } from "../paths"
import { readMediaHandoff } from "../media-handoff"
import { restoreReferenceFiles, roundReferenceSources } from "../reference-assets"
import MotionSubjectPicker from "./MotionSubjectPicker"
import "./motion-transfer-tool.css"
import "./face-restore-tool.css"

type Workflow = { parameters: { name: string; schema?: { properties?: Record<string, ToolOptionDefinition> } }[] }
const asset = (file: File): MotionReferenceAsset => ({ id: createLocalId(), file, preview: URL.createObjectURL(file) })
const errorText = (error: unknown, fallback: string) => error instanceof Error ? error.message : apiErrorMessage(error, fallback)

export default function FaceRestoreTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const baseInput = useRef<HTMLInputElement>(null)
  const originalInput = useRef<HTMLInputElement>(null)
  const pending = useRef(false)
  const initialized = useRef(false)
  const [base, setBase] = useState<MotionReferenceAsset | null>(null)
  const [original, setOriginal] = useState<MotionReferenceAsset | null>(null)
  const [point, setPoint] = useState<FacePoint | null>(null)
  const [origin, setOrigin] = useState<FaceSourceLocator | null>(null)
  const [values, setValues] = useState<Record<string, string | number | boolean>>({})
  const [picking, setPicking] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [restoreError, setRestoreError] = useState("")
  const [sourceHint, setSourceHint] = useState("")
  const workflow = useQuery({ queryKey: ["workflow", FACE_RESTORE_WORKFLOW], queryFn: () => api<Workflow>(`/api/modes/${FACE_RESTORE_WORKFLOW}`) })
  const capability = useQuery({ queryKey: ["face-restore-capabilities"],
    queryFn: () => api<{ available: boolean; reason: string }>("/api/face-restore/capabilities"), staleTime: 30_000 })
  const schema = workflow.data?.parameters.find((p) => p.name === "options")?.schema?.properties
  const controls = useMemo(() => motionToolOptions(schema), [schema])
  useEffect(() => {
    if (!schema || initialized.current) return
    initialized.current = true
    setValues(motionToolDefaults(schema))
  }, [schema])
  const jobId = params.get("job")
  const roundId = params.get("round")
  const handoff = readMediaHandoff(params)
  const handoffKey = handoff ? `${handoff.jobId}:${handoff.generationItemId}:${handoff.outputIndex}` : ""
  useEffect(() => {
    if (!schema || (!jobId && !handoff)) return
    let active = true
    setRestoring(true); setRestoreError(""); setSourceHint("")
    const load = (id: string) => api<FaceRestoreJob>(`/api/jobs/${encodeURIComponent(id)}`)
    void (async () => {
      if (jobId) {
        const job = await load(jobId)
        const round = roundId ? job.rounds.find((r) => r.id === roundId) : job.rounds.at(-1)
        if (!round || round.mode !== FACE_RESTORE_WORKFLOW) throw new Error("此任务不是人脸高清修复，请从成片选择修复入口")
        const files = await restoreReferenceFiles(roundReferenceSources(job, round).map((r) => ({ ...r, kind: "video" })))
        if (!active) return
        if (!files[0]) throw new Error("修复素材不完整，请重新上传")
        setBase(asset(files[0])); setOriginal(files[1] ? asset(files[1]) : null)
        setPoint(facePoint(round.options.target_point)); setValues({ ...motionToolDefaults(schema), ...round.options })
        setOrigin(job.source ?? null)
      } else if (handoff) {
        const locator = { job_id: handoff.jobId, generation_item_id: handoff.generationItemId, output_index: handoff.outputIndex }
        const job = await load(handoff.jobId)
        const restored = await faceRestoreReferences(job, locator, load)
        const files = await restoreReferenceFiles(restored.references)
        if (!active) return
        setBase(asset(files[0])); setOriginal(files[1] ? asset(files[1]) : null)
        setOrigin(locator); setPoint(null); setSourceHint(restored.warning)
      } else {
        throw new Error("成片来源不完整，请返回成片重新选择")
      }
    })().catch((error: unknown) => { if (active) setRestoreError(errorText(error, "读取修复素材失败，请重新上传")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [jobId, roundId, handoffKey, schema])
  useEffect(() => { const url = base?.preview; return () => { if (url) URL.revokeObjectURL(url) } }, [base?.preview])
  useEffect(() => { const url = original?.preview; return () => { if (url) URL.revokeObjectURL(url) } }, [original?.preview])

  const chooseFile = (file: File | undefined, raw: boolean) => {
    if (!file) return
    const error = faceVideoError(file)
    if (error) { message.warning(error); return }
    if (raw) setOriginal(asset(file))
    else { setBase(asset(file)); setOriginal(null); setPoint(null); setOrigin(null) }
    setRestoreError(""); setSourceHint("")
  }
  const ready = Boolean(base && point && workflow.data && capability.data?.available) && !restoring && !submitting
  const submit = async () => {
    if (pending.current || !ready || !base || !point) return
    pending.current = true; setSubmitting(true)
    const form = new FormData()
    form.set("mode", FACE_RESTORE_WORKFLOW)
    form.set("options", JSON.stringify({ ...values, target_point: JSON.stringify(point) }))
    form.append("references", base.file)
    if (original) form.append("references", original.file)
    if (origin) {
      form.set("source_job_id", origin.job_id); form.set("source_generation_item_id", origin.generation_item_id)
      form.set("source_output_index", String(origin.output_index))
    }
    try {
      const response = await fetch("/api/jobs", { method: "POST", headers: { "X-CSRF-Token": csrfToken }, body: form })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交人脸修复失败"))
      message.success("人脸修复任务已提交")
      navigate(generateJobPath("video", payload.id))
    } catch (error) { message.error(errorText(error, "提交人脸修复失败")) }
    finally { pending.current = false; setSubmitting(false) }
  }

  return <div className="studio-tools-page studio-motion-tool studio-face-restore-tool">
    <header className="studio-motion-hero">
      <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate(PATHS.tools)}>返回 AI 工具</Button>
      <div className="studio-motion-hero-copy"><h1>人脸高清修复</h1><p>修复选中的模糊人脸，保留视频中的其他人物、身体与背景</p></div>
    </header>
    {workflow.isLoading || restoring ? <div className="grid min-h-[220px] place-items-center"><Spin tip={restoring ? "正在关联视频与高清前原片" : "正在读取修复设置"} /></div>
      : workflow.isError ? <Empty description="人脸修复设置读取失败"><Button onClick={() => void workflow.refetch()}>重新读取</Button></Empty>
      : <section className="studio-motion-card" aria-label="人脸高清修复创作">
        <div className="studio-tool-motion-materials">
          {restoreError ? <Alert type="error" title={restoreError} showIcon /> : null}
          {sourceHint ? <Alert type="info" title={sourceHint} showIcon /> : null}
          <div className="studio-motion-material-row">
            {[{ value: base, raw: false, label: "待修复视频" }, { value: original, raw: true, label: "高清前原片（可选）" }].map(({ value, raw, label }) => <div className="studio-motion-material" data-kind="video" key={label}>
              <h2 className="studio-face-source-label">{label}</h2>
              {value ? <video src={value.preview} controls muted playsInline preload="metadata" aria-label={label} />
                : <div className="studio-motion-material-empty">{raw ? <Upload size={24} /> : <Video size={24} />}<span>{label}</span></div>}
              <div className="studio-motion-material-actions">
                <Button size="small" onClick={() => (raw ? originalInput : baseInput).current?.click()}>{value ? "更换视频" : "上传视频"}</Button>
                {value ? <Button size="small" danger onClick={() => {
                  if (raw) setOriginal(null)
                  else { setBase(null); setPoint(null); setOriginal(null); setOrigin(null) }
                }}>移除</Button> : null}
              </div>
            </div>)}
          </div>
          <div className="studio-motion-upload-actions">
            <Button icon={<ScanFace size={16} />} disabled={!base} onClick={() => setPicking(true)}>{point ? "重新选择人脸" : "选择要修复的人脸"}</Button>
            <span className="studio-motion-selection-help">{point ? "已选中 1 个人脸" : "在视频首帧点击人脸中心"}</span>
          </div>
          <p className="studio-motion-selection-help">{original ? "已关联高清前原片：用原片修脸，身体和背景沿用待修复视频。" : "当前视频将作为修脸输入。若已有智能高清前的原片，可一并上传同一片段。"}</p>
          <p className="studio-motion-selection-help">保持视频尺寸。短暂遮挡时保留原画面；五官和表情细节可能重建，可先试前 5 秒。</p>
        </div>
        <div className="studio-motion-settings">
          {capability.isError || capability.data?.available === false ? <Alert showIcon type="warning" title={capability.data?.reason || "渲染服务暂不可用"}
            action={<Button size="small" icon={<RefreshCw size={14} />} onClick={() => void capability.refetch()}>重新检查</Button>} /> : null}
          <div className="studio-motion-param-grid">
            {controls.map(({ name, definition, control, options }) => <label className="studio-motion-param" key={name}><span>{definition.label}</span>
              {control === "switch" ? <Switch aria-label={definition.label} checked={Boolean(values[name] ?? definition.default)} onChange={(value) => setValues((s) => ({ ...s, [name]: value }))} />
                : <Select aria-label={definition.label} value={String(values[name] ?? definition.default)} options={options} onChange={(value) => setValues((s) => ({ ...s, [name]: value }))} />}
            </label>)}
          </div>
          <div className="studio-motion-footer"><span className="studio-tool-motion-note">每次修复一个人脸，视频不超过 500 MB</span>
            <Button type="primary" size="large" icon={<Sparkles size={18} />} disabled={!ready} loading={submitting} onClick={() => void submit()}>开始修复</Button>
          </div>
        </div>
      </section>}
    <input ref={baseInput} type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" className="hidden" aria-label="上传待修复视频"
      onChange={(e) => { chooseFile(e.target.files?.[0], false); e.target.value = "" }} />
    <input ref={originalInput} type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" className="hidden" aria-label="上传高清前原片"
      onChange={(e) => { chooseFile(e.target.files?.[0], true); e.target.value = "" }} />
    <MotionSubjectPicker asset={picking ? base : null} video purpose="face" points={point ? [{ ...point, exclude: false }] : []}
      onChange={(points) => setPoint(points[0] ? { x: points[0].x, y: points[0].y } : null)} onClose={() => setPicking(false)} />
  </div>
}
