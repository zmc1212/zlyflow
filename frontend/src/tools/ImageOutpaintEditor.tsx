import { Button, Input, Modal, Segmented, message } from "antd"
import { promptAutoSize } from "../prompt-autosize"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  OUTPAINT_MAX_SIDE,
  OUTPAINT_RATIO_PRESETS,
  OUTPAINT_SCALE_PRESETS,
  evenizedPads,
  formatOutpaintScale,
  matchedRatioPreset,
  matchedScalePreset,
  outpaintCanvasSize,
  outpaintScaleFactor,
  padsAfterDrag,
  padsForOriginalRatio,
  padsForRatio,
  padsForScale,
  type OutpaintHandle,
  type OutpaintPads,
  type OutpaintRatioId,
} from "../generation/outpaint-editor"

export type OutpaintEditorPayload = {
  targetWidth: number
  targetHeight: number
  offsetX: number
  offsetY: number
  prompt: string
}

type EditorSource = { preview: string; width: number; height: number }

const HANDLE_CURSORS: Record<OutpaintHandle, string> = {
  nw: "nwse-resize", n: "ns-resize", ne: "nesw-resize", e: "ew-resize",
  se: "nwse-resize", s: "ns-resize", sw: "nesw-resize", w: "ew-resize",
}

const HANDLES: OutpaintHandle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]

function handleStyle(handle: OutpaintHandle): React.CSSProperties {
  const size = 10
  const offset = -size / 2
  const center = "calc(50% - 5px)"
  const position: React.CSSProperties = {}
  if (handle.includes("w")) position.left = offset
  if (handle.includes("e")) position.right = offset
  if (handle === "n" || handle === "s") position.left = center
  if (handle.includes("n")) position.top = offset
  if (handle.includes("s")) position.bottom = offset
  if (handle === "w" || handle === "e") position.top = center
  return { ...position, width: size, height: size, cursor: HANDLE_CURSORS[handle] }
}

/** 比例预设的小形状图标（即梦同款线框示意）。 */
function RatioIcon({ id }: { id: OutpaintRatioId }) {
  const shapes: Record<OutpaintRatioId, { w: number; h: number }> = {
    original: { w: 16, h: 11 },
    "1:1": { w: 11, h: 11 },
    "3:4": { w: 9, h: 12 },
    "9:16": { w: 7, h: 12 },
    "4:3": { w: 14, h: 11 },
  }
  const shape = shapes[id]
  return (
    <svg width="18" height="14" viewBox="0 0 18 14" aria-hidden="true">
      {id === "original" ? (
        <>
          <rect x={(18 - shape.w) / 2} y={(14 - shape.h) / 2} width={shape.w} height={shape.h} rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <rect x={(18 - shape.w) / 2 - 1.5} y={(14 - shape.h) / 2 - 1.5} width={shape.w + 3} height={shape.h + 3} rx="2" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" opacity="0.7" />
        </>
      ) : (
        <rect x={(18 - shape.w) / 2} y={(14 - shape.h) / 2} width={shape.w} height={shape.h} rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      )}
    </svg>
  )
}

type DragState = { handle: OutpaintHandle; startX: number; startY: number; startPads: OutpaintPads }

/** 即梦式扩图编辑器：原图居中固定，拖拽手柄/倍数/比例预设决定目标画布，扩展区由模型补全。 */
export default function ImageOutpaintEditor({
  source, submitting, onApply, onCancel,
}: {
  source: EditorSource
  submitting: boolean
  onApply: (payload: OutpaintEditorPayload) => void
  onCancel: () => void
}) {
  const [pads, setPads] = useState<OutpaintPads>(() => padsForScale(source, 1.5))
  const [prompt, setPrompt] = useState("")
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null)
  const [stageSize, setStageSize] = useState<{ w: number; h: number } | null>(null)
  const [lockedScale, setLockedScale] = useState<number | null>(null)
  const dragRef = useRef<DragState | null>(null)

  useEffect(() => {
    // antd Modal 子节点延迟挂载：用 callback ref 驱动，stage 就绪后才测量与监听。
    if (!stageEl) return
    const measure = () => {
      const width = stageEl.clientWidth
      const height = stageEl.clientHeight
      if (width <= 0 || height <= 0) return
      setStageSize((prev) => (prev && prev.w === width && prev.h === height ? prev : { w: width, h: height }))
    }
    measure()
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null
    observer?.observe(stageEl)
    window.addEventListener("resize", measure)
    return () => {
      observer?.disconnect()
      window.removeEventListener("resize", measure)
    }
  }, [stageEl])

  const canvas = outpaintCanvasSize(source, pads)
  const factor = outpaintScaleFactor(source, pads)
  const fitScale = useMemo(() => {
    if (!stageSize) return 0
    return Math.min((stageSize.w - 56) / canvas.width, (stageSize.h - 56) / canvas.height, 1)
  }, [stageSize, canvas.width, canvas.height])
  const scale = Math.max(lockedScale ?? fitScale, 0.01)
  const matchedScale = matchedScalePreset(factor)
  const sourceRatio = source.width / source.height
  const canvasRatio = canvas.width / canvas.height
  // 固定比例未命中时回落"原比例"高亮（原图比例 ±0.5%）。
  const matchedRatio: OutpaintRatioId | null =
    matchedRatioPreset(source, pads)
    ?? (Math.abs(canvasRatio - sourceRatio) / sourceRatio < 0.005 ? "original" : null)
  const submitted = evenizedPads(source, pads)
  const submitCanvas = outpaintCanvasSize(source, submitted)

  const beginDrag = (event: React.PointerEvent<HTMLDivElement>, handle: OutpaintHandle) => {
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { handle, startX: event.clientX, startY: event.clientY, startPads: pads }
    setLockedScale(scale)
  }
  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const dx = (event.clientX - drag.startX) / scale
    const dy = (event.clientY - drag.startY) / scale
    setPads(padsAfterDrag(drag.startPads, source, drag.handle, dx, dy))
  }
  const endDrag = () => {
    dragRef.current = null
    setLockedScale(null)
  }

  const applyScalePreset = (value: number | string) => {
    const presetScale = Number(value)
    if (!Number.isFinite(presetScale)) return
    setPads(padsForScale(source, presetScale))
  }

  const applyRatioPreset = (id: OutpaintRatioId) => {
    const preset = OUTPAINT_RATIO_PRESETS.find((item) => item.id === id)
    if (!preset) return
    setPads(preset.ratio === null ? padsForOriginalRatio(source, pads) : padsForRatio(source, preset.ratio))
  }

  const apply = () => {
    if (submitCanvas.width > Math.max(OUTPAINT_MAX_SIDE, source.width) || submitCanvas.height > Math.max(OUTPAINT_MAX_SIDE, source.height)) {
      message.warning(`目标画布单边不能超过 ${OUTPAINT_MAX_SIDE} 像素`)
      return
    }
    onApply({
      targetWidth: submitCanvas.width,
      targetHeight: submitCanvas.height,
      offsetX: submitted.left,
      offsetY: submitted.top,
      prompt: prompt.trim(),
    })
  }

  return (
    <Modal
      open
      title="扩图"
      width={840}
      centered
      destroyOnHidden
      footer={null}
      onCancel={submitting ? undefined : onCancel}
      wrapClassName="studio-outpaint-modal"
    >
      <div className="studio-outpaint-editor">
        <div className="studio-outpaint-stage" ref={setStageEl}>
          <span className="studio-outpaint-zoom">{formatOutpaintScale(factor)}</span>
          {stageSize && fitScale > 0 ? (
            <div
              className="studio-outpaint-frame"
              style={{ width: canvas.width * scale, height: canvas.height * scale }}
            >
              <img
                src={source.preview}
                alt="原图"
                draggable={false}
                className="studio-outpaint-original"
                style={{
                  left: pads.left * scale,
                  top: pads.top * scale,
                  width: source.width * scale,
                  height: source.height * scale,
                }}
              />
              {HANDLES.map((handle) => (
                <div
                  key={handle}
                  className="studio-outpaint-handle"
                  style={handleStyle(handle)}
                  onPointerDown={(event) => beginDrag(event, handle)}
                  onPointerMove={moveDrag}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                />
              ))}
            </div>
          ) : null}
        </div>

        <div className="studio-outpaint-scale-row">
          <Segmented
            key={matchedScale ?? "custom"}
            value={matchedScale ?? undefined}
            options={OUTPAINT_SCALE_PRESETS.map((preset) => ({ label: formatOutpaintScale(preset), value: preset }))}
            onChange={(value) => applyScalePreset(value as number)}
          />
        </div>

        <div className="studio-outpaint-ratio-row" role="radiogroup" aria-label="目标画幅比例">
          {OUTPAINT_RATIO_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={matchedRatio === preset.id}
              className={
                matchedRatio === preset.id
                  ? "studio-outpaint-ratio is-active"
                  : "studio-outpaint-ratio"
              }
              onClick={() => applyRatioPreset(preset.id)}
            >
              <RatioIcon id={preset.id} />
              <span>{preset.label}</span>
            </button>
          ))}
        </div>

        <Input.TextArea
          autoSize={promptAutoSize(2)}
          maxLength={500}
          placeholder="描述想要扩图的内容，不填将基于原图生成"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />

        <div className="studio-outpaint-footer">
          <span className="studio-outpaint-output-size">输出 {submitCanvas.width}×{submitCanvas.height}</span>
          <Button type="primary" loading={submitting} onClick={apply}>应用</Button>
        </div>
      </div>
    </Modal>
  )
}
