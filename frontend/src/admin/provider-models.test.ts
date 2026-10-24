import { describe, expect, it } from "vitest"
import { buildModelOptions, modelPriceLabel, providerPresetFor, resolveModelFree, sameProviderEndpoint } from "./provider-models"
import type { OfficialProviderPreset } from "./provider-models"

const preset: OfficialProviderPreset = {
  key: "zhipu", label: "智谱官方", base_url: "https://open.bigmodel.cn/api/paas/v4",
  api_key_url: "https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys",
  pricing_url: "https://docs.bigmodel.cn/cn/guide/start/pricing", pricing_verified_at: "2026-10-20",
  chat_models: [{ id: "glm-4.7-flash", label: "GLM-4.7-Flash", free: true }, { id: "glm-4.7", label: "GLM-4.7", free: false }],
  vision_models: [{ id: "glm-4.6v-flash", label: "GLM-4.6V-Flash", free: true }, { id: "glm-4.6v", label: "GLM-4.6V", free: false }],
}

describe("provider model selection and pricing", () => {
  it("fills purpose-specific defaults from the backend preset", () => {
    expect(providerPresetFor(preset, "chat").model).toBe("glm-4.7-flash")
    expect(providerPresetFor(preset, "vision").model).toBe("glm-4.6v-flash")
    expect(providerPresetFor(preset, "chat").baseUrl).toBe(preset.base_url)
  })

  it("keeps free and shorter paid IDs together without changing stored values", () => {
    const options = buildModelOptions(preset.base_url, "glm-4.7-flash", [], providerPresetFor(preset, "chat"), [preset])
    expect(options).toEqual([
      { value: "glm-4.7-flash", label: "GLM-4.7-Flash · 免费" },
      { value: "glm-4.7", label: "GLM-4.7 · 付费" },
    ])
  })

  it("keeps unknown manual aliases and never guesses from Flash suffixes", () => {
    const options = buildModelOptions(preset.base_url, "unknown-flash", [], providerPresetFor(preset, "chat"), [preset])
    expect(options.at(-1)).toEqual({ value: "unknown-flash", label: "unknown-flash · 价格未知" })
    expect(resolveModelFree(preset.base_url, "glm-4.7-flashx", [], [preset])).toBeNull()
  })

  it("gives explicit catalog prices priority and deduplicates by exact ID", () => {
    const catalog = [{ id: "glm-4.7-flash", label: "Account-specific price", free: false }]
    const options = buildModelOptions(preset.base_url, "glm-4.7-flash", catalog, providerPresetFor(preset, "chat"), [preset])
    expect(options.filter(row => row.value === "glm-4.7-flash")).toEqual([
      { value: "glm-4.7-flash", label: "Account-specific price · 付费" },
    ])
  })

  it("does not apply official free status to a relay or lookalike host", () => {
    for (const base of ["https://relay.example/v1", "https://open.bigmodel.cn.example/api/paas/v4", "http://open.bigmodel.cn/api/paas/v4"]) {
      expect(resolveModelFree(base, "glm-4.7-flash", [], [preset])).toBeNull()
    }
  })

  it("treats local model service prices independently of official Zhipu", () => {
    expect(resolveModelFree("http://127.0.0.1:11434/v1", "custom", [], [preset])).toBe(true)
    expect(resolveModelFree("http://[::1]:11434/v1", "custom", [], [preset])).toBe(true)
    expect(resolveModelFree("invalid", "custom", [], [preset])).toBeNull()
  })

  it("compares exact endpoints for saved-key and catalog reuse", () => {
    expect(sameProviderEndpoint(preset.base_url, preset.base_url + "/")).toBe(true)
    expect(sameProviderEndpoint(preset.base_url, preset.base_url + "/v1")).toBe(false)
    expect(sameProviderEndpoint(preset.base_url, preset.base_url + "?relay=1")).toBe(false)
    expect(sameProviderEndpoint("", "")).toBe(false)
  })

  it("always provides a readable three-state price label", () => {
    expect([true, false, null].map(modelPriceLabel)).toEqual(["免费", "付费", "价格未知"])
  })
})
