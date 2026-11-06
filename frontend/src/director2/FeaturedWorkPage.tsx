import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Drawer, Empty, Skeleton, Tabs, Tag, message } from "antd"
import { ArrowLeft, Clapperboard, Copy, GitBranch, Play, ScrollText, Users } from "lucide-react"
import { copyFeaturedWork, director2ErrorDetail, getFeaturedWork, type Director2FeaturedEpisode } from "./api"
import { formatHomeProjectDate } from "./home-project-cards"
import FeaturedWorkPreview from "./FeaturedWorkPreview"
import { director2FeaturedPath, director2FeaturedProcessPath, director2HomePath, director2ProjectPath } from "./paths"
import "./director-featured.css"

const KIND_LABELS: Record<string, string> = { character: "角色", scene: "场景", prop: "道具" }
const EPISODE_STATUS: Record<string, string> = {
  draft: "草稿",
  script_ready: "剧本就绪",
  storyboard_ready: "分镜就绪",
  producing: "制作中",
  completed: "已完成",
}

function EpisodeScript({ episode }: { episode: Director2FeaturedEpisode }) {
  return <div className="featured-drawer-body">
    {episode.episode_video_url ? <video className="featured-drawer-video" src={episode.episode_video_url} controls preload="metadata" /> : null}
    {episode.summary ? <p className="featured-drawer-summary">{episode.summary}</p> : null}
    <h3><ScrollText size={16} /> 本集剧本</h3>
    <pre className="featured-script-text">{episode.script_text || "本集暂无剧本正文"}</pre>
    <h3><Clapperboard size={16} /> 分镜（{episode.beats.length}）</h3>
    {episode.beats.length ? <div className="featured-beat-list">{episode.beats.map((beat, index) => (
      <article className="featured-beat" key={beat.id || index}>
        <div className="featured-beat-media">
          {beat.video_url ? <video src={beat.video_url} controls preload="metadata" /> : beat.image_url ? <img src={beat.image_url} alt="" loading="lazy" /> : <Clapperboard size={22} />}
        </div>
        <div className="featured-beat-copy">
          <div className="featured-beat-head">
            <strong>{beat.heading || `镜头 ${index + 1}`}</strong>
            {beat.camera ? <Tag bordered={false}>{beat.camera}</Tag> : null}
            {beat.duration > 0 ? <span>{beat.duration}s</span> : null}
          </div>
          {beat.dialogue ? <p className="featured-beat-dialogue"><span>{beat.speaker || "对白"}</span>{beat.dialogue}</p> : null}
          {beat.action ? <p>{beat.action}</p> : null}
          {beat.scene || beat.time_of_day ? <small>{[beat.scene, beat.time_of_day].filter(Boolean).join(" · ")}</small> : null}
        </div>
      </article>
    ))}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本集还没有分镜" />}
  </div>
}

export default function FeaturedWorkPage({ featuredId, csrfToken = "" }: { featuredId: string; csrfToken?: string }) {
  const navigate = useNavigate()
  const [episode, setEpisode] = useState<Director2FeaturedEpisode | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [copying, setCopying] = useState(false)
  const query = useQuery({
    queryKey: ["director-featured-work", featuredId],
    queryFn: () => getFeaturedWork(featuredId),
    retry: false,
  })
  const back = <Button type="text" className="featured-back" icon={<ArrowLeft size={16} />} onClick={() => navigate(director2HomePath())}>返回精选作品</Button>

  if (query.isLoading) {
    return <div className="featured-page"><div className="featured-page-inner">
      {back}
      <Skeleton active paragraph={{ rows: 3 }} />
      <div className="featured-loading-grid">{Array.from({ length: 3 }, (_, index) => <Skeleton.Node key={index} active className="featured-loading-card" />)}</div>
    </div></div>
  }
  if (query.isError || !query.data) {
    return <div className="featured-page"><div className="featured-page-inner">
      {back}
      <Alert type="error" showIcon title="精选作品加载失败" description="作品可能已下架，或当前登录状态已失效。" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />
    </div></div>
  }

  const work = query.data
  const snapshot = work.snapshot
  const cover = work.cover_url || snapshot.project.cover_url
  const assets = snapshot.assets.filter(asset => asset.name)
  const assetGroups = (["character", "scene", "prop"] as const)
    .map(kind => ({ kind, label: KIND_LABELS[kind], items: assets.filter(asset => asset.kind === kind) }))
    .filter(group => group.items.length)

  async function handleCopy() {
    if (copying) return
    setCopying(true)
    try {
      const result = await copyFeaturedWork(csrfToken, featuredId)
      message.success(`已复制到我的短剧「${result.name}」，现在可以编辑了`)
      navigate(director2ProjectPath(result.project_id, "content"))
    } catch (error) {
      message.error(director2ErrorDetail(error, "复制项目失败，请重试"))
    } finally {
      setCopying(false)
    }
  }

  const tabItems = [
    {
      key: "episodes",
      label: `分集 ${snapshot.episodes.length}`,
      children: snapshot.episodes.length ? <div className="featured-episode-grid">{snapshot.episodes.map(item => {
        const image = item.beats.find(beat => beat.image_url)?.image_url
        const video = item.beats.find(beat => beat.video_url)?.video_url
        return <button type="button" className="featured-episode-card" key={item.id || item.number} onClick={() => setEpisode(item)}>
          <div className="featured-episode-cover">
            {image ? <img src={image} alt="" loading="lazy" /> : video ? <video src={video} muted playsInline preload="metadata" /> : <Clapperboard size={24} />}
            {item.episode_video_url ? <span className="featured-episode-play"><Play size={14} /></span> : null}
          </div>
          <div className="featured-episode-copy">
            <div className="featured-episode-title"><span>第 {item.number} 集</span><h3>{item.title}</h3></div>
            {item.summary ? <p>{item.summary}</p> : null}
            <div className="featured-episode-meta">
              <span>{item.beats.length} 个镜头</span>
              {EPISODE_STATUS[item.status] ? <span>{EPISODE_STATUS[item.status]}</span> : null}
              <em>查看剧本</em>
            </div>
          </div>
        </button>
      })}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该作品还没有分集" />,
    },
    {
      key: "script",
      label: "剧本",
      children: snapshot.documents.length ? <div className="featured-documents">{snapshot.documents.map((document, index) => (
        <section className="featured-document" key={`${document.filename}-${index}`}>
          <h2><ScrollText size={16} /> {document.filename}</h2>
          <pre className="featured-script-text">{document.raw_text}</pre>
        </section>
      ))}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该作品未保存剧本文档，可在分集中查看每集剧本" />,
    },
    {
      key: "assets",
      label: `角色与场景 ${assets.length}`,
      children: assetGroups.length ? <div className="featured-asset-groups">{assetGroups.map(group => (
        <section className="featured-asset-group" key={group.kind}>
          <h2><Users size={16} /> {group.label}</h2>
          <div className="featured-asset-grid">{group.items.map(asset => (
            <article className="featured-asset-card" key={`${asset.kind}-${asset.name}`}>
              <div className="featured-asset-image">
                {asset.image_url ? <img src={asset.image_url} alt={asset.name} loading="lazy" /> : <Clapperboard size={20} />}
              </div>
              <strong>{asset.name}</strong>
              {asset.role ? <span>{asset.role}</span> : null}
              {asset.description ? <p>{asset.description}</p> : null}
            </article>
          ))}</div>
        </section>
      ))}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该作品还没有角色或场景资产" />,
    },
  ]

  return <div className="featured-page">
    <div className="featured-page-inner">
      {back}
      <header className="featured-hero">
        {cover ? <img className="featured-hero-bg" src={cover} alt="" /> : <div className="featured-hero-bg is-empty"><Clapperboard size={40} /></div>}
        <div className="featured-hero-shade" />
        <div className="featured-hero-body">
          <span className="featured-kicker">ZLY 精选作品</span>
          <h1>{work.title}</h1>
          {work.summary ? <p>{work.summary}</p> : null}
          <div className="featured-hero-meta">
            <span>{work.episode_count} 集</span>
            <span>{work.shot_count} 个镜头</span>
            <span>发布于 {formatHomeProjectDate(work.published_at)}</span>
          </div>
          <div className="featured-hero-actions">
            {snapshot.episodes.some(item => item.episode_video_url) ? <Button icon={<Play size={14} />} onClick={() => setPreviewOpen(true)}>查看成片</Button> : null}
            <Button icon={<GitBranch size={14} />} onClick={() => navigate(director2FeaturedProcessPath(featuredId))}>查看创作过程</Button>
            <Button type="primary" icon={<Copy size={14} />} loading={copying} onClick={() => void handleCopy()}>复制项目</Button>
          </div>
        </div>
      </header>
      <Tabs className="featured-tabs" items={tabItems} />
    </div>
    <Drawer
      className="featured-drawer"
      open={Boolean(episode)}
      onClose={() => setEpisode(null)}
      width={760}
      title={episode ? `第 ${episode.number} 集 · ${episode.title}` : ""}
      destroyOnHidden
    >
      {episode ? <EpisodeScript episode={episode} /> : null}
    </Drawer>
    {previewOpen && <FeaturedWorkPreview featuredId={featuredId} onClose={() => setPreviewOpen(false)} />}
  </div>
}
