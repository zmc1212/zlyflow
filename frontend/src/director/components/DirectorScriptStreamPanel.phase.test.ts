import { describe, expect, it } from "vitest"
import { parseStoryboardPhase } from "./DirectorScriptStreamPanel"

describe("parseStoryboardPhase", () => {
  it("parses timing phase with range, current shot and chars", () => {
    const phase = parseStoryboardPhase("正在按秒分配对白与动作 (1/2) · 第 1-5 镜 · 正在第 3 镜 - 已收 2900 字")
    expect(phase).not.toBeNull()
    expect(phase?.title).toBe("按秒分配对白与动作")
    expect(phase?.index).toBe(1)
    expect(phase?.total).toBe(2)
    expect(phase?.range).toEqual([1, 5])
    expect(phase?.currentShot).toBe(3)
    expect(phase?.chars).toBe(2900)
  })

  it("parses continuity phase with current shot", () => {
    const phase = parseStoryboardPhase("正在校验镜头衔接 (2/2) · 第 6-9 镜 · 正在第 7 镜 - 已收 1024 字")
    expect(phase?.title).toBe("校验镜头衔接")
    expect(phase?.range).toEqual([6, 9])
    expect(phase?.currentShot).toBe(7)
  })

  it("keeps legacy messages without current shot parseable", () => {
    const phase = parseStoryboardPhase("正在按秒分配对白与动作 (1/2) · 第 1-5 镜 - 已收 900 字")
    expect(phase?.currentShot).toBeUndefined()
    expect(phase?.range).toEqual([1, 5])
    expect(phase?.chars).toBe(900)
  })

  it("parses misc phases and rejects unrelated messages", () => {
    expect(parseStoryboardPhase("正在整理镜头 (1/2)")?.title).toBe("正在整理镜头")
    expect(parseStoryboardPhase("正在写分镜 (1/2) - 已收 100 字")).toBeNull()
    expect(parseStoryboardPhase(undefined)).toBeNull()
  })
})
