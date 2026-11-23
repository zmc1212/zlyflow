import { describe, expect, it } from "vitest"

import { creditsForProviderPrice, providerSourceLabel } from "./provider-price"

describe("provider price conversion", () => {
  it("converts CNY per million tokens into credits with margin", () => {
    // ¥2/M × 100 积分/元 × 1.5 = 300 积分/M
    expect(creditsForProviderPrice(2, 1.5)).toBe(300)
    expect(creditsForProviderPrice(0.04, 1.5)).toBe(6)
    expect(creditsForProviderPrice(8, 1)).toBe(800)
  })

  it("rounds up fractional credits", () => {
    expect(creditsForProviderPrice(0.005, 1)).toBe(1)
    expect(creditsForProviderPrice(0.0004, 1)).toBe(1)
  })

  it("keeps free models at zero and rejects invalid input", () => {
    expect(creditsForProviderPrice(0, 2)).toBe(0)
    expect(creditsForProviderPrice(-1, 2)).toBe(0)
    expect(creditsForProviderPrice(1, 0)).toBe(0)
    expect(creditsForProviderPrice(Number.NaN, 1)).toBe(0)
  })

  it("labels price sources", () => {
    expect(providerSourceLabel("upstream")).toBe("供应商接口")
    expect(providerSourceLabel("builtin")).toBe("内置核验价目")
    expect(providerSourceLabel(null)).toBe("手工价格")
  })
})
