// The homepage uses real assistant and project APIs; the v003 reference supplies layout only.
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Drawer, Dropdown, Empty, Input, InputNumber, Modal, Skeleton, Tooltip, message } from "antd"
import { Clapperboard, EyeOff, MoreHorizontal, Plus, Search, Sparkles, Trash2 } from "lucide-react"
import { createProject, deleteProject, director2ErrorDetail, listAssets, listDocuments, listEpisodes, listFeaturedWorks, listProjects, listSkillPacks, publishFeaturedWork, unpublishFeaturedWork, type Director2FeaturedWork, type Director2Project, type Director2SkillPack } from "./api"
import { director2ProjectPath } from "./paths"
import SkillPackPickerModal from "./SkillPackPickerModal"
import { createProjectSkillPackExtra, defaultCreateSkillPackId } from "./skill-pack"
import { useDirectorAssistantHome } from "./assistant/DirectorAssistant"
import { formatHomeProjectDate, homeProjectImages, type HomeProjectImage } from "./home-project-cards"
import HomeCreationPanel from "./HomeCreationPanel"
import FeaturedWorkPreview from "./FeaturedWorkPreview"
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

function ProjectCard({ project, featured, isAdmin, onOpen, onDelete, onPublish, onUnpublish }: {
  project: Director2Project
  featured?: Director2FeaturedWork
  isAdmin: boolean
  onOpen: () => void
  onDelete: () => void
  onPublish: () => void
  onUnpublish: () => void
}) {
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
  const items = [
    { key: "open", label: "打开短剧", icon: <Clapperboard size={14} /> },
    { type: "divider" as const },
    ...(isAdmin ? [{ key: "publish", label: featured ? "更新精选" : "发布为精选", icon: <Sparkles size={14} /> }] : []),
    ...(isAdmin && featured ? [{ key: "unpublish", label: "取消精选", icon: <EyeOff size={14} />, danger: true }] : []),
    ...(isAdmin ? [{ type: "divider" as const }] : []),
    { key: "delete", label: "删除短剧", icon: <Trash2 size={14} />, danger: true },
  ]
  return <article ref={card} className="dh-project-card">
    <Button type="text" className="dh-project-open" aria-label={`打开短剧：${project.name}`} onClick={onOpen} />
    <ProjectCover images={homeProjectImages(project, assets.data)} />
    <div className="dh-project-info">
      <div className="dh-project-title-row">
        <h3 title={project.name}>{project.name}</h3>
        <Dropdown trigger={["click"]} menu={{ items, onClick: ({ key }) => {
          if (key === "publish") onPublish()
          else if (key === "unpublish") onUnpublish()
          else if (key === "delete") onDelete()
          else onOpen()
        } }}>
          <Button type="text" className="dh-project-more" aria-label={`${project.name}的更多操作`} icon={<MoreHorizontal size={16} />} />
        </Dropdown>
      </div>
      <div className="dh-project-date-row"><time dateTime={project.updated_at} title={new Date(project.updated_at).toLocaleString("zh-CN")}>{formatHomeProjectDate(project.updated_at)}</time></div>
    </div>
  </article>
}

function FeaturedCard({ work, isAdmin, onOpen, onUnpublish }: { work: Director2FeaturedWork; isAdmin: boolean; onOpen: () => void; onUnpublish: () => void }) {
  return <article className="dh-featured-card">
    <Button type="text" className="dh-featured-open" aria-label={`打开精选作品：${work.title}`} onClick={onOpen} />
    <div className="dh-featured-cover">
      {work.cover_url ? <img src={work.cover_url} alt="" loading="lazy" /> : <Clapperboard size={22} />}
      <span className="dh-featured-badge"><Sparkles size={12} />精选</span>
      {isAdmin && <Dropdown trigger={["click"]} menu={{ items: [{ key: "unpublish", label: "取消精选", icon: <EyeOff size={14} />, danger: true }], onClick: onUnpublish }}>
        <Button type="text" className="dh-featured-more" aria-label={`${work.title}的精选操作`} icon={<MoreHorizontal size={16} />} />
      </Dropdown>}
    </div>
    <div className="dh-featured-info">
      <h3 title={work.title}>{work.title}</h3>
      <p>{work.summary || "管理员精选的短剧作品"}</p>
      <div className="dh-featured-meta">
        <span>{work.episode_count} 集</span>
        <span>{work.shot_count} 个镜头</span>
        <time dateTime={work.published_at}>{formatHomeProjectDate(work.published_at)}</time>
      </div>
    </div>
  </article>
}

type FeaturedDraft = {
  project: Director2Project
  work?: Director2FeaturedWork
  title: string
  summary: string
  coverUrl: string
  sortOrder: number
}

export default function Director2StudioHome({ csrfToken, isAdmin = false }: { csrfToken: string; isAdmin?: boolean; onExitDirector?: () => void }) {
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
  const featuredQuery = useQuery({ queryKey: ["director-featured-works"], queryFn: listFeaturedWorks, staleTime: 30_000, retry: false })
  const featuredWorks = useMemo(() => featuredQuery.data ?? [], [featuredQuery.data])
  const featuredByProject = useMemo(() => new Map(featuredWorks.map(work => [work.project_id, work])), [featuredWorks])
  const [featuredDraft, setFeaturedDraft] = useState<FeaturedDraft | null>(null)
  const [publishingFeatured, setPublishingFeatured] = useState(false)
  const [previewWorkId, setPreviewWorkId] = useState<string | null>(null)
  const query = search.trim().toLocaleLowerCase()
  const filtered = projects.filter(project => !query || `${project.name}\n${project.description || ""}`.toLocaleLowerCase().includes(query))
  const visible = showAll || query ? filtered : filtered.slice(0, columns)
  const showFeatured = isAdmin || featuredWorks.length > 0
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
  function openFeaturedModal(project: Director2Project) {
    const work = featuredByProject.get(project.id)
    setFeaturedDraft({
      project,
      work,
      title: work?.title || project.name,
      summary: work?.summary || project.description || "",
      coverUrl: work?.cover_url || project.cover_url || "",
      sortOrder: work?.sort_order ?? 0,
    })
  }
  async function submitFeatured() {
    if (!featuredDraft) return
    const title = featuredDraft.title.trim()
    if (!title) { message.warning("请填写精选标题"); return }
    setPublishingFeatured(true)
    try {
      await publishFeaturedWork(csrfToken, {
        project_id: featuredDraft.project.id,
        title,
        summary: featuredDraft.summary.trim(),
        cover_url: featuredDraft.coverUrl.trim(),
        sort_order: featuredDraft.sortOrder,
      })
      await queryClient.invalidateQueries({ queryKey: ["director-featured-works"] })
      setFeaturedDraft(null)
      message.success(featuredDraft.work ? "精选作品已更新" : "已发布为精选作品")
    } catch (error) { message.error(director2ErrorDetail(error, "发布精选失败")) }
    finally { setPublishingFeatured(false) }
  }
  function confirmUnpublish(work: Director2FeaturedWork) {
    modal.confirm({
      title: `取消精选“${work.title}”？`,
      content: "取消后所有成员将不再在首页精选作品里看到它，短剧本身不受影响。",
      okText: "取消精选", cancelText: "保留", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await unpublishFeaturedWork(csrfToken, work.id)
          await queryClient.invalidateQueries({ queryKey: ["director-featured-works"] })
          message.success("已取消精选")
        } catch (error) { message.error(director2ErrorDetail(error, "取消精选失败")); throw error }
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
          {loading && !projects.length ? <div className="dh-project-grid" aria-label="正在加载短剧" aria-busy="true">{Array.from({ length: columns }, (_, index) => <div className="dh-project-skeleton" key={index}><Skeleton.Node active className="dh-project-cover" /><Skeleton active paragraph={{ rows: 1, width: "30%" }} title={{ width: "55%" }} /></div>)}</div> : visible.length ? <div className="dh-project-grid">{visible.map(project => {
            const work = featuredByProject.get(project.id)
            return <ProjectCard key={project.id} project={project} featured={work} isAdmin={isAdmin} onOpen={() => void openProject(project)} onDelete={() => confirmDelete(project)} onPublish={() => openFeaturedModal(project)} onUnpublish={() => { if (work) confirmUnpublish(work) }} />
          })}</div> : !loadError && <Empty className="dh-project-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? "没有找到相关短剧" : "还没有短剧，先和助手聊聊你的想法"}>{!query && <Button onClick={() => void openCreatePicker()}>新建短剧</Button>}</Empty>}
        </>}
      </section>
      {showFeatured && <section className="dh-projects dh-featured-section" aria-labelledby="featured-works-heading">
        <div className="dh-projects-heading">
          <h2 id="featured-works-heading">精选作品</h2>
          <span className="dh-featured-note">{featuredWorks.length ? `${featuredWorks.length} 部 · 管理员发布` : "管理员发布后全员可见"}</span>
        </div>
        {featuredQuery.isLoading && !featuredWorks.length
          ? <div className="dh-project-grid" aria-label="正在加载精选作品" aria-busy="true">{Array.from({ length: columns }, (_, index) => <div className="dh-project-skeleton" key={index}><Skeleton.Node active className="dh-project-cover" /><Skeleton active paragraph={{ rows: 1, width: "40%" }} title={{ width: "60%" }} /></div>)}</div>
          : featuredWorks.length
            ? <div className="dh-project-grid">{featuredWorks.map(work => <FeaturedCard key={work.id} work={work} isAdmin={isAdmin} onOpen={() => setPreviewWorkId(work.id)} onUnpublish={() => confirmUnpublish(work)} />)}</div>
            : <Empty className="dh-project-empty dh-featured-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有精选作品" />}
      </section>}
      {previewWorkId && <FeaturedWorkPreview featuredId={previewWorkId} onClose={() => setPreviewWorkId(null)} />}
    </div>
    <SkillPackPickerModal open={packPickerOpen} packs={skillPacks} loading={packsLoading} value={selectedPackId} confirming={creatingProject} onChange={setSelectedPackId} onCancel={() => { if (!creatingProject) setPackPickerOpen(false) }} onOk={packId => void createStudioProject(packId)} />
    <Drawer title="创作工具与历史" rootClassName="director-tools-drawer" open={toolsOpen} onClose={() => setToolsOpen(false)} size={960} destroyOnHidden><div className="director-agent-home dh-tools-surface">{assistant.surface}</div></Drawer>
    <Modal
      open={!!featuredDraft}
      title={featuredDraft?.work ? "更新精选作品" : "发布为精选作品"}
      okText={featuredDraft?.work ? "保存更新" : "发布精选"}
      cancelText="取消"
      confirmLoading={publishingFeatured}
      onCancel={() => { if (!publishingFeatured) setFeaturedDraft(null) }}
      onOk={() => void submitFeatured()}
      destroyOnHidden
    >
      {featuredDraft && <div className="dh-featured-form">
        <div className="dh-featured-source">
          <div className="dh-featured-source-cover">{featuredDraft.project.cover_url ? <img src={featuredDraft.project.cover_url} alt="" /> : <Clapperboard size={18} />}</div>
          <div>
            <strong>{featuredDraft.project.name}</strong>
            <span>{featuredDraft.work ? "已发布，保存后将用当前内容重新生成快照" : "发布后所有成员可在首页查看"}</span>
          </div>
        </div>
        <label>
          <span>精选标题</span>
          <Input maxLength={120} value={featuredDraft.title} placeholder="展示在精选作品里的标题" onChange={event => setFeaturedDraft(current => current && { ...current, title: event.target.value })} />
        </label>
        <label>
          <span>一句话简介</span>
          <Input.TextArea rows={3} maxLength={280} showCount value={featuredDraft.summary} placeholder="留空时使用短剧简介，也可以写更吸引人的推荐语" onChange={event => setFeaturedDraft(current => current && { ...current, summary: event.target.value })} />
        </label>
        <label>
          <span>封面地址</span>
          <Input value={featuredDraft.coverUrl} placeholder="留空时自动取项目封面或首个角色、场景图" onChange={event => setFeaturedDraft(current => current && { ...current, coverUrl: event.target.value })} />
        </label>
        <label>
          <span>排序（数字越小越靠前）</span>
          <InputNumber min={0} max={999} precision={0} value={featuredDraft.sortOrder} onChange={value => setFeaturedDraft(current => current && { ...current, sortOrder: typeof value === "number" ? value : current.sortOrder })} />
        </label>
        <Alert type="info" showIcon title="发布会把当前剧本、分集和角色场景冻结成只读快照；之后修改短剧不影响已发布内容，需要同步时再次点击发布即可。" />
      </div>}
    </Modal>
    {modalContext}
  </div>
}
