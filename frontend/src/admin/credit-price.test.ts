import { describe, expect, it } from "vitest"
import { previewCallCost } from "./credit-price"

const deepseek = {
  input_per_mtok: 1,
  cached_input_per_mtok: 0.02,
  output_per_mtok: 4,
  assumed_input_tokens: 6000,
  assumed_cached_tokens: 0,
  assumed_output_tokens: 800,
  provider_coefficient: 1,
}

describe("previewCallCost", () => {
  it("按输入/输出 token 单价计算单次成本与覆盖率", () => {
    const preview = previewCallCost(deepseek, 1)
    expect(preview?.costCny).toBeCloseTo(0.0092, 6)
    expect(preview?.billedCny).toBeCloseTo(0.01, 6)
    expect(preview?.coverage).toBeCloseTo(1.087, 3)
    expect(preview?.status).toBe("thin")
    expect(preview?.suggestedUnitCredits).toBe(1)
  })

  it("缓存命中按缓存价计费", () => {
    const preview = previewCallCost({ ...deepseek, assumed_cached_tokens: 4000 }, 1)
    expect(preview?.costCny).toBeCloseTo(0.00528, 6)
    expect(preview?.coverage).toBeGreaterThan(1.8)
  })

  it("低于成本时给出倒贴状态", () => {
    const preview = previewCallCost({ ...deepseek, assumed_input_tokens: 120000, assumed_output_tokens: 30000 }, 30)
    expect(preview?.costCny).toBeCloseTo(0.24, 6)
    expect(preview?.coverage).toBeCloseTo(1.25, 3)
    expect(preview?.status).toBe("healthy")
    expect(previewCallCost(deepseek, 0)?.status).toBe("below_cost")
  })

  it("没有有效 token 单价时不产生预览", () => {
    expect(previewCallCost({ ...deepseek, input_per_mtok: 0, cached_input_per_mtok: 0, output_per_mtok: 0 }, 1)).toBeNull()
  })

  it("缓存 tokens 不会超过输入 tokens", () => {
    const preview = previewCallCost({ ...deepseek, assumed_cached_tokens: 999999 }, 1)
    expect(preview?.costCny).toBeCloseTo(6000 * 0.02 / 1_000_000 + 800 * 4 / 1_000_000, 6)
  })

  it("按 token 结算按成本与加价系数给出典型积分，并按最低积分兜底", () => {
    const preview = previewCallCost(deepseek, 10, { billingMode: "per_token", billingMargin: 2, minCredits: 1 })
    expect(preview?.tokenCredits).toBe(2)
    const minimum = previewCallCost(deepseek, 10, { billingMode: "per_token", billingMargin: 1, minCredits: 50 })
    expect(minimum?.tokenCredits).toBe(50)
    expect(previewCallCost(deepseek, 10, { billingMode: "per_call" })?.tokenCredits).toBeNull()
  })
})
