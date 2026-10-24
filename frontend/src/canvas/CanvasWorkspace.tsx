import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, ConfigProvider, Empty, Input, Modal, Popconfirm, Segmented, Select, Spin, Tag, message, type ThemeConfig } from "antd"
import zhCN from "antd/locale/zh_CN"
import { ArrowRight, CopyPlus, Frame, Plus, RefreshCw, RotateCcw, Search, Star, Tags, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { canvasProjectPath, PATHS } from "../paths"
import { useStudioTheme } from "../ThemeProvider"
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
import "./canvas.css"
import "./canvas-fidelity.css"

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
  return (
    <ConfigProvider theme={{ ...canvasTheme, token: { ...canvasTheme.token, colorPrimary: mode === "light" ? "#4554ff" : "#6977f5" } }} locale={zhCN} button={{ autoInsertSpace: false }}>
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
      return <div className="canvas-loading"><Spin size="large" /><span>正在加载画布…</span></div>
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
  const isTrash = view === "trash"
  const projectsQuery = useQuery({
    queryKey: ["canvas-projects", isTrash],
    queryFn: () => listCanvasProjects(isTrash),
  })
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
  const [savingTags, setSavingTags] = useState(false)
  const projects = projectsQuery.data ?? []
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

  return (
    <div className="canvas-list-page">
      <div className="canvas-list-heading">
        <div>
          <h1><Frame size={22} />无限画布</h1>
          <p>从文字、参考图出发连续生成图片与视频，结果留在同一张画布上继续分支创作。</p>
        </div>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>新建画布</Button>
      </div>

      <Segmented
        className="canvas-list-views"
        value={view}
        onChange={(value) => switchView(value as CanvasListView)}
        options={[
          { label: "全部", value: "active" },
          { label: "收藏", value: "favorites" },
          { label: "回收站", value: "trash" },
        ]}
      />

      {projectsQuery.isLoading ? (
        <div className="canvas-loading"><Spin /><span>正在加载画布列表…</span></div>
      ) : projectsQuery.isError ? (
        <Empty description={errorText(projectsQuery.error)}>
          <Button icon={<RefreshCw size={15} />} onClick={() => { projectsQuery.refetch().catch(() => undefined) }}>重试</Button>
        </Empty>
      ) : !projects.length ? (
        renderEmpty()
      ) : (
        <>
          <div className="canvas-list-toolbar">
            <Input
              className="canvas-list-search"
              allowClear
              prefix={<Search size={15} />}
              value={search}
              placeholder="搜索标题或标签"
              aria-label="搜索画布"
              onChange={(event) => setSearch(event.target.value)}
            />
            {!isTrash && tagOptions.length ? (
              <Select
                classNames={{ popup: { root: "canvas-select-popup" } }}
                className="canvas-list-tag-filter"
                allowClear
                value={tagFilter ?? undefined}
                placeholder="按标签筛选"
                aria-label="按标签筛选"
                suffixIcon={<Tags size={14} />}
                options={tagOptions.map((tag) => ({ label: tag, value: tag }))}
                onChange={(value) => setTagFilter(value ?? null)}
              />
            ) : null}
            <Select
              classNames={{ popup: { root: "canvas-select-popup" } }}
              className="canvas-list-sort"
              value={sort}
              aria-label="画布排序"
              onChange={(value) => setSort(value)}
              options={[
                { label: "最近更新", value: "updated_desc" },
                { label: "最近创建", value: "created_desc" },
                { label: "标题 A–Z", value: "title_asc" },
              ]}
            />
          </div>
          {!visibleProjects.length ? (
            <div className="canvas-empty">
              <Empty description={view === "favorites" && !search.trim() && !tagFilter ? "还没有收藏的画布，点击画布右上角的星标即可收藏" : "没有匹配的画布"} />
              {view === "favorites" && !search.trim() && !tagFilter
                ? <Button onClick={() => switchView("active")}>查看全部画布</Button>
                : <Button onClick={clearFilters}>清除筛选</Button>}
            </div>
          ) : (
            <div className="canvas-project-grid">
              {visibleProjects.map((project) => {
                const favorite = Boolean(project.is_favorite)
                const preview = project.preview?.items.length ? project.preview : null
                return (
                  <article
                    key={project.id}
                    className={[
                      "canvas-project-card",
                      favorite ? "is-favorite" : "",
                      isTrash ? "is-trash" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    <button
                      type="button"
                      className="canvas-project-open"
                      disabled={isTrash}
                      onClick={() => navigate(canvasProjectPath(project.id))}
                    >
                      <span
                        className={`canvas-project-preview${preview ? " has-preview" : ""}`}
                        aria-hidden="true"
                      >
                        {preview
                          ? <CanvasPreviewThumbnail preview={preview} />
                          : <Frame size={30} />}
                      </span>
                      <span className="canvas-project-meta">
                        <strong>{project.title}</strong>
                        {project.tags?.length ? (
                          <span className="canvas-project-tags">
                            {project.tags.map((tag) => (
                              <Tag key={tag} variant="filled">{tag}</Tag>
                            ))}
                          </span>
                        ) : null}
                        <span className="canvas-project-stats">
                          <Tag variant="filled">{project.node_count ?? 0} 个节点</Tag>
                          <Tag variant="filled">v{project.draft_version ?? 1}</Tag>
                        </span>
                        <small>
                          {isTrash
                            ? `删除于 ${formatCanvasTime(project.deleted_at)}`
                            : `最近保存 ${formatCanvasTime(project.draft_updated_at ?? project.updated_at)}`}
                        </small>
                      </span>
                      {!isTrash ? <ArrowRight size={16} className="canvas-project-arrow" /> : null}
                    </button>

                    {!isTrash ? (
                      <Button
                        type="text"
                        className={`canvas-project-favorite${favorite ? " is-active" : ""}`}
                        title={favorite ? "取消收藏" : "收藏画布"}
                        aria-label={favorite ? `取消收藏 ${project.title}` : `收藏画布 ${project.title}`}
                        loading={updatingId === project.id}
                        icon={<Star size={15} fill={favorite ? "currentColor" : "none"} />}
                        onClick={() => { void toggleFavorite(project) }}
                      />
                    ) : null}

                    <div className="canvas-project-actions">
                      {isTrash ? (
                        <>
                          <Button
                            type="text"
                            title="恢复画布"
                            loading={updatingId === project.id}
                            icon={<RotateCcw size={15} />}
                            aria-label={`恢复画布 ${project.title}`}
                            onClick={() => { void restoreProject(project.id) }}
                          />
                          <Popconfirm
                            classNames={{ root: "canvas-popover canvas-confirm-popover" }}
                            title="彻底删除这张画布？"
                            description="画布内容和历史版本会永久删除，无法恢复。"
                            okText="彻底删除"
                            okButtonProps={{ danger: true }}
                            cancelText="取消"
                            onConfirm={() => { void removeProject(project.id) }}
                          >
                            <Button
                              type="text"
                              danger
                              loading={deletingId === project.id}
                              icon={<Trash2 size={15} />}
                              aria-label={`彻底删除画布 ${project.title}`}
                            />
                          </Popconfirm>
                        </>
                      ) : (
                        <>
                          <Button
                            type="text"
                            title="编辑标签"
                            icon={<Tags size={15} />}
                            aria-label={`编辑画布标签 ${project.title}`}
                            onClick={() => openTagEditor(project)}
                          />
                          <Button
                            type="text"
                            title="复制画布"
                            loading={duplicatingId === project.id}
                            icon={<CopyPlus size={15} />}
                            aria-label={`复制画布 ${project.title}`}
                            onClick={() => { void duplicateProject(project.id) }}
                          />
                          <Popconfirm
                            classNames={{ root: "canvas-popover canvas-confirm-popover" }}
                            title="移入回收站？"
                            description="画布会保留在回收站，可随时恢复。"
                            okText="移入回收站"
                            cancelText="取消"
                            onConfirm={() => { void moveToTrash(project.id) }}
                          >
                            <Button
                              type="text"
                              danger
                              loading={deletingId === project.id}
                              icon={<Trash2 size={15} />}
                              aria-label={`移入回收站 ${project.title}`}
                            />
                          </Popconfirm>
                        </>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </>
      )}

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
          value={tagDraft}
          maxCount={CANVAS_MAX_TAGS}
          maxTagTextLength={CANVAS_MAX_TAG_LENGTH}
          tokenSeparators={[",", "，"]}
          placeholder={`输入标签后回车，最多 ${CANVAS_MAX_TAGS} 个`}
          options={tagOptions.map((tag) => ({ label: tag, value: tag }))}
          onChange={(values) => setTagDraft(values)}
        />
        <p className="canvas-tag-editor-hint">
          标签用于筛选画布；单个标签最多 {CANVAS_MAX_TAG_LENGTH} 个字符，最多 {CANVAS_MAX_TAGS} 个。
        </p>
      </Modal>
    </div>
  )
}
