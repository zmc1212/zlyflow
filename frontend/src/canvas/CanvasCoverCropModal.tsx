import { Alert, Button, Modal, Segmented, Slider, Spin } from "antd"
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react"
import {
  CANVAS_COVER_CROP_MAX_ZOOM,
  canvasCoverAspectRatio,
  canvasCoverCropRect,
  canvasCoverFrameSize,
  moveCanvasCoverCropFocus,
  type CanvasCoverCropAspect,
  type CanvasCoverCropRect,
  type CanvasCoverFocus,
} from "./canvas-cover"

const CROP_STAGE_LONG_EDGE = 360

const ASPECT_OPTIONS: { label: string; value: CanvasCoverCropAspect }[] = [
  { label: "原始", value: "original" },
  { label: "16:9", value: "16:9" },
  { label: "9:16", value: "9:16" },
  { label: "1:1", value: "1:1" },
]

function cropStageSize(aspectRatio: number) {
  return aspectRatio >= 1
    ? { width: CROP_STAGE_LONG_EDGE, height: Math.round((CROP_STAGE_LONG_EDGE / aspectRatio) * 100) / 100 }
    : { width: Math.round((CROP_STAGE_LONG_EDGE * aspectRatio) * 100) / 100, height: CROP_STAGE_LONG_EDGE }
}

type CanvasCoverCropModalProps = {
  open: boolean
  file: File | null
  applying: boolean
  onCancel: () => void
  onApply: (crop: CanvasCoverCropRect) => void
}

export default function CanvasCoverCropModal({
  open,
  file,
  applying,
  onCancel,
  onApply,
}: CanvasCoverCropModalProps) {
  const [imageSrc, setImageSrc] = useState("")
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [aspect, setAspectState] = useState<CanvasCoverCropAspect>("original")
  const [zoom, setZoomState] = useState(1)
  const [focus, setFocusState] = useState<CanvasCoverFocus>({ x: 0.5, y: 0.5 })
  const aspectRef = useRef<CanvasCoverCropAspect>("original")
  const zoomRef = useRef(1)
  const focusRef = useRef<CanvasCoverFocus>({ x: 0.5, y: 0.5 })
  const dragRef = useRef<{ x: number; y: number } | null>(null)

  const setAspect = (value: CanvasCoverCropAspect) => {
    aspectRef.current = value
    setAspectState(value)
  }
  const setZoom = (value: number) => {
    zoomRef.current = value
    setZoomState(value)
  }
  const setFocus = (value: CanvasCoverFocus) => {
    focusRef.current = value
    setFocusState(value)
  }
  const resetCrop = () => {
    setZoom(1)
    setFocus({ x: 0.5, y: 0.5 })
  }

  useEffect(() => {
    if (!open || !file) return
    setLoading(true)
    setFailed(false)
    setImageSize(null)
    aspectRef.current = "original"
    zoomRef.current = 1
    focusRef.current = { x: 0.5, y: 0.5 }
    setAspectState("original")
    setZoomState(1)
    setFocusState({ x: 0.5, y: 0.5 })
    const url = URL.createObjectURL(file)
    setImageSrc(url)
    const image = new Image()
    image.onload = () => {
      if (image.naturalWidth > 0 && image.naturalHeight > 0) {
        setImageSize({ width: image.naturalWidth, height: image.naturalHeight })
      } else {
        setFailed(true)
      }
      setLoading(false)
    }
    image.onerror = () => {
      setFailed(true)
      setLoading(false)
    }
    image.src = url
    return () => {
      image.onload = null
      image.onerror = null
      URL.revokeObjectURL(url)
      setImageSrc("")
    }
  }, [open, file])

  const aspectRatio = canvasCoverAspectRatio(
    aspect,
    imageSize?.width ?? 16,
    imageSize?.height ?? 9,
  )
  const stage = cropStageSize(aspectRatio)
  const crop = imageSize
    ? canvasCoverCropRect(imageSize.width, imageSize.height, aspectRatio, zoom, focus)
    : null
  const output = crop ? canvasCoverFrameSize(crop.width, crop.height) : null
  const scale = crop ? stage.width / crop.width : 1

  const panBy = (deltaX: number, deltaY: number) => {
    if (!imageSize) return
    const currentAspect = canvasCoverAspectRatio(aspectRef.current, imageSize.width, imageSize.height)
    const currentCrop = canvasCoverCropRect(
      imageSize.width,
      imageSize.height,
      currentAspect,
      zoomRef.current,
      focusRef.current,
    )
    if (!currentCrop) return
    const currentStage = cropStageSize(currentAspect)
    const next = moveCanvasCoverCropFocus(
      imageSize.width,
      imageSize.height,
      currentCrop,
      currentStage.width,
      currentStage.height,
      deltaX,
      deltaY,
    )
    if (next) setFocus(next)
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!crop || applying) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x: event.clientX, y: event.clientY }
  }
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const last = dragRef.current
    if (!last || applying) return
    const deltaX = event.clientX - last.x
    const deltaY = event.clientY - last.y
    if (!deltaX && !deltaY) return
    dragRef.current = { x: event.clientX, y: event.clientY }
    panBy(deltaX, deltaY)
  }
  const endDrag = () => {
    dragRef.current = null
  }
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 24 : 8
    if (event.key === "ArrowLeft") panBy(step, 0)
    else if (event.key === "ArrowRight") panBy(-step, 0)
    else if (event.key === "ArrowUp") panBy(0, step)
    else if (event.key === "ArrowDown") panBy(0, -step)
    else return
    event.preventDefault()
  }

  return (
    <Modal
      className="canvas-dialog canvas-cover-crop-dialog"
      width={560}
      title="裁切封面"
      open={open}
      okText="应用裁切"
      cancelText="取消"
      okButtonProps={{ disabled: !crop || loading || failed }}
      confirmLoading={applying}
      maskClosable={!applying}
      onOk={() => {
        if (crop && !applying) onApply(crop)
      }}
      onCancel={() => {
        if (!applying) onCancel()
      }}
      destroyOnHidden
    >
      {failed ? (
        <Alert
          type="error"
          showIcon
          title="图片读取失败"
          description="请选择可正常打开的 JPG、PNG 或 WebP 图片后重试。"
        />
      ) : (
        <div className="canvas-cover-crop-body">
          <div className="canvas-cover-crop-stage-wrap">
            {loading || !crop || !imageSize || !imageSrc ? (
              <div className="canvas-cover-crop-loading"><Spin size="small" /> 图片加载中…</div>
            ) : (
              <div
                className="canvas-cover-crop-stage"
                style={{ width: stage.width, height: stage.height }}
                role="group"
                aria-label="封面裁切区域，拖动或使用方向键调整取景"
                tabIndex={0}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onLostPointerCapture={endDrag}
                onKeyDown={handleKeyDown}
              >
                <img
                  className="canvas-cover-crop-image"
                  src={imageSrc}
                  alt="待裁切的封面图片"
                  draggable={false}
                  style={{
                    width: imageSize.width * scale,
                    height: imageSize.height * scale,
                    left: -crop.x * scale,
                    top: -crop.y * scale,
                  }}
                />
                <div className="canvas-cover-crop-grid" aria-hidden="true" />
              </div>
            )}
          </div>
          <div className="canvas-cover-crop-controls">
            <div className="canvas-cover-crop-control">
              <span className="canvas-cover-crop-label">比例</span>
              <Segmented
                size="small"
                value={aspect}
                onChange={(value) => setAspect(value as CanvasCoverCropAspect)}
                options={ASPECT_OPTIONS}
                disabled={loading || failed}
              />
            </div>
            <div className="canvas-cover-crop-zoom">
              <span className="canvas-cover-crop-label">缩放</span>
              <Slider
                min={1}
                max={CANVAS_COVER_CROP_MAX_ZOOM}
                step={0.05}
                value={zoom}
                disabled={loading || failed}
                tooltip={{ formatter: (value) => `${Number(value).toFixed(2)}x` }}
                onChange={(value) => setZoom(value)}
                aria-label="封面裁切缩放"
              />
            </div>
            <Button
              size="small"
              type="text"
              disabled={loading || failed || applying}
              onClick={resetCrop}
            >
              重置取景
            </Button>
          </div>
          <div className="canvas-cover-crop-meta">
            <span>
              {output
                ? `裁切 ${Math.round(crop!.width)} × ${Math.round(crop!.height)} px`
                : "等待图片加载"}
            </span>
            <span>{output ? `输出 ${output.width} × ${output.height} px JPEG` : ""}</span>
          </div>
          <p className="canvas-dialog-hint">在预览区拖动图片或用方向键移动取景，缩放后输出仍会压缩到 320 px 以内。</p>
        </div>
      )}
    </Modal>
  )
}
