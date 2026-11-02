import { Button, Modal, Slider, Tag, Tooltip } from "antd"
import { ChevronDown, ChevronUp, Download, FileImage, Film, Info, Maximize, Minimize, Pause, Play, Volume2, VolumeX, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
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

export type MediaPreviewNavigation = {
  hasPrev?: boolean
  hasNext?: boolean
  onPrev?: () => void
  onNext?: () => void
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
  navigation?: MediaPreviewNavigation
}

function measureAspect(width: number, height: number): MediaAspectSize | undefined {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return undefined
  return { width, height }
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00"
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  return `${minutes}:${String(rest).padStart(2, "0")}`
}

/** 统一的图片 / 视频资产检视器：媒体自适应撑满舞台，系统支持的操作集中在右侧。 */
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
  navigation,
}: MediaPreviewModalProps) {
  const typeLabel = kind === "video" ? "视频" : "图片"
  const hint = useMemo(() => parseMediaAspect(aspectRatio), [aspectRatio])
  const [measured, setMeasured] = useState<MediaAspectSize>()
  const aspect = measured || hint
  const orientation = aspect && aspect.height > aspect.width ? "portrait" : aspect && aspect.width === aspect.height ? "square" : "landscape"

  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [muted, setMuted] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [scrubbing, setScrubbing] = useState(false)
  const [scrubValue, setScrubValue] = useState(0)

  useEffect(() => {
    setMeasured(undefined)
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
    setScrubbing(false)
  }, [src, kind])

  useEffect(() => {
    const onFullscreenChange = () => setFullscreen(document.fullscreenElement === canvasRef.current)
    document.addEventListener("fullscreenchange", onFullscreenChange)
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange)
  }, [])

  const hasNavigation = Boolean(navigation?.onPrev || navigation?.onNext)
  useEffect(() => {
    if (!hasNavigation) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowUp" && navigation?.hasPrev) navigation.onPrev?.()
      if (event.key === "ArrowDown" && navigation?.hasNext) navigation.onNext?.()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [hasNavigation, navigation])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) void video.play().catch(() => {})
    else video.pause()
  }, [])

  const toggleMute = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    video.muted = !video.muted
    setMuted(video.muted)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
    else void canvasRef.current?.requestFullscreen().catch(() => {})
  }, [])

  const seek = useCallback((value: number) => {
    const video = videoRef.current
    if (!video || !Number.isFinite(value)) return
    video.currentTime = value
    setCurrentTime(value)
  }, [])

  const barVisible = !playing || hovered || scrubbing

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      destroyOnHidden
      width="100vw"
      zIndex={1100}
      rootClassName="media-preview-root"
      className="media-preview-modal"
    >
      <section className="media-preview-shell" aria-label={`${title}预览`}>
        <div className="media-preview-stage">
          <div
            ref={canvasRef}
            className={`media-preview-canvas media-preview-canvas-${kind} is-${orientation}${hasNavigation ? " has-navigation" : ""}`}
            style={mediaAspectVars(aspect) as CSSProperties}
          >
            <div
              className={`media-preview-frame ${barVisible ? "is-bar-visible" : "is-bar-hidden"}`}
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
              onDoubleClick={kind === "video" ? toggleFullscreen : undefined}
            >
              {kind === "video" ? (
                <>
                  <video
                    ref={videoRef}
                    src={src}
                    playsInline
                    autoPlay
                    preload="metadata"
                    aria-label={title}
                    onClick={togglePlay}
                    onLoadedMetadata={(event) => {
                      setMeasured(measureAspect(event.currentTarget.videoWidth, event.currentTarget.videoHeight))
                      const total = event.currentTarget.duration
                      if (Number.isFinite(total)) setDuration(total)
                    }}
                    onTimeUpdate={(event) => {
                      if (!scrubbing) setCurrentTime(event.currentTarget.currentTime)
                      // 自动播放被策略打断/恢复时，以元素真实状态为准，避免控件状态脱同步
                      setPlaying(!event.currentTarget.paused)
                    }}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                  />
                  {!playing && (
                    <button type="button" className="media-preview-center" aria-label="播放" onClick={togglePlay}>
                      <span className="media-preview-center-btn"><Play size={26} /></span>
                    </button>
                  )}
                  <div className="media-preview-bar">
                    <Slider
                      className="media-preview-seek"
                      min={0}
                      max={duration > 0 ? duration : 1}
                      step={0.1}
                      value={scrubbing ? scrubValue : Math.min(currentTime, duration || currentTime)}
                      tooltip={{ formatter: (value) => formatTime(Number(value)) }}
                      onChange={(value) => { setScrubbing(true); setScrubValue(Number(value)); seek(Number(value)) }}
                      onChangeComplete={() => setScrubbing(false)}
                    />
                    <div className="media-preview-bar-row">
                      <button type="button" aria-label={playing ? "暂停" : "播放"} onClick={togglePlay}>
                        {playing ? <Pause size={17} /> : <Play size={17} />}
                      </button>
                      <span className="media-preview-time">{formatTime(currentTime)} / {formatTime(duration)}</span>
                      <span className="media-preview-spacer" />
                      <button type="button" aria-label={muted ? "取消静音" : "静音"} onClick={toggleMute}>
                        {muted ? <VolumeX size={17} /> : <Volume2 size={17} />}
                      </button>
                      <button type="button" aria-label={fullscreen ? "退出全屏" : "全屏播放"} onClick={toggleFullscreen}>
                        {fullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <img
                  src={src}
                  alt={title}
                  onLoad={(event) => setMeasured(measureAspect(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight))}
                />
              )}
            </div>
            {hasNavigation ? (
              <div className="media-preview-nav">
                <button type="button" aria-label="上一个" title="上一个" disabled={!navigation?.hasPrev} onClick={navigation?.onPrev}>
                  <ChevronUp size={22} />
                </button>
                <button type="button" aria-label="下一个" title="下一个" disabled={!navigation?.hasNext} onClick={navigation?.onNext}>
                  <ChevronDown size={22} />
                </button>
              </div>
            ) : null}
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
