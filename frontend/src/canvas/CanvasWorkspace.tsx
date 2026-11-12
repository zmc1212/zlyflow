import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, ConfigProvider, Dropdown, Empty, Input, Modal, Select, Spin, Tabs, Tag, Tooltip, message, type ThemeConfig } from "antd"
import zhCN from "antd/locale/zh_CN"
import { ArrowRight, CopyPlus, Frame, History, MoreHorizontal, Network, Plus, RefreshCw, RotateCcw, Search, Star, Tags, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"
import { canvasProjectPath, PATHS } from "../paths"
import { useStudioTheme } from "../ThemeProvider"
import { searchFilterOption } from "../search-match"
import {
  createCanvasProject,
  deleteCanvasProject,
  duplicateCanvasProject,
  getCanvasProject,
  listCanvasProjects,
  restoreCanvasProject,
  trashCanvasProject,
  updateCanvasProject,
} from "./canvas-api"
import {
  CANVAS_MAX_TAG_LENGTH,
  CANVAS_MAX_TAGS,
  collectCanvasTags,
  filterCanvasProjects,
  normalizeCanvasTags,
  type CanvasProjectSort,
} from "./canvas-manage"
import { formatCanvasTime, type CanvasProject } from "./canvas-model"
import CanvasEditor from "./CanvasEditor"
import CanvasPreviewThumbnail from "./CanvasPreviewThumbnail"
import CanvasCreateGraphic from "./CanvasCreateGraphic"
import { canvasSavedTime, recentCanvasProject } from "./canvas-home"
import "./canvas.css"
import "./canvas-fidelity.css"
import "./canvas-home.css"
// 共享节点样式层：放在各画布 CSS 之后，改一次两个画布同时生效
import "./canvas-node-shared.css"
import "./canvas-chrome-shared.css"

type CanvasListView = "active" | "favorites" | "trash"

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败"
}

function projectIdFromPath(pathname: string): string | null {
  const match = /^\/canvas\/([^/]+)\/?$/.exec(pathname)
  if (!match) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return null
  }
}

const canvasTheme: ThemeConfig = {
  token: { controlHeight: 34, fontSize: 13, borderRadius: 8, fontFamily: '"Microsoft YaHei", "Segoe UI", sans-serif' },
  components: {
    Button: { controlHeightSM: 28, fontSizeSM: 12 },
    Dropdown: { borderRadiusLG: 12, paddingBlock: 6 },
    Menu: { itemHeight: 36, itemBorderRadius: 8 },
    Modal: { borderRadiusLG: 16 },
    Popover: { borderRadiusLG: 12 },
    Tooltip: { fontSize: 12 },
    Tabs: { horizontalItemGutter: 8 },
  },
}

export default function CanvasWorkspace({ csrfToken }: { csrfToken: string }) {
  const { mode } = useStudioTheme()
  const isHome = /^\/canvas\/?$/.test(useLocation().pathname)
  return (
    <ConfigProvider theme={{ ...canvasTheme, token: { ...canvasTheme.token, fontSize: isHome ? 14 : 13, colorPrimary: isHome ? (mode === "light" ? "#435ce8" : "#5b65e6") : (mode === "light" ? "#4554ff" : "#6977f5") } }} locale={zhCN} button={{ autoInsertSpace: false }}>
      <CanvasWorkspaceContent csrfToken={csrfToken} />
    </ConfigProvider>
  )
}

function CanvasWorkspaceContent({ csrfToken }: { csrfToken: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const projectId = projectIdFromPath(location.pathname)

  const projectQuery = useQuery({
    queryKey: ["canvas-project", projectId],
    queryFn: () => getCanvasProject(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
    // The editor owns the current draft and version; reconnect must not replace it.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnReconnect: false,
  })

  if (projectId) {
    if (projectQuery.isLoading) {
      return (
        <div className="canvas-loading-skeleton" role="status" aria-busy="true" aria-label="正在加载画布">
          <div className="canvas-skeleton-topbar" aria-hidden="true">
            <span className="studio-skeleton-bar" style={{ width: 140 }} />
            <span className="studio-skeleton-bar" style={{ width: 220 }} />
            <span className="studio-skeleton-bar" style={{ width: 96 }} />
          </div>
          <div className="canvas-skeleton-board" aria-hidden="true">
            <span className="studio-skeleton-bar canvas-skeleton-node" style={{ left: "10%", top: "16%", width: 180, height: 120 }} />
            <span className="studio-skeleton-bar canvas-skeleton-node" style={{ left: "36%", top: "34%", width: 230, height: 150 }} />
            <span className="studio-skeleton-bar canvas-skeleton-node" style={{ left: "66%", top: "14%", width: 170, height: 110 }} />
            <span className="studio-skeleton-bar canvas-skeleton-node" style={{ left: "22%", top: "60%", width: 210, height: 130 }} />
            <span className="studio-skeleton-bar canvas-skeleton-node" style={{ left: "58%", top: "62%", width: 150, height: 100 }} />
          </div>
          <p className="canvas-skeleton-status"><Spin size="small" /><span>正在加载画布…</span></p>
        </div>
      )
    }
    if (projectQuery.isError || !projectQuery.data) {
      return (
        <div className="canvas-loading">
          <Empty description={errorText(projectQuery.error)} />
          <Button onClick={() => { projectQuery.refetch().catch(() => undefined) }} icon={<RefreshCw size={15} />}>重试</Button>
          <Button type="link" onClick={() => navigate(PATHS.canvas)}>返回画布列表</Button>
        </div>
      )
    }
    if (projectQuery.data.linked_director_project_id) return <Navigate to={`/director/projects/${encodeURIComponent(projectQuery.data.linked_director_project_id)}/assets?view=canvas`} replace/>
    return (
      <CanvasEditor
        key={projectQuery.data.id}
        project={projectQuery.data}
        csrfToken={csrfToken}
        onBack={() => {
          navigate(PATHS.canvas)
        }}
      />
    )
  }

  return <CanvasProjectList csrfToken={csrfToken} />
}

function CanvasProjectList({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [view, setView] = useState<CanvasListView>("active")
  const [modal, modalContext] = Modal.useModal()
  const isTrash = view === "trash"
  const activeProjectsQuery = useQuery({
    queryKey: ["canvas-projects", false],
    queryFn: () => listCanvasProjects(),
  })
  const trashProjectsQuery = useQuery({
    queryKey: ["canvas-projects", true],
    queryFn: () => listCanvasProjects(true),
    enabled: isTrash,
  })
  const projectsQuery = isTrash ? trashProjectsQuery : activeProjectsQuery
  const [createOpen, setCreateOpen] = useState(false)
  const [newTitle, setNewTitle] = useState("")
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null)
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<CanvasProjectSort>("updated_desc")
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [tagEditing, setTagEditing] = useState<CanvasProject | null>(null)
  const [tagDraft, setTagDraft] = useState<string[]>([])
  const [tagSuggestionsOpen, setTagSuggestionsOpen] = useState(false)
  const [savingTags, setSavingTags] = useState(false)
  const projects = projectsQuery.data ?? []
  const recent = useMemo(() => recentCanvasProject(activeProjectsQuery.data ?? []), [activeProjectsQuery.data])
  const tagOptions = useMemo(() => collectCanvasTags(projects), [projects])
  const visibleProjects = useMemo(
    () => filterCanvasProjects(projects, search, sort, {
      favoriteOnly: view === "favorites",
      tag: isTrash ? null : tagFilter,
    }),
    [projects, search, sort, view, tagFilter, isTrash],
  )

  const refreshProjects = () => queryClient.invalidateQueries({ queryKey: ["canvas-projects"] })

  const createProject = async () => {
    if (creating) return
    setCreating(true)
    try {
      const created = await createCanvasProject(csrfToken, newTitle.trim() || "未命名画布")
      setCreateOpen(false)
      setNewTitle("")
      await refreshProjects()
      navigate(canvasProjectPath(created.id))
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setCreating(false)
    }
  }

  const moveToTrash = async (projectId: string) => {
    setDeletingId(projectId)
    try {
      await trashCanvasProject(csrfToken, projectId)
      await refreshProjects()
      message.success("已移入回收站")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setDeletingId(null)
    }
  }

  const restoreProject = async (projectId: string) => {
    setUpdatingId(projectId)
    try {
      await restoreCanvasProject(csrfToken, projectId)
      await refreshProjects()
      message.success("画布已恢复")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setUpdatingId(null)
    }
  }

  const removeProject = async (projectId: string) => {
    setDeletingId(projectId)
    try {
      await deleteCanvasProject(csrfToken, projectId)
      await refreshProjects()
      message.success("画布已彻底删除")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setDeletingId(null)
    }
  }

  const toggleFavorite = async (project: CanvasProject) => {
    setUpdatingId(project.id)
    try {
      await updateCanvasProject(csrfToken, project.id, { is_favorite: !project.is_favorite })
      await refreshProjects()
      message.success(project.is_favorite ? "已取消收藏" : "已收藏画布")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setUpdatingId(null)
    }
  }

  const duplicateProject = async (projectId: string) => {
    setDuplicatingId(projectId)
    try {
      const created = await duplicateCanvasProject(csrfToken, projectId)
      await refreshProjects()
      message.success("画布已复制")
      navigate(canvasProjectPath(created.id))
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setDuplicatingId(null)
    }
  }

  const openTagEditor = (project: CanvasProject) => {
    setTagEditing(project)
    setTagDraft(project.tags ?? [])
    setTagSuggestionsOpen(false)
  }

  const saveTags = async () => {
    if (!tagEditing) return
    const normalized = normalizeCanvasTags(tagDraft)
    if (normalized.error) {
      message.warning(normalized.error)
      return
    }
    setSavingTags(true)
    try {
      await updateCanvasProject(csrfToken, tagEditing.id, { tags: normalized.tags })
      setTagEditing(null)
      await refreshProjects()
      message.success("标签已更新")
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setSavingTags(false)
    }
  }

  const switchView = (next: CanvasListView) => {
    setView(next)
    setTagFilter(null)
  }

  const clearFilters = () => {
    setSearch("")
    setTagFilter(null)
  }

  const renderEmpty = () => {
    if (isTrash) {
      return (
        <div className="canvas-empty">
          <Empty description="回收站为空" />
          <Button onClick={() => switchView("active")}>返回全部画布</Button>
        </div>
      )
    }
    if (view === "favorites") {
      return (
        <div className="canvas-empty">
          <Empty description="还没有收藏的画布，点击画布右上角的星标即可收藏" />
          <Button onClick={() => switchView("active")}>查看全部画布</Button>
        </div>
      )
    }
    return (
      <div className="canvas-empty">
        <Empty description="还没有画布，从第一张无限画布开始吧" />
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>创建画布</Button>
      </div>
    )
  }

  const confirmTrash = (project: CanvasProject) => {
    modal.confirm({
      title: "移入回收站？",
      content: `「${project.title}」会保留在回收站，可随时恢复。`,
      okText: "移入回收站",
      cancelText: "取消",
      onOk: () => moveToTrash(project.id),
    })
  }

  const confirmDelete = (project: CanvasProject) => {
    modal.confirm({
      title: "彻底删除这张画布？",
      content: `「${project.title}」的内容和历史版本会永久删除，无法恢复。`,
      okText: "彻底删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => removeProject(project.id),
    })
  }

  return (
    <div className="canvas-list-page canvas-home">
      {modalContext}
      <div className="canvas-home-heading">
        <span className="canvas-home-eyebrow"><Network size={22} aria-hidden="true" />CREATIVE WORKSPACE</span>
        <h1>无限画布</h1>
        <p>从文字、参考图出发，让灵感连接成作品。</p>
      </div>

      <section className={`canvas-home-features${recent && !isTrash ? " has-recent" : ""}`} aria-label="开始画布创作">
        {recent && !isTrash && (
          <article className="canvas-home-recent">
            <div className="canvas-home-recent-info">
              <span className="canvas-home-recent-label"><History size={19} aria-hidden="true" />继续创作</span>
              <Tooltip title={recent.title}><h2>{recent.title}</h2></Tooltip>
              <p>把一个镜头，延展成一个故事</p>
              {recent.tags?.length ? <div className="canvas-home-tags">{recent.tags.slice(0, 2).map((tag) => <Tag key={tag}>{tag}</Tag>)}{recent.tags.length > 2 && <Tooltip title={recent.tags.join("、")}><Tag>+{recent.tags.length - 2}</Tag></Tooltip>}</div> : null}
              <span className="canvas-home-recent-saved">{recent.node_count ?? 0} 个节点<span aria-hidden="true"> · </span><time dateTime={recent.draft_updated_at ?? recent.updated_at} title={formatCanvasTime(recent.draft_updated_at ?? recent.updated_at)}>{canvasSavedTime(recent.draft_updated_at ?? recent.updated_at)}保存</time></span>
              <Button type="primary" className="canvas-home-open-recent" onClick={() => navigate(canvasProjectPath(recent.id))}>打开画布<ArrowRight size={18} aria-hidden="true" /></Button>
            </div>
            <button type="button" className="canvas-home-recent-preview" aria-label={`继续创作 ${recent.title}`} onClick={() => navigate(canvasProjectPath(recent.id))}>
              <CanvasPreviewThumbnail key={recent.id} preview={recent.preview} nodeCount={recent.node_count ?? 0} featured />
            </button>
          </article>
        )}
        <article className="canvas-home-create">
          <CanvasCreateGraphic />
          <div className="canvas-home-create-copy">
            <h2>从一张空白开始</h2>
            <p>连接文字、图片与视频，自由分支创作。</p>
            <Button type="primary" icon={<Plus size={20} />} onClick={() => setCreateOpen(true)}>新建画布</Button>
          </div>
        </article>
      </section>

      <section className="canvas-home-library" aria-labelledby="canvas-home-library-title">
        <div className="canvas-home-library-bar">
          <h2 id="canvas-home-library-title">我的画布</h2>
          <Tabs
            className="canvas-home-tabs"
            activeKey={view}
            onChange={(value) => switchView(value as CanvasListView)}
            items={[
              { key: "active", label: <span>全部画布{activeProjectsQuery.data && <span className="canvas-home-tab-count">{activeProjectsQuery.data.length}</span>}</span> },
              { key: "favorites", label: <span><Star size={16} aria-hidden="true" />已收藏</span> },
              { key: "trash", label: <span><Trash2 size={16} aria-hidden="true" />回收站</span> },
            ]}
          />
          <div className="canvas-home-filters">
            <Input
              allowClear
              prefix={<Search size={17} />}
              value={search}
              placeholder="搜索标题或标签"
              aria-label="搜索画布"
              onChange={(event) => setSearch(event.target.value)}
            />
            {!isTrash && <Select
              classNames={{ popup: { root: "canvas-select-popup" } }}
              allowClear
              disabled={!tagOptions.length}
              value={tagFilter ?? undefined}
              placeholder="全部标签"
              aria-label="按标签筛选"
              showSearch
              filterOption={searchFilterOption}
              options={tagOptions.map((tag) => ({ label: tag, value: tag }))}
              onChange={(value) => setTagFilter(value ?? null)}
            />}
            <Select
              classNames={{ popup: { root: "canvas-select-popup" } }}
              value={sort}
              aria-label="画布排序"
              onChange={setSort}
              options={[
                { label: "最近更新", value: "updated_desc" },
                { label: "最近创建", value: "created_desc" },
                { label: "标题 A–Z", value: "title_asc" },
              ]}
            />
          </div>
        </div>

        {projectsQuery.isLoading ? (
          <div className="canvas-home-state" role="status"><Spin /><span>正在加载画布列表…</span></div>
        ) : projectsQuery.isError ? (
          <div className="canvas-home-state" role="alert"><Empty description={errorText(projectsQuery.error)}><Button icon={<RefreshCw size={15} />} onClick={() => { projectsQuery.refetch().catch(() => undefined) }}>重试</Button></Empty></div>
        ) : !projects.length ? renderEmpty() : !visibleProjects.length ? (
          <div className="canvas-empty">
            <Empty description={view === "favorites" && !search.trim() && !tagFilter ? "还没有收藏的画布，点击画布右上角的星标即可收藏" : "没有匹配的画布"} />
            {view === "favorites" && !search.trim() && !tagFilter
              ? <Button onClick={() => switchView("active")}>查看全部画布</Button>
              : <Button onClick={clearFilters}>清除筛选</Button>}
          </div>
        ) : (
          <div className="canvas-home-grid">
            {visibleProjects.map((project) => {
              const favorite = Boolean(project.is_favorite)
              const busy = updatingId === project.id || deletingId === project.id || duplicatingId === project.id
              const savedAt = isTrash ? project.deleted_at : project.draft_updated_at ?? project.updated_at
              return (
                <article key={project.id} className={`canvas-home-card${isTrash ? " is-trash" : ""}`}>
                  <button type="button" className="canvas-home-card-open" disabled={isTrash} aria-label={`打开画布 ${project.title}`} onClick={() => navigate(canvasProjectPath(project.id))}>
                    <span className="canvas-home-card-preview"><CanvasPreviewThumbnail preview={project.preview} nodeCount={project.node_count ?? 0} /></span>
                    <span className="canvas-home-card-info">
                      <Tooltip title={project.title}><strong>{project.title}</strong></Tooltip>
                      {project.tags?.length ? <span className="canvas-home-tags">{project.tags.slice(0, 2).map((tag) => <Tag key={tag}>{tag}</Tag>)}{project.tags.length > 2 && <Tooltip title={project.tags.join("、")}><Tag>+{project.tags.length - 2}</Tag></Tooltip>}</span> : null}
                      <span className="canvas-home-card-saved">{project.node_count ?? 0} 个节点<span aria-hidden="true"> · </span><time dateTime={savedAt ?? undefined} title={formatCanvasTime(savedAt)}>{isTrash ? "删除于 " : ""}{canvasSavedTime(savedAt)}</time></span>
                    </span>
                  </button>
                  {!isTrash && <Button type="text" className={`canvas-home-favorite${favorite ? " is-active" : ""}`} title={favorite ? "取消收藏" : "收藏画布"} aria-label={`${favorite ? "取消收藏" : "收藏画布"} ${project.title}`} aria-pressed={favorite} loading={updatingId === project.id} disabled={busy && updatingId !== project.id} icon={<Star size={18} fill={favorite ? "currentColor" : "none"} />} onClick={() => { void toggleFavorite(project) }} />}
                  <Dropdown
                    trigger={["click"]}
                    placement="bottomRight"
                    classNames={{ root: "canvas-home-card-menu" }}
                    menu={{
                      items: isTrash ? [
                        { key: "restore", label: "恢复画布", icon: <RotateCcw size={15} /> },
                        { type: "divider" },
                        { key: "delete", label: "彻底删除", icon: <Trash2 size={15} />, danger: true },
                      ] : [
                        { key: "tags", label: "编辑标签", icon: <Tags size={15} /> },
                        { key: "duplicate", label: "复制画布", icon: <CopyPlus size={15} /> },
                        { type: "divider" },
                        { key: "trash", label: "移入回收站", icon: <Trash2 size={15} />, danger: true },
                      ],
                      onClick: ({ key }) => {
                        if (key === "tags") openTagEditor(project)
                        else if (key === "duplicate") void duplicateProject(project.id)
                        else if (key === "trash") confirmTrash(project)
                        else if (key === "restore") void restoreProject(project.id)
                        else if (key === "delete") confirmDelete(project)
                      },
                    }}
                  ><Button type="text" className="canvas-home-more" aria-label={`更多画布操作 ${project.title}`} loading={deletingId === project.id || duplicatingId === project.id} disabled={busy} icon={<MoreHorizontal size={18} />} /></Dropdown>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <Modal
        className="canvas-dialog"
        width={480}
        title="新建画布"
        open={createOpen}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        onOk={() => { void createProject() }}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
      >
        <div className="canvas-dialog-intro"><span className="canvas-dialog-symbol"><Frame size={22} /></span><p>把灵感、参考素材与生成结果放在一起，自由连接你的创作思路。</p></div>
        <label className="canvas-inspector-field-label" htmlFor="canvas-new-title">画布名称</label>
        <Input
          autoFocus
          id="canvas-new-title"
          name="canvas-new-title"
          value={newTitle}
          maxLength={120}
          placeholder="画布标题，例如：第一集分镜草稿"
          onChange={(event) => setNewTitle(event.target.value)}
          onPressEnter={() => { void createProject() }}
        />
        <p className="canvas-dialog-hint">稍后也可以在画布顶部修改名称。</p>
      </Modal>

      <Modal
        className="canvas-dialog"
        width={480}
        title={`编辑标签${tagEditing ? ` · ${tagEditing.title}` : ""}`}
        open={Boolean(tagEditing)}
        okText="保存"
        cancelText="取消"
        confirmLoading={savingTags}
        onOk={() => { void saveTags() }}
        onCancel={() => setTagEditing(null)}
        destroyOnHidden
      >
        <Select
          classNames={{ popup: { root: "canvas-select-popup" } }}
          mode="tags"
          autoFocus
          className="canvas-tag-editor"
          open={tagSuggestionsOpen}
          onOpenChange={setTagSuggestionsOpen}
          listHeight={160}
          value={tagDraft}
          maxCount={CANVAS_MAX_TAGS}
          maxTagTextLength={CANVAS_MAX_TAG_LENGTH}
          tokenSeparators={[",", "，"]}
          placeholder={`输入标签后回车，最多 ${CANVAS_MAX_TAGS} 个`}
          options={tagOptions.map((tag) => ({ label: tag, value: tag }))}
          onChange={(values) => { setTagDraft(values); setTagSuggestionsOpen(false) }}
        />
        <p className="canvas-tag-editor-hint">
          标签用于筛选画布；单个标签最多 {CANVAS_MAX_TAG_LENGTH} 个字符，最多 {CANVAS_MAX_TAGS} 个。
        </p>
      </Modal>
    </div>
  )
}
