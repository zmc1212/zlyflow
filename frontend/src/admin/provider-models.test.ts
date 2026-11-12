import { describe, expect, it } from "vitest"
import { filterSearchOptions } from "../search-match"
import {
  buildModelOptions,
  filterModelOptions,
  modelPriceLabel,
  providerPresetFor,
  resolveModelFree,
  sameProviderEndpoint,
} from "./provider-models"
import type { OfficialProviderPreset } from "./provider-models"

// 截图里的真实目录：全部“价格未知”。
const catalog = [
  "antdigital/Ling-3.1-flash",
  "cmaas-glm-5.3",
  "cmaas-qwen3.8-flash",
  "deepseek-r1-distill-llama-70b",
  "deepseek-r1-distill-qwen-1.5b",
  "deepseek-v4-flash-0731",
  "deepseek-v4-pro",
  "deepseek-v4-pro-0813",
].map(id => ({ id, label: `${id} · 价格未知`, free: null }))

const modelOptions = buildModelOptions("https://relay.example/v1", "deepseek-v4-pro", catalog, undefined, [])

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

  it("lists everything in original order while the keyword is empty", () => {
    expect(filterSearchOptions(modelOptions, "")).toEqual(modelOptions)
    expect(filterSearchOptions(modelOptions, "   ")).toEqual(modelOptions)
  })

  it("narrows the list as soon as a keyword is typed", () => {
    // 回归：旧的“输入恰好等于某个选项就全部放行”逻辑会让任何输入都不过滤。
    const typing = buildModelOptions("https://relay.example/v1", "3.7", catalog, undefined, [])
    const filtered = filterSearchOptions(typing, "3.7")
    expect(filtered.map(row => row.value)).toEqual(["3.7"])
  })

  it("keeps one disabled hint row instead of collapsing the model dropdown", () => {
    expect(filterModelOptions(modelOptions, "not-a-model")).toEqual([
      { value: "__no-model-match__not-a-model", label: "无匹配模型，继续输入或用「not-a-model」保存", disabled: true, hint: true },
    ])
    expect(filterModelOptions(modelOptions, "glm53").map(row => row.value)).toEqual(["cmaas-glm-5.3"])
  })

  it("maps the internai discovery preset to chat and vision defaults", () => {
    const internai: OfficialProviderPreset = {
      key: "internai", label: "书生·端砚（上海AI实验室）", base_url: "https://discovery-api.intern-ai.org.cn/v1",
      api_key_url: "https://discovery.intern-ai.org.cn",
      pricing_url: "https://discovery.intern-ai.org.cn", pricing_verified_at: "2026-11-01",
      chat_models: [
        { id: "intern-s2", label: "书生-S2（限时 0 墨点）", free: true },
        { id: "deepseek-v4-flash-0731", label: "DeepSeek-V4-Flash-0731（按墨点）", free: false },
      ],
      vision_models: [{ id: "deepseek-v4-flash-vision", label: "DeepSeek-V4-Flash-Vision（按墨点，可看图）", free: false }],
    }
    expect(providerPresetFor(internai, "chat").model).toBe("intern-s2")
    expect(providerPresetFor(internai, "vision").model).toBe("deepseek-v4-flash-vision")
    const options = buildModelOptions(internai.base_url, "intern-s2", [], providerPresetFor(internai, "chat"), [internai])
    expect(options).toEqual([
      { value: "intern-s2", label: "书生-S2（限时 0 墨点） · 免费" },
      { value: "deepseek-v4-flash-0731", label: "DeepSeek-V4-Flash-0731（按墨点） · 付费" },
    ])
    // 中转地址不得借用端砚官方免费标记。
    expect(resolveModelFree("https://relay.example/v1", "intern-s2", [], [internai])).toBeNull()
  })
})
