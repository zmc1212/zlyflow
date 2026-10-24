import { Empty, Modal, Segmented, Spin, message } from "antd"
import { useEffect, useMemo, useRef, useState } from "react"
import { useStudioTheme } from "../ThemeProvider"
import {
  buildCanvasExportScene,
  canvasExportPreviewScale,
  canvasPngFileName,
  type CanvasExportBackground,
  type CanvasExportScope,
} from "./canvas-export"
import { drawCanvasExport, loadCanvasExportImages } from "./canvas-export-render"
import type { CanvasEdge, CanvasNode } from "./canvas-model"

type CanvasExportDialogProps = {
  open: boolean
  title: string
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  selectedNodeIds: string[]
  onClose: () => void
}

function megapixelLabel(width: number, height: number): string {
  return `${(width * height / 1_000_000).toFixed(1)} MP`
}

export default function CanvasExportDialog({
  open,
  title,
  nodes,
  edges,
  selectedNodeIds,
  onClose,
}: CanvasExportDialogProps) {
  const { mode } = useStudioTheme()
  const previewRef = useRef<HTMLCanvasElement>(null)
  const [scope, setScope] = useState<CanvasExportScope>("all")
  const [background, setBackground] = useState<CanvasExportBackground>("light")
  const [scale, setScale] = useState<1 | 2>(2)
  const [images, setImages] = useState<Map<string, HTMLImageElement>>(new Map())
  const [loadingImages, setLoadingImages] = useState(false)
  const [exporting, setExporting] = useState(false)

  const selectionCount = selectedNodeIds.length
  const scene = useMemo(() => buildCanvasExportScene(nodes, edges, {
    scope,
    selectedNodeIds,
    background,
    theme: mode,
    scale,
  }), [background, edges, mode, nodes, scale, scope, selectedNodeIds])

  useEffect(() => {
    if (!open) return
    setBackground(mode)
    setScale(2)
    setScope("all")
  }, [open, mode])

  useEffect(() => {
    if (selectionCount) return
    setScope("all")
  }, [selectionCount])

  useEffect(() => {
    if (!open || !scene) return
    let cancelled = false
    setImages(new Map())
    setLoadingImages(true)
    void loadCanvasExportImages(scene)
      .then((loaded) => {
        if (!cancelled) setImages(loaded)
      })
      .finally(() => {
        if (!cancelled) setLoadingImages(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, scene])

  useEffect(() => {
    if (!open || !scene || !previewRef.current) return
    drawCanvasExport(previewRef.current, scene, images, canvasExportPreviewScale(scene.bounds))
  }, [images, open, scene])

  const handleExport = async () => {
    if (!scene || exporting) return
    setExporting(true)
    try {
      const canvas = document.createElement("canvas")
      drawCanvasExport(canvas, scene, images, scene.scale)
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"))
      if (!blob) throw new Error("PNG 编码失败，请缩小画布后重试")
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = canvasPngFileName(title)
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      message.success("PNG 已导出")
      onClose()
    } catch (error) {
      message.error(error instanceof Error ? error.message : "PNG 导出失败")
    } finally {
      setExporting(false)
    }
  }

  const downscaled = Boolean(scene && scene.scale + 0.001 < scene.requestedScale)

  return (
    <Modal
      className="canvas-dialog canvas-export-dialog"
      width={880}
      title="导出 PNG"
      open={open}
      okText="导出 PNG"
      cancelText="取消"
      okButtonProps={{ disabled: !scene || loadingImages }}
      confirmLoading={exporting}
      onOk={() => { void handleExport() }}
      onCancel={() => {
        if (!exporting) onClose()
      }}
      destroyOnHidden
    >
      {scene ? (
        <>
          <div className="canvas-export-controls">
            <div className="canvas-export-control">
              <span className="canvas-export-label">范围</span>
              <Segmented
                size="small"
                value={scope}
                onChange={(value) => setScope(value as CanvasExportScope)}
                options={[
                  { label: "整个画布", value: "all" },
                  { label: selectionCount ? `选中 ${selectionCount} 个节点` : "选中节点", value: "selection", disabled: !selectionCount },
                ]}
              />
            </div>
            <div className="canvas-export-control">
              <span className="canvas-export-label">背景</span>
              <Segmented
                size="small"
                value={background}
                onChange={(value) => setBackground(value as CanvasExportBackground)}
                options={[
                  { label: "浅色", value: "light" },
                  { label: "深色", value: "dark" },
                  { label: "透明", value: "transparent" },
                ]}
              />
            </div>
            <div className="canvas-export-control">
              <span className="canvas-export-label">清晰度</span>
              <Segmented
                size="small"
                value={String(scale)}
                onChange={(value) => setScale(value === "1" ? 1 : 2)}
                options={[
                  { label: "标准 1x", value: "1" },
                  { label: "高清 2x", value: "2" },
                ]}
              />
            </div>
          </div>

          <div
            className={`canvas-export-preview${background === "transparent" ? " is-transparent" : ""}`}
            style={{ backgroundColor: background === "dark" ? "#0b0d10" : background === "light" ? (mode === "dark" ? "#0b0d10" : "#eef0f3") : undefined }}
          >
            <canvas ref={previewRef} role="img" aria-label="PNG 导出预览" />
            {loadingImages ? (
              <div className="canvas-export-loading"><Spin size="small" /> 素材加载中…</div>
            ) : null}
          </div>

          <div className="canvas-export-meta">
            <span>{scene.nodeCount} 个节点 · {scene.edgeCount} 条连线</span>
            <span>输出 {scene.width} × {scene.height} px · {megapixelLabel(scene.width, scene.height)}</span>
          </div>
          {downscaled ? (
            <p className="canvas-dialog-hint">画布较大，已按 {scene.scale}x 输出（单边上限 8192 px、总量上限 24 MP）。</p>
          ) : null}
          <p className="canvas-dialog-hint">导出画布的结构示意图；图片与可用的视频封面会一并呈现，无法加载的素材使用占位卡。</p>
        </>
      ) : (
        <Empty description="画布还没有可导出的节点" />
      )}
    </Modal>
  )
}
