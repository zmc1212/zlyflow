// 导演台首页（/director）：复用 index.css 中 .director-home-v2 / .dh-* 全局样式（浅/暗 token 已成对配置）。
// 最近工程合并 /api/projects 导演创作与 /api/director/projects 中的批量 / 复刻 / Hypit；过滤 recipe / timeline。
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button, Empty, Popconfirm, Segmented, Spin, message } from "antd"
import { ArrowLeft, ChevronRight, Clapperboard, Clock3, Copy, Image as ImageIcon, Layers, Play, Plus, Shapes, Trash2 } from "lucide-react"
import ThemeToggle from "../components/ThemeToggle"
import { createProject, deleteProject, director2ErrorDetail, listProjects, listSkillPacks, type Director2SkillPack } from "./api"
import { director2ProjectPath } from "./paths"
import SkillPackPickerModal from "./SkillPackPickerModal"
import { createProjectSkillPackExtra, defaultCreateSkillPackId } from "./skill-pack"
import { directorBatchPath, directorHypitPath, directorReplicationPath } from "../paths"
import { copyDirectorProject, createDirectorProjectRecord, deleteDirectorProject, listDirectorProjects } from "../director/director-api"
import { createEmptyBatch } from "../director/types"
import { createEmptyHypit } from "../director/hypit-model"
import { createEmptyReplication } from "../director/replication-model"
import {
  DEFAULT_HOME_PROJECT_FILTER,
  HOME_PROJECT_FILTERS,
  filterHomeProjects,
  homeProjectFilterEmptyCopy,
  homeProjectFilterLabel,
  homeProjectKindLabel,
  mergeHomeProjects,
  type HomeProjectFilter,
  type HomeProjectItem,
} from "./home-projects"

const RECENT_VISIBLE_COUNT = 6

function pad(value: number) { return String(value).padStart(2, "0") }
function formatUpdatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function kindIcon(kind: HomeProjectItem["kind"]) {
  if (kind === "batch_run") return Layers
  if (kind === "shot_replication") return ImageIcon
  if (kind === "hypit_replication") return Shapes
  return Clapperboard
}

interface Director2StudioHomeProps { csrfToken: string; onExitDirector?: () => void }

export default function Director2StudioHome({ csrfToken, onExitDirector }: Director2StudioHomeProps) {
  const navigate = useNavigate()
  const [items, setItems] = useState<HomeProjectItem[]>([])
  const [loading, setLoading] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [kindFilter, setKindFilter] = useState<HomeProjectFilter>(DEFAULT_HOME_PROJECT_FILTER)
  const [packPickerOpen, setPackPickerOpen] = useState(false)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [packsLoading, setPacksLoading] = useState(false)
  const [selectedPackId, setSelectedPackId] = useState("")
  const [creatingProject, setCreatingProject] = useState(false)
  const filteredItems = filterHomeProjects(items, kindFilter)
  const canToggleAll = filteredItems.length > RECENT_VISIBLE_COUNT
  const visibleItems = showAll ? filteredItems : filteredItems.slice(0, RECENT_VISIBLE_COUNT)
  const emptyCopy = homeProjectFilterEmptyCopy(kindFilter)

  async function loadItems() {
    const [studioProjects, directorProjects] = await Promise.all([listProjects(), listDirectorProjects()])
    return mergeHomeProjects(Array.isArray(studioProjects) ? studioProjects : [], Array.isArray(directorProjects) ? directorProjects : [])
  }

  async function refreshItems() {
    setItems(await loadItems())
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    loadItems()
      .then((next) => { if (!cancelled) setItems(next) })
      .catch((error) => { if (!cancelled) message.error(director2ErrorDetail(error, "加载项目列表失败")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function openStudioCreatePicker() {
    setPackPickerOpen(true)
    setPacksLoading(true)
    try {
      const { packs } = await listSkillPacks()
      setSkillPacks(packs)
      setSelectedPackId(defaultCreateSkillPackId(packs))
    } catch (error) {
      message.error(director2ErrorDetail(error, "加载制作配方失败"))
      setSkillPacks([])
      setSelectedPackId("")
    } finally {
      setPacksLoading(false)
    }
  }

  async function handleCreateStudioProject(packId = selectedPackId) {
    setCreatingProject(true)
    try {
      const created = await createProject(csrfToken, {
        name: "未命名导演工程",
        extra: createProjectSkillPackExtra(packId),
      })
      setPackPickerOpen(false)
      navigate(director2ProjectPath(created.id, "content"))
    } catch (error) {
      message.error(director2ErrorDetail(error, "创建项目失败"))
    } finally {
      setCreatingProject(false)
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

  async function handleCreateHypit() {
    try {
      const created = await createDirectorProjectRecord({
        title: "Hypit 复刻",
        summary: "",
        source_script: "",
        payload: createEmptyHypit(),
      }, csrfToken)
      navigate(directorHypitPath(created.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败")
    }
  }

  function handleKindFilterChange(value: string | number) {
    setKindFilter(value as HomeProjectFilter)
    setShowAll(false)
  }

  function handleEmptyCreate() {
    if (kindFilter === "batch_run") {
      void handleCreateBatch()
      return
    }
    if (kindFilter === "shot_replication") {
      void handleCreateReplication()
      return
    }
    if (kindFilter === "hypit_replication") {
      void handleCreateHypit()
      return
    }
    void openStudioCreatePicker()
  }

  function handleOpen(item: HomeProjectItem) {
    if (item.kind === "batch_run") {
      navigate(directorBatchPath(item.id))
      return
    }
    if (item.kind === "shot_replication") {
      navigate(directorReplicationPath(item.id))
      return
    }
    if (item.kind === "hypit_replication") {
      navigate(directorHypitPath(item.id))
      return
    }
    navigate(director2ProjectPath(item.id, "content"))
  }

  async function handleCopy(item: HomeProjectItem) {
    if (item.source !== "director") return
    try {
      await copyDirectorProject(item.id, csrfToken)
      message.success("已复制工程")
      await refreshItems()
    } catch (error) {
      message.error(error instanceof Error ? error.message : "复制失败")
    }
  }

  async function handleDelete(item: HomeProjectItem) {
    try {
      if (item.source === "director") {
        await deleteDirectorProject(item.id, csrfToken)
      } else {
        await deleteProject(csrfToken, item.id)
      }
      message.success(item.source === "director" ? "工程已删除" : "项目已删除")
      setItems((current) => current.filter((entry) => entry.id !== item.id || entry.source !== item.source))
    } catch (error) {
      message.error(item.source === "director"
        ? (error instanceof Error ? error.message : "删除失败")
        : director2ErrorDetail(error, "删除项目失败"))
    }
  }

  return <div className="director-home-v2">
    <header className="director-mobile-header director-home-mobile-header">
      <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
      <strong>导演台</strong>
      <div className="director-home-mobile-actions"><ThemeToggle /><button type="button" className="director-home-mobile-add" aria-label="新建导演工程" onClick={openStudioCreatePicker}><Plus size={18} /></button></div>
    </header>
    <header className="director-home-topbar"><strong>导演台</strong><ThemeToggle /></header>
    <div className="director-home-scroll">
      <section className="director-home-hero"><h1>今天，想拍点什么？</h1><p>用 AI 将你的创意变成精彩的影视作品。</p></section>
      <section className="director-home-entries" aria-label="创作入口">
        <button type="button" className="dh-entry-primary" onClick={openStudioCreatePicker}>
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
        <button type="button" className="dh-entry-card is-hypit" onClick={handleCreateHypit}>
          <span className="dh-entry-icon is-hypit"><Shapes size={18} /></span>
          <span className="dh-entry-copy"><strong>Hypit 复刻</strong><small>拆结构、换内容、合字幕图形</small></span>
          <span className="dh-entry-go"><ChevronRight size={18} /></span>
        </button>
      </section>
      <section className="director-home-projects" aria-label="最近工程">
        <div className="director-home-section-head">
          <h2>最近工程</h2>
          <div className="director-home-section-tools">
            <div className="dh-kind-filter-wrap">
              <Segmented
                className="dh-kind-filter"
                size="small"
                aria-label="按创作类型筛选最近工程"
                value={kindFilter}
                onChange={handleKindFilterChange}
                options={HOME_PROJECT_FILTERS.map((filter) => ({ label: homeProjectFilterLabel(filter), value: filter }))}
              />
            </div>
            {canToggleAll ? <button type="button" className="dh-view-all" onClick={() => setShowAll((open) => !open)}>{showAll ? "收起" : "查看全部"}<span>→</span></button> : null}
          </div>
        </div>
        {loading ? <div className="dh-state"><Spin /><span>正在加载工程</span></div> : filteredItems.length === 0 ? <div className="dh-state is-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<div className="dh-empty-copy"><strong>{emptyCopy.title}</strong><span>{emptyCopy.hint}</span></div>}><Button type="primary" icon={<Plus size={15} />} onClick={handleEmptyCreate}>{emptyCopy.action}</Button></Empty></div> : <div className="dh-project-grid">{visibleItems.map((item) => {
          const KindIcon = kindIcon(item.kind)
          return <article key={`${item.source}-${item.id}`} className="dh-project">
            <button type="button" className="dh-project-main" onClick={() => handleOpen(item)} aria-label={`打开工程 ${item.title}`}>
              <span className="dh-project-cover" data-kind={item.kind}>
                {item.cover_url ? <img src={item.cover_url} alt="" /> : <KindIcon size={22} />}
              </span>
              <span className="dh-project-info">
                <strong>{item.title}</strong>
                <span className="dh-project-summary">{item.summary || "暂无简介"}</span>
                <span className="dh-project-chips"><span className="dh-chip is-kind">{homeProjectKindLabel(item.kind)}</span></span>
                <span className="dh-project-meta"><span><Clock3 size={12} />{formatUpdatedAt(item.updated_at)}</span></span>
              </span>
            </button>
            <div className="dh-project-actions">
              <Button type="primary" className="dh-open-btn" onClick={() => handleOpen(item)}>打开</Button>
              {item.source === "director" ? <Button type="text" className="dh-ghost-btn" icon={<Copy size={14} />} onClick={() => handleCopy(item)}>复制</Button> : null}
              <Popconfirm title="删除这个项目？" description={item.source === "director" ? "工程文档会从服务器移除，已生成的视频任务仍保留在任务列表。" : "项目会从服务器移除，删除后不可恢复。"} okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => handleDelete(item)}>
                <Button type="text" className="dh-ghost-btn is-danger" icon={<Trash2 size={14} />}>删除</Button>
              </Popconfirm>
            </div>
          </article>
        })}</div>}
      </section>
    </div>
    <SkillPackPickerModal
      open={packPickerOpen}
      packs={skillPacks}
      loading={packsLoading}
      confirming={creatingProject}
      value={selectedPackId}
      onChange={setSelectedPackId}
      onOk={(packId) => { void handleCreateStudioProject(packId ?? selectedPackId) }}
      onCancel={() => { if (!creatingProject) setPackPickerOpen(false) }}
    />
  </div>
}
