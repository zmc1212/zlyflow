/**
 * 无限画布独立窗口。
 *
 * 编辑页 `/canvas/:canvasId` 放在独立浏览器窗口里渲染，只保留画布自己的悬浮工具条，
 * 不再为全局顶栏与左侧导航让位，从而真正占满视口（对齐即梦的无限画布）。
 */

const CANVAS_EDITOR_PATH = /^\/canvas\/[^/]+\/?$/

export type CanvasWindowOpen = (url: string, target: string) => Window | null

/** 是否为画布编辑页路径（`/canvas/:canvasId`，可带查询串）。 */
export function isCanvasEditorPath(pathname: string): boolean {
  return CANVAS_EDITOR_PATH.test(pathname.split(/[?#]/)[0] ?? "")
}

/**
 * 在独立浏览器窗口打开画布。
 *
 * 返回 false 表示浏览器拦截了弹窗或路径不是画布编辑页，
 * 调用方应在当前窗口内跳转，保证入口不会失效。
 */
export function openCanvasEditorWindow(path: string, open: CanvasWindowOpen): boolean {
  if (!isCanvasEditorPath(path)) return false
  const opened = open(path, "_blank")
  if (!opened) return false
  try {
    opened.focus()
  } catch {
    // 部分浏览器禁止脚本聚焦新窗口，不影响画布本身
  }
  return true
}

/**
 * 画布窗口的返回动作。
 *
 * 由工作台列表打开时直接关窗（回到列表所在窗口），
 * 手动输入地址或刷新后的窗口没有 opener，则在当前窗口回到画布列表。
 */
export function leaveCanvasEditor(win: Pick<Window, "opener" | "close">, fallback: () => void): void {
  if (win.opener) {
    win.close()
    return
  }
  fallback()
}
