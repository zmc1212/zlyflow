import { Button, Dropdown, Empty, Modal, Progress, Slider, Spin, Tag, Tooltip, message } from "antd"
import { Download, FileText, ListMusic, MoreHorizontal, Pause, Play, SkipBack, SkipForward, Trash2, Volume2, VolumeX, X } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { MusicJob, deleteMusicJob, formatMusicDuration } from "./api"
import { musicArtworkUrl, musicDate, musicStyleTags, type MusicView } from "./music-library"

const STATUS_TAGS: Record<MusicJob["status"], { color: string; label: string }> = {
  queued: { color: "default", label: "排队中" }, running: { color: "processing", label: "生成中" },
  succeeded: { color: "success", label: "已完成" }, failed: { color: "error", label: "生成失败" },
}

export type MusicPlayerState = {
  playingId: string | null
  progress: { id: string; current: number; total: number } | null
}

export function MusicArtwork({ job, className = "", decorative = false }: { job: MusicJob; className?: string; decorative?: boolean }) {
  return <img className={className} src={musicArtworkUrl(job)} alt={decorative ? "" : `${job.title || "未命名歌曲"} 封面`} onError={(event) => {
    if (!event.currentTarget.src.endsWith("/music-art/daylight.webp")) event.currentTarget.src = "/music-art/daylight.webp"
  }} />
}

export function MusicEqualizer() {
  return <span className="studio-music-equalizer" aria-hidden="true"><i /><i /><i /><i /></span>
}

/** 曲库数据始终来自工作台任务；筛选与视图不改变播放器的当前歌曲。 */
export default function MusicJobList({ jobs, csrfToken, loading, player, selectedId, view, emptyText, onToggle, onSelect, onLyrics, onRemoved }: {
  jobs: MusicJob[]
  csrfToken: string
  loading?: boolean
  player: MusicPlayerState
  selectedId?: string
  view: MusicView
  emptyText: string
  onToggle: (job: MusicJob) => void
  onSelect: (job: MusicJob) => void
  onLyrics: (job: MusicJob) => void
  onRemoved: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const [modal, modalContext] = Modal.useModal()
  const remove = (job: MusicJob) => {
    modal.confirm({
      title: `删除「${job.title || "未命名歌曲"}」？`, content: "这条音乐任务及其工作台记录将被删除。",
      okText: "删除", cancelText: "保留", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteMusicJob(csrfToken, job.id)
          onRemoved(job.id)
          await queryClient.invalidateQueries({ queryKey: ["music-jobs"] })
          message.success("已删除歌曲")
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除失败")
          throw error
        }
      },
    })
  }

  if (loading) return <div className="studio-music-list-loading"><Spin tip="正在加载歌曲"><div /></Spin></div>
  if (!jobs.length) return <div className="studio-music-list-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} /></div>

  return <>
    {modalContext}
    <ul className={`studio-music-grid ${view === "list" ? "is-list" : ""}`} aria-label="歌曲列表">
      {jobs.map((job) => {
        const tag = STATUS_TAGS[job.status] ?? STATUS_TAGS.queued
        const title = job.title || "未命名歌曲"
        const playable = job.status === "succeeded" && Boolean(job.result_url)
        const isPlaying = player.playingId === job.id
        const duration = player.progress?.id === job.id && player.progress.total ? player.progress.total : job.duration_seconds
        return <li key={job.id} className={`studio-music-card ${isPlaying ? "is-playing" : ""} ${selectedId === job.id ? "is-selected" : ""}`}>
          <div className={`studio-music-card-cover-box ${job.status === "running" ? "is-running" : ""}`}>
            <MusicArtwork job={job} className="studio-music-card-cover" />
            <Button type="text" className="studio-music-cover-hit" onClick={() => playable ? onToggle(job) : onSelect(job)} aria-label={playable ? `${isPlaying ? "暂停" : "播放"} ${title}` : `查看 ${title}`}>
              {playable && <span className="studio-music-card-play">{isPlaying ? <Pause size={21} fill="currentColor" /> : <Play size={19} fill="currentColor" />}</span>}
            </Button>
            <Dropdown trigger={["click"]} placement="bottomRight" menu={{
              items: [
                { key: "lyrics", icon: <FileText size={15} />, label: "查看歌曲详情" },
                ...(job.result_url ? [{ key: "download", icon: <Download size={15} />, label: <a href={job.result_url} target="_blank" rel="noreferrer" download>下载 {job.result_format?.toUpperCase() || "音频"}</a> }] : []),
                ...(job.status === "succeeded" || job.status === "failed" ? [{ type: "divider" as const }, { key: "delete", danger: true, icon: <Trash2 size={15} />, label: "删除歌曲" }] : []),
              ],
              onClick: ({ key }) => { if (key === "lyrics") onLyrics(job); else if (key === "delete") remove(job) },
            }}>
              <Button type="text" className="studio-music-card-more" icon={<MoreHorizontal size={20} />} aria-label={`${title}的更多操作`} />
            </Dropdown>
            {isPlaying ? <span className="studio-music-playing-badge"><MusicEqualizer />正在播放</span>
              : job.status !== "succeeded" ? <Tag color={tag.color} className="studio-music-cover-status">{tag.label}</Tag> : null}
            {duration && !isPlaying ? <span className="studio-music-card-duration">{formatMusicDuration(duration)}</span> : null}
          </div>
          <div className="studio-music-card-info">
            <Button type="text" className="studio-music-card-title" title={title} onClick={() => onSelect(job)}>{title}</Button>
            <p className="studio-music-card-style" title={job.style}>{musicStyleTags(job).join(" · ")}</p>
            <p className="studio-music-card-sub">{[musicDate(job.created_at), job.result_format?.toUpperCase()].filter(Boolean).join(" · ")}</p>
            {job.status === "running" && <Progress className="studio-music-card-progress" percent={Math.max(0, Math.min(100, job.progress || 0))} size="small" strokeColor="var(--studio-music-accent)" />}
            {job.status === "failed" && <Tooltip title={job.error_message}><p className="studio-music-card-error">{job.error_message || "生成失败，请重新创作"}</p></Tooltip>}
          </div>
        </li>
      })}
    </ul>
  </>
}

export function MusicPlayerBar({ job, player, volume, previous, next, lyricsOpen, onLyrics, onToggle, onSeek, onVolume, onMute, onPrevious, onNext, onClose }: {
  job: MusicJob
  player: MusicPlayerState
  volume: number
  previous: boolean
  next: boolean
  lyricsOpen: boolean
  onLyrics: () => void
  onToggle: (job: MusicJob) => void
  onSeek: (job: MusicJob, value: number) => void
  onVolume: (value: number) => void
  onMute: () => void
  onPrevious: () => void
  onNext: () => void
  onClose: () => void
}) {
  const isPlaying = player.playingId === job.id
  const total = player.progress?.id === job.id && player.progress.total ? player.progress.total : job.duration_seconds || 0
  const current = player.progress?.id === job.id ? player.progress.current : 0
  const clock = (value: number) => formatMusicDuration(value) || "0:00"
  return <div className={`studio-music-player-bar ${isPlaying ? "is-playing" : ""}`} role="region" aria-label="音乐播放条">
    <div className="studio-music-player-song">
      <MusicArtwork job={job} className="studio-music-player-cover" decorative />
      <div className="studio-music-player-info">
        <p className="studio-music-player-title">{job.title || "未命名歌曲"}</p>
        <p className="studio-music-player-sub">{musicStyleTags(job).slice(0, 2).join(" · ")}</p>
      </div>
      <MusicEqualizer />
    </div>
    <div className="studio-music-player-center">
      <div className="studio-music-player-controls">
        <Button type="text" icon={<SkipBack size={19} fill="currentColor" />} disabled={!previous} onClick={onPrevious} aria-label="上一首" />
        <Button type="primary" shape="circle" className="studio-music-player-toggle" icon={isPlaying ? <Pause size={21} fill="currentColor" /> : <Play size={21} fill="currentColor" />} onClick={() => onToggle(job)} aria-label={isPlaying ? "暂停" : "播放"} />
        <Button type="text" icon={<SkipForward size={19} fill="currentColor" />} disabled={!next} onClick={onNext} aria-label="下一首" />
      </div>
      <div className="studio-music-player-timeline">
        <span className="studio-music-player-time">{clock(current)}</span>
        <Slider className="studio-music-seek" min={0} max={Math.max(1, total)} step={0.1} value={Math.min(current, total || 0)} disabled={!total} onChange={(value) => onSeek(job, value)} tooltip={{ formatter: (value) => clock(Number(value || 0)) }} ariaLabelForHandle="播放进度" ariaValueTextFormatterForHandle={clock} />
        <span className="studio-music-player-time">{clock(total)}</span>
      </div>
    </div>
    <div className="studio-music-player-actions">
      <Button type="text" icon={volume === 0 ? <VolumeX size={19} /> : <Volume2 size={19} />} onClick={onMute} aria-label={volume === 0 ? "取消静音" : "静音"} />
      <Slider className="studio-music-volume" min={0} max={1} step={0.01} value={volume} onChange={onVolume} tooltip={{ formatter: (value) => `${Math.round(Number(value || 0) * 100)}%` }} ariaLabelForHandle="音量" ariaValueTextFormatterForHandle={(value) => `${Math.round(value * 100)}%`} />
      <span className="studio-music-player-divider" />
      <Button id="music-player-lyrics-toggle" type="text" className="studio-music-player-lyrics-toggle" icon={<ListMusic size={18} />} onClick={onLyrics} aria-expanded={lyricsOpen} aria-controls={lyricsOpen ? "music-live-lyrics" : undefined}>歌词</Button>
      <Tooltip title="下载音频"><Button type="text" icon={<Download size={19} />} href={job.result_url || undefined} target="_blank" rel="noreferrer" download aria-label="下载当前歌曲" /></Tooltip>
      <Tooltip title="关闭播放条"><Button type="text" icon={<X size={20} />} onClick={onClose} aria-label="关闭播放条" /></Tooltip>
    </div>
  </div>
}
