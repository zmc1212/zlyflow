import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Empty, Slider, Spin, Tooltip, message } from "antd"
import { ArrowLeft, Brush, Download, Eraser, Minus, Plus, Redo2, RotateCcw, Scan, Sparkles, Undo2 } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { apiErrorMessage, notifyUnauthorized, requestJson as api } from "../api"
import { IMAGE_BACKGROUND_REMOVE_WORKFLOW } from "../generation/image-edit"
import { PATHS } from "../paths"
import { roundReferenceSources, restoreReferenceFiles, type ReferenceSource } from "../reference-assets"
import "./image-bg-remove.css"
import "./motion-transfer-tool.css"
import "./tools.css"

/**
 * 图片去背景画布编辑器（对照即梦交互）：
 * - 落地页上传后自动创建 SAM3 任务并跳转到本页 `?job=<id>`；
 * - 任务进行中在近黑画布上显示原图占位；成功后展示透明结果（棋盘格 + 移除区蓝色高亮）；
 * - 画笔=强制移除、橡皮擦=强制保留，蒙版随「生成」作为 references[1]/[2] 提交，
 *   由后端 MaskComposite 与 SAM3 alpha 合成（见 image_edit_workflow.py）。
 */

type OutputPayload = {
  kind?: string
  label?: string
  download_url?: string | null
  cloud_url?: string | null
}

type EditorJob = {
  id: string
  mode: string
  status: string
  error?: string | null
  outputs?: OutputPayload[]
  references?: ReferenceSource[]
  rounds?: {
    id: string
    reference_count: number
    references?: ReferenceSource[]
    generation_items?: { id: string; outputs?: OutputPayload[] }[]
  }[]
}

type StrokePoint = { x: number; y: number }
type Stroke = { tool: "brush" | "eraser"; size: number; points: StrokePoint[] }
type CanvasRef = { current: HTMLCanvasElement | null }

const STAGE_PADDING = 28
const MIN_ZOOM = 0.25
const MAX_ZOOM = 4
/** 移除区蓝色高亮（即梦风格）：画在近黑媒体底上，两种主题下均可读。 */
const TINT_COLOR = "rgba(101, 127, 255, 0.42)"
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "interrupted", "partial"])

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("图片加载失败"))
    image.src = src
  })
}

function createMaskCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas")
  canvas.width = width
  canvas.height = height
  return canvas
}

function fillMaskTransparent(canvas: HTMLCanvasElement) {
  const ctx = canvas.getContext("2d")
  if (!ctx) return
  ctx.globalCompositeOperation = "source-over"
  ctx.clearRect(0, 0, canvas.width, canvas.height)
}

function drawStroke(canvas: HTMLCanvasElement, stroke: Stroke) {
  const ctx = canvas.getContext("2d")
  if (!ctx || stroke.points.length === 0) return
  ctx.globalCompositeOperation = "source-over"
  ctx.strokeStyle = "#ffffff"
  ctx.fillStyle = "#ffffff"
  ctx.lineWidth = stroke.size
  ctx.lineCap = "round"
  ctx.lineJoin = "round"
  if (stroke.points.length === 1) {
    ctx.beginPath()
    ctx.arc(stroke.points[0].x, stroke.points[0].y, stroke.size / 2, 0, Math.PI * 2)
    ctx.fill()
    return
  }
  ctx.beginPath()
  stroke.points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y)
    else ctx.lineTo(point.x, point.y)
  })
  ctx.stroke()
}

/** 从结果 alpha 提取"自动移除区"（alpha<0.5 → 白色），用于蓝色高亮；跨域污染时返回 null。 */
function computeAutoRemoved(image: HTMLImageElement): HTMLCanvasElement | null {
  const canvas = document.createElement("canvas")
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) return null
  ctx.drawImage(image, 0, 0)
  let sampled: ImageData
  try {
    sampled = ctx.getImageData(0, 0, canvas.width, canvas.height)
  } catch {
    return null
  }
  const extracted = ctx.createImageData(canvas.width, canvas.height)
  const source = sampled.data
  const target = extracted.data
  for (let offset = 0; offset < source.length; offset += 4) {
    if (source[offset + 3] < 128) {
      target[offset] = 255
      target[offset + 1] = 255
      target[offset + 2] = 255
      target[offset + 3] = 255
    }
  }
  ctx.putImageData(extracted, 0, 0)
  return canvas
}

function containFit(width: number, height: number, maxWidth: number, maxHeight: number) {
  const scale = Math.min(maxWidth / width, maxHeight / height)
  return { width: width * scale, height: height * scale, scale }
}

function ensureLayer(ref: CanvasRef, width: number, height: number): HTMLCanvasElement {
  let layer = ref.current
  if (!layer) {
    layer = document.createElement("canvas")
    ref.current = layer
  }
  if (layer.width !== width || layer.height !== height) {
    layer.width = width
    layer.height = height
  }
  return layer
}

let CHECKER_TILE: HTMLCanvasElement | null = null
function getCheckerTile(): HTMLCanvasElement {
  if (CHECKER_TILE) return CHECKER_TILE
  const tile = document.createElement("canvas")
  tile.width = 24
  tile.height = 24
  const ctx = tile.getContext("2d")
  if (ctx) {
    ctx.fillStyle = "#26282e"
    ctx.fillRect(0, 0, 24, 24)
    ctx.fillStyle = "#33363d"
    ctx.fillRect(0, 0, 12, 12)
    ctx.fillRect(12, 12, 12, 12)
  }
  CHECKER_TILE = tile
  return tile
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"))
}

export default function ImageBgRemoveEditor({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = searchParams.get("job") ?? ""

  const [originalFile, setOriginalFile] = useState<File | null>(null)
  const [originalImage, setOriginalImage] = useState<HTMLImageElement | null>(null)
  const [resultImage, setResultImage] = useState<HTMLImageElement | null>(null)
  const [restoringSource, setRestoringSource] = useState(false)
  const [tool, setTool] = useState<"brush" | "eraser">("brush")
  const [brushSize, setBrushSize] = useState(28)
  const [zoom, setZoom] = useState(1)
  const [stageBox, setStageBox] = useState({ w: 0, h: 0 })
  const [historyLen, setHistoryLen] = useState(0)
  const [redoLen, setRedoLen] = useState(0)
  const [generating, setGenerating] = useState(false)

  const stageRef = useRef<HTMLElement | null>(null)
  const displayRef = useRef<HTMLCanvasElement | null>(null)
  const cursorRef = useRef<HTMLDivElement | null>(null)
  const removeMaskRef = useRef<HTMLCanvasElement | null>(null)
  const keepMaskRef = useRef<HTMLCanvasElement | null>(null)
  const autoRemovedRef = useRef<HTMLCanvasElement | null>(null)
  const imageLayerRef = useRef<HTMLCanvasElement | null>(null)
  const keepLayerRef = useRef<HTMLCanvasElement | null>(null)
  const tintLayerRef = useRef<HTMLCanvasElement | null>(null)
  const strokesRef = useRef<Stroke[]>([])
  const redoStrokesRef = useRef<Stroke[]>([])
  const activeStrokeRef = useRef<Stroke | null>(null)
  const paintingRef = useRef(false)
  const lastPointRef = useRef<StrokePoint | null>(null)
  const masksKeyRef = useRef("")
  const originalUrlRef = useRef<string | null>(null)
  const renderRef = useRef<() => void>(() => {})
  const rafRef = useRef(0)

  const jobQuery = useQuery({
    queryKey: ["bg-remove-editor-job", jobId],
    queryFn: () => api<EditorJob>(`/api/jobs/${encodeURIComponent(jobId)}`),
    enabled: jobId !== "",
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return !status || TERMINAL_STATUSES.has(status) ? false : 2000
    },
  })
  const job = jobQuery.data
  const jobStatus = job?.status
  const running = Boolean(jobStatus) && !TERMINAL_STATUSES.has(jobStatus ?? "")
  const succeeded = jobStatus === "succeeded" || jobStatus === "partial"
  const failed = jobStatus === "failed" || jobStatus === "cancelled" || jobStatus === "interrupted"
  const nodeNo = job?.rounds?.length || 1

  const referenceUrl = useMemo(() => {
    if (!job) return null
    const lastRound = job.rounds?.at(-1)
    const sources = lastRound
      ? roundReferenceSources(
          job as { id: string; references: ReferenceSource[] },
          lastRound as { id: string; reference_count: number; references: ReferenceSource[] },
        )
      : job.references ?? []
    const ordered = [...sources].sort((left, right) => left.index - right.index)
    return ordered[0]?.url ?? null
  }, [job])

  const outputUrl = useMemo(() => {
    if (!job || !succeeded) return null
    const items = [
      ...(job.outputs ?? []),
      ...(job.rounds?.at(-1)?.generation_items ?? []).flatMap((item) => item.outputs ?? []),
    ]
    const output = items.find((item) => item.kind === "image")
    return output ? output.download_url ?? output.cloud_url ?? null : null
  }, [job, succeeded])

  const ensureMasks = useCallback((key: string, width: number, height: number) => {
    const maskKey = `${key}:${width}x${height}`
    if (masksKeyRef.current === maskKey) return
    masksKeyRef.current = maskKey
    removeMaskRef.current = createMaskCanvas(width, height)
    keepMaskRef.current = createMaskCanvas(width, height)
    autoRemovedRef.current = null
    strokesRef.current = []
    redoStrokesRef.current = []
    setHistoryLen(0)
    setRedoLen(0)
  }, [])

  // 原图：从任务参考素材恢复为 File（供再次提交蒙版任务），并加载为画布底图。
  useEffect(() => {
    if (!referenceUrl) return
    let active = true
    setRestoringSource(true)
    restoreReferenceFiles([{ index: 1, url: referenceUrl }])
      .then((files) => {
        const file = files[0]
        if (!active || !file) return
        const objectUrl = URL.createObjectURL(file)
        originalUrlRef.current = objectUrl
        setOriginalFile(file)
        return loadImageElement(objectUrl).then((image) => {
          if (!active) return
          setOriginalImage(image)
          ensureMasks(jobId, image.naturalWidth, image.naturalHeight)
        })
      })
      .catch((error) => {
        if (active) message.error(error instanceof Error ? error.message : "原图读取失败")
      })
      .finally(() => {
        if (active) setRestoringSource(false)
      })
    return () => {
      active = false
      if (originalUrlRef.current) {
        URL.revokeObjectURL(originalUrlRef.current)
        originalUrlRef.current = null
      }
      setOriginalImage(null)
      setOriginalFile(null)
      setResultImage(null)
    }
  }, [referenceUrl, jobId, ensureMasks])

  // 结果：优先 fetch → blob → objectURL（画布不跨域污染，可提取自动移除区做蓝色高亮）。
  useEffect(() => {
    if (!outputUrl) {
      setResultImage(null)
      autoRemovedRef.current = null
      return
    }
    let active = true
    let objectUrl: string | null = null
    void (async () => {
      try {
        const response = await fetch(outputUrl, { credentials: "include" })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const blob = await response.blob()
        objectUrl = URL.createObjectURL(blob)
        const image = await loadImageElement(objectUrl)
        if (!active) return
        autoRemovedRef.current = computeAutoRemoved(image)
        setResultImage(image)
      } catch {
        try {
          const image = await loadImageElement(outputUrl)
          if (!active) return
          autoRemovedRef.current = null
          setResultImage(image)
        } catch {
          if (active) message.error("去背景结果读取失败")
        }
      }
    })()
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [outputUrl])

  useEffect(() => {
    const element = stageRef.current
    if (!element || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) setStageBox({ w: rect.width, h: rect.height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const render = useCallback(() => {
    const display = displayRef.current
    const base = originalImage
    const result = resultImage
    const removeMask = removeMaskRef.current
    const keepMask = keepMaskRef.current
    if (!display || !base || !result || !removeMask || !keepMask) return
    if (!stageBox.w || !stageBox.h) return
    const availableW = Math.max(80, stageBox.w - STAGE_PADDING * 2)
    const availableH = Math.max(80, stageBox.h - STAGE_PADDING * 2)
    const fit = containFit(base.naturalWidth, base.naturalHeight, availableW, availableH)
    const drawW = Math.max(1, Math.round(fit.width * zoom))
    const drawH = Math.max(1, Math.round(fit.height * zoom))
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const pw = Math.max(1, Math.round(drawW * dpr))
    const ph = Math.max(1, Math.round(drawH * dpr))
    if (display.width !== pw || display.height !== ph) {
      display.width = pw
      display.height = ph
    }
    display.style.width = `${drawW}px`
    display.style.height = `${drawH}px`
    const ctx = display.getContext("2d")
    if (!ctx) return
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, pw, ph)
    const pattern = ctx.createPattern(getCheckerTile(), "repeat")
    if (pattern) {
      ctx.fillStyle = pattern
      ctx.fillRect(0, 0, pw, ph)
    }
    // 结果图层：结果 − 画笔移除区 + 画笔恢复的原图像素。
    const imageLayer = ensureLayer(imageLayerRef, pw, ph)
    const ictx = imageLayer.getContext("2d")
    if (!ictx) return
    ictx.setTransform(1, 0, 0, 1, 0, 0)
    ictx.globalCompositeOperation = "source-over"
    ictx.clearRect(0, 0, pw, ph)
    ictx.drawImage(result, 0, 0, pw, ph)
    ictx.globalCompositeOperation = "destination-out"
    ictx.drawImage(removeMask, 0, 0, pw, ph)
    const keepLayer = ensureLayer(keepLayerRef, pw, ph)
    const kctx = keepLayer.getContext("2d")
    if (kctx) {
      kctx.setTransform(1, 0, 0, 1, 0, 0)
      kctx.globalCompositeOperation = "source-over"
      kctx.clearRect(0, 0, pw, ph)
      kctx.drawImage(base, 0, 0, pw, ph)
      kctx.globalCompositeOperation = "destination-in"
      kctx.drawImage(keepMask, 0, 0, pw, ph)
      ictx.globalCompositeOperation = "source-over"
      ictx.drawImage(keepLayer, 0, 0)
    }
    ctx.drawImage(imageLayer, 0, 0)
    // 蓝色高亮：自动移除区 ∪ 画笔移除区 − 画笔保留区。
    const tintLayer = ensureLayer(tintLayerRef, pw, ph)
    const tctx = tintLayer.getContext("2d")
    if (tctx) {
      tctx.setTransform(1, 0, 0, 1, 0, 0)
      tctx.globalCompositeOperation = "source-over"
      tctx.clearRect(0, 0, pw, ph)
      tctx.fillStyle = "#ffffff"
      tctx.fillRect(0, 0, pw, ph)
      const autoRemoved = autoRemovedRef.current
      tctx.globalCompositeOperation = "destination-in"
      if (autoRemoved) {
        tctx.drawImage(autoRemoved, 0, 0, pw, ph)
        tctx.globalCompositeOperation = "source-over"
        tctx.drawImage(removeMask, 0, 0, pw, ph)
      } else {
        tctx.drawImage(removeMask, 0, 0, pw, ph)
      }
      tctx.globalCompositeOperation = "destination-out"
      tctx.drawImage(keepMask, 0, 0, pw, ph)
      tctx.globalCompositeOperation = "source-in"
      tctx.fillStyle = TINT_COLOR
      tctx.fillRect(0, 0, pw, ph)
      ctx.drawImage(tintLayer, 0, 0)
    }
  }, [originalImage, resultImage, stageBox, zoom])

  useEffect(() => {
    renderRef.current = render
  })
  useEffect(() => {
    render()
  }, [render])

  const scheduleRender = useCallback(() => {
    if (rafRef.current) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      renderRef.current()
    })
  }, [])

  const rebuildMasks = useCallback(() => {
    const removeMask = removeMaskRef.current
    const keepMask = keepMaskRef.current
    if (!removeMask || !keepMask) return
    fillMaskTransparent(removeMask)
    fillMaskTransparent(keepMask)
    for (const stroke of strokesRef.current) {
      drawStroke(stroke.tool === "brush" ? removeMask : keepMask, stroke)
    }
    scheduleRender()
  }, [scheduleRender])

  const finishStroke = useCallback(() => {
    if (!paintingRef.current) return
    paintingRef.current = false
    lastPointRef.current = null
    const stroke = activeStrokeRef.current
    activeStrokeRef.current = null
    if (stroke) {
      strokesRef.current.push(stroke)
      redoStrokesRef.current = []
      setHistoryLen(strokesRef.current.length)
      setRedoLen(0)
    }
  }, [])

  const toImagePoint = (event: React.PointerEvent<HTMLCanvasElement>): StrokePoint | null => {
    const display = displayRef.current
    const base = originalImage
    if (!display || !base) return null
    const rect = display.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    return {
      x: (event.clientX - rect.left) * (base.naturalWidth / rect.width),
      y: (event.clientY - rect.top) * (base.naturalHeight / rect.height),
    }
  }

  const paintSegment = (from: StrokePoint | null, to: StrokePoint) => {
    const stroke = activeStrokeRef.current
    const mask = stroke?.tool === "brush" ? removeMaskRef.current : keepMaskRef.current
    if (!stroke || !mask) return
    stroke.points.push(to)
    const ctx = mask.getContext("2d")
    if (!ctx) return
    ctx.globalCompositeOperation = "source-over"
    ctx.strokeStyle = "#ffffff"
    ctx.fillStyle = "#ffffff"
    ctx.lineWidth = stroke.size
    ctx.lineCap = "round"
    ctx.lineJoin = "round"
    if (!from || (from.x === to.x && from.y === to.y)) {
      ctx.beginPath()
      ctx.arc(to.x, to.y, stroke.size / 2, 0, Math.PI * 2)
      ctx.fill()
      return
    }
    ctx.beginPath()
    ctx.moveTo(from.x, from.y)
    ctx.lineTo(to.x, to.y)
    ctx.stroke()
  }

  const updateCursor = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const cursor = cursorRef.current
    const stage = stageRef.current
    const display = displayRef.current
    const base = originalImage
    if (!cursor || !stage || !display || !base) return
    const rect = stage.getBoundingClientRect()
    const scale = display.getBoundingClientRect().width / base.naturalWidth
    cursor.style.left = `${event.clientX - rect.left}px`
    cursor.style.top = `${event.clientY - rect.top}px`
    cursor.style.width = `${Math.max(6, brushSize * scale)}px`
    cursor.style.height = `${Math.max(6, brushSize * scale)}px`
    cursor.dataset.visible = "true"
  }

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!resultImage || running) return
    const point = toImagePoint(event)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    paintingRef.current = true
    lastPointRef.current = point
    activeStrokeRef.current = { tool, size: brushSize, points: [point] }
    paintSegment(null, point)
    scheduleRender()
  }

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    updateCursor(event)
    if (!paintingRef.current) return
    const point = toImagePoint(event)
    if (!point) return
    paintSegment(lastPointRef.current, point)
    lastPointRef.current = point
    scheduleRender()
  }

  const onPointerLeave = () => {
    if (cursorRef.current) cursorRef.current.dataset.visible = "false"
  }

  const undo = () => {
    if (!strokesRef.current.length) return
    redoStrokesRef.current.push(strokesRef.current.pop() as Stroke)
    rebuildMasks()
    setHistoryLen(strokesRef.current.length)
    setRedoLen(redoStrokesRef.current.length)
  }

  const redo = () => {
    const stroke = redoStrokesRef.current.pop()
    if (!stroke) return
    strokesRef.current.push(stroke)
    rebuildMasks()
    setHistoryLen(strokesRef.current.length)
    setRedoLen(redoStrokesRef.current.length)
  }

  const resetEdits = () => {
    if (!strokesRef.current.length && !redoStrokesRef.current.length) return
    strokesRef.current = []
    redoStrokesRef.current = []
    rebuildMasks()
    setHistoryLen(0)
    setRedoLen(0)
  }

  const submitJob = async (withMasks: boolean) => {
    if (!originalFile || generating) return
    if (withMasks && strokesRef.current.length === 0) {
      message.info("画布没有手动调整，当前结果已是最新，可直接下载")
      return
    }
    setGenerating(true)
    try {
      const form = new FormData()
      form.set("mode", IMAGE_BACKGROUND_REMOVE_WORKFLOW)
      form.set("prompt", "")
      form.append("references", originalFile)
      if (withMasks) {
        const removeMask = removeMaskRef.current
        const keepMask = keepMaskRef.current
        if (!removeMask || !keepMask) throw new Error("画布尚未就绪")
        const [removeBlob, keepBlob] = await Promise.all([canvasToBlob(removeMask), canvasToBlob(keepMask)])
        if (!removeBlob || !keepBlob) throw new Error("蒙版导出失败")
        form.append("references", new File([removeBlob], "bg-remove-mask-remove.png", { type: "image/png" }))
        form.append("references", new File([keepBlob], "bg-remove-mask-keep.png", { type: "image/png" }))
      }
      const response = await fetch("/api/jobs", { method: "POST", body: form, headers: { "X-CSRF-Token": csrfToken } })
      if (response.status === 401) notifyUnauthorized()
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw new Error(apiErrorMessage(payload, "提交生成任务失败"))
      message.success(withMasks ? "已按画布调整重新生成" : "已重新提交去背景任务")
      navigate(`${PATHS.toolImageBgRemoveEditor}?job=${encodeURIComponent(payload.id)}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交生成任务失败")
    } finally {
      setGenerating(false)
    }
  }

  const generate = () => {
    if (running) return
    void submitJob(true)
  }

  const download = async () => {
    if (!outputUrl) return
    try {
      const response = await fetch(outputUrl, { credentials: "include" })
      if (!response.ok) throw new Error(String(response.status))
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = objectUrl
      anchor.download = `去背景-${(jobId || "result").slice(0, 12)}.png`
      anchor.click()
      URL.revokeObjectURL(objectUrl)
    } catch {
      window.open(outputUrl, "_blank", "noopener")
    }
  }

  const zoomPercent = useMemo(() => {
    if (!originalImage || !stageBox.w || !stageBox.h) return 100
    const fit = containFit(
      originalImage.naturalWidth,
      originalImage.naturalHeight,
      Math.max(80, stageBox.w - STAGE_PADDING * 2),
      Math.max(80, stageBox.h - STAGE_PADDING * 2),
    )
    return Math.round((fit.width * zoom / originalImage.naturalWidth) * 100)
  }, [originalImage, stageBox, zoom])

  const statusState = running ? "running" : succeeded ? "succeeded" : failed ? "failed" : "idle"
  const statusText = running ? "生成中" : failed ? "失败" : "已保存"

  if (!jobId) {
    return (
      <div className="studio-tools-page studio-motion-tool">
        <div className="bgremove-editor-empty">
          <Empty description="画布任务不存在，请从图片去背景工具页上传图片开始">
            <Button type="primary" onClick={() => navigate(PATHS.toolImageBgRemove)}>去上传图片</Button>
          </Empty>
        </div>
      </div>
    )
  }

  const canvasDisabled = !succeeded || !resultImage || running

  return (
    <div className="studio-tools-page bgremove-editor">
      <div className="bgremove-topbar">
        <div className="bgremove-topbar-left">
          <Button
            type="text"
            size="small"
            icon={<ArrowLeft size={14} />}
            aria-label="返回图片去背景"
            onClick={() => navigate(PATHS.toolImageBgRemove)}
          />
          <span className="bgremove-topbar-title">图片去背景</span>
          <span className="bgremove-node-chip" data-state={statusState}>
            {`节点 ${nodeNo} · ${statusText}`}
          </span>
        </div>
        <div className="bgremove-topbar-right">
          {succeeded && outputUrl ? (
            <Button size="small" icon={<Download size={13} />} onClick={() => void download()}>下载 PNG</Button>
          ) : null}
        </div>
      </div>

      <section className="bgremove-stage" ref={stageRef} aria-label="去背景画布">
        <div className="bgremove-canvas-scroll">
          <div className="bgremove-canvas-frame">
            <canvas
              ref={displayRef}
              className="bgremove-canvas"
              data-disabled={canvasDisabled ? "true" : "false"}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={finishStroke}
              onPointerCancel={finishStroke}
              onPointerLeave={onPointerLeave}
            />
          </div>
        </div>
        <div className="bgremove-brush-cursor" ref={cursorRef} data-visible="false" />
        <div className="bgremove-zoom">
          <Button type="text" size="small" icon={<Minus size={12} />} aria-label="缩小" onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value / 1.25))} />
          <span className="bgremove-zoom-label">{zoomPercent}%</span>
          <Button type="text" size="small" icon={<Plus size={12} />} aria-label="放大" onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value * 1.25))} />
          <Button type="text" size="small" icon={<Scan size={12} />} aria-label="适应画布" onClick={() => setZoom(1)} />
        </div>

        {restoringSource || (!originalImage && !jobQuery.isError) ? (
          <div className="bgremove-stage-overlay"><Spin /><p>正在读取原图…</p></div>
        ) : null}
        {originalImage && running ? (
          <div className="bgremove-stage-overlay"><Spin /><p>正在识别主体并移除背景…</p></div>
        ) : null}
        {succeeded && originalImage && !resultImage && !restoringSource ? (
          <div className="bgremove-stage-overlay"><Spin /><p>正在加载去背景结果…</p></div>
        ) : null}
        {failed ? (
          <div className="bgremove-stage-overlay">
            <Alert
              className="bgremove-alert"
              type="error"
              showIcon
              message="去背景任务失败"
              description={job?.error || "请重试；若持续失败请检查当前连接的视频服务实例。"}
            />
            <Button type="primary" loading={generating} onClick={() => void submitJob(false)}>重新生成</Button>
          </div>
        ) : null}
        {jobQuery.isError ? (
          <div className="bgremove-stage-overlay">
            <Alert
              className="bgremove-alert"
              type="error"
              showIcon
              message="画布任务读取失败"
              description={apiErrorMessage(jobQuery.error, "请返回工具页重新上传")}
            />
            <Button onClick={() => navigate(PATHS.toolImageBgRemove)}>返回工具页</Button>
          </div>
        ) : null}
      </section>

      <footer className="bgremove-toolbar" aria-label="去背景工具条">
        <Tooltip title="画笔：涂抹要移除的区域">
          <Button
            type={tool === "brush" ? "primary" : "text"}
            icon={<Brush size={15} />}
            aria-label="画笔"
            disabled={!succeeded}
            onClick={() => setTool("brush")}
          />
        </Tooltip>
        <Tooltip title="橡皮擦：涂抹要恢复保留的区域">
          <Button
            type={tool === "eraser" ? "primary" : "text"}
            icon={<Eraser size={15} />}
            aria-label="橡皮擦"
            disabled={!succeeded}
            onClick={() => setTool("eraser")}
          />
        </Tooltip>
        <div className="bgremove-toolbar-divider" />
        <div className="bgremove-toolbar-size">
          <Slider
            min={6}
            max={80}
            step={1}
            value={brushSize}
            onChange={(value: number) => setBrushSize(value)}
            aria-label="画笔粗细"
            tooltip={{ formatter: (value?: number) => `${value ?? brushSize} px` }}
          />
        </div>
        <div className="bgremove-toolbar-divider" />
        <Tooltip title="撤销">
          <Button type="text" icon={<Undo2 size={15} />} aria-label="撤销" disabled={historyLen === 0} onClick={undo} />
        </Tooltip>
        <Tooltip title="重做">
          <Button type="text" icon={<Redo2 size={15} />} aria-label="重做" disabled={redoLen === 0} onClick={redo} />
        </Tooltip>
        <Tooltip title="重置手动调整">
          <Button type="text" icon={<RotateCcw size={14} />} disabled={historyLen === 0 && redoLen === 0} onClick={resetEdits}>
            重置
          </Button>
        </Tooltip>
        <div className="bgremove-toolbar-divider" />
        <span className="bgremove-count-chip">1 张</span>
        <Button
          type="primary"
          className="bgremove-toolbar-generate"
          icon={<Sparkles size={14} />}
          loading={generating}
          disabled={!succeeded || !originalFile}
          onClick={generate}
        >
          生成
        </Button>
      </footer>
    </div>
  )
}
