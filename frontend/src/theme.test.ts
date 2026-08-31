import { describe, expect, it } from "vitest"
import {
  isThemeMode,
  resolveThemeMode,
  studioThemes,
  THEME_META_COLORS,
  THEME_STORAGE_KEY,
} from "./theme"

describe("studio theme contract", () => {
  it("accepts only the two supported persisted modes", () => {
    expect(isThemeMode("light")).toBe(true)
    expect(isThemeMode("dark")).toBe(true)
    expect(isThemeMode("system")).toBe(false)
    expect(isThemeMode(null)).toBe(false)
  })

  it("keeps light as the safe default for missing or invalid storage", () => {
    expect(resolveThemeMode(null)).toBe("light")
    expect(resolveThemeMode("legacy-dark")).toBe("light")
    expect(resolveThemeMode("dark")).toBe("dark")
  })

  it("provides a complete Ant Design and browser-chrome pair", () => {
    expect(THEME_STORAGE_KEY).toBe("zly-ai-video-studio.theme")
    expect(THEME_META_COLORS).toEqual({ light: "#f8f9fa", dark: "#0f1115" })
    expect(studioThemes.light.token?.colorBgBase).toBe("#f8f9fa")
    expect(studioThemes.dark.token?.colorBgBase).toBe("#0f1115")
    expect(studioThemes.light.algorithm).toBeTruthy()
    expect(studioThemes.dark.algorithm).toBeTruthy()
  })
})
