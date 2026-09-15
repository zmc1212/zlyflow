// AI Media Studio 顶导航 —— 复刻自 dev0914 z-admin/src/App.vue
// 差异：router-link → 工作台 react-router 跳转；全局样式收敛到 .director2-app 作用域
// （工作台自身仍有全局外壳，导台2 以全屏工作区嵌入，视觉与原版一致）。
// 本模块内 antd 组件恢复 antd（ant-design-vue 4 同源）默认亮色主题：
// 工作台全局 ConfigProvider 的主色/控件高度/圆角会破坏原版视觉，故在模块根部覆写。
import { useMemo } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { ConfigProvider, theme as antdTheme } from "antd"
import { Sparkles, Settings } from "lucide-react"
import Director2Home from "./Director2Home"
import Director2ProjectDetail from "./Director2ProjectDetail"
import Director2Settings from "./settings/Director2Settings"
import { parseDirector2Path, director2HomePath, director2SettingsPath } from "./paths"
import "./director2.css"

const director2AntdTheme = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: "#1677ff",
    colorInfo: "#1677ff",
    colorLink: "#1677ff",
    colorText: "rgba(0, 0, 0, 0.88)",
    colorTextSecondary: "rgba(0, 0, 0, 0.65)",
    colorTextTertiary: "rgba(0, 0, 0, 0.45)",
    colorTextQuaternary: "rgba(0, 0, 0, 0.25)",
    colorBorder: "#d9d9d9",
    colorBorderSecondary: "#f0f0f0",
    colorBgContainer: "#ffffff",
    borderRadius: 6,
    controlHeight: 32,
    fontSize: 14,
  },
}

export default function Director2App({ csrfToken }: { csrfToken: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const route = useMemo(() => parseDirector2Path(location.pathname), [location.pathname])

  const isHome = route.kind === "home"
  const isSettings = route.kind === "settings"

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

          <div className="nav-right">
            <a
              className={`settings-btn${isSettings ? " active" : ""}`}
              href={director2SettingsPath()}
              onClick={(event) => {
                event.preventDefault()
                navigate(director2SettingsPath())
              }}
            >
              <Settings size={16} />
              <span>设置</span>
            </a>
          </div>
        </div>
      </header>

      <main className="app-main">
        {route.kind === "home" ? (
          <Director2Home csrfToken={csrfToken} />
        ) : route.kind === "settings" ? (
          <Director2Settings csrfToken={csrfToken} />
        ) : (
          <Director2ProjectDetail key={route.projectId} csrfToken={csrfToken} route={route} />
        )}
      </main>
      </div>
    </ConfigProvider>
  )
}
