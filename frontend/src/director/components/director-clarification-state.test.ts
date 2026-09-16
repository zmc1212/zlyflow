import { describe, expect, it } from "vitest"
import {
  commitClarification,
  completeClarifications,
  emptyClarificationState,
  moveClarification,
  selectClarificationOption,
  skipClarification,
  writeCustomClarification,
} from "./director-clarification-state"

const QUESTIONS = [
  { id: "tone", question: "主角类型？", options: [{ label: "成长型", value: "成长型" }] },
  { id: "ending", question: "结局方向？", options: [{ label: "圆满", value: "圆满" }] },
]

describe("director clarification state", () => {
  it("keeps preset selection and custom input independent", () => {
    const selected = selectClarificationOption(writeCustomClarification(emptyClarificationState(), "自己写"), "成长型")
    expect(selected).toMatchObject({ selectedOption: "成长型", customValue: "" })
    expect(writeCustomClarification(selected, "现实主义")).toMatchObject({ selectedOption: null, customValue: "现实主义" })
  })

  it("stores the option label when it differs from the agent value", () => {
    const questions = [
      { id: "episode_count", question: "这部剧分多少集？", options: [{ label: "1 集 · 单集成片", value: "1" }] },
    ]
    const result = commitClarification(emptyClarificationState(), questions, "1")
    expect(result.state.answers).toEqual([
      { id: "episode_count", question: "这部剧分多少集？", answer: "1", label: "1 集 · 单集成片" },
    ])
    expect(result.completedAnswers).toEqual(result.state.answers)
  })

  it("commits a preset answer and advances to the next question", () => {
    const result = commitClarification(selectClarificationOption(emptyClarificationState(), "成长型"), QUESTIONS, "成长型")
    expect(result.state.questionIndex).toBe(1)
    expect(result.state.answers).toEqual([{ id: "tone", question: "主角类型？", answer: "成长型" }])
    expect(result.completedAnswers).toBeUndefined()
  })

  it("skips one question without writing an answer", () => {
    const result = skipClarification(emptyClarificationState(), QUESTIONS.length)
    expect(result.state.questionIndex).toBe(1)
    expect(result.state.answers).toEqual([])
  })

  it("submits existing answers when skipping all", () => {
    const answered = commitClarification(emptyClarificationState(), QUESTIONS, "成长型").state
    expect(answered.answers).toHaveLength(1)
    expect(completeClarifications(moveClarification(answered, 1))).toEqual([
      { id: "tone", question: "主角类型？", answer: "成长型" },
    ])
  })
})
