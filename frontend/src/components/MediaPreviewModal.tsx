import { Button, Modal, Tag, Tooltip } from "antd"
import { Download, FileImage, Film, Info, X } from "lucide-react"
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react"
import { mediaAspectVars, parseMediaAspect, type MediaAspectSize } from "../lib/utils"

export type PreviewMediaKind = "image" | "video"

export type MediaPreviewAction = {
  key: string
  label: string
  icon?: ReactNode
  onClick: () => void
  type?: "primary" | "default"
  danger?: boolean
  disabled?: boolean
}

interface MediaPreviewModalProps {
  open: boolean
  kind: PreviewMediaKind
  src: string
  title: string
  description?: string
  onClose: () => void
  actions?: MediaPreviewAction[]
  downloadName?: string
  aspectRatio?: string
}

function measureAspect(width: number, height: number): MediaAspectSize | undefined {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return undefined
  return { width, height }
}

/** 统一的图片 / 视频资产检视器：媒体居左，系统支持的操作集中在右侧。 */
export default function MediaPreviewModal({
  open,
  kind,
  src,
  title,
  description,
  onClose,
  actions = [],
  downloadName,
  aspectRatio,
}: MediaPreviewModalProps) {
  const typeLabel = kind === "video" ? "视频" : "图片"
  const hint = useMemo(() => parseMediaAspect(aspectRatio), [aspectRatio])
  const [measured, setMeasured] = useState<MediaAspectSize>()
  const aspect = measured || hint
  const orientation = aspect && aspect.height > aspect.width ? "portrait" : aspect && aspect.width === aspect.height ? "square" : "landscape"

  useEffect(() => {
    setMeasured(undefined)
  }, [src, kind])

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      destroyOnHidden
      width="100vw"
      rootClassName="media-preview-root"
      className="media-preview-modal"
    >
      <section className="media-preview-shell" aria-label={`${title}预览`}>
        <div className="media-preview-stage">
          <div
            className={`media-preview-canvas media-preview-canvas-${kind} is-${orientation}`}
            style={mediaAspectVars(aspect) as CSSProperties}
          >
            {kind === "video" ? (
              <video
                src={src}
                controls
                playsInline
                autoPlay
                preload="metadata"
                aria-label={title}
                onLoadedMetadata={(event) => setMeasured(measureAspect(event.currentTarget.videoWidth, event.currentTarget.videoHeight))}
              />
            ) : (
              <img
                src={src}
                alt={title}
                onLoad={(event) => setMeasured(measureAspect(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight))}
              />
            )}
          </div>
        </div>
        <nav className="media-preview-rail" aria-label="媒体操作">
          <Tooltip title="关闭预览" placement="left">
            <Button type="text" shape="circle" aria-label="关闭预览" icon={<X size={19} />} onClick={onClose} />
          </Tooltip>
          <Tooltip title="下载原文件" placement="left">
            <a className="media-preview-rail-download" href={src} download={downloadName || title} aria-label="下载原文件">
              <Download size={18} />
            </a>
          </Tooltip>
        </nav>
        <aside className="media-preview-sidebar">
          <div className="media-preview-heading">
            <div className="media-preview-kind"><Tag icon={kind === "video" ? <Film size={12} /> : <FileImage size={12} />}>{typeLabel}</Tag></div>
            <span className="media-preview-heading-label">资产详情</span>
          </div>
          <div className="media-preview-copy">
            <h2 title={title}>{title}</h2>
            {description ? <p>{description}</p> : <p className="is-empty">在这里查看完整媒体内容。</p>}
          </div>
          <div className="media-preview-actions" aria-label="系统支持的快捷操作">
            {actions.map((action) => (
              <Button key={action.key} type={action.type || "default"} danger={action.danger} disabled={action.disabled} icon={action.icon} onClick={action.onClick}>
                {action.label}
              </Button>
            ))}
          </div>
          <div className="media-preview-tip"><Info size={14} /> 仅展示当前系统已支持的操作</div>
        </aside>
      </section>
    </Modal>
  )
}
