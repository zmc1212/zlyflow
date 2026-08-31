import { ConfigProvider } from "antd"
import { createContext, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from "react"
import {
  resolveThemeMode,
  studioThemes,
  THEME_META_COLORS,
  THEME_STORAGE_KEY,
  type ThemeMode,
} from "./theme"

type StudioThemeContextValue = {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  toggleMode: () => void
}

const StudioThemeContext = createContext<StudioThemeContextValue | null>(null)

function readStoredTheme(): ThemeMode {
  try {
    return resolveThemeMode(window.localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return "light"
  }
}

function applyDocumentTheme(mode: ThemeMode) {
  document.documentElement.dataset.theme = mode
  document.documentElement.style.colorScheme = mode
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (themeColor) themeColor.content = THEME_META_COLORS[mode]
}

export function StudioThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readStoredTheme)

  useLayoutEffect(() => {
    applyDocumentTheme(mode)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, mode)
    } catch {
      // Private browsing or a locked-down webview may deny localStorage.
    }
    ConfigProvider.config({
      holderRender: (holder) => <ConfigProvider theme={studioThemes[mode]}>{holder}</ConfigProvider>,
    })
  }, [mode])

  const value = useMemo<StudioThemeContextValue>(() => ({
    mode,
    setMode,
    toggleMode: () => setMode((current) => current === "light" ? "dark" : "light"),
  }), [mode])

  return (
    <StudioThemeContext.Provider value={value}>
      <ConfigProvider theme={studioThemes[mode]}>{children}</ConfigProvider>
    </StudioThemeContext.Provider>
  )
}

export function useStudioTheme(): StudioThemeContextValue {
  const context = useContext(StudioThemeContext)
  if (!context) throw new Error("useStudioTheme must be used inside StudioThemeProvider")
  return context
}
