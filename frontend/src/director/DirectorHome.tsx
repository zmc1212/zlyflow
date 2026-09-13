import { useState } from "react"
import { Button, Empty, Popconfirm, Spin } from "antd"
import { ArrowLeft, ChevronRight, Clapperboard, Clock3, Copy, Film, Image as ImageIcon, Layers, Play, Plus, Trash2 } from "lucide-react"
import ThemeToggle from "../components/ThemeToggle"
import { DirectorGenerationStatus, DirectorPayloadKind, DirectorProjectListItem } from "./director-api"

const RECENT_VISIBLE_COUNT = 6

function generationLabel(status: DirectorGenerationStatus) {
  return status === "complete" ? { text: "已完成", tone: "done" } : status === "partial" ? { text: "部分完成", tone: "partial" } : { text: "待生成", tone: "pending" }
}
function kindLabel(kind: DirectorPayloadKind) {
  return kind === "batch_run" ? { text: "短视频批量", Icon: Layers } : kind === "shot_replication" ? { text: "参考片复刻", Icon: ImageIcon } : { text: "导演创作", Icon: Clapperboard }
}
function pad(value: number) { return String(value).padStart(2, "0") }
function formatUpdatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

interface DirectorHomeProps { items: DirectorProjectListItem[]; loading: boolean; onCreateDirector: () => void; onCreateBatch: () => void; onCreateReplication?: () => void; onOpen: (item: DirectorProjectListItem) => void; onCopy: (projectId: string) => void; onDelete: (projectId: string) => void; onExitDirector?: () => void }

export default function DirectorHome({ items, loading, onCreateDirector, onCreateBatch, onCreateReplication, onOpen, onCopy, onDelete, onExitDirector }: DirectorHomeProps) {
  const [showAll, setShowAll] = useState(false)
  const canToggleAll = items.length > RECENT_VISIBLE_COUNT
  const visibleItems = showAll ? items : items.slice(0, RECENT_VISIBLE_COUNT)
  return <div className="director-home-v2">
    <header className="director-mobile-header director-home-mobile-header">
      <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
      <strong>导演台</strong>
      <div className="director-home-mobile-actions"><ThemeToggle /><button type="button" className="director-home-mobile-add" aria-label="新建导演创作" onClick={onCreateDirector}><Plus size={18} /></button></div>
    </header>
    <header className="director-home-topbar"><strong>导演台</strong><ThemeToggle /></header>
    <div className="director-home-scroll">
      <section className="director-home-hero"><h1>今天，想拍点什么？</h1><p>用 AI 将你的创意变成精彩的影视作品。</p></section>
      <section className="director-home-entries" aria-label="创作入口">
        <button type="button" className="dh-entry-primary" onClick={onCreateDirector}>
          <span className="dh-entry-head">
            <span className="dh-entry-icon"><Clapperboard size={20} /></span>
            <span className="dh-entry-copy"><strong>导演创作</strong><small>一句话开始，完成剧本与分镜</small></span>
          </span>
          <span className="dh-entry-steps">
            <span className="dh-step"><i>1</i>故事</span>
            <span className="dh-step-arrow">→</span>
            <span className="dh-step"><i>2</i>角色</span>
            <span className="dh-step-arrow">→</span>
            <span className="dh-step"><i>3</i>分镜</span>
          </span>
          <span className="dh-entry-cta"><Plus size={16} />新建导演工程</span>
          <span className="dh-entry-art" aria-hidden="true">
            <span className="dh-polaroid is-back"><i /></span>
            <span className="dh-polaroid is-front"><i /></span>
          </span>
        </button>
        <button type="button" className="dh-entry-card is-batch" onClick={onCreateBatch}>
          <span className="dh-entry-icon is-batch"><Play size={18} /></span>
          <span className="dh-entry-copy"><strong>短视频批量</strong><small>一个主题，生成多条短视频</small></span>
          <span className="dh-entry-go"><ChevronRight size={18} /></span>
        </button>
        {onCreateReplication ? <button type="button" className="dh-entry-card is-replication" onClick={onCreateReplication}>
          <span className="dh-entry-icon is-replication"><ImageIcon size={18} /></span>
          <span className="dh-entry-copy"><strong>参考片复刻</strong><small>分析参考片，批量转绘</small></span>
          <span className="dh-entry-go"><ChevronRight size={18} /></span>
        </button> : <span className="dh-entry-card is-placeholder" aria-hidden="true" />}
      </section>
      <section className="director-home-projects" aria-label="最近工程">
        <div className="director-home-section-head">
          <h2>最近工程</h2>
          {canToggleAll ? <button type="button" className="dh-view-all" onClick={() => setShowAll((open) => !open)}>{showAll ? "收起" : "查看全部"}<span>→</span></button> : null}
        </div>
        {loading ? <div className="dh-state"><Spin /><span>正在加载工程</span></div> : items.length === 0 ? <div className="dh-state is-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<div className="dh-empty-copy"><strong>还没有导演工程</strong><span>从上方选择一种创作方式，开始你的第一部片。</span></div>}><Button type="primary" icon={<Plus size={15} />} onClick={onCreateDirector}>新建导演工程</Button></Empty></div> : <div className="dh-project-grid">{visibleItems.map((item) => {
          const gen = generationLabel(item.generation_status)
          const kind = kindLabel(item.kind)
          const KindIcon = kind.Icon
          return <article key={item.id} className="dh-project">
            <button type="button" className="dh-project-main" onClick={() => onOpen(item)} aria-label={`打开工程 ${item.title}`}>
              <span className="dh-project-cover" data-kind={item.kind}>
                {item.cover_url ? <img src={item.cover_url} alt="" /> : <KindIcon size={22} />}
              </span>
              <span className="dh-project-info">
                <strong>{item.title}</strong>
                <span className="dh-project-summary">{item.summary || "暂无梗概"}</span>
                <span className="dh-project-chips"><span className="dh-chip is-kind">{kind.text}</span><span className={`dh-chip is-${gen.tone}`}>{gen.text}</span></span>
                <span className="dh-project-meta"><span><Film size={12} />{item.shot_count} 个镜头</span><span><Clock3 size={12} />{formatUpdatedAt(item.updated_at)}</span></span>
              </span>
            </button>
            <div className="dh-project-actions">
              <Button type="primary" className="dh-open-btn" onClick={() => onOpen(item)}>打开</Button>
              <Button type="text" className="dh-ghost-btn" icon={<Copy size={14} />} onClick={() => onCopy(item.id)}>复制</Button>
              <Popconfirm title="删除这个工程？" description="工程文档会从服务器移除，已生成的视频任务仍保留在任务列表。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => onDelete(item.id)}>
                <Button type="text" className="dh-ghost-btn is-danger" icon={<Trash2 size={14} />}>删除</Button>
              </Popconfirm>
            </div>
          </article>
        })}</div>}
      </section>
    </div>
  </div>
}
