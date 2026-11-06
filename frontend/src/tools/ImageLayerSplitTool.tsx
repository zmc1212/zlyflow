import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Input, Spin, Tooltip, message } from "antd"
import { ArrowLeft, ImageUp, Minus, PenLine, Plus, Sparkles, SquareDashed, X } from "lucide-react"
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { IMAGE_LAYER_SPLIT_WORKFLOW, imageToolSourceError, type PhotoEditRegion } from "../generation/image-edit"
import { generateJobPath } from "../paths"
import { useMediaHandoffPrefill } from "../media-handoff-prefill"
import { restoreReferenceFiles, roundReferenceSources, type ReferenceSource } from "../reference-assets"
import { createLocalId } from "../lib/utils"
import "./photo-edit-editor.css"
import "./image-layer-split.css"

type SourceImage = { file: File; preview: string; width: number; height: number }
type SplitMode = "auto" | "box" | "description"

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5] as const

const SPLIT_MODE_TABS: Array<{ value: SplitMode; label: string; icon: typeof Sparkles }> = [
  { value: "auto", label: "智能拆分", icon: Sparkles },
  { value: "box", label: "框选拆分", icon: SquareDashed },
  { value: "description", label: "按描述拆分", icon: PenLine },
]

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
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

/** 框选矩形 → 千分比坐标串（与注册表 split_box 约定一致，相对原图左上角）。 */
function boxToPerMille(box: PhotoEditRegion, width: number, height: number): string {
  const format = (value: number) => clamp(Math.round(value * 10) / 10, 0, 1000)
  return [
    format(box.x / width * 1000),
    format(box.y / height * 1000),
    format((box.x + box.w) / width * 1000),
    format((box.y + box.h) / height * 1000),
  ].join(",")
}

/**
 * 图片图层拆分（对照即梦）：暗色舞台 + 三种拆分方式的指令条。
 * - 智能拆分：自动识别主体，直接提交；
 * - 框选拆分：在原图拖拽虚线框住要拆出的主体（单框，重新拖拽即替换）；
 * - 按描述拆分：填写主体描述提交。
 * 后端统一产出前景层 / 背景层两张透明 PNG（SAM3.1，纯本地免费）。
 */
export default function ImageLayerSplitTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const inputRef = useRef<HTMLInputElement>(null)
  const regionLayerRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)
  const submissionPending = useRef(false)

  const [source, setSource] = useState<SourceImage | null>(null)
  const [splitMode, setSplitMode] = useState<SplitMode>("auto")
  const [box, setBox] = useState<PhotoEditRegion | null>(null)
  const [draft, setDraft] = useState<PhotoEditRegion | null>(null)
  const [description, setDescription] = useState("")
  const [zoomIndex, setZoomIndex] = useState(2)
  const [dragOver, setDragOver] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const workflowQuery = useQuery({
    queryKey: ["tool-workflow", IMAGE_LAYER_SPLIT_WORKFLOW],
    queryFn: () => api<{ id: string; available?: boolean; unavailable_reason?: string }>(`/api/modes/${IMAGE_LAYER_SPLIT_WORKFLOW}`),
    staleTime: 1000 * 60,
  })

  useEffect(() => {
    const preview = source?.preview
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [source?.preview])

  // 从生成页「再次编辑」跳回时恢复原图素材。
  const restoreJobId = searchParams.get("job")
  const restoreRoundId = searchParams.get("round")

  const acceptSource = useCallback(async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    try {
      const size = await probeImage(candidate)
      setSource({ file: candidate, preview: URL.createObjectURL(candidate), ...size })
      setBox(null)
      setDraft(null)
      setZoomIndex(2)
    } catch {
      message.warning("图片无法读取，请换一张")
    }
  }, [])

  useEffect(() => {
    if (!restoreJobId) return
    let active = true
    setRestoring(true)
    type SavedRound = { id: string; mode: string; reference_count: number; references: ReferenceSource[] }
    void api<{ id: string; references: ReferenceSource[]; rounds: SavedRound[] }>(`/api/jobs/${encodeURIComponent(restoreJobId)}`).then(async (job) => {
      const round = restoreRoundId ? job.rounds.find((item) => item.id === restoreRoundId) : job.rounds.at(-1)
      if (!round || round.mode !== IMAGE_LAYER_SPLIT_WORKFLOW) throw new Error("此任务不是图层拆分任务")
      const sources = roundReferenceSources(job, round)
      const files = await restoreReferenceFiles(sources)
      if (!active) return
      if (files.length !== 1) throw new Error("参考素材不完整，请重新上传")
      await acceptSource(files[0])
    }).catch((error) => { if (active) message.error(apiErrorMessage(error, "恢复任务素材失败")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [restoreJobId, restoreRoundId, acceptSource])

  // 预览/悬浮工具条「图层拆分」跳转进来时，直接把该结果图当作原图。
  const handoffRestoring = useMediaHandoffPrefill(searchParams, acceptSource)

  // 舞台尺寸探测：缩放百分比相对“适配舞台”档位。
  // 舞台在工作流能力加载完成后才挂载，用回调 ref 才能拿到真实元素，否则缩放退化为原图 1:1 撑满页面。
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null)
  const [stageBox, setStageBox] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    if (!stageEl) return
    const measure = () => {
      const rect = stageEl.getBoundingClientRect()
      setStageBox({ width: rect.width, height: rect.height })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(stageEl)
    return () => observer.disconnect()
  }, [stageEl])
  const fitScale = useMemo(() => {
    if (!source || !stageBox.width || !stageBox.height) return 1
    return Math.min((stageBox.width - 48) / source.width, (stageBox.height - 48) / source.height, 1)
  }, [source, stageBox])
  const displayScale = fitScale * ZOOM_STEPS[zoomIndex]
  const frameWidth = source ? Math.max(1, Math.round(source.width * displayScale)) : 0
  const frameHeight = source ? Math.max(1, Math.round(source.height * displayScale)) : 0

  const toNaturalPoint = (event: React.PointerEvent): { x: number; y: number } | null => {
    const layer = regionLayerRef.current
    if (!layer || !source) return null
    const rect = layer.getBoundingClientRect()
    const scale = source.width / rect.width
    return {
      x: clamp((event.clientX - rect.left) * scale, 0, source.width),
      y: clamp((event.clientY - rect.top) * scale, 0, source.height),
    }
  }

  const onLayerPointerDown = (event: React.PointerEvent) => {
    if (!source || splitMode !== "box" || event.button !== 0) return
    const point = toNaturalPoint(event)
    if (!point) return
    event.preventDefault()
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    dragStartRef.current = point
    setDraft({ id: "draft", x: point.x, y: point.y, w: 0, h: 0 })
  }

  const onLayerPointerMove = (event: React.PointerEvent) => {
    const start = dragStartRef.current
    if (!start || !source) return
    const point = toNaturalPoint(event)
    if (!point) return
    setDraft({
      id: "draft",
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      w: Math.abs(point.x - start.x),
      h: Math.abs(point.y - start.y),
    })
  }

  const onLayerPointerUp = () => {
    const start = dragStartRef.current
    dragStartRef.current = null
    const pending = draft
    setDraft(null)
    if (!start || !pending || !source) return
    // 起手即视为重画：拖动过小（误触）时保留原框。
    const minSide = Math.max(4, Math.min(source.width, source.height) * 0.005)
    if (pending.w < minSide || pending.h < minSide) return
    setBox({ ...pending, id: createLocalId() })
  }

  const unavailable = workflowQuery.data && workflowQuery.data.available === false
  const ready = Boolean(source && workflowQuery.data && !unavailable) && !submitting && !restoring && !handoffRestoring
    && (splitMode === "auto" || (splitMode === "box" ? Boolean(box) : Boolean(description.trim())))

  const submit = async () => {
    if (submissionPending.current || !source) return
    if (splitMode === "box" && !box) {
      message.warning("请先在原图上拖拽框选要拆出的主体")
      return
    }
    if (splitMode === "description" && !description.trim()) {
      message.warning("请填写要拆出的主体描述")
      return
    }
    submissionPending.current = true
    setSubmitting(true)
    try {
      const options: Record<string, string> = { split_mode: splitMode }
      if (splitMode === "box" && box) options.split_box = boxToPerMille(box, source.width, source.height)
      const form = new FormData()
      form.set("mode", IMAGE_LAYER_SPLIT_WORKFLOW)
      // 智能拆分留空由后端 default_prompt 兜底；框选拆分的 prompt 不参与分割。
      form.set("prompt", splitMode === "description" ? description.trim() : "")
      form.set("options", JSON.stringify(options))
      form.append("references", source.file)
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("图层拆分任务已提交，可在生成页查看进度")
      navigate(generateJobPath("image", payload.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交任务失败")
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const hasSource = Boolean(source)
  const percent = Math.round(ZOOM_STEPS[zoomIndex] * 100)

  return (
    <div className="studio-tools-page studio-motion-tool studio-photo-tool">
      <header className="studio-motion-hero">
        <Button type="text" className="studio-tool-back" icon={<ArrowLeft size={14} />} onClick={() => navigate("/tools")}>返回 AI 工具</Button>
        <div className="studio-motion-hero-copy">
          <h1>图片图层分离</h1>
          <p>智能识别、框选或按描述拆分主体，得到前景层与背景层两张透明 PNG，可分别继续编辑</p>
        </div>
      </header>

      {workflowQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取图片图层分离能力" /></div>
      ) : workflowQuery.isError ? (
        <Empty description={`能力读取失败：${apiErrorMessage(workflowQuery.error, "请稍后重试")}`}>
          <Button icon={<ImageUp size={14} />} onClick={() => void workflowQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-photo-editor" aria-label="图片图层拆分创作">
          <div
            className={`studio-photo-stage${dragOver ? " is-dragover" : ""}`}
            ref={setStageEl}
            onDragOver={(event) => {
              if (hasSource) return
              event.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              if (hasSource) return
              event.preventDefault()
              setDragOver(false)
              void acceptSource(event.dataTransfer.files?.[0])
            }}
          >
            {source ? (
              <div className="studio-photo-stage-frame" style={{ width: frameWidth, height: frameHeight }}>
                <img className="studio-photo-stage-img" src={source.preview} alt="待拆分原图" draggable={false} />
                <div
                  className={`studio-photo-regions${splitMode === "box" ? "" : " is-idle"}`}
                  ref={regionLayerRef}
                  role="application"
                  aria-label="框选拆分画布"
                  onPointerDown={onLayerPointerDown}
                  onPointerMove={onLayerPointerMove}
                  onPointerUp={onLayerPointerUp}
                  onPointerLeave={onLayerPointerUp}
                >
                  {box
                    ? (
                      <div
                        className="studio-ls-region"
                        style={{
                          left: `${box.x / source.width * 100}%`,
                          top: `${box.y / source.height * 100}%`,
                          width: `${box.w / source.width * 100}%`,
                          height: `${box.h / source.height * 100}%`,
                        }}
                      >
                        <i className="studio-ls-handle" data-corner="tl" aria-hidden="true" />
                        <i className="studio-ls-handle" data-corner="tr" aria-hidden="true" />
                        <i className="studio-ls-handle" data-corner="bl" aria-hidden="true" />
                        <i className="studio-ls-handle" data-corner="br" aria-hidden="true" />
                        <button
                          type="button"
                          className="studio-photo-region-remove is-visible"
                          aria-label="移除框选"
                          onClick={(event) => {
                            event.stopPropagation()
                            setBox(null)
                          }}
                        ><X size={11} /></button>
                      </div>
                    )
                    : null}
                  {draft
                    ? (
                      <div
                        className="studio-photo-region is-draft"
                        style={{
                          left: `${draft.x / source.width * 100}%`,
                          top: `${draft.y / source.height * 100}%`,
                          width: `${draft.w / source.width * 100}%`,
                          height: `${draft.h / source.height * 100}%`,
                        }}
                      />
                    )
                    : null}
                </div>
              </div>
            ) : restoring || handoffRestoring ? (
              <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取图片…" /></div>
            ) : (
              <button type="button" className="studio-photo-stage-empty" onClick={() => inputRef.current?.click()}>
                <ImageUp size={26} aria-hidden="true" />
                <strong>上传要拆分的原图</strong>
                <span>点击选择或把图片拖到此处，支持 JPG / PNG 等常见格式，单张不超过 20 MB</span>
              </button>
            )}
          </div>

          <div className="studio-photo-toolbar">
            <span className="studio-ls-toolbar-note">
              {splitMode === "box"
                ? "在原图上按住拖拽，框住要拆出的主体；重新拖拽即替换当前框选。"
                : "拆分在当前连接的 ComfyUI 实例上完成，纯本地免费。"}
            </span>
            <span className="studio-photo-toolbar-spacer" />
            <span className="studio-photo-zoom" role="group" aria-label="舞台缩放">
              <Button size="small" type="text" aria-label="缩小" disabled={!hasSource || zoomIndex === 0} icon={<Minus size={14} />} onClick={() => setZoomIndex((index) => Math.max(0, index - 1))} />
              <span className="studio-photo-zoom-value" aria-live="polite">{percent}%</span>
              <Button size="small" type="text" aria-label="放大" disabled={!hasSource || zoomIndex === ZOOM_STEPS.length - 1} icon={<Plus size={14} />} onClick={() => setZoomIndex((index) => Math.min(ZOOM_STEPS.length - 1, index + 1))} />
            </span>
          </div>

          <div className={`studio-photo-promptbar studio-ls-bar${hasSource ? "" : " is-disabled"}`}>
            <div className="studio-ls-tabs" role="tablist" aria-label="拆分方式">
              {SPLIT_MODE_TABS.map((tab) => {
                const Icon = tab.icon
                return (
                  <button
                    key={tab.value}
                    type="button"
                    role="tab"
                    aria-selected={splitMode === tab.value}
                    className="studio-ls-tab"
                    data-active={splitMode === tab.value || undefined}
                    onClick={() => setSplitMode(tab.value)}
                  >
                    <Icon size={14} aria-hidden="true" />
                    <span>{tab.label}</span>
                  </button>
                )
              })}
            </div>
            <div className="studio-ls-body">
              {splitMode === "auto" ? (
                <p className="studio-ls-note">自动识别画面主体并拆出，前景层与背景层分别输出。</p>
              ) : null}
              {splitMode === "box" ? (
                box ? (
                  <span className="studio-ls-chip">
                    <SquareDashed size={13} aria-hidden="true" />
                    <span>框选 1 处</span>
                    <button type="button" className="studio-ls-chip-remove" aria-label="移除框选" onClick={() => setBox(null)}><X size={10} /></button>
                  </span>
                ) : (
                  <p className="studio-ls-note">在原图上拖拽，框住要拆出的主体。</p>
                )
              ) : null}
              {splitMode === "description" ? (
                <Input.TextArea
                  className="studio-photo-input"
                  aria-label="主体描述"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder={hasSource
                    ? "描述要拆出的主体，例如：书页上的书法大字。"
                    : "先上传原图，再描述要拆出的主体"}
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  maxLength={500}
                />
              ) : null}
              <Tooltip title={ready ? "提交拆分任务" : unavailable ? "图层拆分暂不可用" : !hasSource ? "请先上传原图" : splitMode === "box" ? "请先框选主体" : "请填写主体描述"}>
                <Button
                  type="primary"
                  className="studio-ls-confirm"
                  loading={submitting}
                  disabled={!ready}
                  icon={<Sparkles size={15} />}
                  onClick={() => void submit()}
                >
                  确认拆分
                </Button>
              </Tooltip>
            </div>
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
    </div>
  )
}
