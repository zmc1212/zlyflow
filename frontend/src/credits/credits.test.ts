import { describe, expect, it } from "vitest"
import { formatCny, friendlyCreditReason, usageMetaSummary } from "./credits"

describe("formatCny", () => {
  it("保留有效小数并去掉尾随 0", () => {
    expect(formatCny(0)).toBe("¥0")
    expect(formatCny(0.01)).toBe("¥0.01")
    expect(formatCny(0.0092, 6)).toBe("¥0.0092")
    expect(formatCny(0.24, 6)).toBe("¥0.24")
    expect(formatCny(null)).toBe("—")
  })
})

describe("usageMetaSummary", () => {
  it("真实用量显示 token 与约合人民币", () => {
    const text = usageMetaSummary({
      model: "deepseek-v4-flash",
      prompt_tokens: 6000,
      completion_tokens: 800,
      total_tokens: 6800,
      cost_cny: 0.0092,
      cost_basis: "actual",
      unit_credits: 1,
    })
    expect(text).toBe("输入 6,000 · 输出 800 tokens · ≈¥0.0092")
  })

  it("估算用量带「估算」标记", () => {
    const text = usageMetaSummary({
      prompt_tokens: 120000,
      completion_tokens: 30000,
      cost_cny: 0.24,
      cost_basis: "estimated",
    })
    expect(text).toBe("输入 120,000 · 输出 30,000 tokens · ≈¥0.24（估算）")
  })

  it("缓存命中单独列出，缺少成本时仍显示 tokens", () => {
    expect(usageMetaSummary({ prompt_tokens: 6000, cached_tokens: 4000 })).toBe("输入 6,000 · 缓存 4,000 tokens")
    expect(usageMetaSummary(null)).toBe("")
  })
})

describe("friendlyCreditReason", () => {
  it("把调用类流水的内部键改写成用户可读文案", () => {
    expect(friendlyCreditReason("llm:assistant_chat 调用一次")).toBe("AI 对话（按次计费）")
    expect(friendlyCreditReason("llm:assistant_chat 按 token 结算")).toBe("AI 对话（按 token 计费）")
    expect(friendlyCreditReason("vlm:analyze_subject 调用一次")).toBe("主体识别分析（按次计费）")
    expect(friendlyCreditReason("llm:music_chat 调用一次")).toBe("音乐创作对话（按次计费）")
  })

  it("未登记的调用类型不外露内部键", () => {
    expect(friendlyCreditReason("llm:new_tool 调用一次")).toBe("AI 调用（按次计费）")
    expect(friendlyCreditReason("vlm:future 按 token 结算")).toBe("AI 调用（按 token 计费）")
    expect(friendlyCreditReason("llm:mystery")).toBe("AI 调用（按次计费）")
  })

  it("任务扣费与退款等本身可读的 reason 原样保留", () => {
    expect(friendlyCreditReason("生图 2 张 × 3 积分")).toBe("生图 2 张 × 3 积分")
    expect(friendlyCreditReason("云端视频 5 秒 · 1080P")).toBe("云端视频 5 秒 · 1080P")
    expect(friendlyCreditReason("任务创建失败，积分退回")).toBe("任务创建失败，积分退回")
    expect(friendlyCreditReason("")).toBe("")
    expect(friendlyCreditReason(null)).toBe("")
  })
})
