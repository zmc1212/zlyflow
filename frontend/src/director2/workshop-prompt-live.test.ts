import { describe, expect, it } from "vitest"
import { splitStreamTokens } from "./WorkshopPromptLive"
import {
  applyPromptJobSnapshot,
  applyPromptStreamEvent,
  emptyPromptLiveState,
} from "./workshop-prompt-stream"
import { shouldShowWorkshopPromptLive, workshopFailedLiveText, workshopH3StatusLabel } from "./workshop-h3-status"

describe("workshop prompt live stream", () => {
  it("keeps thinking and visible text on separate channels", () => {
    let state = emptyPromptLiveState("job-1")
    state = applyPromptStreamEvent(state, {
      seq: 1,
      event: "status",
      data: { phase: "author", message: "正在看图写稿", reset: true },
    })
    state = applyPromptStreamEvent(state, {
      seq: 2,
      event: "reasoning",
      data: { text: "先锁人物身份" },
    })
    state = applyPromptStreamEvent(state, {
      seq: 3,
      event: "delta",
      data: { text: "subject_definitions:" },
    })
    expect(state.message).toBe("正在看图写稿")
    expect(state.reasoning).toBe("先锁人物身份")
    expect(state.text).toBe("subject_definitions:")
    expect(state.working).toBe(true)
    expect(state.failed).toBe(false)
  })

  it("keeps leftover draft on error and does not report success", () => {
    let state = emptyPromptLiveState("job-1")
    state = applyPromptStreamEvent(state, {
      seq: 1,
      event: "delta",
      data: { text: "镜头目的：对峙\nsubject_definitions:" },
    })
    state = applyPromptStreamEvent(state, {
      seq: 2,
      event: "error",
      data: { status: "failed", message: "写稿未通过校验：缺 <<<ZH>>> 中文分秒稿" },
    })
    expect(state.failed).toBe(true)
    expect(state.working).toBe(false)
    expect(state.text).toContain("镜头目的")
    expect(state.message).toContain("写稿未通过校验")
    expect(workshopH3StatusLabel({
      generating: false,
      failed: true,
      editing: false,
      dirty: false,
      savedPrompt: "previous prompt",
      source: "generated",
    })).toBe("生成失败")
    expect(workshopH3StatusLabel({
      generating: false,
      failed: true,
      editing: false,
      dirty: false,
      savedPrompt: "previous prompt",
      source: "generated",
    })).not.toBe("已生成")
    expect(workshopFailedLiveText({
      liveText: state.text,
      streamText: "",
      authorEnDraft: "subject_definitions: leftover",
    })).toContain("镜头目的")
    expect(shouldShowWorkshopPromptLive({
      generating: false,
      failed: true,
      liveText: state.text,
    })).toBe(true)
  })

  it("does not let a stale job snapshot overwrite a longer live buffer", () => {
    const live = {
      ...emptyPromptLiveState("job-1"),
      reasoning: "abcdefghij",
      text: "subject_definitions:\nA long prompt.",
    }
    const next = applyPromptJobSnapshot(live, {
      stream: { reasoning: "abc", text: "subject" },
    })
    expect(next.reasoning).toBe("abcdefghij")
    expect(next.text).toBe("subject_definitions:\nA long prompt.")
  })

  it("splits streamed English words and Chinese characters for blur-in", () => {
    expect(splitStreamTokens("Hello 世界")).toEqual(["Hello", " ", "世", "界"])
  })
})
