import { Button, ConfigProvider, Dropdown, Slider, Tooltip, message } from "antd"
import { ChevronDown, Clapperboard, Download, FileSliders, Frame, HardDrive, LoaderCircle, Maximize2, MoreHorizontal, Pause, Play, Trash2, Volume2, VolumeX, WandSparkles } from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react"
import { mediaAspectVars, parseMediaAspect, type MediaAspectSize } from "../lib/utils"
import { cloudThumbnailSrc } from "../media-thumbnails"
import { isUpscaleOutput } from "../video-upscale"
import { formatVideoTime, videoResultKey, type VideoResult } from "./video-result-model"
import "./video-results.css"

export type { VideoResult } from "./video-result-model"

export type VideoUpscaleEngine = {
  id: "rtx" | "seedvr2"; label: string; hint?: string; disabled?: boolean
}

export type VideoUpscaleAction = {
  disabled: boolean; pending?: boolean; hint?: string; engines?: VideoUpscaleEngine[]
  onClick: (engine?: "rtx" | "seedvr2") => void
}

type ResultActions = {
  onDownload: (result: VideoResult) => void
  onPreview?: (result: VideoResult) => void
  onAddToCanvas?: (result: VideoResult) => void
  onExportJianying?: (result: VideoResult) => void
  onShowRuntime?: () => void
  onDeleteTask?: () => void
}

const videoSeekTheme = {
  components: {
    Slider: { handleSize: 6, handleSizeHover: 6, handleActiveOutlineColor: "transparent" },
  },
}

function VideoResultCard({ result, aspectRatio, upscale, ...actions }: ResultActions & {
  result: VideoResult; aspectRatio?: string; upscale?: VideoUpscaleAction
}) {
  const hint = useMemo(() => parseMediaAspect(aspectRatio), [aspectRatio])
  const [measured, setMeasured] = useState<MediaAspectSize>()
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [upscaleMenuOpen, setUpscaleMenuOpen] = useState(false)
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

  const moreItems = [
    ...(actions.onAddToCanvas ? [{ key: "canvas", label: "加入画布", icon: <Frame size={16} />, disabled: !available }] : []),
    ...(actions.onExportJianying ? [{ key: "jianying", label: "导出剪映", icon: <Clapperboard size={16} />, disabled: !available }] : []),
    ...(actions.onShowRuntime ? [{ key: "runtime", label: "查看运行参数", icon: <FileSliders size={16} /> }] : []),
    ...(actions.onDeleteTask ? [{ type: "divider" as const }, { key: "delete", label: "删除任务", icon: <Trash2 size={16} />, danger: true }] : []),
  ]

  return <article className={`studio-video-result-card ${portrait ? "is-portrait" : "is-landscape"} ${menuOpen || upscaleMenuOpen ? "is-menu-open" : ""}`} style={mediaAspectVars(aspect) as CSSProperties}>
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
            if (key === "canvas") actions.onAddToCanvas?.(result)
            if (key === "jianying") actions.onExportJianying?.(result)
            if (key === "runtime") actions.onShowRuntime?.()
            if (key === "delete") actions.onDeleteTask?.()
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
          </div>
          <div className="studio-video-quick-tools">
            {upscale ? <Tooltip title={upscale.hint || "2× 超分"}><span className="studio-video-quick-item">
              {upscale.engines?.length ? <Dropdown
                trigger={["click"]}
                disabled={upscale.disabled || upscale.pending}
                classNames={{ root: "studio-video-upscale-popup" }}
                open={upscaleMenuOpen}
                onOpenChange={setUpscaleMenuOpen}
                menu={{
                  items: upscale.engines.map((engine) => ({
                    key: engine.id,
                    disabled: engine.disabled,
                    label: <span className="studio-video-upscale-option">
                      <span>{engine.label}</span>
                      {engine.hint ? <em className="studio-video-upscale-hint">{engine.hint}</em> : null}
                    </span>,
                  })),
                  onClick: ({ key }) => {
                    setUpscaleMenuOpen(false)
                    upscale.onClick(key as "rtx" | "seedvr2")
                  },
                }}
              >
                <Button type="text" disabled={upscale.disabled || upscale.pending} aria-label="超分当前任务" className="studio-video-quick-button">
                  {upscale.pending ? <LoaderCircle size={16} className="animate-spin" /> : <WandSparkles size={16} />}<span>2× 超分</span><ChevronDown size={13} />
                </Button>
              </Dropdown> : <Button type="text" disabled={upscale.disabled || upscale.pending} onClick={() => upscale.onClick()} aria-label="2× 超分当前任务" className="studio-video-quick-button">
                {upscale.pending ? <LoaderCircle size={16} className="animate-spin" /> : <WandSparkles size={16} />}<span>2× 超分</span>
              </Button>}
            </span></Tooltip> : null}
            {actions.onAddToCanvas ? <Tooltip title="将当前视频加入画布"><Button type="text" onClick={() => actions.onAddToCanvas?.(result)} aria-label="将当前视频加入画布" className="studio-video-quick-button"><Frame size={16} /><span>加入画布</span></Button></Tooltip> : null}
            {actions.onExportJianying ? <Tooltip title="将当前视频导出为剪映草稿"><Button type="text" onClick={() => actions.onExportJianying?.(result)} aria-label="导出当前视频到剪映" className="studio-video-quick-button"><Clapperboard size={16} /><span>导出剪映</span></Button></Tooltip> : null}
            <Tooltip title={muted ? "开启声音" : "静音"}><Button type="text" className="studio-video-volume-button" icon={muted ? <VolumeX size={17} /> : <Volume2 size={17} />} aria-label={muted ? "开启声音" : "静音"} onClick={() => { if (videoRef.current) videoRef.current.muted = !muted }} /></Tooltip>
          </div>
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

export default function VideoStudioModule({ results, roundCount, embedded = false, showHeading = true, aspectRatio, upscale, upscaleStage, ...actions }: ResultActions & {
  results: VideoResult[]; roundCount: number; embedded?: boolean; showHeading?: boolean
  aspectRatio?: string; upscale?: VideoUpscaleAction; upscaleStage?: string
}) {
  const videos = results.filter((result) => result.output.kind === "video")
  return <section className={`studio-video-results ${embedded ? "" : "is-standalone"}`} aria-label="视频生成结果">
    {showHeading ? <div className="studio-video-results-heading"><h2>视频结果</h2><p>共 {roundCount} 轮</p></div> : null}
    {upscaleStage ? <p className="studio-video-upscale-stage">{upscaleStage}</p> : null}
    <div className="studio-video-result-grid is-single">{videos.map((result) => <VideoResultCard key={videoResultKey(result)} result={result} aspectRatio={aspectRatio} upscale={isUpscaleOutput(result.output) ? undefined : upscale} {...actions} />)}</div>
  </section>
}
