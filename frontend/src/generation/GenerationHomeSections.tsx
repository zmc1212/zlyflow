import { Button, Dropdown, Empty, Skeleton, Tabs, Tooltip } from "antd"
import { ArrowRight, ChevronRight, Clapperboard, ExternalLink, Image as ImageIcon, MoreHorizontal, Play, RotateCw } from "lucide-react"
import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { PATHS } from "../paths"
import { recentCreations, type HomeJob, type RecentCreation } from "./generation-home"
import "./generation-home.css"

type Props = {
  jobs: readonly HomeJob[]
  loading: boolean
  error?: string
  onRetry: () => void
  onOpen: (jobId: string) => void
  onImageCreate: () => void
}

function createdLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
}

function CreationPreview({ item }: { item: RecentCreation }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false)
  const [mediaFailed, setMediaFailed] = useState(false)
  const [measuredRatio, setMeasuredRatio] = useState<number>()
  const ratio = measuredRatio ?? item.aspectRatio ?? (item.kind === "video" ? 16 / 9 : 1)
  const useImage = item.kind === "image" || (item.thumbnail && !thumbnailFailed)
  return <div className="studio-home-preview" style={{ aspectRatio: ratio }}>
    {mediaFailed ? <div className="studio-home-preview-fallback">
      {item.kind === "video" ? <Clapperboard size={24} /> : <ImageIcon size={24} />}
      <span>预览暂不可用</span><span>打开任务查看</span>
    </div> : useImage ? <img
      src={item.thumbnail && !thumbnailFailed ? item.thumbnail : item.src}
      alt="" loading="lazy" decoding="async"
      onLoad={(event) => {
        const image = event.currentTarget
        if (image.naturalWidth && image.naturalHeight) setMeasuredRatio(image.naturalWidth / image.naturalHeight)
      }}
      onError={() => item.thumbnail && !thumbnailFailed ? setThumbnailFailed(true) : setMediaFailed(true)}
    /> : <video
      src={item.src} muted playsInline preload="metadata" aria-hidden="true"
      onLoadedMetadata={(event) => {
        const video = event.currentTarget
        if (video.videoWidth && video.videoHeight) setMeasuredRatio(video.videoWidth / video.videoHeight)
      }}
      onError={() => setMediaFailed(true)}
    />}
    <span className="studio-home-preview-open"><ExternalLink size={17} />打开任务</span>
    {item.kind === "video" && <span className="studio-home-preview-duration"><Play size={11} fill="currentColor" />{item.duration || "视频"}</span>}
  </div>
}

export default function GenerationHomeSections({ jobs, loading, error, onRetry, onOpen, onImageCreate }: Props) {
  const [filter, setFilter] = useState("all")
  const entries = useMemo(() => recentCreations(jobs, jobs.length), [jobs])
  const visible = entries.filter((item) => filter === "all" || item.kind === filter).slice(0, 12)
  const columns = Array.from({ length: 4 }, () => [] as RecentCreation[])
  visible.forEach((item, index) => columns[index % columns.length].push(item))

  return <div className="studio-home-sections">
    <nav className="studio-home-doorways" aria-label="创作工具">
      <Link to={PATHS.director} className="studio-home-doorway studio-home-doorway-director">
        <img src="/generation-home/director-coast.png" alt="" />
        <div className="studio-home-doorway-copy"><h2>导演台 <ArrowRight size={19} /></h2><p>从剧本到镜头，连成一个故事</p></div>
        <span className="studio-home-doorway-go" aria-hidden="true"><ChevronRight size={20} /></span>
      </Link>
      <Button type="text" onClick={onImageCreate} className="studio-home-doorway studio-home-doorway-image">
        <img src="/generation-home/image-camellia.png" alt="" />
        <span className="studio-home-doorway-copy"><span className="studio-home-doorway-title">图片生成 <ArrowRight size={17} /></span><span className="studio-home-doorway-description">把想法变成参考画面</span></span>
      </Button>
      <Link to={PATHS.canvas} className="studio-home-doorway studio-home-doorway-canvas">
        <img src="/generation-home/canvas-workspace.png" alt="" />
        <div className="studio-home-doorway-copy"><h2>无限画布 <ArrowRight size={17} /></h2><p>把素材放在一起，自由编排</p></div>
      </Link>
    </nav>
    <section className="studio-home-recent" aria-labelledby="studio-home-recent-title">
      <div className="studio-home-recent-header">
        <h2 id="studio-home-recent-title">最近创作</h2>
        <Tabs
          className="studio-home-media-tabs" activeKey={filter} onChange={setFilter}
          items={[{ key: "all", label: "全部" }, { key: "video", label: "视频" }, { key: "image", label: "图片" }]}
        />
        <Link to={PATHS.assets} className="studio-home-view-all">查看全部 <ChevronRight size={14} /></Link>
      </div>
      {error && entries.length > 0 && <p className="studio-home-stale" role="status">刷新失败，正在显示上次的作品<Button type="link" size="small" onClick={onRetry}>重试</Button></p>}
      {loading ? <div className="studio-home-loading" aria-label="正在加载最近创作">
        {Array.from({ length: 4 }, (_, index) => <Skeleton.Image active key={index} />)}
      </div> : error && !entries.length ? <div className="studio-home-empty" role="status">
        <p>最近创作加载失败</p><span>{error}</span><Button icon={<RotateCw size={14} />} onClick={onRetry}>重新加载</Button>
      </div> : !visible.length ? <div className="studio-home-empty">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={entries.length ? `还没有${filter === "video" ? "视频" : "图片"}作品` : "第一幅作品，从上面的一个想法开始"} />
      </div> : <div className="studio-home-gallery">
        {columns.map((items, index) => <div key={index} className="studio-home-gallery-column">
          {items.map((item) => <article key={item.id} className="studio-home-creation">
            <button type="button" onClick={() => onOpen(item.jobId)} className="studio-home-creation-open" aria-label={`打开任务：${item.title}`}>
              <CreationPreview key={`${item.id}:${item.src}`} item={item} />
            </button>
            <div className="studio-home-creation-caption">
              <Tooltip title={item.title}><button type="button" onClick={() => onOpen(item.jobId)} className="studio-home-creation-title">{item.title}</button></Tooltip>
              <Dropdown trigger={["click"]} menu={{ items: [{ key: "open", label: "打开任务", icon: <ExternalLink size={14} /> }], onClick: () => onOpen(item.jobId) }}>
                <Button type="text" size="small" aria-label={`作品操作：${item.title}`} icon={<MoreHorizontal size={16} />} />
              </Dropdown>
              <p>{createdLabel(item.createdAt)}<span>·</span>{item.kind === "video" ? "视频" : "图片"}</p>
            </div>
          </article>)}
        </div>)}
      </div>}
    </section>
  </div>
}
