import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { Button, Empty, Slider, Switch, Tooltip } from "antd"
import { Maximize2, Pause, Play, Volume2, VolumeX } from "lucide-react"
import type { Director2Beat } from "../api"
import { segmentAt, workshopSegments, workshopTime } from "../workshop-editor"

export default function WorkshopPlayer({ beats, selectedId, onSelect, onExpand, active = true }: {
  beats: Director2Beat[]; selectedId: string; onSelect: (id: string) => void; onExpand?: () => void; active?: boolean
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [measured, setMeasured] = useState<Record<string, number>>({})
  const segments = useMemo(() => workshopSegments(beats, measured), [beats, measured])
  const segment = segments.find(s => s.id === selectedId) || segments[0]
  const [localTime, setLocalTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [loopCurrent, setLoopCurrent] = useState(false)
  const [failed, setFailed] = useState(false)
  const [aspect, setAspect] = useState(16 / 9)
  const pending = useRef<{ id: string; time: number; play: boolean } | null>(null)
  const retryTimer = useRef<number | null>(null)
  const retried = useRef(false)
  const cancelRetry = () => { if (retryTimer.current !== null) { window.clearTimeout(retryTimer.current); retryTimer.current = null } }
  // CDN 首次回源或弹窗打开时多段并发探测偶发单请求失败，先静默重拉一次，仍失败才提示手动重新加载。
  const handleMediaError = (media: HTMLVideoElement) => {
    setPlaying(false)
    if (retried.current) { setFailed(true); return }
    retried.current = true
    cancelRetry()
    retryTimer.current = window.setTimeout(() => { retryTimer.current = null; media.load() }, 800)
  }
  useEffect(() => () => cancelRetry(), [])
  const total = segments.at(-1)?.end || 0
  const currentTime = (segment?.start || 0) + localTime
  const recordDuration = (src: string, duration: number) => {
    if (Number.isFinite(duration) && duration > 0) setMeasured(previous => previous[src] === duration ? previous : { ...previous, [src]: duration })
  }
  const seek = (time: number, play = playing) => {
    const target = segmentAt(segments, time)
    if (!target) return
    pending.current = { id: target.segment.id, time: target.offset, play }
    if (target.segment.id !== selectedId) onSelect(target.segment.id)
    else if (videoRef.current?.readyState) {
      videoRef.current.currentTime = Math.min(target.offset, videoRef.current.duration || target.offset)
      setLocalTime(target.offset)
      if (play) void videoRef.current.play().catch(() => setPlaying(false))
      pending.current = null
    }
  }
  useEffect(() => {
    setLocalTime(0); setFailed(false); retried.current = false; cancelRetry()
    const media = videoRef.current
    if (!media) return
    const requested = pending.current
    if (!requested || requested.id !== selectedId) { pending.current = null; setPlaying(false) }
  }, [selectedId, segment?.src])
  useEffect(() => { if (!active) videoRef.current?.pause() }, [active])
  const togglePlayback = () => {
    const media = videoRef.current
    if (!media) return
    if (media.paused) void media.play().catch(() => setFailed(true)); else media.pause()
  }
  const loaded = (media: HTMLVideoElement) => {
    retried.current = false
    recordDuration(segment.src, media.duration)
    if (media.videoWidth && media.videoHeight) setAspect(media.videoWidth / media.videoHeight)
    const requested = pending.current
    if (requested?.id === selectedId) {
      media.currentTime = Math.min(requested.time, media.duration || requested.time)
      setLocalTime(media.currentTime)
      pending.current = null
      if (requested.play && active) void media.play().catch(() => setPlaying(false))
    }
  }
  return <div className="ws-player" aria-label="分段视频播放器">
    <div className="ws-player-stage" style={{ "--ws-video-aspect": aspect } as CSSProperties}>
      {segment?.src && !failed ? <>
        <video key={segment.src} ref={videoRef} src={segment.src} playsInline preload="metadata" muted={muted} onLoadedMetadata={event => loaded(event.currentTarget)} onTimeUpdate={event => setLocalTime(event.currentTarget.currentTime)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onError={event => handleMediaError(event.currentTarget)} onEnded={() => {
          if (loopCurrent) { seek(segment.start, true); return }
          const next = segments[segment.index + 1]
          if (next) seek(next.start, true); else setPlaying(false)
        }}/>
        {!playing && <Button type="text" className="ws-player-play-overlay" icon={<Play size={24} fill="currentColor"/>} aria-label="播放当前片段" onClick={togglePlayback}/>}
        <div className="ws-player-time">{workshopTime(currentTime)} / {workshopTime(total)}</div>
        {onExpand && <Tooltip title="放大预览"><Button type="text" className="ws-player-expand" size="small" icon={<Maximize2 size={14}/>} aria-label="放大视频预览" onClick={onExpand}/></Tooltip>}
      </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={failed ? "视频加载失败" : "当前片段尚未出片"}>{failed && <Button size="small" onClick={() => { retried.current = false; setFailed(false) }}>重新加载</Button>}</Empty>}
    </div>
    <div className="ws-player-controls">
      <Button type="text" size="small" icon={playing ? <Pause size={14} fill="currentColor"/> : <Play size={14} fill="currentColor"/>} disabled={!segment?.src || failed} onClick={togglePlayback} aria-label={playing ? "暂停视频" : "播放视频"}/>
      <div className="ws-segment-slider">
        <div className="ws-segment-track" aria-hidden="true">{segments.map(s => <span key={s.id} className={s.id === selectedId ? "is-selected" : ""} style={{ width: `${total ? s.duration / total * 100 : 0}%` }}/>)}</div>
        <Slider min={0} max={total || 1} step={0.01} value={Math.min(currentTime, total)} onChange={value => seek(value)} tooltip={{ formatter: value => { const target = segmentAt(segments, value || 0); return target ? `片段 ${String(target.segment.index + 1).padStart(2, "0")} · ${workshopTime(value || 0)}` : "" } }} ariaLabelForHandle="整集分段进度，拖动同步分镜"/>
      </div>
      <Tooltip title={loopCurrent ? "关闭当前片段循环" : "循环当前片段"}><Switch size="small" checked={loopCurrent} onChange={setLoopCurrent} aria-label="循环当前片段"/></Tooltip>
      <Button type="text" size="small" icon={muted ? <VolumeX size={15}/> : <Volume2 size={15}/>} onClick={() => setMuted(!muted)} aria-label={muted ? "开启声音" : "静音"}/>
    </div>
    <div className="ws-segment-buttons" aria-label="按片段定位播放">{segments.map(s => <Tooltip key={s.id} title={`片段 ${String(s.index + 1).padStart(2, "0")} · ${workshopTime(s.start)}–${workshopTime(s.end)}${s.src ? "" : " · 未出片"}`}><Button type="text" className={s.id === selectedId ? "is-selected" : ""} style={{ flexGrow: s.duration }} aria-label={`定位片段${s.index + 1}`} aria-pressed={s.id === selectedId} onClick={() => seek(s.start)}>{String(s.index + 1).padStart(2, "0")}</Button></Tooltip>)}</div>
    <div className="ws-duration-probes" aria-hidden="true">{[...new Set(segments.map(s => s.src).filter(Boolean))].map(src => <video key={src} src={src} preload="metadata" muted onLoadedMetadata={event => recordDuration(src, event.currentTarget.duration)}/>)}</div>
  </div>
}
