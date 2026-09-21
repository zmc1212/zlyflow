import { describe, expect, it } from "vitest"
import {
  assetRowGenDisplayLabel,
  assetRowProgressPercent,
  assetRowProgressStatus,
  clearAssetRow,
  hasGeneratingAssetRow,
  hasLaterJobForAsset,
  lookBatchProgressLabel,
  markAssetRowFailed,
  markAssetRowGenerating,
  seedQueuedAssetRows,
  tickAssetRowPercent,
  tickGeneratingAssetRows,
} from "./asset-row-generation"

describe("asset row generation progress", () => {
  it("queues unique asset rows before one-click generate starts", () => {
    const rows = seedQueuedAssetRows(["scene-1", "scene-1", "scene-2", ""], "正面")
    expect(Object.keys(rows)).toEqual(["scene-1", "scene-2"])
    expect(rows["scene-1"]).toEqual({ status: "queued", label: "排队生成正面", percent: 0 })
    expect(assetRowProgressPercent(rows["scene-1"])).toBe(0)
    expect(assetRowProgressStatus(rows["scene-1"].status)).toBe("normal")
    expect(assetRowGenDisplayLabel(rows["scene-1"])).toBe("排队生成正面")
  })

  it("keeps percent when the same row continues generating the next look", () => {
    const queued = seedQueuedAssetRows(["char-1"], "设定板")
    const first = markAssetRowGenerating(queued, "char-1", "正在生成设定板 1/2 · 日常")
    first["char-1"].percent = 40
    const second = markAssetRowGenerating(first, "char-1", "正在生成设定板 2/2 · 礼服")
    expect(second["char-1"].status).toBe("generating")
    expect(second["char-1"].percent).toBe(40)
    expect(second["char-1"].label).toContain("2/2")
    expect(assetRowProgressStatus("generating")).toBe("active")
    expect(assetRowGenDisplayLabel(second["char-1"])).toBe("正在生成设定板 2/2 · 礼服 40%")
  })

  it("ticks generating rows toward 92 and leaves queued rows alone", () => {
    expect(tickAssetRowPercent(0)).toBe(8)
    expect(tickAssetRowPercent(10)).toBe(16)
    expect(tickAssetRowPercent(90)).toBe(91)
    expect(tickAssetRowPercent(92)).toBe(92)
    expect(tickAssetRowPercent(99)).toBe(92)

    const ticked = tickGeneratingAssetRows({
      a: { status: "queued", label: "排队中", percent: 0 },
      b: { status: "generating", label: "正在生成正面", percent: 12 },
      c: { status: "failed", label: "失败", percent: 100 },
    })
    expect(ticked.a.percent).toBe(0)
    expect(ticked.b.percent).toBe(18)
    expect(ticked.c.percent).toBe(100)
    expect(hasGeneratingAssetRow(ticked)).toBe(true)
  })

  it("marks failed rows and can clear a finished row", () => {
    const generating = markAssetRowGenerating({}, "scene-1", "正在生成正面")
    const failed = markAssetRowFailed(generating, "scene-1", "正面失败")
    expect(failed["scene-1"].status).toBe("failed")
    expect(assetRowProgressPercent(failed["scene-1"])).toBe(100)
    expect(assetRowProgressStatus("failed")).toBe("exception")
    expect(assetRowGenDisplayLabel(failed["scene-1"])).toBe("正面失败")
    expect(clearAssetRow(failed, "scene-1")).toEqual({})
  })

  it("labels character look batches per asset and detects remaining looks", () => {
    const jobs = [
      { ast: { id: "char-a" }, ident: { name: "日常" } },
      { ast: { id: "char-a" }, ident: { name: "礼服" } },
      { ast: { id: "char-b" }, ident: { name: "校服" } },
    ]
    expect(lookBatchProgressLabel(jobs, 0)).toBe("正在生成设定板 1/2 · 日常")
    expect(lookBatchProgressLabel(jobs, 1)).toBe("正在生成设定板 2/2 · 礼服")
    expect(lookBatchProgressLabel(jobs, 2)).toBe("正在生成设定板 · 校服")
    expect(hasLaterJobForAsset(jobs, 0, "char-a")).toBe(true)
    expect(hasLaterJobForAsset(jobs, 1, "char-a")).toBe(false)
    expect(hasLaterJobForAsset(jobs, 2, "char-b")).toBe(false)
  })
})
