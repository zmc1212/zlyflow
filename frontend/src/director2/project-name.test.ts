import { describe, expect, it } from "vitest"
import {
  DEFAULT_DIRECTOR_PROJECT_NAME,
  isPlaceholderDirectorProjectName,
  sanitizeDirectorProjectName,
} from "./project-name"

describe("director project name", () => {
  it("treats the homepage default and unnamed prefixes as placeholders", () => {
    expect(isPlaceholderDirectorProjectName("")).toBe(true)
    expect(isPlaceholderDirectorProjectName(DEFAULT_DIRECTOR_PROJECT_NAME)).toBe(true)
    expect(isPlaceholderDirectorProjectName("未命名短剧剧本")).toBe(true)
    expect(isPlaceholderDirectorProjectName("寒门硕士穿越古代逆袭记")).toBe(false)
  })

  it("trims suffixes and caps length for the editable title", () => {
    expect(sanitizeDirectorProjectName("  花甲逆袭.md  ")).toBe("花甲逆袭")
    expect(sanitizeDirectorProjectName("甲".repeat(100))).toHaveLength(80)
  })
})
