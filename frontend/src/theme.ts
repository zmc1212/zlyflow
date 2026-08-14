import { theme, type ThemeConfig } from "antd"

export const studioTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: "#7655ff",
    colorPrimaryHover: "#8b70ff",
    colorPrimaryActive: "#6542ed",
    colorBgBase: "#17181e",
    colorBgLayout: "#17181e",
    colorBgContainer: "#202127",
    colorBgElevated: "#18191d",
    colorFillSecondary: "#29292f",
    colorText: "#f5f5f7",
    colorTextSecondary: "#c9c9d1",
    colorTextTertiary: "#9898a2",
    colorTextQuaternary: "#777781",
    colorTextPlaceholder: "#85858f",
    colorBorder: "#37373b",
    colorBorderSecondary: "#2d2e34",
    colorSplit: "rgba(255, 255, 255, 0.08)",
    controlOutline: "rgba(112, 71, 255, 0.45)",
    borderRadius: 8,
    controlHeight: 40,
    boxShadowSecondary: "0 20px 48px rgba(0, 0, 0, 0.42)",
  },
  components: {
    Alert: {
      colorWarningBg: "rgba(252, 211, 77, 0.08)",
      colorWarningBorder: "rgba(252, 211, 77, 0.2)",
    },
    Button: {
      defaultBg: "#202127",
      defaultBorderColor: "#37373b",
      defaultColor: "#d8d8df",
      defaultHoverBg: "#292a32",
      defaultHoverBorderColor: "#5c526f",
      defaultHoverColor: "#f5f5f7",
    },
    Input: {
      activeBorderColor: "#805fff",
      hoverBorderColor: "#53535c",
      activeShadow: "0 0 0 2px rgba(112, 71, 255, 0.22)",
    },
    InputNumber: {
      activeBorderColor: "#805fff",
      hoverBorderColor: "#53535c",
      activeShadow: "0 0 0 2px rgba(112, 71, 255, 0.22)",
    },
    Select: {
      optionSelectedBg: "rgba(112, 71, 255, 0.22)",
      optionActiveBg: "rgba(255, 255, 255, 0.08)",
      selectorBg: "#202127",
    },
    Switch: {
      colorPrimary: "#7655ff",
      colorPrimaryHover: "#8b70ff",
      colorTextQuaternary: "#54545c",
    },
    Tabs: {
      itemColor: "#9b9ba5",
      itemHoverColor: "#d8d0ff",
      itemActiveColor: "#a996ff",
      itemSelectedColor: "#a996ff",
      inkBarColor: "#7047f6",
      horizontalItemGutter: 32,
    },
  },
}
