import { Button, Popover, Slider, Tooltip } from "antd"
import { Brush, Eraser, Hand, Minus, Plus, Redo2, Undo2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

/** 编辑器工具：画笔涂抹 / 橡皮擦除 / 抓手平移（对齐即梦「局部重绘」编辑器）。 */
export type MaskPainterTool = "brush" | "eraser" | "hand"

type Point = { x: number; y: number }
type BrushStroke = { type: "brush"; points: Point[]; size: number }
type EraserStroke = { type: "eraser"; points: Point[]; size: number }
type Stroke = BrushStroke | EraserStroke
type View = { zoom: number; x: number; y: number }
type Size = { width: number; height: number }

/** 画笔/橡皮粗细范围（画布显示像素；缩放只改变视野，不改变笔迹显示粗细）。 */
export const MASK_BRUSH_MIN = 4
export const MASK_BRUSH_MAX = 80
export const MASK_BRUSH_DEFAULT = 26
export const MASK_ERASER_DEFAULT = 40

const ZOOM_MIN = 0.2
const ZOOM_MAX = 4
const ZOOM_STEP = 1.2
/** 滚轮缩放灵敏度。 */
const WHEEL_ZOOM_SENSITIVITY = 0.0016
/** 适应画布时四周留白。 */
const FIT_PADDING = 28
/** 遮罩笔迹颜色：即梦同款淡紫。 */
const MASK_COLOR = "rgba(167, 139, 250, 0.55)"

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/** 平移越界夹取：内容放大出界时最多拖到边缘，缩小时回正居中。 */
function clampView(view: View, plane: Size, viewport: Size): View {
  const maxX = Math.max(0, (plane.width * view.zoom - viewport.width) / 2)
  const maxY = Math.max(0, (plane.height * view.zoom - viewport.height) / 2)
  return { zoom: view.zoom, x: clamp(view.x, -maxX, maxX), y: clamp(view.y, -maxY, maxY) }
}

/** 按顺序绘制笔画：画笔叠淡紫，橡皮用 destination-out 彻底挖掉已画区域（源须全不透明）。 */
function paintStrokes(context: CanvasRenderingContext2D, strokes: Stroke[], cssToNatural: number) {
  for (const stroke of strokes) {
    const erasing = stroke.type === "eraser"
    context.globalCompositeOperation = erasing ? "destination-out" : "source-over"
    // destination-out 只看源 alpha：橡皮必须用不透明源才能一次擦净，颜色随意。
    context.fillStyle = erasing ? "#000000" : MASK_COLOR
    context.strokeStyle = erasing ? "#000000" : MASK_COLOR
    context.lineWidth = stroke.size * cssToNatural
    context.lineCap = "round"
    context.lineJoin = "round"
    context.beginPath()
    stroke.points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y)
      else context.lineTo(point.x, point.y)
    })
    if (stroke.points.length === 1) {
      const [point] = stroke.points
      context.arc(point.x, point.y, context.lineWidth / 2, 0, Math.PI * 2)
      context.fill()
    }
    context.stroke()
  }
  context.globalCompositeOperation = "source-over"
}

/**
 * 即梦式遮罩编辑器：深色画布上用画笔涂抹 / 橡皮擦除标记要编辑的区域，
 * 支持滚轮与按钮缩放、抓手平移、撤销重做。导出「白色=编辑区、黑色=保留区」
 * 的遮罩 PNG（按原图分辨率），遮罩语义与后端 load_mask / 局部重绘工作流一致。
 */
export default function ImageMaskPainter({
  imageUrl,
  naturalSize,
  tool,
  onToolChange,
  onMaskReady,
}: {
  imageUrl: string
  naturalSize: { width: number; height: number }
  tool: MaskPainterTool
  onToolChange: (tool: MaskPainterTool) => void
  onMaskReady: (mask: File | null) => void
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fitRef = useRef<Size>({ width: 0, height: 0 })
  const viewportSizeRef = useRef<Size>({ width: 0, height: 0 })
  const drawingRef = useRef<Stroke | null>(null)
  const panRef = useRef<{ startX: number; startY: number; view: View } | null>(null)

  const [strokes, setStrokes] = useState<Stroke[]>([])
  const [redoStack, setRedoStack] = useState<Stroke[]>([])
  const [brushSize, setBrushSize] = useState(MASK_BRUSH_DEFAULT)
  const [eraserSize, setEraserSize] = useState(MASK_ERASER_DEFAULT)
  const [sizeAnchor, setSizeAnchor] = useState<null | "brush" | "eraser">(null)
  const [plane, setPlane] = useState<Size>({ width: 0, height: 0 })
  const [view, setView] = useState<View>({ zoom: 1, x: 0, y: 0 })
  const [cursor, setCursor] = useState<Point | null>(null)
  const [panning, setPanning] = useState(false)

  // 视口尺寸变化时重算适应画布的基准尺寸（zoom=1 的 100% 基准）。
  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const compute = () => {
      const rect = element.getBoundingClientRect()
      viewportSizeRef.current = { width: rect.width, height: rect.height }
      const scale = Math.min(
        Math.max(0, rect.width - FIT_PADDING * 2) / naturalSize.width,
        Math.max(0, rect.height - FIT_PADDING * 2) / naturalSize.height,
      )
      fitRef.current = {
        width: Math.max(1, naturalSize.width * scale),
        height: Math.max(1, naturalSize.height * scale),
      }
      setPlane(fitRef.current)
      setView((current) => clampView(current, fitRef.current, viewportSizeRef.current))
    }
    compute()
    const observer = new ResizeObserver(compute)
    observer.observe(element)
    return () => observer.disconnect()
  }, [naturalSize.width, naturalSize.height])

  const zoomAt = useCallback((factor: number, clientX?: number, clientY?: number) => {
    const rect = viewportRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    const px = (clientX ?? rect.left + rect.width / 2) - rect.left
    const py = (clientY ?? rect.top + rect.height / 2) - rect.top
    setView((current) => {
      const zoom = clamp(current.zoom * factor, ZOOM_MIN, ZOOM_MAX)
      const ratio = zoom / current.zoom
      // 光标指向的画布内容点在缩放前后保持同一屏幕位置。
      return clampView(
        { zoom, x: px - (px - current.x) * ratio, y: py - (py - current.y) * ratio },
        fitRef.current,
        { width: rect.width, height: rect.height },
      )
    })
  }, [])

  // 滚轮缩放需非 passive 监听才能阻止页面滚动。
  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      zoomAt(Math.exp(-event.deltaY * WHEEL_ZOOM_SENSITIVITY), event.clientX, event.clientY)
    }
    element.addEventListener("wheel", onWheel, { passive: false })
    return () => element.removeEventListener("wheel", onWheel)
  }, [zoomAt])

  const redrawWithPending = useCallback((pending: Stroke | null) => {
    const canvas = canvasRef.current
    const context = canvas?.getContext("2d")
    if (!canvas || !context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    const scale = plane.width ? naturalSize.width / plane.width : 1
    paintStrokes(context, pending ? [...strokes, pending] : strokes, scale)
  }, [strokes, plane.width, naturalSize.width])

  useEffect(() => {
    redrawWithPending(null)
  }, [redrawWithPending])

  const toNaturalPoint = (event: React.PointerEvent): Point => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const scale = rect.width ? naturalSize.width / rect.width : 1
    return {
      x: clamp((event.clientX - rect.left) * scale, 0, naturalSize.width),
      y: clamp((event.clientY - rect.top) * scale, 0, naturalSize.height),
    }
  }

  const onPointerDown = (event: React.PointerEvent) => {
    event.preventDefault()
    try {
      ;(event.target as HTMLElement).setPointerCapture(event.pointerId)
    } catch {
      // 指针已释放等边缘场景下继续绘制，捕获失败仅影响拖出画布后的跟踪。
    }
    if (tool === "hand") {
      panRef.current = { startX: event.clientX, startY: event.clientY, view }
      setPanning(true)
      return
    }
    const size = tool === "eraser" ? eraserSize : brushSize
    drawingRef.current = { type: tool === "eraser" ? "eraser" : "brush", points: [toNaturalPoint(event)], size }
    setRedoStack([])
  }

  const onPointerMove = (event: React.PointerEvent) => {
    const viewportRect = viewportRef.current?.getBoundingClientRect()
    if (viewportRect) {
      setCursor({ x: event.clientX - viewportRect.left, y: event.clientY - viewportRect.top })
    }
    if (panRef.current) {
      const { startX, startY, view: base } = panRef.current
      setView(clampView(
        { zoom: base.zoom, x: base.x + (event.clientX - startX), y: base.y + (event.clientY - startY) },
        fitRef.current,
        viewportSizeRef.current,
      ))
      return
    }
    const pending = drawingRef.current
    if (!pending) return
    pending.points.push(toNaturalPoint(event))
    redrawWithPending(pending)
  }

  const onPointerUp = () => {
    panRef.current = null
    setPanning(false)
    const pending = drawingRef.current
    drawingRef.current = null
    if (!pending) return
    setStrokes((current) => [...current, pending])
    redrawWithPending(null)
  }

  const onPointerLeave = () => {
    onPointerUp()
    setCursor(null)
  }

  const undo = () => {
    setStrokes((current) => {
      if (!current.length) return current
      const next = [...current]
      const last = next.pop()
      if (last) setRedoStack((stack) => [...stack, last])
      return next
    })
  }

  const redo = () => {
    setRedoStack((stack) => {
      if (!stack.length) return stack
      const next = [...stack]
      const last = next.pop()
      if (last) setStrokes((current) => [...current, last])
      return next
    })
  }

  /** 把笔画合成到原图分辨率的白底黑区遮罩，产出 PNG File。 */
  const buildMask = useCallback(async (): Promise<File | null> => {
    if (!strokes.length || !plane.width) return null
    const canvas = document.createElement("canvas")
    canvas.width = naturalSize.width
    canvas.height = naturalSize.height
    const context = canvas.getContext("2d")
    if (!context) return null
    context.fillStyle = "#000000"
    context.fillRect(0, 0, canvas.width, canvas.height)
    const scale = naturalSize.width / plane.width
    for (const stroke of strokes) {
      context.globalCompositeOperation = stroke.type === "eraser" ? "destination-out" : "source-over"
      context.fillStyle = "#ffffff"
      context.strokeStyle = "#ffffff"
      context.lineWidth = stroke.size * scale
      context.lineCap = "round"
      context.lineJoin = "round"
      context.beginPath()
      stroke.points.forEach((point, index) => {
        if (index === 0) context.moveTo(point.x, point.y)
        else context.lineTo(point.x, point.y)
      })
      if (stroke.points.length === 1) {
        const [point] = stroke.points
        context.arc(point.x, point.y, context.lineWidth / 2, 0, Math.PI * 2)
        context.fill()
      }
      context.stroke()
    }
    context.globalCompositeOperation = "source-over"
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"))
    if (!blob) return null
    return new File([blob], "mask.png", { type: "image/png" })
  }, [strokes, naturalSize.width, naturalSize.height, plane.width])

  // 笔画变化即产出遮罩文件；无笔画时清空。
  useEffect(() => {
    let active = true
    if (!strokes.length) {
      onMaskReady(null)
      return
    }
    void buildMask().then((mask) => { if (active) onMaskReady(mask) })
    return () => { active = false }
  }, [strokes, buildMask, onMaskReady])

  const selectTool = (next: MaskPainterTool) => {
    if ((next === "brush" || next === "eraser") && tool === next) {
      // 再次点击当前画笔/橡皮：打开粗细调节。
      setSizeAnchor((anchor) => (anchor === next ? null : next))
      return
    }
    onToolChange(next)
    if (next === "hand") setSizeAnchor(null)
  }

  const activeSize = tool === "eraser" ? eraserSize : brushSize
  const sizeSlider = (
    <div className="studio-inpaint-size">
      <span>粗细</span>
      <Slider
        aria-label="画笔粗细"
        min={MASK_BRUSH_MIN}
        max={MASK_BRUSH_MAX}
        value={activeSize}
        onChange={(value) => (sizeAnchor === "eraser" ? setEraserSize(value) : setBrushSize(value))}
        style={{ width: 148, margin: "0 4px" }}
        tooltip={{ formatter: (value) => `${value} px` }}
      />
      <output>{activeSize}</output>
    </div>
  )

  const hasStrokes = strokes.length > 0
  const painting = tool !== "hand"

  return (
    <div className="studio-inpaint-editor" aria-label="遮罩编辑器">
      <div
        ref={viewportRef}
        className={`studio-inpaint-viewport ${painting ? "is-painting" : "is-panning"}${panning ? " is-panning-now" : ""}`}
      >
        <div
          className="studio-inpaint-plane"
          style={{
            width: plane.width || 1,
            height: plane.height || 1,
            transform: `translate(calc(-50% + ${view.x}px), calc(-50% + ${view.y}px)) scale(${view.zoom})`,
          }}
        >
          <img src={imageUrl} alt="原图" draggable={false} />
          <canvas
            ref={canvasRef}
            width={naturalSize.width}
            height={naturalSize.height}
            className="studio-inpaint-canvas"
            aria-label="遮罩绘制画布"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerLeave}
          />
        </div>
        {painting && cursor ? (
          <div
            className="studio-inpaint-cursor"
            style={{ left: cursor.x, top: cursor.y, width: activeSize * view.zoom, height: activeSize * view.zoom }}
          />
        ) : null}
        <div className="studio-inpaint-toolbar">
          <Tooltip title="画笔" placement="bottom">
            <Popover
              content={sizeSlider}
              trigger="click"
              placement="topLeft"
              open={sizeAnchor === "brush"}
              onOpenChange={(open) => setSizeAnchor(open ? "brush" : null)}
            >
              <Button
                type="text"
                className="studio-inpaint-tool-btn"
                data-active={tool === "brush"}
                aria-label="画笔涂抹"
                icon={<Brush size={16} />}
                onClick={() => selectTool("brush")}
              />
            </Popover>
          </Tooltip>
          <Tooltip title="橡皮擦" placement="bottom">
            <Popover
              content={sizeSlider}
              trigger="click"
              placement="topLeft"
              open={sizeAnchor === "eraser"}
              onOpenChange={(open) => setSizeAnchor(open ? "eraser" : null)}
            >
              <Button
                type="text"
                className="studio-inpaint-tool-btn"
                data-active={tool === "eraser"}
                aria-label="橡皮擦除"
                icon={<Eraser size={16} />}
                onClick={() => selectTool("eraser")}
              />
            </Popover>
          </Tooltip>
          <Tooltip title="抓手" placement="bottom">
            <Button
              type="text"
              className="studio-inpaint-tool-btn"
              data-active={tool === "hand"}
              aria-label="抓手平移"
              icon={<Hand size={16} />}
              onClick={() => selectTool("hand")}
            />
          </Tooltip>
          <span className="studio-inpaint-toolbar-divider" aria-hidden="true" />
          <Tooltip title="撤销" placement="bottom">
            <Button
              type="text"
              className="studio-inpaint-tool-btn"
              aria-label="撤销上一笔"
              disabled={!hasStrokes}
              icon={<Undo2 size={16} />}
              onClick={undo}
            />
          </Tooltip>
          <Tooltip title="重做" placement="bottom">
            <Button
              type="text"
              className="studio-inpaint-tool-btn"
              aria-label="重做"
              disabled={!redoStack.length}
              icon={<Redo2 size={16} />}
              onClick={redo}
            />
          </Tooltip>
        </div>
        <div className="studio-inpaint-zoom">
          <Tooltip title="缩小" placement="top">
            <Button type="text" className="studio-inpaint-tool-btn" aria-label="缩小" icon={<Minus size={14} />} onClick={() => zoomAt(1 / ZOOM_STEP)} />
          </Tooltip>
          <Tooltip title="点击复位到适应画布" placement="top">
            <Button type="text" className="studio-inpaint-zoom-value" aria-label="缩放比例，点击复位" onClick={() => setView({ zoom: 1, x: 0, y: 0 })}>
              {Math.round(view.zoom * 100)}%
            </Button>
          </Tooltip>
          <Tooltip title="放大" placement="top">
            <Button type="text" className="studio-inpaint-tool-btn" aria-label="放大" icon={<Plus size={14} />} onClick={() => zoomAt(ZOOM_STEP)} />
          </Tooltip>
        </div>
      </div>
    </div>
  )
}
