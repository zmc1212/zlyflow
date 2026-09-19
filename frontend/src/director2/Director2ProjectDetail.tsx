// 项目详情壳：顶部项目条 + 左侧 4 菜单 + 右侧面板 —— 逐行复刻自 dev0914 ProjectDetailView.vue
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Select, message } from "antd"
import { BookOpen, Boxes, ChevronLeft, Film, ListChecks } from "lucide-react"
import { getProject, listSkillPacks, updateProject, director2ErrorDetail, type Director2Project, type Director2SkillPack } from "./api"
import ContentLibraryPane from "./panes/ContentLibraryPane"
import AssetsLibraryPane from "./panes/AssetsLibraryPane"
import EpisodeWorkshopPane from "./panes/EpisodeWorkshopPane"
import JobsCenterPane from "./panes/JobsCenterPane"
import { director2ProjectPath, director2HomePath, type Director2Route } from "./paths"
import Director2AiStudioPane from "./panes/Director2AiStudioPane"
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
  { key: "content", label: "内容库", Icon: BookOpen },
  { key: "assets", label: "资产库", Icon: Boxes },
  { key: "workshop", label: "剧集工坊", Icon: Film },
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

  const [project, setProject] = useState<Director2Project | null>(null)
  const [skillPacks, setSkillPacks] = useState<Director2SkillPack[]>([])
  const [savingPack, setSavingPack] = useState(false)
  // 剧集工坊分集详情：外壳锁死视口，左右栏各自滚动
  const [inWorkshopDetail, setInWorkshopDetail] = useState(false)
  const [creationMode, setCreationMode] = useState<Director2CreationMode>(() => parseDirector2CreationMode(searchParams.get("mode")) ?? readDirector2CreationMode(projectId))
  const [aiBusy, setAiBusy] = useState(false)

  const assetsPaneRef = useRef<{ fetchAssets: () => Promise<void> | void } | null>(null)
  const workshopPaneRef = useRef<{ fetchEpisodes: () => Promise<void> | void } | null>(null)

  const activeMenu = route.menu
  const isWorkshopDetail = activeMenu === "workshop" && (!!route.episodeId || inWorkshopDetail)

  function handleMenuClick(key: string) {
    navigate(director2ProjectPath(projectId, key))
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

  function onAssetsTransferred() {
    assetsPaneRef.current?.fetchAssets()
  }

  function onEpisodesTransferred() {
    workshopPaneRef.current?.fetchEpisodes()
  }

  return (
    <MediaPreviewProvider>
      <div className="project-detail-layout">
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
              <span>全部项目</span>
            </a>
            <div className="divider" />
            <div className="project-info">
              <h1 className="project-title">{project?.name || "加载中..."}</h1>
              <span className="project-badge">进行中</span>
            </div>
          </div>

          <div className="topbar-right">
            <Select
              className="project-skill-pack-select"
              size="small"
              aria-label="制作配方"
              popupMatchSelectWidth={false}
              value={selectValueForPackId(projectBoundSkillPackId(project))}
              options={skillPackSelectOptions(skillPacks)}
              loading={savingPack}
              disabled={aiBusy || savingPack || skillPacks.length === 0}
              onChange={(value) => { void changeSkillPack(String(value)) }}
            />
            <DirectorCreationModeSwitch
              value={creationMode}
              disabled={aiBusy}
              onChange={(value) => changeCreationMode(value as Director2CreationMode)}
            />
            <span className="project-id-tag">{project?.id ?? projectId}</span>
          </div>
        </div>
      </header>

      {/* 主体区域：左侧菜单 + 右侧工作区 */}
      <div className="project-main-body">
        {/* 左侧 4 个菜单导航 */}
        <aside className={`project-sidebar${creationMode === "agent" ? " is-hidden" : ""}`}>
          <div className="menu-list">
            {MENU_ITEMS.map(({ key, label, Icon }) => (
              <div
                key={key}
                className={`sidebar-menu-item${activeMenu === key ? " active" : ""}`}
                onClick={() => handleMenuClick(key)}
              >
                <Icon size={18} className="menu-icon" />
                <span className="menu-text">{label}</span>
                {activeMenu === key && <div className="active-indicator" />}
              </div>
            ))}
          </div>
        </aside>

        {/* 右侧子模块内容区 */}
        <section className={`project-content-pane${isWorkshopDetail ? " is-workshop-detail" : ""}`}>
          {creationMode === "agent" && (
            <div key="ai" className="d2-fade">
              <Director2AiStudioPane
                csrfToken={csrfToken}
                projectId={projectId}
                onBusyChange={setAiBusy}
                onNavigate={(menu) => {
                  changeCreationMode("manual")
                  handleMenuClick(menu)
                }}
              />
            </div>
          )}
          {creationMode === "manual" && activeMenu === "content" && (
            <div key="content" className="d2-fade">
              <ContentLibraryPane
                csrfToken={csrfToken}
                projectId={projectId}
                onAssetsTransferred={onAssetsTransferred}
                onEpisodesTransferred={onEpisodesTransferred}
              />
            </div>
          )}
          {creationMode === "manual" && activeMenu === "assets" && (
            <div key="assets" className="d2-fade">
              <AssetsLibraryPane ref={assetsPaneRef} csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
          {creationMode === "manual" && activeMenu === "workshop" && (
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
          {creationMode === "manual" && activeMenu === "jobs" && (
            <div key="jobs" className="d2-fade">
              <JobsCenterPane csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
        </section>
      </div>
      </div>
    </MediaPreviewProvider>
  )
}
