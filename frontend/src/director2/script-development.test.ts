import { describe, expect, it, vi } from "vitest"
import { actScriptDevelopment, scriptDevelopmentWorking, type ScriptDevelopment } from "./script-development"
import { ensureDirector2OpeningQuestions } from "./director2-stage-choices"
const { requestJson, jsonMutation } = vi.hoisted(() => ({ requestJson: vi.fn(), jsonMutation: vi.fn((_csrf, body, method) => ({ body, method })) }))
vi.mock("../api", () => ({ requestJson, jsonMutation }))

describe("script development", () => {
  it("uses duration instead of shot count for story development", () => {
    const questions = ensureDirector2OpeningQuestions([{ id: "shots_per_episode", question: "镜数", options: [], allowCustom: true }], true)
    expect(questions.map(q => q.id)).toEqual(["episode_count", "duration_seconds"])
    expect(ensureDirector2OpeningQuestions([], false).map(q => q.id)).toEqual(["episode_count", "shots_per_episode"])
  })
  it("submits the displayed revision when adopting or revising a draft", async () => {
    const job = { job_id: "job-1", revision: "displayed-revision", status: "awaiting_review", data: { phase: "script_review", message: "" } } as ScriptDevelopment
    await actScriptDevelopment("csrf", "project", "document", job, "revise", { episode_numbers: [2], feedback: "接住前集伏笔" })
    expect(jsonMutation).toHaveBeenCalledWith("csrf", { action: "revise", revision: "displayed-revision", episode_numbers: [2], feedback: "接住前集伏笔" }, "POST")
    expect(requestJson.mock.calls[0][0]).toBe("/api/projects/project/documents/document/script-developments/job-1/actions")
  })
  it("pauses at review gates and resumes polling while working", () => {
    expect(scriptDevelopmentWorking(null)).toBe(false)
    for (const status of ["queued", "running"]) expect(scriptDevelopmentWorking({ status } as ScriptDevelopment)).toBe(true)
    for (const status of ["awaiting_review", "failed", "succeeded"]) expect(scriptDevelopmentWorking({ status } as ScriptDevelopment)).toBe(false)
  })
})
