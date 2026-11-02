// 项目详情壳：顶部项目条 + 左侧 4 菜单 + 右侧面板 —— 逐行复刻自 dev0914 ProjectDetailView.vue
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Button, Form, Input, Modal, Select, message } from "antd"
import { Boxes, ChevronLeft, FileText, Film, ListChecks, Pencil, Scissors } from "lucide-react"
import { getProject, listSkillPacks, updateProject, director2ErrorDetail, type Director2Project, type Director2SkillPack } from "./api"
import ContentLibraryPane from "./panes/ContentLibraryPane"
import AssetsLibraryPane from "./panes/AssetsLibraryPane"
import EpisodeWorkshopPane from "./panes/EpisodeWorkshopPane"
import JobsCenterPane from "./panes/JobsCenterPane"
import SmartEditPane from "./smart-edit/SmartEditPane"
import { director2ProjectPath, director2HomePath, director2MenuEpisodeId, type Director2Route } from "./paths"
import Director2AiStudioPane from "./panes/Director2AiStudioPane"
import { useDirectorAssistant } from "./assistant/DirectorAssistant"
import { parseDirector2CreationMode, readDirector2CreationMode, storeDirector2CreationMode, type Director2CreationMode } from "./creation-mode"
import DirectorCreationModeSwitch from "../director/components/DirectorCreationModeSwitch"
import { MediaPreviewProvider } from "./media-preview"
import {
  packIdFromSelectValue,
  projectBoundSkillPackId,
  selectValueForPackId,
  skillPackSelectOptions,
} from "./skill-pack"
import "./project-detail.css"

const MENU_ITEMS = [
  { key: "content", label: "内容库", Icon: FileText },
  { key: "assets", label: "资产库", Icon: Boxes },
  { key: "workshop", label: "剧集工坊", Icon: Film },
  { key: "edit", label: "智能剪辑", Icon: Scissors },
  { key: "jobs", label: "全部任务", Icon: ListChecks },
] as const

export default function Director2ProjectDetail({
  csrfToken,
  route,
}: {
  csrfToken: string
  route: Extract<Director2Route, { kind: "project" }>
}) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const projectId = route.projectId
  const assistant = useDirectorAssistant()

  const [project, setProject] = useState<Director2Project | null>(null)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [savingPack, setSavingPack] = useState(false)
  const [editingInfo, setEditingInfo] = useState(false)
  const [savingInfo, setSavingInfo] = useState(false)
  const [infoForm] = Form.useForm<{ name: string; description: string }>()
  const infoSnapshotRef = useRef({ name: "", description: "" })
  // 剧集工坊分集详情：外壳锁死视口，左右栏各自滚动
  const [inWorkshopDetail, setInWorkshopDetail] = useState(false)
  // 本项目里最近打开的分集：工坊与智能剪辑切换时延续这个上下文
  const [lastEpisode, setLastEpisode] = useState<{ projectId: string; episodeId: string } | null>(null)
  const [creationMode, setCreationMode] = useState<Director2CreationMode>(() => parseDirector2CreationMode(searchParams.get("mode")) ?? readDirector2CreationMode(projectId))
  const [aiBusy, setAiBusy] = useState(false)

  const assetsPaneRef = useRef<{ fetchAssets: () => Promise<void> | void } | null>(null)
  const workshopPaneRef = useRef<{ fetchEpisodes: () => Promise<void> | void } | null>(null)

  const activeMenu = route.menu
  const isWorkshopDetail = activeMenu === "workshop" && (!!route.episodeId || inWorkshopDetail)

  useEffect(() => {
    if (route.episodeId) setLastEpisode({ projectId, episodeId: route.episodeId })
    // 停在自由剪辑，说明用户显式放下了分集上下文
    else if (route.menu === "edit") setLastEpisode(null)
  }, [projectId, route.episodeId, route.menu])

  function handleMenuClick(key: string) {
    const episodeId = director2MenuEpisodeId({
      targetMenu: key,
      currentMenu: activeMenu,
      currentEpisodeId: route.episodeId,
      lastEpisodeId: lastEpisode?.projectId === projectId ? lastEpisode.episodeId : null,
    })
    navigate(director2ProjectPath(projectId, key, episodeId))
    if (key !== "workshop") setInWorkshopDetail(false)
  }

  const loadProjectInfo = useCallback(async () => {
    try {
      const data = await getProject(projectId)
      setProject(data)
    } catch (err) {
      message.error(director2ErrorDetail(err, "未找到该项目"))
      navigate(director2HomePath())
    }
  }, [projectId, navigate])

  useEffect(() => {
    loadProjectInfo()
  }, [loadProjectInfo])

  useEffect(() => {
    let cancelled = false
    listSkillPacks()
      .then((res) => { if (!cancelled) setSkillPacks(res.packs || []) })
      .catch((error) => { if (!cancelled) message.error(director2ErrorDetail(error, "加载制作配方失败")) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const fromUrl = parseDirector2CreationMode(searchParams.get("mode"))
    if (fromUrl) setCreationMode(fromUrl)
  }, [searchParams])

  useEffect(() => {
    if (assistant.enabled) assistant.setOpen(activeMenu === "edit" || creationMode === "agent")
  }, [assistant.enabled, assistant.setOpen, creationMode, projectId, activeMenu])

  useEffect(() => {
    function syncMode(event: Event) {
      const value = (event as CustomEvent).detail as Director2CreationMode
      setCreationMode(value)
      storeDirector2CreationMode(projectId, value)
      setSearchParams(current => { current.set("mode", value); return current }, { replace: true })
    }
    function refreshProject(event: Event) {
      if ((event as CustomEvent).detail.projectId !== projectId) return
      void loadProjectInfo()
      assetsPaneRef.current?.fetchAssets()
      workshopPaneRef.current?.fetchEpisodes()
    }
    window.addEventListener("director-assistant-mode", syncMode)
    window.addEventListener("director-assistant-project-updated", refreshProject)
    return () => {
      window.removeEventListener("director-assistant-mode", syncMode)
      window.removeEventListener("director-assistant-project-updated", refreshProject)
    }
  }, [projectId, setSearchParams, loadProjectInfo])

  async function changeSkillPack(selectValue: string) {
    if (savingPack || aiBusy) return
    const packId = packIdFromSelectValue(selectValue)
    if (packId === projectBoundSkillPackId(project)) return
    setSavingPack(true)
    try {
      const updated = await updateProject(csrfToken, projectId, { extra: { skill_pack_id: packId } })
      setProject(updated)
      message.success(packId ? "已切换制作配方" : "已取消配方绑定")
    } catch (error) {
      message.error(director2ErrorDetail(error, "更新制作配方失败"))
    } finally {
      setSavingPack(false)
    }
  }

  function changeCreationMode(value: Director2CreationMode) {
    if (aiBusy) return
    setCreationMode(value)
    storeDirector2CreationMode(projectId, value)
    setSearchParams((current) => {
      current.set("mode", value)
      return current
    }, { replace: true })
  }

  function editProjectInfo() {
    if (!project) return
    infoForm.resetFields()
    infoSnapshotRef.current = { name: project.name, description: project.description || "" }
    infoForm.setFieldsValue(infoSnapshotRef.current)
    setEditingInfo(true)
  }

  async function saveProjectInfo(values: { name: string; description: string }) {
    if (savingInfo || !project) return
    const changes: { name?: string; description?: string } = {}
    if (values.name.trim() !== infoSnapshotRef.current.name) changes.name = values.name.trim()
    if (values.description.trim() !== infoSnapshotRef.current.description) changes.description = values.description.trim()
    if (!Object.keys(changes).length) {
      setEditingInfo(false)
      return
    }
    setSavingInfo(true)
    try {
      const updated = await updateProject(csrfToken, projectId, changes)
      setProject(updated)
      setEditingInfo(false)
      message.success("已保存基本信息")
    } catch (error) {
      message.error(director2ErrorDetail(error, "保存基本信息失败，请重试"))
    } finally {
      setSavingInfo(false)
    }
  }

  function onAssetsTransferred() {
    assetsPaneRef.current?.fetchAssets()
  }

  function onEpisodesTransferred() {
    workshopPaneRef.current?.fetchEpisodes()
  }

  return (
    <MediaPreviewProvider>
      <div className={`project-detail-layout${activeMenu === "edit" ? " has-smart-edit" : ""}`}>
      {/* 顶部项目条 */}
      <header className="project-topbar">
        <div className="topbar-content">
          <div className="topbar-left">
            <a
              className="back-link"
              href={director2HomePath()}
              onClick={(event) => {
                event.preventDefault()
                navigate(director2HomePath())
              }}
            >
              <ChevronLeft size={18} />
              <span>导演台</span>
            </a>
            <div className="divider" />
            <div className="project-info">
              <h1 className="project-title" title={project?.name}>{project?.name || "加载中..."}</h1>
              <Button type="text" size="small" aria-label="编辑基本信息" title="编辑基本信息" icon={<Pencil size={14} />} disabled={!project} onClick={editProjectInfo}>
                {activeMenu !== "edit" && "编辑基本信息"}
              </Button>
            </div>
          </div>

          <div className="topbar-right">
            <div className="project-skill-pack-field"><span>制作配方</span><Select
              className="project-skill-pack-select"
              aria-label="制作配方"
              popupMatchSelectWidth={false}
              value={selectValueForPackId(projectBoundSkillPackId(project))}
              options={skillPackSelectOptions(skillPacks)}
              loading={savingPack}
              disabled={aiBusy || savingPack || skillPacks.length === 0}
              onChange={(value) => { void changeSkillPack(String(value)) }}
            /></div>
            <DirectorCreationModeSwitch
              value={creationMode}
              disabled={aiBusy}
              onChange={(value) => changeCreationMode(value as Director2CreationMode)}
            />
          </div>
        </div>
      </header>

      <Modal
        title="编辑基本信息"
        forceRender
        open={editingInfo}
        okText="保存"
        cancelText="取消"
        confirmLoading={savingInfo}
        onOk={() => infoForm.submit()}
        onCancel={() => { if (!savingInfo) setEditingInfo(false) }}
        closable={!savingInfo}
        mask={{ closable: !savingInfo }}
        cancelButtonProps={{ disabled: savingInfo }}
      >
        <Form form={infoForm} layout="vertical" onFinish={saveProjectInfo} disabled={savingInfo}>
          <Form.Item name="name" label="剧本名称" extra="同时作为工程名称显示；手动保存后，AI 不会覆盖。" rules={[{ required: true, whitespace: true, message: "请输入剧本名称" }, { max: 255, message: "剧本名称最多 255 个字符" }]}>
            <Input placeholder="给这部剧起一个名字" maxLength={255} autoFocus />
          </Form.Item>
          <Form.Item name="description" label="剧本简介">
            <Input.TextArea placeholder="简要介绍故事内容、主角和创作方向" autoSize={{ minRows: 4, maxRows: 8 }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 主体区域：左侧菜单 + 右侧工作区 */}
      <div className="project-main-body">
        {/* 左侧 4 个菜单导航 */}
        <aside className={`project-sidebar${creationMode === "agent" && assistant.ready && !assistant.enabled ? " is-hidden" : ""}`}>
          <nav className="menu-list" aria-label="工程导航">
            {MENU_ITEMS.map(({ key, label, Icon }) => (
              <button
                type="button"
                key={key}
                className={`sidebar-menu-item${activeMenu === key ? " active" : ""}`}
                title={label}
                aria-current={activeMenu === key ? "page" : undefined}
                onClick={() => handleMenuClick(key)}
              >
                <Icon size={18} className="menu-icon" />
                <span className="menu-text">{label}</span>
              </button>
            ))}
          </nav>
        </aside>

        {/* 右侧子模块内容区 */}
        <section className={`project-content-pane${isWorkshopDetail ? " is-workshop-detail" : ""}${activeMenu === "workshop" && !isWorkshopDetail ? " is-workshop-overview" : ""}${activeMenu === "edit" ? " is-smart-edit" : ""}`}>
          {creationMode === "agent" && assistant.ready && !assistant.enabled && activeMenu !== "edit" && (
            <div key="ai" className="d2-fade">
              <Director2AiStudioPane
                csrfToken={csrfToken}
                projectId={projectId}
                onBusyChange={setAiBusy}
                onProjectInfoChange={loadProjectInfo}
                onNavigate={(menu) => {
                  changeCreationMode("manual")
                  handleMenuClick(menu)
                }}
              />
            </div>
          )}
          {(creationMode === "manual" || assistant.enabled || !assistant.ready) && activeMenu === "content" && (
            <div key="content" className="d2-fade">
              <ContentLibraryPane
                csrfToken={csrfToken}
                projectId={projectId}
                onAssetsTransferred={onAssetsTransferred}
                onEpisodesTransferred={onEpisodesTransferred}
              />
            </div>
          )}
          {(creationMode === "manual" || assistant.enabled || !assistant.ready) && activeMenu === "assets" && (
            <div key="assets" className="d2-fade">
              <AssetsLibraryPane ref={assetsPaneRef} csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
          {(creationMode === "manual" || assistant.enabled || !assistant.ready) && activeMenu === "workshop" && (
            <div key="workshop" className="d2-fade d2-workshop-host">
              <EpisodeWorkshopPane
                ref={workshopPaneRef}
                csrfToken={csrfToken}
                projectId={projectId}
                episodeId={route.episodeId}
                onDetailModeChange={setInWorkshopDetail}
              />
            </div>
          )}
          {(creationMode === "manual" || assistant.enabled || !assistant.ready) && activeMenu === "jobs" && (
            <div key="jobs" className="d2-fade">
              <JobsCenterPane csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
          {activeMenu === "edit" && <SmartEditPane csrfToken={csrfToken} projectId={projectId} episodeId={route.episodeId} />}
        </section>
      </div>
      </div>
    </MediaPreviewProvider>
  )
}
