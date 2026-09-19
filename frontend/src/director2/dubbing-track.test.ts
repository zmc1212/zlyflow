import { describe, expect, it } from "vitest"
import {
  formatLineDuration,
  isActiveDubbingStatus,
  lineContributesTts,
  lineKindLabel,
  lineMixLabel,
  lineStatusLabel,
  mixDirectorHint,
  parseWorkshopTab,
  speakerColor,
} from "./dubbing-track"

describe("dubbing track labels", () => {
  it("maps kinds, statuses and mix modes", () => {
    expect(lineKindLabel("spoken")).toBe("开口")
    expect(lineKindLabel("inner")).toBe("内心")
    expect(lineKindLabel("narration")).toBe("旁白")
    expect(lineStatusLabel("ready")).toBe("已就绪")
    expect(lineStatusLabel("queued")).toBe("排队")
    expect(lineMixLabel("overlay")).toBe("叠到成片")
    expect(lineMixLabel("replace")).toBe("替换片内对白")
    expect(isActiveDubbingStatus("running")).toBe(true)
    expect(isActiveDubbingStatus("ready")).toBe(false)
  })

  it("keeps speaker colors stable and formats duration", () => {
    expect(speakerColor("吴耐")).toBe(speakerColor("吴耐"))
    expect(speakerColor("沙丽丽")).not.toBe(speakerColor("吴耐"))
    expect(formatLineDuration(0)).toBe("—")
    expect(formatLineDuration(2.4)).toBe("2.4 秒")
    expect(formatLineDuration(12.2)).toBe("12 秒")
  })

  it("only mixes inner/narration overlay or replace onto the film", () => {
    expect(lineContributesTts({ kind: "spoken", mix: "overlay", status: "ready", audio_url: "https://x/a.wav" })).toBe(false)
    expect(lineContributesTts({ kind: "inner", mix: "overlay", status: "ready", audio_url: "https://x/a.wav" })).toBe(true)
    expect(lineContributesTts({ kind: "spoken", mix: "replace", status: "ready", audio_url: "https://x/a.wav" })).toBe(true)
    expect(mixDirectorHint("spoken", "overlay")).toContain("口型声")
    expect(mixDirectorHint("narration", "overlay")).toContain("叠到成片")
    expect(parseWorkshopTab("dubbing")).toBe("dubbing")
    expect(parseWorkshopTab("weird")).toBe("")
  })
})
