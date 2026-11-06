import { describe, expect, it } from "vitest"
import {
  applyAssetExtractionJobSnapshot,
  applyAssetExtractionStreamEvent,
  assetExtractionDescription,
  assetExtractionElapsedLabel,
  assetExtractionFinishedNotice,
  emptyAssetExtractionLiveState,
} from "./asset-extraction-live"
import type { Director2Job } from "./api"

function job(overrides: Partial<Director2Job>): Director2Job {
  return {
    id: "job-1",
    project_id: "proj-1",
    job_type: "asset_extraction",
    title: "拆解剧本资产",
    status: "running",
    progress: 35,
    result_url: null,
    error_message: null,
    payload: {},
    created_at: "2026-11-04T10:00:00Z",
    updated_at: "2026-11-04T10:00:10Z",
    ...overrides,
  }
}

describe("asset extraction live state", () => {
  it("tracks the extraction phase, message and streamed characters", () => {
    let state = emptyAssetExtractionLiveState("job-1")
    expect(state.working).toBe(true)
    state = applyAssetExtractionStreamEvent(state, {
      seq: 1,
      event: "status",
      data: { phase: "extract", message: "正在从原文确定角色、场景与道具名称", chars: 120 },
    })
    expect(state.phase).toBe("extract")
    expect(state.message).toBe("正在从原文确定角色、场景与道具名称")
    expect(state.chars).toBe(120)
    expect(state.working).toBe(true)
    state = applyAssetExtractionStreamEvent(state, {
      seq: 2,
      event: "status",
      data: { phase: "describe", message: "正在整理角色资产（共 3 项）" },
    })
    expect(state.phase).toBe("describe")
    expect(state.chars).toBe(120)
  })

  it("reports how many items were skipped when the job finishes", () => {
    const state = applyAssetExtractionStreamEvent(emptyAssetExtractionLiveState("job-1"), {
      seq: 1,
      event: "done",
      data: { status: "succeeded", document_id: "doc-1", total: 8, skipped_count: 2 },
    })
    expect(state.working).toBe(false)
    expect(state.message).toBe("已新增 8 个制作资产，2 项无法核对已跳过")
    expect(assetExtractionFinishedNotice(state)).toBe(state.message)
  })

  it("keeps a failed extraction visible with its reason", () => {
    const state = applyAssetExtractionStreamEvent(emptyAssetExtractionLiveState("job-1"), {
      seq: 1,
      event: "error",
      data: { status: "failed", message: "模型服务不可用" },
    })
    expect(state.working).toBe(false)
    expect(state.phase).toBe("failed")
    expect(state.error).toBe("模型服务不可用")
    expect(assetExtractionDescription(state, state.startedAt + 90_000)).toContain("可重试")
  })

  it("mirrors job snapshots for the polling fallback", () => {
    const running = applyAssetExtractionJobSnapshot(emptyAssetExtractionLiveState("job-1"), job({
      payload: { phase: "describe", message: "正在整理场景资产（共 2 项）", chars: 300 },
    }))
    expect(running.working).toBe(true)
    expect(running.phase).toBe("describe")
    expect(running.chars).toBe(300)

    const failed = applyAssetExtractionJobSnapshot(running, job({
      status: "failed",
      error_message: "剧本已更新，请重新加载后拆解资产",
    }))
    expect(failed.working).toBe(false)
    expect(failed.error).toBe("剧本已更新，请重新加载后拆解资产")

    const completed = applyAssetExtractionJobSnapshot(failed, job({
      status: "completed",
      payload: { total: 5, skipped_count: 1 },
    }))
    expect(completed.working).toBe(false)
    expect(completed.error).toBe("")
    expect(completed.message).toBe("已新增 5 个制作资产，1 项无法核对已跳过")
  })

  it("formats elapsed time and background hints", () => {
    expect(assetExtractionElapsedLabel(1_000, 46_000)).toBe("45 秒")
    expect(assetExtractionElapsedLabel(1_000, 126_000)).toBe("2 分 05 秒")
    const state = { ...emptyAssetExtractionLiveState("job-1"), chars: 480 }
    const description = assetExtractionDescription(state, state.startedAt + 30_000)
    expect(description).toContain("模型已接收 480 字")
    expect(description).toContain("任务会在后台继续")
  })
})
