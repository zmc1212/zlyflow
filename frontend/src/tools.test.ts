import { describe, expect, it } from "vitest"
import { PATHS, studioWorkspaceFromPath } from "./paths"
import { STUDIO_TOOLS, TOOL_CATEGORY_LABEL, availableTools, toolFromPath, wallTools } from "./tools/tool-registry"

describe("studioWorkspaceFromPath", () => {
  it("maps /tools paths to the tools workspace", () => {
    expect(studioWorkspaceFromPath(PATHS.tools)).toBe("tools")
    expect(studioWorkspaceFromPath(PATHS.toolPromptReverse)).toBe("tools")
    expect(studioWorkspaceFromPath(`${PATHS.tools}/unknown`)).toBe("tools")
    expect(studioWorkspaceFromPath("/toolbox")).toBe("generate")
  })
})

describe("tool-registry", () => {
  it("keeps registry paths unique and aligned with PATHS", () => {
    const paths = STUDIO_TOOLS.map((tool) => tool.path)
    expect(new Set(paths).size).toBe(paths.length)
    expect(toolFromPath(PATHS.toolPromptReverse)?.id).toBe("prompt-reverse")
    expect(toolFromPath(PATHS.toolMotionTransfer)?.id).toBe("motion-transfer")
  })

  it("never routes unavailable tools", () => {
    const available = new Set(availableTools().map((tool) => tool.id))
    for (const tool of STUDIO_TOOLS) {
      const matched = toolFromPath(tool.path)
      if (tool.status !== "available") expect(matched).toBeNull()
      else expect(matched?.id && available.has(matched.id)).toBeTruthy()
    }
  })

  it("returns null for unknown tool paths", () => {
    expect(toolFromPath("/tools/not-a-tool")).toBeNull()
    expect(toolFromPath("/generate/video")).toBeNull()
  })

  it("keeps covers, categories and highlight well-formed", () => {
    for (const tool of STUDIO_TOOLS) {
      expect(tool.cover.startsWith("/tool-covers/")).toBe(true)
      expect(TOOL_CATEGORY_LABEL[tool.category]).toBeTruthy()
      if (tool.highlight) {
        expect(tool.category).toBe("featured")
      }
    }
    const highlighted = STUDIO_TOOLS.filter((tool) => tool.highlight)
    expect(highlighted).toHaveLength(2)
    expect(highlighted[0]?.id).toBe("prompt-reverse")
    expect(highlighted[0]?.status).toBe("available")
    expect(highlighted[1]?.id).toBe("motion-transfer")
    expect(highlighted[1]?.status).toBe("available")
  })

  it("orders the home wall with highlighted featured tools first", () => {
    const wall = wallTools()
    expect(wall[0]?.id).toBe("prompt-reverse")
    expect(wall[1]?.id).toBe("motion-transfer")
    expect(wall[0]?.highlight).toBe(true)
    expect(wall[1]?.highlight).toBe(true)
  })
})
