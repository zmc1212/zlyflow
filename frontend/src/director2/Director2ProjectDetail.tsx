// 项目详情壳：顶部项目条 + 左侧 4 菜单 + 右侧面板 —— 逐行复刻自 dev0914 ProjectDetailView.vue
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { message } from "antd"
import { BookOpen, Boxes, ChevronLeft, Film, ListChecks } from "lucide-react"
import { getProject, director2ErrorDetail } from "./api"
import ContentLibraryPane from "./panes/ContentLibraryPane"
import AssetsLibraryPane from "./panes/AssetsLibraryPane"
import EpisodeWorkshopPane from "./panes/EpisodeWorkshopPane"
import JobsCenterPane from "./panes/JobsCenterPane"
import { director2ProjectPath, director2HomePath, type Director2Route } from "./paths"
import "./project-detail.css"

const MENU_ITEMS = [
  { key: "content", label: "内容库", Icon: BookOpen },
  { key: "assets", label: "资产库", Icon: Boxes },
  { key: "workshop", label: "剧集工坊", Icon: Film },
  { key: "jobs", label: "全部任务", Icon: ListChecks },
] as const

interface ProjectInfo {
  id: string
  name: string
}

export default function Director2ProjectDetail({
  csrfToken,
  route,
}: {
  csrfToken: string
  route: Extract<Director2Route, { kind: "project" }>
}) {
  const navigate = useNavigate()
  const projectId = route.projectId

  const [project, setProject] = useState<ProjectInfo | null>(null)
  // 剧集工坊分集详情模式判断（全屏工作台布局，去除外层多余滚动条）
  const [inWorkshopDetail, setInWorkshopDetail] = useState(false)

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

  function onAssetsTransferred() {
    assetsPaneRef.current?.fetchAssets()
  }

  function onEpisodesTransferred() {
    workshopPaneRef.current?.fetchEpisodes()
  }

  return (
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
            <span className="project-id-tag">{project?.id ?? projectId}</span>
          </div>
        </div>
      </header>

      {/* 主体区域：左侧菜单 + 右侧工作区 */}
      <div className="project-main-body">
        {/* 左侧 4 个菜单导航 */}
        <aside className="project-sidebar">
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
          {activeMenu === "content" && (
            <div key="content" className="d2-fade">
              <ContentLibraryPane
                csrfToken={csrfToken}
                projectId={projectId}
                onAssetsTransferred={onAssetsTransferred}
                onEpisodesTransferred={onEpisodesTransferred}
              />
            </div>
          )}
          {activeMenu === "assets" && (
            <div key="assets" className="d2-fade">
              <AssetsLibraryPane ref={assetsPaneRef} csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
          {activeMenu === "workshop" && (
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
          {activeMenu === "jobs" && (
            <div key="jobs" className="d2-fade">
              <JobsCenterPane csrfToken={csrfToken} projectId={projectId} />
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
