// The homepage uses real assistant and project APIs; the v003 reference supplies layout only.
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Drawer, Dropdown, Empty, Input, Modal, Skeleton, Tooltip, message } from "antd"
import { Clapperboard, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react"
import { createProject, deleteProject, director2ErrorDetail, listAssets, listDocuments, listEpisodes, listProjects, listSkillPacks, type Director2Project, type Director2SkillPack } from "./api"
import { director2ProjectPath } from "./paths"
import SkillPackPickerModal from "./SkillPackPickerModal"
import { createProjectSkillPackExtra, defaultCreateSkillPackId } from "./skill-pack"
import { useDirectorAssistantHome } from "./assistant/DirectorAssistant"
import { formatHomeProjectDate, homeProjectImages, type HomeProjectImage } from "./home-project-cards"
import HomeCreationPanel from "./HomeCreationPanel"
import { readProjectPosition, resumeProjectPath } from "./project-flow"
import "./director-home.css"
import "./home-creation.css"

function ProjectCover({ images }: { images: HomeProjectImage[] }) {
  const [failed, setFailed] = useState<string[]>([])
  const visible = images.filter(image => !failed.includes(image.url))
  return <div className={`dh-project-cover${visible.length ? "" : " is-empty"}`}>
    {visible.length ? visible.map(image => <div className="dh-project-photo" key={image.url}>
      <img src={image.url} alt="" loading="lazy" style={{ objectFit: image.fit }} onError={() => setFailed(current => [...current, image.url])} />
    </div>) : <Clapperboard size={20} strokeWidth={1.5} aria-hidden="true" />}
  </div>
}

function ProjectCard({ project, onOpen, onDelete }: { project: Director2Project; onOpen: () => void; onDelete: () => void }) {
  const card = useRef<HTMLElement>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    if (!card.current || !window.IntersectionObserver) { setInView(true); return }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setInView(true); observer.disconnect() }
    }, { rootMargin: "120px" })
    observer.observe(card.current)
    return () => observer.disconnect()
  }, [])
  const assets = useQuery({ queryKey: ["director-home-assets", project.id], queryFn: () => listAssets(project.id), enabled: inView && !project.cover_url?.trim(), staleTime: 60_000, retry: false })
  return <article ref={card} className="dh-project-card">
    <Button type="text" className="dh-project-open" aria-label={`打开短剧：${project.name}`} onClick={onOpen} />
    <ProjectCover images={homeProjectImages(project, assets.data)} />
    <div className="dh-project-info">
      <div className="dh-project-title-row">
        <h3 title={project.name}>{project.name}</h3>
        <Dropdown trigger={["click"]} menu={{ items: [
          { key: "open", label: "打开短剧", icon: <Clapperboard size={14} /> },
          { type: "divider" },
          { key: "delete", label: "删除短剧", icon: <Trash2 size={14} />, danger: true },
        ], onClick: ({ key }) => key === "delete" ? onDelete() : onOpen() }}>
          <Button type="text" className="dh-project-more" aria-label={`${project.name}的更多操作`} icon={<MoreHorizontal size={16} />} />
        </Dropdown>
      </div>
      <div className="dh-project-date-row"><time dateTime={project.updated_at} title={new Date(project.updated_at).toLocaleString("zh-CN")}>{formatHomeProjectDate(project.updated_at)}</time></div>
    </div>
  </article>
}

export default function Director2StudioHome({ csrfToken }: { csrfToken: string; onExitDirector?: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const assistant = useDirectorAssistantHome()
  const [toolsOpen, setToolsOpen] = useState(false)
  const opening = useRef(false)
  const [projects, setProjects] = useState<Director2Project[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [searchOpen, setSearchOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [columns, setColumns] = useState(() => window.matchMedia("(min-width: 1701px)").matches ? 5 : 3)
  const [packPickerOpen, setPackPickerOpen] = useState(false)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [packsLoading, setPacksLoading] = useState(false)
  const [selectedPackId, setSelectedPackId] = useState("")
  const [creatingProject, setCreatingProject] = useState(false)
  const loadVersion = useRef(0)
  const [modal, modalContext] = Modal.useModal()
  const query = search.trim().toLocaleLowerCase()
  const filtered = projects.filter(project => !query || `${project.name}\n${project.description || ""}`.toLocaleLowerCase().includes(query))
  const visible = showAll || query ? filtered : filtered.slice(0, columns)
  const collapsed = false

  const refreshProjects = useCallback(async () => {
    const version = ++loadVersion.current
    setLoading(true); setLoadError("")
    try {
      const next = await listProjects()
      if (version === loadVersion.current) setProjects([...next].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)))
    } catch (error) { if (version === loadVersion.current) setLoadError(director2ErrorDetail(error, "加载短剧失败")) }
    finally { if (version === loadVersion.current) setLoading(false) }
  }, [])
  useEffect(() => {
    void refreshProjects()
    const updated = (event: Event) => {
      void refreshProjects()
      const projectId = (event as CustomEvent<{ projectId?: string }>).detail?.projectId
      void queryClient.invalidateQueries({ queryKey: projectId ? ["director-home-assets", projectId] : ["director-home-assets"] })
    }
    window.addEventListener("director-assistant-project-updated", updated)
    return () => { loadVersion.current++; window.removeEventListener("director-assistant-project-updated", updated) }
  }, [refreshProjects, queryClient])
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1701px)")
    const change = () => setColumns(media.matches ? 5 : 3)
    media.addEventListener("change", change)
    return () => media.removeEventListener("change", change)
  }, [])

  async function openCreatePicker() {
    setPackPickerOpen(true); setPacksLoading(true)
    try {
      const { packs } = await listSkillPacks()
      setSkillPacks(packs); setSelectedPackId(defaultCreateSkillPackId(packs))
    } catch (error) { message.error(director2ErrorDetail(error, "加载制作配方失败")); setSkillPacks([]); setSelectedPackId("") }
    finally { setPacksLoading(false) }
  }
  async function createStudioProject(packId = selectedPackId) {
    setCreatingProject(true)
    try {
      const project = await createProject(csrfToken, { name: "未命名短剧", extra: createProjectSkillPackExtra(packId) })
      setPackPickerOpen(false); navigate(director2ProjectPath(project.id, "content"))
    } catch (error) { message.error(director2ErrorDetail(error, "创建短剧失败")) }
    finally { setCreatingProject(false) }
  }
  async function openProject(project: Director2Project) {
    if (opening.current) return
    opening.current = true
    message.loading({ key: "director-open-project", content: "正在恢复短剧…", duration: 0 })
    try {
      const [documents, assets, episodes] = await Promise.all([listDocuments(project.id), listAssets(project.id), listEpisodes(project.id)])
      navigate(resumeProjectPath(project.id, { documents, assets, episodes }, readProjectPosition(project.id)))
    } catch (error) { message.error(director2ErrorDetail(error, "读取短剧失败，请重试")) }
    finally { opening.current = false; message.destroy("director-open-project") }
  }
  function confirmDelete(project: Director2Project) {
    modal.confirm({ title: `删除“${project.name}”？`, content: "将删除此短剧及其关联内容，此操作无法撤销。", okText: "删除短剧", cancelText: "取消", okButtonProps: { danger: true },
      onOk: async () => {
        try { await deleteProject(csrfToken, project.id); setProjects(current => current.filter(item => item.id !== project.id)); message.success("短剧已删除") }
        catch (error) { message.error(director2ErrorDetail(error, "删除短剧失败")); throw error }
      },
    })
  }

  return <div className="director-agent-home">
    <div className="dh-home-content">
      <section className="dh-agent-section" aria-label="智能助手">
        <h1>把故事想法，变成你的短剧</h1>
        <HomeCreationPanel csrfToken={csrfToken} onTools={() => setToolsOpen(true)} />
      </section>
      <section className={`dh-projects${collapsed ? " is-collapsed" : ""}`} aria-labelledby="my-dramas-heading">
        <div className="dh-projects-heading">
          <h2 id="my-dramas-heading">我的短剧</h2>
          {!collapsed && <div className="dh-project-actions">
            {searchOpen ? <Input size="small" className="dh-project-search" aria-label="搜索我的短剧" placeholder="搜索短剧" autoFocus allowClear prefix={<Search size={13} />} value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === "Escape") { setSearch(""); setSearchOpen(false) } }} /> : <Tooltip title="搜索短剧"><Button type="text" className="dh-project-icon" aria-label="搜索短剧" icon={<Search size={14} />} onClick={() => setSearchOpen(true)} /></Tooltip>}
            <Tooltip title="新建短剧"><Button type="text" className="dh-project-icon" aria-label="新建短剧" icon={<Plus size={15} />} onClick={() => void openCreatePicker()} /></Tooltip>
            <Button type="text" className="dh-all-projects" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? "收起" : "全部"}</Button>
          </div>}
        </div>
        {!collapsed && <>
          {loadError && <Alert className="dh-project-error" type="error" showIcon title={loadError} action={<Button size="small" onClick={() => void refreshProjects()}>重试</Button>} />}
          {loading && !projects.length ? <div className="dh-project-grid" aria-label="正在加载短剧" aria-busy="true">{Array.from({ length: columns }, (_, index) => <div className="dh-project-skeleton" key={index}><Skeleton.Node active className="dh-project-cover" /><Skeleton active paragraph={{ rows: 1, width: "30%" }} title={{ width: "55%" }} /></div>)}</div> : visible.length ? <div className="dh-project-grid">{visible.map(project => <ProjectCard key={project.id} project={project} onOpen={() => void openProject(project)} onDelete={() => confirmDelete(project)} />)}</div> : !loadError && <Empty className="dh-project-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? "没有找到相关短剧" : "还没有短剧，先和助手聊聊你的想法"}>{!query && <Button onClick={() => void openCreatePicker()}>新建短剧</Button>}</Empty>}
        </>}
      </section>
    </div>
    <SkillPackPickerModal open={packPickerOpen} packs={skillPacks} loading={packsLoading} value={selectedPackId} confirming={creatingProject} onChange={setSelectedPackId} onCancel={() => { if (!creatingProject) setPackPickerOpen(false) }} onOk={packId => void createStudioProject(packId)} />
    <Drawer title="创作工具与历史" rootClassName="director-tools-drawer" open={toolsOpen} onClose={() => setToolsOpen(false)} size={960} destroyOnHidden><div className="director-agent-home dh-tools-surface">{assistant.surface}</div></Drawer>
    {modalContext}
  </div>
}
