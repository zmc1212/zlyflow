/**
 * 导演台「资产画布」独立窗口。
 *
 * `/director/projects/:projectId/assets/canvas` 只渲染资产画布本身：项目阶段导航、
 * 全局顶栏与任务栏都不参与，画布占满整个视口，与无限画布窗口保持一致。
 * 旧的 `/director/projects/:projectId/assets?view=canvas` 仍可用（内嵌画布视图），
 * 新入口一律优先打开独立窗口，弹窗被拦截再退回当前窗口。
 */

const DIRECTOR_CANVAS_PATH = /^\/director\/projects\/[^/]+\/assets\/canvas\/?$/

export type DirectorCanvasWindowOpen = (url: string, target: string) => Window | null

/** 资产画布独立窗口的路径；可带上当前选中的资产与节点，打开后直接定位。 */
export function directorCanvasPath(
  projectId: string,
  focus: { assetId?: string | null; nodeId?: string | null } = {},
): string {
  const base = `/director/projects/${encodeURIComponent(projectId)}/assets/canvas`
  const params = new URLSearchParams()
  if (focus.assetId) params.set("asset", focus.assetId)
  if (focus.nodeId) params.set("node", focus.nodeId)
  const query = params.toString()
  return query ? `${base}?${query}` : base
}

/** 是否为资产画布独立窗口路径（可带查询串）。 */
export function isDirectorCanvasPath(pathname: string): boolean {
  return DIRECTOR_CANVAS_PATH.test(pathname.split(/[?#]/)[0] ?? "")
}

/**
 * 在独立浏览器窗口打开导演台资产画布。
 *
 * 返回 false 表示浏览器拦截了弹窗或路径不是资产画布页，
 * 调用方应在当前窗口内跳转，保证入口不会失效。
 */
export function openDirectorCanvasWindow(path: string, open: DirectorCanvasWindowOpen): boolean {
  if (!isDirectorCanvasPath(path)) return false
  const opened = open(path, "_blank")
  if (!opened) return false
  try {
    opened.focus()
  } catch {
    // 部分浏览器禁止脚本聚焦新窗口，不影响画布本身
  }
  return true
}
