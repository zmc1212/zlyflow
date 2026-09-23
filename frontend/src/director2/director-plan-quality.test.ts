import { describe, expect, it } from "vitest"
import type { DirectorPromptPlan } from "./api"
import { directorPlanNeedsReview, directorRevisionStopMessage } from "./director-plan-quality"

describe("Director quality gates", () => {
  it("keeps historical plans compatible and blocks unaudited new drafts", () => {
    expect(directorPlanNeedsReview({} as DirectorPromptPlan)).toBe(false)
    expect(directorPlanNeedsReview({ quality_version: 1 } as DirectorPromptPlan)).toBe(true)
    expect(directorPlanNeedsReview({ quality_version: 1, quality_status: "not_reviewed", creative_review: { issues: [] } } as unknown as DirectorPromptPlan)).toBe(true)
  })
  it("distinguishes blocking violations from optional aesthetic suggestions", () => {
    const plan = { quality_version: 1, quality_status: "review_required", creative_review: { issues: [{ severity: "advisory" }] } } as unknown as DirectorPromptPlan
    expect(directorPlanNeedsReview(plan)).toBe(false)
    plan.creative_review!.issues[0].severity = "blocking"
    expect(directorPlanNeedsReview(plan)).toBe(true)
  })
  it("explains why another identical retry will not help", () => {
    expect(directorRevisionStopMessage("no_progress")).toContain("保留上一版")
    expect(directorRevisionStopMessage("planning_required")).toContain("调整分镜")
    expect(directorRevisionStopMessage("completed")).toBe("")
  })
})
