import { describe, expect, it } from "vitest"
import {
  creditsToYuan,
  durationBounds,
  quotePricing,
  type PricingModel,
  type PricingResolution,
} from "./pricing-model"

const liteModel: PricingModel = {
  key: "MiniMax-H3-Lite",
  label: "Lite",
  tagline: "最省",
  description: "",
  resolutions: [],
  input_image_credits: 13,
}

const lite768: PricingResolution = {
  value: "768P",
  label: "768P",
  credits_per_second: 26,
  native_price_per_second: 0.26,
  credits_5s: 130,
  credits_10s: 260,
}

const grsModel: PricingModel = {
  key: "minimax-h3",
  label: "MiniMax-H3",
  tagline: "高性价比",
  description: "",
  resolutions: [],
  input_image_credits: 0,
}

const grs768: PricingResolution = {
  value: "768p",
  label: "768p",
  credits_per_second: 7,
  native_price_per_second: 0.07,
  credits_5s: 35,
  credits_10s: 70,
}

describe("pricing quote", () => {
  it("adds input image fees beyond the free quota", () => {
    const quote = quotePricing(liteModel, lite768, 5, 7, 5)
    expect(quote.secondsCredits).toBe(130)
    expect(quote.inputImageCount).toBe(2)
    expect(quote.inputImageCredits).toBe(26)
    expect(quote.totalCredits).toBe(156)
    expect(quote.yuan).toBeCloseTo(1.56)
  })

  it("keeps references within the free quota free", () => {
    const quote = quotePricing(liteModel, lite768, 5, 5, 5)
    expect(quote.inputImageCredits).toBe(0)
    expect(quote.totalCredits).toBe(130)
  })

  it("does not charge GRS input images when the configured price is zero", () => {
    const quote = quotePricing(grsModel, grs768, 10, 9, 5)
    expect(quote.secondsCredits).toBe(70)
    expect(quote.inputImageCredits).toBe(0)
    expect(quote.totalCredits).toBe(70)
  })

  it("rounds duration and clamps negative values", () => {
    const quote = quotePricing(liteModel, lite768, 4.6, -2, 5)
    expect(quote.secondsCredits).toBe(130)
    expect(quote.inputImageCredits).toBe(0)
  })
})

describe("credits to yuan", () => {
  it("converts at the 100 credits = 1 yuan anchor", () => {
    expect(creditsToYuan(35)).toBeCloseTo(0.35)
    expect(creditsToYuan(0)).toBe(0)
  })

  it("returns zero for a non-positive or invalid anchor", () => {
    expect(creditsToYuan(50, 0)).toBe(0)
    expect(creditsToYuan(Number.NaN, 100)).toBe(0)
  })
})

describe("duration bounds", () => {
  it("limits GRS 1080p to 10 seconds and keeps 768p at 15", () => {
    expect(durationBounds("grs", "minimax-h3", "1080p")).toEqual({ min: 1, max: 10 })
    expect(durationBounds("grs", "minimax-h3", "768p")).toEqual({ min: 1, max: 15 })
  })

  it("keeps GRS Agnes 2.5 at 4-12 seconds for every resolution", () => {
    expect(durationBounds("grs-agnes", "agnes-video-2.5", "720p")).toEqual({ min: 4, max: 12 })
    expect(durationBounds("grs-agnes", "agnes-video-2.5", "2k")).toEqual({ min: 4, max: 12 })
  })

  it("keeps GRS Wan 3.0 at 2-30 seconds for every resolution", () => {
    expect(durationBounds("grs-wan", "wan-3.0", "480p")).toEqual({ min: 2, max: 30 })
    expect(durationBounds("grs-wan", "wan-3.0", "1080p")).toEqual({ min: 2, max: 30 })
  })

  it("keeps official H3-Max at 5 seconds minimum", () => {
    expect(durationBounds("minimax", "MiniMax-H3-Max", "768P")).toEqual({ min: 5, max: 15 })
    expect(durationBounds("minimax", "MiniMax-H3-Lite", "480P")).toEqual({ min: 4, max: 15 })
  })
})
