import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { splitStreamTokens, WorkshopPromptLive } from "./WorkshopPromptLive"
import {
  applyPromptJobSnapshot,
  applyPromptStreamEvent,
  emptyPromptLiveState,
} from "./workshop-prompt-stream"
import { isWorkshopPromptLiveForBeat, shouldShowWorkshopPromptLive, workshopFailedLiveText, workshopH3StatusLabel } from "./workshop-h3-status"

describe("workshop prompt live stream", () => {
  it("does not attach a live prompt to a different selected beat", () => {
    expect(isWorkshopPromptLiveForBeat("beat-1", "beat-2")).toBe(false)
    expect(isWorkshopPromptLiveForBeat("beat-2", "beat-2")).toBe(true)
    expect(isWorkshopPromptLiveForBeat(null, "beat-2")).toBe(false)
  })

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

  it("keeps structured Director failure metadata for local retry", () => {
    const state = applyPromptStreamEvent(emptyPromptLiveState("job-1"), {
      seq: 3,
      event: "error",
      data: {
        status: "failed",
        code: "DIRECTOR_PART_INVALID",
        stage: "part_generation",
        part_id: "part-2",
        segment_ids: ["segment-4", "segment-5"],
        attempt: 2,
        retryable: true,
        message: "Part 2 自动修复两次后仍未通过，可只重试失败部分。",
        detail: "技术校验详情",
      },
    })
    expect(state.failure).toMatchObject({
      code: "DIRECTOR_PART_INVALID",
      stage: "part_generation",
      part_id: "part-2",
      attempt: 2,
      retryable: true,
    })
    expect(state.message).not.toContain("技术校验详情")
  })

  it("shows the exact validation error in the failed live card header", () => {
    const html = renderToStaticMarkup(createElement(WorkshopPromptLive, {
      state: {
        ...emptyPromptLiveState("job-1"),
        working: false,
        failed: true,
        message: "章节“主体定义”不能为空",
      },
    }))
    expect(html).toContain("章节“主体定义”不能为空")
    expect(html).toContain("workshop-think-error")
  })

  it("keeps the Director stage visible while reasoning is streaming", () => {
    const html = renderToStaticMarkup(createElement(WorkshopPromptLive, {
      state: {
        ...emptyPromptLiveState("job-1"),
        startedAt: Date.now() - 5000,
        message: "正在生成 Director Part 1/2",
        reasoning: "检查分镜事实",
      },
      showStage: true,
    }))
    expect(html).toContain("正在生成 Director Part 1/2")
    expect(html).toContain("思考中")
  })
})
