import { describe, expect, it } from "vitest"
import type { Director2AiOperation } from "./api"
import {
  DIRECTOR2_ACTIVE_AI_STATUSES,
  DIRECTOR2_OCCUPYING_AI_STATUSES,
  DIRECTOR2_PIPELINE_STAGES,
  director2AiHeadlineDetail,
  director2AwaitingStage,
  director2CheckpointHeadline,
  director2ContentStages,
  director2RailStageStatus,
  director2ReviewStepNumber,
  deriveDirector2ContentSummary,
  isDirector2AiOperationActive,
  isDirector2AiOperationOccupying,
  isDirector2AwaitingReview,
  isDirector2LastPipelineStage,
  markDirector2AiOperationCancelling,
  mergeDirector2AiStatusEvent,
  mergeDirector2StageCompletion,
} from "./director2-ai-operation-state"

function operation(overrides: Partial<Director2AiOperation> = {}): Director2AiOperation {
  return {
    id: "aiop-1",
    project_id: "project-1",
    kind: "pipeline",
    status: "running",
    progress: 35,
    current_stage: "assets",
    request: {},
    result: { completed_stages: ["script"] },
    error: null,
    cancel_requested: false,
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    ...overrides,
  }
}

describe("director2 AI operation state", () => {
  it("keeps an operation active while cancellation is being acknowledged", () => {
    const cancelling = markDirector2AiOperationCancelling(operation())
    expect(cancelling.cancel_requested).toBe(true)
    expect(cancelling.result.message).toBe("正在停止当前生成…")
    expect(isDirector2AiOperationActive(cancelling)).toBe(true)
  })

  it("merges the backend cancellation status without losing completed stages", () => {
    const cancelling = mergeDirector2AiStatusEvent(operation(), {
      cancel_requested: true,
      message: "正在停止当前生成…",
    })
    expect(cancelling.cancel_requested).toBe(true)
    expect(cancelling.result.completed_stages).toEqual(["script"])
  })

  it("becomes terminal only after the backend confirms cancellation", () => {
    const cancelled = mergeDirector2AiStatusEvent(operation({ cancel_requested: true }), {
      status: "cancelled",
    })
    expect(cancelled.status).toBe("cancelled")
    expect(isDirector2AiOperationActive(cancelled)).toBe(false)
    expect(director2AiHeadlineDetail(cancelled, undefined, "fallback")).not.toContain("正在停止")
  })

  it("keeps the stopping copy only while cancellation is still in flight", () => {
    const stopping = operation({ cancel_requested: true })
    expect(director2AiHeadlineDetail(stopping, undefined, "fallback")).toBe("正在停止当前生成，已完成的内容会保留。")
    const cancelled = operation({
      status: "cancelled",
      cancel_requested: true,
      error: "AI 生成已取消",
    })
    expect(director2AiHeadlineDetail(cancelled, undefined, "fallback")).toBe("AI 生成已取消")
  })

  it("ignores leftover recovery errors while the operation is still running", () => {
    const running = operation({
      error: "服务进程重启，AI 任务已中断，请重新提交或重试。",
      result: { completed_stages: ["script", "assets", "episodes"], message: "正在读剧本并构思 (1/3)" },
      current_stage: "storyboard",
    })
    expect(director2AiHeadlineDetail(running, undefined, "fallback")).toBe("正在读剧本并构思 (1/3)")
    expect(director2AiHeadlineDetail(running, "正在写分镜 (1/3) - 已收 12 字", "fallback")).toBe("正在写分镜 (1/3) - 已收 12 字")
  })

  it("keeps the previous live message when a status event has no copy", () => {
    const merged = mergeDirector2AiStatusEvent(
      operation({ result: { completed_stages: ["script"], message: "正在读剧本并构思 (1/3)" } }),
      { stage: "storyboard", progress: 65 },
    )
    expect(merged.result.message).toBe("正在读剧本并构思 (1/3)")
  })

  it("treats revising as active and awaiting_review as occupying but idle for the prompt bar", () => {
    expect(DIRECTOR2_PIPELINE_STAGES).toEqual(["script", "assets", "episodes", "storyboard"])
    expect(DIRECTOR2_ACTIVE_AI_STATUSES.has("revising")).toBe(true)
    expect(DIRECTOR2_ACTIVE_AI_STATUSES.has("awaiting_review")).toBe(false)
    expect(DIRECTOR2_OCCUPYING_AI_STATUSES.has("awaiting_review")).toBe(true)
    expect(DIRECTOR2_OCCUPYING_AI_STATUSES.has("revising")).toBe(true)
    expect(DIRECTOR2_OCCUPYING_AI_STATUSES.has("succeeded")).toBe(false)
    expect(isDirector2AiOperationActive(operation({ status: "revising", awaiting_stage: "script" }))).toBe(true)
    const review = operation({ status: "awaiting_review", current_stage: "script", awaiting_stage: "script" })
    expect(isDirector2AiOperationActive(review)).toBe(false)
    expect(isDirector2AiOperationOccupying(review)).toBe(true)
    expect(isDirector2AwaitingReview(review)).toBe(true)
    expect(director2AwaitingStage(review)).toBe("script")
    expect(director2AwaitingStage(operation({ status: "revising", awaiting_stage: "episodes" }))).toBe("episodes")
    expect(isDirector2LastPipelineStage("storyboard")).toBe(true)
    expect(isDirector2LastPipelineStage("episodes")).toBe(false)
    expect(isDirector2AiOperationOccupying(operation({ status: "succeeded" }))).toBe(false)
  })

  it("merges awaiting_stage from status events without dropping completed stages", () => {
    const merged = mergeDirector2AiStatusEvent(operation(), {
      status: "awaiting_review",
      awaiting_stage: "assets",
      stage: "assets",
      completed_stages: ["script"],
      message: "角色·场景·道具已生成，请确认或提出调整",
    })
    expect(merged.status).toBe("awaiting_review")
    expect(merged.awaiting_stage).toBe("assets")
    expect(merged.current_stage).toBe("assets")
    expect(merged.result.completed_stages).toEqual(["script"])
    expect(merged.result.message).toBe("角色·场景·道具已生成，请确认或提出调整")
  })

  it("titles the checkpoint headline by pipeline step number", () => {
    expect(director2ReviewStepNumber("script")).toBe(1)
    expect(director2ReviewStepNumber("storyboard")).toBe(4)
    expect(director2CheckpointHeadline(operation({
      status: "awaiting_review",
      current_stage: "episodes",
      awaiting_stage: "episodes",
    }))).toBe("第 3 步已生成，请确认")
    expect(director2CheckpointHeadline(operation({ status: "revising", awaiting_stage: "script" }))).toBe("正在按你的反馈重新规划…")
    expect(director2CheckpointHeadline(operation({
      status: "awaiting_review",
      current_stage: "storyboard",
      awaiting_stage: "storyboard",
    }))).toBe("第 4 步已生成，请确认")
    expect(director2AiHeadlineDetail(
      operation({ status: "awaiting_review", awaiting_stage: "script", result: { message: "剧本已生成，请确认或提出调整" } }),
      undefined,
      "fallback",
    )).toBe("剧本已生成，请确认或提出调整")
  })

  it("merges revise questions without dropping completed stages", () => {
    const merged = mergeDirector2AiStatusEvent(
      operation({
        status: "revising",
        current_stage: "episodes",
        awaiting_stage: "episodes",
        result: { completed_stages: ["script", "assets"] },
      }),
      {
        status: "revising",
        awaiting_stage: "episodes",
        stage: "episodes",
        questions: [{ question: "高潮落在哪一集？" }],
        completed_stages: ["script", "assets"],
      },
    )
    expect(merged.status).toBe("revising")
    expect(merged.awaiting_stage).toBe("episodes")
    expect(merged.result.completed_stages).toEqual(["script", "assets"])
    expect(merged.result.questions).toEqual([{ question: "高潮落在哪一集？" }])
  })
})

describe("director2 content stage derivation", () => {
  it("counts an empty project as having no ready stages", () => {
    const summary = deriveDirector2ContentSummary({ documents: [], assets: [], episodes: [] })
    expect(summary).toEqual({ scriptCount: 0, assetCount: 0, episodeCount: 0, shotCount: 0 })
    expect(director2ContentStages(summary)).toEqual([])
    expect(director2ContentStages(null)).toEqual([])
  })

  it("lights up stages from a manually imported script document", () => {
    const summary = deriveDirector2ContentSummary({
      documents: [{ raw_text: "第一集……", analysis: { episodes: [{ shots: [] }, { shots: [] }, { shots: [] }] } }],
      assets: [],
      episodes: [],
    })
    expect(summary).toEqual({ scriptCount: 1, assetCount: 0, episodeCount: 3, shotCount: 0 })
    expect(director2ContentStages(summary)).toEqual(["clarify", "script", "episodes"])
  })

  it("counts asset library rows and workshop shots", () => {
    const summary = deriveDirector2ContentSummary({
      documents: [{ raw_text: "剧本", analysis: null }],
      assets: [{ id: "a1" }, { id: "a2" }],
      episodes: [{ shots_count: 4 }, { shots_count: 0 }],
    })
    expect(summary).toEqual({ scriptCount: 1, assetCount: 2, episodeCount: 2, shotCount: 4 })
    expect(director2ContentStages(summary)).toEqual(["clarify", "script", "assets", "episodes", "storyboard"])
  })

  it("prefers the larger of workshop and document-parsed counts for episodes and shots", () => {
    const summary = deriveDirector2ContentSummary({
      documents: [{ raw_text: "", analysis: { episodes: [{ shots: [{}, {}] }, { shots: [{}] }] } }],
      assets: [],
      episodes: [{ shots_count: 1 }],
    })
    expect(summary.episodeCount).toBe(2)
    expect(summary.shotCount).toBe(3)
    expect(summary.scriptCount).toBe(1)
    expect(director2ContentStages(summary)).toEqual(["clarify", "script", "episodes", "storyboard"])
  })

  it("uses the pipeline record as the source of truth and ignores later content leftovers", () => {
    const merged = mergeDirector2StageCompletion(
      operation({ result: { completed_stages: ["clarify", "script"] } }),
      { scriptCount: 1, assetCount: 2, episodeCount: 3, shotCount: 8 },
    )
    expect([...merged].sort()).toEqual(["clarify", "script"])
    expect(mergeDirector2StageCompletion(null, null).size).toBe(0)
    expect([...mergeDirector2StageCompletion(null, { scriptCount: 1, assetCount: 0, episodeCount: 0, shotCount: 0 })]).toEqual([
      "clarify",
      "script",
    ])
  })

  it("does not mark clarify completed while the opening questions are being regenerated", () => {
    const reopening = operation({
      status: "revising",
      current_stage: "clarify",
      result: { completed_stages: [] },
    })
    const completed = mergeDirector2StageCompletion(reopening, {
      scriptCount: 1,
      assetCount: 2,
      episodeCount: 1,
      shotCount: 0,
    })
    expect([...completed]).toEqual([])
    expect(director2RailStageStatus("clarify", reopening, completed)).toBe("running")
    expect(director2CheckpointHeadline(reopening)).toBe("正在重新确认创作方向…")
  })

  it("keeps the awaiting stage out of the completed set so the rail can mark it for review", () => {
    const review = operation({
      status: "awaiting_review",
      current_stage: "assets",
      awaiting_stage: "assets",
      result: { completed_stages: ["clarify", "script"] },
    })
    const completed = mergeDirector2StageCompletion(review, {
      scriptCount: 1,
      assetCount: 2,
      episodeCount: 0,
      shotCount: 0,
    })
    expect([...completed].sort()).toEqual(["clarify", "script"])
    expect(director2RailStageStatus("clarify", review, completed)).toBe("completed")
    expect(director2RailStageStatus("script", review, completed)).toBe("completed")
    expect(director2RailStageStatus("assets", review, completed)).toBe("review")
    expect(director2RailStageStatus("episodes", review, completed)).toBe("pending")
    expect(director2RailStageStatus("assets", operation({
      status: "revising",
      current_stage: "assets",
      awaiting_stage: "assets",
      result: { completed_stages: ["clarify", "script"] },
    }), completed)).toBe("running")
  })

  it("marks the last pipeline step as review while keeping earlier stages completed", () => {
    const review = operation({
      status: "awaiting_review",
      current_stage: "storyboard",
      awaiting_stage: "storyboard",
      result: { completed_stages: ["clarify", "script", "assets", "episodes"] },
    })
    const completed = mergeDirector2StageCompletion(review, null)
    expect([...completed].sort()).toEqual(["assets", "clarify", "episodes", "script"])
    expect(director2RailStageStatus("episodes", review, completed)).toBe("completed")
    expect(director2RailStageStatus("storyboard", review, completed)).toBe("review")
  })
})
