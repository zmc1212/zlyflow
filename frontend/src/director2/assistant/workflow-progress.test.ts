import { describe, expect, it } from "vitest"
import { assetDraftPrompt, buildWorkflowProgress, countWorkflowAssets, type WorkflowDocumentLike } from "./workflow-progress"

function planEpisode(source = "parser", shots = 5) {
  return {
    episode_num: 1,
    shots: Array.from({ length: shots }, (_, index) => ({ title: `镜头 ${index + 1}` })),
    shots_source: source,
  }
}

function document(overrides: Partial<WorkflowDocumentLike> & { episodes?: unknown[] } = {}): WorkflowDocumentLike {
  const { episodes, ...rest } = overrides
  return {
    id: "doc-1",
    filename: "第一集",
    input_mode: "paste",
    status: "ready",
    shot_plan_job_id: null,
    analysis: { episodes: episodes ?? [planEpisode("parser", 7)] },
    ...rest,
  }
}

function stepStates(progress: ReturnType<typeof buildWorkflowProgress>) {
  return Object.fromEntries(progress.steps.map((step) => [step.id, step.state]))
}

describe("workflow progress", () => {
  it("asks for a script when the project has no document", () => {
    const progress = buildWorkflowProgress({ documents: [], assets: [], episodes: [] })
    expect(progress.completed).toBe(0)
    expect(progress.action.kind).toBe("import-script")
    expect(stepStates(progress)).toEqual({ script: "current", assets: "pending", shots: "pending", workshop: "pending" })
  })

  it("moves to assets after a parsed script exists", () => {
    const progress = buildWorkflowProgress({ documents: [document()], assets: [], episodes: [] })
    expect(progress.completed).toBe(1)
    expect(progress.action).toMatchObject({ kind: "draft-assets", button: "生成资产设定" })
    expect(stepStates(progress)).toEqual({ script: "done", assets: "current", shots: "pending", workshop: "pending" })
    expect(progress.steps[0].detail).toBe("第 1 集 · 7 个分镜")
  })

  it("asks for shot planning once assets exist", () => {
    const progress = buildWorkflowProgress({
      documents: [document()],
      assets: [{ kind: "character" }, { kind: "character" }, { kind: "scene" }],
      episodes: [],
    })
    expect(progress.completed).toBe(2)
    expect(progress.action).toMatchObject({ kind: "plan-shots", button: "规划出片镜头", documentId: "doc-1" })
    expect(progress.steps[2].detail).toBe("第 1 集待规划")
    expect(progress.steps[1].detail).toBe("2 角色 · 1 场景")
  })

  it("shows a running plan and disables the next action while the job is active", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ shot_plan_job_id: "job-1", status: "planning" })],
      assets: [{ kind: "character" }],
      episodes: [],
    })
    expect(progress.action).toMatchObject({ kind: "planning", button: "规划中" })
    expect(progress.steps[2]).toMatchObject({ state: "current", running: true })
  })

  it("keeps planning the remaining episodes when only part of the document is planned", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ episodes: [planEpisode("llm", 4), { ...planEpisode("parser", 3), episode_num: 2 }] })],
      assets: [{ kind: "scene" }],
      episodes: [],
    })
    expect(progress.action).toMatchObject({ kind: "plan-shots", button: "继续规划剩余分集" })
    expect(progress.steps[2].detail).toBe("1/2 集已规划")
    expect(progress.completed).toBe(2)
  })

  it("syncs planned shots into an empty workshop", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ episodes: [planEpisode("llm", 6)] })],
      assets: [{ kind: "character" }],
      episodes: [],
    })
    expect(progress.completed).toBe(3)
    expect(progress.action).toMatchObject({ kind: "sync-episodes", documentId: "doc-1" })
    expect(progress.steps[2].detail).toBe("第 1 集 · 6 个出片镜头")
  })

  it("points into the first shootable episode when every stage is ready", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ episodes: [planEpisode("llm", 6)] })],
      assets: [{ kind: "character" }, { kind: "prop" }],
      episodes: [
        { id: "ep-1", episode_num: 1, title: "午夜禁地", shots_count: 3 },
        { id: "ep-2", episode_num: 2, title: "回声", shots_count: 4 },
      ],
    })
    expect(progress.completed).toBe(4)
    expect(progress.action).toMatchObject({ kind: "open-workshop", episodeId: "ep-1", episodeShots: 3, button: "分段提交 3 个镜头" })
    expect(progress.action.detail).toContain("第 1 集 · 午夜禁地")
    expect(progress.action.detail).toContain("整集出片请到剧集工坊手动操作")
    expect(progress.steps[3].detail).toBe("2 集 · 7 个分镜")
  })

  it("skips empty episodes when choosing the workshop entry", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ episodes: [planEpisode("llm", 6)] })],
      assets: [{ kind: "character" }],
      episodes: [
        { id: "ep-1", episode_num: 1, title: "空集", shots_count: 0 },
        { id: "ep-2", episode_num: 2, title: "正片", shots_count: 5 },
      ],
    })
    expect(progress.action).toMatchObject({ kind: "open-workshop", episodeId: "ep-2", episodeShots: 5, button: "分段提交 5 个镜头" })
    expect(progress.workshop.episodeId).toBe("ep-2")
    expect(progress.workshop.episodeLabel).toBe("第 2 集 · 正片")
  })

  it("falls back to plain navigation when no episode has shots", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ episodes: [planEpisode("llm", 6)] })],
      assets: [{ kind: "character" }],
      episodes: [{ id: "ep-1", episode_num: 1, title: "空集", shots_count: 0 }],
    })
    expect(progress.action).toMatchObject({ kind: "open-workshop", episodeId: "ep-1", episodeShots: 0, button: "进入第 1 集出片" })
    expect(progress.action.detail).toContain("还没有分镜")
  })

  it("still asks for planning when the workshop already has episodes", () => {
    const progress = buildWorkflowProgress({
      documents: [document()],
      assets: [{ kind: "character" }],
      episodes: [{ shots_count: 7 }],
    })
    expect(progress.action.kind).toBe("plan-shots")
    expect(stepStates(progress)).toEqual({ script: "done", assets: "done", shots: "current", workshop: "done" })
    expect(progress.completed).toBe(3)
  })

  it("sends the user to check a document that has no parsed episodes", () => {
    const progress = buildWorkflowProgress({ documents: [document({ episodes: [] })], assets: [], episodes: [] })
    expect(progress.completed).toBe(0)
    expect(progress.action.kind).toBe("check-script")
    expect(progress.steps[0]).toMatchObject({ state: "current", detail: "已导入，等待解析分集" })
  })

  it("treats AI pipeline documents as already planned", () => {
    const progress = buildWorkflowProgress({
      documents: [document({ input_mode: "ai_pipeline", episodes: [] })],
      assets: [{ kind: "character" }],
      episodes: [{ shots_count: 5 }],
    })
    expect(progress.completed).toBe(4)
    expect(progress.action.kind).toBe("open-workshop")
    expect(progress.steps[2].detail).toBe("AI 流程已生成出片镜头")
  })

  it("counts only the three asset kinds and ignores unknown entries", () => {
    expect(countWorkflowAssets([{ kind: "character" }, { kind: "scene" }, { kind: "prop" }, { kind: "other" }])).toEqual({
      character: 1,
      scene: 1,
      prop: 1,
      total: 3,
    })
  })

  it("writes the document name into the asset drafting prompt", () => {
    expect(assetDraftPrompt("第一集")).toContain("剧本《第一集》")
    expect(assetDraftPrompt("")).toContain("当前工程内容库里的剧本")
  })
})
