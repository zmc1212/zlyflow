import { Button, ConfigProvider, Dropdown, Slider, Tooltip, message } from "antd"
import { Download, HardDrive, Maximize2, MoreHorizontal, Pause, Play, Sparkles, Volume2, VolumeX, type LucideIcon } from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react"
import { mediaAspectVars, parseMediaAspect, type MediaAspectSize } from "../lib/utils"
import type { MediaHandoffSource } from "../media-handoff"
import { cloudThumbnailSrc } from "../media-thumbnails"
import { mediaActionBar, mediaActionMenu, type MediaActionItem } from "./media-actions"
import { formatVideoTime, videoResultKey, type VideoResult } from "./video-result-model"
import "./video-results.css"

export type { VideoResult } from "./video-result-model"

type ResultActions = {
  onDownload: (result: VideoResult) => void
  onPreview?: (result: VideoResult) => void
  onEnhance?: (result: VideoResult) => void
  enhancing?: boolean
  /** 卡片按每个视频版本自己的定位符取动作，注册表仍由宿主持有。 */
  resolveActions?: (source: MediaHandoffSource) => MediaActionItem[]
  onAction?: (action: MediaActionItem, result: VideoResult) => void
}

const videoSeekTheme = {
  components: {
    Slider: { handleSize: 6, handleSizeHover: 6, handleActiveOutlineColor: "transparent" },
  },
}

function ActionIcon({ icon: Icon, size }: { icon: LucideIcon; size: number }) {
  return <Icon size={size} />
}

function VideoResultCard({ result, aspectRatio, ...actions }: ResultActions & {
  result: VideoResult; aspectRatio?: string
}) {
  const hint = useMemo(() => parseMediaAspect(aspectRatio), [aspectRatio])
  const [measured, setMeasured] = useState<MediaAspectSize>()
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [playError, setPlayError] = useState(false)
  const [seekEngaged, setSeekEngaged] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const mediaRef = useRef<HTMLDivElement>(null)
  const moreRef = useRef<HTMLButtonElement>(null)
  const seekAreaRef = useRef<HTMLDivElement>(null)
  const seekPointerDownRef = useRef(false)
  const menuId = useId()
  const [messageApi, messageHolder] = message.useMessage()
  const aspect = measured || hint
  const portrait = aspect && aspect.height > aspect.width
  const available = Boolean(result.src) && result.output.delivery_status !== "expired"
  const unavailableReason = result.output.delivery_status === "expired" ? "云端文件已过期" : "视频暂不可用"
  const canDownload = available && Boolean(result.output.download_url || result.output.cloud_url)

  useEffect(() => {
    const video = videoRef.current
    const syncMetadata = () => {
      if (!video || video.readyState < 1) return
      if (video.videoWidth > 0 && video.videoHeight > 0) setMeasured({ width: video.videoWidth, height: video.videoHeight })
      setDuration(Number.isFinite(video.duration) ? video.duration : 0)
    }
    // A cached video can finish loading metadata before React attaches its
    // handlers, which would leave the timeline stuck at 00:00.
    syncMetadata()
    video?.addEventListener("durationchange", syncMetadata)
    return () => { video?.removeEventListener("durationchange", syncMetadata); video?.pause() }
  }, [result.src])

  useEffect(() => {
    if (!menuOpen) return
    // Focusing a portal before it is positioned can scroll the entire feed.
    const frame = requestAnimationFrame(() => document.getElementById(menuId)?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(frame)
  }, [menuId, menuOpen])

  useEffect(() => {
    const media = mediaRef.current
    const enterPreview = () => {
      setSeekEngaged(false)
      const video = videoRef.current
      if (video?.paused) {
        // Hover previews are best-effort; browsers can block audible autoplay.
        void video.play().catch(() => {})
      }
    }
    const leavePreview = () => {
      videoRef.current?.pause()
      setSeekEngaged(false)
    }
    const finishSeek = () => {
      if (!seekPointerDownRef.current) return
      seekPointerDownRef.current = false
      if (!seekAreaRef.current?.matches(":hover")) setSeekEngaged(false)
    }
    const cancelSeek = () => {
      seekPointerDownRef.current = false
      setSeekEngaged(false)
    }
    // Native mouse events follow the visible container boundary, including when
    // the pointer enters a Dropdown portal rendered outside that boundary.
    media?.addEventListener("mouseenter", enterPreview)
    media?.addEventListener("mouseleave", leavePreview)
    if (media?.matches(":hover")) enterPreview()
    window.addEventListener("pointerup", finishSeek)
    window.addEventListener("pointercancel", cancelSeek)
    return () => {
      media?.removeEventListener("mouseenter", enterPreview)
      media?.removeEventListener("mouseleave", leavePreview)
      window.removeEventListener("pointerup", finishSeek)
      window.removeEventListener("pointercancel", cancelSeek)
    }
  }, [])

  const togglePlayback = async () => {
    const video = videoRef.current
    if (!video || !available) return
    if (!video.paused) { video.pause(); return }
    try { await video.play() }
    catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return
      void messageApi.error("视频暂时无法播放，请重新加载或下载查看")
    }
  }

  const fullscreen = async () => {
    try {
      if (document.fullscreenElement === mediaRef.current) await document.exitFullscreen()
      else if (mediaRef.current?.requestFullscreen) await mediaRef.current.requestFullscreen()
      else actions.onPreview?.(result)
    } catch { actions.onPreview?.(result) }
  }

  const source = result.jobId
    ? { jobId: result.jobId, generationItemId: result.generationItemId, outputIndex: result.outputIndex, kind: "video" as const }
    : null
  const registry = source ? actions.resolveActions?.(source) ?? [] : []
  const bar = mediaActionBar(registry)
  // 运行参数与删除不依赖视频本身能不能播放，其余动作在没有结果时按住。
  const alwaysEnabled = (item: MediaActionItem) => item.id === "params" || item.id === "remove"
  const moreItems = [
    ...(actions.onEnhance ? [{ key: "enhance", label: actions.enhancing ? "智能高清处理中" : "SeedVR2 2× 智能高清", icon: <Sparkles size={16} />, disabled: !available || actions.enhancing }] : []),
    ...mediaActionMenu(registry).map((item) => ({
      key: item.id, label: item.label, danger: item.danger, disabled: !alwaysEnabled(item) && !available,
      icon: <ActionIcon icon={item.icon} size={16} />,
    })),
  ]

  return <article className={`studio-video-result-card ${portrait ? "is-portrait" : "is-landscape"} ${menuOpen ? "is-menu-open" : ""}`} style={mediaAspectVars(aspect) as CSSProperties}>
    {messageHolder}
    <div ref={mediaRef} className="studio-video-result-media">
      {available ? <video ref={videoRef} className="studio-video-player" src={result.src}
        poster={cloudThumbnailSrc("video", result.output.cloud_url) ?? undefined}
        muted={muted} playsInline preload="metadata" tabIndex={0} aria-label={`${result.output.label}，空格播放或暂停`}
        onClick={() => void togglePlayback()}
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") { event.preventDefault(); void togglePlayback() }
        }}
        onLoadedMetadata={(event) => {
          const video = event.currentTarget
          if (video.videoWidth > 0 && video.videoHeight > 0) setMeasured({ width: video.videoWidth, height: video.videoHeight })
          setDuration(Number.isFinite(video.duration) ? video.duration : 0)
        }}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onPlay={(event) => {
          document.querySelectorAll<HTMLVideoElement>(".studio-video-player").forEach((other) => { if (other !== event.currentTarget) other.pause() })
          setPlaying(true)
        }}
        onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
        onVolumeChange={(event) => setMuted(event.currentTarget.muted || event.currentTarget.volume === 0)}
        onError={() => setPlayError(true)} onLoadedData={() => setPlayError(false)}
      /> : <div className="studio-video-unavailable"><HardDrive size={22} /><span>{unavailableReason}</span></div>}
      {playError ? <div className="studio-video-unavailable studio-video-play-error"><span>视频暂时无法播放</span><Button size="small" onClick={() => { setPlayError(false); videoRef.current?.load() }}>重新加载</Button></div> : null}
      <div className="studio-video-hover-top">
        {canDownload ? <Tooltip title="下载当前视频"><Button type="text" className="studio-video-tool" icon={<Download size={17} />} aria-label="下载当前视频" onClick={() => actions.onDownload(result)} /></Tooltip> : null}
        {moreItems.length ? <Dropdown trigger={["click"]} placement="bottomLeft" open={menuOpen}
          onOpenChange={setMenuOpen} classNames={{ root: "studio-video-more-popup" }}
          popupRender={(menu) => <div onKeyDownCapture={(event) => {
            if (event.key === "Escape") {
              event.preventDefault()
              event.stopPropagation()
              setMenuOpen(false)
              requestAnimationFrame(() => moreRef.current?.focus({ preventScroll: true }))
            }
          }}>{menu}</div>}
          menu={{ id: menuId, items: moreItems, onClick: ({ key }) => {
            setMenuOpen(false)
            if (key === "enhance") { actions.onEnhance?.(result); return }
            const item = registry.find((entry) => entry.id === key)
            if (item) actions.onAction?.(item, result)
          } }}>
          <Button ref={moreRef} type="text" className="studio-video-tool" icon={<MoreHorizontal size={19} />} aria-label="更多视频操作" aria-expanded={menuOpen} />
        </Dropdown> : null}
        {available ? <Tooltip title="全屏预览"><Button type="text" className="studio-video-tool" icon={<Maximize2 size={17} />} aria-label="全屏预览" onClick={() => void fullscreen()} /></Tooltip> : null}
      </div>
      {available ? <div className="studio-video-hover-bottom">
        <div className="studio-video-bottom-row">
          <div className="studio-video-playback">
            <Tooltip title={playing ? "暂停" : "播放"}><Button type="text" className="studio-video-play-button" icon={playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />} aria-label={playing ? "暂停视频" : "播放视频"} onClick={() => void togglePlayback()} /></Tooltip>
            <span className="studio-video-time">{formatVideoTime(currentTime)} / {formatVideoTime(duration)}</span>
            <Tooltip title={muted ? "开启声音" : "静音"}><Button type="text" className="studio-video-volume-button" icon={muted ? <VolumeX size={17} /> : <Volume2 size={17} />} aria-label={muted ? "开启声音" : "静音"} onClick={() => { if (videoRef.current) videoRef.current.muted = !muted }} /></Tooltip>
          </div>
          {bar.length ? <div className="studio-video-quick-tools">
            {bar.map((item) => <Tooltip key={item.id} title={item.label}>
              <Button type="text" className="studio-video-quick-button" icon={<ActionIcon icon={item.icon} size={17} />} aria-label={item.label} onClick={() => actions.onAction?.(item, result)} />
            </Tooltip>)}
          </div> : null}
        </div>
        <div ref={seekAreaRef} className={`studio-video-seek-area ${seekEngaged ? "is-seek-engaged" : ""}`}
          onPointerDownCapture={(event) => {
            if (event.button !== 0 || !duration) return
            seekPointerDownRef.current = true
            setSeekEngaged(true)
          }}
          onMouseLeave={() => { if (!seekPointerDownRef.current) setSeekEngaged(false) }}
          onFocusCapture={(event) => { if (event.target.matches(":focus-visible")) setSeekEngaged(true) }}
          onBlurCapture={() => {
            requestAnimationFrame(() => {
              if (!seekAreaRef.current?.contains(document.activeElement)) setSeekEngaged(false)
            })
          }}>
          <ConfigProvider theme={videoSeekTheme}>
            <Slider min={0} max={duration || 1} step={0.01} value={currentTime} disabled={!duration}
              ariaLabelForHandle="视频播放进度" tooltip={{ open: seekEngaged ? undefined : false, formatter: (value) => formatVideoTime(value ?? 0) }}
              onChange={(value) => { if (videoRef.current) { videoRef.current.currentTime = value; setCurrentTime(value) } }}
              className="studio-video-seek" />
          </ConfigProvider>
        </div>
      </div> : null}
    </div>
  </article>
}

export default function VideoStudioModule({ results, roundCount, embedded = false, showHeading = true, aspectRatio, upscaleStage, ...actions }: ResultActions & {
  results: VideoResult[]; roundCount: number; embedded?: boolean; showHeading?: boolean
  aspectRatio?: string; upscaleStage?: string
}) {
  const videos = results.filter((result) => result.output.kind === "video")
  return <section className={`studio-video-results ${embedded ? "" : "is-standalone"}`} aria-label="视频生成结果">
    {showHeading ? <div className="studio-video-results-heading"><h2>视频结果</h2><p>共 {roundCount} 轮</p></div> : null}
    {upscaleStage ? <p className="studio-video-upscale-stage">{upscaleStage}</p> : null}
    <div className="studio-video-result-grid is-single">{videos.map((result) => <VideoResultCard key={videoResultKey(result)} result={result} aspectRatio={aspectRatio} {...actions} />)}</div>
  </section>
}
