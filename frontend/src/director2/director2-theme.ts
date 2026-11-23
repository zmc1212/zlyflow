import type { ThemeMode } from "../theme"

/**
 * 导演台局部 antd 主题：只调整控件尺寸与字体，颜色与算法继承根级双主题。
 * 项目壳与资产画布独立窗口共用同一份，避免两处主色/按钮配色漂移。
 */
const director2AntdTheme = {
  token: {
    borderRadius: 6,
    controlHeight: 32,
    fontSize: 14,
    fontFamily: '"Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif',
  },
}

export function director2FlowTheme(mode: ThemeMode) {
  return {
    ...director2AntdTheme,
    token: { ...director2AntdTheme.token, colorPrimary: mode === "dark" ? "#8bf0d6" : "#087f68" },
    components: { Button: { primaryColor: mode === "dark" ? "#10251e" : "#ffffff" } },
  }
}
