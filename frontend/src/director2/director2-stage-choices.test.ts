import { describe, expect, it } from "vitest"
import type { Director2AiOperation } from "./api"
import {
  DIRECTOR2_STAGE_CHOICE_FALLBACK,
  DIRECTOR2_SHOTS_PER_EPISODE_QUESTION,
  choiceDestinationStage,
  choiceEchoLabel,
  ensureDirector2OpeningQuestions,
  normalizeStageChoices,
  stageChoiceEcho,
  stageChoiceFallbackLabel,
  stageChoicePathGroups,
  stageChoicePreviewAnswer,
} from "./director2-stage-choices"

function operation(overrides: Partial<Director2AiOperation> = {}): Director2AiOperation {
  return {
    id: "aiop-1",
    project_id: "project-1",
    kind: "pipeline",
    status: "awaiting_review",
    progress: 40,
    current_stage: "assets",
    awaiting_stage: "assets",
    request: {},
    result: { completed_stages: ["script"] },
    error: null,
    cancel_requested: false,
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
    ...overrides,
  }
}

const OPENING = [
  { id: "q1", question: "结局是主角取得最终成功，还是留下开放式悬念？", answer: "1" },
  { id: "q2", question: "故事基调是热血励志、现实写实、悬疑暗黑还是黑色幽默？", answer: "1" },
  { id: "q3", question: "主角的创业动机是追求个人梦想、解决社会问题，还是复仇/雪耻？", answer: "1" },
  { id: "episode_count", question: "这部剧分多少集？", answer: "1" },
]

const OPENING_QUESTIONS = [
  {
    id: "q1",
    question: "结局是主角取得最终成功，还是留下开放式悬念？",
    options: [
      { label: "主角最终成功", value: "1" },
      { label: "开放式悬念", value: "2" },
    ],
  },
  {
    id: "q2",
    question: "故事基调是热血励志、现实写实、悬疑暗黑还是黑色幽默？",
    options: [{ label: "热血励志", value: "1" }],
  },
  {
    id: "q3",
    question: "主角的创业动机是追求个人梦想、解决社会问题，还是复仇/雪耻？",
    options: [{ label: "追求个人梦想", value: "1" }],
  },
  {
    id: "episode_count",
    question: "这部剧分多少集？",
    options: [{ label: "1 集 · 单集成片", value: "1" }],
  },
]

describe("director2 stage choice mapping", () => {
  it("reads clarify answers from request.clarifications and prefers labels", () => {
    const echo = stageChoiceEcho(operation({
      request: {
        clarifications: [
          { id: "episode_count", question: "这部剧分多少集？", answer: "12", label: "12 集 · 完整系列" },
          { question: "结局倒向？", answer: "开放式结局" },
        ],
      },
    }), "clarify")
    expect(echo.items).toEqual([
      { id: "episode_count", question: "这部剧分多少集？", answer: "12 集 · 完整系列" },
      { question: "结局倒向？", answer: "开放式结局" },
    ])
    expect(echo.fallback).toBeNull()
    expect(stageChoicePreviewAnswer(operation({
      request: { clarifications: echo.items },
    }), "clarify")).toBe("12 集 · 完整系列")
  })

  it("maps numeric episode_count values to the Chinese option label", () => {
    const items = normalizeStageChoices([
      { id: "episode_count", question: "这部剧分多少集？", answer: "1" },
    ])
    expect(items[0]?.answer).toBe("1 集 · 单集成片")
  })

  it("resolves option labels from the saved clarify_questions snapshot", () => {
    const echo = stageChoiceEcho(operation({
      request: { clarifications: OPENING, clarify_questions: OPENING_QUESTIONS },
    }), "clarify")
    expect(echo.items.map((item) => item.answer)).toEqual([
      "主角最终成功",
      "热血励志",
      "追求个人梦想",
      "1 集 · 单集成片",
    ])
  })

  it("routes opening answers onto the stages they actually steer", () => {
    expect(choiceDestinationStage({ question: "结局是主角取得最终成功，还是留下开放式悬念？" })).toBe("script")
    expect(choiceDestinationStage({ question: "故事基调是热血励志还是黑色幽默？" })).toBe("script")
    expect(choiceDestinationStage({ question: "主角的创业动机是追求个人梦想吗？" })).toBe("assets")
    expect(choiceDestinationStage({ id: "episode_count", question: "这部剧分多少集？" })).toBe("episodes")
    expect(choiceDestinationStage({ id: "shots_per_episode", question: "每一集默认拍多少个镜头？" })).toBe("storyboard")
  })

  it("echoes inherited opening choices on later steps instead of 已采纳", () => {
    const op = operation({
      request: { clarifications: OPENING, clarify_questions: OPENING_QUESTIONS },
    })
    expect(stageChoiceEcho(op, "script").items.map((item) => item.question)).toEqual([
      "结局是主角取得最终成功，还是留下开放式悬念？",
      "故事基调是热血励志、现实写实、悬疑暗黑还是黑色幽默？",
    ])
    expect(stageChoiceEcho(op, "assets").items.map((item) => item.answer)).toEqual(["追求个人梦想"])
    expect(stageChoiceEcho(op, "episodes").items.map((item) => item.answer)).toEqual(["1 集 · 单集成片"])
    expect(stageChoiceEcho(op, "storyboard").items).toEqual([])
    expect(stageChoiceEcho(op, "script").fallback).toBeNull()
    expect(stageChoiceFallbackLabel(stageChoiceEcho(op, "storyboard"))).toBeUndefined()
  })

  it("still hangs opening questions onto later steps when old tasks only stored values", () => {
    const op = operation({ request: { clarifications: OPENING } })
    expect(stageChoiceEcho(op, "script").items).toHaveLength(2)
    expect(stageChoiceEcho(op, "assets").items).toHaveLength(1)
    expect(stageChoiceEcho(op, "episodes").items[0]?.answer).toBe("1 集 · 单集成片")
    expect(stageChoiceEcho(op, "script").fallback).toBeNull()
  })

  it("lets a later revise answer replace the inherited question", () => {
    const echo = stageChoiceEcho(operation({
      request: { clarifications: [{ question: "结局倒向？", answer: "开放式结局" }] },
      stage_clarifications: {
        script: [{ question: "结局倒向？", answer: "主角成功" }],
      },
    }), "script")
    expect(echo.items).toEqual([{ question: "结局倒向？", answer: "主角成功" }])
  })

  it("reads later stages from stage_clarifications and drops empty answers", () => {
    const echo = stageChoiceEcho(operation({
      stage_clarifications: {
        script: [
          { question: "结局倒向？", answer: "开放式结局" },
          { question: "跳过的题", answer: "  " },
        ],
      },
    }), "script")
    expect(echo.items).toEqual([{ question: "结局倒向？", answer: "开放式结局" }])
  })

  it("dedupes assets copies that repeat the same question and answer", () => {
    const echo = stageChoiceEcho(operation({
      stage_clarifications: {
        assets: [
          { agent: "characters", question: "气质？", answer: "更冷" },
          { agent: "locations", question: "气质？", answer: "更冷" },
          { agent: "props", question: "气质？", answer: "更冷" },
          { agent: "characters", id: "revise_feedback", question: "本轮调整诉求", answer: "道具再少一点" },
          { agent: "locations", id: "revise_feedback", question: "本轮调整诉求", answer: "道具再少一点" },
        ],
      },
    }), "assets")
    expect(echo.items).toEqual([
      { question: "气质？", answer: "更冷" },
      { id: "revise_feedback", question: "本轮调整诉求", answer: "道具再少一点" },
    ])
    expect(choiceEchoLabel(echo.items[0])).toBe("气质？ → 更冷")
  })

  it("keeps 本轮调整诉求 as a normal recorded choice", () => {
    const items = normalizeStageChoices([
      { question: "本轮调整诉求", answer: "高潮再往后挪一集" },
    ])
    expect(items).toEqual([{ question: "本轮调整诉求", answer: "高潮再往后挪一集" }])
  })

  it("treats an empty submitted card as skipped, and a missing store as no fallback", () => {
    expect(stageChoiceEcho(operation({ request: { clarifications: [] } }), "clarify")).toEqual({
      items: [],
      fallback: "skipped",
    })
    expect(stageChoiceFallbackLabel(stageChoiceEcho(operation({ request: { clarifications: [] } }), "clarify"))).toBe(
      DIRECTOR2_STAGE_CHOICE_FALLBACK.skipped,
    )
    expect(stageChoiceEcho(operation({ stage_clarifications: { assets: [] } }), "assets").fallback).toBe("skipped")
    expect(stageChoiceEcho(operation(), "script")).toEqual({ items: [], fallback: null })
    expect(stageChoiceFallbackLabel(stageChoiceEcho(operation(), "script"))).toBeUndefined()
  })

  it("does not throw when old tasks omit stage_clarifications", () => {
    const legacy = operation()
    delete legacy.stage_clarifications
    expect(stageChoiceEcho(legacy, "assets")).toEqual({ items: [], fallback: null })
    expect(stageChoiceEcho(null, "clarify")).toEqual({ items: [], fallback: null })
    expect(normalizeStageChoices(undefined)).toEqual([])
    expect(stageChoicePreviewAnswer(legacy, "clarify")).toBeNull()
  })

  it("groups path chips by the stage a choice steers, not by 创意确认", () => {
    const groups = stageChoicePathGroups(operation({
      request: {
        clarifications: [
          { id: "episode_count", question: "这部剧分多少集？", answer: "12", label: "12 集 · 完整系列" },
          { question: "结局倒向？", answer: "开放式结局" },
        ],
      },
      stage_clarifications: {
        script: [],
        assets: [
          { agent: "characters", question: "气质？", answer: "更冷" },
          { agent: "locations", question: "气质？", answer: "更冷" },
          { agent: "props", question: "本轮调整诉求", answer: "道具再少一点" },
        ],
      },
    }))
    expect(groups).toEqual([
      {
        stage: "script",
        items: [{ question: "结局倒向？", answer: "开放式结局" }],
      },
      {
        stage: "assets",
        items: [
          { question: "气质？", answer: "更冷" },
          { question: "本轮调整诉求", answer: "道具再少一点" },
        ],
      },
      {
        stage: "episodes",
        items: [{ id: "episode_count", question: "这部剧分多少集？", answer: "12 集 · 完整系列" }],
      },
    ])
  })

  it("leaves the path bar empty when no answers were recorded", () => {
    expect(stageChoicePathGroups(operation({ request: { clarifications: [] } }))).toEqual([])
    expect(stageChoicePathGroups(operation({ stage_clarifications: { script: [] } }))).toEqual([])
    const legacy = operation()
    delete legacy.stage_clarifications
    expect(stageChoicePathGroups(legacy)).toEqual([])
    expect(stageChoicePathGroups(null)).toEqual([])
  })

  it("pins the per-episode shot question onto director2 opening clarify", () => {
    const questions = ensureDirector2OpeningQuestions([
      { id: "q1", question: "结局如何倒向？", options: [{ label: "反转", value: "反转" }] },
      { id: "episode_count", question: "这部剧分多少集？", options: [{ label: "1 集 · 单集成片", value: "1" }] },
    ])
    expect(questions.map((item) => item.id)).toEqual(["q1", "episode_count", "shots_per_episode"])
    expect(questions.at(-1)).toMatchObject({
      id: "shots_per_episode",
      question: DIRECTOR2_SHOTS_PER_EPISODE_QUESTION.question,
    })
    expect(questions.at(-1)?.options?.find((item) => item.recommended)?.value).toBe("6")
    expect(questions.at(-1)?.why).toContain("节奏建议")
    expect(questions.at(-1)?.why).toContain("导入")
    expect(questions.at(-1)?.why).toContain("出片镜")
    expect(questions.at(-1)?.why).not.toMatch(/还会再拆|生成提示词时还会再拆/)
  })
})
