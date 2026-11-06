import { describe, expect, it } from "vitest"
import { PATHS, studioWorkspaceFromPath } from "./paths"
import { STUDIO_TOOLS, TOOL_CATEGORY_LABEL, TOOL_CATEGORY_ORDER, availableTools, toolFromPath, wallTools } from "./tools/tool-registry"

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
    expect(toolFromPath(PATHS.toolCharacterReplace)?.id).toBe("character-replace")
    expect(toolFromPath(PATHS.toolDigitalHuman)?.id).toBe("digital-human")
    expect(toolFromPath(PATHS.toolLipSync)?.id).toBe("lip-sync")
  })

  it("exposes the lip sync tool as available on the video group", () => {
    const tool = toolFromPath(PATHS.toolLipSync)
    expect(tool?.status).toBe("available")
    expect(tool?.cover).toBe("/tool-covers/lip-sync.jpg")
    expect(tool?.category).toBe("video")
    expect(tool?.highlight).toBeFalsy()
  })

  it("exposes the digital human tool as available on the video group", () => {
    const tool = toolFromPath(PATHS.toolDigitalHuman)
    expect(tool?.status).toBe("available")
    expect(tool?.cover).toBe("/tool-covers/digital-human.jpg")
    expect(tool?.category).toBe("video")
    expect(tool?.highlight).toBeFalsy()
  })

  it("classifies tools like the Jimeng AI-tool page groups", () => {
    // 即梦工具页分组：精选 / 视频 / 图片 / 镜头与动态。
    const categoryOf = (id: string) => STUDIO_TOOLS.find((tool) => tool.id === id)?.category
    expect(categoryOf("prompt-reverse")).toBe("featured")
    expect(categoryOf("video-upscale")).toBe("featured")
    expect(categoryOf("partial-retake")).toBe("featured")
    expect(categoryOf("smart-edit")).toBe("featured")
    expect(categoryOf("digital-human")).toBe("video")
    expect(categoryOf("lip-sync")).toBe("video")
    expect(categoryOf("keyframe-narrative")).toBe("video")
    expect(categoryOf("stem-split")).toBe("video")
    expect(categoryOf("video-extend")).toBe("video")
    expect(categoryOf("frame-video")).toBe("video")
    expect(categoryOf("smart-cover")).toBe("image")
    expect(categoryOf("motion-transfer")).toBe("camera")
    expect(categoryOf("character-replace")).toBe("camera")
    expect(categoryOf("depth-capture")).toBe("camera")
    expect(categoryOf("image-angles")).toBe("camera")
  })

  it("exposes the character swap tool as an available dedicated entry", () => {
    const tool = toolFromPath(PATHS.toolCharacterReplace)
    expect(tool?.status).toBe("available")
    expect(tool?.title).toBe("视频换人")
    expect(tool?.cover).toBe("/tool-covers/character-replace.jpg")
    expect(tool?.category).toBe("camera")
    expect(tool?.highlight).toBeFalsy()
  })

  it("exposes the action shot tool as an available dedicated entry", () => {
    const tool = toolFromPath(PATHS.toolActionShot)
    expect(tool?.status).toBe("available")
    expect(tool?.title).toBe("打斗镜头")
    expect(tool?.icon).toBe("action-shot")
    expect(tool?.cover).toBe("/tool-covers/action-shot.jpg")
    expect(tool?.category).toBe("camera")
    expect(tool?.highlight).toBeFalsy()
    expect(tool?.demo).toBeUndefined()
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
      expect(TOOL_CATEGORY_ORDER).toContain(tool.category)
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
