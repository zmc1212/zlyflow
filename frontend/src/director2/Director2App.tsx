// 导演台模块：项目条由 ProjectDetail 承载，避免重复顶栏。
// 局部 Provider 仅调整控件尺寸和字体，颜色与算法继承根级双主题。
import { useMemo } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { ConfigProvider } from "antd"
import Director2StudioHome from "./Director2StudioHome"
import Director2ProjectDetail from "./Director2ProjectDetail"
import ScriptDiagnosisPage from "./script-diagnosis/ScriptDiagnosisPage"
import DirectorAssistantProvider from "./assistant/DirectorAssistant"
import { parseDirector2Path, director2HomePath } from "./paths"
import "./director2.css"
import "./director-surfaces.css"

const director2AntdTheme = {
  token: {
    borderRadius: 6,
    controlHeight: 32,
    fontSize: 14,
    fontFamily: '"Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif',
  },
}

export default function Director2App({ csrfToken, onExitDirector }: { csrfToken: string; onExitDirector?: () => void }) {
  const location = useLocation()
  const route = useMemo(() => parseDirector2Path(location.pathname), [location.pathname])
  const leftoverRecipe = useMemo(() => {
    const segments = location.pathname.split("/").filter(Boolean)
    return segments[0] === "director" && segments.length === 2 && !["projects", "batch", "replication", "script-diagnosis"].includes(segments[1])
  }, [location.pathname])

  if (leftoverRecipe) {
    return <Navigate to={director2HomePath()} replace />
  }

  if (route.kind === "diagnosis") {
    return <div className="director2-app director2-app-home"><ScriptDiagnosisPage csrfToken={csrfToken} /></div>
  }

  // 首页（复刻旧导演台首页）不套 director2AntdTheme：
  // 旧首页样式走全局 --dh-*/--studio-* 双主题 token，antd 控件也需继承工作台全局主题，
  // 暗色主题下按钮/气泡才能正确变色；且首页不显示 AI Media Studio 顶导航（视觉对齐旧版）。
  if (route.kind === "home") {
    return (
      <DirectorAssistantProvider csrfToken={csrfToken} projectId={null}>
      <div className="director2-app director2-app-home">
        <Director2StudioHome csrfToken={csrfToken} onExitDirector={onExitDirector} />
      </div>
      </DirectorAssistantProvider>
    )
  }

  return (
    <DirectorAssistantProvider csrfToken={csrfToken} projectId={route.kind === "project" ? route.projectId : null} editingContext={route.kind === "project" && route.menu === "edit" ? { kind: "smart_edit", sequence_id: route.episodeId || "main" } : null}>
    <ConfigProvider theme={director2AntdTheme}>
      <div className="director2-app app-layout">
      <main className="app-main">
        <Director2ProjectDetail key={route.projectId} csrfToken={csrfToken} route={route} />
      </main>
      </div>
    </ConfigProvider>
    </DirectorAssistantProvider>
  )
}
