import { Button, Dropdown, Empty, Spin } from "antd"
import { EyeOff, FileText, MoreHorizontal, Pause, Play, Sparkles } from "lucide-react"
import { formatMusicDuration, type FeaturedMusic } from "./api"
import { MusicArtwork, MusicEqualizer, type MusicPlayerState } from "./MusicJobList"
import { featuredMusicAsJob, musicDate, musicStyleTags } from "./music-library"

/** 精选音乐：管理员发布后全员可见的只读展示位；播放复用音乐页播放条。 */
export default function FeaturedMusicGrid({ songs, loading, player, isAdmin, onToggle, onLyrics, onUnpublish }: {
  songs: FeaturedMusic[]
  loading?: boolean
  player: MusicPlayerState
  isAdmin: boolean
  onToggle: (song: FeaturedMusic) => void
  onLyrics: (song: FeaturedMusic) => void
  onUnpublish: (song: FeaturedMusic) => void
}) {
  if (loading) return <div className="studio-music-list-loading"><Spin description="正在加载精选音乐"><div /></Spin></div>
  if (!songs.length) return <div className="studio-music-list-empty">
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={isAdmin ? "还没有精选音乐，在「我的歌曲」的卡片菜单里发布" : "管理员还没有发布精选音乐"} />
  </div>

  return <ul className="studio-music-grid studio-featured-music-grid" aria-label="精选音乐列表">
    {songs.map((song) => {
      const job = featuredMusicAsJob(song)
      const isPlaying = player.playingId === job.id
      const title = song.title || "未命名歌曲"
      const duration = player.progress?.id === job.id && player.progress.total ? player.progress.total : song.duration_seconds
      return <li key={song.id} className={`studio-music-card studio-featured-music-card ${isPlaying ? "is-playing" : ""}`}>
        <div className="studio-music-card-cover-box">
          <MusicArtwork job={job} className="studio-music-card-cover" />
          <Button type="text" className="studio-music-cover-hit" onClick={() => onToggle(song)} aria-label={`${isPlaying ? "暂停" : "播放"} ${title}`}>
            <span className="studio-music-card-play">{isPlaying ? <Pause size={21} fill="currentColor" /> : <Play size={19} fill="currentColor" />}</span>
          </Button>
          <span className="studio-featured-music-badge"><Sparkles size={12} />精选</span>
          {isAdmin && <Dropdown trigger={["click"]} placement="bottomRight" menu={{
            items: [
              { key: "lyrics", icon: <FileText size={15} />, label: "查看歌曲详情" },
              { type: "divider" as const },
              { key: "unpublish", danger: true, icon: <EyeOff size={15} />, label: "取消精选" },
            ],
            onClick: ({ key }) => { if (key === "lyrics") onLyrics(song); else if (key === "unpublish") onUnpublish(song) },
          }}>
            <Button type="text" className="studio-music-card-more" icon={<MoreHorizontal size={20} />} aria-label={`${title}的精选操作`} />
          </Dropdown>}
          {isPlaying ? <span className="studio-music-playing-badge"><MusicEqualizer />正在播放</span>
            : duration ? <span className="studio-music-card-duration">{formatMusicDuration(duration)}</span> : null}
        </div>
        <div className="studio-music-card-info">
          <Button type="text" className="studio-music-card-title" title={title} onClick={() => onLyrics(song)}>{title}</Button>
          <p className="studio-music-card-style" title={song.style}>{musicStyleTags(song).join(" · ")}</p>
          <p className="studio-music-card-sub">{song.summary || ["管理员精选", musicDate(song.published_at), song.result_format?.toUpperCase()].filter(Boolean).join(" · ")}</p>
        </div>
      </li>
    })}
  </ul>
}
