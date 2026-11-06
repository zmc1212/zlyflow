// 精选作品成片预览：点击精选卡片直接弹出，全屏播放成片；
// 右下角「查看创作过程」进入只读画布，流程参考即梦精选作品页。
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Button, Skeleton } from "antd"
import { ArrowLeft, Clapperboard, GitBranch, ScrollText, X } from "lucide-react"
import { getFeaturedWork } from "./api"
import { director2FeaturedPath, director2FeaturedProcessPath } from "./paths"

export default function FeaturedWorkPreview({ featuredId, onClose }: { featuredId: string; onClose: () => void }) {
  const navigate = useNavigate()
  const [episodeIndex, setEpisodeIndex] = useState(0)
  const query = useQuery({
    queryKey: ["director-featured-work", featuredId],
    queryFn: () => getFeaturedWork(featuredId),
    retry: false,
  })
  const work = query.data
  const episodes = useMemo(
    () => work?.snapshot.episodes.filter(item => item.episode_video_url) ?? [],
    [work],
  )
  const current = episodes.length ? episodes[Math.min(episodeIndex, episodes.length - 1)] : null

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose() }
    window.addEventListener("keydown", onKey)
    document.body.classList.add("featured-preview-lock")
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.classList.remove("featured-preview-lock")
    }
  }, [onClose])

  return <div className="featured-preview" role="dialog" aria-modal="true" aria-label={`成片预览：${work?.title ?? ""}`}>
    <header className="featured-preview-top">
      <Button type="text" className="featured-preview-icon" aria-label="返回精选作品" icon={<ArrowLeft size={18} />} onClick={onClose} />
      <Button type="text" className="featured-preview-icon featured-preview-close" aria-label="关闭预览" icon={<X size={18} />} onClick={onClose} />
    </header>

    <div className="featured-preview-stage">
      {query.isLoading ? <div className="featured-preview-loading"><Skeleton active paragraph={{ rows: 4 }} title={{ width: "30%" }} /></div>
        : query.isError || !work ? <div className="featured-preview-empty"><Clapperboard size={28} /><p>作品可能已下架，或当前登录状态已失效。</p></div>
        : current
          ? <video
              key={current.episode_video_url}
              className="featured-preview-video"
              src={current.episode_video_url}
              poster={work.cover_url || undefined}
              controls
              autoPlay
              muted
              playsInline
            />
          : work.cover_url
            ? <div className="featured-preview-empty is-cover"><img src={work.cover_url} alt="" /><p>该作品还没有成片视频，可点击「查看创作过程」了解制作流程。</p></div>
            : <div className="featured-preview-empty"><Clapperboard size={28} /><p>该作品还没有成片视频，可点击「查看创作过程」了解制作流程。</p></div>}
    </div>

    <footer className="featured-preview-bar">
      <div className="featured-preview-meta">
        <h2>{work?.title}</h2>
        <span className="featured-preview-ai">内容由 AI 生成</span>
        {episodes.length > 1 && <div className="featured-preview-episodes" role="tablist" aria-label="切换分集">
          {episodes.map((episode, index) => (
            <button
              key={episode.id || episode.number}
              type="button"
              role="tab"
              aria-selected={current?.id === episode.id}
              className={`featured-preview-episode${current?.id === episode.id ? " is-active" : ""}`}
              onClick={() => setEpisodeIndex(index)}
            >
              第 {episode.number} 集
            </button>
          ))}
        </div>}
      </div>
      <div className="featured-preview-actions">
        <Button className="featured-preview-detail" icon={<ScrollText size={14} />} onClick={() => navigate(director2FeaturedPath(featuredId))}>图文详情</Button>
        <Button type="primary" className="featured-preview-process" icon={<GitBranch size={15} />} onClick={() => navigate(director2FeaturedProcessPath(featuredId))}>查看创作过程</Button>
      </div>
    </footer>
  </div>
}
