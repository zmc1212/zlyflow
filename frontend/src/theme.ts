import { theme, type ThemeConfig } from "antd"

export const studioTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#4d6bfe",
    colorPrimaryHover: "#6480ff",
    colorPrimaryActive: "#3d59e3",
    colorBgBase: "#f8f9fa",
    colorBgLayout: "#f8f9fa",
    colorBgContainer: "#ffffff",
    colorBgElevated: "#ffffff",
    colorFillSecondary: "#f1f3f5",
    colorText: "#171a1f",
    colorTextSecondary: "#59636f",
    colorTextTertiary: "#7c8794",
    colorTextQuaternary: "#9aa3ad",
    colorTextPlaceholder: "#9099a5",
    colorBorder: "#e6e9ed",
    colorBorderSecondary: "#edf0f2",
    colorSplit: "rgba(15, 23, 42, 0.07)",
    controlOutline: "rgba(77, 107, 254, 0.22)",
    borderRadius: 8,
    controlHeight: 40,
    boxShadowSecondary: "0 16px 36px rgba(22, 31, 44, 0.12)",
  },
  components: {
    Alert: {
      colorWarningBg: "rgba(252, 211, 77, 0.08)",
      colorWarningBorder: "rgba(252, 211, 77, 0.2)",
    },
    Button: {
      defaultBg: "#ffffff",
      defaultBorderColor: "#e6e9ed",
      defaultColor: "#2d333a",
      defaultHoverBg: "#f6f7f8",
      defaultHoverBorderColor: "#ced5dc",
      defaultHoverColor: "#171a1f",
    },
    Input: {
      activeBorderColor: "#4d6bfe",
      hoverBorderColor: "#b9c2cd",
      activeShadow: "0 0 0 2px rgba(77, 107, 254, 0.16)",
    },
    InputNumber: {
      activeBorderColor: "#4d6bfe",
      hoverBorderColor: "#b9c2cd",
      activeShadow: "0 0 0 2px rgba(77, 107, 254, 0.16)",
    },
    Select: {
      optionSelectedBg: "rgba(77, 107, 254, 0.10)",
      optionActiveBg: "#f4f6f8",
      selectorBg: "#ffffff",
    },
    Switch: {
      colorPrimary: "#4d6bfe",
      colorPrimaryHover: "#6480ff",
      colorTextQuaternary: "#b8c0c9",
    },
    Tabs: {
      itemColor: "#6d7782",
      itemHoverColor: "#4d6bfe",
      itemActiveColor: "#4d6bfe",
      itemSelectedColor: "#4d6bfe",
      inkBarColor: "#4d6bfe",
      horizontalItemGutter: 32,
    },
  },
}
