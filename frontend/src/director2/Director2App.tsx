// AI Media Studio 顶导航 —— 复刻自 dev0914 z-admin/src/App.vue
// 差异：router-link → 工作台 react-router 跳转；全局样式收敛到 .director2-app 作用域
// （工作台自身仍有全局外壳，导演台（原导台2）以全屏工作区嵌入，视觉与原版一致）。
// 项目壳继承根级主题，只保留布局尺寸。
import { useMemo } from "react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"
import { ConfigProvider } from "antd"
import ThemeToggle from "../components/ThemeToggle"
import { Sparkles } from "lucide-react"
import Director2StudioHome from "./Director2StudioHome"
import Director2ProjectDetail from "./Director2ProjectDetail"
import { parseDirector2Path, director2HomePath } from "./paths"
import "./director2.css"

const director2AntdTheme = { token: { borderRadius: 6, controlHeight: 32, fontSize: 14 } }

export default function Director2App({ csrfToken, onExitDirector }: { csrfToken: string; onExitDirector?: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const route = useMemo(() => parseDirector2Path(location.pathname), [location.pathname])
  const leftoverRecipe = useMemo(() => {
    const segments = location.pathname.split("/").filter(Boolean)
    return segments[0] === "director" && segments.length === 2 && !["projects", "batch", "replication", "hypit"].includes(segments[1])
  }, [location.pathname])

  const isHome = route.kind === "home"

  if (leftoverRecipe) {
    return <Navigate to={director2HomePath()} replace />
  }

  // 首页（复刻旧导演台首页）不套 director2AntdTheme：
  // 旧首页样式走全局 --dh-*/--studio-* 双主题 token，antd 控件也需继承工作台全局主题，
  // 暗色主题下按钮/气泡才能正确变色；且首页不显示 AI Media Studio 顶导航（视觉对齐旧版）。
  if (route.kind === "home") {
    return (
      <div className="director2-app director2-app-home">
        <Director2StudioHome csrfToken={csrfToken} onExitDirector={onExitDirector} />
      </div>
    )
  }

  return (
    <ConfigProvider theme={director2AntdTheme}>
      <div className="director2-app app-layout">
      <header className="top-nav">
        <div className="nav-container">
          <div className="nav-left">
            <a
              className="brand-link"
              href={director2HomePath()}
              onClick={(event) => {
                event.preventDefault()
                navigate(director2HomePath())
              }}
            >
              <div className="brand-logo">
                <Sparkles size={18} />
              </div>
              <span className="brand-title">AI Media Studio</span>
            </a>

            <nav className="nav-links">
              <a
                className={`nav-item${isHome ? " active" : ""}`}
                href={director2HomePath()}
                onClick={(event) => {
                  event.preventDefault()
                  navigate(director2HomePath())
                }}
              >
                首页
              </a>
            </nav>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="app-main">
        <Director2ProjectDetail key={route.projectId} csrfToken={csrfToken} route={route} />
      </main>
      </div>
    </ConfigProvider>
  )
}
