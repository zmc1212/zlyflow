import { useStudioTheme } from "../ThemeProvider"
import type { CanvasAccount } from "./CanvasAccountMenu"
import CanvasWorkspace from "./CanvasWorkspace"

/**
 * 无限画布编辑页的独立窗口载体（路由 `/canvas/:canvasId`）。
 *
 * 即梦式全屏：画布占满整个视口，全局顶栏、左侧导航、任务栏都不参与渲染，
 * 编辑器的标题条与工具面板悬浮在画布之上。
 */
export default function CanvasEditorWindow({ csrfToken, ...account }: CanvasAccount & { csrfToken: string }) {
  const { mode } = useStudioTheme()
  return (
    <div className={`${mode === "light" ? "studio-light" : "studio-dark"} studio-canvas-shell studio-canvas-window`}>
      <main className="canvas-window-main" aria-label="无限画布">
        <CanvasWorkspace csrfToken={csrfToken} account={account} />
      </main>
    </div>
  )
}
