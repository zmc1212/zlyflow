import { useQuery } from "@tanstack/react-query"
import { Button, Empty, Input, InputNumber, Select, Spin, Tooltip, message } from "antd"
import { ArrowLeft, ArrowUp, ImageUp, MapPin, Minus, Plus, Redo2, RefreshCw, Undo2, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import {
  PHOTO_EDIT_MAX_REFERENCES,
  PHOTO_EDIT_REGION_MAX,
  drawRegionAnnotation,
  imageToolSourceError,
  photoEditCountBounds,
  photoEditOptions,
  photoEditResolutionChoices,
  photoEditWorkflowChoices,
  regionAnnotationPromptSuffix,
  type PhotoEditModeDetail,
  type PhotoEditWorkflowChoice,
  type PhotoEditRegion,
} from "../generation/image-edit"
import { generateJobPath } from "../paths"
import { createLocalId } from "../lib/utils"
import "./motion-transfer-tool.css"
import "./photo-edit-editor.css"

type PhotoAsset = { id: string; file: File; preview: string }
type SourceImage = { file: File; preview: string; width: number; height: number }
type RegionThumb = { id: string; url: string }

type ModeEntry = PhotoEditModeDetail

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5] as const

function assetFrom(file: File): PhotoAsset {
  return { id: createLocalId(), file, preview: URL.createObjectURL(file) }
}

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

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("图片读取失败"))
    image.src = src
  })
}

/** 把单个区域裁成正方形缩略图 dataURL（底部指令条的区域芯片）。 */
function cropRegionThumb(image: HTMLImageElement, region: PhotoEditRegion, size = 48): string {
  const canvas = document.createElement("canvas")
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext("2d")
  if (!context) return ""
  const side = Math.max(region.w, region.h)
  context.fillStyle = "#0f1115"
  context.fillRect(0, 0, size, size)
  context.drawImage(
    image,
    region.x, region.y, region.w, region.h,
    (size - region.w / side * size) / 2, (size - region.h / side * size) / 2,
    region.w / side * size, region.h / side * size,
  )
  return canvas.toDataURL("image/jpeg", 0.72)
}

/** 在原图分辨率上渲染编号标注副本（虚线框 + 编号徽标），作为第 2 张参考图提交。 */
async function buildAnnotatedOverlay(source: SourceImage, regions: PhotoEditRegion[]): Promise<File | null> {
  const image = await loadImage(source.preview)
  const canvas = document.createElement("canvas")
  canvas.width = source.width
  canvas.height = source.height
  const context = canvas.getContext("2d")
  if (!context) return null
  context.drawImage(image, 0, 0, source.width, source.height)
  const unit = Math.max(2, Math.round(Math.min(source.width, source.height) / 220))
  regions.forEach((region, index) => {
    drawRegionAnnotation(context, region, index + 1, unit)
  })
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"))
  if (!blob) return null
  return new File([blob], "regions-annotated.png", { type: "image/png" })
}

/** 图片编辑：即梦式智能改图——原图舞台 + 编号区域标记 + 指令条，走 GRS 指令改图模型。 */
export default function PhotoEditTool({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const originalInputRef = useRef<HTMLInputElement>(null)
  const refsInputRef = useRef<HTMLInputElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const regionLayerRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)
  const submissionPending = useRef(false)

  const [source, setSource] = useState<SourceImage | null>(null)
  const [extraRefs, setExtraRefs] = useState<PhotoAsset[]>([])
  const [regionHistory, setRegionHistory] = useState<{ stack: PhotoEditRegion[][]; index: number }>({ stack: [[]], index: 0 })
  const [draft, setDraft] = useState<PhotoEditRegion | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [zoomIndex, setZoomIndex] = useState(2)
  const [dragOver, setDragOver] = useState(false)
  const [regionThumbs, setRegionThumbs] = useState<RegionThumb[]>([])
  const [workflowId, setWorkflowId] = useState<string | null>(null)
  const [resolution, setResolution] = useState<string | null>(null)
  const [count, setCount] = useState<number>(1)
  const [prompt, setPrompt] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const regions = regionHistory.stack[regionHistory.index] ?? []

  const modesQuery = useQuery({
    queryKey: ["tool-workflows", "photo-edit"],
    queryFn: () => api<{ modes: ModeEntry[] }>("/api/modes"),
    staleTime: 1000 * 60,
  })
  const modes = useMemo(() => modesQuery.data?.modes ?? [], [modesQuery.data])
  const choices: PhotoEditWorkflowChoice[] = photoEditWorkflowChoices(modes)
  // 初值直接派生自可选列表，避免首帧空选择；effect 只跟踪用户显式切换。
  const activeWorkflowId = workflowId ?? choices.find((item) => item.isDefault)?.id ?? choices[0]?.id ?? null
  const activeMode = modes.find((mode) => mode.id === activeWorkflowId)
  const selectedUnavailable = activeMode?.available === false
  const resolutionMeta = useMemo(() => photoEditResolutionChoices(activeMode), [activeMode])
  const countBounds = useMemo(() => photoEditCountBounds(activeMode), [activeMode])
  const effectiveResolution = resolution && resolutionMeta.values.includes(resolution) ? resolution : resolutionMeta.defaultValue
  const effectiveCount = clamp(Math.trunc(count) || 1, countBounds.min, countBounds.max)

  useEffect(() => {
    const previews = [source?.preview, ...extraRefs.map((asset) => asset.preview)].filter(Boolean) as string[]
    return () => { previews.forEach((preview) => URL.revokeObjectURL(preview)) }
  }, [source?.preview, extraRefs])

  // 舞台尺寸探测：缩放百分比相对“适配舞台”档位。
  const [stageBox, setStageBox] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const element = stageRef.current
    if (!element) return
    const observer = new ResizeObserver(() => {
      const rect = element.getBoundingClientRect()
      setStageBox({ width: rect.width, height: rect.height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const fitScale = useMemo(() => {
    if (!source || !stageBox.width || !stageBox.height) return 1
    return Math.min((stageBox.width - 48) / source.width, (stageBox.height - 48) / source.height, 1)
  }, [source, stageBox])
  const displayScale = fitScale * ZOOM_STEPS[zoomIndex]
  const frameWidth = source ? Math.max(1, Math.round(source.width * displayScale)) : 0
  const frameHeight = source ? Math.max(1, Math.round(source.height * displayScale)) : 0

  const overlayReserved = regions.length ? 1 : 0
  const extraRefCapacity = PHOTO_EDIT_MAX_REFERENCES - 1 - overlayReserved - extraRefs.length

  // 区域缩略芯片：按当前区域列表重新裁剪。
  useEffect(() => {
    if (!source || !regions.length) {
      setRegionThumbs([])
      return
    }
    let active = true
    loadImage(source.preview).then((image) => {
      if (!active) return
      setRegionThumbs(regions.map((region) => ({ id: region.id, url: cropRegionThumb(image, region) })))
    }).catch(() => setRegionThumbs([]))
    return () => { active = false }
  }, [source, regions])

  const applyRegions = useCallback((next: PhotoEditRegion[]) => {
    setRegionHistory(({ stack, index }) => ({
      stack: [...stack.slice(0, index + 1), next].slice(-60),
      index: Math.min(index + 1, 59),
    }))
  }, [])
  const undo = useCallback(() => setRegionHistory(({ stack, index }) => ({ stack, index: Math.max(0, index - 1) })), [])
  const redo = useCallback(() => setRegionHistory(({ stack, index }) => ({ stack, index: Math.min(stack.length - 1, index + 1) })), [])
  const removeRegion = useCallback((id: string) => {
    applyRegions(regions.filter((region) => region.id !== id))
    setSelectedId((current) => (current === id ? null : current))
  }, [applyRegions, regions])

  // 选中区域后支持 Delete / Backspace 删除（输入框内除外）。
  useEffect(() => {
    if (!selectedId) return
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
      if (event.key === "Delete" || event.key === "Backspace") removeRegion(selectedId)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [selectedId, removeRegion])

  const acceptOriginal = async (candidate: File | undefined | null) => {
    if (!candidate) return
    const problem = imageToolSourceError(candidate)
    if (problem) {
      message.warning(problem)
      return
    }
    try {
      const size = await probeImage(candidate)
      setSource({ file: candidate, preview: URL.createObjectURL(candidate), ...size })
      setRegionHistory({ stack: [[]], index: 0 })
      setSelectedId(null)
      setDraft(null)
      setZoomIndex(2)
    } catch {
      message.warning("图片无法读取，请换一张")
    }
  }

  const acceptExtraRefs = (candidates: FileList | null) => {
    if (!candidates?.length) return
    const next: PhotoAsset[] = []
    for (const file of Array.from(candidates)) {
      if (next.length >= extraRefCapacity) {
        message.warning(`参考图最多 ${PHOTO_EDIT_MAX_REFERENCES} 张（含原图${regions.length ? "与标注副本" : ""}）`)
        break
      }
      const problem = imageToolSourceError(file, "参考图")
      if (problem) {
        message.warning(problem)
        continue
      }
      next.push(assetFrom(file))
    }
    if (next.length) setExtraRefs((current) => [...current, ...next])
  }

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
    if (!source || event.button !== 0) return
    if (regions.length >= PHOTO_EDIT_REGION_MAX) {
      message.warning(`最多标记 ${PHOTO_EDIT_REGION_MAX} 个区域`)
      return
    }
    const point = toNaturalPoint(event)
    if (!point) return
    event.preventDefault()
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    setSelectedId(null)
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
    const minSide = Math.max(4, Math.min(source.width, source.height) * 0.005)
    if (pending.w < minSide || pending.h < minSide) return
    applyRegions([...regions, { id: createLocalId(), x: pending.x, y: pending.y, w: pending.w, h: pending.h }])
  }

  const ready = Boolean(activeWorkflowId && source && prompt.trim() && !selectedUnavailable) && !submitting

  const submit = async () => {
    if (submissionPending.current || !source) return
    if (!prompt.trim()) {
      message.warning("请填写编辑指令")
      return
    }
    submissionPending.current = true
    setSubmitting(true)
    try {
      const overlay = regions.length ? await buildAnnotatedOverlay(source, regions) : null
      if (regions.length && !overlay) throw new Error("标注示意图生成失败，请重试")
      const trimmed = prompt.trim()
      const form = new FormData()
      form.set("mode", activeWorkflowId ?? "")
      form.set("prompt", regions.length ? `${trimmed}\n${regionAnnotationPromptSuffix(regions.length)}` : trimmed)
      form.set("options", JSON.stringify(photoEditOptions(effectiveResolution, effectiveCount)))
      form.append("references", source.file)
      if (overlay) form.append("references", overlay)
      extraRefs.forEach((asset) => form.append("references", asset.file))
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交任务失败"))
      message.success("图片编辑任务已提交，可在生成页查看进度")
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
          <h1>图片编辑</h1>
          <p>在原图上框选要修改的区域并编号标记，用一句话描述改法，模型保持其余画面不变</p>
        </div>
      </header>

      {modesQuery.isLoading ? (
        <div className="grid min-h-[220px] place-items-center"><Spin tip="正在读取图片编辑能力" /></div>
      ) : modesQuery.isError ? (
        <Empty description={`能力读取失败：${apiErrorMessage(modesQuery.error, "请稍后重试")}`}>
          <Button icon={<RefreshCw size={14} />} onClick={() => void modesQuery.refetch()}>重新读取</Button>
        </Empty>
      ) : (
        <section className="studio-photo-editor" aria-label="图片编辑创作">
          <div
            className={`studio-photo-stage${dragOver ? " is-dragover" : ""}`}
            ref={stageRef}
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
              void acceptOriginal(event.dataTransfer.files?.[0])
            }}
          >
            {source ? (
              <div className="studio-photo-stage-frame" style={{ width: frameWidth, height: frameHeight }}>
                <img className="studio-photo-stage-img" src={source.preview} alt="待编辑原图" draggable={false} />
                <div
                  className="studio-photo-regions"
                  ref={regionLayerRef}
                  role="application"
                  aria-label="区域标记画布"
                  onPointerDown={onLayerPointerDown}
                  onPointerMove={onLayerPointerMove}
                  onPointerUp={onLayerPointerUp}
                  onPointerLeave={onLayerPointerUp}
                >
                  {regions.map((region, index) => (
                    <div
                      key={region.id}
                      className={`studio-photo-region${selectedId === region.id ? " is-selected" : ""}`}
                      style={{
                        left: `${region.x / source.width * 100}%`,
                        top: `${region.y / source.height * 100}%`,
                        width: `${region.w / source.width * 100}%`,
                        height: `${region.h / source.height * 100}%`,
                      }}
                      onPointerDown={(event) => {
                        event.stopPropagation()
                        setSelectedId(region.id)
                      }}
                    >
                      <span className="studio-photo-region-badge">{index + 1}</span>
                      <button
                        type="button"
                        className="studio-photo-region-remove"
                        aria-label={`删除区域标记 ${index + 1}`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation()
                          removeRegion(region.id)
                        }}
                      ><X size={11} /></button>
                    </div>
                  ))}
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
            ) : (
              <button type="button" className="studio-photo-stage-empty" onClick={() => originalInputRef.current?.click()}>
                <ImageUp size={26} aria-hidden="true" />
                <strong>上传要编辑的原图</strong>
                <span>点击选择或把图片拖到此处，支持 JPG / PNG 等常见格式，单张不超过 20 MB</span>
              </button>
            )}
          </div>

          <div className="studio-photo-toolbar">
            <Tooltip title="在图上拖拽框选要修改的区域">
              <Button type="primary" size="small" className="studio-photo-mark" icon={<MapPin size={14} />}>标记</Button>
            </Tooltip>
            <span className="studio-photo-toolbar-divider" aria-hidden="true" />
            <Tooltip title="撤销">
              <Button size="small" type="text" aria-label="撤销上一处标记" disabled={!regions.length} icon={<Undo2 size={14} />} onClick={undo} />
            </Tooltip>
            <Tooltip title="重做">
              <Button size="small" type="text" aria-label="重做标记" disabled={regionHistory.index >= regionHistory.stack.length - 1} icon={<Redo2 size={14} />} onClick={redo} />
            </Tooltip>
            <span className="studio-photo-toolbar-spacer" />
            <span className="studio-photo-zoom" role="group" aria-label="舞台缩放">
              <Button size="small" type="text" aria-label="缩小" disabled={!hasSource || zoomIndex === 0} icon={<Minus size={14} />} onClick={() => setZoomIndex((index) => Math.max(0, index - 1))} />
              <span className="studio-photo-zoom-value" aria-live="polite">{percent}%</span>
              <Button size="small" type="text" aria-label="放大" disabled={!hasSource || zoomIndex === ZOOM_STEPS.length - 1} icon={<Plus size={14} />} onClick={() => setZoomIndex((index) => Math.min(ZOOM_STEPS.length - 1, index + 1))} />
            </span>
          </div>

          {hasSource
            ? (
              <p className="studio-photo-hint">
                在原图上拖拽框选生成编号标记，提交时会附上一张标注示意图辅助模型定位；不标记也可以直接下指令全局改图。
              </p>
            )
            : null}

          <div className={`studio-photo-promptbar${hasSource ? "" : " is-disabled"}`}>
            <div className="studio-photo-chips" aria-label="已标记区域与参考图">
              {regionThumbs.map((thumb, index) => (
                <span key={thumb.id} className="studio-photo-chip" data-selected={selectedId === thumb.id || undefined}>
                  {thumb.url ? <img src={thumb.url} alt={`区域标记 ${index + 1}`} /> : <span className="studio-photo-chip-fallback">{index + 1}</span>}
                  <i className="studio-photo-chip-badge">{index + 1}</i>
                  <button
                    type="button"
                    className="studio-photo-chip-remove"
                    aria-label={`移除区域标记 ${index + 1}`}
                    onClick={() => removeRegion(thumb.id)}
                  ><X size={10} /></button>
                </span>
              ))}
              {extraRefs.map((asset, index) => (
                <span key={asset.id} className="studio-photo-chip" data-kind="ref">
                  <img src={asset.preview} alt={`参考图 ${index + 1}`} />
                  <button
                    type="button"
                    className="studio-photo-chip-remove"
                    aria-label={`移除参考图 ${index + 1}`}
                    onClick={() => setExtraRefs((current) => current.filter((item) => item.id !== asset.id))}
                  ><X size={10} /></button>
                </span>
              ))}
              {hasSource && extraRefCapacity > 0
                ? (
                  <Tooltip title={`追加参考图（风格、角色、素材，剩余 ${extraRefCapacity} 张）`}>
                    <button type="button" className="studio-photo-chip-add" aria-label="追加参考图" onClick={() => refsInputRef.current?.click()}><Plus size={14} /></button>
                  </Tooltip>
                )
                : null}
            </div>
            <Input.TextArea
              className="studio-photo-input"
              aria-label="编辑指令"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={hasSource
                ? "描述要怎么改，例如：把外套换成红色羽绒衫，保持人物姿势与背景不变。"
                : "先上传原图，再用一句话描述要怎么改"}
              autoSize={{ minRows: 1, maxRows: 4 }}
              maxLength={1500}
            />
            <div className="studio-photo-controls">
              <Select
                aria-label="编辑模型"
                className="studio-photo-model"
                value={activeWorkflowId ?? undefined}
                onChange={(next) => setWorkflowId(next)}
                placeholder="编辑模型"
                options={choices.map((choice) => ({ value: choice.id, label: choice.name }))}
                disabled={!choices.length}
              />
              {resolutionMeta.values.length > 1
                ? (
                  <Select
                    aria-label="输出分辨率"
                    className="studio-photo-resolution"
                    value={effectiveResolution ?? undefined}
                    onChange={(next) => setResolution(next)}
                    options={resolutionMeta.values.map((value) => ({ value, label: value }))}
                  />
                )
                : null}
              {countBounds.max > 1
                ? (
                  <InputNumber
                    aria-label="生成数量"
                    className="studio-photo-count"
                    min={countBounds.min}
                    max={countBounds.max}
                    step={1}
                    value={effectiveCount}
                    onChange={(value) => setCount(typeof value === "number" ? value : countBounds.min)}
                    controls={false}
                  />
                )
                : null}
              <Tooltip title={ready ? "提交编辑任务" : selectedUnavailable ? "所选编辑模型暂不可用" : hasSource ? "请填写编辑指令" : "请先上传原图"}>
                <Button
                  type="primary"
                  shape="circle"
                  size="large"
                  className="studio-photo-submit"
                  aria-label="开始编辑"
                  loading={submitting}
                  disabled={!ready}
                  icon={<ArrowUp size={20} />}
                  onClick={() => void submit()}
                />
              </Tooltip>
            </div>
          </div>

          {choices.length === 0
            ? <p className="studio-motion-validation" role="alert">暂无可用的图片编辑模型，请稍后重试</p>
            : selectedUnavailable
              ? <p className="studio-motion-validation" role="alert">所选编辑模型暂不可用，请换一个模型</p>
              : null}
        </section>
      )}

      <input
        ref={originalInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ""
          void acceptOriginal(selected)
        }}
      />
      <input
        ref={refsInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files
          event.target.value = ""
          acceptExtraRefs(selected)
        }}
      />
    </div>
  )
}
