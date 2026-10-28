// 导演台首页（/director）：director-home.css 按设计图调整桌面布局，继承全局双主题。
// 最近工程合并 /api/projects 导演创作与 /api/director/projects 中的批量 / 复刻；过滤 recipe / timeline。
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Alert, Button, Dropdown, Empty, Input, Menu, Modal, Segmented, Skeleton, Table, message, type TableProps } from "antd"
import { ArrowLeft, ArrowUpRight, ChevronRight, Clapperboard, Copy, FileSearch, Image as ImageIcon, Layers, MoreHorizontal, Plus, RotateCw, Search, Trash2 } from "lucide-react"
import ThemeToggle from "../components/ThemeToggle"
import { createProject, deleteProject, director2ErrorDetail, listProjects, listSkillPacks, type Director2SkillPack } from "./api"
import { director2DiagnosisPath, director2ProjectPath } from "./paths"
import SkillPackPickerModal from "./SkillPackPickerModal"
import { createProjectSkillPackExtra, defaultCreateSkillPackId } from "./skill-pack"
import { directorBatchPath, directorReplicationPath } from "../paths"
import { copyDirectorProject, createDirectorProjectRecord, deleteDirectorProject, listDirectorProjects } from "../director/director-api"
import { createEmptyBatch } from "../director/types"
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
import "./director-home.css"

const RECENT_VISIBLE_COUNT = 6

function pad(value: number) { return String(value).padStart(2, "0") }
function formatUpdatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function kindIcon(kind: HomeProjectItem["kind"]) {
  if (kind === "batch_run") return Layers
  if (kind === "shot_replication") return ImageIcon
  return Clapperboard
}

type CreateKind = HomeProjectItem["kind"]
const CREATE_MODES = [
  { kind: "studio", title: "导演创作", summary: "一句话开始，完成剧本与分镜", action: "新建导演工程", steps: [["故事", "输入你的创意或主题"], ["角色", "让角色和世界更加丰满"], ["分镜", "自动生成分镜脚本与画面提示"]] },
  { kind: "batch_run", title: "短视频批量", summary: "一个主题，生成多条短视频", action: "新建短视频批量", steps: [["主题", "确定系列与选题方向"], ["脚本", "准备每条视频的脚本"], ["视频", "生成镜头并合成短片"]] },
  { kind: "shot_replication", title: "参考片复刻", summary: "分析参考片，批量转绘", action: "新建参考片复刻", steps: [["参考", "选择要分析的参考片"], ["分析", "拆解参考片的镜头结构"], ["转绘", "按镜头批量转绘"]] },
] as const

function DirectorLens() {
  return <svg className="dh-workspace-lens" viewBox="0 0 326 160" fill="none" aria-hidden="true">
    <defs>
      <radialGradient id="dh-lens-core"><stop stopColor="var(--dh-lens-cyan)" stopOpacity=".32" /><stop offset=".65" stopColor="var(--dh-lens-blue)" stopOpacity=".1" /><stop offset="1" stopColor="var(--dh-lens-blue)" stopOpacity="0" /></radialGradient>
      <radialGradient id="dh-lens-shell" cx="32%" cy="24%" r="83%"><stop stopColor="var(--dh-lens-cyan)" stopOpacity=".38" /><stop offset=".4" stopColor="var(--studio-surface-raised)" /><stop offset=".76" stopColor="var(--dh-lens-shadow)" /><stop offset="1" stopColor="var(--dh-lens-blue)" stopOpacity=".5" /></radialGradient>
      <radialGradient id="dh-lens-glass" cx="34%" cy="25%" r="78%"><stop stopColor="var(--dh-lens-cyan)" stopOpacity=".46" /><stop offset=".32" stopColor="var(--studio-surface-raised)" /><stop offset=".68" stopColor="var(--dh-lens-shadow)" /><stop offset="1" stopColor="var(--dh-lens-blue)" stopOpacity=".45" /></radialGradient>
      <linearGradient id="dh-lens-ring" x1="102" y1="4" x2="222" y2="122" gradientUnits="userSpaceOnUse"><stop stopColor="var(--dh-lens-blue)" /><stop offset=".5" stopColor="var(--dh-lens-cyan)" /><stop offset="1" stopColor="var(--dh-lens-blue)" stopOpacity=".2" /></linearGradient>
      <linearGradient id="dh-lens-reflection" x1="133" y1="17" x2="192" y2="108" gradientUnits="userSpaceOnUse"><stop stopColor="var(--dh-lens-cyan)" stopOpacity=".8" /><stop offset=".4" stopColor="var(--studio-text)" stopOpacity=".12" /><stop offset=".65" stopColor="var(--dh-lens-shadow)" stopOpacity="0" /><stop offset="1" stopColor="var(--dh-lens-cyan)" stopOpacity=".5" /></linearGradient>
      <filter id="dh-lens-edge-glow" x="-35%" y="-35%" width="170%" height="170%"><feGaussianBlur stdDeviation="2" /></filter>
    </defs>
    <circle cx="163" cy="63" r="63" fill="url(#dh-lens-core)" />
    <g stroke="var(--dh-lens-blue)" opacity=".3"><circle cx="163" cy="63" r="62" /><circle cx="163" cy="63" r="43" /><path d="M4 57h145m27-17h145M52 81h40m143 0h43" /></g>
    <circle cx="163" cy="63" r="53" fill="url(#dh-lens-shell)" stroke="url(#dh-lens-ring)" strokeWidth="4" />
    <circle cx="163" cy="63" r="48" stroke="var(--dh-lens-shadow)" strokeWidth="5" />
    <circle cx="163" cy="63" r="43" stroke="url(#dh-lens-reflection)" strokeWidth="6" />
    <circle cx="163" cy="63" r="39" fill="url(#dh-lens-glass)" stroke="url(#dh-lens-ring)" strokeWidth="3" />
    <path d="M112 63a51 51 0 0 1 83-39M211 75a49 49 0 0 1-39 36" stroke="var(--dh-lens-cyan)" strokeWidth="4" opacity=".42" filter="url(#dh-lens-edge-glow)" />
    <path d="M114 49a51 51 0 0 1 65-35M199 96a48 48 0 0 1-33 15" stroke="var(--dh-lens-cyan)" strokeWidth="1.5" opacity=".8" />
    <circle cx="163" cy="63" r="28" stroke="url(#dh-lens-reflection)" strokeWidth="8" opacity=".42" />
    <circle cx="163" cy="63" r="18" fill="var(--dh-lens-shadow)" stroke="var(--dh-lens-blue)" strokeOpacity=".45" />
    <ellipse cx="153" cy="42" rx="22" ry="6" fill="var(--dh-lens-cyan)" opacity=".1" transform="rotate(-25 153 42)" />
    <path d="M163 7v21m-7 35h14m-7-7v14m-8 2-9 16m13-13 14 8m0-21 15-1m-17-9-4-12m-12 13-14-6" stroke="var(--dh-lens-cyan)" strokeOpacity=".6" />
    <path className="dh-lens-signal" d="M110 64H87q-8 0-8 8v7H48v14m164-29h27q8 0 8 8v7h31v14m-115-7v7" stroke="var(--dh-lens-cyan)" />
    {[7, 115, 223].map((x, i) => <g key={x}>
      <path d={`M${x} 93h96v59h-96Z`} fill="var(--studio-surface)" stroke="var(--dh-lens-cyan)" strokeWidth="1.4" />
      <path d={`M${x + 6} 100h84v45h-84Z`} fill="var(--studio-surface-raised)" stroke="var(--dh-lens-blue)" strokeOpacity=".4" />
      {i === 0 ? <><path d={`m${x + 9} 140 20-20 17 13 13-12 26 19Z`} fill="var(--dh-lens-blue)" opacity=".3" /><circle cx={x + 66} cy="112" r="6" fill="var(--dh-lens-blue)" opacity=".4" /></> : i === 1 ? <g stroke="var(--dh-lens-blue)" strokeOpacity=".65">{[0, 1, 2, 3, 4].map(n => <path key={n} d={`M${x + 13 + n * 14} 140v-${[19, 34, 23, 12, 19][n]}h8v${[19, 34, 23, 12, 19][n]}`} />)}</g> : <g stroke="var(--dh-lens-blue)" strokeOpacity=".65"><path d={`m${x + 8} 124 20-15 20 9 16-10 24 16m-81 2c36-20 76-2 57 6s-16 9 15 10m-23-20c-37 10-12 9-33 20`} /></g>}
      <circle cx={x + 48} cy="157" r="2" fill="var(--dh-lens-cyan)" />
    </g>)}
    <g fill="var(--dh-lens-cyan)"><circle cx="163" cy="7" r="2.2" /><circle cx="27" cy="79" r="2" /><circle cx="299" cy="79" r="2" /></g>
  </svg>
}


interface Director2StudioHomeProps { csrfToken: string; onExitDirector?: () => void }

export default function Director2StudioHome({ csrfToken, onExitDirector }: Director2StudioHomeProps) {
  const navigate = useNavigate()
  const [createKind, setCreateKind] = useState<CreateKind>("studio")
  const [items, setItems] = useState<HomeProjectItem[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState("")
  const [searchText, setSearchText] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [kindFilter, setKindFilter] = useState<HomeProjectFilter>(DEFAULT_HOME_PROJECT_FILTER)
  const [packPickerOpen, setPackPickerOpen] = useState(false)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [packsLoading, setPacksLoading] = useState(false)
  const [selectedPackId, setSelectedPackId] = useState("")
  const [creatingProject, setCreatingProject] = useState(false)
  const filteredItems = filterHomeProjects(items, kindFilter, searchText)
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
      .catch((error) => { if (!cancelled) setLoadError(director2ErrorDetail(error, "加载项目列表失败")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function retryLoadItems() {
    setLoading(true)
    setLoadError("")
    try {
      await refreshItems()
    } catch (error) {
      setLoadError(director2ErrorDetail(error, "加载项目列表失败"))
    } finally {
      setLoading(false)
    }
  }

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
    if (creatingProject) return
    setCreatingProject(true)
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
    } finally {
      setCreatingProject(false)
    }
  }

  async function handleCreateReplication() {
    if (creatingProject) return
    setCreatingProject(true)
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
    } finally {
      setCreatingProject(false)
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

  const createMode = CREATE_MODES.find((mode) => mode.kind === createKind) ?? CREATE_MODES[0]
  const columns: TableProps<HomeProjectItem>["columns"] = [
    { title: "工程", key: "project", render: (_, item) => {
      const KindIcon = kindIcon(item.kind)
      return <button type="button" className="dh-workspace-project-link" onClick={() => handleOpen(item)} aria-label={`打开工程 ${item.title}`}>
        <span className="dh-workspace-cover" data-kind={item.kind}>{item.cover_url ? <img src={item.cover_url} alt="" /> : <KindIcon size={26} />}</span>
        <span className="dh-workspace-project-copy"><strong title={item.title}>{item.title}</strong><span>{item.summary || "暂无简介"}</span></span>
      </button>
    } },
    { title: "创作类型", key: "kind", width: 170, render: (_, item) => <span className="dh-workspace-kind">{homeProjectKindLabel(item.kind)}</span> },
    { title: "最近编辑", key: "updated", width: 220, render: (_, item) => <time className="dh-workspace-time" dateTime={item.updated_at}>{formatUpdatedAt(item.updated_at)}</time> },
    { title: "", key: "actions", width: 180, render: (_, item) => <div className="dh-workspace-row-actions">
      <Button type="text" className="dh-workspace-open" onClick={() => handleOpen(item)}>打开<ArrowUpRight size={16} /></Button>
      <Dropdown trigger={["click"]} menu={{ items: [
        ...(item.source === "director" ? [{ key: "copy", label: "复制工程", icon: <Copy size={15} /> }] : []),
        { key: "delete", label: "删除工程", icon: <Trash2 size={15} />, danger: true },
      ], onClick: ({ key }) => {
        if (key === "copy") { void handleCopy(item); return }
        Modal.confirm({ title: "删除这个项目？", content: item.source === "director" ? "工程文档会从服务器移除，已生成的视频任务仍保留在任务列表。" : "项目会从服务器移除，删除后不可恢复。", okText: "删除", cancelText: "取消", okButtonProps: { danger: true }, onOk: () => handleDelete(item) })
      } }}><Button type="text" icon={<MoreHorizontal size={21} />} aria-label={`工程操作 ${item.title}`} /></Dropdown>
    </div> },
  ]

  async function handleStartCreate() {
    if (creatingProject) return
    if (createKind === "batch_run") { await handleCreateBatch(); return }
    if (createKind === "shot_replication") { await handleCreateReplication(); return }
    await openStudioCreatePicker()
  }

  return <div className="director-home-v2 dh-home-workspace">
    <header className="director-mobile-header director-home-mobile-header">
      <button type="button" aria-label="返回创作工作台" onClick={onExitDirector}><ArrowLeft size={20} /></button>
      <strong>导演台</strong><div className="director-home-mobile-actions"><ThemeToggle /></div>
    </header>
    <div className="director-home-scroll dh-workspace">
      <aside className="dh-start-column" aria-label="创作启动台">
        <section className="dh-start-panel">
          <header className="dh-start-heading"><h1>开始创作</h1><p>选择创作模式，开启你的故事。</p></header>
          <Menu className="dh-create-menu" mode="inline" aria-label="选择创作模式" selectedKeys={[createKind]} onClick={({ key }) => { if (CREATE_MODES.some((mode) => mode.kind === key)) setCreateKind(key as CreateKind) }} items={CREATE_MODES.map((mode) => {
            const Icon = kindIcon(mode.kind)
            return { key: mode.kind, icon: <Icon size={26} />, label: <span className="dh-create-menu-label"><strong>{mode.title}</strong><small>{mode.summary}</small></span>, extra: <ChevronRight size={17} /> }
          })} />
          <div className="dh-start-visual" data-kind={createKind}><DirectorLens /></div>
          <p className="dh-start-summary">{createMode.summary}</p>
          <ol className="dh-start-steps">{createMode.steps.map(([title, detail], index) => <li key={title}><span className="dh-start-step-number">{index + 1}</span><span><strong>{title}</strong><small>{detail}</small></span></li>)}</ol>
          <Button type="primary" className="dh-start-create" block icon={<Plus size={23} />} loading={creatingProject} onClick={() => { void handleStartCreate() }}>{createMode.action}</Button>
        </section>
        <Button type="text" className="dh-workspace-diagnosis" onClick={() => navigate(director2DiagnosisPath())} icon={<FileSearch size={29} />}><span><strong>剧本诊断</strong><small>查看评估与修改建议</small></span><ChevronRight size={19} /></Button>
      </aside>
      <section className="dh-project-workspace" aria-label="我的工程">
        <header className="dh-workspace-heading"><div><h2>我的工程 <span className="dh-project-count">{loading || loadError ? "" : `(${filteredItems.length})`}</span></h2><p>继续创作，或开始一个新故事。</p></div><Button className="dh-workspace-refresh" type="text" icon={<RotateCw size={17} />} loading={loading} onClick={() => { void retryLoadItems() }}>刷新</Button></header>
        <div className="dh-workspace-toolbar">
          <Segmented block className="dh-kind-filter" aria-label="按创作类型筛选工程" value={kindFilter} onChange={handleKindFilterChange} options={HOME_PROJECT_FILTERS.map((filter) => ({ label: homeProjectFilterLabel(filter), value: filter }))} />
          <Input className="dh-project-search" aria-label="搜索工程" placeholder="搜索工程" prefix={<Search size={18} />} allowClear value={searchText} onChange={(event) => { setSearchText(event.target.value); setShowAll(false) }} />
        </div>
        <div className="dh-workspace-list-scroll">
          <div className="dh-workspace-table-shell">
            {loading ? <div className="dh-workspace-loading" role="status" aria-label="正在加载工程">{[0, 1, 2, 3, 4, 5].map((key) => <Skeleton active avatar={{ shape: "square", size: 70 }} title paragraph={{ rows: 1 }} key={key} />)}</div> : loadError ? <Alert type="error" showIcon title="工程列表加载失败" description={loadError} action={<Button onClick={() => { void retryLoadItems() }}>重新加载</Button>} /> : filteredItems.length === 0 ? <div className="dh-workspace-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<div className="dh-empty-copy"><strong>{searchText.trim() ? "没有找到匹配的工程" : emptyCopy.title}</strong><span>{searchText.trim() ? "试试其他名称或简介关键词，也可以切换创作类型。" : emptyCopy.hint}</span></div>}>{searchText.trim() ? <Button onClick={() => setSearchText("")}>清空搜索</Button> : <Button type="primary" icon={<Plus size={15} />} onClick={handleEmptyCreate}>{emptyCopy.action}</Button>}</Empty></div> : <Table<HomeProjectItem> className="dh-workspace-table" tableLayout="fixed" pagination={false} rowKey={(item) => `${item.source}-${item.id}`} rowClassName="dh-workspace-project" columns={columns} dataSource={visibleItems} />}
            {!loading && !loadError && filteredItems.length > 0 ? <footer className="dh-workspace-list-footer"><span>显示 {visibleItems.length} 个工程</span><div>{canToggleAll ? <Button type="text" className="dh-view-all" onClick={() => setShowAll((open) => !open)}>{showAll ? "收起" : "查看全部"}</Button> : null}<span>按最近编辑排序</span></div></footer> : null}
          </div>
        </div>
      </section>
    </div>
    <SkillPackPickerModal open={packPickerOpen} packs={skillPacks} loading={packsLoading} confirming={creatingProject} value={selectedPackId} onChange={setSelectedPackId} onOk={(packId) => { void handleCreateStudioProject(packId ?? selectedPackId) }} onCancel={() => { if (!creatingProject) setPackPickerOpen(false) }} />
  </div>
}
