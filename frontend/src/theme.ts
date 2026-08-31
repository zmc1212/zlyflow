import { theme, type ThemeConfig } from "antd"

export type ThemeMode = "light" | "dark"

export const THEME_STORAGE_KEY = "zly-ai-video-studio.theme"

export const THEME_META_COLORS: Record<ThemeMode, string> = {
  light: "#f8f9fa",
  dark: "#0f1115",
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === "light" || value === "dark"
}

export function resolveThemeMode(value: unknown): ThemeMode {
  return isThemeMode(value) ? value : "light"
}

const lightTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#435ce8",
    colorPrimaryHover: "#526bf2",
    colorPrimaryActive: "#344bcf",
    colorLink: "#435ce8",
    colorLinkHover: "#526bf2",
    colorBgBase: "#f8f9fa",
    colorBgLayout: "#f8f9fa",
    colorBgContainer: "#ffffff",
    colorBgElevated: "#ffffff",
    colorFillSecondary: "#f1f3f5",
    colorText: "#171a1f",
    colorTextSecondary: "#59636f",
    colorTextTertiary: "#7c8794",
    colorTextQuaternary: "#9aa3ad",
    colorTextPlaceholder: "#7c8794",
    colorBorder: "#e1e5ea",
    colorBorderSecondary: "#e9edf1",
    colorSplit: "rgba(15, 23, 42, 0.08)",
    controlOutline: "rgba(67, 92, 232, 0.22)",
    borderRadius: 8,
    controlHeight: 40,
    boxShadowSecondary: "0 16px 36px rgba(22, 31, 44, 0.12)",
  },
  components: {
    Alert: {
      colorWarningBg: "rgba(245, 158, 11, 0.08)",
      colorWarningBorder: "rgba(245, 158, 11, 0.24)",
    },
    Button: {
      defaultBg: "#ffffff",
      defaultBorderColor: "#e1e5ea",
      defaultColor: "#2d333a",
      defaultHoverBg: "#f6f7f8",
      defaultHoverBorderColor: "#c9d1da",
      defaultHoverColor: "#171a1f",
    },
    Input: {
      activeBorderColor: "#435ce8",
      hoverBorderColor: "#b9c2cd",
      activeShadow: "0 0 0 2px rgba(67, 92, 232, 0.16)",
    },
    InputNumber: {
      activeBorderColor: "#435ce8",
      hoverBorderColor: "#b9c2cd",
      activeShadow: "0 0 0 2px rgba(67, 92, 232, 0.16)",
    },
    Select: {
      optionSelectedBg: "rgba(67, 92, 232, 0.10)",
      optionActiveBg: "#f4f6f8",
      selectorBg: "#ffffff",
    },
    Switch: {
      colorPrimary: "#435ce8",
      colorPrimaryHover: "#526bf2",
      colorTextQuaternary: "#aeb7c1",
    },
    Tabs: {
      itemColor: "#65707c",
      itemHoverColor: "#435ce8",
      itemActiveColor: "#435ce8",
      itemSelectedColor: "#435ce8",
      inkBarColor: "#435ce8",
      horizontalItemGutter: 32,
    },
  },
}

const darkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: "#5b65e6",
    colorPrimaryHover: "#6974ef",
    colorPrimaryActive: "#4c56cf",
    colorLink: "#9aa8ff",
    colorLinkHover: "#b0baff",
    colorBgBase: "#0f1115",
    colorBgLayout: "#0f1115",
    colorBgContainer: "#171a20",
    colorBgElevated: "#1e2229",
    colorFillSecondary: "#252a33",
    colorFillTertiary: "#20252d",
    colorText: "#f3f5f7",
    colorTextSecondary: "#c0c7d0",
    colorTextTertiary: "#9ba5b1",
    colorTextQuaternary: "#737e8a",
    colorTextPlaceholder: "#929ca8",
    colorBorder: "#343b46",
    colorBorderSecondary: "#2a3039",
    colorSplit: "rgba(255, 255, 255, 0.10)",
    controlOutline: "rgba(154, 168, 255, 0.28)",
    borderRadius: 8,
    controlHeight: 40,
    boxShadowSecondary: "0 18px 46px rgba(0, 0, 0, 0.42)",
  },
  components: {
    Alert: {
      colorWarningBg: "rgba(245, 158, 11, 0.12)",
      colorWarningBorder: "rgba(251, 191, 36, 0.30)",
    },
    Button: {
      defaultBg: "#1e2229",
      defaultBorderColor: "#343b46",
      defaultColor: "#e8ebef",
      defaultHoverBg: "#252a33",
      defaultHoverBorderColor: "#4a5361",
      defaultHoverColor: "#ffffff",
    },
    Input: {
      activeBorderColor: "#7f8df6",
      hoverBorderColor: "#4a5361",
      activeShadow: "0 0 0 2px rgba(127, 141, 246, 0.20)",
    },
    InputNumber: {
      activeBorderColor: "#7f8df6",
      hoverBorderColor: "#4a5361",
      activeShadow: "0 0 0 2px rgba(127, 141, 246, 0.20)",
    },
    Select: {
      optionSelectedBg: "rgba(127, 141, 246, 0.18)",
      optionActiveBg: "#252a33",
      selectorBg: "#1e2229",
    },
    Switch: {
      colorPrimary: "#5b65e6",
      colorPrimaryHover: "#6974ef",
      colorTextQuaternary: "#5b6572",
    },
    Tabs: {
      itemColor: "#9ba5b1",
      itemHoverColor: "#b0baff",
      itemActiveColor: "#9aa8ff",
      itemSelectedColor: "#9aa8ff",
      inkBarColor: "#8797ff",
      horizontalItemGutter: 32,
    },
  },
}

export const studioThemes: Record<ThemeMode, ThemeConfig> = {
  light: lightTheme,
  dark: darkTheme,
}
