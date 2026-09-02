import { describe, expect, it } from "vitest"
import {
  PLAN_GENERATION_FAILURE,
  PLAN_GENERATION_HINT,
  PLAN_GENERATION_LABEL,
  PLAN_GENERATION_SUCCESS,
  approveBatchConfirm,
  approveBatchLabel,
  boardBatchConfirm,
  boardBatchLabel,
  muxBatchConfirm,
  muxBatchLabel,
  plateBatchConfirm,
  plateBatchLabel,
  ttsBatchConfirm,
  ttsBatchLabel,
} from "./action-copy"

/** Compile-time + runtime contract checks used by `pnpm --dir frontend build`. */
export function assertActionCopyContract(): void {
  if (PLAN_GENERATION_LABEL !== "生成创作方案") {
    throw new Error("top-bar plan action must be 生成创作方案, not the old pipeline label")
  }
  if (!PLAN_GENERATION_HINT.includes("不会生成视频")) {
    throw new Error("plan generation hint must say it does not produce video")
  }
  if (PLAN_GENERATION_SUCCESS.includes("流水线已完成") || PLAN_GENERATION_FAILURE.includes("流水线失败")) {
    throw new Error("plan generation copy must not reuse pipeline-done wording")
  }

  const plates = plateBatchConfirm("character", 4, 3)
  if (!plates.countLabel.includes("4") || !plates.costLabel.includes("3")) {
    throw new Error("plate confirm must show total and pending GRS count")
  }
  if (!plateBatchLabel("location", 2).includes("2")) {
    throw new Error("plate button must show quantity")
  }
  if (!approveBatchLabel("location", 3).includes("3")) {
    throw new Error("approve batch button must show quantity")
  }
  const approve = approveBatchConfirm("location", 5)
  if (!approve.countLabel.includes("5") || !approve.costLabel.includes("不消耗")) {
    throw new Error("approve confirm must show count and no-cost hint")
  }

  const shots = boardBatchConfirm("final", 8)
  if (!shots.countLabel.includes("8") || !shots.costLabel.includes("8")) {
    throw new Error("board confirm must show shot count and H3 cost")
  }
  if (!boardBatchLabel("preview", 5).includes("5 镜")) {
    throw new Error("board button must show N 镜")
  }

  const tts = ttsBatchConfirm(6)
  if (!tts.countLabel.includes("6") || !tts.costLabel.includes("6")) {
    throw new Error("tts confirm must show dialogue count")
  }
  if (!ttsBatchLabel(6).includes("6 条")) {
    throw new Error("tts button must show N 条")
  }

  const mux = muxBatchConfirm(3)
  if (!mux.countLabel.includes("3") || mux.costLabel.includes("H3")) {
    throw new Error("mux confirm must show shot count and must not claim another H3 submit")
  }
  if (!muxBatchLabel(3).includes("3 镜")) {
    throw new Error("mux button must show N 镜")
  }
}

describe("director action copy", () => {
  it("keeps labels and cost confirmations aligned", () => {
    expect(() => assertActionCopyContract()).not.toThrow()
  })
})
