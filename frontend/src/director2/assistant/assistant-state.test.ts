import { describe, expect, it } from "vitest"
import { emptySelections, isAssistantRunning, mergeAssistantEvent, type AssistantDetail } from "./api"

function detail(): AssistantDetail {
  return { session: { id: "s", status: "ready", version: 1, created_at: "now", updated_at: "now", title: "西游创作", project_id: "project-a", selections: emptySelections(), resource_snapshot: {}, active_run_id: "r", pending_question: null },
    messages: [{ id: "m", role: "assistant", status: "streaming", version: 1, created_at: "now", updated_at: "now", run_id: "r", parts: [], selections: emptySelections() }],
    artifacts: [], proposals: [], executions: [], run: { id: "r", session_id: "s", message_id: "m", cancel_requested: false, status: "running", version: 1, created_at: "now", updated_at: "now" } }
}

describe("assistant event recovery", () => {
  it("replaces cumulative text without duplicating chunks or changing project binding", () => {
    const first = mergeAssistantEvent(detail(), { index: 0, text: "先聊" }, "m")
    const second = mergeAssistantEvent(first, { index: 0, text: "先聊故事方向" }, "m")
    expect(second.messages[0].parts).toEqual([{ type: "markdown", text: "先聊故事方向" }])
    expect(second.session.project_id).toBe("project-a")
  })
  it("restores typed question snapshots and leaves unrelated messages intact", () => {
    const state = detail()
    const snapshot = mergeAssistantEvent(state, { message_id: "m", parts: [{ type: "question", question: { id: "q", title: "哪种悬疑？", type: "single", options: [{ label: "古风", value: "period" }], allow_custom: true } }] }, "m")
    expect(snapshot.messages[0].parts[0].type).toBe("question")
    expect(mergeAssistantEvent(state, { index: 0, text: "other" }, "other").messages[0].parts).toEqual([])
  })
  it("releases controls while waiting for a question and locks active runs", () => {
    expect(isAssistantRunning(detail().run)).toBe(true)
    expect(isAssistantRunning({ ...detail().run!, status: "succeeded" })).toBe(false)
    expect(isAssistantRunning(null)).toBe(false)
  })
})
