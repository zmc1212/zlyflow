// 导演台首页 —— 逐像素复刻旧导演台首页（frontend/src/director/DirectorHome.tsx），
// 复用 index.css 中 .director-home-v2 / .dh-* 全局样式（浅/暗 token 已成对配置），不复制样式。
// 差异：工程列表接导演台2 创作项目（/api/projects）；「短视频批量 / 参考片复刻」入口
// 仍走旧导演台的创建接口并跳转对应工作台；导演台2 暂无复制接口，卡片仅保留打开/删除。
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button, Empty, Popconfirm, Spin, message } from "antd"
import { ArrowLeft, ChevronRight, Clapperboard, Clock3, Image as ImageIcon, Play, Plus, Trash2 } from "lucide-react"
import ThemeToggle from "../components/ThemeToggle"
import { createProject, deleteProject, director2ErrorDetail, listProjects, type Director2Project } from "./api"
import { director2ProjectPath } from "./paths"
import { directorBatchPath, directorReplicationPath } from "../paths"
import { createDirectorProjectRecord } from "../director/director-api"
import { createEmptyBatch } from "../director/types"
import { createEmptyReplication } from "../director/replication-model"

const RECENT_VISIBLE_COUNT = 6

function pad(value: number) { return String(value).padStart(2, "0") }
function formatUpdatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

interface Director2StudioHomeProps { csrfToken: string; onExitDirector?: () => void }

export default function Director2StudioHome({ csrfToken, onExitDirector }: Director2StudioHomeProps) {
  const navigate = useNavigate()
  const [items, setItems] = useState<Director2Project[]>([])
  const [loading, setLoading] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const canToggleAll = items.length > RECENT_VISIBLE_COUNT
  const visibleItems = showAll ? items : items.slice(0, RECENT_VISIBLE_COUNT)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listProjects()
      .then((data) => { if (!cancelled) setItems(Array.isArray(data) ? data : []) })
      .catch((error) => { if (!cancelled) message.error(director2ErrorDetail(error, "加载项目列表失败")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function handleCreateStudioProject() {
    try {
      const created = await createProject(csrfToken, { name: "未命名导演工程" })
      navigate(director2ProjectPath(created.id, "content"))
    } catch (error) {
      message.error(director2ErrorDetail(error, "创建项目失败"))
    }
  }

  async function handleCreateBatch() {
    try {
      const created = await createDirectorProjectRecord({
        title: "批量短视频",
        summary: "",
        source_script: "",
        payload: createEmptyBatch(),
      }, csrfToken)
      navigate(directorBatchPath(created.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败")
    }
  }

  async function handleCreateReplication() {
    try {
      const created = await createDirectorProjectRecord({
        title: "参考片复刻",
        summary: "",
        source_script: "",
        payload: createEmptyReplication(),
      }, csrfToken)
      navigate(directorReplicationPath(created.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败")
    }
  }

  function handleOpen(item: Director2Project) {
    navigate(director2ProjectPath(item.id, "content"))
  }

  async function handleDelete(projectId: string) {
    try {
      await deleteProject(csrfToken, projectId)
      message.success("项目已删除")
      setItems((current) => current.filter((item) => item.id !== projectId))
    } catch (error) {
      message.error(director2ErrorDetail(error, "删除项目失败"))
    }
  }

  return <div className="director-home-v2">
    <header className="director-mobile-header director-home-mobile-header">
      <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
      <strong>导演台</strong>
      <div className="director-home-mobile-actions"><ThemeToggle /><button type="button" className="director-home-mobile-add" aria-label="新建导演工程" onClick={handleCreateStudioProject}><Plus size={18} /></button></div>
    </header>
    <header className="director-home-topbar"><strong>导演台</strong><ThemeToggle /></header>
    <div className="director-home-scroll">
      <section className="director-home-hero"><h1>今天，想拍点什么？</h1><p>用 AI 将你的创意变成精彩的影视作品。</p></section>
      <section className="director-home-entries" aria-label="创作入口">
        <button type="button" className="dh-entry-primary" onClick={handleCreateStudioProject}>
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
        <button type="button" className="dh-entry-card is-batch" onClick={handleCreateBatch}>
          <span className="dh-entry-icon is-batch"><Play size={18} /></span>
          <span className="dh-entry-copy"><strong>短视频批量</strong><small>一个主题，生成多条短视频</small></span>
          <span className="dh-entry-go"><ChevronRight size={18} /></span>
        </button>
        <button type="button" className="dh-entry-card is-replication" onClick={handleCreateReplication}>
          <span className="dh-entry-icon is-replication"><ImageIcon size={18} /></span>
          <span className="dh-entry-copy"><strong>参考片复刻</strong><small>分析参考片，批量转绘</small></span>
          <span className="dh-entry-go"><ChevronRight size={18} /></span>
        </button>
      </section>
      <section className="director-home-projects" aria-label="最近工程">
        <div className="director-home-section-head">
          <h2>最近工程</h2>
          {canToggleAll ? <button type="button" className="dh-view-all" onClick={() => setShowAll((open) => !open)}>{showAll ? "收起" : "查看全部"}<span>→</span></button> : null}
        </div>
        {loading ? <div className="dh-state"><Spin /><span>正在加载工程</span></div> : items.length === 0 ? <div className="dh-state is-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<div className="dh-empty-copy"><strong>还没有创作项目</strong><span>从上方选择一种创作方式，开始你的第一部片。</span></div>}><Button type="primary" icon={<Plus size={15} />} onClick={handleCreateStudioProject}>新建项目</Button></Empty></div> : <div className="dh-project-grid">{visibleItems.map((item) => {
          return <article key={item.id} className="dh-project">
            <button type="button" className="dh-project-main" onClick={() => handleOpen(item)} aria-label={`打开工程 ${item.name}`}>
              <span className="dh-project-cover">
                {item.cover_url ? <img src={item.cover_url} alt="" /> : <Clapperboard size={22} />}
              </span>
              <span className="dh-project-info">
                <strong>{item.name}</strong>
                <span className="dh-project-summary">{item.description || "暂无简介"}</span>
                <span className="dh-project-chips"><span className="dh-chip is-kind">创作项目</span></span>
                <span className="dh-project-meta"><span><Clock3 size={12} />{formatUpdatedAt(item.updated_at)}</span></span>
              </span>
            </button>
            <div className="dh-project-actions">
              <Button type="primary" className="dh-open-btn" onClick={() => handleOpen(item)}>打开</Button>
              <Popconfirm title="删除这个项目？" description="项目会从服务器移除，删除后不可恢复。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => handleDelete(item.id)}>
                <Button type="text" className="dh-ghost-btn is-danger" icon={<Trash2 size={14} />}>删除</Button>
              </Popconfirm>
            </div>
          </article>
        })}</div>}
      </section>
    </div>
  </div>
}
