import { ConfigProvider } from "antd"
import { Navigate, useParams } from "react-router-dom"
import { useStudioTheme } from "../ThemeProvider"
import { director2HomePath } from "./paths"
import { director2FlowTheme } from "./director2-theme"
import ProjectFlowShell from "./ProjectFlowShell"
import "./director2.css"
import "./director-surfaces.css"
import "./director-canvas-window.css"

/**
 * 导演台资产画布的独立窗口载体（路由 `/director/projects/:projectId/assets/canvas`）。
 *
 * 只渲染项目壳里的资产画布：阶段导航栏、全局顶栏与任务栏都不参与，
 * 画布占满整个视口；项目名、资产数据、自动保存与「进入分镜」沿用项目壳的实现。
 */
export default function DirectorCanvasWindow({ csrfToken }: { csrfToken: string }) {
  const { projectId } = useParams<{ projectId: string }>()
  const { mode } = useStudioTheme()
  if (!projectId) return <Navigate to={director2HomePath()} replace />
  return (
    <div className={`${mode === "light" ? "studio-light" : "studio-dark"} studio-project-shell director-canvas-window`}>
      <ConfigProvider theme={director2FlowTheme(mode)}>
        <div className="director2-app app-layout">
          <main className="app-main">
            <ProjectFlowShell
              key={projectId}
              csrfToken={csrfToken}
              canvasWindow
              route={{ kind: "project", projectId, menu: "assets", episodeId: null }}
            />
          </main>
        </div>
      </ConfigProvider>
    </div>
  )
}
