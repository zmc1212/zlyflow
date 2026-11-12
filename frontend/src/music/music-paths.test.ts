import { describe, expect, it } from "vitest"
import { musicChatPath, parseMusicPath } from "../paths"

describe("music chat routes", () => {
  it("parses the chat deep link and ignores stray segments", () => {
    expect(parseMusicPath("/music")).toEqual({})
    expect(parseMusicPath("/music/mchat-123")).toEqual({ chatId: "mchat-123" })
    expect(parseMusicPath("/music/mchat-123/extra")).toEqual({})
    expect(parseMusicPath("/generate/video")).toEqual({})
  })

  it("builds encoded chat paths", () => {
    expect(musicChatPath()).toBe("/music")
    expect(musicChatPath(null)).toBe("/music")
    expect(musicChatPath("mchat-1")).toBe("/music/mchat-1")
    expect(musicChatPath("a/b")).toBe("/music/a%2Fb")
  })
})
